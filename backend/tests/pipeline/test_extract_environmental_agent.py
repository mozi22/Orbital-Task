"""Tests for `environmental_extraction_agent`/`extract_environmental_report`
(issue #41) -- the LLM-call side of environmental report extraction.

Mirrors `tests/services/test_llm.py`'s `FunctionModel` stubbing pattern: no
real network call, just verifying the prompt sent to the model and that a
structured tool-call response round-trips into an
`EnvironmentalReportExtraction`. `tests/pipeline/test_extract_environmental.py`
covers the flattening/normalisation logic in isolation from the LLM call.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from pydantic_ai import capture_run_messages
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from takehome.pipeline.extract_environmental import (
    environmental_extraction_agent,
    extract_environmental_report,
)


def _user_prompt_text(messages: list[ModelMessage]) -> str:
    for message in messages:
        for part in message.parts:
            if isinstance(part, UserPromptPart):
                assert isinstance(part.content, str)
                return part.content
    raise AssertionError("No UserPromptPart found in captured messages")


_STUB_ARGS = {
    "report_metadata": {
        "report_reference": "GEC/2024/0142",
        "report_date": "2024-01-15",
        "consultant": "Greenfield Environmental Consultants Ltd",
        "authors": "J. Smith",
        "client_name": "Manchester Property Holdings Ltd",
        "confidence": 0.95,
        "source": {"pdf_page_index": 1, "clause_ref": None, "quote": "GEC/2024/0142"},
    },
    "reliance": {
        "who_may_rely": ["Manchester Property Holdings Ltd"],
        "third_party_reliance_allowed": False,
        "confidence": 0.9,
        "source": None,
    },
    "site": {
        "address": "15-21 Deansgate, Manchester M3 4FN",
        "postcode": "M3 4FN",
        "area_m2": "about 0.28 ha",
        "buildings": {
            "storeys": 4,
            "gross_internal_area_m2": "about 2,400 m2",
            "construction_year": 1920,
        },
        "confidence": 0.9,
        "source": None,
    },
    "historical_uses": [],
    "geology_water": {
        "geology_summary": None,
        "aquifer_classification": None,
        "nearest_watercourse_name": None,
        "nearest_watercourse_distance_m": None,
        "confidence": 0.9,
        "source": None,
    },
    "flood_risk": {
        "flood_zone": "2",
        "flood_defences": False,
        "confidence": 0.9,
        "source": None,
    },
    "contamination_status": {
        "contaminated_land_register_status": "Not determined as contaminated land",
        "air_quality_management_area": True,
        "confidence": 0.9,
        "source": None,
    },
    "pollution_incidents": [],
    "storage_tanks": [],
    "overall_risk": {
        "overall_risk_rating": "Low to moderate",
        "recommendations": [],
        "confidence": 0.9,
        "source": None,
    },
    "cost_estimates": [],
}


def _stub_extraction(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    tool = info.output_tools[0]
    return ModelResponse(parts=[ToolCallPart(tool_name=tool.name, args=_STUB_ARGS)])


@pytest.fixture(autouse=True)
def _use_stub_model() -> Iterator[None]:
    with environmental_extraction_agent.override(model=FunctionModel(_stub_extraction)):
        yield


async def test_extract_environmental_report_returns_the_structured_output() -> None:
    result = await extract_environmental_report("Some environmental report text.")

    assert result.report_metadata.report_reference == "GEC/2024/0142"
    assert result.site.buildings is not None
    assert result.site.buildings.storeys == 4
    assert result.flood_risk.flood_zone == "2"


async def test_extract_environmental_report_sends_the_documents_text_to_the_model() -> None:
    with capture_run_messages() as messages:
        await extract_environmental_report("ENV-MARKER: contaminated land register clear.")

    prompt = _user_prompt_text(messages)
    assert "ENV-MARKER: contaminated land register clear." in prompt
