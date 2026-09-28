"""Tests for the `Fact` model and its migration.

Covers issue #39's shared scaffolding: `facts` is the table every document
type's extraction (title report here; lease and environmental in the
sibling issues #40-#42) writes its normalised, sourced values into, per the
requirements doc's section 7 "Fact" wrapper.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from alembic.config import Config
from sqlalchemy.exc import DBAPIError, IntegrityError

from alembic import command
from takehome.db.models import Document, Fact, Matter

from .conftest import _fetch_one, _run_sql, make_reset_schema

reset_schema = make_reset_schema("004_merge_heads")


def _insert_conversation(conversation_id: str) -> None:
    asyncio.run(
        _run_sql(
            "INSERT INTO conversations (id, title) VALUES (:id, :title)",
            {"id": conversation_id, "title": "Test Conversation"},
        )
    )


def _insert_matter(matter_id: str, conversation_id: str) -> None:
    asyncio.run(
        _run_sql(
            "INSERT INTO matters (id, conversation_id, gate_result) "
            "VALUES (:id, :conversation_id, :gate_result)",
            {"id": matter_id, "conversation_id": conversation_id, "gate_result": "pending"},
        )
    )


def _insert_document(document_id: str, conversation_id: str) -> None:
    asyncio.run(
        _run_sql(
            "INSERT INTO documents "
            "(id, conversation_id, filename, display_name, file_path, page_count) "
            "VALUES (:id, :conversation_id, :filename, :display_name, :file_path, :page_count)",
            {
                "id": document_id,
                "conversation_id": conversation_id,
                "filename": "title-report-lot-7.pdf",
                "display_name": "title-report-lot-7.pdf",
                "file_path": "/uploads/title-report-lot-7.pdf",
                "page_count": 3,
            },
        )
    )


def _seed_matter_and_document() -> tuple[str, str]:
    conversation_id = uuid.uuid4().hex[:16]
    matter_id = uuid.uuid4().hex[:16]
    document_id = uuid.uuid4().hex[:16]
    _insert_conversation(conversation_id)
    _insert_matter(matter_id, conversation_id)
    _insert_document(document_id, conversation_id)
    return matter_id, document_id


def test_model_declares_expected_columns() -> None:
    columns = Fact.__table__.columns

    assert columns["id"].primary_key is True

    assert columns["matter_id"].nullable is False
    assert {fk.target_fullname for fk in columns["matter_id"].foreign_keys} == {"matters.id"}

    assert columns["document_id"].nullable is False
    assert {fk.target_fullname for fk in columns["document_id"].foreign_keys} == {"documents.id"}

    assert columns["key"].nullable is False
    assert columns["value"].nullable is True
    assert columns["normalised_value"].nullable is True
    assert columns["unit"].nullable is True
    assert columns["sources"].nullable is False
    assert columns["confidence"].nullable is False
    assert columns["status"].nullable is False
    assert set(columns["status"].type.enums) == {
        "extracted",
        "needs_checking",
        "not_found",
        "edited_by_user",
    }
    assert columns["created_at"].nullable is False


def test_migration_creates_facts_table(reset_schema: Config) -> None:
    cfg = reset_schema
    command.upgrade(cfg, "head")

    matter_id, document_id = _seed_matter_and_document()
    fact_id = uuid.uuid4().hex[:16]
    sources = [
        {
            "document_id": document_id,
            "pdf_page_index": 1,
            "printed_page_label": "Page 1",
            "clause_ref": None,
            "quote": "Title Number: LN782451",
        }
    ]

    asyncio.run(
        _run_sql(
            "INSERT INTO facts "
            "(id, matter_id, document_id, key, value, normalised_value, sources, "
            "confidence, status) "
            "VALUES (:id, :matter_id, :document_id, :key, :value, :normalised_value, "
            ":sources, :confidence, :status)",
            {
                "id": fact_id,
                "matter_id": matter_id,
                "document_id": document_id,
                "key": "title.title_number",
                "value": json.dumps("LN782451"),
                "normalised_value": json.dumps("LN782451"),
                "sources": json.dumps(sources),
                "confidence": 0.98,
                "status": "extracted",
            },
        )
    )

    row = asyncio.run(
        _fetch_one(
            "SELECT key, value, confidence, status FROM facts WHERE id = :id",
            {"id": fact_id},
        )
    )
    assert row.key == "title.title_number"
    assert row.value == "LN782451"
    assert row.confidence == pytest.approx(0.98)
    assert row.status == "extracted"


def test_status_column_accepts_each_enum_value(reset_schema: Config) -> None:
    cfg = reset_schema
    command.upgrade(cfg, "head")
    matter_id, document_id = _seed_matter_and_document()

    for value in ("extracted", "needs_checking", "not_found", "edited_by_user"):
        fact_id = uuid.uuid4().hex[:16]
        asyncio.run(
            _run_sql(
                "INSERT INTO facts (id, matter_id, document_id, key, sources, confidence, status) "
                "VALUES (:id, :matter_id, :document_id, :key, :sources, :confidence, :status)",
                {
                    "id": fact_id,
                    "matter_id": matter_id,
                    "document_id": document_id,
                    "key": "title.title_number",
                    "sources": json.dumps([]),
                    "confidence": 0.5,
                    "status": value,
                },
            )
        )
        row = asyncio.run(_fetch_one("SELECT status FROM facts WHERE id = :id", {"id": fact_id}))
        assert row.status == value


def test_status_column_rejects_invalid_value(reset_schema: Config) -> None:
    cfg = reset_schema
    command.upgrade(cfg, "head")
    matter_id, document_id = _seed_matter_and_document()

    with pytest.raises(DBAPIError):
        asyncio.run(
            _run_sql(
                "INSERT INTO facts (id, matter_id, document_id, key, sources, confidence, status) "
                "VALUES (:id, :matter_id, :document_id, :key, :sources, :confidence, :status)",
                {
                    "id": uuid.uuid4().hex[:16],
                    "matter_id": matter_id,
                    "document_id": document_id,
                    "key": "title.title_number",
                    "sources": json.dumps([]),
                    "confidence": 0.5,
                    "status": "not-a-real-status",
                },
            )
        )


def test_facts_matter_id_requires_existing_matter(reset_schema: Config) -> None:
    cfg = reset_schema
    command.upgrade(cfg, "head")
    _, document_id = _seed_matter_and_document()

    with pytest.raises((IntegrityError, DBAPIError)):
        asyncio.run(
            _run_sql(
                "INSERT INTO facts (id, matter_id, document_id, key, sources, confidence, status) "
                "VALUES (:id, :matter_id, :document_id, :key, :sources, :confidence, :status)",
                {
                    "id": uuid.uuid4().hex[:16],
                    "matter_id": uuid.uuid4().hex[:16],
                    "document_id": document_id,
                    "key": "title.title_number",
                    "sources": json.dumps([]),
                    "confidence": 0.5,
                    "status": "extracted",
                },
            )
        )


def test_deleting_document_cascades_to_its_facts(reset_schema: Config) -> None:
    cfg = reset_schema
    command.upgrade(cfg, "head")
    matter_id, document_id = _seed_matter_and_document()
    fact_id = uuid.uuid4().hex[:16]
    asyncio.run(
        _run_sql(
            "INSERT INTO facts (id, matter_id, document_id, key, sources, confidence, status) "
            "VALUES (:id, :matter_id, :document_id, :key, :sources, :confidence, :status)",
            {
                "id": fact_id,
                "matter_id": matter_id,
                "document_id": document_id,
                "key": "title.title_number",
                "sources": json.dumps([]),
                "confidence": 0.5,
                "status": "extracted",
            },
        )
    )

    asyncio.run(_run_sql("DELETE FROM documents WHERE id = :id", {"id": document_id}))

    row = asyncio.run(
        _fetch_one(
            "SELECT count(*) AS n FROM facts WHERE id = :id",
            {"id": fact_id},
        )
    )
    assert row.n == 0


def test_migration_is_reversible(reset_schema: Config) -> None:
    cfg = reset_schema
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "004_merge_heads")

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from takehome.config import settings

    engine = create_async_engine(settings.database_url)

    async def _check_dropped() -> tuple[bool, bool]:
        async with engine.connect() as conn:
            table_result = await conn.execute(
                text("SELECT 1 FROM information_schema.tables WHERE table_name = 'facts'")
            )
            enum_result = await conn.execute(
                text("SELECT 1 FROM pg_type WHERE typname = 'fact_status'")
            )
            return table_result.first() is not None, enum_result.first() is not None

    table_exists, enum_exists = asyncio.run(_check_dropped())
    asyncio.run(engine.dispose())

    assert table_exists is False
    assert enum_exists is False


def test_matter_and_document_expose_facts_relationship() -> None:
    assert "facts" in Matter.__mapper__.relationships
    assert "facts" in Document.__mapper__.relationships
