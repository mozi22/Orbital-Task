"""Tests for the `Fact` model and its migration.

Covers issue #41's shared scaffolding: `facts` is the table every document
type's extraction stage (title #39, lease #40/#42, environmental #41)
persists its extracted values into, one row per dotted `key` (see the
Milestone 2 PRD's data model and the requirements doc's "Extracted facts
data model", section 7).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from alembic.config import Config
from sqlalchemy.exc import DBAPIError, IntegrityError

from alembic import command
from takehome.db.models import Fact

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


def _seed_matter() -> str:
    conversation_id = uuid.uuid4().hex[:16]
    matter_id = uuid.uuid4().hex[:16]
    _insert_conversation(conversation_id)
    _insert_matter(matter_id, conversation_id)
    return matter_id


def test_model_declares_expected_columns() -> None:
    columns = Fact.__table__.columns

    assert columns["id"].primary_key is True

    assert columns["matter_id"].nullable is False
    fk_targets = {fk.target_fullname for fk in columns["matter_id"].foreign_keys}
    assert fk_targets == {"matters.id"}

    assert columns["key"].nullable is False
    assert columns["value"].nullable is True
    assert columns["normalised_value"].nullable is True
    assert columns["unit"].nullable is True
    assert columns["source"].nullable is True
    assert columns["confidence"].nullable is False
    assert columns["status"].nullable is False
    assert columns["created_at"].nullable is False


def test_migration_creates_facts_table(reset_schema: Config) -> None:
    cfg = reset_schema
    command.upgrade(cfg, "head")

    matter_id = _seed_matter()
    fact_id = uuid.uuid4().hex[:16]

    asyncio.run(
        _run_sql(
            "INSERT INTO facts (id, matter_id, key, value, confidence, status) "
            "VALUES (:id, :matter_id, :key, :value, :confidence, :status)",
            {
                "id": fact_id,
                "matter_id": matter_id,
                "key": "environmental.flood_zone",
                "value": '"2"',
                "confidence": 0.9,
                "status": "found",
            },
        )
    )

    row = asyncio.run(
        _fetch_one(
            "SELECT key, value, confidence, status FROM facts WHERE id = :id",
            {"id": fact_id},
        )
    )
    assert row.key == "environmental.flood_zone"
    assert row.value == '"2"'
    assert row.status == "found"


def test_facts_matter_id_requires_existing_matter(reset_schema: Config) -> None:
    cfg = reset_schema
    command.upgrade(cfg, "head")

    with pytest.raises((IntegrityError, DBAPIError)):
        asyncio.run(
            _run_sql(
                "INSERT INTO facts (id, matter_id, key, confidence, status) "
                "VALUES (:id, :matter_id, :key, :confidence, :status)",
                {
                    "id": uuid.uuid4().hex[:16],
                    "matter_id": uuid.uuid4().hex[:16],
                    "key": "environmental.flood_zone",
                    "confidence": 0.9,
                    "status": "not_found",
                },
            )
        )


def test_deleting_matter_cascades_to_its_facts(reset_schema: Config) -> None:
    cfg = reset_schema
    command.upgrade(cfg, "head")

    matter_id = _seed_matter()
    fact_id = uuid.uuid4().hex[:16]
    asyncio.run(
        _run_sql(
            "INSERT INTO facts (id, matter_id, key, confidence, status) "
            "VALUES (:id, :matter_id, :key, :confidence, :status)",
            {
                "id": fact_id,
                "matter_id": matter_id,
                "key": "environmental.flood_zone",
                "confidence": 0.9,
                "status": "not_found",
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


def test_multiple_facts_can_share_the_same_key(reset_schema: Config) -> None:
    """List-shaped facts (e.g. historical_uses) are one row per document per
    key, not constrained unique -- and a pipeline re-run inserts a fresh
    batch rather than upserting (see the requirements doc's "Re-runs"
    section), so the same matter can end up with more than one row for the
    same key across runs."""
    cfg = reset_schema
    command.upgrade(cfg, "head")

    matter_id = _seed_matter()
    for _ in range(2):
        asyncio.run(
            _run_sql(
                "INSERT INTO facts (id, matter_id, key, confidence, status) "
                "VALUES (:id, :matter_id, :key, :confidence, :status)",
                {
                    "id": uuid.uuid4().hex[:16],
                    "matter_id": matter_id,
                    "key": "environmental.historical_uses",
                    "confidence": 0.9,
                    "status": "found",
                },
            )
        )

    row = asyncio.run(
        _fetch_one(
            "SELECT count(*) AS n FROM facts WHERE matter_id = :matter_id",
            {"matter_id": matter_id},
        )
    )
    assert row.n == 2


def test_migration_is_reversible(reset_schema: Config) -> None:
    cfg = reset_schema
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "004_merge_heads")

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from takehome.config import settings

    async def _table_exists() -> bool:
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(
                    text("SELECT 1 FROM information_schema.tables WHERE table_name = 'facts'")
                )
                return result.first() is not None
        finally:
            await engine.dispose()

    exists = asyncio.run(_table_exists())
    assert exists is False


def test_matter_exposes_facts_relationship() -> None:
    from takehome.db.models import Matter

    assert "facts" in Matter.__mapper__.relationships
