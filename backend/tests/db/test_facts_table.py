"""Tests for the `Fact` model and its migration.

Covers the shared `facts` table this ticket (issue #42, lease remaining
terms) introduces: document-type-agnostic scaffolding for every extraction
stage (title/lease/environmental) to persist extracted facts against a
`Matter`, keyed by a dotted `key` string rather than one column per field
(see `Fact`'s docstring in `takehome.db.models`).
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
from takehome.db.models import Fact, FactStatus, Matter

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
            {"id": matter_id, "conversation_id": conversation_id, "gate_result": "pass"},
        )
    )


def test_model_declares_expected_columns() -> None:
    """The ORM model must expose the columns the requirements doc's Fact
    wrapper (section 7) and the PRD's `facts` table (section 4) call for:
    id, matter_id (FK), key, value, normalised_value, unit, sources,
    confidence, status, created_at."""
    columns = Fact.__table__.columns

    assert columns["id"].primary_key is True

    assert columns["matter_id"].nullable is False
    fk_targets = {fk.target_fullname for fk in columns["matter_id"].foreign_keys}
    assert fk_targets == {"matters.id"}

    assert columns["key"].nullable is False
    assert columns["value"].nullable is True
    assert columns["normalised_value"].nullable is True
    assert columns["unit"].nullable is True
    assert columns["sources"].nullable is False
    assert columns["confidence"].nullable is False
    assert columns["status"].nullable is False
    assert columns["created_at"].nullable is False


def test_migration_creates_facts_table(reset_schema: Config) -> None:
    cfg = reset_schema
    command.upgrade(cfg, "head")

    conversation_id = uuid.uuid4().hex[:16]
    matter_id = uuid.uuid4().hex[:16]
    fact_id = uuid.uuid4().hex[:16]
    _insert_conversation(conversation_id)
    _insert_matter(matter_id, conversation_id)

    asyncio.run(
        _run_sql(
            "INSERT INTO facts (id, matter_id, key, value, sources, confidence, status) "
            "VALUES (:id, :matter_id, :key, :value, :sources, :confidence, :status)",
            {
                "id": fact_id,
                "matter_id": matter_id,
                "key": "lease.permitted_use",
                "value": '{"text": "Offices, Class E(g)(i)"}',
                "sources": "[]",
                "confidence": 0.95,
                "status": "extracted",
            },
        )
    )

    row = asyncio.run(
        _fetch_one(
            "SELECT key, confidence, status FROM facts WHERE id = :id",
            {"id": fact_id},
        )
    )
    assert row.key == "lease.permitted_use"
    assert row.confidence == pytest.approx(0.95)
    assert row.status == "extracted"


def test_facts_matter_id_requires_existing_matter(reset_schema: Config) -> None:
    cfg = reset_schema
    command.upgrade(cfg, "head")

    with pytest.raises((IntegrityError, DBAPIError)):
        asyncio.run(
            _run_sql(
                "INSERT INTO facts (id, matter_id, key, sources, confidence, status) "
                "VALUES (:id, :matter_id, :key, :sources, :confidence, :status)",
                {
                    "id": uuid.uuid4().hex[:16],
                    "matter_id": uuid.uuid4().hex[:16],
                    "key": "lease.breaks",
                    "sources": "[]",
                    "confidence": 0.5,
                    "status": "not_found",
                },
            )
        )


def test_deleting_matter_cascades_to_facts(reset_schema: Config) -> None:
    cfg = reset_schema
    command.upgrade(cfg, "head")

    conversation_id = uuid.uuid4().hex[:16]
    matter_id = uuid.uuid4().hex[:16]
    fact_id = uuid.uuid4().hex[:16]
    _insert_conversation(conversation_id)
    _insert_matter(matter_id, conversation_id)

    asyncio.run(
        _run_sql(
            "INSERT INTO facts (id, matter_id, key, sources, confidence, status) "
            "VALUES (:id, :matter_id, :key, :sources, :confidence, :status)",
            {
                "id": fact_id,
                "matter_id": matter_id,
                "key": "lease.repair",
                "sources": "[]",
                "confidence": 0.9,
                "status": "extracted",
            },
        )
    )

    asyncio.run(_run_sql("DELETE FROM matters WHERE id = :id", {"id": matter_id}))

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

    engine = create_async_engine(settings.database_url)

    async def _table_exists() -> bool:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT 1 FROM information_schema.tables WHERE table_name = 'facts'")
            )
            return result.first() is not None

    exists = asyncio.run(_table_exists())
    asyncio.run(engine.dispose())

    assert exists is False


def test_matter_exposes_facts_relationship() -> None:
    """`Matter` must expose a `facts` relationship back to its `Fact` rows."""
    assert "facts" in Matter.__mapper__.relationships


def test_fact_status_enum_has_expected_members() -> None:
    assert {member.value for member in FactStatus} == {
        "extracted",
        "needs_checking",
        "not_found",
        "edited_by_user",
    }
