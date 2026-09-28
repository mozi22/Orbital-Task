"""Tests for the risk-review progress SSE stream (issue #38).

Covers this ticket's acceptance criteria:
  - pipeline stage boundaries (classify, extract-per-document,
    gate-per-rule, rule-per-rule) emit progress events over SSE;
  - events carry enough detail to render lines like "Extracting facts from
    lease.pdf..." or "Running rule O-01: mortgage predates lease...";
  - the sequence terminates with a `done` event;
  - a full sequence of progress events for one run is covered end-to-end,
    against the real (unmocked) stub pipeline and a real Postgres database.
"""

from __future__ import annotations

import json

from httpx import AsyncClient

from tests.conftest import read_sample_pdf_bytes


def _pdf_upload_tuple(filename: str) -> tuple[str, tuple[str, bytes, str]]:
    return ("file", (filename, read_sample_pdf_bytes(), "application/pdf"))


async def _create_conversation_with_documents(
    client: AsyncClient, filenames: list[str]
) -> str:
    create_resp = await client.post("/api/conversations")
    conversation_id = create_resp.json()["id"]

    for filename in filenames:
        field_name, file_tuple = _pdf_upload_tuple(filename)
        upload_resp = await client.post(
            f"/api/conversations/{conversation_id}/documents",
            files=[(field_name, file_tuple)],
        )
        assert upload_resp.status_code == 201, upload_resp.text

    return conversation_id


async def _collect_sse_events(client: AsyncClient, url: str) -> list[dict]:
    events: list[dict] = []
    async with client.stream("GET", url) as resp:
        assert resp.status_code == 200, await resp.aread()
        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: ") :]))
    return events


async def test_full_progress_sequence_for_a_run_with_one_document(
    client: AsyncClient,
) -> None:
    """The end-to-end "one full sequence of progress events for a run"
    acceptance criterion: trigger a real run against the real stub pipeline,
    then read back its full SSE sequence and check every stage boundary
    appears, in order, ending with `done`."""
    conversation_id = await _create_conversation_with_documents(client, ["lease.pdf"])

    trigger_resp = await client.post(f"/api/conversations/{conversation_id}/risk-review")
    assert trigger_resp.status_code == 202
    run_id = trigger_resp.json()["run_id"]

    events = await _collect_sse_events(client, f"/api/matters/{run_id}/events")

    assert events[0] == {
        "type": "progress",
        "stage": "classify",
        "message": "Classifying uploaded documents...",
    }
    assert events[-1] == {"type": "done"}

    extract_events = [e for e in events if e.get("stage") == "extract"]
    assert len(extract_events) == 1
    assert extract_events[0]["message"] == "Extracting facts from lease.pdf..."
    assert extract_events[0]["document_id"]

    gate_events = [e for e in events if e.get("stage") == "gate"]
    assert [e["rule_id"] for e in gate_events] == ["G-01", "G-02", "G-04"]
    assert gate_events[0]["message"] == "Running gate check G-01: address and postcode match across all documents..."

    rule_events = [e for e in events if e.get("stage") == "rules"]
    assert [e["rule_id"] for e in rule_events] == [
        "O-01",
        "L-03",
        "E-01",
        "D-01",
        "R-03",
        "R-04",
        "E-02",
        "D-04",
        "V-01",
    ]
    assert rule_events[0]["message"] == "Running rule O-01: mortgage predates lease..."

    # classify (1) + extract (1) + gate (3) + rules (9) + done (1)
    assert len(events) == 15


async def test_emits_one_extract_event_per_uploaded_document_in_upload_order(
    client: AsyncClient,
) -> None:
    conversation_id = await _create_conversation_with_documents(
        client, ["title.pdf", "lease.pdf", "environmental.pdf"]
    )

    trigger_resp = await client.post(f"/api/conversations/{conversation_id}/risk-review")
    run_id = trigger_resp.json()["run_id"]

    events = await _collect_sse_events(client, f"/api/matters/{run_id}/events")

    extract_messages = [e["message"] for e in events if e.get("stage") == "extract"]
    assert extract_messages == [
        "Extracting facts from title.pdf...",
        "Extracting facts from lease.pdf...",
        "Extracting facts from environmental.pdf...",
    ]


async def test_subscribing_after_the_run_already_finished_still_replays_the_full_sequence(
    client: AsyncClient,
) -> None:
    """With the test's ASGI transport, `BackgroundTasks` finish running
    before the trigger POST's response is returned (see
    `test_risk_review_trigger_api.py`'s
    `test_stub_pipeline_completes_without_error_against_a_real_matter`) -- so
    by the time this test opens the SSE stream, the run has already
    completed. It must still see every event from the start, not just
    whatever hadn't been delivered yet."""
    conversation_id = await _create_conversation_with_documents(client, ["lease.pdf"])

    trigger_resp = await client.post(f"/api/conversations/{conversation_id}/risk-review")
    run_id = trigger_resp.json()["run_id"]

    events = await _collect_sse_events(client, f"/api/matters/{run_id}/events")

    assert events[0]["stage"] == "classify"
    assert events[-1] == {"type": "done"}
    assert len(events) == 15  # same shape as the single-document test above


async def test_events_for_unknown_run_id_returns_404(client: AsyncClient) -> None:
    resp = await client.get("/api/matters/does-not-exist/events")

    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "matter_not_found"


async def test_two_runs_on_different_conversations_have_independent_event_streams(
    client: AsyncClient,
) -> None:
    first_conversation_id = await _create_conversation_with_documents(client, ["lease.pdf"])
    second_conversation_id = await _create_conversation_with_documents(
        client, ["title.pdf", "environmental.pdf"]
    )

    first_run_id = (
        await client.post(f"/api/conversations/{first_conversation_id}/risk-review")
    ).json()["run_id"]
    second_run_id = (
        await client.post(f"/api/conversations/{second_conversation_id}/risk-review")
    ).json()["run_id"]

    first_events = await _collect_sse_events(client, f"/api/matters/{first_run_id}/events")
    second_events = await _collect_sse_events(client, f"/api/matters/{second_run_id}/events")

    first_extract_messages = [e["message"] for e in first_events if e.get("stage") == "extract"]
    second_extract_messages = [e["message"] for e in second_events if e.get("stage") == "extract"]

    assert first_extract_messages == ["Extracting facts from lease.pdf..."]
    assert second_extract_messages == [
        "Extracting facts from title.pdf...",
        "Extracting facts from environmental.pdf...",
    ]
