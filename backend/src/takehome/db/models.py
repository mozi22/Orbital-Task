from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
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
    """Lifecycle status of one extracted `Fact` (requirements doc section 7).

    "not_found" is a real, meaningful answer -- not an error -- when a field
    genuinely isn't present in the document (e.g. no cautions registered).
    "needs_checking" is assigned by extraction code, never the LLM itself,
    whenever a fact's confidence is below the 0.7 threshold (see
    `pipeline.extract_title`). "edited_by_user" is never written by
    extraction -- it is reserved for a later ticket that lets a solicitor
    correct a fact from the review screen.
    """

    EXTRACTED = "extracted"
    NEEDS_CHECKING = "needs_checking"
    NOT_FOUND = "not_found"
    EDITED_BY_USER = "edited_by_user"


def _fact_status_values(enum_cls: type[FactStatus]) -> list[str]:
    """Same rationale as `_document_type_values` above: store `.value`
    ("extracted") as the Postgres enum label, not `.name` ("EXTRACTED")."""
    return [member.value for member in enum_cls]


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
    facts: Mapped[list[Fact]] = relationship(back_populates="document", cascade="all, delete-orphan")


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
    """One extracted value from a document, per the requirements doc's
    section 7 "Fact" wrapper -- shared by every document type's extraction
    (title report here, issue #39; lease and environmental in the sibling
    issues #40-#42 running in parallel). Each document type owns only its
    own `key` namespace and extraction logic; this table and model are the
    shared scaffolding all of them write into.

    `key` is a dotted, document-type-prefixed field name (e.g.
    "title.registered_owner_name", mirroring the requirements doc's own
    example "lease.term.end_date") so keys from different document types
    never collide in this shared table.

    A repeating field (e.g. title.charges, one row per charge) simply has
    more than one `Fact` row sharing the same `key` -- there is no separate
    list/collection type. `value` holds the fact as extracted (a plain
    scalar for most title-report fields, or a small JSON object for a
    repeating field's single item, e.g. one charge's entry_number/date/
    lender_name/etc together). `normalised_value` mirrors `value`'s shape
    but with normalisable sub-values (dates, money, company names, areas --
    see `pipeline.normalise`, issue #37) converted to their machine-
    comparable form; fields with no defined normaliser (e.g. a company
    number, a postcode) are copied through unchanged rather than invented
    here.
    """

    __tablename__ = "facts"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: uuid.uuid4().hex[:16]
    )
    matter_id: Mapped[str] = mapped_column(ForeignKey("matters.id", ondelete="CASCADE"))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String)
    value: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    normalised_value: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    # SourceSpan[] (requirements doc section 7), stored as JSON rather than a
    # child table -- it has no independent lifecycle or query pattern of its
    # own beyond "read alongside its Fact", so a second table would only add
    # join overhead with no real benefit at this scope.
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
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
    document: Mapped[Document] = relationship(back_populates="facts")
