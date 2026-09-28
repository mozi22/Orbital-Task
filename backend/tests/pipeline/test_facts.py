"""Tests for the shared Fact wrapper (`ExtractedFact`/`SourceSpan`) and its
persistence (`save_facts`) into the `facts` table.

Uses the root `backend/tests/conftest.py` session fixture (ORM
`create_all`/`drop_all` per test), not `backend/tests/db`'s Alembic-driven
fixtures -- this module tests the persistence *function*, not the
migration itself (see `backend/tests/db/test_facts_table.py` for that).
"""

from __future__ import annotations

import uuid

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from takehome.db.models import Conversation, Fact, FactStatus, Matter
from takehome.pipeline.extract_lease_core_terms import (
    LeaseCoreTermsExtraction,
    PartyExtraction,
    TextField,
    extract_lease_core_terms,
    lease_core_terms_agent,
)
from takehome.pipeline.facts import ExtractedFact, SourceSpan, save_facts


async def _make_matter(session: AsyncSession) -> str:
    conversation = Conversation(id=uuid.uuid4().hex[:16])
    session.add(conversation)
    await session.commit()

    matter = Matter(
        id=uuid.uuid4().hex[:16], conversation_id=conversation.id, gate_result="pending"
    )
    session.add(matter)
    await session.commit()
    return matter.id


async def test_save_facts_persists_all_fields(session: AsyncSession) -> None:
    matter_id = await _make_matter(session)

    fact = ExtractedFact(
        key="lease.landlord.name",
        value="Bishopsgate Property Holdings Ltd",
        normalised_value="Bishopsgate Property Holdings Limited",
        unit=None,
        sources=[
            SourceSpan(
                document_id="doc-1",
                pdf_page_index=3,
                clause_ref="1.1",
                quote="Bishopsgate Property Holdings Ltd",
            )
        ],
        confidence=0.95,
        status=FactStatus.EXTRACTED,
    )

    saved = await save_facts(session, matter_id, [fact])

    assert len(saved) == 1
    row = saved[0]
    assert row.matter_id == matter_id
    assert row.key == "lease.landlord.name"
    assert row.value == "Bishopsgate Property Holdings Ltd"
    assert row.normalised_value == "Bishopsgate Property Holdings Limited"
    assert row.confidence == pytest.approx(0.95)
    assert row.status == "extracted"
    assert row.sources == [
        {
            "document_id": "doc-1",
            "pdf_page_index": 3,
            "printed_page_label": None,
            "clause_ref": "1.1",
            "quote": "Bishopsgate Property Holdings Ltd",
            "char_start": None,
            "char_end": None,
        }
    ]


async def test_not_found_fact_can_have_no_sources(session: AsyncSession) -> None:
    matter_id = await _make_matter(session)

    fact = ExtractedFact(
        key="lease.guarantor.name",
        value=None,
        normalised_value=None,
        sources=[],
        confidence=0.0,
        status=FactStatus.NOT_FOUND,
    )

    saved = await save_facts(session, matter_id, [fact])

    assert saved[0].status == "not_found"
    assert saved[0].sources == []
    assert saved[0].value is None


async def test_save_facts_replaces_existing_rows_for_the_same_key(session: AsyncSession) -> None:
    matter_id = await _make_matter(session)

    first = ExtractedFact(
        key="lease.term.start_date",
        value="1 January 2024",
        normalised_value="2024-01-01",
        sources=[SourceSpan(document_id="doc-1", pdf_page_index=4, quote="1 January 2024")],
        confidence=0.9,
        status=FactStatus.EXTRACTED,
    )
    await save_facts(session, matter_id, [first])

    second = ExtractedFact(
        key="lease.term.start_date",
        value="1 February 2024",
        normalised_value="2024-02-01",
        sources=[SourceSpan(document_id="doc-1", pdf_page_index=4, quote="1 February 2024")],
        confidence=0.9,
        status=FactStatus.EXTRACTED,
    )
    await save_facts(session, matter_id, [second])

    result = await session.execute(
        select(Fact).where(Fact.matter_id == matter_id, Fact.key == "lease.term.start_date")
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].normalised_value == "2024-02-01"


async def test_save_facts_for_one_key_set_does_not_delete_other_keys(session: AsyncSession) -> None:
    matter_id = await _make_matter(session)

    await save_facts(
        session,
        matter_id,
        [
            ExtractedFact(
                key="lease.landlord.name",
                value="Acme Ltd",
                sources=[],
                confidence=0.9,
                status=FactStatus.EXTRACTED,
            )
        ],
    )
    await save_facts(
        session,
        matter_id,
        [
            ExtractedFact(
                key="lease.tenant.name",
                value="Widgets LLP",
                sources=[],
                confidence=0.9,
                status=FactStatus.EXTRACTED,
            )
        ],
    )

    result = await session.execute(select(Fact).where(Fact.matter_id == matter_id))
    keys = {row.key for row in result.scalars().all()}
    assert keys == {"lease.landlord.name", "lease.tenant.name"}


async def test_extracted_lease_facts_can_be_saved_end_to_end(session: AsyncSession) -> None:
    """Sanity check that `extract_lease_core_terms`'s output is directly
    consumable by `save_facts` -- the two modules' contracts actually line
    up, not just each in isolation."""
    matter_id = await _make_matter(session)

    extraction = LeaseCoreTermsExtraction(
        landlord=PartyExtraction(
            name=TextField(
                value="Acme Holdings Ltd", quote="Acme Holdings Ltd", page=3, confidence=0.9
            )
        )
    )

    def _stub(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        tool = info.output_tools[0]
        return ModelResponse(
            parts=[ToolCallPart(tool_name=tool.name, args=extraction.model_dump(mode="json"))]
        )

    with lease_core_terms_agent.override(model=FunctionModel(_stub)):
        facts = await extract_lease_core_terms("... irrelevant text ...", "doc-1")

    saved = await save_facts(session, matter_id, facts)

    by_key = {row.key: row for row in saved}
    assert by_key["lease.landlord.name"].normalised_value == "Acme Holdings Limited"
    assert by_key["lease.guarantor.name"].status == "not_found"
