from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from time import monotonic

from app.guide.feedback.contracts import ConversationSnapshot
from app.guide.feedback.ports import (
    ConversationStateConflict,
    ConversationStateCorrupt,
    validate_conversation_state_transition,
)
from app.guide.feedback.profile_contracts import ProfileOwnerRef


@dataclass(slots=True)
class _Entry:
    snapshot: ConversationSnapshot
    updated_at: float


class InMemoryConversationState:
    def __init__(
        self,
        *,
        max_sessions: int = 512,
        ttl_seconds: float = 1800,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if max_sessions <= 0:
            raise ValueError("max_sessions must be positive")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._max_sessions = max_sessions
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._entries: dict[str, _Entry] = {}
        self._lock = RLock()

    def load(self, session_id: str) -> ConversationSnapshot | None:
        with self._lock:
            now = self._clock()
            self._purge_expired(now)
            entry = self._entries.get(session_id)
            if entry is None:
                return None
            return entry.snapshot.model_copy(deep=True)

    def save(
        self,
        snapshot: ConversationSnapshot,
        *,
        expected_version: int,
    ) -> ConversationSnapshot:
        if type(snapshot) is not ConversationSnapshot:
            raise TypeError(
                "snapshot must be an exact ConversationSnapshot"
            )
        if (
            not isinstance(expected_version, int)
            or isinstance(expected_version, bool)
            or expected_version < 0
        ):
            raise ValueError(
                "expected_version must be a non-negative integer"
            )
        try:
            snapshot = ConversationSnapshot.model_validate(
                snapshot.model_dump(mode="python"),
                strict=True,
            )
        except (TypeError, ValueError):
            raise ConversationStateCorrupt(
                snapshot.session_id
            ) from None
        with self._lock:
            now = self._clock()
            self._purge_expired(now)
            current = self._entries.get(snapshot.session_id)
            current_version = (
                current.snapshot.version if current is not None else 0
            )
            if current_version != expected_version:
                raise ConversationStateConflict(snapshot.session_id)
            if (
                current is not None
                and snapshot.profile_owner
                != current.snapshot.profile_owner
            ):
                raise ConversationStateConflict(snapshot.session_id)
            if snapshot.version != expected_version + 1:
                raise ValueError("snapshot version must increment by one")
            validate_conversation_state_transition(
                current.snapshot if current is not None else None,
                snapshot,
            )
            if current is None and len(self._entries) >= self._max_sessions:
                oldest_session_id = min(
                    self._entries,
                    key=lambda key: (
                        self._entries[key].updated_at,
                        key,
                    ),
                )
                del self._entries[oldest_session_id]
            stored = snapshot.model_copy(deep=True)
            self._entries[snapshot.session_id] = _Entry(
                snapshot=stored,
                updated_at=now,
            )
            return stored.model_copy(deep=True)

    def delete(
        self,
        session_id: str,
        *,
        expected_owner: ProfileOwnerRef | None,
    ) -> bool:
        if not isinstance(session_id, str):
            raise TypeError("session_id must be a string")
        if (
            expected_owner is not None
            and type(expected_owner) is not ProfileOwnerRef
        ):
            raise TypeError(
                "expected_owner must be ProfileOwnerRef or None"
            )
        with self._lock:
            self._purge_expired(self._clock())
            current = self._entries.get(session_id)
            if (
                current is None
                or current.snapshot.profile_owner != expected_owner
            ):
                return False
            del self._entries[session_id]
            return True

    def _purge_expired(self, now: float) -> None:
        expired = [
            session_id
            for session_id, entry in self._entries.items()
            if now - entry.updated_at >= self._ttl_seconds
        ]
        for session_id in expired:
            del self._entries[session_id]
