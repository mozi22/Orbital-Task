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

# Stored as `.value` labels ("extracted", not "EXTRACTED"), matching every
# other native enum this project defines (see `document_type`).
_FACT_STATUS_VALUES = ("extracted", "needs_checking", "not_found", "edited_by_user")


def upgrade() -> None:
    # Unlike `op.add_column` (see `003_add_document_type.py`), `op.create_table`
    # already creates any `sa.Enum` column's Postgres type itself as part of
    # the table DDL -- an extra explicit `.create()` call here would issue a
    # duplicate `CREATE TYPE` and fail.
    fact_status = sa.Enum(*_FACT_STATUS_VALUES, name="fact_status")

    op.create_table(
        "facts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("matter_id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        # Dotted, document-type-prefixed field name (e.g.
        # "title.registered_owner_name") -- see `Fact`'s own docstring for
        # why this is a plain string column, not an enum: it is shared
        # across every document type's extraction (issues #39-#42), each
        # owning its own namespace of keys, so a fixed enum here would
        # require every one of those tickets to migrate the same column.
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("normalised_value", sa.JSON(), nullable=True),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", fact_status, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["matter_id"], ["matters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_facts_matter_id", "facts", ["matter_id"])
    op.create_index("ix_facts_document_id", "facts", ["document_id"])
    op.create_index("ix_facts_key", "facts", ["key"])


def downgrade() -> None:
    op.drop_index("ix_facts_key", table_name="facts")
    op.drop_index("ix_facts_document_id", table_name="facts")
    op.drop_index("ix_facts_matter_id", table_name="facts")
    op.drop_table("facts")
    sa.Enum(name="fact_status").drop(op.get_bind(), checkfirst=True)
