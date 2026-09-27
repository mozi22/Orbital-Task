"""Add display_name to documents, backfilled from filename

Revision ID: 002_display_name
Revises: 001_initial
Create Date: 2025-01-02 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002_display_name"
down_revision: str | None = "001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add nullable first so it can coexist with existing rows, backfill, then
    # tighten to NOT NULL once every row has a value.
    op.add_column("documents", sa.Column("display_name", sa.String(), nullable=True))
    op.execute("UPDATE documents SET display_name = filename WHERE display_name IS NULL")
    op.alter_column("documents", "display_name", nullable=False)


def downgrade() -> None:
    op.drop_column("documents", "display_name")
