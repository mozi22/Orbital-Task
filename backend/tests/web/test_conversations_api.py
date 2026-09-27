from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import read_sample_pdf_bytes


def _pdf_upload_tuple(filename: str) -> tuple[str, tuple[str, bytes, str]]:
    return ("file", (filename, read_sample_pdf_bytes(), "application/pdf"))


async def test_get_conversation_with_no_documents_returns_empty_documents_list(
    client: AsyncClient,
) -> None:
    create_resp = await client.post("/api/conversations")
    conversation_id = create_resp.json()["id"]

    get_resp = await client.get(f"/api/conversations/{conversation_id}")
    assert get_resp.status_code == 200
    body = get_resp.json()

    assert "document" not in body
    assert body["documents"] == []
    assert body["has_document"] is False


async def test_get_conversation_with_two_documents_returns_both_in_documents_array(
    client: AsyncClient,
) -> None:
    create_resp = await client.post("/api/conversations")
    conversation_id = create_resp.json()["id"]

    uploaded_ids = []
    for i in range(2):
        field_name, file_tuple = _pdf_upload_tuple(f"doc-{i}.pdf")
        resp = await client.post(
            f"/api/conversations/{conversation_id}/documents",
            files=[(field_name, file_tuple)],
        )
        assert resp.status_code == 201, resp.text
        uploaded_ids.append(resp.json()["id"])

    get_resp = await client.get(f"/api/conversations/{conversation_id}")
    assert get_resp.status_code == 200
    body = get_resp.json()

    assert "document" not in body
    assert len(body["documents"]) == 2
    assert {d["id"] for d in body["documents"]} == set(uploaded_ids)
    assert {d["filename"] for d in body["documents"]} == {"doc-0.pdf", "doc-1.pdf"}
    assert body["has_document"] is True


async def test_get_conversation_document_display_name_defaults_to_filename(
    client: AsyncClient,
) -> None:
    create_resp = await client.post("/api/conversations")
    conversation_id = create_resp.json()["id"]

    field_name, file_tuple = _pdf_upload_tuple("lease-agreement.pdf")
    upload_resp = await client.post(
        f"/api/conversations/{conversation_id}/documents",
        files=[(field_name, file_tuple)],
    )
    assert upload_resp.status_code == 201, upload_resp.text
    document_id = upload_resp.json()["id"]

    get_resp = await client.get(f"/api/conversations/{conversation_id}")
    assert get_resp.status_code == 200
    body = get_resp.json()

    documents_by_id = {doc["id"]: doc for doc in body["documents"]}
    assert documents_by_id[document_id]["display_name"] == "lease-agreement.pdf"


async def test_create_conversation_response_has_no_document_field(client: AsyncClient) -> None:
    create_resp = await client.post("/api/conversations")
    assert create_resp.status_code == 201
    body = create_resp.json()

    assert "document" not in body
    assert body["documents"] == []


async def test_update_conversation_preserves_documents_list(client: AsyncClient) -> None:
    create_resp = await client.post("/api/conversations")
    conversation_id = create_resp.json()["id"]

    field_name, file_tuple = _pdf_upload_tuple("doc-0.pdf")
    upload_resp = await client.post(
        f"/api/conversations/{conversation_id}/documents",
        files=[(field_name, file_tuple)],
    )
    assert upload_resp.status_code == 201

    patch_resp = await client.patch(
        f"/api/conversations/{conversation_id}", json={"title": "Renamed"}
    )
    assert patch_resp.status_code == 200
    body = patch_resp.json()

    assert "document" not in body
    assert len(body["documents"]) == 1
    assert body["documents"][0]["filename"] == "doc-0.pdf"
