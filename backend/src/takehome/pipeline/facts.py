"""Shared Fact wrapper models and persistence (Milestone 2).

Every extracted fact -- regardless of document type or which parallel
ticket's extractor produced it -- goes through the same wrapper described in
the requirements doc (section 7): a value, a normalised value, its
source(s), a confidence score and a status. This module is the one shared
home for that wrapper and its persistence into the `facts` table
(`takehome.db.models.Fact`), so issue #40 (lease core terms) and the
sibling document-type/field-subset tickets running in parallel (#39 title,
#41 environmental, #42 lease remaining terms) all read/write facts the same
way rather than each re-inventing its own shape.

Deliberately minimal: no cross-document-type extraction framework lives
here (see issue #40's own ticket text -- designing one unilaterally isn't
this ticket's call to make while three sibling PRs are mid-flight on the
same area). Just the wrapper + a save function; each extractor (e.g.
`takehome.pipeline.extract_lease_core_terms`) builds `ExtractedFact`s its
own way and hands them to `save_facts`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from takehome.db.models import Fact, FactStatus

# Below this, a fact is marked `needs_checking` regardless of whether
# extraction/normalisation otherwise succeeded (requirements doc section 7:
# "confidence... Below 0.7 = needs checking"). Lives here -- not in a
# document-type-specific extractor module -- so every sibling extractor
# (#39 title, #41 environmental, #42 lease remaining terms) shares the same
# threshold instead of each redefining (and potentially drifting from) its
# own copy.
NEEDS_CHECKING_CONFIDENCE_THRESHOLD = 0.7


class SourceSpan(BaseModel):
    """Where a fact's value came from (requirements doc section 7)."""

    document_id: str
    pdf_page_index: int
    printed_page_label: str | None = None
    clause_ref: str | None = None
    quote: str = Field(max_length=500)
    char_start: int | None = None
    char_end: int | None = None


class ExtractedFact(BaseModel):
    """One extracted fact, ready to persist as a `Fact` row.

    `sources` may be empty when `status` is `NOT_FOUND` -- the requirements
    doc's "at least one, always" note doesn't hold for a fact that's
    genuinely absent from the document (there's no quote to cite for
    something that isn't there).
    """

    key: str
    value: Any = None
    normalised_value: Any = None
    unit: str | None = None
    sources: list[SourceSpan] = Field(default_factory=list[SourceSpan])
    confidence: float = Field(ge=0.0, le=1.0)
    status: FactStatus


async def save_facts(
    session: AsyncSession, matter_id: str, facts: list[ExtractedFact]
) -> list[Fact]:
    """Persist a batch of extracted facts for a Matter, replacing any
    existing rows for the same `(matter_id, key)`.

    Re-running extraction (e.g. a document was replaced) is expected to
    supersede previous facts for the same keys entirely, per the
    requirements doc's re-run semantics (section 6: "Replacing a document
    re-runs stages 2 to 7 for the whole matter"). This is implemented as a
    single atomic `INSERT ... ON CONFLICT (matter_id, key) DO UPDATE` upsert
    per row, rather than a separate delete-then-insert: a delete-then-insert
    is only race-safe for *disjoint* key namespaces (different extractors
    writing different `key` prefixes never touch each other's rows), but two
    concurrent callers writing the *same* key set (a duplicate pipeline
    trigger, a retry after a timeout, the same document re-uploaded twice)
    could otherwise both see zero existing rows under READ COMMITTED and
    then race on the insert (`IntegrityError` on `uq_facts_matter_id_key`),
    or a still-pending delete from a stale run could delete rows a
    concurrent run just committed. `ON CONFLICT DO UPDATE` makes each row's
    check-then-act atomic at the database level -- no separate row lock
    (e.g. `services.conversation.lock_conversation_for_update`'s pattern) is
    needed since Postgres itself serializes conflicting upserts on the same
    unique key. It still only touches rows whose key is in this batch, so
    one extractor's save call never deletes another document type's facts
    for the same Matter.

    The upsert statement itself carries a `RETURNING` clause, so the rows
    this function returns come back in the *same* round trip -- and the
    same transaction -- as the write itself. A separate follow-up
    `select()` after `commit()` was tried first, but that runs in its own
    transaction: under the exact concurrent-same-key race this function
    exists to handle, caller A's post-commit select can land after caller
    B's concurrent upsert has *also* committed in between, so A's select
    would silently return B's values under A's own key instead of what A
    itself just wrote. `RETURNING` on the `INSERT ... ON CONFLICT DO
    UPDATE` statement sidesteps that window entirely: Postgres documents
    `RETURNING` on an upsert as reflecting the row as it exists *after*
    the conflict resolution (i.e. the post-update values on the conflict
    branch, not the originally-attempted insert values), so what's
    returned here is guaranteed to be exactly what this call itself
    persisted.

    Commits its own transaction, consistent with every other write in this
    codebase's service layer (see `services.matter.get_or_create_matter`'s
    own docstring for the same convention and its trade-offs).
    """
    if not facts:
        return []

    values = [
        {
            "matter_id": matter_id,
            "key": f.key,
            "value": f.value,
            "normalised_value": f.normalised_value,
            "unit": f.unit,
            "sources": [s.model_dump() for s in f.sources],
            "confidence": f.confidence,
            "status": f.status.value,
        }
        for f in facts
    ]

    stmt = pg_insert(Fact).values(values)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_facts_matter_id_key",
        set_={
            "value": stmt.excluded.value,
            "normalised_value": stmt.excluded.normalised_value,
            "unit": stmt.excluded.unit,
            "sources": stmt.excluded.sources,
            "confidence": stmt.excluded.confidence,
            "status": stmt.excluded.status,
            "updated_at": func.now(),
        },
    ).returning(Fact)
    result = await session.execute(stmt)
    rows_by_key = {row.key: row for row in result.scalars().all()}
    await session.commit()
    return [rows_by_key[f.key] for f in facts]
