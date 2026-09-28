"""Tests for `takehome.services.fact` (issue #41) -- the shared `Fact`
persistence CRUD every document type's extraction stage writes through."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from takehome.services.conversation import create_conversation
from takehome.services.fact import (
    NewFact,
    NewFactSource,
    compute_status,
    create_facts,
    decode_sources,
    decode_value,
    list_facts_for_matter,
)
from takehome.services.matter import get_or_create_matter


async def _make_matter_id(session: AsyncSession) -> str:
    conversation = await create_conversation(session)
    matter, _ = await get_or_create_matter(session, conversation.id)
    return matter.id


# =============================================================================
# compute_status
# =============================================================================


class TestComputeStatus:
    def test_missing_scalar_value_is_not_found(self) -> None:
        assert compute_status(value=None, confidence=0.9, normalisation_failed=False) == (
            "not_found"
        )

    def test_empty_string_is_not_found(self) -> None:
        assert compute_status(value="", confidence=0.9, normalisation_failed=False) == ("not_found")

    def test_empty_list_is_not_found(self) -> None:
        assert compute_status(value=[], confidence=0.9, normalisation_failed=False) == ("not_found")

    def test_false_boolean_is_a_real_found_value(self) -> None:
        assert compute_status(value=False, confidence=0.9, normalisation_failed=False) == "found"

    def test_normalisation_failure_forces_needs_checking_even_at_high_confidence(self) -> None:
        assert (
            compute_status(value="not a date", confidence=0.99, normalisation_failed=True)
            == "needs_checking"
        )

    def test_low_confidence_is_needs_checking(self) -> None:
        assert compute_status(value="x", confidence=0.5, normalisation_failed=False) == (
            "needs_checking"
        )

    def test_high_confidence_normal_value_is_found(self) -> None:
        assert compute_status(value="x", confidence=0.95, normalisation_failed=False) == "found"

    def test_confidence_exactly_at_threshold_is_found(self) -> None:
        assert compute_status(value="x", confidence=0.7, normalisation_failed=False) == "found"


# =============================================================================
# create_facts / list_facts_for_matter
# =============================================================================


async def test_create_facts_persists_every_field(session: AsyncSession) -> None:
    matter_id = await _make_matter_id(session)

    facts = await create_facts(
        session,
        matter_id,
        [
            NewFact(
                key="environmental.flood_zone",
                value="2",
                normalised_value=None,
                unit=None,
                confidence=0.92,
                status="found",
                sources=[
                    NewFactSource(
                        document_id="doc-1",
                        pdf_page_index=3,
                        clause_ref=None,
                        quote="Flood Zone 2",
                    )
                ],
            )
        ],
    )

    assert len(facts) == 1
    row = facts[0]
    assert row.matter_id == matter_id
    assert row.key == "environmental.flood_zone"
    assert decode_value(row.value) == "2"
    assert decode_value(row.normalised_value) is None
    assert row.confidence == 0.92
    assert row.status == "found"
    sources = decode_sources(row.source)
    assert sources == [
        {
            "document_id": "doc-1",
            "pdf_page_index": 3,
            "clause_ref": None,
            "quote": "Flood Zone 2",
        }
    ]


async def test_create_facts_with_no_sources_stores_null_source(session: AsyncSession) -> None:
    matter_id = await _make_matter_id(session)

    facts = await create_facts(
        session,
        matter_id,
        [
            NewFact(
                key="environmental.historical_uses",
                value=[],
                confidence=1.0,
                status="not_found",
            )
        ],
    )

    assert facts[0].source is None
    assert decode_sources(facts[0].source) == []


async def test_create_facts_encodes_list_shaped_values(session: AsyncSession) -> None:
    matter_id = await _make_matter_id(session)

    value = [{"from_year": 1920, "to_year": 1975, "use": "textile warehouse"}]
    facts = await create_facts(
        session,
        matter_id,
        [
            NewFact(
                key="environmental.historical_uses",
                value=value,
                confidence=0.9,
                status="found",
            )
        ],
    )

    assert decode_value(facts[0].value) == value


async def test_list_facts_for_matter_returns_only_that_matters_facts(
    session: AsyncSession,
) -> None:
    matter_id = await _make_matter_id(session)
    other_matter_id = await _make_matter_id(session)

    await create_facts(
        session,
        matter_id,
        [NewFact(key="environmental.flood_zone", value="2", confidence=0.9, status="found")],
    )
    await create_facts(
        session,
        other_matter_id,
        [NewFact(key="environmental.flood_zone", value="3", confidence=0.9, status="found")],
    )

    facts = await list_facts_for_matter(session, matter_id)

    assert len(facts) == 1
    assert facts[0].matter_id == matter_id
    assert decode_value(facts[0].value) == "2"


async def test_list_facts_for_matter_returns_empty_list_when_none_exist(
    session: AsyncSession,
) -> None:
    matter_id = await _make_matter_id(session)

    facts = await list_facts_for_matter(session, matter_id)

    assert facts == []
