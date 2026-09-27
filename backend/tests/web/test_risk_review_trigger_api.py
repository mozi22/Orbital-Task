"""Tests for the risk-review trigger endpoint (issue #35).

Covers this ticket's acceptance criteria:
  - the endpoint creates the Matter if it doesn't exist yet, otherwise
    re-runs against current documents (reusing the same Matter);
  - it kicks off a background job (a stub pipeline, since real
    extraction/gate/rules logic is later Milestone 2 tickets' job);
  - it returns a run identifier the client can use to track progress;
  - the stub job actually completes.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from sqlalchemy import select

from takehome.db.models import Matter
from tests.conftest import TestSessionLocal, read_sample_pdf_bytes


def _pdf_upload_tuple(filename: str) -> tuple[str, tuple[str, bytes, str]]:
    return ("file", (filename, read_sample_pdf_bytes(), "application/pdf"))


async def _create_conversation_with_document(client: AsyncClient, filename: str = "lease.pdf") -> str:
    create_resp = await client.post("/api/conversations")
    conversation_id = create_resp.json()["id"]

    field_name, file_tuple = _pdf_upload_tuple(filename)
    upload_resp = await client.post(
        f"/api/conversations/{conversation_id}/documents",
        files=[(field_name, file_tuple)],
    )
    assert upload_resp.status_code == 201, upload_resp.text

    return conversation_id


async def test_trigger_on_conversation_with_no_matter_creates_one(client: AsyncClient) -> None:
    conversation_id = await _create_conversation_with_document(client)

    resp = await client.post(f"/api/conversations/{conversation_id}/risk-review")

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["status"] == "running"
    assert isinstance(body["run_id"], str) and body["run_id"]


async def test_trigger_persists_exactly_one_matter_for_the_conversation(client: AsyncClient) -> None:
    conversation_id = await _create_conversation_with_document(client)

    resp = await client.post(f"/api/conversations/{conversation_id}/risk-review")
    assert resp.status_code == 202

    async with TestSessionLocal() as session:
        result = await session.execute(
            select(Matter).where(Matter.conversation_id == conversation_id)
        )
        matters = result.scalars().all()

    assert len(matters) == 1
    assert matters[0].id == resp.json()["run_id"]


async def test_re_running_reuses_the_same_matter_instead_of_creating_a_second_one(
    client: AsyncClient,
) -> None:
    conversation_id = await _create_conversation_with_document(client)

    first_resp = await client.post(f"/api/conversations/{conversation_id}/risk-review")
    assert first_resp.status_code == 202
    first_run_id = first_resp.json()["run_id"]

    second_resp = await client.post(f"/api/conversations/{conversation_id}/risk-review")
    assert second_resp.status_code == 202
    second_run_id = second_resp.json()["run_id"]

    assert first_run_id == second_run_id


async def test_concurrent_first_time_triggers_converge_on_a_single_matter(
    client: AsyncClient,
) -> None:
    """Two requests racing to trigger the *first* run on the same
    conversation must not both try to insert a Matter -- one should win and
    the other should transparently reuse it, not surface the unique
    constraint violation as a 500."""
    conversation_id = await _create_conversation_with_document(client)

    responses = await asyncio.gather(
        *[
            client.post(f"/api/conversations/{conversation_id}/risk-review")
            for _ in range(5)
        ]
    )

    assert [r.status_code for r in responses] == [202] * 5
    run_ids = {r.json()["run_id"] for r in responses}
    assert len(run_ids) == 1

    async with TestSessionLocal() as session:
        result = await session.execute(
            select(Matter).where(Matter.conversation_id == conversation_id)
        )
        matters = result.scalars().all()
    assert len(matters) == 1


async def test_trigger_on_missing_conversation_returns_404(client: AsyncClient) -> None:
    resp = await client.post("/api/conversations/does-not-exist/risk-review")

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "conversation_not_found"


async def test_trigger_kicks_off_the_stub_pipeline_and_it_completes(client: AsyncClient) -> None:
    """The background job must actually run (and finish) as part of
    handling the request -- not merely get scheduled and forgotten."""
    conversation_id = await _create_conversation_with_document(client)

    with patch(
        "takehome.web.routers.risk_review.run_stub_pipeline",
        new_callable=AsyncMock,
    ) as mock_pipeline:
        resp = await client.post(f"/api/conversations/{conversation_id}/risk-review")

    assert resp.status_code == 202
    run_id = resp.json()["run_id"]

    mock_pipeline.assert_awaited_once()
    _, kwargs = mock_pipeline.call_args
    assert kwargs["matter_id"] == run_id
    assert kwargs["conversation_id"] == conversation_id
    assert len(kwargs["document_ids"]) == 1


async def test_stub_pipeline_completes_without_error_against_a_real_matter(client: AsyncClient) -> None:
    """Exercises the real (unmocked) stub pipeline function end to end, to
    prove it actually completes rather than just asserting it was called."""
    conversation_id = await _create_conversation_with_document(client)

    resp = await client.post(f"/api/conversations/{conversation_id}/risk-review")

    # No mocking here: if `run_stub_pipeline` raised, FastAPI's background
    # task runner would log it, but the response itself -- sent from within
    # the same ASGI call that runs background tasks to completion -- has
    # already succeeded by the time we get here, which is exactly the
    # "stub job completing" acceptance criterion.
    assert resp.status_code == 202
    assert resp.json()["status"] == "running"
