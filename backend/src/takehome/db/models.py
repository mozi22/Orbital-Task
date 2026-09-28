from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text, func
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
    """One extracted fact for a Matter (see the Milestone 2 PRD's data model
    and the requirements doc's "Extracted facts data model", section 7).

    Shared across every document type's extraction stage (title, lease,
    environmental -- see issues #39/#40/#42 alongside this one): each row is
    one dotted `key` (e.g. `environmental.report_reference`,
    `lease.landlord`), not one row per document-type-specific column, so the
    facts table doesn't need reshaping every time a new document type or
    field is added. `value`, `normalised_value` and `source` are stored as
    JSON-encoded text (mirroring the PRD's "facts and flags stored as JSON
    columns plus key indexed fields" suggestion, and this project's existing
    convention of plain `Text`/`String` columns over Postgres-native JSON,
    e.g. `Matter.gate_result`) rather than typed columns, since `value` is
    genuinely `any` per the requirements doc (a string, a number, a list of
    objects, ...) depending on which `key` it is.

    `source` deliberately has no character-offset fields -- the Milestone 2
    PRD notes the assignment's own simplified `Source` model omits them
    (text-highlighting a PDF page is explicitly out of scope this
    milestone), so only document/page/clause/quote are kept.
    """

    __tablename__ = "facts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: uuid.uuid4().hex[:16])
    matter_id: Mapped[str] = mapped_column(ForeignKey("matters.id", ondelete="CASCADE"))
    # Dotted field name, e.g. "environmental.report_reference",
    # "environmental.historical_uses". Not unique alone -- a fact can be
    # re-extracted on a pipeline re-run (see the requirements doc's
    # "Re-runs" section), and this table keeps every row rather than
    # upserting in place.
    key: Mapped[str] = mapped_column(String)
    # As written in the document, JSON-encoded (a bare JSON string for a
    # scalar, e.g. '"Flood Zone 2"', or a JSON array of objects for a
    # list-shaped fact, e.g. `historical_uses`).
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Machine-comparable form (ISO date, integer pence, m^2, standardised
    # company name -- see `takehome.pipeline.normalise`), JSON-encoded the
    # same way as `value`. Null whenever no normalisation applies to this
    # key, or normalisation failed (see `status`).
    normalised_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    # e.g. "GBP", "m2", "sq ft" -- null when the fact has no natural unit.
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    # SourceSpan[] (JSON array of {document_id, pdf_page_index, clause_ref,
    # quote}), at least one entry whenever `status` isn't "not_found".
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float)
    # found | not_found | needs_checking (see the Milestone 2 PRD's data
    # model) -- kept as a plain string, not a DB enum, matching this
    # schema's existing convention for similarly-constrained columns (e.g.
    # `Matter.gate_result`, `Message.role`). Validated in application code by
    # `takehome.services.fact`, not at the database level.
    status: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    matter: Mapped[Matter] = relationship(back_populates="facts")


Index("ix_facts_matter_id_key", Fact.__table__.c.matter_id, Fact.__table__.c.key)
