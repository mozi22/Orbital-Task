from __future__ import annotations

import os
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import FileResponse

from takehome.db.models import DocumentType
from takehome.db.session import get_session
from takehome.services.conversation import get_conversation
from takehome.services.document import (
    DocumentLimitExceededError,
    DocumentValidationError,
    InvalidDisplayNameError,
    get_document,
    rename_document,
    set_document_type,
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
    # Classification driving the risk-review pipeline (Milestone 2), shown as
    # an editable dropdown next to the rename pencil (see #33). `None` until
    # auto-classification runs (or the user corrects it via this same PATCH).
    document_type: DocumentType | None = None

    model_config = {"from_attributes": True}


class DocumentUpdateRequest(BaseModel):
    """Partial update for a document's two user-editable fields.

    Both are optional so the same endpoint serves both the rename pencil
    (`display_name`, see #17) and the document_type dropdown (`document_type`,
    see #33) -- each PATCH may correct either or both in one request, but at
    least one must actually be provided (an empty body is rejected below
    rather than silently no-oping).
    """

    display_name: str | None = None
    document_type: DocumentType | None = None


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
    except DocumentValidationError as e:
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
async def update_document_endpoint(
    document_id: str,
    body: DocumentUpdateRequest,
    session: AsyncSession = Depends(get_session),
) -> DocumentOut:
    """Correct a document's `display_name` and/or `document_type`.

    Either field may be supplied on its own or both together; at least one
    must be present or this returns 400 (`no_fields_to_update`). Renaming
    leaves the underlying `filename` (the original upload name) and the
    stored file on disk unchanged, and rejects an empty/blank
    `display_name` with 400 (`invalid_display_name`). Returns 404
    (`document_not_found`) if no document with that id exists.
    """
    fields_set = body.model_fields_set
    if "display_name" not in fields_set and "document_type" not in fields_set:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "no_fields_to_update",
                "message": "At least one of display_name or document_type "
                "must be provided.",
            },
        )

    document = None

    if "display_name" in fields_set:
        if body.display_name is None:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "invalid_display_name",
                    "message": "display_name must not be empty or blank.",
                },
            )
        try:
            document = await rename_document(session, document_id, body.display_name)
        except InvalidDisplayNameError as e:
            raise HTTPException(
                status_code=400, detail={"code": e.code, "message": str(e)}
            ) from e
        if document is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "document_not_found",
                    "message": "Document not found",
                },
            )
        logger.info(
            "Document renamed",
            document_id=document.id,
            display_name=document.display_name,
        )

    if "document_type" in fields_set:
        document = await set_document_type(session, document_id, body.document_type)
        if document is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "document_not_found",
                    "message": "Document not found",
                },
            )
        logger.info(
            "Document type updated",
            document_id=document.id,
            document_type=document.document_type,
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
