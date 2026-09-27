from __future__ import annotations

import os
import uuid

import fitz  # PyMuPDF
import structlog
from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from takehome.config import settings
from takehome.db.models import Conversation, Document

logger = structlog.get_logger()

# Maximum number of documents allowed per conversation.
MAX_DOCUMENTS_PER_CONVERSATION = 5


class DocumentUploadError(ValueError):
    """Base class for document upload validation failures.

    Each subclass carries a distinct ``code`` so callers (the router, and
    ultimately batch-upload UX) can tell failure reasons apart programmatically
    instead of pattern-matching on the human-readable message.
    """

    code = "document_upload_error"


class DocumentLimitExceededError(DocumentUploadError):
    """Raised when a conversation already has the maximum number of documents."""

    code = "document_limit_exceeded"


class InvalidFileTypeError(DocumentUploadError):
    """Raised when the uploaded file is not a PDF."""

    code = "invalid_file_type"


class FileTooLargeError(DocumentUploadError):
    """Raised when the uploaded file exceeds the configured size limit."""

    code = "file_too_large"


async def upload_document(
    session: AsyncSession, conversation_id: str, file: UploadFile
) -> Document:
    """Upload and process a PDF document for a conversation.

    Validates the file is a PDF, saves it to disk, extracts text using PyMuPDF,
    and stores metadata in the database.

    Raises DocumentLimitExceededError if the conversation already has the
    maximum number of documents allowed, InvalidFileTypeError if the file is
    not a PDF, or FileTooLargeError if it exceeds the configured size limit.
    Each is a distinctly-coded subclass of DocumentUploadError so callers can
    tell the failure reasons apart without parsing message text.
    """
    # Lock the conversation row for the duration of the check-then-act cap
    # check below, so two concurrent uploads to the same conversation can't
    # both read a count under the cap and both commit past it. Postgres
    # releases this lock at transaction end (commit/rollback).
    lock_stmt = select(Conversation.id).where(Conversation.id == conversation_id).with_for_update()
    await session.execute(lock_stmt)

    # Check if the conversation has already reached the document cap. Counted
    # via SELECT count(*) rather than fetching full rows (which would include
    # potentially large extracted_text columns).
    count_stmt = select(func.count()).select_from(Document).where(
        Document.conversation_id == conversation_id
    )
    existing_count = (await session.execute(count_stmt)).scalar_one()
    if existing_count >= MAX_DOCUMENTS_PER_CONVERSATION:
        raise DocumentLimitExceededError(
            "Conversation already has the maximum of "
            f"{MAX_DOCUMENTS_PER_CONVERSATION} documents allowed."
        )

    # Validate file type
    if file.content_type not in ("application/pdf", "application/x-pdf"):
        filename = file.filename or ""
        if not filename.lower().endswith(".pdf"):
            raise InvalidFileTypeError("Only PDF files are supported.")

    # Read file content
    content = await file.read()

    # Validate file size
    if len(content) > settings.max_upload_size:
        raise FileTooLargeError(
            f"File too large. Maximum size is {settings.max_upload_size // (1024 * 1024)}MB."
        )

    # Generate a unique filename to avoid collisions
    original_filename = file.filename or "document.pdf"
    unique_name = f"{uuid.uuid4().hex}_{original_filename}"
    file_path = os.path.join(settings.upload_dir, unique_name)

    # Ensure upload directory exists
    os.makedirs(settings.upload_dir, exist_ok=True)

    # Save the file to disk
    with open(file_path, "wb") as f:
        f.write(content)

    logger.info("Saved uploaded PDF", filename=original_filename, path=file_path, size=len(content))

    # Extract text using PyMuPDF
    extracted_text = ""
    page_count = 0
    try:
        doc = fitz.open(file_path)
        page_count = len(doc)
        pages: list[str] = []
        for page_num in range(page_count):
            page = doc[page_num]
            text = page.get_text()  # type: ignore[union-attr]
            if text.strip():
                pages.append(f"--- Page {page_num + 1} ---\n{text}")
        extracted_text = "\n\n".join(pages)
        doc.close()
    except Exception:
        logger.exception("Failed to extract text from PDF", filename=original_filename)
        extracted_text = ""

    logger.info(
        "Extracted text from PDF",
        filename=original_filename,
        page_count=page_count,
        text_length=len(extracted_text),
    )

    # Create the document record
    document = Document(
        conversation_id=conversation_id,
        filename=original_filename,
        display_name=original_filename,
        file_path=file_path,
        extracted_text=extracted_text if extracted_text else None,
        page_count=page_count,
    )
    session.add(document)
    await session.commit()
    await session.refresh(document)
    return document


async def get_document(session: AsyncSession, document_id: str) -> Document | None:
    """Get a document by its ID."""
    stmt = select(Document).where(Document.id == document_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_document_for_conversation(
    session: AsyncSession, conversation_id: str
) -> Document | None:
    """Get the first document for a conversation, if one exists.

    Used by single-document call sites (e.g. chat prompt building) that
    haven't yet been updated to work across multiple documents.
    """
    documents = await get_documents_for_conversation(session, conversation_id)
    return documents[0] if documents else None


async def get_documents_for_conversation(
    session: AsyncSession, conversation_id: str
) -> list[Document]:
    """Get all documents for a conversation, ordered by upload time."""
    stmt = (
        select(Document)
        .where(Document.conversation_id == conversation_id)
        .order_by(Document.uploaded_at)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
