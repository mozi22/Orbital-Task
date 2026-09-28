from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
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


class FactStatus(enum.StrEnum):
    """A `Fact`'s review status (requirements doc section 7's Fact wrapper).

    `NOT_FOUND` is a real, expected answer -- not an error -- for a field
    genuinely absent from the document (e.g. no guarantor named in a lease).
    `NEEDS_CHECKING` covers both a low-confidence extraction (below 0.7, per
    the requirements doc) and a value that failed normalisation.
    """

    EXTRACTED = "extracted"
    NEEDS_CHECKING = "needs_checking"
    NOT_FOUND = "not_found"
    EDITED_BY_USER = "edited_by_user"


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
    facts: Mapped[list[Fact]] = relationship(back_populates="matter", cascade="all, delete-orphan")


class Fact(Base):
    """One extracted fact for a Matter (requirements doc section 7, PRD
    section 4). Shared across every document-type/field-subset extraction
    ticket (issues #39-#42 and beyond) -- each writes rows here keyed by its
    own dotted `key` namespace (e.g. `lease.landlord.name`), so they never
    collide with each other's rows for the same Matter.

    `value`/`normalised_value` are stored as JSON rather than a fixed column
    per fact shape, since a fact's value can be a string, a number, a bool,
    or a list (e.g. `lease.rent_review.dates`) depending on which field it
    is -- one `Fact` row shape has to serve all of them. `sources` is a JSON
    array of source-span objects (document, page, clause, quote), per the
    same section's `SourceSpan` structure.
    """

    __tablename__ = "facts"
    __table_args__ = (UniqueConstraint("matter_id", "key", name="uq_facts_matter_id_key"),)

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: uuid.uuid4().hex[:16]
    )
    matter_id: Mapped[str] = mapped_column(ForeignKey("matters.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String)
    value: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    normalised_value: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float)
    # extracted | needs_checking | not_found | edited_by_user -- kept as a
    # plain string (not a DB enum), matching this schema's existing
    # convention for status-like columns that aren't yet validated at the
    # DB level (see `Matter.gate_result`'s own comment).
    status: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    matter: Mapped[Matter] = relationship(back_populates="facts")
