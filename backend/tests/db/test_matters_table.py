"""Tests for the `Matter` model and its migration.

Covers issue #34: `Matter` is a 1:1 extension of `Conversation` holding
risk-review gate state (`gate_result`, `gate_override_reason`). The DB-level
uniqueness constraint on `conversation_id` is what actually enforces the 1:1
relationship (the ORM relationship alone wouldn't).
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
from takehome.db.models import Matter

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
    matters migration, leaving a clean pre-migration schema for each test.

    See `test_document_display_name.py`'s identical fixture for why this uses
    a raw `DROP SCHEMA` rather than `Base.metadata.drop_all` or
    `alembic downgrade base`.
    """
    cfg = _alembic_config()
    asyncio.run(_run_sql("DROP SCHEMA public CASCADE"))
    asyncio.run(_run_sql("CREATE SCHEMA public"))
    command.upgrade(cfg, "002_display_name")
    yield cfg
    # Leave the DB migrated to head so other tests/tools see a consistent state.
    command.upgrade(cfg, "head")


def _insert_conversation(conversation_id: str) -> None:
    asyncio.run(
        _run_sql(
            "INSERT INTO conversations (id, title) VALUES (:id, :title)",
            {"id": conversation_id, "title": "Test Conversation"},
        )
    )


def test_model_declares_expected_columns() -> None:
    """The ORM model must expose the columns the ticket's acceptance criteria
    lists: id, conversation_id (unique FK), gate_result, gate_override_reason
    (nullable), created_at."""
    columns = Matter.__table__.columns

    assert columns["id"].primary_key is True

    assert columns["conversation_id"].nullable is False
    fk_targets = {fk.target_fullname for fk in columns["conversation_id"].foreign_keys}
    assert fk_targets == {"conversations.id"}

    assert columns["gate_result"].nullable is False

    assert columns["gate_override_reason"].nullable is True

    assert columns["created_at"].nullable is False


def test_conversation_id_has_unique_constraint() -> None:
    """A `conversation_id` unique constraint (or unique index) must exist on
    the table -- this is what actually enforces "one Matter per
    Conversation", not just application code."""
    table = Matter.__table__
    unique_column_sets = [
        {col.name for col in constraint.columns} for constraint in table.constraints
    ] + [{col.name for col in index.columns} for index in table.indexes if index.unique]

    assert {"conversation_id"} in unique_column_sets


def test_migration_creates_matters_table(reset_schema: Config) -> None:
    cfg = reset_schema
    command.upgrade(cfg, "head")

    conversation_id = uuid.uuid4().hex[:16]
    matter_id = uuid.uuid4().hex[:16]
    _insert_conversation(conversation_id)

    asyncio.run(
        _run_sql(
            "INSERT INTO matters (id, conversation_id, gate_result) "
            "VALUES (:id, :conversation_id, :gate_result)",
            {"id": matter_id, "conversation_id": conversation_id, "gate_result": "pass"},
        )
    )

    row = asyncio.run(
        _fetch_one(
            "SELECT gate_result, gate_override_reason FROM matters WHERE id = :id",
            {"id": matter_id},
        )
    )
    assert row.gate_result == "pass"
    assert row.gate_override_reason is None


def test_one_matter_per_conversation_is_enforced(reset_schema: Config) -> None:
    """The core acceptance criterion: a second Matter for the same
    conversation must be rejected by the DB's uniqueness constraint."""
    cfg = reset_schema
    command.upgrade(cfg, "head")

    conversation_id = uuid.uuid4().hex[:16]
    _insert_conversation(conversation_id)

    asyncio.run(
        _run_sql(
            "INSERT INTO matters (id, conversation_id, gate_result) "
            "VALUES (:id, :conversation_id, :gate_result)",
            {
                "id": uuid.uuid4().hex[:16],
                "conversation_id": conversation_id,
                "gate_result": "pass",
            },
        )
    )

    with pytest.raises((IntegrityError, DBAPIError)):
        asyncio.run(
            _run_sql(
                "INSERT INTO matters (id, conversation_id, gate_result) "
                "VALUES (:id, :conversation_id, :gate_result)",
                {
                    "id": uuid.uuid4().hex[:16],
                    "conversation_id": conversation_id,
                    "gate_result": "fail",
                },
            )
        )


def test_matters_conversation_id_requires_existing_conversation(reset_schema: Config) -> None:
    """The FK constraint must reject a matter pointing at a nonexistent
    conversation."""
    cfg = reset_schema
    command.upgrade(cfg, "head")

    with pytest.raises((IntegrityError, DBAPIError)):
        asyncio.run(
            _run_sql(
                "INSERT INTO matters (id, conversation_id, gate_result) "
                "VALUES (:id, :conversation_id, :gate_result)",
                {
                    "id": uuid.uuid4().hex[:16],
                    "conversation_id": uuid.uuid4().hex[:16],
                    "gate_result": "pass",
                },
            )
        )


def test_migration_is_reversible(reset_schema: Config) -> None:
    cfg = reset_schema
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "002_display_name")

    engine = create_async_engine(settings.database_url)

    async def _table_exists() -> bool:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT 1 FROM information_schema.tables WHERE table_name = 'matters'")
            )
            return result.first() is not None

    exists = asyncio.run(_table_exists())
    asyncio.run(engine.dispose())

    assert exists is False


def test_conversation_exposes_matter_relationship(reset_schema: Config) -> None:
    """`Conversation` must expose a `matter` relationship back to its
    (optional, at most one) `Matter`."""
    from takehome.db.models import Conversation

    assert "matter" in Conversation.__mapper__.relationships
