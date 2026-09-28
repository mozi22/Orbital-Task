"""Environmental report fact extraction (Milestone 2, issue #41).

Fills the "Environmental report fields" part of the extracted facts data
model (requirements doc, section 7) from an environmental report's extracted
text: report metadata, reliance, site, historical uses, geology/water,
flood risk, contamination register status, pollution incidents, air quality
management area, storage tanks, overall risk rating/recommendations and
cost estimates.

Follows the "AI reads, code compares" design principle (section 6): the LLM
(`environmental_extraction_agent`, Sonnet per the Milestone 2 PRD -- a
misread clause here produces a wrong severity flag a solicitor relies on,
not just an awkward chat reply) only reads the document and returns a
strict, quoted, structured extraction. Normalising those raw values into a
machine-comparable form (dates, money, areas, company names) is ordinary,
LLM-free code (`flatten_environmental_facts`, using
`takehome.pipeline.normalise`), independently testable from the LLM call
itself.

Two composite groups (`site`/`buildings` and each list item) share one
confidence/source between the handful of scalar fields they naturally
appear together in on the page (e.g. report reference, date, consultant and
client name are usually one header block) -- a deliberate simplification
given the assignment's own simplified data model, not full per-leaf-field
citation. Each list-shaped fact (`historical_uses`, `pollution_incidents`,
`storage_tanks`, `cost_estimates`) still cites one source per list item.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from takehome.pipeline.normalise import (
    NormalisationError,
    normalise_area,
    normalise_company_name,
    normalise_date,
    normalise_money,
)
from takehome.services.fact import NewFact, NewFactSource, compute_status

# =============================================================================
# LLM extraction schema
# =============================================================================


class SourceSpan(BaseModel):
    """Where an extracted value came from -- one page/clause/quote citation.

    No character-offset fields (see this module's docstring): the
    Milestone 2 PRD notes the assignment's own simplified `Source` model
    omits them.
    """

    pdf_page_index: int = Field(description="1-based page number in the PDF this was found on")
    clause_ref: str | None = Field(
        default=None, description='e.g. "Section 3.2", "Appendix B" -- null if not applicable'
    )
    quote: str = Field(description="Exact text copied from the document, max 500 characters")


class ReportMetadata(BaseModel):
    report_reference: str | None = None
    report_date: str | None = None
    consultant: str | None = None
    authors: str | None = None
    client_name: str | None = None
    confidence: float = Field(ge=0, le=1)
    source: SourceSpan | None = None


class Reliance(BaseModel):
    who_may_rely: list[str] = Field(default_factory=list[str])
    third_party_reliance_allowed: bool | None = None
    confidence: float = Field(ge=0, le=1)
    source: SourceSpan | None = None


class Buildings(BaseModel):
    storeys: int | None = None
    gross_internal_area_m2: str | None = Field(
        default=None, description='As written, e.g. "about 2,400 m2"'
    )
    construction_year: int | None = None


class Site(BaseModel):
    address: str | None = None
    postcode: str | None = None
    area_m2: str | None = Field(default=None, description='As written, e.g. "about 0.28 ha"')
    buildings: Buildings | None = None
    confidence: float = Field(ge=0, le=1)
    source: SourceSpan | None = None


class HistoricalUse(BaseModel):
    from_year: int | None = None
    to_year: int | None = None
    use: str
    potentially_contaminative: bool
    confidence: float = Field(ge=0, le=1)
    source: SourceSpan


class GeologyWater(BaseModel):
    geology_summary: str | None = None
    aquifer_classification: str | None = None
    nearest_watercourse_name: str | None = None
    nearest_watercourse_distance_m: float | None = None
    confidence: float = Field(ge=0, le=1)
    source: SourceSpan | None = None


class FloodRisk(BaseModel):
    flood_zone: str | None = Field(default=None, description='"1", "2" or "3"')
    flood_defences: bool | None = None
    confidence: float = Field(ge=0, le=1)
    source: SourceSpan | None = None


class ContaminationStatus(BaseModel):
    contaminated_land_register_status: str | None = None
    air_quality_management_area: bool | None = None
    confidence: float = Field(ge=0, le=1)
    source: SourceSpan | None = None


class PollutionIncident(BaseModel):
    year: int | None = None
    type: str
    distance_m: float | None = None
    status: str | None = None
    confidence: float = Field(ge=0, le=1)
    source: SourceSpan


class StorageTank(BaseModel):
    location: str
    contents: str | None = None
    capacity_litres: float | None = None
    status: str = Field(description='"removed", "in situ" or "unknown"')
    confidence: float = Field(ge=0, le=1)
    source: SourceSpan


class OverallRisk(BaseModel):
    overall_risk_rating: str | None = None
    recommendations: list[str] = Field(default_factory=list[str])
    confidence: float = Field(ge=0, le=1)
    source: SourceSpan | None = None


class CostEstimate(BaseModel):
    item: str
    low_amount: str | None = Field(default=None, description='As written, e.g. "£15,000"')
    high_amount: str | None = Field(default=None, description='As written, e.g. "£25,000"')
    vat_exclusive: bool | None = None
    confidence: float = Field(ge=0, le=1)
    source: SourceSpan


class EnvironmentalReportExtraction(BaseModel):
    """The full structured extraction for one environmental report,
    matching the requirements doc's "Environmental report fields" (section
    7). A field is `None` (or an empty list) when the report genuinely
    doesn't state it -- "not_found" is a real answer, not an error."""

    report_metadata: ReportMetadata
    reliance: Reliance
    site: Site
    historical_uses: list[HistoricalUse] = Field(default_factory=list[HistoricalUse])
    geology_water: GeologyWater
    flood_risk: FloodRisk
    contamination_status: ContaminationStatus
    pollution_incidents: list[PollutionIncident] = Field(default_factory=list[PollutionIncident])
    storage_tanks: list[StorageTank] = Field(default_factory=list[StorageTank])
    overall_risk: OverallRisk
    cost_estimates: list[CostEstimate] = Field(default_factory=list[CostEstimate])


environmental_extraction_agent = Agent(
    # Sonnet, not Haiku (see `services/llm.py`'s chat/classification agents):
    # per the Milestone 2 PRD, risk-review extraction uses the stronger
    # model since a misread clause here produces a wrong severity flag a
    # solicitor relies on.
    "anthropic:claude-sonnet-4-5-20250929",
    output_type=EnvironmentalReportExtraction,
    system_prompt=(
        "You extract structured facts from environmental site assessment "
        "reports for commercial real estate lawyers, so their risk-review "
        "software can compare those facts across documents.\n\n"
        "IMPORTANT INSTRUCTIONS:\n"
        "- Read the whole document before answering.\n"
        "- Every value you report must be grounded in an exact quote copied "
        "from the document (max 500 characters) -- never paraphrase the "
        "quote, and never invent a value that isn't stated.\n"
        "- If the report genuinely doesn't state something, leave that "
        "field null (or an empty list) rather than guessing. A missing "
        "value is a normal, expected answer.\n"
        "- Give each fact a confidence score from 0 to 1 reflecting how "
        "clearly the document states it.\n"
        "- Report the page number a value was found on as it's labelled in "
        "the text (e.g. after a '--- Page 4 ---' marker, report 4)."
    ),
)


# =============================================================================
# Extraction call
# =============================================================================


async def extract_environmental_report(text: str) -> EnvironmentalReportExtraction:
    """Call the LLM to extract every environmental report fact from a
    document's extracted text, returning the raw structured result (not yet
    normalised or flattened into `Fact` rows -- see `flatten_environmental_facts`).
    """
    result = await environmental_extraction_agent.run(
        f"Extract every environmental report fact from the following document:\n\n{text}"
    )
    return result.output


# =============================================================================
# Flattening + normalisation (pure, LLM-free -- see this module's docstring)
# =============================================================================

KEY_PREFIX = "environmental"


def _source(document_id: str, span: SourceSpan | None) -> list[NewFactSource]:
    if span is None:
        return []
    return [
        NewFactSource(
            document_id=document_id,
            pdf_page_index=span.pdf_page_index,
            clause_ref=span.clause_ref,
            quote=span.quote,
        )
    ]


def _normalise_date_or_none(raw: str | None) -> tuple[str | None, bool]:
    """Returns (normalised_value, normalisation_failed)."""
    if raw is None:
        return None, False
    try:
        return normalise_date(raw), False
    except NormalisationError:
        return None, True


def _normalise_company_or_none(raw: str | None) -> str | None:
    if raw is None:
        return None
    return normalise_company_name(raw)


def _normalise_area_or_none(raw: str | None) -> tuple[float | None, str | None, bool]:
    """Returns (value_m2, canonical_unit, normalisation_failed)."""
    if raw is None:
        return None, None, False
    try:
        area = normalise_area(raw)
        return area.value_m2, area.canonical_unit, False
    except NormalisationError:
        return None, None, True


def _normalise_money_or_none(raw: str | None) -> tuple[int | None, bool]:
    """Returns (pence, normalisation_failed)."""
    if raw is None:
        return None, False
    try:
        return normalise_money(raw), False
    except NormalisationError:
        return None, True


def _fact(
    key: str,
    value: object,
    confidence: float,
    sources: list[NewFactSource],
    *,
    normalised_value: object | None = None,
    unit: str | None = None,
    normalisation_failed: bool = False,
) -> NewFact:
    status = compute_status(
        value=value, confidence=confidence, normalisation_failed=normalisation_failed
    )
    return NewFact(
        key=f"{KEY_PREFIX}.{key}",
        value=value,
        normalised_value=normalised_value,
        unit=unit,
        confidence=confidence,
        status=status,
        sources=sources,
    )


def flatten_environmental_facts(
    extraction: EnvironmentalReportExtraction, *, document_id: str
) -> list[NewFact]:
    """Turn one document's raw LLM extraction into `NewFact` rows ready for
    `takehome.services.fact.create_facts`, normalising every value that has
    a normaliser (dates, money, areas, company names) along the way.

    Pure and LLM-free: takes the already-extracted structure, does no I/O.
    """
    facts: list[NewFact] = []

    # --- report_metadata -> 5 scalar facts, one shared source group -------
    meta = extraction.report_metadata
    meta_source = _source(document_id, meta.source)
    report_date_norm, report_date_failed = _normalise_date_or_none(meta.report_date)
    facts.append(_fact("report_reference", meta.report_reference, meta.confidence, meta_source))
    facts.append(
        _fact(
            "report_date",
            meta.report_date,
            meta.confidence,
            meta_source,
            normalised_value=report_date_norm,
            normalisation_failed=report_date_failed,
        )
    )
    facts.append(
        _fact(
            "consultant",
            meta.consultant,
            meta.confidence,
            meta_source,
            normalised_value=_normalise_company_or_none(meta.consultant),
        )
    )
    facts.append(_fact("authors", meta.authors, meta.confidence, meta_source))
    facts.append(
        _fact(
            "client_name",
            meta.client_name,
            meta.confidence,
            meta_source,
            normalised_value=_normalise_company_or_none(meta.client_name),
        )
    )

    # --- reliance -----------------------------------------------------------
    reliance_source = _source(document_id, extraction.reliance.source)
    facts.append(
        _fact(
            "reliance.who_may_rely",
            extraction.reliance.who_may_rely,
            extraction.reliance.confidence,
            reliance_source,
        )
    )
    facts.append(
        _fact(
            "reliance.third_party_reliance_allowed",
            extraction.reliance.third_party_reliance_allowed,
            extraction.reliance.confidence,
            reliance_source,
        )
    )

    # --- site / buildings ----------------------------------------------------
    site = extraction.site
    site_source = _source(document_id, site.source)
    site_area_m2, site_area_unit, site_area_failed = _normalise_area_or_none(site.area_m2)
    facts.append(_fact("site.address", site.address, site.confidence, site_source))
    facts.append(_fact("site.postcode", site.postcode, site.confidence, site_source))
    facts.append(
        _fact(
            "site.area_m2",
            site.area_m2,
            site.confidence,
            site_source,
            normalised_value=site_area_m2,
            unit=site_area_unit,
            normalisation_failed=site_area_failed,
        )
    )

    buildings = site.buildings
    storeys = buildings.storeys if buildings else None
    gia_raw = buildings.gross_internal_area_m2 if buildings else None
    construction_year = buildings.construction_year if buildings else None
    gia_m2, gia_unit, gia_failed = _normalise_area_or_none(gia_raw)
    facts.append(_fact("site.buildings.storeys", storeys, site.confidence, site_source))
    facts.append(
        _fact(
            "site.buildings.gross_internal_area_m2",
            gia_raw,
            site.confidence,
            site_source,
            normalised_value=gia_m2,
            unit=gia_unit,
            normalisation_failed=gia_failed,
        )
    )
    facts.append(
        _fact(
            "site.buildings.construction_year",
            construction_year,
            site.confidence,
            site_source,
        )
    )

    # --- historical_uses[] ---------------------------------------------------
    if extraction.historical_uses:
        confidence = min(u.confidence for u in extraction.historical_uses)
        sources = [s for u in extraction.historical_uses for s in _source(document_id, u.source)]
        value = [
            {
                "from_year": u.from_year,
                "to_year": u.to_year,
                "use": u.use,
                "potentially_contaminative": u.potentially_contaminative,
            }
            for u in extraction.historical_uses
        ]
        facts.append(_fact("historical_uses", value, confidence, sources))
    else:
        facts.append(_fact("historical_uses", [], 1.0, []))

    # --- geology_water --------------------------------------------------------
    gw = extraction.geology_water
    gw_source = _source(document_id, gw.source)
    facts.append(_fact("geology_summary", gw.geology_summary, gw.confidence, gw_source))
    facts.append(
        _fact("aquifer_classification", gw.aquifer_classification, gw.confidence, gw_source)
    )
    nearest_watercourse = (
        {"name": gw.nearest_watercourse_name, "distance_m": gw.nearest_watercourse_distance_m}
        if gw.nearest_watercourse_name is not None
        else None
    )
    facts.append(_fact("nearest_watercourse", nearest_watercourse, gw.confidence, gw_source))

    # --- flood_risk -----------------------------------------------------------
    flood = extraction.flood_risk
    flood_source = _source(document_id, flood.source)
    facts.append(_fact("flood_zone", flood.flood_zone, flood.confidence, flood_source))
    facts.append(_fact("flood_defences", flood.flood_defences, flood.confidence, flood_source))

    # --- contamination_status --------------------------------------------------
    contamination = extraction.contamination_status
    contamination_source = _source(document_id, contamination.source)
    facts.append(
        _fact(
            "contaminated_land_register_status",
            contamination.contaminated_land_register_status,
            contamination.confidence,
            contamination_source,
        )
    )
    facts.append(
        _fact(
            "air_quality_management_area",
            contamination.air_quality_management_area,
            contamination.confidence,
            contamination_source,
        )
    )

    # --- pollution_incidents[] --------------------------------------------------
    if extraction.pollution_incidents:
        confidence = min(p.confidence for p in extraction.pollution_incidents)
        sources = [
            s for p in extraction.pollution_incidents for s in _source(document_id, p.source)
        ]
        value = [
            {
                "year": p.year,
                "type": p.type,
                "distance_m": p.distance_m,
                "status": p.status,
            }
            for p in extraction.pollution_incidents
        ]
        facts.append(_fact("pollution_incidents", value, confidence, sources))
    else:
        facts.append(_fact("pollution_incidents", [], 1.0, []))

    # --- storage_tanks[] ---------------------------------------------------------
    if extraction.storage_tanks:
        confidence = min(t.confidence for t in extraction.storage_tanks)
        sources = [s for t in extraction.storage_tanks for s in _source(document_id, t.source)]
        value = [
            {
                "location": t.location,
                "contents": t.contents,
                "capacity_litres": t.capacity_litres,
                "status": t.status,
            }
            for t in extraction.storage_tanks
        ]
        facts.append(_fact("storage_tanks", value, confidence, sources))
    else:
        facts.append(_fact("storage_tanks", [], 1.0, []))

    # --- overall_risk -------------------------------------------------------------
    overall = extraction.overall_risk
    overall_source = _source(document_id, overall.source)
    facts.append(
        _fact(
            "overall_risk_rating", overall.overall_risk_rating, overall.confidence, overall_source
        )
    )
    facts.append(
        _fact("recommendations", overall.recommendations, overall.confidence, overall_source)
    )

    # --- cost_estimates[] -----------------------------------------------------------
    if extraction.cost_estimates:
        confidence = min(c.confidence for c in extraction.cost_estimates)
        sources = [s for c in extraction.cost_estimates for s in _source(document_id, c.source)]
        value: list[dict[str, object]] = []
        normalised_value: list[dict[str, object]] = []
        any_failed = False
        for c in extraction.cost_estimates:
            low_pence, low_failed = _normalise_money_or_none(c.low_amount)
            high_pence, high_failed = _normalise_money_or_none(c.high_amount)
            any_failed = any_failed or low_failed or high_failed
            value.append(
                {
                    "item": c.item,
                    "low_amount": c.low_amount,
                    "high_amount": c.high_amount,
                    "vat_exclusive": c.vat_exclusive,
                }
            )
            normalised_value.append(
                {
                    "item": c.item,
                    "low_amount_pence": low_pence,
                    "high_amount_pence": high_pence,
                    "vat_exclusive": c.vat_exclusive,
                }
            )
        facts.append(
            _fact(
                "cost_estimates",
                value,
                confidence,
                sources,
                normalised_value=normalised_value,
                unit="GBP",
                normalisation_failed=any_failed,
            )
        )
    else:
        facts.append(_fact("cost_estimates", [], 1.0, []))

    return facts


async def extract_environmental_facts(text: str, *, document_id: str) -> list[NewFact]:
    """Extract and flatten every environmental report fact from a
    document's text in one call -- the function later pipeline stages
    (extraction orchestration, a later ticket) plug in for `document_type ==
    DocumentType.ENVIRONMENTAL`."""
    extraction = await extract_environmental_report(text)
    return flatten_environmental_facts(extraction, document_id=document_id)
