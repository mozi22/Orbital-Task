"""Tests for title-report fact extraction (issue #39).

Two layers, per the ticket's own acceptance criteria:
  - Pure unit tests of `extraction_to_facts` (the extraction-schema ->
    normalised-`Fact` wiring), with no LLM or database involved.
  - A functional check that runs `extract_title_report_facts` end to end
    (real Postgres, a stubbed LLM whose output mirrors the sample
    `title-report-lot-7.pdf` fixture's real content) and asserts the
    persisted facts match the eval doc's expected facts for that fixture
    (EX-T01-EX-T20) -- functional correctness, not full answer-key scoring
    (that's Milestone 3, per the requirements doc's eval test cases doc).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from typing import Any, cast

import fitz
import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy.ext.asyncio import AsyncSession

from takehome.db.models import Conversation, Document, Fact, FactStatus, Matter
from takehome.pipeline.extract_title import (
    KEY_PREFIX,
    NEEDS_CHECKING_THRESHOLD,
    ExtractedListItem,
    ExtractedScalar,
    ExtractedSource,
    TitleReportExtraction,
    _locate_quote,
    _split_pages,
    extract_title_report_facts,
    extraction_to_facts,
    title_extraction_agent,
)

SAMPLE_DOCS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "sample-docs")
SAMPLE_TITLE_PDF_PATH = os.path.join(SAMPLE_DOCS_DIR, "title-report-lot-7.pdf")


def _extract_pdf_text(path: str) -> str:
    """Mirror `services/document.py`'s own page-by-page PyMuPDF extraction,
    so this test exercises extraction against exactly the same text shape
    the real upload path would hand to the extraction agent."""
    doc = fitz.open(path)
    try:
        pages: list[str] = []
        for page_num in range(len(doc)):
            text = doc[page_num].get_text()  # type: ignore[union-attr]
            if text.strip():
                pages.append(f"--- Page {page_num + 1} ---\n{text}")
        return "\n\n".join(pages)
    finally:
        doc.close()


def _scalar(value: str, *, confidence: float = 0.95, page: int = 1) -> ExtractedScalar:
    return ExtractedScalar(
        found=True,
        value=value,
        confidence=confidence,
        sources=[ExtractedSource(pdf_page_index=page, quote=value[:120])],
    )


def _as_dict(value: Any) -> dict[str, Any]:
    """Narrow a `Fact.value`/`normalised_value` (typed `Any | None` on the
    JSON-backed column) to a plain dict for subscripting in assertions,
    failing loudly if a test's fixture data is somehow shaped wrong rather
    than silently mis-subscripting it."""
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


def _not_found(*, confidence: float = 0.95) -> ExtractedScalar:
    return ExtractedScalar(found=False, value=None, confidence=confidence, sources=[])


def _item(
    value: dict[str, object], *, confidence: float = 0.95, page: int = 1
) -> ExtractedListItem:
    return ExtractedListItem(
        value=value,
        confidence=confidence,
        sources=[ExtractedSource(pdf_page_index=page, quote=str(next(iter(value.values())))[:120])],
    )


def _minimal_extraction(**overrides: Any) -> TitleReportExtraction:
    """Build a `TitleReportExtraction` with every scalar field defaulted to
    a simple found value, so individual tests only need to override the
    one or two fields they care about."""
    base: dict[str, Any] = {
        "title_number": _scalar("LN782451"),
        "edition_date": _scalar("22 November 2023"),
        "as_at_datetime": _scalar("12:00 on 22 November 2023"),
        "is_summary": _scalar("true"),
        "tenure": _scalar("Freehold"),
        "title_class": _scalar("Absolute"),
        "property_address": _scalar("Lot 7, Victoria Park Estate, London E9 7HD"),
        "property_postcode": _scalar("E9 7HD"),
        "property_description": _scalar("Freehold parcel with commercial building"),
        "property_site_area": _scalar("0.34 hectares"),
        "property_boundary_north": _scalar("Victoria Park Road"),
        "property_boundary_east": _scalar("Cadogan Terrace"),
        "property_boundary_south": _scalar("Wick Road"),
        "property_boundary_west": _scalar("access road"),
        "property_building_storeys": _scalar("2"),
        "property_building_gross_internal_area": _scalar("1,200 square metres"),
        "property_building_use": _scalar("commercial"),
        "registered_owner_name": _scalar("Victoria Park Developments Ltd"),
        "registered_owner_company_number": _scalar("08234571"),
        "registered_owner_registered_office": _scalar("17 Hackney Road, London E2 7NX"),
        "registered_owner_registered_since": _scalar("14 March 2019"),
        "price_paid_amount": _scalar("£4,250,000"),
        "price_paid_date": _scalar("14 March 2019"),
        "charges": [],
        "restrictive_covenants": [],
        "easements": [],
        "noted_entries": [],
        "cautions_and_restrictions": [],
    }
    base.update(overrides)
    return TitleReportExtraction(**base)


# =============================================================================
# _split_pages / _locate_quote -- pure unit tests
# =============================================================================


def test_split_pages_splits_on_page_markers() -> None:
    document_text = (
        "--- Page 1 ---\nFirst page text.\n\n--- Page 2 ---\nSecond page text.\n"
    )
    pages = _split_pages(document_text)

    assert pages == {1: "First page text.\n\n", 2: "Second page text.\n"}


def test_split_pages_captures_the_final_pages_text_to_the_end_of_the_document() -> None:
    """The last page has no following marker to bound it -- its text must
    run all the way to the end of `document_text`, not be truncated."""
    document_text = "--- Page 1 ---\nFirst.\n\n--- Page 2 ---\nLast page, no trailing marker."
    pages = _split_pages(document_text)

    assert pages[2] == "Last page, no trailing marker."


def test_split_pages_with_no_markers_returns_no_pages() -> None:
    """A document with no `--- Page N ---` markers (e.g. hand-written test
    text, or extraction that produced a single unmarked blob) has nothing
    for this to key by page number -- the sane fallback is an empty
    mapping, so callers (`_sources_to_dicts`) fall through to leaving
    `char_start`/`char_end` unset rather than mis-attributing text."""
    document_text = "Some text with no page markers at all."
    pages = _split_pages(document_text)

    assert pages == {}


def test_locate_quote_finds_a_verbatim_match() -> None:
    page_text = "The property is Freehold. Title Number: LN782451."
    located = _locate_quote(page_text, "LN782451")

    assert located is not None
    assert located == (40, 48)
    assert page_text[located[0] : located[1]] == "LN782451"


def test_locate_quote_returns_none_when_quote_is_not_present() -> None:
    page_text = "The property is Freehold. Title Number: LN782451."
    assert _locate_quote(page_text, "Leasehold") is None


def test_locate_quote_returns_none_on_whitespace_mismatch() -> None:
    """The LLM's copy of a quote commonly collapses whitespace differently
    from the extracted PDF text (e.g. a line break where the source has a
    single space) -- this must not fuzzy-match, only return `None`."""
    page_text = "Title Number:\nLN782451"
    assert _locate_quote(page_text, "Title Number: LN782451") is None


# =============================================================================
# extraction_to_facts -- pure unit tests
# =============================================================================


def test_every_scalar_field_becomes_a_key_prefixed_fact() -> None:
    extraction = _minimal_extraction()
    facts = extraction_to_facts(extraction, matter_id="m1", document_id="d1")

    keys = {f.key for f in facts}
    assert f"{KEY_PREFIX}.title_number" in keys
    assert f"{KEY_PREFIX}.registered_owner_name" in keys
    assert all(k.startswith(f"{KEY_PREFIX}.") for k in keys)


def test_date_fields_are_normalised_to_iso() -> None:
    extraction = _minimal_extraction(edition_date=_scalar("22 November 2023"))
    facts = extraction_to_facts(extraction, matter_id="m1", document_id="d1")

    fact = next(f for f in facts if f.key == f"{KEY_PREFIX}.edition_date")
    assert fact.normalised_value == "2023-11-22"
    assert fact.value == "22 November 2023"


def test_money_field_is_normalised_to_pence_gbp() -> None:
    extraction = _minimal_extraction(price_paid_amount=_scalar("£4,250,000"))
    facts = extraction_to_facts(extraction, matter_id="m1", document_id="d1")

    fact = next(f for f in facts if f.key == f"{KEY_PREFIX}.price_paid_amount")
    assert fact.normalised_value == 425_000_000
    assert fact.unit == "GBP"


def test_company_name_field_is_normalised() -> None:
    extraction = _minimal_extraction(registered_owner_name=_scalar("Victoria Park Ltd"))
    facts = extraction_to_facts(extraction, matter_id="m1", document_id="d1")

    fact = next(f for f in facts if f.key == f"{KEY_PREFIX}.registered_owner_name")
    assert fact.normalised_value == "Victoria Park Limited"


def test_area_field_is_normalised_to_m2_with_unit() -> None:
    extraction = _minimal_extraction(property_site_area=_scalar("0.34 hectares"))
    facts = extraction_to_facts(extraction, matter_id="m1", document_id="d1")

    fact = next(f for f in facts if f.key == f"{KEY_PREFIX}.property_site_area")
    assert fact.normalised_value == pytest.approx(3400.0)
    assert fact.unit == "ha"


def test_area_field_strips_trailing_alternate_unit_parenthetical() -> None:
    """Title-report site areas are routinely written with a trailing
    alternate-unit parenthetical, e.g. "0.34 hectares (0.84 acres)" -- this
    must still normalise, not silently fail."""
    extraction = _minimal_extraction(property_site_area=_scalar("0.34 hectares (0.84 acres)"))
    facts = extraction_to_facts(extraction, matter_id="m1", document_id="d1")

    fact = next(f for f in facts if f.key == f"{KEY_PREFIX}.property_site_area")
    assert fact.normalised_value == pytest.approx(3400.0)
    assert fact.unit == "ha"


def test_bool_field_is_normalised_from_text() -> None:
    extraction = _minimal_extraction(is_summary=_scalar("true"))
    facts = extraction_to_facts(extraction, matter_id="m1", document_id="d1")

    fact = next(f for f in facts if f.key == f"{KEY_PREFIX}.is_summary")
    assert fact.normalised_value is True


def test_field_with_no_normaliser_is_copied_through_unchanged() -> None:
    """Company number and postcode have no defined normaliser (issue #37
    doesn't cover them) -- this module must not invent one, per the
    ticket's own acceptance criteria wording ("normalised ... via #3.1")."""
    extraction = _minimal_extraction(
        registered_owner_company_number=_scalar("08234571"),
        property_postcode=_scalar("E9 7HD"),
    )
    facts = extraction_to_facts(extraction, matter_id="m1", document_id="d1")

    company_number_fact = next(
        f for f in facts if f.key == f"{KEY_PREFIX}.registered_owner_company_number"
    )
    postcode_fact = next(f for f in facts if f.key == f"{KEY_PREFIX}.property_postcode")
    assert company_number_fact.normalised_value == "08234571"
    assert postcode_fact.normalised_value == "E9 7HD"


def test_not_found_field_gets_not_found_status_and_no_value() -> None:
    extraction = _minimal_extraction(title_class=_not_found())
    facts = extraction_to_facts(extraction, matter_id="m1", document_id="d1")

    fact = next(f for f in facts if f.key == f"{KEY_PREFIX}.title_class")
    assert fact.status == FactStatus.NOT_FOUND
    assert fact.value is None
    assert fact.normalised_value is None
    assert fact.sources == []


def test_low_confidence_field_is_marked_needs_checking() -> None:
    extraction = _minimal_extraction(
        title_number=_scalar("LN782451", confidence=NEEDS_CHECKING_THRESHOLD - 0.01)
    )
    facts = extraction_to_facts(extraction, matter_id="m1", document_id="d1")

    fact = next(f for f in facts if f.key == f"{KEY_PREFIX}.title_number")
    assert fact.status == FactStatus.NEEDS_CHECKING


def test_confidence_at_threshold_is_extracted_not_needs_checking() -> None:
    extraction = _minimal_extraction(
        title_number=_scalar("LN782451", confidence=NEEDS_CHECKING_THRESHOLD)
    )
    facts = extraction_to_facts(extraction, matter_id="m1", document_id="d1")

    fact = next(f for f in facts if f.key == f"{KEY_PREFIX}.title_number")
    assert fact.status == FactStatus.EXTRACTED


def test_high_confidence_field_is_marked_extracted() -> None:
    extraction = _minimal_extraction(title_number=_scalar("LN782451", confidence=0.95))
    facts = extraction_to_facts(extraction, matter_id="m1", document_id="d1")

    fact = next(f for f in facts if f.key == f"{KEY_PREFIX}.title_number")
    assert fact.status == FactStatus.EXTRACTED


def test_scalar_fact_keeps_matter_and_document_ids() -> None:
    extraction = _minimal_extraction()
    facts = extraction_to_facts(extraction, matter_id="m1", document_id="d1")

    assert all(f.matter_id == "m1" for f in facts)
    assert all(f.document_id == "d1" for f in facts)


def test_scalar_fact_sources_carry_the_document_id() -> None:
    extraction = _minimal_extraction(title_number=_scalar("LN782451"))
    facts = extraction_to_facts(extraction, matter_id="m1", document_id="d1")

    fact = next(f for f in facts if f.key == f"{KEY_PREFIX}.title_number")
    assert fact.sources[0]["document_id"] == "d1"
    assert fact.sources[0]["pdf_page_index"] == 1


def test_empty_list_field_produces_no_facts_but_is_not_an_error() -> None:
    extraction = _minimal_extraction(cautions_and_restrictions=[])
    facts = extraction_to_facts(extraction, matter_id="m1", document_id="d1")

    caution_facts = [f for f in facts if f.key == f"{KEY_PREFIX}.cautions_and_restrictions"]
    assert caution_facts == []


def test_list_field_produces_one_fact_per_item() -> None:
    extraction = _minimal_extraction(
        restrictive_covenants=[
            _item({"date": "1 June 1952", "category": "use", "full_text": "No industrial use"}),
            _item({"date": "1 June 1952", "category": "height", "full_text": "No over 4 storeys"}),
        ]
    )
    facts = extraction_to_facts(extraction, matter_id="m1", document_id="d1")

    covenant_facts = [f for f in facts if f.key == f"{KEY_PREFIX}.restrictive_covenants"]
    assert len(covenant_facts) == 2
    assert _as_dict(covenant_facts[0].value)["category"] == "use"
    assert _as_dict(covenant_facts[1].value)["category"] == "height"


def test_list_item_date_subfield_is_normalised() -> None:
    extraction = _minimal_extraction(
        charges=[
            _item(
                {
                    "entry_number": "1",
                    "date": "15 March 2019",
                    "lender_name": "Barclays Bank Ltd",
                    "lender_company_number": "01026167",
                    "secures_further_advances": True,
                }
            )
        ]
    )
    facts = extraction_to_facts(extraction, matter_id="m1", document_id="d1")

    charge_fact = next(f for f in facts if f.key == f"{KEY_PREFIX}.charges")
    normalised = _as_dict(charge_fact.normalised_value)
    assert normalised["date"] == "2019-03-15"
    assert normalised["lender_name"] == "Barclays Bank Limited"
    assert normalised["lender_company_number"] == "01026167"
    assert normalised["secures_further_advances"] is True


def test_list_item_status_reflects_its_own_confidence() -> None:
    extraction = _minimal_extraction(easements=[_item({"type": "right_of_way"}, confidence=0.5)])
    facts = extraction_to_facts(extraction, matter_id="m1", document_id="d1")

    easement_fact = next(f for f in facts if f.key == f"{KEY_PREFIX}.easements")
    assert easement_fact.status == FactStatus.NEEDS_CHECKING


# =============================================================================
# extract_title_report_facts -- functional check against the real fixture
# =============================================================================


def _stub_model(extraction: TitleReportExtraction):
    def _fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        tool = info.output_tools[0]
        return ModelResponse(
            parts=[ToolCallPart(tool_name=tool.name, args=extraction.model_dump(mode="json"))]
        )

    return _fn


def _title_report_lot_7_ground_truth() -> TitleReportExtraction:
    """A hand-built extraction result mirroring the real content of
    `sample-docs/title-report-lot-7.pdf` and the eval doc's expected facts
    for it (EX-T01-EX-T20). One field (`property_description`) is
    deliberately given a below-threshold confidence to exercise the
    "needs_checking" wiring against a realistic fixture, not just synthetic
    unit-test data."""
    return TitleReportExtraction(
        title_number=_scalar("LN782451", page=1),
        edition_date=_scalar("22 November 2023", page=1),
        as_at_datetime=_scalar("12:00 on 22 November 2023", page=3),
        is_summary=_scalar("true", page=3),
        tenure=_scalar("Freehold", page=1),
        title_class=_scalar("Absolute", page=1),
        property_address=_scalar(
            "Lot 7, Victoria Park Estate, 42-48 Victoria Park Road, London E9 7HD", page=1
        ),
        property_postcode=_scalar("E9 7HD", page=1),
        property_description=_scalar(
            "Freehold parcel of land with a two-storey detached commercial building",
            confidence=0.6,
            page=1,
        ),
        property_site_area=_scalar("0.34 hectares", page=1),
        property_boundary_north=_scalar("Victoria Park Road", page=1),
        property_boundary_east=_scalar("residential properties on Cadogan Terrace", page=1),
        property_boundary_south=_scalar("rear gardens of properties on Wick Road", page=1),
        property_boundary_west=_scalar("access road serving the Victoria Park Estate", page=1),
        property_building_storeys=_scalar("2", page=1),
        property_building_gross_internal_area=_scalar("1,200 square metres", page=1),
        property_building_use=_scalar("commercial", page=1),
        registered_owner_name=_scalar("Victoria Park Developments Ltd", page=1),
        registered_owner_company_number=_scalar("08234571", page=1),
        registered_owner_registered_office=_scalar("17 Hackney Road, London E2 7NX", page=1),
        registered_owner_registered_since=_scalar("14 March 2019", page=1),
        price_paid_amount=_scalar("£4,250,000", page=1),
        price_paid_date=_scalar("14 March 2019", page=1),
        charges=[
            _item(
                {
                    "entry_number": "1",
                    "date": "15 March 2019",
                    "lender_name": "Barclays Bank PLC",
                    "lender_company_number": "01026167",
                    "secures_further_advances": True,
                },
                page=1,
            )
        ],
        restrictive_covenants=[
            _item(
                {
                    "date": "1 June 1952",
                    "parties": "London County Council to Herbert William Marsh",
                    "full_text": "Not to use for industrial, manufacturing or heavy "
                    "commercial purposes, nor cause a nuisance",
                    "category": "use",
                },
                page=2,
            ),
            _item(
                {
                    "date": "1 June 1952",
                    "parties": "London County Council to Herbert William Marsh",
                    "full_text": "Maintain boundary fencing at least 1.8 metres high",
                    "category": "boundary",
                },
                page=2,
            ),
            _item(
                {
                    "date": "1 June 1952",
                    "parties": "London County Council to Herbert William Marsh",
                    "full_text": "No building over 4 storeys",
                    "category": "height",
                    "parsed_limits": "max_storeys: 4",
                },
                page=2,
            ),
        ],
        easements=[
            _item(
                {
                    "type": "right_of_way",
                    "benefit_or_burden": "benefit",
                    "route_description": "access road to the north leading to Victoria Park Road",
                },
                page=2,
            ),
            _item(
                {
                    "type": "drainage",
                    "benefit_or_burden": "burden",
                    "route_description": "shared sewer, north-east to south-west",
                    "obligations": "permit access for maintenance and repair",
                },
                page=2,
            ),
        ],
        noted_entries=[
            _item(
                {
                    "type": "planning_permission",
                    "reference": "B/2023/4521",
                    "date": "8 September 2023",
                    "summary": "Demolish existing building, erect 48 residential units",
                },
                page=2,
            ),
            _item(
                {
                    "type": "s106_agreement",
                    "date": "12 October 2023",
                    "summary": "35% affordable housing, highways and open space contributions",
                },
                page=2,
            ),
        ],
        cautions_and_restrictions=[],
    )


@pytest.fixture
def _use_ground_truth_stub() -> Iterator[None]:
    with title_extraction_agent.override(
        model=FunctionModel(_stub_model(_title_report_lot_7_ground_truth()))
    ):
        yield


async def _seed_matter_and_title_document(session: AsyncSession) -> tuple[str, Document]:
    conversation = Conversation(id=uuid.uuid4().hex[:16], title="Test")
    session.add(conversation)
    await session.flush()

    matter = Matter(
        id=uuid.uuid4().hex[:16], conversation_id=conversation.id, gate_result="pending"
    )
    session.add(matter)

    document = Document(
        id=uuid.uuid4().hex[:16],
        conversation_id=conversation.id,
        filename="title-report-lot-7.pdf",
        display_name="title-report-lot-7.pdf",
        file_path=SAMPLE_TITLE_PDF_PATH,
        extracted_text=_extract_pdf_text(SAMPLE_TITLE_PDF_PATH),
        page_count=3,
    )
    session.add(document)
    await session.commit()
    await session.refresh(matter)
    await session.refresh(document)
    return matter.id, document


async def test_extract_title_report_facts_persists_expected_facts_for_lot_7_fixture(
    session: AsyncSession, _use_ground_truth_stub: None
) -> None:
    matter_id, document = await _seed_matter_and_title_document(session)

    facts = await extract_title_report_facts(session, matter_id=matter_id, document=document)

    assert len(facts) > 0
    by_key: dict[str, list[Fact]] = {}
    for f in facts:
        by_key.setdefault(f.key, []).append(f)

    # EX-T01: title number
    title_number_fact = by_key[f"{KEY_PREFIX}.title_number"][0]
    assert title_number_fact.normalised_value == "LN782451"
    # `document_text` is threaded through in production (see
    # `extract_title_report_facts`), so the source's char offsets must be
    # located against the *real* fixture PDF text, not left `None` -- this
    # is the actual end-to-end wiring the unit tests for `_split_pages` and
    # `_locate_quote` can't prove on their own.
    title_number_source = title_number_fact.sources[0]
    assert title_number_source["pdf_page_index"] == 1
    assert document.extracted_text is not None
    page_1_text = _split_pages(document.extracted_text)[1]
    expected_start = page_1_text.find("LN782451")
    assert expected_start != -1
    assert title_number_source["char_start"] == expected_start
    assert title_number_source["char_end"] == expected_start + len("LN782451")
    assert (
        page_1_text[title_number_source["char_start"] : title_number_source["char_end"]]
        == "LN782451"
    )
    # EX-T02: edition date, normalised to ISO 8601
    assert by_key[f"{KEY_PREFIX}.edition_date"][0].normalised_value == "2023-11-22"
    # EX-T03: tenure and class
    assert by_key[f"{KEY_PREFIX}.tenure"][0].value == "Freehold"
    assert by_key[f"{KEY_PREFIX}.title_class"][0].value == "Absolute"
    # EX-T04: address
    address_value = by_key[f"{KEY_PREFIX}.property_address"][0].value
    assert address_value is not None
    assert "Victoria Park Road" in address_value
    # EX-T05: site area, normalised to m2 (0.34 ha = 3400 m2)
    site_area_fact = by_key[f"{KEY_PREFIX}.property_site_area"][0]
    assert site_area_fact.normalised_value == pytest.approx(3400.0)
    assert site_area_fact.unit == "ha"
    # EX-T08: registered owner, company name suffix normalised
    owner_fact = by_key[f"{KEY_PREFIX}.registered_owner_name"][0]
    assert owner_fact.normalised_value == "Victoria Park Developments Limited"
    # EX-T09: registered since, normalised to ISO 8601
    assert by_key[f"{KEY_PREFIX}.registered_owner_registered_since"][0].normalised_value == (
        "2019-03-14"
    )
    # EX-T10: price paid, normalised to pence GBP
    price_fact = by_key[f"{KEY_PREFIX}.price_paid_amount"][0]
    assert price_fact.normalised_value == 425_000_000
    assert price_fact.unit == "GBP"
    # EX-T11: charge, one item, lender name normalised
    charge_fact = by_key[f"{KEY_PREFIX}.charges"][0]
    charge_normalised = _as_dict(charge_fact.normalised_value)
    assert charge_normalised["lender_name"] == "Barclays Bank PLC"
    assert charge_normalised["date"] == "2019-03-15"
    # EX-T12-15: three restrictive covenants
    assert len(by_key[f"{KEY_PREFIX}.restrictive_covenants"]) == 3
    # EX-T16-17: two easements
    assert len(by_key[f"{KEY_PREFIX}.easements"]) == 2
    # EX-T18-19: two noted entries
    assert len(by_key[f"{KEY_PREFIX}.noted_entries"]) == 2
    # EX-T20: no cautions registered -- an empty list is a meaningful answer,
    # represented here as no Fact rows for that key.
    assert by_key.get(f"{KEY_PREFIX}.cautions_and_restrictions") is None

    # The deliberately below-threshold field is marked needs_checking.
    assert by_key[f"{KEY_PREFIX}.property_description"][0].status == FactStatus.NEEDS_CHECKING

    # Every fact is scoped to the right matter and document.
    assert all(f.matter_id == matter_id for f in facts)
    assert all(f.document_id == document.id for f in facts)


async def test_extract_title_report_facts_are_actually_persisted_to_the_database(
    session: AsyncSession, _use_ground_truth_stub: None
) -> None:
    """Not just returned -- durably committed, so a later pipeline stage
    reading straight from the database (not from this function's return
    value) sees them too."""
    matter_id, document = await _seed_matter_and_title_document(session)

    await extract_title_report_facts(session, matter_id=matter_id, document=document)

    from sqlalchemy import func, select

    count = (
        await session.execute(
            select(func.count()).select_from(Fact).where(Fact.matter_id == matter_id)
        )
    ).scalar_one()
    assert count > 0


async def test_extract_title_report_facts_returns_empty_for_document_with_no_text(
    session: AsyncSession,
) -> None:
    """No extracted text (e.g. OCR/parsing failed) must not call the LLM at
    all -- it should return no facts rather than sending an empty prompt."""

    def _fail(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise AssertionError("The extraction agent must not be called with no text")

    conversation = Conversation(id=uuid.uuid4().hex[:16], title="Test")
    session.add(conversation)
    await session.flush()
    matter = Matter(
        id=uuid.uuid4().hex[:16], conversation_id=conversation.id, gate_result="pending"
    )
    session.add(matter)
    document = Document(
        id=uuid.uuid4().hex[:16],
        conversation_id=conversation.id,
        filename="blank.pdf",
        display_name="blank.pdf",
        file_path="/uploads/blank.pdf",
        extracted_text=None,
        page_count=1,
    )
    session.add(document)
    await session.commit()
    await session.refresh(matter)
    await session.refresh(document)

    with title_extraction_agent.override(model=FunctionModel(_fail)):
        facts = await extract_title_report_facts(session, matter_id=matter.id, document=document)

    assert facts == []


async def test_extract_title_report_facts_propagates_llm_failures(
    session: AsyncSession,
) -> None:
    """A failed extraction call must not be silently swallowed (unlike the
    best-effort `classify_document_type` in `services/llm.py`): a solicitor
    relying on a risk review must never see a report silently missing a
    document's facts with no indication anything went wrong. The caller
    (a future pipeline-orchestration ticket) decides how to surface this,
    e.g. retry or mark the run as errored -- not this function."""

    def _raise(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        raise RuntimeError("simulated LLM failure")

    conversation = Conversation(id=uuid.uuid4().hex[:16], title="Test")
    session.add(conversation)
    await session.flush()
    matter = Matter(
        id=uuid.uuid4().hex[:16], conversation_id=conversation.id, gate_result="pending"
    )
    session.add(matter)
    document = Document(
        id=uuid.uuid4().hex[:16],
        conversation_id=conversation.id,
        filename="title-report-lot-7.pdf",
        display_name="title-report-lot-7.pdf",
        file_path=SAMPLE_TITLE_PDF_PATH,
        extracted_text="--- Page 1 ---\nSome title report text.",
        page_count=1,
    )
    session.add(document)
    await session.commit()
    await session.refresh(matter)
    await session.refresh(document)

    with (
        title_extraction_agent.override(model=FunctionModel(_raise)),
        pytest.raises(Exception, match="simulated LLM failure"),
    ):
        await extract_title_report_facts(session, matter_id=matter.id, document=document)

    # No partial facts were left behind by the failed run.
    from sqlalchemy import func, select

    count = (
        await session.execute(
            select(func.count()).select_from(Fact).where(Fact.matter_id == matter.id)
        )
    ).scalar_one()
    assert count == 0
