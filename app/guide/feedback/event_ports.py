from __future__ import annotations

from typing import Protocol

from app.guide.feedback.contracts import ConversationVersionRef
from app.guide.feedback.event_contracts import (
    FeedbackActorContext,
    FeedbackConversationContext,
    FeedbackProfileVersionRef,
    RecordedFeedbackEvent,
)
from app.guide.feedback.profile_contracts import ProfileOwnerRef


class FeedbackIdempotencyConflict(RuntimeError):
    pass


class FeedbackEventStoreCorrupt(RuntimeError):
    pass


class FeedbackEventStorePort(Protocol):
    def load(
        self,
        *,
        owner: ProfileOwnerRef,
        idempotency_key: str,
    ) -> RecordedFeedbackEvent | None: ...

    def record_once(
        self,
        event: RecordedFeedbackEvent,
    ) -> RecordedFeedbackEvent: ...


class FeedbackConversationReferencePort(Protocol):
    def load(
        self,
        *,
        actor: FeedbackActorContext,
        reference: ConversationVersionRef,
    ) -> FeedbackConversationContext | None: ...


class FeedbackProfileReferencePort(Protocol):
    def exists(
        self,
        *,
        actor: FeedbackActorContext,
        reference: FeedbackProfileVersionRef,
    ) -> bool: ...
