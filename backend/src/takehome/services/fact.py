"""Persistence for extracted `Fact` rows (Milestone 2, section 7's "Extracted
facts data model").

Shared scaffolding for every document type's extraction stage -- title
(#39), lease (#40/#42) and environmental (#41, this ticket) each build their
own LLM extraction schema and prompt (see `takehome.pipeline.extract_*`), but
all flatten their results into the same `NewFact` shape and persist them
through the functions here, so the `facts` table and its CRUD only need to
exist once.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from takehome.db.models import Fact

# The three statuses a Fact can carry (Milestone 2 PRD, section 4's data
# model). "not_found" is a real, meaningful answer -- many risks come from
# something being absent -- not an error (requirements doc, section 7).
FactStatus = Literal["found", "not_found", "needs_checking"]

# Below this confidence, a fact is always marked "needs_checking" regardless
# of whether it was found (requirements doc, section 6, stage 3).
NEEDS_CHECKING_CONFIDENCE_THRESHOLD = 0.7


@dataclass(frozen=True)
class NewFactSource:
    """One citation for a `NewFact` -- where in a document it came from.

    No character-offset fields: the Milestone 2 PRD notes the assignment's
    own simplified `Source` model omits them (text-highlighting a PDF page
    is explicitly out of scope this milestone).
    """

    document_id: str
    pdf_page_index: int
    quote: str
    clause_ref: str | None = None


@dataclass(frozen=True)
class NewFact:
    """One fact ready to be persisted -- the common shape every document
    type's extraction stage flattens its results into before calling
    `create_facts`.

    `value` and `normalised_value` are anything JSON-serialisable (a plain
    scalar for most keys, a list of plain dicts for list-shaped keys like
    `environmental.historical_uses`) -- serialised to the `facts` table's
    JSON-encoded `value`/`normalised_value` text columns by `create_facts`.
    """

    key: str
    value: Any
    confidence: float
    status: FactStatus
    normalised_value: Any | None = None
    unit: str | None = None
    sources: list[NewFactSource] = field(default_factory=list[NewFactSource])


def compute_status(*, value: Any, confidence: float, normalisation_failed: bool) -> FactStatus:
    """Decide a fact's `status` from its extracted value, confidence and
    whether normalisation succeeded, per the requirements doc's rules:

    - A missing value (`None`, empty string, or empty list) is "not_found"
      -- a real answer, not an error -- regardless of confidence.
    - A value code couldn't normalise is "needs_checking" -- it can't be
      compared reliably by later rules/gates, so a human must look at it,
      whatever the extraction confidence was.
    - Otherwise, confidence below `NEEDS_CHECKING_CONFIDENCE_THRESHOLD`
      (0.7) is "needs_checking"; at or above it, "found".
    """
    if value is None or value == "" or value == []:
        return "not_found"
    if normalisation_failed:
        return "needs_checking"
    if confidence < NEEDS_CHECKING_CONFIDENCE_THRESHOLD:
        return "needs_checking"
    return "found"


def _encode(value: Any | None) -> str | None:
    """JSON-encode a `NewFact.value`/`normalised_value`, leaving `None` as
    `None` (a real SQL NULL) rather than the string `"null"` -- so a later
    `SELECT ... WHERE value IS NULL` (e.g. finding not_found facts) works."""
    if value is None:
        return None
    return json.dumps(value)


def _encode_sources(sources: list[NewFactSource]) -> str | None:
    if not sources:
        return None
    return json.dumps(
        [
            {
                "document_id": s.document_id,
                "pdf_page_index": s.pdf_page_index,
                "clause_ref": s.clause_ref,
                "quote": s.quote,
            }
            for s in sources
        ]
    )


async def create_facts(session: AsyncSession, matter_id: str, facts: list[NewFact]) -> list[Fact]:
    """Persist a batch of extracted facts for a Matter in one transaction.

    Each pipeline re-run (see the requirements doc's "Re-runs" section)
    calls this again with a fresh batch -- existing rows for the same
    `matter_id`/`key` are left alone (not upserted or deleted), since
    reconciling "same fact across runs" is the report-building stage's
    concern (a later ticket), not this one's.
    """
    rows = [
        Fact(
            matter_id=matter_id,
            key=f.key,
            value=_encode(f.value),
            normalised_value=_encode(f.normalised_value),
            unit=f.unit,
            source=_encode_sources(list(f.sources)),
            confidence=f.confidence,
            status=f.status,
        )
        for f in facts
    ]
    session.add_all(rows)
    await session.commit()
    for row in rows:
        await session.refresh(row)
    return rows


async def list_facts_for_matter(session: AsyncSession, matter_id: str) -> list[Fact]:
    """Get every fact extracted so far for a Matter, in insertion order."""
    stmt = select(Fact).where(Fact.matter_id == matter_id).order_by(Fact.created_at, Fact.id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


def decode_value(raw: str | None) -> Any | None:
    """Decode a `Fact.value`/`Fact.normalised_value` column back to a Python
    value -- the inverse of `create_facts`'s JSON encoding."""
    if raw is None:
        return None
    return json.loads(raw)


def decode_sources(raw: str | None) -> list[dict[str, Any]]:
    """Decode a `Fact.source` column back to a list of source dicts -- the
    inverse of `create_facts`'s JSON encoding."""
    if raw is None:
        return []
    return json.loads(raw)
