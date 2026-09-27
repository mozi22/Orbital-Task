from __future__ import annotations

import asyncio
import io

import pytest
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import Headers

from takehome.config import settings
from takehome.db.models import Document
from takehome.services.conversation import create_conversation
from takehome.services.document import (
    MAX_DOCUMENTS_PER_CONVERSATION,
    DocumentLimitExceededError,
    FileTooLargeError,
    InvalidFileTypeError,
    get_documents_for_conversation,
    upload_document,
)
from tests.conftest import TestSessionLocal, read_sample_pdf_bytes


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
