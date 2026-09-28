"""Title-report fact extraction (Milestone 2, issue #39).

Reads a `DocumentType.TITLE` document's extracted PDF text with an LLM
(Sonnet, per the Milestone 2 PRD -- misreading a clause here produces a
wrong severity flag a solicitor relies on, so extraction uses the stronger
model even though chat Q&A stays on Haiku) and turns it into `Fact` rows
covering every title-report field listed in the requirements doc, section 7:
title_number, edition_date, as_at_datetime, is_summary, tenure, title_class,
property (address, postcode, description, site area, boundaries, building),
registered_owner, price_paid, charges[], restrictive_covenants[],
easements[], noted_entries[], cautions_and_restrictions[].

This module only extracts and persists *title-report* facts. Lease and
environmental-report extraction are separate, parallel tickets (#40-#42)
that write their own `key` namespace into the same shared `facts` table
(see `takehome.services.fact`) -- this module never reads or writes keys
outside the `title.` prefix.

Per the "AI reads, code compares" design principle (requirements doc,
section 6): the LLM's job here is purely to *read* -- pull out each field's
raw value plus its exact source quote and a confidence score. Normalising
those raw values into a machine-comparable form (dates, money, company
names, areas) is ordinary, independently-tested code (`pipeline.normalise`,
issue #37), not the LLM's judgement.
"""

from __future__ import annotations

import re
from typing import Any

import structlog
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from sqlalchemy.ext.asyncio import AsyncSession

from takehome.config import settings  # noqa: F401 -- triggers ANTHROPIC_API_KEY export
from takehome.db.models import Document, Fact
from takehome.pipeline.normalise import (
    NormalisationError,
    normalise_area,
    normalise_company_name,
    normalise_date,
    normalise_money,
)
from takehome.services.fact import NewFact, NewFactSource, compute_status, create_facts

logger = structlog.get_logger()

# `key` prefix every `Fact` this module writes uses, so title-report facts
# never collide with the sibling lease/environmental extraction tickets'
# own keys in the shared `facts` table.
KEY_PREFIX = "title"


# =============================================================================
# LLM output schema
# =============================================================================


class ExtractedSource(BaseModel):
    """One documented source for an extracted value (requirements doc's
    `SourceSpan`, minus `document_id` -- that's already known from the
    document being processed, filled in by this module rather than the LLM,
    see `_sources_to_new_sources`). No character-offset fields: the
    Milestone 2 PRD notes the assignment's own simplified `Source` model
    omits them (text-highlighting a PDF page is explicitly out of scope
    this milestone)."""

    pdf_page_index: int = Field(ge=1, description="1-based page number in the PDF")
    clause_ref: str | None = Field(
        default=None, description='e.g. "8.3.1", "Charges Register entry 1"'
    )
    quote: str = Field(max_length=500, description="Exact text copied from the document")


class ExtractedScalar(BaseModel):
    """Wrapper for one scalar title-report field, e.g. `title_number` or
    `registered_owner_name`. `found=False` means the field genuinely isn't
    present in this document -- a real answer (see `Fact`'s docstring on
    `not_found`), not an extraction failure."""

    found: bool = Field(description="False if this field isn't present in the document at all")
    value: str | None = Field(
        default=None, description="The value exactly as written in the document"
    )
    confidence: float = Field(ge=0, le=1)
    sources: list[ExtractedSource] = Field(default_factory=lambda: list[ExtractedSource]())


class ChargeItem(BaseModel):
    entry_number: str | None = None
    date: str | None = None
    lender_name: str | None = None
    lender_company_number: str | None = None
    secures_further_advances: bool | None = None


class RestrictiveCovenantItem(BaseModel):
    date: str | None = None
    parties: str | None = None
    full_text: str | None = None
    category: str | None = Field(
        default=None, description="One of: use, height, boundary, building, other"
    )
    parsed_limits: str | None = Field(
        default=None,
        description='Machine-readable limits pulled from full_text, e.g. "max_storeys: 4; '
        'banned_uses: industrial, manufacturing, heavy commercial"',
    )


class EasementItem(BaseModel):
    type: str | None = Field(
        default=None, description="One of: right_of_way, drainage, light, support, other"
    )
    benefit_or_burden: str | None = None
    route_description: str | None = None
    obligations: str | None = None


class NotedEntryItem(BaseModel):
    type: str | None = Field(
        default=None, description="One of: planning_permission, s106_agreement, lease, other"
    )
    reference: str | None = None
    date: str | None = None
    summary: str | None = None
    obligations: str | None = Field(
        default=None, description="Free-text summary of any obligations[] this entry lists"
    )


class ExtractedListItem(BaseModel):
    """One element of a repeating title-report field (one charge, one
    covenant, etc). `value` is one of the item schemas above, serialised as
    a plain dict so this one wrapper covers every repeating field without a
    separate wrapper class per item type."""

    value: dict[str, Any]
    confidence: float = Field(ge=0, le=1)
    sources: list[ExtractedSource] = Field(default_factory=lambda: list[ExtractedSource]())


class CautionItem(BaseModel):
    text: str


class TitleReportExtraction(BaseModel):
    """The full set of title-report facts extracted from one document,
    per the requirements doc, section 7 ("Title report fields")."""

    title_number: ExtractedScalar
    edition_date: ExtractedScalar
    as_at_datetime: ExtractedScalar
    is_summary: ExtractedScalar = Field(
        description='value should be the literal string "true" or "false": true if this is not '
        "the full official register (e.g. it says it can't be relied on under s.67 Land "
        "Registration Act 2002)"
    )
    tenure: ExtractedScalar = Field(description="freehold or leasehold")
    title_class: ExtractedScalar = Field(description="e.g. absolute")

    property_address: ExtractedScalar
    property_postcode: ExtractedScalar
    property_description: ExtractedScalar
    property_site_area: ExtractedScalar
    property_boundary_north: ExtractedScalar
    property_boundary_east: ExtractedScalar
    property_boundary_south: ExtractedScalar
    property_boundary_west: ExtractedScalar
    property_building_storeys: ExtractedScalar
    property_building_gross_internal_area: ExtractedScalar
    property_building_use: ExtractedScalar

    registered_owner_name: ExtractedScalar
    registered_owner_company_number: ExtractedScalar
    registered_owner_registered_office: ExtractedScalar
    registered_owner_registered_since: ExtractedScalar

    price_paid_amount: ExtractedScalar
    price_paid_date: ExtractedScalar

    charges: list[ExtractedListItem] = Field(default_factory=lambda: list[ExtractedListItem]())
    restrictive_covenants: list[ExtractedListItem] = Field(
        default_factory=lambda: list[ExtractedListItem]()
    )
    easements: list[ExtractedListItem] = Field(default_factory=lambda: list[ExtractedListItem]())
    noted_entries: list[ExtractedListItem] = Field(
        default_factory=lambda: list[ExtractedListItem]()
    )
    cautions_and_restrictions: list[ExtractedListItem] = Field(
        default_factory=lambda: list[ExtractedListItem]()
    )


# =============================================================================
# Agent
# =============================================================================

# A distinct Agent (Sonnet, not the Haiku `agent`/`classification_agent` in
# `services/llm.py`) since extraction quality here directly drives which
# risk flags a solicitor sees -- per the Milestone 2 PRD's explicit model
# choice for extraction, gate checks and judgement-based rules.
title_extraction_agent = Agent(
    "anthropic:claude-sonnet-4-5-20250929",
    output_type=TitleReportExtraction,
    system_prompt=(
        "You extract structured facts from a UK commercial property title report for a "
        "law firm's due-diligence pipeline. You are given the report's full text, with "
        "each page marked '--- Page N ---'.\n\n"
        "For every field: report the value exactly as written in the document (do not "
        "normalise dates, money or units yourself -- copy them verbatim), set found=false "
        "if the field genuinely isn't present anywhere in the document, give a confidence "
        "from 0 to 1 reflecting how certain you are the value is correct and complete, and "
        "give at least one source (the 1-based PDF page number, a clause/entry reference if "
        "there is one, and an exact quote of at most 500 characters copied verbatim from the "
        "document) for every field you did find. Never fabricate a quote -- every quote must "
        "be text that actually appears in the document.\n\n"
        "For repeating fields (charges, restrictive_covenants, easements, noted_entries, "
        "cautions_and_restrictions), return one list item per entry found in the document, "
        "an empty list if none are present -- an empty list is a meaningful, correct answer, "
        "not a missing one."
    ),
)

# Cap how much extracted text is sent to the extraction call. Title reports
# in this pipeline's scope are short (a handful of pages); this bound
# guards against an unexpectedly long document blowing the prompt budget
# without ever needing to trigger in practice for real fixtures.
_EXTRACTION_TEXT_LIMIT = 60_000


# =============================================================================
# Normalisation wiring
# =============================================================================


def _normalise_optional_date(raw: str | None) -> tuple[str | None, bool]:
    """Returns (normalised_value, normalisation_failed)."""
    if raw is None:
        return None, False
    try:
        return normalise_date(raw), False
    except NormalisationError:
        logger.warning("Could not normalise date value", raw=raw)
        return None, True


def _normalise_optional_money(raw: str | None) -> tuple[int | None, bool]:
    """Returns (pence, normalisation_failed)."""
    if raw is None:
        return None, False
    try:
        return normalise_money(raw), False
    except NormalisationError:
        logger.warning("Could not normalise money value", raw=raw)
        return None, True


def _normalise_optional_company_name(raw: str | None) -> str | None:
    """Company-name normalisation never raises `NormalisationError` (see
    `pipeline.normalise.normalise_company_name`'s docstring -- an
    unrecognised suffix, or no suffix at all, is returned unchanged rather
    than failing), so unlike the date/money/area normalisers this has no
    `normalisation_failed` outcome to report."""
    if raw is None:
        return None
    return normalise_company_name(raw)


_TRAILING_PARENTHETICAL_RE = re.compile(r"\s*\([^()]*\)\s*$")


def _normalise_optional_area(raw: str | None) -> tuple[float | None, str | None, bool]:
    """Returns (value_m2, canonical_unit, normalisation_failed).

    Title-report site areas in this pipeline's documents are routinely
    written with a trailing alternate-unit parenthetical (e.g. "0.34
    hectares (0.84 acres)") -- stripped here, specifically for this
    extraction module's own raw-value shape, before handing the value to
    `normalise_area` (issue #37), rather than teaching that shared utility
    a title-report-specific quirk.
    """
    if raw is None:
        return None, None, False
    stripped = _TRAILING_PARENTHETICAL_RE.sub("", raw).strip()
    try:
        area = normalise_area(stripped)
    except NormalisationError:
        logger.warning("Could not normalise area value", raw=raw)
        return None, None, True
    return area.value_m2, area.canonical_unit, False


def _normalise_optional_bool(raw: str | None) -> bool | None:
    if raw is None:
        return None
    return raw.strip().lower() in ("true", "yes")


# Which normaliser (if any) applies to each scalar field's raw string value.
# Fields absent from this mapping (e.g. company numbers, postcodes -- no
# normaliser exists for either yet) are copied through unchanged: this
# module only wires up the normalisers issue #37 already built, per this
# ticket's own acceptance criteria ("normalised ... via #3.1"), rather than
# inventing new ones.
_DATE_FIELDS = {"edition_date", "registered_owner_registered_since", "price_paid_date"}
_MONEY_FIELDS = {"price_paid_amount"}
_COMPANY_NAME_FIELDS = {"registered_owner_name"}
_AREA_FIELDS = {"property_site_area", "property_building_gross_internal_area"}
_BOOL_FIELDS = {"is_summary"}


def _normalise_scalar(
    field_name: str, raw_value: str | None
) -> tuple[Any | None, str | None, bool]:
    """Normalise one scalar field's raw string value, returning
    (normalised_value, unit, normalisation_failed). `unit` is only ever set
    for area fields."""
    if raw_value is None:
        return None, None, False
    if field_name in _DATE_FIELDS:
        value, failed = _normalise_optional_date(raw_value)
        return value, None, failed
    if field_name in _MONEY_FIELDS:
        value, failed = _normalise_optional_money(raw_value)
        return value, "GBP", failed
    if field_name in _COMPANY_NAME_FIELDS:
        return _normalise_optional_company_name(raw_value), None, False
    if field_name in _AREA_FIELDS:
        value_m2, unit, failed = _normalise_optional_area(raw_value)
        return value_m2, unit, failed
    if field_name in _BOOL_FIELDS:
        return _normalise_optional_bool(raw_value), None, False
    return raw_value, None, False


# Per-list-type sub-fields to normalise inside each item's `value`/
# `normalised_value` dict, mirroring `_normalise_scalar`'s field->normaliser
# mapping above but scoped to one repeating field's item shape.
_LIST_ITEM_DATE_FIELDS = {"date"}
_LIST_ITEM_COMPANY_NAME_FIELDS = {"lender_name"}


def _normalise_list_item(raw_item: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Returns (normalised_item, normalisation_failed) -- `failed` is set if
    any sub-field with a normaliser couldn't be normalised."""
    normalised: dict[str, Any] = {}
    any_failed = False
    for field_name, value in raw_item.items():
        if value is None:
            normalised[field_name] = None
        elif field_name in _LIST_ITEM_DATE_FIELDS and isinstance(value, str):
            normalised_value, failed = _normalise_optional_date(value)
            normalised[field_name] = normalised_value
            any_failed = any_failed or failed
        elif field_name in _LIST_ITEM_COMPANY_NAME_FIELDS and isinstance(value, str):
            normalised[field_name] = _normalise_optional_company_name(value)
        else:
            normalised[field_name] = value
    return normalised, any_failed


def _sources_to_new_sources(
    sources: list[ExtractedSource], document_id: str
) -> list[NewFactSource]:
    """Attach `document_id` (known from the document being processed, not
    something the LLM reports) to each of the LLM's reported sources."""
    return [
        NewFactSource(
            document_id=document_id,
            pdf_page_index=source.pdf_page_index,
            clause_ref=source.clause_ref,
            quote=source.quote,
        )
        for source in sources
    ]


def _build_scalar_fact(
    *,
    document_id: str,
    field_name: str,
    scalar: ExtractedScalar,
) -> NewFact:
    key = f"{KEY_PREFIX}.{field_name}"
    if not scalar.found:
        return NewFact(
            key=key,
            value=None,
            normalised_value=None,
            unit=None,
            sources=[],
            confidence=scalar.confidence,
            status=compute_status(value=None, confidence=scalar.confidence, normalisation_failed=False),
        )

    normalised_value, unit, normalisation_failed = _normalise_scalar(field_name, scalar.value)
    return NewFact(
        key=key,
        value=scalar.value,
        normalised_value=normalised_value,
        unit=unit,
        sources=_sources_to_new_sources(scalar.sources, document_id),
        confidence=scalar.confidence,
        status=compute_status(
            value=scalar.value,
            confidence=scalar.confidence,
            normalisation_failed=normalisation_failed,
        ),
    )


def _build_list_item_facts(
    *,
    document_id: str,
    field_name: str,
    items: list[ExtractedListItem],
) -> list[NewFact]:
    key = f"{KEY_PREFIX}.{field_name}"
    facts: list[NewFact] = []
    for item in items:
        normalised_value, normalisation_failed = _normalise_list_item(item.value)
        facts.append(
            NewFact(
                key=key,
                value=item.value,
                normalised_value=normalised_value,
                unit=None,
                sources=_sources_to_new_sources(item.sources, document_id),
                confidence=item.confidence,
                status=compute_status(
                    value=item.value,
                    confidence=item.confidence,
                    normalisation_failed=normalisation_failed,
                ),
            )
        )
    return facts


# Every scalar (`ExtractedScalar`) and repeating (`list[ExtractedListItem]`)
# field on `TitleReportExtraction`, in declaration order -- derived from the
# model itself (rather than hand-copied) so adding a field there is the only
# change needed for `extraction_to_facts` to also persist it: nothing here
# can silently drift out of sync with the model and drop a field.
_SCALAR_FIELD_NAMES = [
    name
    for name, field in TitleReportExtraction.model_fields.items()
    if field.annotation is ExtractedScalar
]
_LIST_FIELD_NAMES = [
    name
    for name, field in TitleReportExtraction.model_fields.items()
    if field.annotation == list[ExtractedListItem]
]


def extraction_to_facts(
    extraction: TitleReportExtraction,
    *,
    document_id: str,
) -> list[NewFact]:
    """Turn one LLM extraction result into the `NewFact`s it represents,
    with normalisation already applied -- pure, no I/O, so it's testable
    without a database or a real LLM call (see `extract_title_report_facts`
    for the function that actually calls the LLM and persists these via
    `takehome.services.fact.create_facts`)."""
    facts: list[NewFact] = []
    for field_name in _SCALAR_FIELD_NAMES:
        scalar = getattr(extraction, field_name)
        facts.append(
            _build_scalar_fact(
                document_id=document_id,
                field_name=field_name,
                scalar=scalar,
            )
        )
    for field_name in _LIST_FIELD_NAMES:
        items = getattr(extraction, field_name)
        facts.extend(
            _build_list_item_facts(
                document_id=document_id,
                field_name=field_name,
                items=items,
            )
        )
    return facts


async def extract_title_report_facts(
    session: AsyncSession, *, matter_id: str, document: Document
) -> list[Fact]:
    """Extract and persist every title-report fact for `document`.

    Calls the Sonnet-backed extraction agent with the document's already-
    extracted PDF text (see `services/document.py`'s PyMuPDF extraction,
    reused unchanged here per the Milestone 2 PRD), converts the result into
    normalised `NewFact`s via `extraction_to_facts`, and persists them via
    `takehome.services.fact.create_facts`.

    Returns the created `Fact` rows (already persisted). Returns an empty
    list without calling the LLM if `document.extracted_text` is empty --
    there is nothing to extract facts from.
    """
    text = document.extracted_text
    if not text or not text.strip():
        logger.warning(
            "No extracted text to run title-report extraction against",
            document_id=document.id,
        )
        return []

    truncated = text[:_EXTRACTION_TEXT_LIMIT]
    result = await title_extraction_agent.run(
        f"Extract title-report facts from the following document:\n\n{truncated}"
    )

    new_facts = extraction_to_facts(result.output, document_id=document.id)
    facts = await create_facts(session, matter_id, new_facts)

    logger.info(
        "Extracted title-report facts",
        document_id=document.id,
        matter_id=matter_id,
        fact_count=len(facts),
    )
    return facts
