"""Shared Server-Sent-Events plumbing for this app's two SSE producers --
`takehome.web.routers.messages.send_message` (chat) and
`takehome.web.routers.risk_review.stream_risk_review_progress` (risk-review
progress, issue #38).

Both endpoints stream `text/event-stream` responses shaped the same way: an
async generator yields already-framed `data: {...}\\n\\n` lines, wrapped in a
`StreamingResponse` with the same `Cache-Control`/`Connection`/
`X-Accel-Buffering` headers (the last one matters for anything sitting
behind an nginx-style buffering proxy in front of this app -- without it, a
proxy can hold the whole stream until it closes instead of forwarding each
event as it's produced). This module owns only that shared plumbing (event
framing, response envelope); it has no opinion on what either endpoint's
event payloads actually contain.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from typing import Any

from starlette.responses import StreamingResponse


def sse_event(data: Mapping[str, Any]) -> str:
    """Frame `data` as one SSE `data:` line, JSON-encoded."""
    return f"data: {json.dumps(data)}\n\n"


def sse_response(generator: AsyncIterator[str]) -> StreamingResponse:
    """Wrap an async generator of already-framed SSE lines (see `sse_event`)
    in the `text/event-stream` `StreamingResponse` both SSE endpoints in
    this app return.
    """
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
