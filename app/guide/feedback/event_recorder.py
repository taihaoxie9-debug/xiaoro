from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import secrets

from app.guide.feedback.event_contracts import (
    ClickFeedbackPayload,
    CompareFeedbackPayload,
    FavoriteFeedbackPayload,
    FeedbackActorContext,
    FeedbackEventRequest,
    NegativeFeedbackPayload,
    RecordedFeedbackEvent,
)
from app.guide.feedback.event_ports import (
    FeedbackConversationReferencePort,
    FeedbackEventStorePort,
    FeedbackIdempotencyConflict,
    FeedbackProfileReferencePort,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _event_id() -> str:
    return f"feedback_event_{secrets.token_urlsafe(24)}"


class FeedbackAuthorizationError(RuntimeError):
    pass


class FeedbackReferenceError(RuntimeError):
    pass


class ForeignFeedbackProductError(RuntimeError):
    pass


class FeedbackClockError(RuntimeError):
    pass


class FeedbackEventRecorder:
    def __init__(
        self,
        *,
        store: FeedbackEventStorePort,
        conversation_references: FeedbackConversationReferencePort,
        profile_references: FeedbackProfileReferencePort,
        clock: Callable[[], datetime] = _utc_now,
        event_id_factory: Callable[[], str] = _event_id,
    ) -> None:
        self._store = store
        self._conversation_references = conversation_references
        self._profile_references = profile_references
        self._clock = clock
        self._event_id_factory = event_id_factory

    def record(
        self,
        request: FeedbackEventRequest,
        *,
        actor: FeedbackActorContext,
    ) -> RecordedFeedbackEvent:
        candidate = request.model_copy(deep=True)
        trusted_actor = actor.model_copy(deep=True)
        if (
            candidate.conversation.session_id
            != trusted_actor.authorized_session_id
        ):
            raise FeedbackAuthorizationError(
                "conversation is not authorized for this actor"
            )
        existing = self._store.load(
            owner=trusted_actor.owner,
            idempotency_key=candidate.idempotency_key,
        )
        if existing is not None:
            if existing.to_request() != candidate:
                raise FeedbackIdempotencyConflict(
                    candidate.idempotency_key
                )
            return existing.model_copy(deep=True)

        context = self._conversation_references.load(
            actor=trusted_actor,
            reference=candidate.conversation,
        )
        if (
            context is None
            or context.reference != candidate.conversation
        ):
            raise FeedbackReferenceError(
                "conversation reference is unavailable"
            )
        if context.owner != trusted_actor.owner:
            raise FeedbackAuthorizationError(
                "conversation owner does not match event owner"
            )

        referenced_products = _referenced_product_ids(candidate)
        if not set(referenced_products).issubset(context.product_ids):
            raise ForeignFeedbackProductError(
                "feedback references a foreign product"
            )

        if (
            candidate.profile is not None
            and candidate.profile != context.profile
        ):
            raise FeedbackReferenceError(
                "profile reference does not match feedback target"
            )
        if (
            candidate.profile is not None
            and not self._profile_references.exists(
                actor=trusted_actor,
                reference=candidate.profile,
            )
        ):
            raise FeedbackReferenceError(
                "profile reference is unavailable"
            )

        event = RecordedFeedbackEvent(
            **candidate.model_dump(),
            owner=trusted_actor.owner,
            event_id=self._event_id_factory(),
            occurred_at=self._now(),
        )
        return self._store.record_once(event).model_copy(deep=True)

    def _now(self) -> datetime:
        now = self._clock()
        if now.utcoffset() is None:
            raise FeedbackClockError(
                "clock must return a timezone-aware datetime"
            )
        return now.astimezone(UTC)


def _referenced_product_ids(
    request: FeedbackEventRequest,
) -> tuple[int, ...]:
    payload = request.payload
    if isinstance(
        payload,
        (ClickFeedbackPayload, FavoriteFeedbackPayload),
    ):
        return (payload.product_id,)
    if isinstance(payload, CompareFeedbackPayload):
        return tuple(payload.product_ids)
    if isinstance(payload, NegativeFeedbackPayload):
        return (
            (payload.product_id,)
            if payload.product_id is not None
            else ()
        )
    raise TypeError("unsupported feedback payload")
