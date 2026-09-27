from __future__ import annotations

import os
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import FileResponse

from takehome.db.session import get_session
from takehome.services.conversation import get_conversation
from takehome.services.document import (
    DocumentLimitExceededError,
    DocumentUploadError,
    get_document,
    rename_document,
    upload_document,
)

logger = structlog.get_logger()

router = APIRouter(tags=["documents"])


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #


class DocumentOut(BaseModel):
    id: str
    conversation_id: str
    filename: str
    display_name: str
    page_count: int
    uploaded_at: datetime

    model_config = {"from_attributes": True}


class DocumentRenameRequest(BaseModel):
    display_name: str


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #


@router.post(
    "/api/conversations/{conversation_id}/documents",
    response_model=DocumentOut,
    status_code=201,
)
async def upload_document_endpoint(
    conversation_id: str,
    file: UploadFile,
    session: AsyncSession = Depends(get_session),
) -> DocumentOut:
    """Upload a PDF document for a conversation.

    Up to 5 documents per conversation are allowed. Returns 409 once the cap
    is reached, and 400 for wrong-file-type or oversized-file failures. Every
    error response body — including the 404 for a missing conversation —
    carries a ``code`` field (``conversation_not_found``,
    ``document_limit_exceeded``, ``invalid_file_type``, or ``file_too_large``)
    in addition to a distinct ``message``, so callers can tell the failure
    reasons apart without relying on status code or message text alone.
    """
    # Verify the conversation exists
    conversation = await get_conversation(session, conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "conversation_not_found",
                "message": "Conversation not found",
            },
        )

    try:
        document = await upload_document(session, conversation_id, file)
    except DocumentLimitExceededError as e:
        raise HTTPException(
            status_code=409, detail={"code": e.code, "message": str(e)}
        ) from e
    except DocumentUploadError as e:
        raise HTTPException(
            status_code=400, detail={"code": e.code, "message": str(e)}
        ) from e

    logger.info(
        "Document uploaded",
        conversation_id=conversation_id,
        document_id=document.id,
        filename=document.filename,
    )

    return DocumentOut.model_validate(document)


@router.patch("/api/documents/{document_id}", response_model=DocumentOut)
async def rename_document_endpoint(
    document_id: str,
    body: DocumentRenameRequest,
    session: AsyncSession = Depends(get_session),
) -> DocumentOut:
    """Rename a document's user-facing `display_name`.

    The underlying `filename` (the original upload name) is left unchanged.
    """
    document = await rename_document(session, document_id, body.display_name)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    logger.info(
        "Document renamed",
        document_id=document.id,
        display_name=document.display_name,
    )

    return DocumentOut.model_validate(document)


@router.get("/api/documents/{document_id}/content")
async def serve_document_file(
    document_id: str,
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    """Serve the raw PDF file for download/viewing."""
    document = await get_document(session, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    if not os.path.exists(document.file_path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        path=document.file_path,
        filename=document.filename,
        media_type="application/pdf",
    )
