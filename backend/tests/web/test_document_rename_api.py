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
    detail = resp.json()["detail"]
    assert detail["code"] == "document_not_found"
    assert detail["message"] == "Document not found"


async def test_patch_empty_display_name_returns_400(client: AsyncClient) -> None:
    _conversation_id, document_id = await _create_conversation_with_document(client)

    resp = await client.patch(
        f"/api/documents/{document_id}",
        json={"display_name": ""},
    )

    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "invalid_display_name"


async def test_patch_blank_display_name_returns_400(client: AsyncClient) -> None:
    _conversation_id, document_id = await _create_conversation_with_document(client)

    resp = await client.patch(
        f"/api/documents/{document_id}",
        json={"display_name": "   "},
    )

    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "invalid_display_name"


async def test_patch_empty_display_name_does_not_change_stored_name(
    client: AsyncClient,
) -> None:
    """A rejected rename must leave the previously-stored display_name intact."""
    conversation_id, document_id = await _create_conversation_with_document(client)

    ok_resp = await client.patch(
        f"/api/documents/{document_id}",
        json={"display_name": "Lease Agreement"},
    )
    assert ok_resp.status_code == 200, ok_resp.text

    bad_resp = await client.patch(
        f"/api/documents/{document_id}",
        json={"display_name": "   "},
    )
    assert bad_resp.status_code == 400, bad_resp.text

    get_resp = await client.get(f"/api/conversations/{conversation_id}")
    assert get_resp.status_code == 200
    documents_by_id = {doc["id"]: doc for doc in get_resp.json()["documents"]}
    assert documents_by_id[document_id]["display_name"] == "Lease Agreement"


async def test_patch_document_leaves_filename_and_file_on_disk_unchanged(
    client: AsyncClient,
) -> None:
    conversation_id, document_id = await _create_conversation_with_document(client)
    original_bytes = read_sample_pdf_bytes()

    before_content_resp = await client.get(f"/api/documents/{document_id}/content")
    assert before_content_resp.status_code == 200
    assert before_content_resp.content == original_bytes

    patch_resp = await client.patch(
        f"/api/documents/{document_id}",
        json={"display_name": "Lease Agreement"},
    )
    assert patch_resp.status_code == 200, patch_resp.text
    assert patch_resp.json()["filename"] == "lease.pdf"

    after_content_resp = await client.get(f"/api/documents/{document_id}/content")
    assert after_content_resp.status_code == 200
    assert after_content_resp.content == original_bytes

    get_resp = await client.get(f"/api/conversations/{conversation_id}")
    assert get_resp.status_code == 200
    documents_by_id = {doc["id"]: doc for doc in get_resp.json()["documents"]}
    assert documents_by_id[document_id]["filename"] == "lease.pdf"
