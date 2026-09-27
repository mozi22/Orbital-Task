"""Add document_type to documents

Revision ID: 003_document_type
Revises: 002_display_name
Create Date: 2025-01-03 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003_document_type"
down_revision: str | None = "002_display_name"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

document_type_enum = sa.Enum(
    "title",
    "lease",
    "environmental",
    "other",
    name="document_type",
)


def upgrade() -> None:
    document_type_enum.create(op.get_bind(), checkfirst=True)
    # Nullable: existing rows (and every upload until classification runs)
    # have no document_type yet.
    op.add_column(
        "documents",
        sa.Column("document_type", document_type_enum, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "document_type")
    document_type_enum.drop(op.get_bind(), checkfirst=True)
