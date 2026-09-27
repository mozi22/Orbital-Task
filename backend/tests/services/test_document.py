from __future__ import annotations

import asyncio
import io

import pytest
from fastapi import UploadFile
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import Headers

from takehome.config import settings
from takehome.db.models import Document, DocumentType
from takehome.services.conversation import create_conversation
from takehome.services.document import (
    MAX_DOCUMENTS_PER_CONVERSATION,
    DocumentLimitExceededError,
    FileTooLargeError,
    InvalidFileTypeError,
    get_documents_for_conversation,
    rename_document,
    upload_document,
)
from takehome.services.llm import classification_agent
from tests.conftest import (
    SAMPLE_ENVIRONMENTAL_PDF_PATH,
    SAMPLE_LEASE_PDF_PATH,
    SAMPLE_TITLE_PDF_PATH,
    TestSessionLocal,
    make_classification_stub,
    read_pdf_bytes,
    read_sample_pdf_bytes,
)


def _make_upload_file(filename: str = "sample.pdf") -> UploadFile:
    return UploadFile(
        file=io.BytesIO(read_sample_pdf_bytes()),
        filename=filename,
        headers=Headers({"content-type": "application/pdf"}),
    )


async def test_upload_document_succeeds_below_cap(session: AsyncSession) -> None:
    conversation = await create_conversation(session)

    document = await upload_document(session, conversation.id, _make_upload_file())

    assert document.conversation_id == conversation.id
    docs = await get_documents_for_conversation(session, conversation.id)
    assert len(docs) == 1


async def test_upload_document_defaults_display_name_to_original_filename(
    session: AsyncSession,
) -> None:
    """Issue #12: display_name must default to the uploaded filename, with no
    separate naming step required at upload time."""
    conversation = await create_conversation(session)

    document = await upload_document(
        session, conversation.id, _make_upload_file("lease-agreement.pdf")
    )

    assert document.display_name == "lease-agreement.pdf"
    assert document.display_name == document.filename

    # Persisted, not just set on the in-memory object returned by the call.
    docs = await get_documents_for_conversation(session, conversation.id)
    assert docs[0].display_name == "lease-agreement.pdf"


async def test_upload_document_allows_up_to_five_documents(session: AsyncSession) -> None:
    conversation = await create_conversation(session)

    for i in range(MAX_DOCUMENTS_PER_CONVERSATION):
        await upload_document(session, conversation.id, _make_upload_file(f"doc-{i}.pdf"))

    docs = await get_documents_for_conversation(session, conversation.id)
    assert len(docs) == MAX_DOCUMENTS_PER_CONVERSATION


async def test_upload_document_rejects_sixth_document(session: AsyncSession) -> None:
    conversation = await create_conversation(session)

    for i in range(MAX_DOCUMENTS_PER_CONVERSATION):
        await upload_document(session, conversation.id, _make_upload_file(f"doc-{i}.pdf"))

    with pytest.raises(DocumentLimitExceededError, match="maximum of 5 documents"):
        await upload_document(session, conversation.id, _make_upload_file("doc-6.pdf"))

    docs = await get_documents_for_conversation(session, conversation.id)
    assert len(docs) == MAX_DOCUMENTS_PER_CONVERSATION


async def test_upload_document_rejects_non_pdf_file(session: AsyncSession) -> None:
    conversation = await create_conversation(session)

    non_pdf = UploadFile(
        file=io.BytesIO(b"not a pdf"),
        filename="notes.txt",
        headers=Headers({"content-type": "text/plain"}),
    )

    with pytest.raises(InvalidFileTypeError, match="Only PDF files"):
        await upload_document(session, conversation.id, non_pdf)

    docs = await get_documents_for_conversation(session, conversation.id)
    assert len(docs) == 0


async def test_upload_document_rejects_oversized_file(session: AsyncSession) -> None:
    conversation = await create_conversation(session)

    oversized = UploadFile(
        file=io.BytesIO(b"0" * (settings.max_upload_size + 1)),
        filename="huge.pdf",
        headers=Headers({"content-type": "application/pdf"}),
    )

    with pytest.raises(FileTooLargeError, match="File too large"):
        await upload_document(session, conversation.id, oversized)

    docs = await get_documents_for_conversation(session, conversation.id)
    assert len(docs) == 0


def test_document_upload_error_codes_are_distinct() -> None:
    """The three upload-failure exceptions must carry distinct machine-
    readable codes so callers (e.g. batch-upload UX) can tell cap-exceeded
    apart from wrong-file-type and oversized-file failures."""
    codes = {
        DocumentLimitExceededError("x").code,
        InvalidFileTypeError("x").code,
        FileTooLargeError("x").code,
    }
    assert len(codes) == 3


async def test_upload_document_guard_counts_documents_not_existence(
    session: AsyncSession,
) -> None:
    """The guard must reject only once 5 documents exist, not on the second upload."""
    conversation = await create_conversation(session)

    # Uploading a second, third and fourth document (well under the cap) must
    # all succeed -- this is the behavior the old "only one document ever"
    # guard used to forbid.
    for i in range(4):
        document = await upload_document(session, conversation.id, _make_upload_file(f"doc-{i}.pdf"))
        assert document is not None

    docs = await get_documents_for_conversation(session, conversation.id)
    assert len(docs) == 4


async def test_rename_document_updates_display_name_and_leaves_filename(
    session: AsyncSession,
) -> None:
    conversation = await create_conversation(session)
    document = await upload_document(session, conversation.id, _make_upload_file("lease.pdf"))

    renamed = await rename_document(session, document.id, "Lease Agreement")

    assert renamed is not None
    assert renamed.display_name == "Lease Agreement"
    assert renamed.filename == "lease.pdf"


async def test_rename_document_returns_none_for_missing_document(
    session: AsyncSession,
) -> None:
    result = await rename_document(session, "does-not-exist", "New Name")

    assert result is None


async def test_concurrent_uploads_at_cap_cannot_exceed_the_limit(
    session: AsyncSession,
) -> None:
    """Two concurrent uploads racing at count=4 must not both succeed.

    Each upload runs on its own session/connection (mirroring the real
    per-request session lifecycle), so the only thing preventing both from
    reading count=4 and both committing is the row lock in upload_document.
    """
    conversation = await create_conversation(session)

    # Bring the conversation to one below the cap.
    for i in range(MAX_DOCUMENTS_PER_CONVERSATION - 1):
        await upload_document(session, conversation.id, _make_upload_file(f"doc-{i}.pdf"))

    async def _upload(filename: str) -> Document | Exception:
        async with TestSessionLocal() as own_session:
            try:
                return await upload_document(own_session, conversation.id, _make_upload_file(filename))
            except DocumentLimitExceededError as e:
                return e

    results = await asyncio.gather(
        _upload("race-a.pdf"), _upload("race-b.pdf"), return_exceptions=False
    )

    successes = [r for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, DocumentLimitExceededError)]

    assert len(successes) == 1
    assert len(failures) == 1

    docs = await get_documents_for_conversation(session, conversation.id)
    assert len(docs) == MAX_DOCUMENTS_PER_CONVERSATION


# --------------------------------------------------------------------------- #
# Auto-classification at upload time (issue #32)
# --------------------------------------------------------------------------- #


async def test_upload_document_persists_the_llms_classification(session: AsyncSession) -> None:
    """The `document_type` an upload gets classified as must be persisted on
    the `Document` row, not just returned in-memory."""
    conversation = await create_conversation(session)

    with classification_agent.override(
        model=FunctionModel(make_classification_stub(DocumentType.LEASE))
    ):
        document = await upload_document(session, conversation.id, _make_upload_file("lease.pdf"))

    assert document.document_type == DocumentType.LEASE

    docs = await get_documents_for_conversation(session, conversation.id)
    assert docs[0].document_type == DocumentType.LEASE


async def test_upload_document_defaults_to_other_when_no_text_was_extracted(
    session: AsyncSession,
) -> None:
    """A document that fails text extraction (empty `extracted_text`) must
    still upload successfully, classified as OTHER rather than left unset."""
    conversation = await create_conversation(session)

    non_pdf_bytes_disguised_as_pdf = UploadFile(
        file=io.BytesIO(b"not a real pdf, so PyMuPDF extracts no text"),
        filename="broken.pdf",
        headers=Headers({"content-type": "application/pdf"}),
    )

    document = await upload_document(session, conversation.id, non_pdf_bytes_disguised_as_pdf)

    assert document.document_type == DocumentType.OTHER


@pytest.mark.parametrize(
    ("fixture_path", "expected_type", "marker_text"),
    [
        (SAMPLE_TITLE_PDF_PATH, DocumentType.TITLE, "OFFICIAL TITLE REPORT"),
        (SAMPLE_LEASE_PDF_PATH, DocumentType.LEASE, "LEASE"),
        (
            SAMPLE_ENVIRONMENTAL_PDF_PATH,
            DocumentType.ENVIRONMENTAL,
            "PHASE I ENVIRONMENTAL",
        ),
    ],
)
async def test_upload_classifies_each_sample_fixture_pdf_correctly(
    session: AsyncSession,
    fixture_path: str,
    expected_type: DocumentType,
    marker_text: str,
) -> None:
    """Integration test (issue #32's acceptance criteria): uploading each of
    the project's 3 real sample fixture PDFs runs it through real PDF text
    extraction and the real classification prompt-building, and persists the
    matching `document_type`.

    The stubbed model here doesn't hardcode "PDF X -> type Y" -- it inspects
    the *actual* prompt it was sent (built from the *actually extracted*
    text of the real PDF) for that document type's distinguishing marker
    text, so the test only passes if the real extracted content genuinely
    reached the classifier.
    """

    def _classify_by_marker(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompt_text = ""
        for message in messages:
            for part in message.parts:
                if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                    prompt_text = part.content

        tool = info.output_tools[0]
        if marker_text in prompt_text:
            result = expected_type.value
        else:
            result = DocumentType.OTHER.value
        return ModelResponse(parts=[ToolCallPart(tool_name=tool.name, args={"response": result})])

    conversation = await create_conversation(session)
    upload_file = UploadFile(
        file=io.BytesIO(read_pdf_bytes(fixture_path)),
        filename=fixture_path.rsplit("/", 1)[-1],
        headers=Headers({"content-type": "application/pdf"}),
    )

    with classification_agent.override(model=FunctionModel(_classify_by_marker)):
        document = await upload_document(session, conversation.id, upload_file)

    assert document.document_type == expected_type
