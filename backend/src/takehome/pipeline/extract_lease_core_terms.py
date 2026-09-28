"""Lease core-term fact extraction (Milestone 2, issue #40).

Extracts the lease identity/term/rent facts the identity gate and several
rules need: `lease_date`, `execution_status`, `is_dated`, `landlord`/
`tenant`/`guarantor`, `premises`, `term`, `rent`, `rent_review` (requirements
doc section 7's "Lease fields" list, the first 8 bullets). Deliberately
scoped to exactly those fields -- the lease's remaining fields (breaks,
alienation, repair, service charge, insurance, indemnities, security of
tenure, dispute resolution, schedules) belong to a sibling ticket (#42)
extracting the same document type in parallel, so this module stays its own
file rather than a shared `extract.py` two in-flight PRs would both need to
edit.

Per the "AI reads, code compares" design principle (requirements doc section
6), the LLM call below only extracts each field's raw value plus a
supporting quote/page/confidence -- it never itself decides whether a date
or money amount "matches" another document's. Turning each raw value into a
machine-comparable one is delegated entirely to `takehome.pipeline.
normalise` (issue #37), which has no LLM dependency of its own.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import structlog
from pydantic import BaseModel, Field
from pydantic_ai import Agent

from takehome.config import settings  # noqa: F401 -- triggers ANTHROPIC_API_KEY export
from takehome.db.models import FactStatus
from takehome.pipeline.facts import NEEDS_CHECKING_CONFIDENCE_THRESHOLD, ExtractedFact, SourceSpan
from takehome.pipeline.normalise import (
    NormalisationError,
    NormalisedArea,
    normalise_area,
    normalise_company_name,
    normalise_date,
    normalise_money,
)

logger = structlog.get_logger()

# Cap how much extracted text is sent to the extraction call, mirroring
# `services.llm.classify_document_type`'s own truncation -- a lease's core
# terms (parties, premises, term, rent) all appear in its opening clauses,
# well within this budget, so truncating keeps prompt size/cost bounded
# without losing the fields this ticket is scoped to.
_EXTRACTION_TEXT_LIMIT = 20_000


# =============================================================================
# Structured LLM output shape
# =============================================================================


class TextField(BaseModel):
    """One extracted string-valued field: its value (verbatim from the
    document), the exact quote supporting it, the page it appears on, and a
    confidence score. `value` (and `quote`/`page`) are `None` when the field
    genuinely isn't present in the document -- a real, expected answer, not
    an extraction failure."""

    value: str | None = None
    quote: str | None = None
    page: int | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class BoolField(BaseModel):
    """Like `TextField`, but for a field whose value is inherently a
    yes/no (e.g. "is this lease dated?")."""

    value: bool | None = None
    quote: str | None = None
    page: int | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ListField(BaseModel):
    """Like `TextField`, but for a field whose value is a list of strings
    (e.g. rent review dates)."""

    value: list[str] | None = None
    quote: str | None = None
    page: int | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class PartyExtraction(BaseModel):
    name: TextField = Field(default_factory=TextField)
    company_or_llp_number: TextField = Field(default_factory=TextField)


class PremisesExtraction(BaseModel):
    description: TextField = Field(default_factory=TextField)
    floors: TextField = Field(default_factory=TextField)
    net_internal_area: TextField = Field(default_factory=TextField)
    building_name: TextField = Field(default_factory=TextField)
    building_address: TextField = Field(default_factory=TextField)


class TermExtraction(BaseModel):
    length_years: TextField = Field(default_factory=TextField)
    start_date: TextField = Field(default_factory=TextField)
    end_date: TextField = Field(default_factory=TextField)


class RentExtraction(BaseModel):
    initial_annual_amount: TextField = Field(default_factory=TextField)
    vat_exclusive: BoolField = Field(default_factory=BoolField)
    payment_frequency: TextField = Field(default_factory=TextField)
    payment_dates: ListField = Field(default_factory=ListField)


class RentReviewExtraction(BaseModel):
    dates: ListField = Field(default_factory=ListField)
    basis: TextField = Field(default_factory=TextField)
    upward_only: BoolField = Field(default_factory=BoolField)


class LeaseCoreTermsExtraction(BaseModel):
    """The full structured output of one extraction call -- exactly the
    fields this ticket is scoped to, per issue #40's acceptance criteria."""

    lease_date: TextField = Field(default_factory=TextField)
    execution_status: TextField = Field(default_factory=TextField)
    is_dated: BoolField = Field(default_factory=BoolField)
    landlord: PartyExtraction = Field(default_factory=PartyExtraction)
    tenant: PartyExtraction = Field(default_factory=PartyExtraction)
    guarantor: PartyExtraction = Field(default_factory=PartyExtraction)
    premises: PremisesExtraction = Field(default_factory=PremisesExtraction)
    term: TermExtraction = Field(default_factory=TermExtraction)
    rent: RentExtraction = Field(default_factory=RentExtraction)
    rent_review: RentReviewExtraction = Field(default_factory=RentReviewExtraction)


lease_core_terms_agent = Agent(
    "anthropic:claude-sonnet-4-5-20250929",
    output_type=LeaseCoreTermsExtraction,
    system_prompt=(
        "You extract structured facts from UK commercial lease documents for "
        "a solicitor's due-diligence review. You are given the full text of "
        "one lease, with each page marked '--- Page N ---'.\n\n"
        "For every field: report its value exactly as written in the "
        "document (do not reformat dates, money, or names yourself -- "
        "normalisation happens separately in code), an exact supporting "
        "quote copied verbatim from the document (at most 500 characters), "
        "the page number it appears on (the N from the nearest preceding "
        "'--- Page N ---' marker), and your confidence in the extraction "
        "from 0 to 1.\n\n"
        "If a field is genuinely not present in the document, leave its "
        "value, quote and page as null/omitted rather than guessing -- "
        "'not found' is a normal, expected answer for fields like "
        "guarantor, which many leases simply don't have.\n\n"
        "Never fabricate a quote: every quote you give must be an exact "
        "substring of the document text you were given."
    ),
)


# =============================================================================
# Flattening + normalisation
# =============================================================================

_YEARS_RE = re.compile(r"(\d+)")


def _normalise_years(raw: str) -> int:
    """Parse a leading integer out of a free-text term length (e.g. "15
    years" -> 15). Raises `NormalisationError` if no digits are present."""
    match = _YEARS_RE.search(raw)
    if match is None:
        raise NormalisationError(f"Could not parse a year count from: {raw!r}")
    return int(match.group(1))


_TRAILING_AREA_PARENTHETICAL_RE = re.compile(r"\s*\([^()]*\)\s*$")


def _normalise_net_internal_area(raw: str):
    """Normalise a net internal area string via `normalise_area`, first
    stripping a trailing parenthetical alternate-unit figure (e.g. "About
    32,500 sq ft (3,019 m²)" -> "About 32,500 sq ft") -- these documents
    routinely give the same area in two units, and `normalise_area` only
    parses a single value+unit pair. The primary (non-parenthetical) figure
    is normalised; the parenthetical figure is not compared against it here
    (that cross-check, if wanted, belongs to a later verification stage)."""
    stripped = _TRAILING_AREA_PARENTHETICAL_RE.sub("", raw)
    return normalise_area(stripped)


def _to_fact(
    key: str,
    field: TextField | BoolField | ListField,
    document_id: str,
    *,
    normaliser: Callable[[Any], Any] | None = None,
    unit: str | None = None,
) -> ExtractedFact:
    """Turn one extracted field into an `ExtractedFact`, applying
    normalisation and the confidence/needs-checking status rules shared by
    every field this extractor produces."""
    if field.value is None:
        return ExtractedFact(
            key=key,
            value=None,
            normalised_value=None,
            unit=None,
            sources=[],
            confidence=field.confidence,
            status=FactStatus.NOT_FOUND,
        )

    sources: list[SourceSpan] = []
    if field.quote and field.page is not None:
        sources = [
            SourceSpan(
                document_id=document_id,
                pdf_page_index=field.page,
                quote=field.quote[:500],
            )
        ]

    status = FactStatus.EXTRACTED
    normalised_value: Any = field.value
    resolved_unit = unit

    if normaliser is not None:
        try:
            normalised_value = normaliser(field.value)
        except NormalisationError:
            logger.warning(
                "Fact normalisation failed, marking needs_checking",
                key=key,
                raw_value=field.value,
            )
            normalised_value = None
            status = FactStatus.NEEDS_CHECKING

    if isinstance(normalised_value, NormalisedArea):
        # `normalise_area` returns a `NormalisedArea` dataclass -- store it
        # as a plain JSON-serialisable dict, and surface its canonical unit
        # at the top level (matching every other field's `unit` column).
        area = normalised_value
        resolved_unit = area.canonical_unit
        normalised_value = {
            "value_m2": area.value_m2,
            "original_value": area.original_value,
            "unit": area.canonical_unit,
        }

    if field.confidence < NEEDS_CHECKING_CONFIDENCE_THRESHOLD:
        status = FactStatus.NEEDS_CHECKING

    return ExtractedFact(
        key=key,
        value=field.value,
        normalised_value=normalised_value,
        unit=resolved_unit,
        sources=sources,
        confidence=field.confidence,
        status=status,
    )


def _to_list_fact(key: str, field: ListField, document_id: str) -> ExtractedFact:
    """Like `_to_fact`, but for a `ListField` whose individual items are
    each normalised as dates -- used for `rent.payment_dates` and
    `rent_review.dates`. An item that fails to normalise as a date is kept
    in the normalised list as `None` rather than dropping the whole fact to
    `needs_checking`, since the other items may still be perfectly good."""
    if not field.value:
        return ExtractedFact(
            key=key,
            value=None,
            normalised_value=None,
            sources=[],
            confidence=field.confidence,
            status=FactStatus.NOT_FOUND,
        )

    sources: list[SourceSpan] = []
    if field.quote and field.page is not None:
        sources = [
            SourceSpan(document_id=document_id, pdf_page_index=field.page, quote=field.quote[:500])
        ]

    status = FactStatus.EXTRACTED
    normalised: list[str | None] = []
    for item in field.value:
        try:
            normalised.append(normalise_date(item))
        except NormalisationError:
            normalised.append(None)
            status = FactStatus.NEEDS_CHECKING

    if field.confidence < NEEDS_CHECKING_CONFIDENCE_THRESHOLD:
        status = FactStatus.NEEDS_CHECKING

    return ExtractedFact(
        key=key,
        value=field.value,
        normalised_value=normalised,
        sources=sources,
        confidence=field.confidence,
        status=status,
    )


def flatten_lease_core_terms(
    extraction: LeaseCoreTermsExtraction, document_id: str
) -> list[ExtractedFact]:
    """Turn one structured extraction result into the flat list of
    `ExtractedFact`s to persist, one per dotted `lease.*` key."""
    facts: list[ExtractedFact] = [
        _to_fact("lease.lease_date", extraction.lease_date, document_id, normaliser=normalise_date),
        _to_fact("lease.execution_status", extraction.execution_status, document_id),
        _to_fact("lease.is_dated", extraction.is_dated, document_id),
        _to_fact(
            "lease.landlord.name",
            extraction.landlord.name,
            document_id,
            normaliser=normalise_company_name,
        ),
        _to_fact(
            "lease.landlord.company_or_llp_number",
            extraction.landlord.company_or_llp_number,
            document_id,
        ),
        _to_fact(
            "lease.tenant.name",
            extraction.tenant.name,
            document_id,
            normaliser=normalise_company_name,
        ),
        _to_fact(
            "lease.tenant.company_or_llp_number",
            extraction.tenant.company_or_llp_number,
            document_id,
        ),
        _to_fact(
            "lease.guarantor.name",
            extraction.guarantor.name,
            document_id,
            normaliser=normalise_company_name,
        ),
        _to_fact(
            "lease.guarantor.company_or_llp_number",
            extraction.guarantor.company_or_llp_number,
            document_id,
        ),
        _to_fact("lease.premises.description", extraction.premises.description, document_id),
        _to_fact("lease.premises.floors", extraction.premises.floors, document_id),
        _to_fact(
            "lease.premises.net_internal_area",
            extraction.premises.net_internal_area,
            document_id,
            normaliser=_normalise_net_internal_area,
        ),
        _to_fact("lease.premises.building_name", extraction.premises.building_name, document_id),
        _to_fact(
            "lease.premises.building_address", extraction.premises.building_address, document_id
        ),
        _to_fact(
            "lease.term.length_years",
            extraction.term.length_years,
            document_id,
            normaliser=_normalise_years,
            unit="years",
        ),
        _to_fact(
            "lease.term.start_date",
            extraction.term.start_date,
            document_id,
            normaliser=normalise_date,
        ),
        _to_fact(
            "lease.term.end_date", extraction.term.end_date, document_id, normaliser=normalise_date
        ),
        _to_fact(
            "lease.rent.initial_annual_amount",
            extraction.rent.initial_annual_amount,
            document_id,
            normaliser=normalise_money,
            unit="GBP",
        ),
        _to_fact("lease.rent.vat_exclusive", extraction.rent.vat_exclusive, document_id),
        _to_fact("lease.rent.payment_frequency", extraction.rent.payment_frequency, document_id),
        _to_list_fact("lease.rent.payment_dates", extraction.rent.payment_dates, document_id),
        _to_list_fact("lease.rent_review.dates", extraction.rent_review.dates, document_id),
        _to_fact("lease.rent_review.basis", extraction.rent_review.basis, document_id),
        _to_fact("lease.rent_review.upward_only", extraction.rent_review.upward_only, document_id),
    ]
    return facts


async def extract_lease_core_terms(text: str, document_id: str) -> list[ExtractedFact]:
    """Extract this ticket's lease core-term facts from a lease's full
    extracted text, returning them ready to persist via
    `takehome.pipeline.facts.save_facts`.

    `document_id` is stamped onto every fact's `SourceSpan` so later stages
    (the identity gate, rules, quote-verification) can trace a fact back to
    the document it came from.
    """
    truncated = text[:_EXTRACTION_TEXT_LIMIT]
    result = await lease_core_terms_agent.run(
        f"Extract the lease's core terms from the following document:\n\n{truncated}"
    )
    return flatten_lease_core_terms(result.output, document_id)
