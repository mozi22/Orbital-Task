"""In-process pub/sub for risk-review pipeline progress events (issue #38).

The trigger endpoint (`takehome.web.routers.risk_review.trigger_risk_review`)
kicks the pipeline off as a `BackgroundTasks` job -- the HTTP response for
that POST returns immediately (202), well before the pipeline finishes. So,
unlike the chat SSE stream (`messages.send_message`), which streams straight
out of the same request that's doing the work, progress here has to cross
from one "producer" (the background pipeline) to a separate "consumer"
(a later, independent GET request that opens the SSE stream) that may
attach before, during, or after the pipeline runs.

`ProgressBroker` is a small in-memory broker that makes that possible without
introducing an external message queue: every event a run publishes is kept
in an ordered buffer (so a subscriber that attaches late -- or after the run
has already finished -- still gets the full sequence from the start) and is
also fanned out live to any subscriber already attached. This mirrors the
scale of the rest of this codebase (single-process app, no Redis/Celery
anywhere else) rather than reaching for one prematurely.

This module owns *only* the transport (publish/subscribe, buffering,
termination). It has no opinion on what a pipeline stage's message text
looks like -- `takehome.pipeline.run` (today) and later real stage modules
(extraction, gate, rules) are the callers that decide *when* to call
`publish_progress`/`publish_done`/`publish_error` and what to put in the
event. That split is what makes "compatible with the real stages as later
tickets land, no rework needed as a stage moves from stub to real" (issue
#38's acceptance criteria) true: a future ticket that replaces a stub stage
with real extraction logic calls the exact same `publish_progress` at the
same boundary, wrapped around now-real work instead of a synthetic loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Literal

ProgressEvent = dict[str, Any]

# Event `type`s a subscriber can see on the stream. "done" and "error" are
# both terminal -- once published, no further events for that run_id are
# expected, and `ProgressBroker.subscribe` stops iterating right after
# yielding one.
EventType = Literal["progress", "done", "error"]

_TERMINAL_EVENT_TYPES: frozenset[str] = frozenset({"done", "error"})


class ProgressBroker:
    """Buffers and fans out progress events for however many runs are
    in-flight (or already finished) at once, keyed by `run_id`.

    Not a singleton by construction -- callers get one from `get_progress_broker`
    below, which *is* the process-wide instance every publisher/subscriber
    shares, the same way `takehome.db.session`'s module-level `engine` is a
    single shared instance rather than a class other code is expected to
    instantiate itself.
    """

    def __init__(self) -> None:
        self._buffers: dict[str, list[ProgressEvent]] = {}
        self._subscriber_queues: dict[str, list[asyncio.Queue[ProgressEvent]]] = {}

    def publish(self, run_id: str, event: ProgressEvent) -> None:
        """Record `event` for `run_id` and hand a copy to every subscriber
        currently attached.

        Synchronous (not a coroutine): this only ever touches in-memory
        dicts/lists and `asyncio.Queue.put_nowait` (queues here are
        unbounded, so `put_nowait` never blocks or raises `QueueFull`), so
        there is nothing to `await`. That matters for `subscribe` below: the
        "snapshot the buffer, then register a queue for what comes next"
        sequence has no `await` between those two steps, so nothing
        published in between can be missed or double-delivered even though
        this is cooperatively (not preemptively) scheduled.
        """
        self._buffers.setdefault(run_id, []).append(event)
        for queue in self._subscriber_queues.get(run_id, []):
            queue.put_nowait(event)

    async def subscribe(self, run_id: str) -> AsyncIterator[ProgressEvent]:
        """Yield every event published for `run_id`, from the start of the
        run, regardless of whether the caller attached before the run
        started, mid-run, or after it already finished.

        Stops (without the caller needing to detect a "done" event itself)
        right after yielding a terminal (`done`/`error`) event.
        """
        buffered = list(self._buffers.get(run_id, []))
        queue: asyncio.Queue[ProgressEvent] = asyncio.Queue()
        self._subscriber_queues.setdefault(run_id, []).append(queue)

        try:
            for event in buffered:
                yield event
                if event["type"] in _TERMINAL_EVENT_TYPES:
                    return

            while True:
                event = await queue.get()
                yield event
                if event["type"] in _TERMINAL_EVENT_TYPES:
                    return
        finally:
            self._subscriber_queues.get(run_id, []).remove(queue)


# The process-wide broker instance. Kept as a module-level singleton (rather
# than, say, a FastAPI dependency) because the publishing side -- the
# background pipeline job -- is not a request handler and has no request
# scope to receive a dependency through; both sides just import this module.
_broker = ProgressBroker()


def get_progress_broker() -> ProgressBroker:
    """The process-wide `ProgressBroker` instance every publisher/subscriber
    shares. A function (not a bare module attribute) so tests can monkeypatch
    it the same way `takehome.db.session.get_session_factory` is reached
    through a function rather than the module attribute directly.
    """
    return _broker


def publish_progress(run_id: str, *, stage: str, message: str, **detail: Any) -> None:
    """Publish one non-terminal progress event for `run_id`.

    `stage` is one of the pipeline's stage boundaries (see
    `takehome.pipeline.run`'s `PipelineStage`) -- e.g. `"classify"`,
    `"extract"`, `"gate"`, `"rules"`. `message` is the human-readable line a
    client renders (e.g. "Extracting facts from lease.pdf..."). Any extra
    keyword args (e.g. `document_id=`, `rule_id=`) are carried alongside so a
    client can key off structured fields instead of parsing `message`.
    """
    event: ProgressEvent = {"type": "progress", "stage": stage, "message": message, **detail}
    get_progress_broker().publish(run_id, event)


def publish_done(run_id: str) -> None:
    """Publish the terminal "the run finished" event for `run_id`."""
    get_progress_broker().publish(run_id, {"type": "done"})


def publish_error(run_id: str, message: str) -> None:
    """Publish the terminal "the run failed" event for `run_id`."""
    get_progress_broker().publish(run_id, {"type": "error", "message": message})
