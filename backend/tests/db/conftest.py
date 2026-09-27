from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_database() -> None:
    """Override the parent conftest's autouse ORM schema reset.

    Tests in this package manage the schema themselves via Alembic
    (see `reset_schema` in test_document_display_name.py), stepping through
    specific revisions rather than the current model state. Letting the
    parent's `Base.metadata.create_all`/`drop_all` run first would create the
    tables outside Alembic's tracking, breaking `command.downgrade`/`upgrade`.
    """
    return None
