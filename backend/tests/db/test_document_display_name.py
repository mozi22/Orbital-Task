"""Tests for the `Document.display_name` column and its backfill migration.

Covers issue #9: Document gains a non-null `display_name` column, and the
migration that introduces it backfills existing rows from `filename`.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from takehome.config import settings
from takehome.db.models import Document

from .conftest import _fetch_one, _run_sql, make_reset_schema

reset_schema = make_reset_schema("001_initial")


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
