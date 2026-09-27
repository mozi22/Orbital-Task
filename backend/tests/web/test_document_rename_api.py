from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import read_sample_pdf_bytes


async def _create_conversation_with_document(client: AsyncClient) -> tuple[str, str]:
    create_resp = await client.post("/api/conversations")
    conversation_id = create_resp.json()["id"]

    upload_resp = await client.post(
        f"/api/conversations/{conversation_id}/documents",
        files=[("file", ("lease.pdf", read_sample_pdf_bytes(), "application/pdf"))],
    )
    assert upload_resp.status_code == 201, upload_resp.text
    document_id = upload_resp.json()["id"]
    return conversation_id, document_id


async def test_patch_document_updates_display_name(client: AsyncClient) -> None:
    _conversation_id, document_id = await _create_conversation_with_document(client)

    resp = await client.patch(
        f"/api/documents/{document_id}",
        json={"display_name": "Lease Agreement"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["display_name"] == "Lease Agreement"
    # The underlying filename is left untouched.
    assert resp.json()["filename"] == "lease.pdf"


async def test_patch_document_rename_reflected_on_conversation_get(client: AsyncClient) -> None:
    conversation_id, document_id = await _create_conversation_with_document(client)

    patch_resp = await client.patch(
        f"/api/documents/{document_id}",
        json={"display_name": "Lease Agreement"},
    )
    assert patch_resp.status_code == 200, patch_resp.text

    get_resp = await client.get(f"/api/conversations/{conversation_id}")
    assert get_resp.status_code == 200
    body = get_resp.json()

    documents_by_id = {doc["id"]: doc for doc in body["documents"]}
    assert documents_by_id[document_id]["display_name"] == "Lease Agreement"


async def test_patch_nonexistent_document_returns_404(client: AsyncClient) -> None:
    resp = await client.patch(
        "/api/documents/does-not-exist",
        json={"display_name": "New Name"},
    )

    assert resp.status_code == 404
