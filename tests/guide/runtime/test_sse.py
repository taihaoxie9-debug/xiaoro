import asyncio
import multiprocessing
import os
from pathlib import Path
import threading
import time

import anyio
import pytest

from app.guide_runtime import sse


def _hold_shared_operation_lock(
    lock_root: str,
    session_id: str,
    acquired,
    release,
) -> None:
    registry = sse.SessionOperationLockRegistry(
        lock_root=Path(lock_root),
    )
    with registry.for_session(session_id):
        acquired.set()
        release.wait(timeout=5)


def _enter_shared_operation_lock(
    lock_root: str,
    session_id: str,
    entered,
) -> None:
    registry = sse.SessionOperationLockRegistry(
        lock_root=Path(lock_root),
    )
    with registry.for_session(session_id):
        entered.set()


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


def test_sync_iterator_uses_dedicated_limiter_for_every_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_run_sync = sse.anyio.to_thread.run_sync
    worker_calls = 0
    observed_limiters: list[object | None] = []
    default_limiters: list[object] = []

    async def recording_run_sync(function, *args, **kwargs):
        nonlocal worker_calls
        worker_calls += 1
        observed_limiters.append(kwargs.get("limiter"))
        return await real_run_sync(function, *args, **kwargs)

    monkeypatch.setattr(
        sse.anyio.to_thread,
        "run_sync",
        recording_run_sync,
    )

    async def exercise() -> list[bytes]:
        default_limiters.append(
            anyio.to_thread.current_default_thread_limiter()
        )
        return [
            frame
            async for frame in sse.iterate_http_events_in_threadpool(
                iter((b"one", b"two"))
            )
        ]

    assert asyncio.run(exercise()) == [b"one", b"two"]
    assert worker_calls == 4
    assert all(limiter is not None for limiter in observed_limiters)
    assert all(
        limiter is not default_limiters[0]
        for limiter in observed_limiters
    )


def test_session_fence_is_shared_across_processes(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    acquired = context.Event()
    release = context.Event()
    entered = context.Event()
    lock_root = tmp_path / "session-locks"
    session_id = "cross-process-session"
    owner = context.Process(
        target=_hold_shared_operation_lock,
        args=(str(lock_root), session_id, acquired, release),
    )
    waiter = context.Process(
        target=_enter_shared_operation_lock,
        args=(str(lock_root), session_id, entered),
    )
    waiter_started = False
    owner.start()
    try:
        assert acquired.wait(timeout=5)
        waiter.start()
        waiter_started = True
        assert not entered.wait(timeout=0.25)
        release.set()
        assert entered.wait(timeout=5)
    finally:
        release.set()
        owner.join(timeout=5)
        if waiter_started:
            waiter.join(timeout=5)
        if owner.is_alive():
            owner.kill()
            owner.join(timeout=5)
        if waiter_started and waiter.is_alive():
            waiter.kill()
            waiter.join(timeout=5)
    assert owner.exitcode == 0
    assert waiter_started and waiter.exitcode == 0


def test_session_fence_uses_a_bounded_lock_file_set(
    tmp_path: Path,
) -> None:
    lock_root = tmp_path / "session-locks"
    registry = sse.SessionOperationLockRegistry(lock_root=lock_root)

    for ordinal in range(512):
        with registry.for_session(f"untrusted-session-{ordinal}"):
            pass

    lock_files = tuple(lock_root.glob("*.lock"))
    assert len(lock_files) <= 256
    assert all(path.is_file() for path in lock_files)


def test_session_fence_releases_thread_lock_when_descriptor_close_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    registry = sse.SessionOperationLockRegistry(
        lock_root=tmp_path / "session-locks"
    )
    operation_lock = registry.for_session("cleanup-failure")
    real_open = sse.os.open
    real_close = sse.os.close
    opened: list[int] = []
    close_calls: list[int] = []

    def record_open(*args, **kwargs) -> int:
        descriptor = real_open(*args, **kwargs)
        opened.append(descriptor)
        return descriptor

    def reject_flock(*_: object) -> None:
        raise OSError("simulated flock failure")

    def fail_first_close(descriptor: int) -> None:
        close_calls.append(descriptor)
        if len(close_calls) == 1:
            raise OSError("simulated close failure")
        real_close(descriptor)

    monkeypatch.setattr(sse.os, "open", record_open)
    monkeypatch.setattr(sse.fcntl, "flock", reject_flock)
    monkeypatch.setattr(sse.os, "close", fail_first_close)
    try:
        with pytest.raises(OSError, match="simulated flock failure"):
            operation_lock.__enter__()
    finally:
        monkeypatch.undo()
        for descriptor in opened:
            try:
                os.close(descriptor)
            except OSError:
                pass

    assert len(close_calls) == 2
    assert operation_lock._thread_lock.acquire(blocking=False)
    operation_lock._thread_lock.release()


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


def test_delivery_does_not_eagerly_drain_later_frames() -> None:
    first_generated = threading.Event()
    second_requested = threading.Event()
    release_second = threading.Event()

    def events():
        first_generated.set()
        yield b"first"
        second_requested.set()
        release_second.wait()
        yield b"second"

    async def exercise() -> tuple[bytes, bool, bytes]:
        stream = sse.iterate_http_events_in_threadpool(events())
        pending = asyncio.create_task(anext(stream))
        await asyncio.to_thread(first_generated.wait)
        await asyncio.sleep(0.05)
        eager_second_request = second_requested.is_set()
        release_second.set()
        first = await pending
        second = await anext(stream)
        await stream.aclose()
        return first, eager_second_request, second

    first, eager_second_request, second = asyncio.run(exercise())

    assert first == b"first"
    assert eager_second_request is False
    assert second == b"second"


def test_lock_waiters_cannot_starve_active_stream_iteration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sse,
        "_SSE_ITERATION_LIMITER",
        anyio.CapacityLimiter(2),
    )
    waiting_count_lock = threading.Lock()
    all_waiting = threading.Event()
    release_waiters = threading.Event()
    waiting_count = 0

    class ImmediateLock:
        def try_enter(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

    class BlockingLock:
        def _record_waiter(self) -> None:
            nonlocal waiting_count
            with waiting_count_lock:
                waiting_count += 1
                if waiting_count == 2:
                    all_waiting.set()

        def try_enter(self):
            self._record_waiter()
            return self if release_waiters.is_set() else False

        def __enter__(self):
            self._record_waiter()
            release_waiters.wait()
            return self

        def __exit__(self, *_: object) -> None:
            return None

    async def exercise() -> bool:
        holder = sse.iterate_http_events_in_threadpool(
            iter((b"first", b"second")),
            operation_lock=ImmediateLock(),
        )
        assert await anext(holder) == b"first"
        waiters = tuple(
            sse.iterate_http_events_in_threadpool(
                iter((b"waiter",)),
                operation_lock=BlockingLock(),
            )
            for _ in range(2)
        )
        waiter_tasks = tuple(
            asyncio.create_task(anext(stream))
            for stream in waiters
        )
        await asyncio.to_thread(all_waiting.wait)

        holder_next = asyncio.create_task(anext(holder))
        await asyncio.sleep(0.05)
        holder_was_starved = not holder_next.done()
        release_waiters.set()

        assert await holder_next == b"second"
        assert await asyncio.gather(*waiter_tasks) == [b"waiter", b"waiter"]
        await holder.aclose()
        for stream in waiters:
            await stream.aclose()
        return holder_was_starved

    assert asyncio.run(exercise()) is False


def test_session_lock_waiters_do_not_consume_acquisition_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sse,
        "_SESSION_LOCK_LIMITER",
        anyio.CapacityLimiter(2),
    )
    waiting_count_lock = threading.Lock()
    all_waiting = threading.Event()
    release_waiters = threading.Event()
    waiting_count = 0

    class ImmediateLock:
        def try_enter(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            return None

    class BlockingLock:
        def _record_waiter(self) -> None:
            nonlocal waiting_count
            with waiting_count_lock:
                waiting_count += 1
                if waiting_count == 2:
                    all_waiting.set()

        def try_enter(self):
            self._record_waiter()
            return self if release_waiters.is_set() else False

        def __enter__(self):
            self._record_waiter()
            release_waiters.wait()
            return self

        def __exit__(self, *_: object) -> None:
            return None

    async def exercise() -> bool:
        holder = sse.iterate_http_events_in_threadpool(
            iter((b"first", b"second")),
            operation_lock=ImmediateLock(),
        )
        assert await anext(holder) == b"first"
        waiters = tuple(
            sse.iterate_http_events_in_threadpool(
                iter((b"waiter",)),
                operation_lock=BlockingLock(),
            )
            for _ in range(2)
        )
        waiter_tasks = tuple(
            asyncio.create_task(anext(stream))
            for stream in waiters
        )
        await asyncio.to_thread(all_waiting.wait)

        unrelated = sse.iterate_http_events_in_threadpool(
            iter((b"unrelated",)),
            operation_lock=ImmediateLock(),
        )
        unrelated_next = asyncio.create_task(anext(unrelated))
        await asyncio.sleep(0.05)
        unrelated_was_starved = not unrelated_next.done()
        release_waiters.set()

        assert await unrelated_next == b"unrelated"
        assert await asyncio.gather(*waiter_tasks) == [
            b"waiter",
            b"waiter",
        ]
        await unrelated.aclose()
        for stream in waiters:
            await stream.aclose()
        return unrelated_was_starved

    assert asyncio.run(exercise()) is False


def test_cancelled_session_lock_waiter_does_not_wait_for_holder() -> None:
    entered = threading.Event()
    release = threading.Event()

    class BlockingLock:
        def try_enter(self):
            entered.set()
            return False

        def __enter__(self):
            entered.set()
            release.wait()
            return self

        def __exit__(self, *_: object) -> None:
            return None

    async def exercise() -> float:
        stream = sse.iterate_http_events_in_threadpool(
            iter((b"waiter",)),
            operation_lock=BlockingLock(),
        )
        pending = asyncio.create_task(anext(stream))
        await asyncio.to_thread(entered.wait)
        asyncio.get_running_loop().call_later(0.25, release.set)
        started = time.monotonic()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        elapsed = time.monotonic() - started
        await stream.aclose()
        return elapsed

    assert asyncio.run(exercise()) < 0.15


def test_cancelled_lock_acquire_releases_late_success() -> None:
    acquire_started = threading.Event()
    finish_acquire = threading.Event()
    released = threading.Event()

    class LateSuccessLock:
        def try_enter(self) -> bool:
            acquire_started.set()
            finish_acquire.wait(timeout=1)
            return True

        def __exit__(self, *_: object) -> None:
            released.set()

    async def exercise() -> None:
        stream = sse.iterate_http_events_in_threadpool(
            iter((b"unreachable",)),
            operation_lock=LateSuccessLock(),
        )
        pending = asyncio.create_task(anext(stream))
        await asyncio.to_thread(acquire_started.wait)
        pending.cancel()
        finish_acquire.set()
        with pytest.raises(asyncio.CancelledError):
            await pending
        await stream.aclose()

    asyncio.run(exercise())

    assert released.is_set()


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


def test_session_fence_blocks_delete_until_cancelled_producer_closes() -> None:
    session_id = "cancelled-session-fence"
    registry = sse.SessionOperationLockRegistry()
    started = threading.Event()
    release = threading.Event()
    delete_waiting = threading.Event()
    delete_completed = threading.Event()

    def events():
        started.set()
        release.wait()
        yield bytes(
            b'event: end\ndata: {"conversation_version":1}\n\n'
        )

    async def exercise() -> None:
        stream = sse.iterate_http_events_in_threadpool(
            events(),
            operation_lock=registry.for_session(session_id),
        )
        pending = asyncio.create_task(anext(stream))
        await asyncio.to_thread(started.wait)

        def delete_session() -> None:
            delete_waiting.set()
            with registry.for_session(session_id):
                delete_completed.set()

        delete_thread = threading.Thread(
            target=delete_session,
            daemon=True,
        )
        delete_thread.start()
        await asyncio.to_thread(delete_waiting.wait)
        await asyncio.sleep(0.05)
        assert not delete_completed.is_set()

        pending.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await pending
        await stream.aclose()
        delete_thread.join(timeout=1)

    asyncio.run(exercise())

    assert delete_completed.is_set()


def test_session_fence_remains_held_until_delivery_iterator_closes() -> None:
    session_id = "delivery-session-fence"
    registry = sse.SessionOperationLockRegistry()
    delete_started = threading.Event()
    delete_completed = threading.Event()
    delete_threads: list[threading.Thread] = []

    async def exercise() -> None:
        stream = sse.iterate_http_events_in_threadpool(
            iter((b"first", b"second")),
            operation_lock=registry.for_session(session_id),
        )
        assert await anext(stream) == b"first"

        def delete_session() -> None:
            delete_started.set()
            with registry.for_session(session_id):
                delete_completed.set()

        delete_thread = threading.Thread(
            target=delete_session,
            daemon=True,
        )
        delete_threads.append(delete_thread)
        delete_thread.start()
        await asyncio.to_thread(delete_started.wait)
        await asyncio.sleep(0.05)
        assert not delete_completed.is_set()
        await stream.aclose()
        delete_thread.join(timeout=1)

    asyncio.run(exercise())

    assert delete_threads
    assert not delete_threads[0].is_alive()
    assert delete_completed.is_set()
