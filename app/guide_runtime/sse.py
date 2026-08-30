from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
import errno
import fcntl
from hashlib import sha256
import os
from pathlib import Path
import stat
from threading import Lock
from uuid import uuid4
from weakref import WeakValueDictionary

import anyio
from starlette.responses import StreamingResponse

from app.guide.application.contracts import TurnIdentity, UserTurn
from app.guide_runtime.contracts import ChatStreamRequest


_CLOSE_ON_EXEC = getattr(os, "O_CLOEXEC", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_NO_FOLLOW = getattr(os, "O_NOFOLLOW", 0)
_SESSION_LOCK_SHARD_COUNT = 256
_SESSION_LOCK_LIMITER = anyio.CapacityLimiter(32)
_SSE_ITERATION_LIMITER = anyio.CapacityLimiter(32)
_SSE_CLEANUP_LIMITER = anyio.CapacityLimiter(32)
_HTTP_EVENT_ITERATION_DONE = object()


def _session_lock_name(session_id: str) -> str:
    digest = sha256(session_id.encode("utf-8")).digest()
    shard = int.from_bytes(digest[:2], "big") % _SESSION_LOCK_SHARD_COUNT
    return f"session-{shard:03d}.lock"


class _SessionOperationLock:
    def __init__(
        self,
        *,
        thread_lock: Lock,
        lock_root: Path | None,
        lock_root_identity: tuple[int, int] | None,
        lock_name: str,
    ) -> None:
        self._thread_lock = thread_lock
        self._lock_root = lock_root
        self._lock_root_identity = lock_root_identity
        self._lock_name = lock_name
        self._root_descriptor: int | None = None
        self._lock_descriptor: int | None = None

    def _enter(self, *, non_blocking: bool) -> bool:
        if not self._thread_lock.acquire(blocking=not non_blocking):
            return False
        if self._lock_root is None:
            return True
        root_descriptor: int | None = None
        lock_descriptor: int | None = None
        try:
            root_descriptor = os.open(
                self._lock_root,
                os.O_RDONLY | _DIRECTORY | _NO_FOLLOW | _CLOSE_ON_EXEC,
            )
            root_stat = os.fstat(root_descriptor)
            if (
                self._lock_root_identity is None
                or (root_stat.st_dev, root_stat.st_ino)
                != self._lock_root_identity
                or not stat.S_ISDIR(root_stat.st_mode)
                or root_stat.st_uid != os.geteuid()
            ):
                raise PermissionError(
                    "session operation lock root changed"
                )
            lock_descriptor = os.open(
                self._lock_name,
                (
                    os.O_RDWR
                    | os.O_CREAT
                    | _NO_FOLLOW
                    | _CLOSE_ON_EXEC
                ),
                0o600,
                dir_fd=root_descriptor,
            )
            os.fchmod(lock_descriptor, 0o600)
            lock_stat = os.fstat(lock_descriptor)
            path_stat = os.stat(
                self._lock_name,
                dir_fd=root_descriptor,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(lock_stat.st_mode)
                or lock_stat.st_uid != os.geteuid()
                or (lock_stat.st_dev, lock_stat.st_ino)
                != (path_stat.st_dev, path_stat.st_ino)
            ):
                raise PermissionError(
                    "session operation lock file is invalid"
                )
            try:
                fcntl.flock(
                    lock_descriptor,
                    fcntl.LOCK_EX
                    | (fcntl.LOCK_NB if non_blocking else 0),
                )
            except OSError as error:
                if not (
                    non_blocking
                    and error.errno in {errno.EACCES, errno.EAGAIN}
                ):
                    raise
                for descriptor in (lock_descriptor, root_descriptor):
                    if descriptor is None:
                        continue
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass
                self._thread_lock.release()
                return False
            self._root_descriptor = root_descriptor
            self._lock_descriptor = lock_descriptor
            return True
        except BaseException:
            try:
                for descriptor in (lock_descriptor, root_descriptor):
                    if descriptor is None:
                        continue
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass
            finally:
                self._thread_lock.release()
            raise

    def __enter__(self):
        self._enter(non_blocking=False)
        return self

    def try_enter(self) -> bool:
        return self._enter(non_blocking=True)

    def __exit__(self, exc_type, exc, traceback) -> None:
        del exc_type, exc, traceback
        lock_descriptor = self._lock_descriptor
        root_descriptor = self._root_descriptor
        self._lock_descriptor = None
        self._root_descriptor = None
        cleanup_error: OSError | None = None
        try:
            if lock_descriptor is not None:
                try:
                    fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
                except OSError as error:
                    cleanup_error = error
                try:
                    os.close(lock_descriptor)
                except OSError as error:
                    cleanup_error = cleanup_error or error
            if root_descriptor is not None:
                try:
                    os.close(root_descriptor)
                except OSError as error:
                    cleanup_error = cleanup_error or error
        finally:
            self._thread_lock.release()
        if cleanup_error is not None and exc is None:
            raise cleanup_error


class SessionOperationLockRegistry:
    def __init__(self, *, lock_root: Path | None = None) -> None:
        self._guard = Lock()
        self._locks: WeakValueDictionary[str, object] = WeakValueDictionary()
        self._lock_root = (
            self._prepare_lock_root(lock_root)
            if lock_root is not None
            else None
        )
        self._lock_root_identity = (
            (
                self._lock_root.stat().st_dev,
                self._lock_root.stat().st_ino,
            )
            if self._lock_root is not None
            else None
        )

    @property
    def lock_root(self) -> Path | None:
        return self._lock_root

    def for_session(self, session_id: str):
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("session_id must be nonempty")
        lock_name = _session_lock_name(session_id)
        with self._guard:
            operation_lock = self._locks.get(lock_name)
            if operation_lock is None:
                operation_lock = _SessionOperationLock(
                    thread_lock=Lock(),
                    lock_root=self._lock_root,
                    lock_root_identity=self._lock_root_identity,
                    lock_name=lock_name,
                )
                self._locks[lock_name] = operation_lock
            return operation_lock

    def hold(self, session_id: str):
        return hold_session_operation_lock(self.for_session(session_id))

    @staticmethod
    def _prepare_lock_root(lock_root: Path) -> Path:
        if not isinstance(lock_root, Path):
            raise TypeError("lock_root must be a pathlib.Path")
        if lock_root.is_symlink():
            raise ValueError(
                "session operation lock root must not be a symlink"
            )
        lock_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        resolved = lock_root.resolve(strict=True)
        root_stat = resolved.stat()
        if (
            not stat.S_ISDIR(root_stat.st_mode)
            or root_stat.st_uid != os.geteuid()
        ):
            raise PermissionError(
                "session operation lock root is invalid"
            )
        os.chmod(resolved, 0o700)
        return resolved


class DeliveryStreamingResponse(StreamingResponse):
    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            close = getattr(self.body_iterator, "aclose", None)
            if close is not None:
                with anyio.CancelScope(shield=True):
                    await close()


@asynccontextmanager
async def hold_session_operation_lock(operation_lock):
    acquired = False
    body_error: BaseException | None = None
    if operation_lock is None:
        yield
        return
    while not acquired:
        acquire_task = asyncio.create_task(
            anyio.to_thread.run_sync(
                operation_lock.try_enter,
                limiter=_SESSION_LOCK_LIMITER,
            )
        )
        try:
            acquired = await asyncio.shield(acquire_task)
        except asyncio.CancelledError as cancelled:
            try:
                with anyio.CancelScope(shield=True):
                    acquired = await acquire_task
            except BaseException as error:
                raise error from cancelled
            if acquired:
                with anyio.CancelScope(shield=True):
                    await anyio.to_thread.run_sync(
                        _exit_session_operation_lock,
                        operation_lock,
                        cancelled,
                        limiter=_SESSION_LOCK_LIMITER,
                    )
            raise
        if not acquired:
            await anyio.sleep(0.01)
    try:
        yield
    except BaseException as error:
        body_error = error
        raise
    finally:
        with anyio.CancelScope(shield=True):
            await anyio.to_thread.run_sync(
                _exit_session_operation_lock,
                operation_lock,
                body_error,
                limiter=_SESSION_LOCK_LIMITER,
            )


def _exit_session_operation_lock(
    operation_lock,
    error: BaseException | None,
) -> None:
    operation_lock.__exit__(
        type(error) if error is not None else None,
        error,
        error.__traceback__ if error is not None else None,
    )


async def iterate_http_events_in_threadpool(
    events: Iterator[bytes],
    *,
    operation_lock=None,
) -> AsyncIterator[bytes]:
    iterator = iter(events)
    next_task = None
    iterator_closed = False
    try:
        async with hold_session_operation_lock(operation_lock):
            try:
                while True:
                    next_task = asyncio.create_task(
                        anyio.to_thread.run_sync(
                            _next_preencoded_frame,
                            iterator,
                            limiter=_SSE_ITERATION_LIMITER,
                        )
                    )
                    try:
                        event = await asyncio.shield(next_task)
                    except asyncio.CancelledError as cancelled:
                        try:
                            with anyio.CancelScope(shield=True):
                                await next_task
                        except BaseException as error:
                            raise error from cancelled
                        raise
                    next_task = None
                    if event is _HTTP_EVENT_ITERATION_DONE:
                        return
                    yield event
            finally:
                if next_task is not None and not next_task.done():
                    with anyio.CancelScope(shield=True):
                        await next_task
                iterator_closed = True
                with anyio.CancelScope(shield=True):
                    await anyio.to_thread.run_sync(
                        _close_preencoded_iterator,
                        iterator,
                        limiter=_SSE_CLEANUP_LIMITER,
                    )
    finally:
        if not iterator_closed:
            with anyio.CancelScope(shield=True):
                await anyio.to_thread.run_sync(
                    _close_preencoded_iterator,
                    iterator,
                    limiter=_SSE_CLEANUP_LIMITER,
                )


def _next_preencoded_frame(iterator) -> bytes | object:
    try:
        return next(iterator)
    except StopIteration:
        return _HTTP_EVENT_ITERATION_DONE


def _close_preencoded_iterator(iterator) -> None:
    close = getattr(iterator, "close", None)
    if close is not None:
        close()


def iter_http_events(
    unified_orchestrator,
    payload: ChatStreamRequest,
    *,
    profile_owner=None,
) -> Iterator[bytes]:
    session_id = payload.session_id or f"guide-{uuid4().hex}"
    identity = TurnIdentity(
        session_id=session_id,
        request_id=f"request_{uuid4().hex}",
        turn_id=f"turn_{uuid4().hex}",
    )
    turn = UserTurn(
        identity=identity,
        session_id=session_id,
        message=payload.message,
        image_action=payload.image_action,
        profile_owner=profile_owner,
        image_bundle_id=payload.image_bundle_id,
        image_bundle_version=payload.image_bundle_version,
        image_bundle_token=payload.image_bundle_token,
        conversation_version=payload.conversation_version,
    )
    frames = _validated_frames(
        unified_orchestrator.stream(turn)
    )
    yield from frames


def _validated_frames(frames) -> Iterator[bytes]:
    for frame in frames:
        if type(frame) is not bytes:
            raise TypeError(
                "unified flow must emit pre-encoded SSE bytes"
            )
        yield frame
