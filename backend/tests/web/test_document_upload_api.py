from __future__ import annotations

from httpx import AsyncClient

from takehome.services.document import get_documents_for_conversation
from tests.conftest import TestSessionLocal, read_sample_pdf_bytes


def _pdf_upload_tuple(filename: str) -> tuple[str, tuple[str, bytes, str]]:
    return ("file", (filename, read_sample_pdf_bytes(), "application/pdf"))


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
    detail = sixth_resp.json()["detail"]
    assert detail["code"] == "document_limit_exceeded"
    assert "maximum of 5 documents" in detail["message"]

    # The conversation must still show exactly the original 5 documents.
    get_resp = await client.get(f"/api/conversations/{conversation_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["has_document"] is True

    async with TestSessionLocal() as session:
        docs = await get_documents_for_conversation(session, conversation_id)

    assert len(docs) == 5
    assert {d.id for d in docs} == set(uploaded_ids)


async def test_wrong_file_type_returns_400_with_invalid_file_type_code(
    client: AsyncClient,
) -> None:
    create_resp = await client.post("/api/conversations")
    conversation_id = create_resp.json()["id"]

    resp = await client.post(
        f"/api/conversations/{conversation_id}/documents",
        files=[("file", ("notes.txt", b"not a pdf", "text/plain"))],
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "invalid_file_type"
    assert "Only PDF files" in detail["message"]


async def test_oversized_file_returns_400_with_file_too_large_code(
    client: AsyncClient,
) -> None:
    create_resp = await client.post("/api/conversations")
    conversation_id = create_resp.json()["id"]

    huge_content = b"0" * (25 * 1024 * 1024 + 1)
    resp = await client.post(
        f"/api/conversations/{conversation_id}/documents",
        files=[("file", ("huge.pdf", huge_content, "application/pdf"))],
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "file_too_large"
    assert "File too large" in detail["message"]


async def test_missing_conversation_returns_404_with_conversation_not_found_code(
    client: AsyncClient,
) -> None:
    field_name, file_tuple = _pdf_upload_tuple("doc.pdf")
    resp = await client.post(
        "/api/conversations/does-not-exist/documents",
        files=[(field_name, file_tuple)],
    )
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert detail["code"] == "conversation_not_found"
    assert detail["message"] == "Conversation not found"


async def test_all_three_error_cases_against_same_conversation_are_distinct(
    client: AsyncClient,
) -> None:
    """Triggers cap-exceeded, wrong-file-type, and oversized-file failures
    against the same conversation and confirms every response is
    distinguishable from the other two by status code, error code, and
    message -- the verification the ticket's acceptance criteria call for."""
    create_resp = await client.post("/api/conversations")
    conversation_id = create_resp.json()["id"]

    # Trigger wrong-type and oversized failures first, while under the cap --
    # neither counts towards it, since the cap check in upload_document runs
    # before the file's contents are ever inspected.
    wrong_type_resp = await client.post(
        f"/api/conversations/{conversation_id}/documents",
        files=[("file", ("notes.txt", b"not a pdf", "text/plain"))],
    )
    oversized_resp = await client.post(
        f"/api/conversations/{conversation_id}/documents",
        files=[
            (
                "file",
                ("huge.pdf", b"0" * (25 * 1024 * 1024 + 1), "application/pdf"),
            )
        ],
    )

    # Now fill the conversation to the cap and trigger cap-exceeded on the
    # same conversation.
    for i in range(5):
        field_name, file_tuple = _pdf_upload_tuple(f"doc-{i}.pdf")
        resp = await client.post(
            f"/api/conversations/{conversation_id}/documents",
            files=[(field_name, file_tuple)],
        )
        assert resp.status_code == 201, resp.text

    cap_resp = await client.post(
        f"/api/conversations/{conversation_id}/documents",
        files=[("file", ("doc-6.pdf", read_sample_pdf_bytes(), "application/pdf"))],
    )

    responses = {
        "cap_exceeded": cap_resp,
        "wrong_type": wrong_type_resp,
        "oversized": oversized_resp,
    }

    statuses = {name: resp.status_code for name, resp in responses.items()}
    codes = {name: resp.json()["detail"]["code"] for name, resp in responses.items()}
    messages = {
        name: resp.json()["detail"]["message"] for name, resp in responses.items()
    }

    assert statuses == {
        "cap_exceeded": 409,
        "wrong_type": 400,
        "oversized": 400,
    }
    # Every code and every message must be pairwise distinct, even though
    # wrong-type and oversized share the same 400 status code.
    assert len(set(codes.values())) == 3
    assert len(set(messages.values())) == 3
