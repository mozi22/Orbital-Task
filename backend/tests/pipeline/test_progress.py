"""Unit tests for the in-process progress broker (issue #38).

Covers this ticket's acceptance criteria at the transport level (the
end-to-end "one full sequence of progress events for a run" criterion is
covered by `tests/web/test_risk_review_progress_api.py`'s integration test
against the real pipeline + real HTTP layer):
  - a subscriber attaching *after* every event was published still gets the
    full, ordered sequence from the start (late/after-the-fact attach);
  - a subscriber attaching *before* anything is published receives events
    live, in publish order;
  - multiple concurrent subscribers to the same run each get their own,
    independent, complete copy of the sequence;
  - the stream ends by itself right after a terminal (`done`/`error`) event,
    without the caller needing to detect that itself;
  - events for one run never leak into another run's stream.
"""

from __future__ import annotations

import asyncio

from takehome.pipeline.progress import (
    ProgressBroker,
    publish_done,
    publish_error,
    publish_progress,
)


class TestSubscribeAfterPublishing:
    async def test_replays_the_full_sequence_including_the_terminal_event(self) -> None:
        broker = ProgressBroker()
        broker.publish("run-1", {"type": "progress", "stage": "classify", "message": "a"})
        broker.publish("run-1", {"type": "progress", "stage": "extract", "message": "b"})
        broker.publish("run-1", {"type": "done"})

        events = [event async for event in broker.subscribe("run-1")]

        assert events == [
            {"type": "progress", "stage": "classify", "message": "a"},
            {"type": "progress", "stage": "extract", "message": "b"},
            {"type": "done"},
        ]

    async def test_stream_ends_right_after_an_error_event_too(self) -> None:
        broker = ProgressBroker()
        broker.publish("run-1", {"type": "progress", "stage": "classify", "message": "a"})
        broker.publish("run-1", {"type": "error", "message": "boom"})

        events = [event async for event in broker.subscribe("run-1")]

        assert events[-1] == {"type": "error", "message": "boom"}
        assert len(events) == 2

    async def test_a_run_with_no_events_yet_yields_nothing_until_something_is_published(
        self,
    ) -> None:
        broker = ProgressBroker()

        async def _subscribe_and_collect() -> list[dict]:
            events = []
            async for event in broker.subscribe("run-1"):
                events.append(event)
            return events

        task = asyncio.ensure_future(_subscribe_and_collect())
        await asyncio.sleep(0)  # let the subscriber attach before anything is published
        assert not task.done()

        broker.publish("run-1", {"type": "done"})
        events = await asyncio.wait_for(task, timeout=1)

        assert events == [{"type": "done"}]


class TestLiveSubscription:
    async def test_a_subscriber_attached_before_publishing_receives_events_in_order(
        self,
    ) -> None:
        broker = ProgressBroker()
        collected: list[dict] = []

        async def _collect() -> None:
            async for event in broker.subscribe("run-1"):
                collected.append(event)

        task = asyncio.ensure_future(_collect())
        await asyncio.sleep(0)

        broker.publish("run-1", {"type": "progress", "stage": "classify", "message": "a"})
        broker.publish("run-1", {"type": "progress", "stage": "extract", "message": "b"})
        broker.publish("run-1", {"type": "done"})

        await asyncio.wait_for(task, timeout=1)

        assert collected == [
            {"type": "progress", "stage": "classify", "message": "a"},
            {"type": "progress", "stage": "extract", "message": "b"},
            {"type": "done"},
        ]


class TestMultipleSubscribers:
    async def test_each_subscriber_gets_its_own_complete_copy_of_the_sequence(self) -> None:
        broker = ProgressBroker()
        broker.publish("run-1", {"type": "progress", "stage": "classify", "message": "a"})
        broker.publish("run-1", {"type": "done"})

        first = [event async for event in broker.subscribe("run-1")]
        second = [event async for event in broker.subscribe("run-1")]

        assert first == second == [
            {"type": "progress", "stage": "classify", "message": "a"},
            {"type": "done"},
        ]


class TestRunIsolation:
    async def test_events_published_for_one_run_do_not_appear_in_another_runs_stream(
        self,
    ) -> None:
        broker = ProgressBroker()
        broker.publish("run-1", {"type": "progress", "stage": "classify", "message": "run 1"})
        broker.publish("run-1", {"type": "done"})
        broker.publish("run-2", {"type": "progress", "stage": "classify", "message": "run 2"})
        broker.publish("run-2", {"type": "done"})

        run_1_events = [event async for event in broker.subscribe("run-1")]
        run_2_events = [event async for event in broker.subscribe("run-2")]

        assert run_1_events == [
            {"type": "progress", "stage": "classify", "message": "run 1"},
            {"type": "done"},
        ]
        assert run_2_events == [
            {"type": "progress", "stage": "classify", "message": "run 2"},
            {"type": "done"},
        ]


class TestPublishHelpers:
    def test_publish_progress_shapes_a_progress_event_with_extra_detail(self) -> None:
        from takehome.pipeline.progress import get_progress_broker

        publish_progress(
            "run-progress",
            stage="extract",
            message="Extracting facts from lease.pdf...",
            document_id="doc-1",
        )

        stored = get_progress_broker()._buffers["run-progress"]
        assert stored == [
            {
                "type": "progress",
                "stage": "extract",
                "message": "Extracting facts from lease.pdf...",
                "document_id": "doc-1",
            }
        ]

    def test_publish_done_and_publish_error_shape_terminal_events(self) -> None:
        from takehome.pipeline.progress import get_progress_broker

        publish_done("run-done")
        publish_error("run-error", "something broke")

        assert get_progress_broker()._buffers["run-done"] == [{"type": "done"}]
        assert get_progress_broker()._buffers["run-error"] == [
            {"type": "error", "message": "something broke"}
        ]
