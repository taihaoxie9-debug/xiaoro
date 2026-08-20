from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.guide.feedback.delivery import (
    FeedbackDeliveryTracker,
    FeedbackEventReceipt,
    FeedbackEventSubmission,
    FeedbackTargetReceipt,
    TrustedFeedbackService,
)
from app.guide.feedback.event_contracts import (
    FeedbackActorContext,
    RecordedFeedbackEvent,
)
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.presentation.contracts import CardDisplayContract


_OWNER = ProfileOwnerRef(
    scope="authenticated_user",
    subject_id="authenticated-user-00000042",
)
_ACTOR = FeedbackActorContext(
    owner=_OWNER,
    authorized_session_id="feedback-delivery-session",
)


class _Targets:
    def __init__(self) -> None:
        self.recorded = []

    def record_once(self, target):
        self.recorded.append(target)
        return target


class _Profiles:
    def __init__(self, version: int | None) -> None:
        self.version = version
        self.loaded = []

    def load(self, owner):
        self.loaded.append(owner)
        if self.version is None:
            return None
        return type(
            "ProfileSnapshot",
            (),
            {"owner": owner, "version": self.version},
        )()


class _Recorder:
    def __init__(self) -> None:
        self.calls = []

    def record(self, request, *, actor):
        self.calls.append((request, actor))
        return RecordedFeedbackEvent(
            **request.model_dump(mode="python"),
            owner=actor.owner,
            event_id="feedback_event_0123456789abcdefghijklmn",
            occurred_at=datetime(2026, 8, 9, 5, 30, tzinfo=UTC),
        )


def _card_display() -> CardDisplayContract:
    return CardDisplayContract(
        mode="comparison",
        visible_product_ids=[91, 38],
        max_cards=2,
        reason="comparison",
    )


def test_delivery_tracker_completes_only_nonzero_successful_response() -> None:
    tracker = FeedbackDeliveryTracker()

    tracker.observe(
        "card_display_contract",
        _card_display().model_dump(mode="json"),
    )
    assert tracker.completion() is None

    tracker.observe("end", {"conversation_version": 4})

    completion = tracker.completion()
    assert completion is not None
    assert completion.conversation_version == 4
    assert completion.card_display == _card_display()


@pytest.mark.parametrize(
    "events",
    [
        [
            (
                "card_display_contract",
                {
                    "mode": "none",
                    "visible_product_ids": [],
                    "max_cards": 0,
                    "reason": "knowledge_only",
                },
            ),
            ("end", {"conversation_version": 1}),
        ],
        [
            (
                "card_display_contract",
                _card_display().model_dump(mode="json"),
            ),
            ("message", {"clarify": True, "content": "请补充信息"}),
            ("end", {"conversation_version": 1}),
        ],
        [
            (
                "card_display_contract",
                _card_display().model_dump(mode="json"),
            ),
            ("error", {"error": "GUIDE_INTERNAL_ERROR"}),
        ],
        [
            (
                "card_display_contract",
                _card_display().model_dump(mode="json"),
            ),
        ],
    ],
)
def test_delivery_tracker_rejects_zero_card_clarify_error_and_abort(
    events,
) -> None:
    tracker = FeedbackDeliveryTracker()
    for event_name, event_data in events:
        tracker.observe(event_name, event_data)

    assert tracker.completion() is None


def test_service_prepares_receipt_without_persisting_until_committed() -> None:
    targets = _Targets()
    profiles = _Profiles(version=7)
    service = TrustedFeedbackService(
        targets=targets,
        profiles=profiles,
        recorder=_Recorder(),
    )
    tracker = FeedbackDeliveryTracker()
    tracker.observe(
        "card_display_contract",
        _card_display().model_dump(mode="json"),
    )
    tracker.observe("end", {"conversation_version": 4})

    prepared = service.prepare_completed(
        actor=_ACTOR,
        completion=tracker.completion(),
    )

    assert prepared is not None
    assert targets.recorded == []
    assert prepared.receipt == FeedbackTargetReceipt(
        conversation_version=4,
        displayed_product_ids=(91, 38),
        profile_version=7,
    )

    receipt = service.persist_prepared(prepared)

    assert receipt == FeedbackTargetReceipt(
        conversation_version=4,
        displayed_product_ids=(91, 38),
        profile_version=7,
    )
    assert receipt.model_dump(mode="json") == {
        "conversation_version": 4,
        "displayed_product_ids": [91, 38],
        "profile_version": 7,
    }
    assert "owner" not in receipt.model_dump()
    assert "session_id" not in receipt.model_dump()
    assert profiles.loaded == [_OWNER]
    assert len(targets.recorded) == 1
    assert targets.recorded[0].owner == _OWNER
    assert targets.recorded[0].conversation.session_id == (
        "feedback-delivery-session"
    )
    assert targets.recorded[0].displayed_product_ids == (91, 38)


def test_service_register_completed_remains_compatible() -> None:
    targets = _Targets()
    service = TrustedFeedbackService(
        targets=targets,
        profiles=_Profiles(version=None),
        recorder=_Recorder(),
    )
    tracker = FeedbackDeliveryTracker()
    tracker.observe(
        "card_display_contract",
        _card_display().model_dump(mode="json"),
    )
    tracker.observe("end", {"conversation_version": 4})

    receipt = service.register_completed(
        actor=_ACTOR,
        completion=tracker.completion(),
    )

    assert receipt == FeedbackTargetReceipt(
        conversation_version=4,
        displayed_product_ids=(91, 38),
        profile_version=None,
    )
    assert len(targets.recorded) == 1


def test_service_does_not_persist_without_a_completion() -> None:
    targets = _Targets()
    service = TrustedFeedbackService(
        targets=targets,
        profiles=_Profiles(version=None),
        recorder=_Recorder(),
    )

    assert service.register_completed(
        actor=_ACTOR,
        completion=None,
    ) is None
    assert targets.recorded == []


@pytest.mark.parametrize(
    "authority",
    [
        {"owner": _OWNER.model_dump(mode="json")},
        {"session_id": "attacker-session"},
        {
            "conversation": {
                "session_id": "attacker-session",
                "conversation_version": 4,
            }
        },
    ],
)
def test_public_feedback_submission_rejects_owner_and_session_authority(
    authority,
) -> None:
    with pytest.raises(ValidationError):
        FeedbackEventSubmission.model_validate(
            {
                "conversation_version": 4,
                "profile_version": 7,
                "idempotency_key": "frontend-feedback-key-0001",
                "payload": {
                    "event_type": "favorite",
                    "product_id": 91,
                },
                **authority,
            }
        )


def test_service_builds_actor_scoped_event_and_safe_receipt() -> None:
    recorder = _Recorder()
    service = TrustedFeedbackService(
        targets=_Targets(),
        profiles=_Profiles(version=None),
        recorder=recorder,
    )
    submission = FeedbackEventSubmission(
        conversation_version=4,
        profile_version=7,
        idempotency_key="frontend-feedback-key-0001",
        payload={
            "event_type": "compare",
            "product_ids": [91, 38],
        },
    )

    receipt = service.record(submission, actor=_ACTOR)

    assert receipt == FeedbackEventReceipt(
        event_id="feedback_event_0123456789abcdefghijklmn",
        event_type="compare",
        occurred_at=datetime(2026, 8, 9, 5, 30, tzinfo=UTC),
    )
    assert receipt.model_dump(mode="json") == {
        "event_id": "feedback_event_0123456789abcdefghijklmn",
        "event_type": "compare",
        "occurred_at": "2026-08-09T05:30:00Z",
    }
    request, actor = recorder.calls[0]
    assert actor == _ACTOR
    assert request.conversation.session_id == "feedback-delivery-session"
    assert request.conversation.conversation_version == 4
    assert request.profile.profile_version == 7
    assert request.payload.product_ids == [91, 38]
