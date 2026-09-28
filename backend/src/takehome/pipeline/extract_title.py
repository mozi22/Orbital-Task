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
(see `takehome.db.models.Fact`) -- this module never reads or writes keys
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
from takehome.db.models import Document, Fact, FactStatus
from takehome.pipeline.normalise import (
    NormalisationError,
    normalise_area,
    normalise_company_name,
    normalise_date,
    normalise_money,
)

logger = structlog.get_logger()

# Below this confidence, a fact is marked "needs_checking" and surfaced to
# the solicitor for manual review (requirements doc, section 6, stage 3).
# This is applied here in code, never left to the LLM's own judgement.
NEEDS_CHECKING_THRESHOLD = 0.7

# `key` prefix every `Fact` this module writes uses, so title-report facts
# never collide with the sibling lease/environmental extraction tickets'
# own keys in the shared `facts` table.
KEY_PREFIX = "title"


# =============================================================================
# LLM output schema
# =============================================================================


class ExtractedSource(BaseModel):
    """One documented source for an extracted value (requirements doc's
    `SourceSpan`, minus `document_id`/`char_start`/`char_end` -- those are
    filled in by this module, not the LLM: `document_id` is already known
    from the document being processed, and reliable character offsets
    aren't something a language model can be trusted to report -- code
    locates the quote in the page text afterward, see `_locate_quote` and
    `_sources_to_dicts`. Locating the quote can fail (the LLM's copy of it
    may not match the extracted PDF text byte-for-byte, e.g. different
    whitespace collapsing) -- when it does, `char_start`/`char_end` are left
    `None` in the persisted source rather than guessing a position; the
    `quote`, page and clause reference are still always present for a human
    to find the passage."""

    pdf_page_index: int = Field(ge=1, description="1-based page number in the PDF")
    printed_page_label: str | None = Field(
        default=None, description='The page number printed on the page, e.g. "Page 4"'
    )
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
        "give at least one source (the 1-based PDF page number, the printed page label if "
        "shown, a clause/entry reference if there is one, and an exact quote of at most 500 "
        "characters copied verbatim from the document) for every field you did find. Never "
        "fabricate a quote -- every quote must be text that actually appears in the document.\n\n"
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


def _normalise_optional_date(raw: str | None) -> str | None:
    if raw is None:
        return None
    try:
        return normalise_date(raw)
    except NormalisationError:
        logger.warning("Could not normalise date value", raw=raw)
        return None


def _normalise_optional_money(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        return normalise_money(raw)
    except NormalisationError:
        logger.warning("Could not normalise money value", raw=raw)
        return None


def _normalise_optional_company_name(raw: str | None) -> str | None:
    if raw is None:
        return None
    try:
        return normalise_company_name(raw)
    except NormalisationError:
        logger.warning("Could not normalise company name value", raw=raw)
        return None


_TRAILING_PARENTHETICAL_RE = re.compile(r"\s*\([^()]*\)\s*$")


def _normalise_optional_area(raw: str | None) -> tuple[float | None, str | None]:
    """Returns (normalised_value_m2, unit_label), or (None, None) if the raw
    string couldn't be normalised.

    Title-report site areas in this pipeline's documents are routinely
    written with a trailing alternate-unit parenthetical (e.g. "0.34
    hectares (0.84 acres)") -- stripped here, specifically for this
    extraction module's own raw-value shape, before handing the value to
    `normalise_area` (issue #37), rather than teaching that shared utility
    a title-report-specific quirk.
    """
    if raw is None:
        return None, None
    stripped = _TRAILING_PARENTHETICAL_RE.sub("", raw).strip()
    try:
        area = normalise_area(stripped)
    except NormalisationError:
        logger.warning("Could not normalise area value", raw=raw)
        return None, None
    return area.value_m2, area.canonical_unit


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


def _normalise_scalar(field_name: str, raw_value: str | None) -> tuple[Any | None, str | None]:
    """Normalise one scalar field's raw string value, returning
    (normalised_value, unit). `unit` is only ever set for area fields."""
    if raw_value is None:
        return None, None
    if field_name in _DATE_FIELDS:
        return _normalise_optional_date(raw_value), None
    if field_name in _MONEY_FIELDS:
        return _normalise_optional_money(raw_value), "GBP"
    if field_name in _COMPANY_NAME_FIELDS:
        return _normalise_optional_company_name(raw_value), None
    if field_name in _AREA_FIELDS:
        value_m2, unit = _normalise_optional_area(raw_value)
        return value_m2, unit
    if field_name in _BOOL_FIELDS:
        return _normalise_optional_bool(raw_value), None
    return raw_value, None


# Per-list-type sub-fields to normalise inside each item's `value`/
# `normalised_value` dict, mirroring `_normalise_scalar`'s field->normaliser
# mapping above but scoped to one repeating field's item shape.
_LIST_ITEM_DATE_FIELDS = {"date"}
_LIST_ITEM_COMPANY_NAME_FIELDS = {"lender_name"}


def _normalise_list_item(raw_item: dict[str, Any]) -> dict[str, Any]:
    normalised: dict[str, Any] = {}
    for field_name, value in raw_item.items():
        if value is None:
            normalised[field_name] = None
        elif field_name in _LIST_ITEM_DATE_FIELDS and isinstance(value, str):
            normalised[field_name] = _normalise_optional_date(value)
        elif field_name in _LIST_ITEM_COMPANY_NAME_FIELDS and isinstance(value, str):
            normalised[field_name] = _normalise_optional_company_name(value)
        else:
            normalised[field_name] = value
    return normalised


def _status_for(confidence: float) -> FactStatus:
    if confidence < NEEDS_CHECKING_THRESHOLD:
        return FactStatus.NEEDS_CHECKING
    return FactStatus.EXTRACTED


# Matches the page markers `services/document.py`'s PyMuPDF extraction
# inserts into `Document.extracted_text` (e.g. "--- Page 3 ---\n...").
_PAGE_MARKER_RE = re.compile(r"--- Page (\d+) ---\n")


def _split_pages(document_text: str) -> dict[int, str]:
    """Split a document's full extracted text (as produced by
    `services/document.py`) back into its per-page text, keyed by the same
    1-based `pdf_page_index` the extraction agent reports sources against."""
    markers = list(_PAGE_MARKER_RE.finditer(document_text))
    pages: dict[int, str] = {}
    for i, marker in enumerate(markers):
        page_num = int(marker.group(1))
        start = marker.end()
        end = markers[i + 1].start() if i + 1 < len(markers) else len(document_text)
        pages[page_num] = document_text[start:end]
    return pages


def _locate_quote(page_text: str, quote: str) -> tuple[int, int] | None:
    """Find `quote`'s character offsets within `page_text`, for the
    requirements doc's `SourceSpan.char_start`/`char_end` ("position in the
    page text, for highlighting"). Returns `None` if the quote can't be
    found verbatim on that page -- e.g. the LLM's copy doesn't match the
    extracted PDF text exactly (whitespace collapsing is the common case) --
    rather than guessing a position from a fuzzy match."""
    index = page_text.find(quote)
    if index == -1:
        return None
    return index, index + len(quote)


def _sources_to_dicts(
    sources: list[ExtractedSource],
    document_id: str,
    *,
    pages: dict[int, str] | None = None,
) -> list[dict[str, Any]]:
    """Attach `document_id` (known from the document being processed, not
    something the LLM reports) to each of the LLM's reported sources, and
    locate each quote's character offsets within its page's text via
    `_locate_quote`. `pages` is the document's text already split by
    `_split_pages`; when it's not supplied (e.g. a caller with no document
    text on hand) or the quote can't be located, `char_start`/`char_end`
    are left `None` rather than fabricated."""
    dicts: list[dict[str, Any]] = []
    for source in sources:
        char_start: int | None = None
        char_end: int | None = None
        if pages is not None:
            page_text = pages.get(source.pdf_page_index)
            if page_text is not None:
                located = _locate_quote(page_text, source.quote)
                if located is not None:
                    char_start, char_end = located
        dicts.append(
            {
                "document_id": document_id,
                "pdf_page_index": source.pdf_page_index,
                "printed_page_label": source.printed_page_label,
                "clause_ref": source.clause_ref,
                "quote": source.quote,
                "char_start": char_start,
                "char_end": char_end,
            }
        )
    return dicts


def _build_scalar_fact(
    *,
    matter_id: str,
    document_id: str,
    field_name: str,
    scalar: ExtractedScalar,
    pages: dict[int, str] | None,
) -> Fact:
    key = f"{KEY_PREFIX}.{field_name}"
    if not scalar.found:
        return Fact(
            matter_id=matter_id,
            document_id=document_id,
            key=key,
            value=None,
            normalised_value=None,
            unit=None,
            sources=[],
            confidence=scalar.confidence,
            status=FactStatus.NOT_FOUND,
        )

    normalised_value, unit = _normalise_scalar(field_name, scalar.value)
    return Fact(
        matter_id=matter_id,
        document_id=document_id,
        key=key,
        value=scalar.value,
        normalised_value=normalised_value,
        unit=unit,
        sources=_sources_to_dicts(scalar.sources, document_id, pages=pages),
        confidence=scalar.confidence,
        status=_status_for(scalar.confidence),
    )


def _build_list_item_facts(
    *,
    matter_id: str,
    document_id: str,
    field_name: str,
    items: list[ExtractedListItem],
    pages: dict[int, str] | None,
) -> list[Fact]:
    key = f"{KEY_PREFIX}.{field_name}"
    facts: list[Fact] = []
    for item in items:
        facts.append(
            Fact(
                matter_id=matter_id,
                document_id=document_id,
                key=key,
                value=item.value,
                normalised_value=_normalise_list_item(item.value),
                unit=None,
                sources=_sources_to_dicts(item.sources, document_id, pages=pages),
                confidence=item.confidence,
                status=_status_for(item.confidence),
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
    matter_id: str,
    document_id: str,
    document_text: str | None = None,
) -> list[Fact]:
    """Turn one LLM extraction result into the `Fact` rows it represents,
    with normalisation already applied -- pure, no I/O, so it's testable
    without a database or a real LLM call (see `extract_title_report_facts`
    for the function that actually calls the LLM and persists these).

    `document_text` is the document's full extracted text (the same
    "--- Page N ---"-marked text the extraction agent was given), used to
    locate each source quote's character offsets via `_locate_quote`. It's
    optional -- callers that don't have it on hand (or tests that only care
    about the value/normalisation wiring) simply get sources with
    `char_start`/`char_end` left `None`."""
    pages = _split_pages(document_text) if document_text else None
    facts: list[Fact] = []
    for field_name in _SCALAR_FIELD_NAMES:
        scalar = getattr(extraction, field_name)
        facts.append(
            _build_scalar_fact(
                matter_id=matter_id,
                document_id=document_id,
                field_name=field_name,
                scalar=scalar,
                pages=pages,
            )
        )
    for field_name in _LIST_FIELD_NAMES:
        items = getattr(extraction, field_name)
        facts.extend(
            _build_list_item_facts(
                matter_id=matter_id,
                document_id=document_id,
                field_name=field_name,
                items=items,
                pages=pages,
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
    normalised `Fact` rows via `extraction_to_facts`, and commits them.

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

    facts = extraction_to_facts(
        result.output, matter_id=matter_id, document_id=document.id, document_text=text
    )
    session.add_all(facts)
    await session.commit()
    for fact in facts:
        await session.refresh(fact)

    logger.info(
        "Extracted title-report facts",
        document_id=document.id,
        matter_id=matter_id,
        fact_count=len(facts),
    )
    return facts
