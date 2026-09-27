"""Add matters table

Revision ID: 003_matters
Revises: 002_display_name
Create Date: 2026-09-27 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003_matters"
down_revision: str | None = "002_display_name"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "matters",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        # pass | fail | overridden -- kept as a plain string (not a DB enum)
        # to match the rest of this schema's convention (see e.g.
        # `messages.role`, `documents.filename`), which also uses a plain
        # string rather than a Postgres ENUM type. Validating that this
        # column only holds one of those three values in application code
        # is deferred to whichever future ticket adds the risk-review gate
        # logic itself; no such validation exists yet.
        sa.Column("gate_result", sa.String(), nullable=False),
        sa.Column("gate_override_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("conversation_id", name="uq_matters_conversation_id"),
    )


def downgrade() -> None:
    op.drop_table("matters")
