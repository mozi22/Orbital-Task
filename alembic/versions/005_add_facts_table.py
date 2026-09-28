"""Add facts table

Revision ID: 005_facts
Revises: 004_merge_heads
Create Date: 2026-09-28 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "005_facts"
down_revision: str | None = "004_merge_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "facts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("matter_id", sa.String(), nullable=False),
        # Dotted field name, e.g. "environmental.report_reference" -- not
        # unique alone, since a pipeline re-run inserts a fresh set of rows
        # rather than upserting in place (see the requirements doc's
        # "Re-runs" section).
        sa.Column("key", sa.String(), nullable=False),
        # `value`, `normalised_value` and `source` are JSON-encoded text --
        # kept as plain Text (not a Postgres-native JSON/JSONB column) to
        # match this schema's existing convention (see e.g.
        # `matters.gate_result`) of plain string/text columns over native
        # Postgres types.
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("normalised_value", sa.Text(), nullable=True),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        # found | not_found | needs_checking -- plain string, not a DB enum,
        # matching e.g. `matters.gate_result`'s own convention. Validated in
        # application code (`takehome.services.fact`), not at the DB level.
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["matter_id"],
            ["matters.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_facts_matter_id_key", "facts", ["matter_id", "key"])


def downgrade() -> None:
    op.drop_index("ix_facts_matter_id_key", table_name="facts")
    op.drop_table("facts")
