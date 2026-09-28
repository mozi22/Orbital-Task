"""Stub orchestration for a risk-review pipeline run (issue #35), now with
live progress narration over SSE (issue #38).

Kicked off in the background by `POST /api/conversations/{id}/risk-review`
(see `takehome.web.routers.risk_review`). This stands in for the full
pipeline the Milestone 2 PRD describes -- classify documents, extract the
24 facts, run the identity gate, run the rule catalogue, verify quotes,
build the report -- but does none of that real work yet: each stage is a
later, separate ticket. This function exists so the trigger endpoint has an
actual background job to kick off (not just a fire-and-forget no-op inline
in the router), and so those later tickets have one place to plug real
stage logic into without reshaping the endpoint that calls it.

What issue #38 adds on top of the #35 stub is progress narration at each
stage *boundary* -- classify, extract-per-document, gate-per-rule,
rule-per-rule -- published via `takehome.pipeline.progress.publish_progress`
so a client watching the SSE stream sees lines like "Extracting facts from
lease.pdf..." or "Running rule O-01: mortgage predates lease..." as the run
progresses, even though today's "work" at each boundary is a no-op. That
split (an orchestrator that walks fixed stage boundaries + a progress
transport that doesn't care what happens inside them) is what makes it
"compatible with the real stages as later tickets land, no rework needed as
a stage moves from stub to real" (issue #38's acceptance criteria): a later
ticket that replaces, say, the extract loop below with a real per-document
extraction call keeps the exact same `publish_progress(..., stage="extract",
...)` call already here, just wrapped around real work instead of nothing.

This module stays a single, separate `run.py` rather than growing "one
placeholder module per future stage" -- the package's own convention
(`takehome.pipeline.__init__`, and `normalise.py`'s existing precedent) is
already one module *per real stage* (parse, extract, normalise, gate,
rules, verify, report), not one per stub. `run_stub_pipeline` itself is the
orchestrator that will eventually call each of those stage modules in
sequence, not a stage itself -- so it has exactly one home, here, and later
tickets add real stage modules alongside it rather than adding to this
file or forking off new orchestrator modules.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from takehome.db.models import Document
from takehome.db.session import get_session_factory
from takehome.pipeline.progress import publish_done, publish_error, publish_progress
from takehome.pipeline.rule_catalogue import GATE_RULES, RULES

logger = structlog.get_logger()


async def run_stub_pipeline(
    *,
    matter_id: str,
    conversation_id: str,
    document_ids: list[str],
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> None:
    """Run the (currently stubbed) risk-review pipeline for one Matter.

    Does not touch the database to do any extraction/gate/rules work --
    later tickets replace each stage's body with real logic (classify,
    extract, gate, rules, quote-verify, report), each reading
    `document_ids` and writing its results against `matter_id`. It does
    read `document_ids` back into `Document` rows (display names only) so
    the per-document progress lines can name the actual file being
    "processed" rather than only its id.

    `session_factory` defaults to `takehome.db.session.get_session_factory()`
    if not given, but the trigger endpoint
    (`takehome.web.routers.risk_review.trigger_risk_review`) passes its own
    `Depends(get_session_factory)` value through explicitly instead of
    letting this function resolve the default itself -- this function is
    invoked directly via `BackgroundTasks.add_task`, not through FastAPI's
    dependency injection, so it would otherwise never see a test's
    `app.dependency_overrides[get_session_factory]` override (see
    `tests/conftest.py`'s `client` fixture) and would silently talk to the
    wrong engine/pool under test.

    Publishes progress events for `matter_id` throughout (see
    `takehome.pipeline.progress`) -- a client can subscribe to
    `GET /api/matters/{matter_id}/events` at any point (before, during, or
    after this coroutine runs) and see the full sequence from the start.
    """
    logger.info(
        "Risk-review stub pipeline started",
        matter_id=matter_id,
        conversation_id=conversation_id,
        document_count=len(document_ids),
    )

    try:
        # Stage 1: classify. Real classification already happens at upload
        # time (issue #32); this stage boundary exists for the re-check /
        # re-classify pass the PRD describes running as part of a review,
        # which is still a later ticket's job -- this is a no-op today.
        publish_progress(
            matter_id,
            stage="classify",
            message="Classifying uploaded documents...",
        )

        # Stage 2: extract-per-document.
        documents_by_id = await _load_documents(document_ids, session_factory)
        for document_id in document_ids:
            document = documents_by_id.get(document_id)
            display_name = document.display_name if document is not None else document_id
            publish_progress(
                matter_id,
                stage="extract",
                message=f"Extracting facts from {display_name}...",
                document_id=document_id,
            )

        # Stage 3: gate-per-rule (G-01, G-02, G-04).
        for rule in GATE_RULES:
            publish_progress(
                matter_id,
                stage="gate",
                message=f"Running gate check {rule.rule_id}: {rule.description}...",
                rule_id=rule.rule_id,
            )

        # Stage 4: rule-per-rule (the 9 remaining rules).
        for rule in RULES:
            publish_progress(
                matter_id,
                stage="rules",
                message=f"Running rule {rule.rule_id}: {rule.description}...",
                rule_id=rule.rule_id,
            )
    except Exception as exc:  # noqa: BLE001 - surfaced to the client as a terminal event
        # Not re-raised: the client-facing failure signal is the `error`
        # event published below (subscribers get it over SSE regardless of
        # when they attached), and it's already logged here. Re-raising on
        # top of that would only additionally surface as an unhandled
        # exception in `BackgroundTasks`' own runner, which has no bearing
        # on the request (the response was already sent) or on the client.
        logger.exception("Risk-review stub pipeline failed", matter_id=matter_id)
        publish_error(matter_id, str(exc))
        return

    publish_done(matter_id)

    logger.info("Risk-review stub pipeline completed", matter_id=matter_id)


async def _load_documents(
    document_ids: list[str],
    session_factory: async_sessionmaker[AsyncSession] | None,
) -> dict[str, Document]:
    """Look up `Document` rows for `document_ids`, keyed by id.

    Opens its own session (rather than being handed one already open)
    because this runs as a `BackgroundTasks` job, not a request handler --
    there is no request-scoped session still open by the time it runs (the
    same reason `messages.send_message`'s streaming generator opens its own
    session to save the assistant message after the response has already
    started streaming).
    """
    if not document_ids:
        return {}

    if session_factory is None:
        session_factory = get_session_factory()

    async with session_factory() as session:
        result = await session.execute(select(Document).where(Document.id.in_(document_ids)))
        return {document.id: document for document in result.scalars().all()}
