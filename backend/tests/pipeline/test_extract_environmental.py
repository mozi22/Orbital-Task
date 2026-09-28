"""Tests for environmental report fact extraction (issue #41).

`flatten_environmental_facts` is pure and LLM-free -- built from
hand-constructed `EnvironmentalReportExtraction` objects here, rather than a
real or stubbed LLM call, so normalisation/status/source-mapping logic is
tested in isolation (see `test_extraction_call` below for the LLM-call
tests, mirroring `tests/services/test_llm.py`'s `FunctionModel` pattern).
"""

from __future__ import annotations

import pytest

from takehome.pipeline.extract_environmental import (
    Buildings,
    ContaminationStatus,
    CostEstimate,
    EnvironmentalReportExtraction,
    FloodRisk,
    GeologyWater,
    HistoricalUse,
    OverallRisk,
    PollutionIncident,
    Reliance,
    ReportMetadata,
    Site,
    SourceSpan,
    StorageTank,
    flatten_environmental_facts,
)
from takehome.services.fact import NewFact

DOCUMENT_ID = "doc-env-1"


def _minimal_extraction(**overrides: object) -> EnvironmentalReportExtraction:
    """Build a fully-populated (but mostly empty/None) extraction, so each
    test only needs to override the one section it cares about."""
    defaults: dict[str, object] = {
        "report_metadata": ReportMetadata(confidence=0.9),
        "reliance": Reliance(confidence=0.9),
        "site": Site(confidence=0.9),
        "historical_uses": [],
        "geology_water": GeologyWater(confidence=0.9),
        "flood_risk": FloodRisk(confidence=0.9),
        "contamination_status": ContaminationStatus(confidence=0.9),
        "pollution_incidents": [],
        "storage_tanks": [],
        "overall_risk": OverallRisk(confidence=0.9),
        "cost_estimates": [],
    }
    defaults.update(overrides)
    return EnvironmentalReportExtraction(**defaults)  # type: ignore[arg-type]


def _fact_by_key(facts: list[NewFact], key: str) -> NewFact:
    matches = [f for f in facts if f.key == key]
    assert len(matches) == 1, f"expected exactly one fact for {key!r}, got {len(matches)}"
    return matches[0]


# =============================================================================
# report_metadata
# =============================================================================


class TestReportMetadata:
    def test_scalar_fields_are_flattened_with_shared_source(self) -> None:
        source = SourceSpan(pdf_page_index=1, clause_ref="Header", quote="GEC/2024/0142")
        extraction = _minimal_extraction(
            report_metadata=ReportMetadata(
                report_reference="GEC/2024/0142",
                report_date="15 January 2024",
                consultant="Greenfield Environmental Consultants Ltd",
                authors="J. Smith",
                client_name="Manchester Property Holdings Ltd",
                confidence=0.95,
                source=source,
            )
        )
        facts = flatten_environmental_facts(extraction, document_id=DOCUMENT_ID)

        ref = _fact_by_key(facts, "environmental.report_reference")
        assert ref.value == "GEC/2024/0142"
        assert ref.status == "found"
        assert ref.confidence == 0.95
        assert len(ref.sources) == 1
        assert ref.sources[0].document_id == DOCUMENT_ID
        assert ref.sources[0].pdf_page_index == 1
        assert ref.sources[0].quote == "GEC/2024/0142"

    def test_report_date_is_normalised_to_iso(self) -> None:
        extraction = _minimal_extraction(
            report_metadata=ReportMetadata(report_date="15 January 2024", confidence=0.9)
        )
        facts = flatten_environmental_facts(extraction, document_id=DOCUMENT_ID)
        fact = _fact_by_key(facts, "environmental.report_date")
        assert fact.normalised_value == "2024-01-15"
        assert fact.status == "found"

    def test_unparseable_report_date_is_flagged_needs_checking(self) -> None:
        extraction = _minimal_extraction(
            report_metadata=ReportMetadata(report_date="not a date", confidence=0.95)
        )
        facts = flatten_environmental_facts(extraction, document_id=DOCUMENT_ID)
        fact = _fact_by_key(facts, "environmental.report_date")
        assert fact.normalised_value is None
        assert fact.status == "needs_checking"

    def test_consultant_and_client_name_are_normalised_company_names(self) -> None:
        extraction = _minimal_extraction(
            report_metadata=ReportMetadata(
                consultant="Greenfield Environmental Consultants Ltd",
                client_name="Manchester Property Holdings Ltd",
                confidence=0.9,
            )
        )
        facts = flatten_environmental_facts(extraction, document_id=DOCUMENT_ID)
        consultant = _fact_by_key(facts, "environmental.consultant")
        client = _fact_by_key(facts, "environmental.client_name")
        assert consultant.normalised_value == "Greenfield Environmental Consultants Limited"
        assert client.normalised_value == "Manchester Property Holdings Limited"

    def test_missing_report_reference_is_not_found(self) -> None:
        extraction = _minimal_extraction(
            report_metadata=ReportMetadata(report_reference=None, confidence=0.9)
        )
        facts = flatten_environmental_facts(extraction, document_id=DOCUMENT_ID)
        fact = _fact_by_key(facts, "environmental.report_reference")
        assert fact.value is None
        assert fact.status == "not_found"

    def test_low_confidence_scalar_is_needs_checking(self) -> None:
        extraction = _minimal_extraction(
            report_metadata=ReportMetadata(report_reference="GEC/2024/0142", confidence=0.5)
        )
        facts = flatten_environmental_facts(extraction, document_id=DOCUMENT_ID)
        fact = _fact_by_key(facts, "environmental.report_reference")
        assert fact.status == "needs_checking"


# =============================================================================
# reliance
# =============================================================================


class TestReliance:
    def test_who_may_rely_and_third_party_flag_are_separate_facts(self) -> None:
        extraction = _minimal_extraction(
            reliance=Reliance(
                who_may_rely=["Manchester Property Holdings Ltd"],
                third_party_reliance_allowed=False,
                confidence=0.9,
            )
        )
        facts = flatten_environmental_facts(extraction, document_id=DOCUMENT_ID)
        who = _fact_by_key(facts, "environmental.reliance.who_may_rely")
        allowed = _fact_by_key(facts, "environmental.reliance.third_party_reliance_allowed")
        assert who.value == ["Manchester Property Holdings Ltd"]
        assert who.status == "found"
        assert allowed.value is False
        assert allowed.status == "found"  # False is a real, found answer

    def test_empty_who_may_rely_is_not_found(self) -> None:
        extraction = _minimal_extraction(reliance=Reliance(confidence=0.9))
        facts = flatten_environmental_facts(extraction, document_id=DOCUMENT_ID)
        who = _fact_by_key(facts, "environmental.reliance.who_may_rely")
        assert who.status == "not_found"


# =============================================================================
# site / buildings
# =============================================================================


class TestSite:
    def test_site_area_is_normalised_to_square_metres(self) -> None:
        extraction = _minimal_extraction(
            site=Site(address="15-21 Deansgate", area_m2="about 0.28 ha", confidence=0.9)
        )
        facts = flatten_environmental_facts(extraction, document_id=DOCUMENT_ID)
        fact = _fact_by_key(facts, "environmental.site.area_m2")
        assert fact.normalised_value == pytest.approx(2800.0)
        assert fact.unit == "ha"
        assert fact.status == "found"

    def test_building_fields_are_flattened_under_their_own_dotted_keys(self) -> None:
        extraction = _minimal_extraction(
            site=Site(
                confidence=0.9,
                buildings=Buildings(
                    storeys=4, gross_internal_area_m2="about 2,400 m2", construction_year=1920
                ),
            )
        )
        facts = flatten_environmental_facts(extraction, document_id=DOCUMENT_ID)
        storeys = _fact_by_key(facts, "environmental.site.buildings.storeys")
        gia = _fact_by_key(facts, "environmental.site.buildings.gross_internal_area_m2")
        year = _fact_by_key(facts, "environmental.site.buildings.construction_year")
        assert storeys.value == 4
        assert gia.normalised_value == pytest.approx(2400.0)
        assert gia.unit == "m2"
        assert year.value == 1920

    def test_no_buildings_present_is_not_found_for_all_building_facts(self) -> None:
        extraction = _minimal_extraction(site=Site(confidence=0.9, buildings=None))
        facts = flatten_environmental_facts(extraction, document_id=DOCUMENT_ID)
        for key in (
            "environmental.site.buildings.storeys",
            "environmental.site.buildings.gross_internal_area_m2",
            "environmental.site.buildings.construction_year",
        ):
            assert _fact_by_key(facts, key).status == "not_found"


# =============================================================================
# historical_uses[]
# =============================================================================


class TestHistoricalUses:
    def test_list_items_are_flattened_into_one_fact_with_multiple_sources(self) -> None:
        extraction = _minimal_extraction(
            historical_uses=[
                HistoricalUse(
                    from_year=1920,
                    to_year=1975,
                    use="textile warehouse",
                    potentially_contaminative=True,
                    confidence=0.9,
                    source=SourceSpan(pdf_page_index=2, quote="1920-1975 textile warehouse"),
                ),
                HistoricalUse(
                    from_year=2019,
                    to_year=None,
                    use="vacant",
                    potentially_contaminative=False,
                    confidence=0.85,
                    source=SourceSpan(pdf_page_index=2, quote="2019 onwards vacant"),
                ),
            ]
        )
        facts = flatten_environmental_facts(extraction, document_id=DOCUMENT_ID)
        fact = _fact_by_key(facts, "environmental.historical_uses")
        assert isinstance(fact.value, list)
        assert len(fact.value) == 2
        assert fact.value[0]["use"] == "textile warehouse"
        assert fact.value[0]["potentially_contaminative"] is True
        assert len(fact.sources) == 2
        # Confidence is the worst-case (minimum) across items.
        assert fact.confidence == 0.85
        assert fact.status == "found"

    def test_no_historical_uses_is_not_found(self) -> None:
        extraction = _minimal_extraction(historical_uses=[])
        facts = flatten_environmental_facts(extraction, document_id=DOCUMENT_ID)
        fact = _fact_by_key(facts, "environmental.historical_uses")
        assert fact.value == []
        assert fact.status == "not_found"


# =============================================================================
# geology_water
# =============================================================================


class TestGeologyWater:
    def test_nearest_watercourse_is_a_single_object_fact(self) -> None:
        extraction = _minimal_extraction(
            geology_water=GeologyWater(
                geology_summary="Glacial till 5-8m over Sherwood Sandstone",
                aquifer_classification="Principal Aquifer",
                nearest_watercourse_name="River Irwell",
                nearest_watercourse_distance_m=180,
                confidence=0.9,
            )
        )
        facts = flatten_environmental_facts(extraction, document_id=DOCUMENT_ID)
        watercourse = _fact_by_key(facts, "environmental.nearest_watercourse")
        assert watercourse.value == {"name": "River Irwell", "distance_m": 180}
        assert watercourse.status == "found"

    def test_no_nearest_watercourse_is_not_found(self) -> None:
        extraction = _minimal_extraction(geology_water=GeologyWater(confidence=0.9))
        facts = flatten_environmental_facts(extraction, document_id=DOCUMENT_ID)
        watercourse = _fact_by_key(facts, "environmental.nearest_watercourse")
        assert watercourse.value is None
        assert watercourse.status == "not_found"


# =============================================================================
# flood_risk / contamination_status
# =============================================================================


class TestFloodAndContamination:
    def test_flood_zone_and_defences_are_separate_facts(self) -> None:
        extraction = _minimal_extraction(
            flood_risk=FloodRisk(flood_zone="2", flood_defences=False, confidence=0.9)
        )
        facts = flatten_environmental_facts(extraction, document_id=DOCUMENT_ID)
        assert _fact_by_key(facts, "environmental.flood_zone").value == "2"
        defences = _fact_by_key(facts, "environmental.flood_defences")
        assert defences.value is False
        assert defences.status == "found"

    def test_contamination_register_and_aqma_are_separate_facts(self) -> None:
        extraction = _minimal_extraction(
            contamination_status=ContaminationStatus(
                contaminated_land_register_status="Not determined as contaminated land",
                air_quality_management_area=True,
                confidence=0.9,
            )
        )
        facts = flatten_environmental_facts(extraction, document_id=DOCUMENT_ID)
        status = _fact_by_key(facts, "environmental.contaminated_land_register_status")
        aqma = _fact_by_key(facts, "environmental.air_quality_management_area")
        assert status.value == "Not determined as contaminated land"
        assert aqma.value is True


# =============================================================================
# pollution_incidents[] / storage_tanks[] / cost_estimates[]
# =============================================================================


class TestListFacts:
    def test_pollution_incidents_are_flattened(self) -> None:
        extraction = _minimal_extraction(
            pollution_incidents=[
                PollutionIncident(
                    year=1987,
                    type="diesel spill",
                    distance_m=120,
                    status="closed 1988",
                    confidence=0.9,
                    source=SourceSpan(pdf_page_index=3, quote="1987 diesel spill"),
                )
            ]
        )
        facts = flatten_environmental_facts(extraction, document_id=DOCUMENT_ID)
        fact = _fact_by_key(facts, "environmental.pollution_incidents")
        assert fact.value == [
            {"year": 1987, "type": "diesel spill", "distance_m": 120, "status": "closed 1988"}
        ]
        assert fact.status == "found"

    def test_storage_tanks_are_flattened(self) -> None:
        extraction = _minimal_extraction(
            storage_tanks=[
                StorageTank(
                    location="rear yard",
                    contents="heating oil",
                    capacity_litres=5000,
                    status="unknown",
                    confidence=0.9,
                    source=SourceSpan(pdf_page_index=4, quote="underground heating oil tank"),
                )
            ]
        )
        facts = flatten_environmental_facts(extraction, document_id=DOCUMENT_ID)
        fact = _fact_by_key(facts, "environmental.storage_tanks")
        assert fact.value[0]["status"] == "unknown"
        assert fact.value[0]["capacity_litres"] == 5000

    def test_cost_estimates_are_normalised_to_pence(self) -> None:
        extraction = _minimal_extraction(
            cost_estimates=[
                CostEstimate(
                    item="Phase II ground investigation",
                    low_amount="£15,000",
                    high_amount="£25,000",
                    vat_exclusive=True,
                    confidence=0.9,
                    source=SourceSpan(pdf_page_index=6, quote="£15,000-£25,000"),
                )
            ]
        )
        facts = flatten_environmental_facts(extraction, document_id=DOCUMENT_ID)
        fact = _fact_by_key(facts, "environmental.cost_estimates")
        assert fact.unit == "GBP"
        assert fact.normalised_value == [
            {
                "item": "Phase II ground investigation",
                "low_amount_pence": 1_500_000,
                "high_amount_pence": 2_500_000,
                "vat_exclusive": True,
            }
        ]

    def test_unparseable_cost_amount_flags_needs_checking(self) -> None:
        extraction = _minimal_extraction(
            cost_estimates=[
                CostEstimate(
                    item="Remediation",
                    low_amount="TBC",
                    high_amount="£200,000",
                    vat_exclusive=False,
                    confidence=0.95,
                    source=SourceSpan(pdf_page_index=6, quote="Remediation TBC"),
                )
            ]
        )
        facts = flatten_environmental_facts(extraction, document_id=DOCUMENT_ID)
        fact = _fact_by_key(facts, "environmental.cost_estimates")
        assert fact.status == "needs_checking"
        assert fact.normalised_value[0]["low_amount_pence"] is None

    def test_no_cost_estimates_is_not_found(self) -> None:
        extraction = _minimal_extraction(cost_estimates=[])
        facts = flatten_environmental_facts(extraction, document_id=DOCUMENT_ID)
        fact = _fact_by_key(facts, "environmental.cost_estimates")
        assert fact.status == "not_found"


# =============================================================================
# overall_risk
# =============================================================================


class TestOverallRisk:
    def test_rating_and_recommendations_are_separate_facts(self) -> None:
        extraction = _minimal_extraction(
            overall_risk=OverallRisk(
                overall_risk_rating="Low to moderate",
                recommendations=["Phase II ground investigation recommended"],
                confidence=0.9,
            )
        )
        facts = flatten_environmental_facts(extraction, document_id=DOCUMENT_ID)
        rating = _fact_by_key(facts, "environmental.overall_risk_rating")
        recs = _fact_by_key(facts, "environmental.recommendations")
        assert rating.value == "Low to moderate"
        assert recs.value == ["Phase II ground investigation recommended"]


# =============================================================================
# Every key is present exactly once
# =============================================================================


def test_every_field_produces_exactly_one_fact_row() -> None:
    extraction = _minimal_extraction()
    facts = flatten_environmental_facts(extraction, document_id=DOCUMENT_ID)
    keys = [f.key for f in facts]
    assert len(keys) == len(set(keys)), "every key must appear exactly once per extraction"
    assert "environmental.report_reference" in keys
    assert "environmental.cost_estimates" in keys
    assert len(keys) == 26
