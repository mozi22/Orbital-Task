from __future__ import annotations

import os

from httpx import AsyncClient

from takehome.services.document import get_documents_for_conversation
from tests.conftest import TestSessionLocal

SAMPLE_PDF_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "sample-docs", "title-report-lot-7.pdf"
)


def _pdf_upload_tuple(filename: str) -> tuple[str, tuple[str, bytes, str]]:
    with open(SAMPLE_PDF_PATH, "rb") as f:
        content = f.read()
    return ("file", (filename, content, "application/pdf"))


async def test_uploading_five_pdfs_one_by_one_all_succeed(client: AsyncClient) -> None:
    create_resp = await client.post("/api/conversations")
    assert create_resp.status_code == 201
    conversation_id = create_resp.json()["id"]

    for i in range(5):
        field_name, file_tuple = _pdf_upload_tuple(f"doc-{i}.pdf")
        resp = await client.post(
            f"/api/conversations/{conversation_id}/documents",
            files=[(field_name, file_tuple)],
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["filename"] == f"doc-{i}.pdf"


async def test_sixth_upload_returns_409_and_conversation_keeps_original_five(
    client: AsyncClient,
) -> None:
    create_resp = await client.post("/api/conversations")
    conversation_id = create_resp.json()["id"]

    uploaded_ids = []
    for i in range(5):
        field_name, file_tuple = _pdf_upload_tuple(f"doc-{i}.pdf")
        resp = await client.post(
            f"/api/conversations/{conversation_id}/documents",
            files=[(field_name, file_tuple)],
        )
        assert resp.status_code == 201, resp.text
        uploaded_ids.append(resp.json()["id"])

    field_name, file_tuple = _pdf_upload_tuple("doc-6.pdf")
    sixth_resp = await client.post(
        f"/api/conversations/{conversation_id}/documents",
        files=[(field_name, file_tuple)],
    )
    assert sixth_resp.status_code == 409
    assert "maximum of 5 documents" in sixth_resp.json()["detail"]

    # The conversation must still show exactly the original 5 documents.
    get_resp = await client.get(f"/api/conversations/{conversation_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["has_document"] is True

    async with TestSessionLocal() as session:
        docs = await get_documents_for_conversation(session, conversation_id)

    assert len(docs) == 5
    assert {d.id for d in docs} == set(uploaded_ids)
