"""Tests for correcting a document's `document_type` via PATCH.

Covers issue #33: the frontend's editable document_type dropdown (next to
the rename pencil) calls `PATCH /api/documents/{id}` with a `document_type`
field, sharing the same endpoint `rename` already uses (see #17) rather than
a second dedicated route. #32's auto-classification now runs on every
upload, so uploaded documents are classified immediately rather than
starting `null` -- these tests instead cover that a user can still
explicitly clear a document's classification back to `null` via PATCH.
"""

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


async def test_patch_document_type_can_be_cleared_to_null(
    client: AsyncClient,
) -> None:
    """#32's auto-classification runs on upload, so a document already has a
    non-null document_type by the time a user can edit it -- but explicitly
    clearing it back to "unclassified" via PATCH must still be possible."""
    _conversation_id, document_id = await _create_conversation_with_document(client)

    patch_resp = await client.patch(
        f"/api/documents/{document_id}",
        json={"document_type": None},
    )
    assert patch_resp.status_code == 200, patch_resp.text
    assert patch_resp.json()["document_type"] is None

    get_resp = await client.get(f"/api/conversations/{_conversation_id}")
    assert get_resp.status_code == 200
    documents_by_id = {doc["id"]: doc for doc in get_resp.json()["documents"]}
    assert documents_by_id[document_id]["document_type"] is None


async def test_patch_document_updates_document_type(client: AsyncClient) -> None:
    _conversation_id, document_id = await _create_conversation_with_document(client)

    resp = await client.patch(
        f"/api/documents/{document_id}",
        json={"document_type": "lease"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["document_type"] == "lease"
    # The rest of the document is left untouched.
    assert resp.json()["filename"] == "lease.pdf"


async def test_patch_document_type_reflected_on_conversation_get(
    client: AsyncClient,
) -> None:
    conversation_id, document_id = await _create_conversation_with_document(client)

    patch_resp = await client.patch(
        f"/api/documents/{document_id}",
        json={"document_type": "environmental"},
    )
    assert patch_resp.status_code == 200, patch_resp.text

    get_resp = await client.get(f"/api/conversations/{conversation_id}")
    assert get_resp.status_code == 200
    documents_by_id = {doc["id"]: doc for doc in get_resp.json()["documents"]}
    assert documents_by_id[document_id]["document_type"] == "environmental"


async def test_patch_document_type_can_be_changed_again(client: AsyncClient) -> None:
    """The user can correct a wrong auto-classification more than once."""
    _conversation_id, document_id = await _create_conversation_with_document(client)

    first = await client.patch(
        f"/api/documents/{document_id}", json={"document_type": "title"}
    )
    assert first.status_code == 200, first.text
    assert first.json()["document_type"] == "title"

    second = await client.patch(
        f"/api/documents/{document_id}", json={"document_type": "other"}
    )
    assert second.status_code == 200, second.text
    assert second.json()["document_type"] == "other"


async def test_patch_document_type_each_enum_value_persists(
    client: AsyncClient,
) -> None:
    _conversation_id, document_id = await _create_conversation_with_document(client)

    for value in ("title", "lease", "environmental", "other"):
        resp = await client.patch(
            f"/api/documents/{document_id}", json={"document_type": value}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["document_type"] == value


async def test_patch_invalid_document_type_returns_422(client: AsyncClient) -> None:
    _conversation_id, document_id = await _create_conversation_with_document(client)

    resp = await client.patch(
        f"/api/documents/{document_id}",
        json={"document_type": "not-a-real-type"},
    )

    assert resp.status_code == 422, resp.text


async def test_patch_nonexistent_document_document_type_returns_404(
    client: AsyncClient,
) -> None:
    resp = await client.patch(
        "/api/documents/does-not-exist",
        json={"document_type": "lease"},
    )

    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert detail["code"] == "document_not_found"


async def test_patch_document_type_does_not_touch_display_name(
    client: AsyncClient,
) -> None:
    """Correcting document_type alone must not clobber a previously-set
    display_name (the two fields are independently optional on the same
    PATCH body)."""
    conversation_id, document_id = await _create_conversation_with_document(client)

    rename_resp = await client.patch(
        f"/api/documents/{document_id}", json={"display_name": "Signed Lease"}
    )
    assert rename_resp.status_code == 200, rename_resp.text

    type_resp = await client.patch(
        f"/api/documents/{document_id}", json={"document_type": "lease"}
    )
    assert type_resp.status_code == 200, type_resp.text
    assert type_resp.json()["display_name"] == "Signed Lease"
    assert type_resp.json()["document_type"] == "lease"

    get_resp = await client.get(f"/api/conversations/{conversation_id}")
    documents_by_id = {doc["id"]: doc for doc in get_resp.json()["documents"]}
    assert documents_by_id[document_id]["display_name"] == "Signed Lease"
    assert documents_by_id[document_id]["document_type"] == "lease"


async def test_patch_display_name_and_document_type_together(
    client: AsyncClient,
) -> None:
    """Both fields can be corrected in a single PATCH request."""
    _conversation_id, document_id = await _create_conversation_with_document(client)

    resp = await client.patch(
        f"/api/documents/{document_id}",
        json={"display_name": "Signed Lease", "document_type": "lease"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["display_name"] == "Signed Lease"
    assert resp.json()["document_type"] == "lease"


async def test_patch_with_no_fields_returns_400(client: AsyncClient) -> None:
    _conversation_id, document_id = await _create_conversation_with_document(client)

    resp = await client.patch(f"/api/documents/{document_id}", json={})

    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "no_fields_to_update"
