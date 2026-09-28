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
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from takehome.db.models import Fact, FactStatus


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
    re-runs stages 2 to 7 for the whole matter") -- so this deletes any
    existing rows matching this batch's own keys before inserting, rather
    than accumulating duplicate rows per key (which the `uq_facts_matter_id_
    key` constraint would reject anyway). It only touches rows whose key is
    in this batch, so one extractor's save call never deletes another
    document type's facts for the same Matter.

    Commits its own transaction, consistent with every other write in this
    codebase's service layer (see `services.matter.get_or_create_matter`'s
    own docstring for the same convention and its trade-offs).
    """
    keys = [f.key for f in facts]
    if keys:
        await session.execute(delete(Fact).where(Fact.matter_id == matter_id, Fact.key.in_(keys)))

    rows = [
        Fact(
            matter_id=matter_id,
            key=f.key,
            value=f.value,
            normalised_value=f.normalised_value,
            unit=f.unit,
            sources=[s.model_dump() for s in f.sources],
            confidence=f.confidence,
            status=f.status.value,
        )
        for f in facts
    ]
    session.add_all(rows)
    await session.commit()
    for row in rows:
        await session.refresh(row)
    return rows
