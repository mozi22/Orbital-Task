"""Add facts table

Shared, document-type-agnostic scaffolding introduced by issue #42 (lease
fact extraction -- remaining terms): every fact-extraction stage (title,
lease, environmental) persists extracted facts against a `Matter` into this
one table, keyed by a dotted `key` string (e.g. `lease.breaks`) rather than
one column per field, per the requirements doc's Fact wrapper (section 7)
and the PRD's `facts` table (section 4).

Revision ID: 005_facts
Revises: 004_merge_heads
Create Date: 2026-09-28 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "005_facts"
down_revision: str | None = "004_merge_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Module-level singleton, reused for both `upgrade` (inline in the new
# table's column, where `op.create_table` auto-emits `CREATE TYPE` for a
# native enum it hasn't seen before -- unlike `op.add_column`, which is why
# `003_add_document_type.py`'s sibling `document_type_enum` needs an
# explicit `.create()` call and this one must *not*, to avoid emitting
# `CREATE TYPE` twice) and `downgrade` (an explicit `.drop()`, since
# `op.drop_table` alone doesn't remove the custom type).
fact_status_enum = sa.Enum(
    "extracted",
    "needs_checking",
    "not_found",
    "edited_by_user",
    name="fact_status",
)


def upgrade() -> None:
    op.create_table(
        "facts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("matter_id", sa.String(), nullable=False),
        # Dotted field name, e.g. "lease.breaks", "lease.security_of_tenure".
        sa.Column("key", sa.String(), nullable=False),
        # Value as written in the document; nullable since "not_found" is a
        # real, meaningful answer with no value to store.
        sa.Column("value", postgresql.JSONB(), nullable=True),
        # Machine-comparable form (ISO date, standardised company name,
        # etc.) -- only populated where normalisation is meaningful for
        # that field's shape.
        sa.Column("normalised_value", postgresql.JSONB(), nullable=True),
        sa.Column("unit", sa.String(), nullable=True),
        # SourceSpan[] (document, page, clause, quote) -- at least one,
        # always, per the requirements doc; defaults to an empty JSON array
        # only as a column-level fallback, never an intended real value.
        sa.Column(
            "sources",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", fact_status_enum, nullable=False),
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
    fact_status_enum.drop(op.get_bind(), checkfirst=True)
