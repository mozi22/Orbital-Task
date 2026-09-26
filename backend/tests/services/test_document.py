from __future__ import annotations

import io
import os

import pytest
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import Headers

from takehome.services.conversation import create_conversation
from takehome.services.document import (
    MAX_DOCUMENTS_PER_CONVERSATION,
    get_documents_for_conversation,
    upload_document,
)

SAMPLE_PDF_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "sample-docs", "title-report-lot-7.pdf"
)


def _make_upload_file(filename: str = "sample.pdf") -> UploadFile:
    with open(SAMPLE_PDF_PATH, "rb") as f:
        content = f.read()
    return UploadFile(
        file=io.BytesIO(content),
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

    with pytest.raises(ValueError, match="maximum of 5 documents"):
        await upload_document(session, conversation.id, _make_upload_file("doc-6.pdf"))

    docs = await get_documents_for_conversation(session, conversation.id)
    assert len(docs) == MAX_DOCUMENTS_PER_CONVERSATION


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
