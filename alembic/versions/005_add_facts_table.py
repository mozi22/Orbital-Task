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
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("normalised_value", sa.JSON(), nullable=True),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
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
        sa.UniqueConstraint("matter_id", "key", name="uq_facts_matter_id_key"),
    )
    op.create_index("ix_facts_matter_id", "facts", ["matter_id"])


def downgrade() -> None:
    op.drop_index("ix_facts_matter_id", table_name="facts")
    op.drop_table("facts")
