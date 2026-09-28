from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.responses import StreamingResponse

from takehome.db.session import get_session, get_session_factory
from takehome.pipeline.progress import get_progress_broker
from takehome.pipeline.run import run_stub_pipeline
from takehome.services.conversation import get_conversation
from takehome.services.document import get_documents_for_conversation
from takehome.services.matter import get_matter_by_id, get_or_create_matter
from takehome.web.sse import sse_event, sse_response

logger = structlog.get_logger()

router = APIRouter(tags=["risk-review"])


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #


class RiskReviewTriggerResponse(BaseModel):
    # Currently backed 1:1 by the Matter's own id (see the Milestone 2 PRD --
    # a Matter is the aggregate root every later fact/flag hangs off), but
    # kept as its own `run_id` field name rather than `matter_id` so the
    # client-facing contract doesn't have to change if a future ticket adds
    # a distinct per-run record.
    run_id: str
    status: Literal["running"]


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #


@router.post(
    "/api/conversations/{conversation_id}/risk-review",
    response_model=RiskReviewTriggerResponse,
    status_code=202,
)
async def trigger_risk_review(
    conversation_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
    session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
) -> RiskReviewTriggerResponse:
    """Trigger a risk-review run for a conversation.

    Creates the conversation's Matter if this is the first run, otherwise
    reuses the existing one and re-runs against whatever documents are
    currently attached (see the Milestone 2 PRD's API surface). The actual
    pipeline work happens in a background job -- currently a stub (see
    `takehome.pipeline.run.run_stub_pipeline`); later Milestone 2 tickets
    replace its stages with real extraction/gate/rules logic without
    changing this endpoint's contract.

    Returns 404 if the conversation doesn't exist.
    """
    conversation = await get_conversation(session, conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "conversation_not_found",
                "message": "Conversation not found",
            },
        )

    matter, created = await get_or_create_matter(session, conversation_id)
    documents = await get_documents_for_conversation(session, conversation_id)
    document_ids = [d.id for d in documents]

    logger.info(
        "Risk review triggered",
        conversation_id=conversation_id,
        matter_id=matter.id,
        created_matter=created,
        document_count=len(document_ids),
    )

    background_tasks.add_task(
        run_stub_pipeline,
        matter_id=matter.id,
        conversation_id=conversation_id,
        document_ids=document_ids,
        session_factory=session_factory,
    )

    return RiskReviewTriggerResponse(run_id=matter.id, status="running")


@router.get("/api/matters/{run_id}/events")
async def stream_risk_review_progress(
    run_id: str,
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """Stream progress events for an in-flight (or already-finished)
    risk-review run over SSE (issue #38), reusing the same `text/event-stream`
    shape the chat message stream (`messages.send_message`) uses.

    `run_id` is the Matter id `trigger_risk_review` returned. Unlike the chat
    stream, this doesn't do any work itself -- it only subscribes to
    `takehome.pipeline.progress`'s broker, which the background pipeline job
    publishes into independently of this request. That means a client can
    open this stream before, during, or after the run: it always receives
    the full event sequence from the start (`classify` -> one `extract` per
    document -> one `gate` per gate rule -> one `rules` per remaining rule ->
    a terminal `done`), because the broker buffers every event rather than
    only fanning out live ones.

    Returns 404 if `run_id` doesn't correspond to any Matter that has ever
    had a risk review triggered.
    """
    matter = await get_matter_by_id(session, run_id)
    if matter is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "matter_not_found", "message": "Risk-review run not found"},
        )

    async def event_stream() -> AsyncIterator[str]:
        async for event in get_progress_broker().subscribe(run_id):
            yield sse_event(event)

    return sse_response(event_stream())
