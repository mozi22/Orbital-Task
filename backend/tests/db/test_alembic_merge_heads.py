"""Tests for issue #107: the Alembic multi-head merge migration.

`003_document_type` (issue #31) and `003_matters` (issue #34) were both
branched from `002_display_name` and merged into `main-milestone-2` in
parallel without a merge migration, leaving two Alembic heads
(`003_document_type`, `003_matters`). That ambiguity broke `alembic upgrade
head`, including the app's own startup-time migration. `004_merge_heads`
reconciles the two heads back into one, without touching either
`003_document_type` or `003_matters`'s own migration bodies.
"""

from __future__ import annotations

import asyncio

from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from takehome.config import settings

from .conftest import _alembic_config, make_reset_schema

reset_schema = make_reset_schema("002_display_name")


def test_alembic_reports_exactly_one_head() -> None:
    """The core acceptance criterion: `alembic heads` must report exactly
    one head, not the two (`003_document_type`, `003_matters`) left behind
    by #31 and #34 merging in parallel without a merge migration."""
    cfg = _alembic_config()
    script = ScriptDirectory.from_config(cfg)

    heads = script.get_heads()

    assert len(heads) == 1


def test_upgrade_to_head_succeeds_from_a_fresh_database(reset_schema) -> None:
    """`alembic upgrade head` must succeed unambiguously from a schema that
    only has `002_display_name` applied -- the exact ambiguous state that
    previously raised `alembic.util.exc.CommandError: Multiple head
    revisions are present`.

    Upgrades only as far as `004_merge_heads` itself (not all the way to
    the real `head`, which has since grown past it, e.g. `005_facts`) --
    this test is specifically about the merge revision's own effect, not
    about whatever schema state later migrations add on top of it.
    """
    cfg = reset_schema

    command.upgrade(cfg, "004_merge_heads")

    async def _current_revision() -> str | None:
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(text("SELECT version_num FROM alembic_version"))
                row = result.first()
                return row[0] if row else None
        finally:
            await engine.dispose()

    current = asyncio.run(_current_revision())
    assert current == "004_merge_heads"


def test_merge_migration_makes_no_schema_changes_of_its_own(reset_schema) -> None:
    """The merge revision must be a pure merge point: it introduces no
    tables/columns of its own, and downgrading past it removes nothing that
    `003_document_type`/`003_matters` didn't already own."""
    cfg = reset_schema
    command.upgrade(cfg, "003_document_type")
    command.upgrade(cfg, "003_matters")

    async def _tables() -> set[str]:
        engine = create_async_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    )
                )
                return {row[0] for row in result.fetchall()}
        finally:
            await engine.dispose()

    tables_before_merge = asyncio.run(_tables())

    # Only as far as the merge revision itself -- not the real `head`, which
    # has since grown past it (e.g. `005_facts`), and this test is only
    # about `004_merge_heads`'s own effect on the schema.
    command.upgrade(cfg, "004_merge_heads")

    tables_after_merge = asyncio.run(_tables())

    assert tables_after_merge == tables_before_merge


def test_merge_revision_declares_both_parent_heads() -> None:
    """`004_merge_heads`'s `down_revision` must name both prior heads, per
    the acceptance criteria -- not silently pick one and drop the other."""
    cfg = _alembic_config()
    script = ScriptDirectory.from_config(cfg)

    merge_revision = script.get_revision("004_merge_heads")

    assert set(merge_revision.down_revision) == {"003_document_type", "003_matters"}
