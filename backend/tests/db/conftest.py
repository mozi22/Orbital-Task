from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from takehome.config import settings

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


@pytest.fixture(autouse=True)
def _reset_database() -> None:
    """Override the parent conftest's autouse ORM schema reset.

    Tests in this package manage the schema themselves via Alembic (see
    `reset_schema` below), stepping through specific revisions rather than
    the current model state. Letting the parent's
    `Base.metadata.create_all`/`drop_all` run first would create the tables
    outside Alembic's tracking, breaking `command.downgrade`/`upgrade`.
    """
    return None


def make_reset_schema(base_revision: str):
    """Build a `reset_schema` fixture that wipes the schema and re-applies
    migrations up to (but not including) the migration under test, leaving a
    clean pre-migration schema for each test.

    The wipe uses a raw `DROP SCHEMA` rather than `alembic downgrade base`:
    other test modules reset state via `Base.metadata.drop_all`, which drops
    the ORM's own tables but leaves `alembic_version` untouched, so Alembic's
    stored "current revision" can drift out of sync with what's actually in
    the database between test runs. Wiping the whole schema directly (which
    also removes `alembic_version`) makes this fixture correct regardless of
    what state prior tests left behind.
    """

    @pytest.fixture
    def reset_schema():
        cfg = _alembic_config()
        asyncio.run(_run_sql("DROP SCHEMA public CASCADE"))
        asyncio.run(_run_sql("CREATE SCHEMA public"))
        command.upgrade(cfg, base_revision)
        yield cfg
        # Leave the DB migrated to head so other tests/tools see a
        # consistent state.
        command.upgrade(cfg, "head")

    return reset_schema
