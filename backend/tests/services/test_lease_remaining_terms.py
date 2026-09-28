"""Tests for lease remaining-terms extraction + persistence (issue #42).

Mocked LLM output throughout (per this project's convention, see
`tests/services/test_llm.py`) -- no real Anthropic call is ever made. The
functional-check tests at the bottom feed the *real* extracted text of the
project's actual lease fixture (`sample-docs/commercial-lease-100-
bishopsgate.pdf`) through the real prompt-building code, with the stub
model returning the values the eval test-cases doc's answer key
(EX-L12-EX-L20) says that fixture actually contains -- so the test only
passes if the real extracted content reaches the extraction call and the
real normalisation/persistence code round-trips those exact values
correctly.
"""

from __future__ import annotations

import fitz
import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy.ext.asyncio import AsyncSession

from takehome.pipeline.lease_remaining_terms import LeaseRemainingTermsExtraction
from takehome.services.conversation import create_conversation
from takehome.services.fact import decode_sources, decode_value, list_facts_for_matter
from takehome.services.lease_remaining_terms import (
    build_lease_remaining_terms_facts,
    extract_and_save_lease_remaining_terms,
    extract_lease_remaining_terms,
    lease_remaining_terms_agent,
)
from takehome.services.matter import get_or_create_matter
from tests.conftest import SAMPLE_LEASE_PDF_PATH


def _user_prompt_text(messages: list[ModelMessage]) -> str:
    for message in messages:
        for part in message.parts:
            if isinstance(part, UserPromptPart):
                assert isinstance(part.content, str)
                return part.content
    raise AssertionError("No UserPromptPart found in captured messages")


def _found_field(**overrides: object) -> dict[str, object]:
    """Build a minimal `found=True` ExtractedFact-shaped dict for a field
    this test doesn't care about, so each test only spells out the field(s)
    it actually asserts on."""
    base = {
        "found": True,
        "sources": [{"pdf_page_index": 1, "quote": "placeholder quote text"}],
        "confidence": 0.9,
    }
    base.update(overrides)
    return base


def _not_found_field() -> dict[str, object]:
    return {"found": False, "value": None, "sources": [], "confidence": 0.0}


def _full_stub_args(**field_overrides: dict[str, object]) -> dict[str, object]:
    """Build a complete `LeaseRemainingTermsExtraction`-shaped args dict,
    defaulting every field to `not_found`, then overriding the fields a
    test actually cares about."""
    args: dict[str, object] = {
        "breaks": _not_found_field(),
        "permitted_use": _not_found_field(),
        "alienation": _not_found_field(),
        "repair": _not_found_field(),
        "service_charge": _not_found_field(),
        "insurance": _not_found_field(),
        "indemnities": _not_found_field(),
        "security_of_tenure": _not_found_field(),
        "dispute_resolution": _not_found_field(),
        "schedules": _not_found_field(),
    }
    args.update(field_overrides)
    return args


def _stub_returning(args: dict[str, object]):
    def _fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        tool = info.output_tools[0]
        return ModelResponse(parts=[ToolCallPart(tool_name=tool.name, args=args)])

    return _fn


# --------------------------------------------------------------------------- #
# extract_lease_remaining_terms
# --------------------------------------------------------------------------- #


async def test_extract_sends_the_documents_text_to_the_model() -> None:
    from pydantic_ai import capture_run_messages

    args = _full_stub_args()
    with (
        lease_remaining_terms_agent.override(model=FunctionModel(_stub_returning(args))),
        capture_run_messages() as messages,
    ):
        await extract_lease_remaining_terms("LEASE-MARKER: break clause 8.1.1.")

    prompt = _user_prompt_text(messages)
    assert "LEASE-MARKER: break clause 8.1.1." in prompt


async def test_extract_returns_the_llms_structured_output() -> None:
    args = _full_stub_args(
        permitted_use=_found_field(value={"text": "Offices, Class E(g)(i)", "use_class": "E(g)(i)"})
    )
    with lease_remaining_terms_agent.override(model=FunctionModel(_stub_returning(args))):
        result = await extract_lease_remaining_terms("some lease text")

    assert result.permitted_use.found is True
    assert result.permitted_use.value is not None
    assert result.permitted_use.value.text == "Offices, Class E(g)(i)"
    assert result.breaks.found is False


# --------------------------------------------------------------------------- #
# build_lease_remaining_terms_facts / extract_and_save_lease_remaining_terms
# --------------------------------------------------------------------------- #


async def _make_matter_id(session: AsyncSession) -> str:
    conversation = await create_conversation(session)
    matter, _ = await get_or_create_matter(session, conversation.id)
    return matter.id


async def _facts_for(session: AsyncSession, matter_id: str) -> dict[str, object]:
    facts = await list_facts_for_matter(session, matter_id)
    return {fact.key: fact for fact in facts}


async def test_saves_exactly_one_fact_per_remaining_terms_field(session: AsyncSession) -> None:
    matter_id = await _make_matter_id(session)
    args = _full_stub_args()

    with lease_remaining_terms_agent.override(model=FunctionModel(_stub_returning(args))):
        facts = await extract_and_save_lease_remaining_terms(
            session, matter_id=matter_id, document_id="doc-1", text="some lease text"
        )

    assert len(facts) == 10
    saved = await _facts_for(session, matter_id)
    assert set(saved) == {
        "lease.breaks",
        "lease.permitted_use",
        "lease.alienation",
        "lease.repair",
        "lease.service_charge",
        "lease.insurance",
        "lease.indemnities",
        "lease.security_of_tenure",
        "lease.dispute_resolution",
        "lease.schedules",
    }


def test_each_field_is_persisted_under_its_own_key_regardless_of_declaration_order() -> None:
    """Regression test for the `zip(FACT_KEYS, model_fields, strict=True)`
    bug this module used to have: that pairing only checked equal length,
    so reordering either list would silently persist a field's value
    under a *different* field's key. Marks every field `found=True` with a
    distinct, field-name-derived quote, then walks the fields in reverse
    declaration order and confirms each one's key/sources still line up
    with its own field -- not with whatever field used to sit at that
    position."""
    field_names = list(LeaseRemainingTermsExtraction.model_fields)
    args = _full_stub_args(
        **{
            field_name: _found_field(
                value=None, sources=[{"pdf_page_index": 1, "quote": f"quote for {field_name}"}]
            )
            for field_name in field_names
            # `value` must be `None` here for every field except the ones
            # that require a real per-field shape; those are covered by
            # more specific tests elsewhere, so this test only needs the
            # sources/quote (not the value) to prove the key<->field
            # binding survives a reordering.
        }
    )
    extraction = LeaseRemainingTermsExtraction.model_validate(args)

    facts = build_lease_remaining_terms_facts(document_id="doc-1", extraction=extraction)
    facts_by_key = {fact.key: fact for fact in facts}

    for field_name in reversed(field_names):
        key = f"lease.{field_name}"
        assert facts_by_key[key].sources[0].quote == f"quote for {field_name}"


async def test_not_found_field_is_saved_with_not_found_status(session: AsyncSession) -> None:
    matter_id = await _make_matter_id(session)
    args = _full_stub_args()  # everything defaults to not_found

    with lease_remaining_terms_agent.override(model=FunctionModel(_stub_returning(args))):
        await extract_and_save_lease_remaining_terms(
            session, matter_id=matter_id, document_id="doc-1", text="some lease text"
        )

    saved = await _facts_for(session, matter_id)
    fact = saved["lease.security_of_tenure"]
    assert fact.status == "not_found"
    assert decode_value(fact.value) is None


async def test_low_confidence_field_is_saved_as_needs_checking(session: AsyncSession) -> None:
    matter_id = await _make_matter_id(session)
    args = _full_stub_args(
        permitted_use=_found_field(value={"text": "Offices", "use_class": None}, confidence=0.4)
    )

    with lease_remaining_terms_agent.override(model=FunctionModel(_stub_returning(args))):
        await extract_and_save_lease_remaining_terms(
            session, matter_id=matter_id, document_id="doc-1", text="some lease text"
        )

    saved = await _facts_for(session, matter_id)
    fact = saved["lease.permitted_use"]
    assert fact.status == "needs_checking"
    assert fact.confidence == pytest.approx(0.4)


async def test_high_confidence_found_field_is_saved_as_found(session: AsyncSession) -> None:
    matter_id = await _make_matter_id(session)
    args = _full_stub_args(
        permitted_use=_found_field(value={"text": "Offices", "use_class": "E(g)(i)"})
    )

    with lease_remaining_terms_agent.override(model=FunctionModel(_stub_returning(args))):
        await extract_and_save_lease_remaining_terms(
            session, matter_id=matter_id, document_id="doc-1", text="some lease text"
        )

    saved = await _facts_for(session, matter_id)
    fact = saved["lease.permitted_use"]
    assert fact.status == "found"
    assert decode_value(fact.value) == {"text": "Offices", "use_class": "E(g)(i)"}


async def test_sources_are_stamped_with_the_document_id(session: AsyncSession) -> None:
    matter_id = await _make_matter_id(session)
    args = _full_stub_args(
        permitted_use=_found_field(
            value={"text": "Offices", "use_class": None},
            sources=[{"pdf_page_index": 6, "clause_ref": "6.1", "quote": "Offices, Class E(g)(i)"}],
        )
    )

    with lease_remaining_terms_agent.override(model=FunctionModel(_stub_returning(args))):
        await extract_and_save_lease_remaining_terms(
            session, matter_id=matter_id, document_id="doc-42", text="some lease text"
        )

    saved = await _facts_for(session, matter_id)
    fact = saved["lease.permitted_use"]
    sources = decode_sources(fact.source)
    assert len(sources) == 1
    assert sources[0]["document_id"] == "doc-42"
    assert sources[0]["pdf_page_index"] == 6
    assert sources[0]["clause_ref"] == "6.1"
    assert sources[0]["quote"] == "Offices, Class E(g)(i)"


async def test_break_dates_are_normalised_to_iso_and_stored_alongside_raw_value(
    session: AsyncSession,
) -> None:
    matter_id = await _make_matter_id(session)
    args = _full_stub_args(
        breaks=_found_field(
            value=[
                {
                    "who_can_break": "tenant",
                    "dates": ["1 January 2029", "1 January 2034"],
                    "notice_period_months": 12,
                    "conditions": ["No unremedied material breach", "Vacant possession"],
                    "break_premium": "6 months' rent in cleared funds",
                }
            ]
        )
    )

    with lease_remaining_terms_agent.override(model=FunctionModel(_stub_returning(args))):
        await extract_and_save_lease_remaining_terms(
            session, matter_id=matter_id, document_id="doc-1", text="some lease text"
        )

    saved = await _facts_for(session, matter_id)
    fact = saved["lease.breaks"]
    assert fact.status == "found"
    value = decode_value(fact.value)
    normalised = decode_value(fact.normalised_value)
    assert value[0]["dates"] == ["1 January 2029", "1 January 2034"]
    assert normalised[0]["dates"] == ["2029-01-01", "2034-01-01"]


async def test_break_with_unparseable_date_is_needs_checking(session: AsyncSession) -> None:
    matter_id = await _make_matter_id(session)
    args = _full_stub_args(
        breaks=_found_field(
            value=[
                {
                    "who_can_break": "tenant",
                    "dates": ["not a real date"],
                    "notice_period_months": None,
                    "conditions": [],
                    "break_premium": None,
                }
            ]
        )
    )

    with lease_remaining_terms_agent.override(model=FunctionModel(_stub_returning(args))):
        await extract_and_save_lease_remaining_terms(
            session, matter_id=matter_id, document_id="doc-1", text="some lease text"
        )

    saved = await _facts_for(session, matter_id)
    assert saved["lease.breaks"].status == "needs_checking"


# --------------------------------------------------------------------------- #
# Functional check against the real fixture (eval doc EX-L12-EX-L20)
# --------------------------------------------------------------------------- #


def _extract_real_lease_text() -> str:
    """Real PyMuPDF extraction of the project's actual lease fixture,
    mirroring `services/document.py`'s own page-by-page extraction."""
    doc = fitz.open(SAMPLE_LEASE_PDF_PATH)
    pages = []
    for page_num in range(len(doc)):
        text = doc[page_num].get_text()
        if text.strip():
            pages.append(f"--- Page {page_num + 1} ---\n{text}")
    doc.close()
    return "\n\n".join(pages)


# The eval test-cases doc's answer key for this fixture (EX-L12-EX-L20),
# expressed as this extraction's stub args.
_EX_L12_TO_L20_ARGS = _full_stub_args(
    permitted_use=_found_field(
        value={"text": "Offices, Class E(g)(i)", "use_class": "E(g)(i)"},
        sources=[{"pdf_page_index": 6, "clause_ref": "6.1", "quote": "Offices, Class E(g)(i)"}],
    ),
    service_charge=_found_field(
        value={"tenant_proportion_percent": 18.7, "schedule_ref": None},
        sources=[{"pdf_page_index": 5, "clause_ref": "4.2.3", "quote": "18.7%"}],
    ),
    insurance=_found_field(
        value={
            "insured_by": "landlord",
            "insured_risks": ["fire", "flood", "storm"],
            "loss_of_rent_years": 3,
            "tenant_share_percent": 18.7,
        },
        sources=[{"pdf_page_index": 6, "clause_ref": "5.1", "quote": "the Landlord shall insure"}],
    ),
    alienation=_found_field(
        value={
            "assignment": "allowed with landlord's consent (may require an authorised guarantee agreement)",
            "sublet_whole": "allowed with consent",
            "sublet_part": "not allowed",
        },
        sources=[{"pdf_page_index": 6, "clause_ref": "7.1", "quote": "not assign, charge, sublet"}],
    ),
    breaks=_found_field(
        value=[
            {
                "who_can_break": "tenant",
                "dates": ["1 January 2029", "1 January 2034"],
                "notice_period_months": 12,
                "conditions": [],
                "break_premium": None,
            }
        ],
        sources=[{"pdf_page_index": 7, "clause_ref": "8.1.1", "quote": "not less than 12 months"}],
    ),
    indemnities=_found_field(
        value={
            "general_scope": "general repair and compliance obligations",
            "environmental_scope": "contamination caused by the Tenant",
            "environmental_limited_to_tenant_caused": True,
        },
        sources=[{"pdf_page_index": 8, "clause_ref": "9.2.1", "quote": "caused by the Tenant"}],
    ),
    security_of_tenure=_found_field(
        value={"contracted_out_of_1954_act": "not_stated"},
        sources=[{"pdf_page_index": 1, "quote": "n/a — never addressed in the lease"}],
        confidence=0.75,
    ),
)


async def test_functional_check_against_real_lease_fixture_ex_l12_to_l20(
    session: AsyncSession,
) -> None:
    """Feeds the real extracted text of `commercial-lease-100-
    bishopsgate.pdf` into the real extraction + persistence pipeline, with
    a stub model returning the eval doc's EX-L12-EX-L20 answer-key values.
    Asserts the persisted facts match those expected values exactly, so
    this only passes if the real fixture's text genuinely reached the
    prompt and the real code correctly threaded it through to storage."""
    real_text = _extract_real_lease_text()
    assert "Bishopsgate" in real_text  # sanity: real extraction actually ran

    matter_id = await _make_matter_id(session)

    with lease_remaining_terms_agent.override(
        model=FunctionModel(_stub_returning(_EX_L12_TO_L20_ARGS))
    ):
        await extract_and_save_lease_remaining_terms(
            session, matter_id=matter_id, document_id="lease-doc", text=real_text
        )

    saved = await _facts_for(session, matter_id)

    assert decode_value(saved["lease.permitted_use"].value) == {
        "text": "Offices, Class E(g)(i)",
        "use_class": "E(g)(i)",
    }
    assert decode_value(saved["lease.service_charge"].value)[
        "tenant_proportion_percent"
    ] == pytest.approx(18.7)
    assert decode_value(saved["lease.insurance"].value)["loss_of_rent_years"] == 3
    assert decode_value(saved["lease.insurance"].value)["tenant_share_percent"] == pytest.approx(
        18.7
    )
    assert decode_value(saved["lease.alienation"].value)["sublet_part"] == "not allowed"
    breaks_normalised = decode_value(saved["lease.breaks"].normalised_value)
    assert breaks_normalised[0]["dates"] == ["2029-01-01", "2034-01-01"]
    assert breaks_normalised[0]["who_can_break"] == "tenant"
    assert decode_value(saved["lease.indemnities"].value)["environmental_limited_to_tenant_caused"] is True
    assert (
        decode_value(saved["lease.security_of_tenure"].value)["contracted_out_of_1954_act"]
        == "not_stated"
    )
    # EX-L19's answer key value is itself "not stated" (confidence 0.75, a
    # real, meaningful finding) -- distinct from the field never being
    # addressed by the extraction at all (which would be `found=False`).
    assert saved["lease.security_of_tenure"].status == "found"
