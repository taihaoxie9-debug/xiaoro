import asyncio
import threading

import anyio
import pytest

from app.guide_runtime import sse


def test_runtime_forwards_only_exact_preencoded_bytes() -> None:
    frames = (
        bytes(b'event: start\ndata: {"session_id":"runtime"}\n\n'),
        bytes(b'event: end\ndata: {"conversation_version":1}\n\n'),
    )
    forwarded = tuple(sse._validated_frames(frames))

    assert forwarded == frames
    assert all(
        actual is expected
        for actual, expected in zip(forwarded, frames, strict=True)
    )
    with pytest.raises(TypeError, match="pre-encoded SSE bytes"):
        tuple(sse._validated_frames((("start", {}),)))


def test_anyio_cancel_waits_for_next_before_close_and_drops_frame() -> None:
    started = threading.Event()
    cancellation_requested = threading.Event()
    release = threading.Event()
    next_finished = threading.Event()
    close_called = threading.Event()
    closed = threading.Event()
    close_before_next_finished = []
    delivered = []
    cancellation_propagated = []
    frame = bytes(
        b'event: end\ndata: {"conversation_version":1}\n\n'
    )

    def events():
        try:
            started.set()
            release.wait()
            yield frame
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


def test_cancel_waits_for_inflight_next_before_closing_generator() -> None:
    started = threading.Event()
    release = threading.Event()
    closed = threading.Event()

    def events():
        try:
            started.set()
            release.wait()
            yield bytes(b'event: message\ndata: {"content":"late"}\n\n')
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


def test_cancel_does_not_deliver_frame_returned_by_inflight_next() -> None:
    started = threading.Event()
    release = threading.Event()
    delivered = []

    def events():
        started.set()
        release.wait()
        yield bytes(
            b'event: end\ndata: {"conversation_version":1}\n\n'
        )

    async def exercise():
        stream = sse.iterate_http_events_in_threadpool(events())
        pending = asyncio.create_task(anext(stream))
        await asyncio.to_thread(started.wait)
        pending.cancel()
        release.set()
        try:
            delivered.append(await pending)
        except asyncio.CancelledError:
            pass
        await stream.aclose()

    asyncio.run(exercise())

    assert delivered == []
