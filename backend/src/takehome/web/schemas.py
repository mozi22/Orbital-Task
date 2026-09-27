"""Response schemas shared across more than one router.

Currently just the document fields common to both `GET
/api/conversations/{id}` (`ConversationDetail.documents`, a `DocumentInfo`
per document) and `POST`/`PATCH /api/documents` (`DocumentOut`) -- the two
independently evolved into the same six fields, so this factors that shape
out once rather than leaving both routers to keep it in sync by hand.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from takehome.db.models import DocumentType


class DocumentBase(BaseModel):
    """Fields common to every document response, regardless of endpoint."""

    id: str
    filename: str
    display_name: str
    page_count: int
    uploaded_at: datetime
    # Classification driving the risk-review pipeline (Milestone 2), shown as
    # an editable dropdown next to the rename pencil (see #33). `None` until
    # auto-classification runs (or the user corrects it via
    # `PATCH /api/documents/{id}`).
    document_type: DocumentType | None = None

    model_config = {"from_attributes": True}
