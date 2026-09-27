"""Tests for the `Document.display_name` column and its backfill migration.

Covers issue #9: Document gains a non-null `display_name` column, and the
migration that introduces it backfills existing rows from `filename`.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from takehome.config import settings
from takehome.db.models import Document

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
    display_name migration, leaving a clean pre-migration schema for each test.

    The wipe uses a raw `DROP SCHEMA` rather than `alembic downgrade base`:
    other test modules reset state via `Base.metadata.drop_all`, which drops
    the ORM's own tables but leaves `alembic_version` untouched, so Alembic's
    stored "current revision" can drift out of sync with what's actually in
    the database between test runs. Wiping the whole schema directly (which
    also removes `alembic_version`) makes this fixture correct regardless of
    what state prior tests left behind.
    """
    cfg = _alembic_config()
    asyncio.run(_run_sql("DROP SCHEMA public CASCADE"))
    asyncio.run(_run_sql("CREATE SCHEMA public"))
    command.upgrade(cfg, "001_initial")
    yield cfg
    # Leave the DB migrated to head so other tests/tools see a consistent state.
    command.upgrade(cfg, "head")


def test_model_declares_display_name_as_non_null_string() -> None:
    """The ORM model itself must expose a non-null `display_name: str` column."""
    column = Document.__table__.columns["display_name"]
    assert column.nullable is False
    assert column.type.python_type is str


def test_migration_adds_and_backfills_display_name_from_filename(reset_schema: Config) -> None:
    cfg = reset_schema
    conversation_id = uuid.uuid4().hex[:16]
    document_id = uuid.uuid4().hex[:16]

    # Seed rows the way they would have looked *before* display_name existed.
    asyncio.run(
        _run_sql(
            "INSERT INTO conversations (id, title) VALUES (:id, :title)",
            {"id": conversation_id, "title": "Test Conversation"},
        )
    )
    asyncio.run(
        _run_sql(
            "INSERT INTO documents (id, conversation_id, filename, file_path, page_count) "
            "VALUES (:id, :conversation_id, :filename, :file_path, :page_count)",
            {
                "id": document_id,
                "conversation_id": conversation_id,
                "filename": "lease-agreement.pdf",
                "file_path": "/uploads/lease-agreement.pdf",
                "page_count": 3,
            },
        )
    )

    # Apply the migration under test.
    command.upgrade(cfg, "head")

    row = asyncio.run(
        _fetch_one(
            "SELECT display_name, filename FROM documents WHERE id = :id",
            {"id": document_id},
        )
    )

    assert row.display_name == "lease-agreement.pdf"
    assert row.display_name == row.filename


def test_display_name_column_rejects_null_after_migration(reset_schema: Config) -> None:
    cfg = reset_schema
    command.upgrade(cfg, "head")

    conversation_id = uuid.uuid4().hex[:16]
    document_id = uuid.uuid4().hex[:16]
    asyncio.run(
        _run_sql(
            "INSERT INTO conversations (id, title) VALUES (:id, :title)",
            {"id": conversation_id, "title": "Test Conversation"},
        )
    )

    with pytest.raises((IntegrityError, DBAPIError)):
        asyncio.run(
            _run_sql(
                "INSERT INTO documents "
                "(id, conversation_id, filename, file_path, page_count) "
                "VALUES (:id, :conversation_id, :filename, :file_path, :page_count)",
                {
                    "id": document_id,
                    "conversation_id": conversation_id,
                    "filename": "no-display-name.pdf",
                    "file_path": "/uploads/no-display-name.pdf",
                    "page_count": 1,
                },
            )
        )


def test_migration_is_reversible(reset_schema: Config) -> None:
    cfg = reset_schema
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "001_initial")

    engine = create_async_engine(settings.database_url)

    async def _column_exists() -> bool:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'documents' AND column_name = 'display_name'"
                )
            )
            return result.first() is not None

    exists = asyncio.run(_column_exists())
    asyncio.run(engine.dispose())

    assert exists is False
