"""Unit tests for lease core-term extraction (issue #40), with the LLM call
itself always stubbed via `FunctionModel` -- these test the flattening,
normalisation and status-assignment logic, not the model's own judgement.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from pydantic import ValidationError
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from takehome.db.models import FactStatus
from takehome.pipeline.extract_lease_core_terms import (
    BoolField,
    LeaseCoreTermsExtraction,
    ListField,
    PartyExtraction,
    PremisesExtraction,
    RentExtraction,
    RentReviewExtraction,
    TermExtraction,
    TextField,
    extract_lease_core_terms,
    flatten_lease_core_terms,
    lease_core_terms_agent,
)

DOCUMENT_ID = "doc-123"


def _stub(extraction: LeaseCoreTermsExtraction):
    def _fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        tool = info.output_tools[0]
        return ModelResponse(
            parts=[ToolCallPart(tool_name=tool.name, args=extraction.model_dump(mode="json"))]
        )

    return _fn


@pytest.fixture
def use_stub(request: pytest.FixtureRequest) -> Iterator[None]:
    extraction: LeaseCoreTermsExtraction = request.param
    with lease_core_terms_agent.override(model=FunctionModel(_stub(extraction))):
        yield


BISHOPSGATE_EXTRACTION = LeaseCoreTermsExtraction(
    lease_date=TextField(
        value="1 January 2024", quote="dated 1 January 2024", page=1, confidence=0.95
    ),
    execution_status=TextField(value="signed", quote="duly executed", page=9, confidence=0.9),
    is_dated=BoolField(value=True, quote="dated 1 January 2024", page=1, confidence=0.95),
    landlord=PartyExtraction(
        name=TextField(
            value="Bishopsgate Property Holdings Ltd",
            quote="Bishopsgate Property Holdings Ltd",
            page=3,
            confidence=0.95,
        ),
        company_or_llp_number=TextField(
            value="05198234", quote="Company No. 05198234", page=3, confidence=0.9
        ),
    ),
    tenant=PartyExtraction(
        name=TextField(
            value="Meridian Consulting Group LLP",
            quote="Meridian Consulting Group LLP",
            page=3,
            confidence=0.95,
        ),
        company_or_llp_number=TextField(
            value="OC412987", quote="Registration No. OC412987", page=3, confidence=0.9
        ),
    ),
    guarantor=PartyExtraction(),
    premises=PremisesExtraction(
        description=TextField(
            value="Floors 8, 9 and 10, 100 Bishopsgate, London EC2M 1GT",
            quote="Floors 8, 9 and 10, 100 Bishopsgate, London EC2M 1GT",
            page=3,
            confidence=0.9,
        ),
        floors=TextField(value="8, 9 and 10", quote="Floors 8, 9 and 10", page=3, confidence=0.9),
        net_internal_area=TextField(
            value="About 32,500 sq ft (3,019 m²)",
            quote="About 32,500 sq ft (3,019 m²)",
            page=4,
            confidence=0.85,
        ),
        building_name=TextField(
            value="100 Bishopsgate", quote="100 Bishopsgate", page=3, confidence=0.9
        ),
        building_address=TextField(
            value="100 Bishopsgate, London EC2M 1GT",
            quote="100 Bishopsgate, London EC2M 1GT",
            page=3,
            confidence=0.9,
        ),
    ),
    term=TermExtraction(
        length_years=TextField(
            value="15 years", quote="a term of 15 years", page=3, confidence=0.9
        ),
        start_date=TextField(
            value="1 January 2024", quote="from 1 January 2024", page=4, confidence=0.9
        ),
        end_date=TextField(
            value="31 December 2038", quote="to 31 December 2038", page=4, confidence=0.9
        ),
    ),
    rent=RentExtraction(
        initial_annual_amount=TextField(
            value="£850,000", quote="£850,000 a year", page=4, confidence=0.9
        ),
        vat_exclusive=BoolField(value=True, quote="excluding VAT", page=4, confidence=0.9),
        payment_frequency=TextField(
            value="quarterly", quote="paid quarterly", page=4, confidence=0.9
        ),
        payment_dates=ListField(
            value=["25 March", "24 June", "29 September", "25 December"],
            quote="the usual quarter days",
            page=4,
            confidence=0.7,
        ),
    ),
    rent_review=RentReviewExtraction(
        dates=ListField(
            value=["1 January 2029", "1 January 2034"],
            quote="1 January 2029 and 1 January 2034",
            page=3,
            confidence=0.9,
        ),
        basis=TextField(
            value="open market rent", quote="open market rent", page=4, confidence=0.85
        ),
        upward_only=BoolField(value=True, quote="upward only", page=5, confidence=0.9),
    ),
)


@pytest.mark.parametrize("use_stub", [BISHOPSGATE_EXTRACTION], indirect=True)
async def test_extract_lease_core_terms_flattens_and_normalises(use_stub: None) -> None:
    facts = await extract_lease_core_terms("... irrelevant raw text ...", DOCUMENT_ID)
    by_key = {f.key: f for f in facts}

    assert by_key["lease.lease_date"].normalised_value == "2024-01-01"
    assert by_key["lease.lease_date"].status == FactStatus.EXTRACTED

    assert by_key["lease.landlord.name"].normalised_value == "Bishopsgate Property Holdings Limited"
    assert by_key["lease.landlord.company_or_llp_number"].value == "05198234"

    assert by_key["lease.tenant.name"].normalised_value == "Meridian Consulting Group LLP"

    assert by_key["lease.term.length_years"].normalised_value == 15
    assert by_key["lease.term.length_years"].unit == "years"
    assert by_key["lease.term.start_date"].normalised_value == "2024-01-01"
    assert by_key["lease.term.end_date"].normalised_value == "2038-12-31"

    assert by_key["lease.rent.initial_annual_amount"].normalised_value == 85_000_000
    assert by_key["lease.rent.initial_annual_amount"].unit == "GBP"
    assert by_key["lease.rent.vat_exclusive"].normalised_value is True

    area_fact = by_key["lease.premises.net_internal_area"]
    assert area_fact.normalised_value["unit"] == "sq ft"
    assert area_fact.normalised_value["original_value"] == 32_500
    assert area_fact.unit == "sq ft"

    assert by_key["lease.rent_review.dates"].normalised_value == ["2029-01-01", "2034-01-01"]
    assert by_key["lease.rent_review.basis"].value == "open market rent"
    assert by_key["lease.rent_review.upward_only"].normalised_value is True

    source = by_key["lease.landlord.name"].sources[0]
    assert source.document_id == DOCUMENT_ID
    assert source.pdf_page_index == 3
    assert source.quote == "Bishopsgate Property Holdings Ltd"


@pytest.mark.parametrize("use_stub", [BISHOPSGATE_EXTRACTION], indirect=True)
async def test_guarantor_not_found_has_no_sources(use_stub: None) -> None:
    facts = await extract_lease_core_terms("... irrelevant raw text ...", DOCUMENT_ID)
    by_key = {f.key: f for f in facts}

    guarantor_name = by_key["lease.guarantor.name"]
    assert guarantor_name.status == FactStatus.NOT_FOUND
    assert guarantor_name.value is None
    assert guarantor_name.sources == []


def test_low_confidence_marks_needs_checking() -> None:
    extraction = LeaseCoreTermsExtraction(
        lease_date=TextField(value="1 January 2024", quote="q", page=1, confidence=0.4),
    )
    facts = flatten_lease_core_terms(extraction, DOCUMENT_ID)
    by_key = {f.key: f for f in facts}

    assert by_key["lease.lease_date"].status == FactStatus.NEEDS_CHECKING
    # A low-confidence fact still keeps its (successfully normalised) value.
    assert by_key["lease.lease_date"].normalised_value == "2024-01-01"


def test_unparseable_date_marks_needs_checking_with_no_normalised_value() -> None:
    extraction = LeaseCoreTermsExtraction(
        lease_date=TextField(value="not a real date", quote="q", page=1, confidence=0.9),
    )
    facts = flatten_lease_core_terms(extraction, DOCUMENT_ID)
    by_key = {f.key: f for f in facts}

    assert by_key["lease.lease_date"].status == FactStatus.NEEDS_CHECKING
    assert by_key["lease.lease_date"].normalised_value is None
    assert by_key["lease.lease_date"].value == "not a real date"


def test_partially_unparseable_date_list_marks_whole_fact_needs_checking() -> None:
    extraction = LeaseCoreTermsExtraction(
        rent_review=RentReviewExtraction(
            dates=ListField(
                value=["1 January 2029", "not a date"], quote="q", page=3, confidence=0.9
            )
        )
    )
    facts = flatten_lease_core_terms(extraction, DOCUMENT_ID)
    by_key = {f.key: f for f in facts}

    fact = by_key["lease.rent_review.dates"]
    assert fact.status == FactStatus.NEEDS_CHECKING
    assert fact.normalised_value == ["2029-01-01", None]


def test_every_field_not_found_produces_not_found_facts_with_no_crash() -> None:
    extraction = LeaseCoreTermsExtraction()
    facts = flatten_lease_core_terms(extraction, DOCUMENT_ID)

    assert len(facts) == 24
    assert all(f.status == FactStatus.NOT_FOUND for f in facts)
    assert all(f.sources == [] for f in facts)


@pytest.mark.parametrize("confidence", [-0.1, 1.5, 5.0])
def test_out_of_range_confidence_is_rejected_at_the_field_boundary(confidence: float) -> None:
    """`TextField`/`BoolField`/`ListField.confidence` must carry the same
    `ge=0.0, le=1.0` bound `ExtractedFact.confidence` already has -- without
    it, an out-of-range LLM-reported confidence would sail through field
    construction and only blow up later inside `_to_fact`'s `ExtractedFact(
    confidence=...)` call, crashing `flatten_lease_core_terms`'s entire
    24-field batch instead of failing fast, close to the untrusted input, at
    the schema boundary."""
    with pytest.raises(ValidationError):
        TextField(value="x", quote="q", page=1, confidence=confidence)
    with pytest.raises(ValidationError):
        BoolField(value=True, quote="q", page=1, confidence=confidence)
    with pytest.raises(ValidationError):
        ListField(value=["x"], quote="q", page=1, confidence=confidence)


async def test_a_single_out_of_range_confidence_field_does_not_crash_the_whole_extraction() -> None:
    """Simulates the LLM reporting an out-of-range confidence for exactly
    one of the 24 fields (bypassing normal construction by hand-crafting the
    raw tool-call args, since a real `TextField` can no longer hold an
    invalid value once constructed). This must surface as a well-defined
    `pydantic_ai` validation/retry failure -- not an obscure crash deep
    inside `_to_fact` for an unrelated field once 23 other, perfectly good
    fields have already been processed."""
    valid = LeaseCoreTermsExtraction(
        lease_date=TextField(value="1 January 2024", quote="q", page=1, confidence=0.9),
        execution_status=TextField(value="signed", quote="q", page=1, confidence=0.9),
    )
    bad_args = valid.model_dump(mode="json")
    bad_args["lease_date"]["confidence"] = 5.0

    def _bad_fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        tool = info.output_tools[0]
        return ModelResponse(parts=[ToolCallPart(tool_name=tool.name, args=bad_args)])

    with lease_core_terms_agent.override(model=FunctionModel(_bad_fn)):
        with pytest.raises(UnexpectedModelBehavior):
            await extract_lease_core_terms("... irrelevant text ...", DOCUMENT_ID)


async def test_extraction_sends_the_documents_text_to_the_model() -> None:
    from pydantic_ai import capture_run_messages
    from pydantic_ai.messages import UserPromptPart

    with (
        lease_core_terms_agent.override(model=FunctionModel(_stub(LeaseCoreTermsExtraction()))),
        capture_run_messages() as messages,
    ):
        await extract_lease_core_terms("LEASE-MARKER: unique document text.", DOCUMENT_ID)

    prompt = ""
    for message in messages:
        for part in message.parts:
            if isinstance(part, UserPromptPart):
                assert isinstance(part.content, str)
                prompt = part.content
    assert "LEASE-MARKER: unique document text." in prompt
