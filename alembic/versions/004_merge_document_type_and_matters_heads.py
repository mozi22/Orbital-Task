"""Merge document_type and matters heads

`003_document_type` (issue #31) and `003_matters` (issue #34) were both
branched from `002_display_name` and merged into `main-milestone-2` in
parallel without a merge migration, leaving two Alembic heads
(`003_document_type`, `003_matters`). That ambiguity breaks `alembic upgrade
head`, including the app's own startup-time migration
(`command.upgrade(alembic_cfg, "head")`).

This is a pure merge point: it makes no schema changes of its own and
doesn't touch either `003_document_type` or `003_matters`'s own
`upgrade()`/`downgrade()` bodies. It only reconciles the two heads back into
one so `alembic heads` reports exactly one head again.

Revision ID: 004_merge_heads
Revises: 003_document_type, 003_matters
Create Date: 2026-09-27 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "004_merge_heads"
down_revision: str | None = ("003_document_type", "003_matters")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No schema changes -- this revision only merges the two heads."""
    pass


def downgrade() -> None:
    """No schema changes -- this revision only merges the two heads."""
    pass
