"""Tests for the `Fact` model and its migration.

Covers the shared `facts` table (Milestone 2, requirements doc section 7 /
PRD section 4) that issue #40 (lease core terms) and its sibling
document-type/field-subset extraction tickets (#39, #41, #42) all persist
extracted facts into, keyed by a dotted `key` namespace per Matter.
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


def _insert_fact(**kwargs: object) -> None:
    asyncio.run(
        _run_sql(
            "INSERT INTO facts (id, matter_id, key, value, normalised_value, unit, sources, "
            "confidence, status) "
            "VALUES (:id, :matter_id, :key, :value, :normalised_value, :unit, :sources, "
            ":confidence, :status)",
            kwargs,
        )
    )


def test_model_declares_expected_columns() -> None:
    """The ORM model must expose the columns the requirements doc's Fact
    wrapper lists: matter_id FK, key, value, normalised_value, unit,
    sources, confidence, status."""
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
    assert columns["updated_at"].nullable is False


def test_matter_id_and_key_have_unique_constraint() -> None:
    """A `(matter_id, key)` unique constraint must exist -- at most one
    current fact per key per Matter (re-runs replace, they don't
    accumulate)."""
    table = Fact.__table__
    unique_column_sets = [
        {col.name for col in constraint.columns} for constraint in table.constraints
    ] + [{col.name for col in index.columns} for index in table.indexes if index.unique]

    assert {"matter_id", "key"} in unique_column_sets


def test_migration_creates_facts_table(reset_schema: Config) -> None:
    cfg = reset_schema
    command.upgrade(cfg, "head")

    conversation_id = uuid.uuid4().hex[:16]
    matter_id = uuid.uuid4().hex[:16]
    fact_id = uuid.uuid4().hex[:16]
    _insert_conversation(conversation_id)
    _insert_matter(matter_id, conversation_id)

    _insert_fact(
        id=fact_id,
        matter_id=matter_id,
        key="lease.landlord.name",
        value='"Bishopsgate Property Holdings Limited"',
        normalised_value='"Bishopsgate Property Holdings Limited"',
        unit=None,
        sources="[]",
        confidence=0.95,
        status="extracted",
    )

    row = asyncio.run(
        _fetch_one(
            "SELECT key, status, confidence FROM facts WHERE id = :id",
            {"id": fact_id},
        )
    )
    assert row.key == "lease.landlord.name"
    assert row.status == "extracted"
    assert row.confidence == pytest.approx(0.95)


def test_duplicate_key_per_matter_is_rejected(reset_schema: Config) -> None:
    cfg = reset_schema
    command.upgrade(cfg, "head")

    conversation_id = uuid.uuid4().hex[:16]
    matter_id = uuid.uuid4().hex[:16]
    _insert_conversation(conversation_id)
    _insert_matter(matter_id, conversation_id)

    _insert_fact(
        id=uuid.uuid4().hex[:16],
        matter_id=matter_id,
        key="lease.term.start_date",
        value='"2024-01-01"',
        normalised_value='"2024-01-01"',
        unit=None,
        sources="[]",
        confidence=0.9,
        status="extracted",
    )

    with pytest.raises((IntegrityError, DBAPIError)):
        _insert_fact(
            id=uuid.uuid4().hex[:16],
            matter_id=matter_id,
            key="lease.term.start_date",
            value='"2024-02-01"',
            normalised_value='"2024-02-01"',
            unit=None,
            sources="[]",
            confidence=0.9,
            status="extracted",
        )


def test_facts_matter_id_requires_existing_matter(reset_schema: Config) -> None:
    cfg = reset_schema
    command.upgrade(cfg, "head")

    with pytest.raises((IntegrityError, DBAPIError)):
        _insert_fact(
            id=uuid.uuid4().hex[:16],
            matter_id=uuid.uuid4().hex[:16],
            key="lease.term.start_date",
            value='"2024-01-01"',
            normalised_value='"2024-01-01"',
            unit=None,
            sources="[]",
            confidence=0.9,
            status="extracted",
        )


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
    from takehome.db.models import Matter

    assert "facts" in Matter.__mapper__.relationships
