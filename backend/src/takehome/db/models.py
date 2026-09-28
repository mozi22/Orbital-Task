from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class DocumentType(enum.StrEnum):
    """Classification of an uploaded document, used by the risk-review
    pipeline (Milestone 2) to decide which extraction and rules apply.
    """

    TITLE = "title"
    LEASE = "lease"
    ENVIRONMENTAL = "environmental"
    OTHER = "other"


def _document_type_values(enum_cls: type[DocumentType]) -> list[str]:
    """Store each member's lowercase `.value` (e.g. "title") as the Postgres
    enum's label, rather than SQLAlchemy's default of `.name` (e.g. "TITLE").
    """
    return [member.value for member in enum_cls]


class FactStatus(enum.StrEnum):
    """Status of one extracted `Fact`, per the requirements doc's Fact
    wrapper (section 7): `extracted` (found with usable confidence),
    `needs_checking` (found but confidence below the 0.7 threshold, or a
    value that failed normalisation), `not_found` (a real, meaningful
    answer -- many risks come from something being absent), or
    `edited_by_user` (a solicitor corrected the extracted value).
    """

    EXTRACTED = "extracted"
    NEEDS_CHECKING = "needs_checking"
    NOT_FOUND = "not_found"
    EDITED_BY_USER = "edited_by_user"


def _fact_status_values(enum_cls: type[FactStatus]) -> list[str]:
    return [member.value for member in enum_cls]


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: uuid.uuid4().hex[:16]
    )
    title: Mapped[str] = mapped_column(String, default="New Conversation")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    documents: Mapped[list[Document]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    matter: Mapped[Matter | None] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", uselist=False
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: uuid.uuid4().hex[:16]
    )
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String)  # "user", "assistant", "system"
    content: Mapped[str] = mapped_column(Text)
    sources_cited: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: uuid.uuid4().hex[:16]
    )
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    filename: Mapped[str] = mapped_column(String)
    # User-facing label, defaulted to `filename` at creation time (see #12) and
    # independently editable afterward (see #12/#17). `filename` itself is left
    # untouched as the original upload name for storage/audit purposes.
    display_name: Mapped[str] = mapped_column(String)
    file_path: Mapped[str] = mapped_column(String)
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    # Classification driving which extraction/rules the risk-review pipeline
    # applies (see Milestone 2 PRD). Nullable: unset until the auto-
    # classification call runs (or is corrected by the user afterward).
    document_type: Mapped[DocumentType | None] = mapped_column(
        Enum(
            DocumentType,
            name="document_type",
            native_enum=True,
            values_callable=_document_type_values,
        ),
        nullable=True,
    )

    conversation: Mapped[Conversation] = relationship(back_populates="documents")


class Matter(Base):
    """A 1:1 extension of a Conversation holding risk-review gate state.

    Created the first time risk review is run on a Conversation (see the
    Milestone 2 PRD). The unique constraint on `conversation_id` is what
    actually enforces "one Matter per Conversation" -- the ORM relationship
    below is just a convenience for navigating it.
    """

    __tablename__ = "matters"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: uuid.uuid4().hex[:16]
    )
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), unique=True
    )
    # pass | fail | overridden -- not yet validated in application code (see
    # the migration that introduces this column); deferred to whichever
    # future ticket adds the risk-review gate logic itself.
    gate_result: Mapped[str] = mapped_column(String)
    gate_override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    conversation: Mapped[Conversation] = relationship(back_populates="matter")
    facts: Mapped[list[Fact]] = relationship(
        back_populates="matter", cascade="all, delete-orphan"
    )


class Fact(Base):
    """One extracted fact belonging to a Matter's risk review.

    Shared, document-type-agnostic scaffolding: every fact-extraction stage
    (title, lease, environmental -- see the Milestone 2 PRD's section 4 data
    model) writes rows to this same table, keyed by a dotted `key` (e.g.
    `lease.breaks`, `lease.security_of_tenure`) rather than one column per
    field, so adding a new extracted field never requires a schema change.

    Mirrors the requirements doc's Fact wrapper (section 7): `value` is the
    value as written in the document, `normalised_value` is its
    machine-comparable form (ISO date, standardised company name, etc. --
    only populated where normalisation is meaningful for that field's
    shape), `sources` is a JSON array of SourceSpan-shaped objects (at least
    one, always), `confidence` is 0-1, and `status` tracks whether the value
    was actually found.
    """

    __tablename__ = "facts"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: uuid.uuid4().hex[:16]
    )
    matter_id: Mapped[str] = mapped_column(ForeignKey("matters.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String)
    value: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    normalised_value: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[FactStatus] = mapped_column(
        Enum(
            FactStatus,
            name="fact_status",
            native_enum=True,
            values_callable=_fact_status_values,
        )
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    matter: Mapped[Matter] = relationship(back_populates="facts")
