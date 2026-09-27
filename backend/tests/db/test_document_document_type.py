"""Tests for the `Document.document_type` column and its migration.

Covers issue #31: Document gains a nullable `document_type` enum column
(`title`, `lease`, `environmental`, `other`) so the risk-review pipeline can
tell which extraction/rules apply to a given upload. Existing rows migrate
with `document_type = NULL` until classification runs.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from takehome.config import settings
from takehome.db.models import Document, DocumentType

REPO_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


def _alembic_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    return cfg


async def _run_sql(sql: str, params: dict[str, object] | None = None) -> None:
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(sql), params or {})
    finally:
        await engine.dispose()


async def _fetch_one(sql: str, params: dict[str, object]) -> object:
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text(sql), params)
            return result.one()
    finally:
        await engine.dispose()


@pytest.fixture
def reset_schema():
    """Wipe the schema and re-apply migrations up to (but not including) the
    document_type migration, leaving a clean pre-migration schema for each test.

    See `test_document_display_name.py`'s identical fixture for why this uses
    a raw `DROP SCHEMA` rather than `alembic downgrade base`.
    """
    cfg = _alembic_config()
    asyncio.run(_run_sql("DROP SCHEMA public CASCADE"))
    asyncio.run(_run_sql("CREATE SCHEMA public"))
    command.upgrade(cfg, "002_display_name")
    yield cfg
    # Leave the DB migrated to head so other tests/tools see a consistent state.
    command.upgrade(cfg, "head")


def _seed_conversation_and_document(document_id: str) -> str:
    conversation_id = uuid.uuid4().hex[:16]
    asyncio.run(
        _run_sql(
            "INSERT INTO conversations (id, title) VALUES (:id, :title)",
            {"id": conversation_id, "title": "Test Conversation"},
        )
    )
    asyncio.run(
        _run_sql(
            "INSERT INTO documents "
            "(id, conversation_id, filename, display_name, file_path, page_count) "
            "VALUES (:id, :conversation_id, :filename, :display_name, :file_path, :page_count)",
            {
                "id": document_id,
                "conversation_id": conversation_id,
                "filename": "lease-agreement.pdf",
                "display_name": "lease-agreement.pdf",
                "file_path": "/uploads/lease-agreement.pdf",
                "page_count": 3,
            },
        )
    )
    return conversation_id


def test_model_declares_document_type_as_nullable_enum() -> None:
    """The ORM model itself must expose a nullable `document_type` enum column."""
    column = Document.__table__.columns["document_type"]
    assert column.nullable is True
    assert set(column.type.enums) == {"title", "lease", "environmental", "other"}


def test_migration_adds_nullable_document_type_column(reset_schema: Config) -> None:
    cfg = reset_schema
    document_id = uuid.uuid4().hex[:16]
    _seed_conversation_and_document(document_id)

    # Apply the migration under test.
    command.upgrade(cfg, "head")

    row = asyncio.run(
        _fetch_one(
            "SELECT document_type FROM documents WHERE id = :id",
            {"id": document_id},
        )
    )

    assert row.document_type is None


def test_document_type_column_accepts_each_enum_value(reset_schema: Config) -> None:
    cfg = reset_schema
    command.upgrade(cfg, "head")

    for value in ("title", "lease", "environmental", "other"):
        document_id = uuid.uuid4().hex[:16]
        _seed_conversation_and_document(document_id)
        asyncio.run(
            _run_sql(
                "UPDATE documents SET document_type = :document_type WHERE id = :id",
                {"document_type": value, "id": document_id},
            )
        )
        row = asyncio.run(
            _fetch_one(
                "SELECT document_type FROM documents WHERE id = :id",
                {"id": document_id},
            )
        )
        assert row.document_type == value


def test_document_type_column_rejects_invalid_value(reset_schema: Config) -> None:
    cfg = reset_schema
    command.upgrade(cfg, "head")
    document_id = uuid.uuid4().hex[:16]
    _seed_conversation_and_document(document_id)

    with pytest.raises(DBAPIError):
        asyncio.run(
            _run_sql(
                "UPDATE documents SET document_type = :document_type WHERE id = :id",
                {"document_type": "not-a-real-type", "id": document_id},
            )
        )


def test_migration_is_reversible(reset_schema: Config) -> None:
    cfg = reset_schema
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "002_display_name")

    async def _check_dropped() -> tuple[bool, bool]:
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                column_result = await conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name = 'documents' AND column_name = 'document_type'"
                    )
                )
                enum_result = await conn.execute(
                    text("SELECT 1 FROM pg_type WHERE typname = 'document_type'")
                )
                return column_result.first() is not None, enum_result.first() is not None
        finally:
            await engine.dispose()

    column_exists, enum_exists = asyncio.run(_check_dropped())

    assert column_exists is False
    assert enum_exists is False


def test_document_model_round_trips_document_type_enum(reset_schema: Config) -> None:
    """The ORM model round-trips `document_type` through a real session,
    including remaining `None` by default for a document not yet classified.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from takehome.db.models import Conversation

    cfg = reset_schema
    command.upgrade(cfg, "head")

    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _round_trip() -> tuple[DocumentType | None, DocumentType]:
        async with session_factory() as session:
            conversation = Conversation(id=uuid.uuid4().hex[:16], title="Test")
            session.add(conversation)
            await session.flush()

            unclassified = Document(
                id=uuid.uuid4().hex[:16],
                conversation_id=conversation.id,
                filename="unknown.pdf",
                display_name="unknown.pdf",
                file_path="/uploads/unknown.pdf",
                page_count=1,
            )
            session.add(unclassified)
            await session.flush()
            await session.refresh(unclassified)

            classified = Document(
                id=uuid.uuid4().hex[:16],
                conversation_id=conversation.id,
                filename="lease.pdf",
                display_name="lease.pdf",
                file_path="/uploads/lease.pdf",
                page_count=1,
                document_type=DocumentType.LEASE,
            )
            session.add(classified)
            await session.commit()
            await session.refresh(classified)

            return unclassified.document_type, classified.document_type

    try:
        unclassified_type, classified_type = asyncio.run(_round_trip())
    finally:
        asyncio.run(engine.dispose())

    assert unclassified_type is None
    assert classified_type == DocumentType.LEASE
