from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.guide.feedback.contracts import ConversationVersionRef
from app.guide.feedback.event_contracts import (
    ClickFeedbackPayload,
    CompareFeedbackPayload,
    FavoriteFeedbackPayload,
    FeedbackActorContext,
    FeedbackConversationContext,
    FeedbackEventRequest,
    FeedbackProfileVersionRef,
    NegativeFeedbackPayload,
    RecordedFeedbackEvent,
)
from app.guide.feedback.event_ports import FeedbackIdempotencyConflict
from app.guide.feedback.event_recorder import (
    FeedbackAuthorizationError,
    FeedbackClockError,
    FeedbackEventRecorder,
    FeedbackReferenceError,
    ForeignFeedbackProductError,
)
from app.guide.feedback.profile_contracts import ProfileOwnerRef


class Clock:
    def __init__(self) -> None:
        self.now = datetime(
            2026,
            8,
            9,
            12,
            30,
            tzinfo=timezone(timedelta(hours=8)),
        )
        self.calls = 0

    def __call__(self) -> datetime:
        self.calls += 1
        return self.now


class ConversationReferences:
    def __init__(self, context: FeedbackConversationContext) -> None:
        self.contexts = {
            (
                context.reference.session_id,
                context.reference.conversation_version,
            ): context
        }
        self.calls = 0

    def load(
        self,
        *,
        actor: FeedbackActorContext,
        reference: ConversationVersionRef,
    ) -> FeedbackConversationContext | None:
        assert actor.authorized_session_id == reference.session_id
        self.calls += 1
        context = self.contexts.get(
            (reference.session_id, reference.conversation_version)
        )
        return context.model_copy(deep=True) if context is not None else None


class ProfileReferences:
    def __init__(self) -> None:
        self.references: set[tuple[str, str, int]] = set()
        self.calls = 0

    def add(
        self,
        *,
        actor: FeedbackActorContext,
        reference: FeedbackProfileVersionRef,
    ) -> None:
        self.references.add(
            (
                actor.owner.scope,
                actor.owner.subject_id,
                reference.profile_version,
            )
        )

    def exists(
        self,
        *,
        actor: FeedbackActorContext,
        reference: FeedbackProfileVersionRef,
    ) -> bool:
        self.calls += 1
        return (
            actor.owner.scope,
            actor.owner.subject_id,
            reference.profile_version,
        ) in self.references


class MemoryEventStore:
    def __init__(self) -> None:
        self.events: dict[tuple[str, str, str], RecordedFeedbackEvent] = {}
        self.insert_count = 0

    @staticmethod
    def _key(
        owner: ProfileOwnerRef,
        idempotency_key: str,
    ) -> tuple[str, str, str]:
        return owner.scope, owner.subject_id, idempotency_key

    def load(
        self,
        *,
        owner: ProfileOwnerRef,
        idempotency_key: str,
    ) -> RecordedFeedbackEvent | None:
        event = self.events.get(self._key(owner, idempotency_key))
        return event.model_copy(deep=True) if event is not None else None

    def record_once(
        self,
        event: RecordedFeedbackEvent,
    ) -> RecordedFeedbackEvent:
        key = self._key(event.owner, event.idempotency_key)
        existing = self.events.get(key)
        if existing is not None:
            if existing.to_request() != event.to_request():
                raise FeedbackIdempotencyConflict(event.idempotency_key)
            return existing.model_copy(deep=True)
        self.events[key] = event.model_copy(deep=True)
        self.insert_count += 1
        return event.model_copy(deep=True)


def _owner(subject_id: str = "profile_0123456789abcdef") -> ProfileOwnerRef:
    return ProfileOwnerRef(
        scope="local_demo",
        subject_id=subject_id,
    )


def _actor(
    owner: ProfileOwnerRef | None = None,
    *,
    session_id: str = "session-feedback-owner",
) -> FeedbackActorContext:
    return FeedbackActorContext(
        owner=owner or _owner(),
        authorized_session_id=session_id,
    )


def _conversation(
    owner: ProfileOwnerRef | None = None,
    *,
    profile: FeedbackProfileVersionRef | None = None,
) -> FeedbackConversationContext:
    return FeedbackConversationContext(
        reference=ConversationVersionRef(
            session_id="session-feedback-owner",
            conversation_version=7,
        ),
        owner=owner or _owner(),
        product_ids=[11, 22, 33, 44],
        profile=profile,
    )


def _request(
    payload: object,
    *,
    key: str = "feedback-idempotency-key-0001",
    version: int = 7,
    profile: FeedbackProfileVersionRef | None = None,
) -> FeedbackEventRequest:
    return FeedbackEventRequest(
        conversation=ConversationVersionRef(
            session_id="session-feedback-owner",
            conversation_version=version,
        ),
        profile=profile,
        idempotency_key=key,
        payload=payload,
    )


def _recorder(
    *,
    context: FeedbackConversationContext | None = None,
    clock: Clock | None = None,
) -> tuple[
    FeedbackEventRecorder,
    MemoryEventStore,
    ConversationReferences,
    ProfileReferences,
    Clock,
]:
    active_clock = clock or Clock()
    conversation_refs = ConversationReferences(context or _conversation())
    profile_refs = ProfileReferences()
    store = MemoryEventStore()
    recorder = FeedbackEventRecorder(
        store=store,
        conversation_references=conversation_refs,
        profile_references=profile_refs,
        clock=active_clock,
        event_id_factory=lambda: "feedback_event_0123456789abcdef",
    )
    return (
        recorder,
        store,
        conversation_refs,
        profile_refs,
        active_clock,
    )


@pytest.mark.parametrize(
    "payload",
    [
        ClickFeedbackPayload(product_id=11),
        FavoriteFeedbackPayload(product_id=11),
        CompareFeedbackPayload(product_ids=[11, 22, 33, 44]),
        NegativeFeedbackPayload(
            product_id=None,
            reason="not_helpful",
        ),
    ],
)
def test_recorder_records_each_typed_event_with_injected_utc_time(
    payload: object,
) -> None:
    recorder, store, _, _, clock = _recorder()

    event = recorder.record(_request(payload), actor=_actor())

    assert event.payload == payload
    assert event.owner == _actor().owner
    assert event.occurred_at == datetime(2026, 8, 9, 4, 30, tzinfo=UTC)
    assert event.occurred_at.tzinfo is UTC
    assert event.event_id == "feedback_event_0123456789abcdef"
    assert store.insert_count == 1
    assert clock.calls == 1


def test_replay_returns_original_without_revalidating_or_retimestamping() -> None:
    recorder, store, conversations, profiles, clock = _recorder()
    request = _request(ClickFeedbackPayload(product_id=11))
    original = recorder.record(request, actor=_actor())
    conversations.contexts.clear()
    profiles.references.clear()
    clock.now = datetime(2030, 1, 1, tzinfo=UTC)

    replayed = recorder.record(
        request.model_copy(deep=True),
        actor=_actor(),
    )

    assert replayed == original
    assert replayed is not original
    assert store.insert_count == 1
    assert conversations.calls == 1
    assert profiles.calls == 0
    assert clock.calls == 1


def test_same_owner_and_key_with_different_payload_fails_closed() -> None:
    recorder, store, _, _, _ = _recorder()
    recorder.record(
        _request(ClickFeedbackPayload(product_id=11)),
        actor=_actor(),
    )

    with pytest.raises(FeedbackIdempotencyConflict):
        recorder.record(
            _request(FavoriteFeedbackPayload(product_id=11)),
            actor=_actor(),
        )

    assert store.insert_count == 1


@pytest.mark.parametrize("version", [6, 8])
def test_stale_or_invalid_conversation_reference_is_rejected(
    version: int,
) -> None:
    recorder, store, _, _, clock = _recorder()

    with pytest.raises(FeedbackReferenceError):
        recorder.record(
            _request(
                ClickFeedbackPayload(product_id=11),
                version=version,
            ),
            actor=_actor(),
        )

    assert store.insert_count == 0
    assert clock.calls == 0


def test_conversation_owned_by_another_subject_is_rejected() -> None:
    context = _conversation(
        _owner("profile_foreign_0123456789abcdef")
    )
    recorder, store, _, _, clock = _recorder(context=context)

    with pytest.raises(FeedbackAuthorizationError):
        recorder.record(
            _request(ClickFeedbackPayload(product_id=11)),
            actor=_actor(),
        )

    assert store.insert_count == 0
    assert clock.calls == 0


@pytest.mark.parametrize(
    "payload",
    [
        ClickFeedbackPayload(product_id=99),
        FavoriteFeedbackPayload(product_id=99),
        CompareFeedbackPayload(product_ids=[11, 99]),
        NegativeFeedbackPayload(
            product_id=99,
            reason="wrong_product",
        ),
    ],
)
def test_foreign_product_references_are_rejected(
    payload: object,
) -> None:
    recorder, store, _, _, clock = _recorder()

    with pytest.raises(ForeignFeedbackProductError):
        recorder.record(_request(payload), actor=_actor())

    assert store.insert_count == 0
    assert clock.calls == 0


def test_optional_profile_reference_must_exist_at_exact_owner_and_version(
) -> None:
    actor = _actor()
    profile = FeedbackProfileVersionRef(profile_version=3)
    recorder, store, _, profiles, _ = _recorder(
        context=_conversation(profile=profile)
    )
    profiles.add(
        actor=actor,
        reference=profile,
    )

    event = recorder.record(
        _request(
            ClickFeedbackPayload(product_id=11),
            profile=profile,
        ),
        actor=actor,
    )

    assert event.profile == profile
    assert profiles.calls == 1
    assert store.insert_count == 1

    stale = profile.model_copy(update={"profile_version": 2})
    with pytest.raises(FeedbackReferenceError):
        recorder.record(
            _request(
                ClickFeedbackPayload(product_id=11),
                key="feedback-idempotency-key-0002",
                profile=stale,
            ),
            actor=actor,
        )
    assert store.insert_count == 1


def test_supplied_profile_must_match_trusted_conversation_target() -> None:
    trusted_profile = FeedbackProfileVersionRef(profile_version=3)
    requested_profile = FeedbackProfileVersionRef(profile_version=4)
    recorder, store, _, profiles, clock = _recorder(
        context=_conversation(profile=trusted_profile)
    )
    profiles.add(
        actor=_actor(),
        reference=requested_profile,
    )

    with pytest.raises(
        FeedbackReferenceError,
        match="target",
    ):
        recorder.record(
            _request(
                ClickFeedbackPayload(product_id=11),
                profile=requested_profile,
            ),
            actor=_actor(),
        )

    assert profiles.calls == 0
    assert store.insert_count == 0
    assert clock.calls == 0


def test_target_profile_remains_optional_in_feedback_request() -> None:
    recorder, store, _, profiles, _ = _recorder(
        context=_conversation(
            profile=FeedbackProfileVersionRef(
                profile_version=3
            )
        )
    )

    event = recorder.record(
        _request(ClickFeedbackPayload(product_id=11)),
        actor=_actor(),
    )

    assert event.profile is None
    assert profiles.calls == 0
    assert store.insert_count == 1


def test_naive_clock_fails_closed_before_store_write() -> None:
    clock = Clock()
    clock.now = datetime(2026, 8, 9, 4, 30)
    recorder, store, _, _, _ = _recorder(clock=clock)

    with pytest.raises(FeedbackClockError):
        recorder.record(
            _request(ClickFeedbackPayload(product_id=11)),
            actor=_actor(),
        )

    assert store.insert_count == 0


def test_request_session_must_match_trusted_actor_session_before_lookup(
) -> None:
    recorder, store, conversations, _, clock = _recorder()

    with pytest.raises(FeedbackAuthorizationError):
        recorder.record(
            _request(ClickFeedbackPayload(product_id=11)),
            actor=_actor(session_id="session-authorized-elsewhere"),
        )

    assert store.insert_count == 0
    assert conversations.calls == 0
    assert clock.calls == 0
