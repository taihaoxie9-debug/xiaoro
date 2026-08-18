from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock


class InMemorySessionLocks:
    def __init__(self, *, stripes: int = 64) -> None:
        if stripes <= 0:
            raise ValueError("stripes must be positive")
        self._locks = tuple(Lock() for _ in range(stripes))

    @property
    def stripe_count(self) -> int:
        return len(self._locks)

    @contextmanager
    def hold(self, session_id: str) -> Iterator[None]:
        if not session_id:
            raise ValueError("session_id must not be empty")
        lock = self._locks[hash(session_id) % len(self._locks)]
        lock.acquire()
        try:
            yield
        finally:
            lock.release()
