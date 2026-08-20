import asyncio
import threading

import anyio

from app.guide.application import chat_api_adapter
from app.guide_runtime import sse


def test_runtime_uses_public_guide_event_name_without_legacy_alias() -> None:
    assert (
        sse.iter_guide_public_events
        is chat_api_adapter.iter_guide_public_events
    )
    retired_name = "_".join(
        ("iter", "slice1", "guide", "legacy", "sse", "events")
    )
    assert not hasattr(
        chat_api_adapter,
        retired_name,
    )


def test_anyio_cancel_waits_for_next_before_close_and_discards_event(
    monkeypatch,
) -> None:
    started = threading.Event()
    cancellation_requested = threading.Event()
    release = threading.Event()
    next_finished = threading.Event()
    close_called = threading.Event()
    closed = threading.Event()
    close_before_next_finished = []
    discarded = []
    delivered = []
    cancellation_propagated = []

    def events():
        try:
            started.set()
            release.wait()
            yield "end", {"conversation_version": 1}
        finally:
            closed.set()

    class ObservedEvents:
        def __init__(self) -> None:
            self.iterator = events()

        def __iter__(self):
            return self

        def __next__(self):
            try:
                return next(self.iterator)
            finally:
                next_finished.set()

        def close(self) -> None:
            close_before_next_finished.append(
                not next_finished.is_set()
            )
            try:
                self.iterator.close()
            finally:
                close_called.set()

    monkeypatch.setattr(
        sse,
        "discard_http_event_delivery",
        discarded.append,
    )
    stream = sse.iterate_http_events_in_threadpool(ObservedEvents())
    cancel_scope = []

    async def consume() -> None:
        with anyio.CancelScope() as scope:
            cancel_scope.append(scope)
            delivered.append(await anext(stream))
        cancellation_propagated.append(scope.cancelled_caught)

    async def exercise() -> None:
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(consume)
            await anyio.to_thread.run_sync(started.wait)
            cancel_scope[0].cancel()
            cancellation_requested.set()

    def release_after_cancel_is_handled() -> None:
        cancellation_requested.wait(timeout=1)
        close_called.wait(timeout=0.25)
        release.set()

    release_thread = threading.Thread(
        target=release_after_cancel_is_handled,
        daemon=True,
    )
    release_thread.start()
    try:
        anyio.run(exercise)
    finally:
        release.set()
        release_thread.join(timeout=1)

    assert close_before_next_finished == [False]
    assert close_called.is_set()
    assert closed.is_set()
    assert cancellation_propagated == [True]
    assert delivered == []
    assert discarded == [
        ("end", {"conversation_version": 1}),
    ]


def test_cancel_waits_for_inflight_next_before_closing_generator() -> None:
    started = threading.Event()
    release = threading.Event()
    closed = threading.Event()

    def events():
        try:
            started.set()
            release.wait()
            yield "message", {"content": "late"}
        finally:
            closed.set()

    async def exercise():
        iterator = events()
        stream = sse.iterate_http_events_in_threadpool(iterator)
        pending = asyncio.create_task(anext(stream))
        await asyncio.to_thread(started.wait)

        pending.cancel()
        await asyncio.sleep(0.05)
        cancellation_waited_for_next = not pending.done()
        release.set()
        try:
            await pending
        except BaseException as error:
            cancellation_error = error
        else:
            cancellation_error = None

        while iterator.gi_running:
            await asyncio.sleep(0)
        closed_by_adapter = closed.is_set()
        if not closed.is_set():
            iterator.close()
        await stream.aclose()
        return (
            cancellation_waited_for_next,
            cancellation_error,
            closed_by_adapter,
        )

    waited, error, closed_by_adapter = asyncio.run(exercise())

    assert isinstance(error, asyncio.CancelledError)
    assert waited is True
    assert closed_by_adapter is True


def test_cancel_discards_event_returned_by_inflight_next(
    monkeypatch,
) -> None:
    started = threading.Event()
    release = threading.Event()
    discarded = []

    def events():
        started.set()
        release.wait()
        yield "end", {"conversation_version": 1}

    monkeypatch.setattr(
        sse,
        "discard_http_event_delivery",
        discarded.append,
    )

    async def exercise():
        stream = sse.iterate_http_events_in_threadpool(events())
        pending = asyncio.create_task(anext(stream))
        await asyncio.to_thread(started.wait)
        pending.cancel()
        release.set()
        try:
            await pending
        except asyncio.CancelledError:
            pass
        await stream.aclose()

    asyncio.run(exercise())

    assert discarded == [
        ("end", {"conversation_version": 1}),
    ]
