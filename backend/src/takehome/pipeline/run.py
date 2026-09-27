"""Stub orchestration for a risk-review pipeline run (issue #35).

Kicked off in the background by `POST /api/conversations/{id}/risk-review`
(see `takehome.web.routers.risk_review`). This stands in for the full
pipeline the Milestone 2 PRD describes -- classify documents, extract the
24 facts, run the identity gate, run the rule catalogue, verify quotes,
build the report -- but does none of that real work yet: each stage is a
later, separate ticket. This function exists so the trigger endpoint has an
actual background job to kick off (not just a fire-and-forget no-op inline
in the router), and so those later tickets have one place to plug real
stage logic into without reshaping the endpoint that calls it.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger()


async def run_stub_pipeline(
    *, matter_id: str, conversation_id: str, document_ids: list[str]
) -> None:
    """Run the (currently stubbed) risk-review pipeline for one Matter.

    Does not touch the database or perform any extraction/gate/rules work --
    later tickets replace this body with real pipeline stages (classify,
    extract, gate, rules, quote-verify, report), each reading `document_ids`
    and writing its results against `matter_id`.
    """
    logger.info(
        "Risk-review stub pipeline started",
        matter_id=matter_id,
        conversation_id=conversation_id,
        document_count=len(document_ids),
    )

    # Real stages land here in later Milestone 2 tickets:
    #   1. Classify documents (if not already classified at upload time).
    #   2. Extract facts per document type.
    #   3. Run the identity gate (G-01, G-02, G-04).
    #   4. Run the remaining rule catalogue.
    #   5. Quote-verify every fact/flag.
    #   6. Build the final report.

    logger.info("Risk-review stub pipeline completed", matter_id=matter_id)
