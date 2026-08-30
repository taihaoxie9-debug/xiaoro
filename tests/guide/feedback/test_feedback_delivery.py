from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

import app.guide.feedback.delivery as delivery
from app.guide.feedback.delivery import (
    FeedbackCompletion,
    FeedbackEventReceipt,
    FeedbackEventSubmission,
    FeedbackTargetReceipt,
    feedback_completion_from_snapshot,
    TrustedFeedbackService,
)
from app.guide.feedback.contracts import (
    ConversationSnapshot,
    DisplayedCandidateRef,
    ImageSlotState,
    ProductSlotState,
    RecommendationQueryContext,
    RecommendationSlotState,
)
from app.guide.feedback.event_contracts import (
    FeedbackActorContext,
    RecordedFeedbackEvent,
)
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.feedback.focus_state import (
    ActiveFocus,
    ConfirmedImageProductRef,
)
from app.guide.intent.responsibility_matrix import Responsibility
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


def _completion() -> FeedbackCompletion:
    return FeedbackCompletion(
        conversation_version=4,
        card_display=_card_display(),
    )


def _candidate(
    product_id: int,
    ordinal: int,
) -> DisplayedCandidateRef:
    return DisplayedCandidateRef(
        product_id=product_id,
        ordinal=ordinal,
        skin_match="unknown",
        matched_efficacies=(),
    )


def _mixed_image_product_comparison_snapshot(
    *,
    image_ids: tuple[int, ...],
    product_ids: tuple[int, ...],
) -> ConversationSnapshot:
    card_display = CardDisplayContract(
        mode="comparison",
        visible_product_ids=product_ids,
        max_cards=len(product_ids),
        reason="comparison",
    )
    snapshot = ConversationSnapshot(
        session_id="mixed-image-product-comparison",
        version=3,
        active_owner=Responsibility.COMPARISON,
        active_focus=ActiveFocus(
            slot="image",
            object_id=image_ids[0],
            ordinal=1,
        ),
        product_slot=ProductSlotState(
            products=tuple(
                _candidate(product_id, ordinal)
                for ordinal, product_id in enumerate(
                    product_ids,
                    start=1,
                )
            ),
        ),
        image_slot=ImageSlotState(
            confirmed_products=tuple(
                ConfirmedImageProductRef(
                    image_ordinal=ordinal,
                    product_id=product_id,
                )
                for ordinal, product_id in enumerate(
                    image_ids,
                    start=1,
                )
            ),
            focused_image_ordinal=1,
            card_display=card_display,
        ),
    )
    return snapshot


def _image_identity_snapshot(
    *,
    product_ids: tuple[int, ...],
    terminal_display: CardDisplayContract | None = None,
) -> ConversationSnapshot:
    card_display = (
        terminal_display
        if terminal_display is not None
        else CardDisplayContract(
            mode="recommendation",
            visible_product_ids=product_ids,
            max_cards=len(product_ids),
            reason="recommendation",
        )
    )
    snapshot = ConversationSnapshot(
        session_id="multi-image-identity",
        version=4,
        active_owner=Responsibility.IMAGE_IDENTITY,
        active_focus=ActiveFocus(slot="image"),
        image_slot=ImageSlotState(
            confirmed_products=tuple(
                ConfirmedImageProductRef(
                    image_ordinal=ordinal,
                    product_id=product_id,
                )
                for ordinal, product_id in enumerate(
                    product_ids,
                    start=1,
                )
            ),
            card_display=card_display,
        ),
    )
    return snapshot


def test_feedback_delivery_has_no_event_stream_rederivation_bridge() -> None:
    assert not hasattr(delivery, "FeedbackDeliveryTracker")


def test_feedback_completion_is_derived_from_committed_snapshot() -> None:
    card_display = CardDisplayContract(
        mode="recommendation",
        visible_product_ids=(91, 38),
        max_cards=2,
        reason="recommendation",
    )
    snapshot = ConversationSnapshot(
        session_id="feedback-completion",
        version=3,
        active_owner=Responsibility.RECOMMENDATION,
        active_focus=ActiveFocus(slot="recommendation"),
        recommendation_slot=RecommendationSlotState(
            query_context=RecommendationQueryContext(
                category="serum",
                recommendation_mode="explore",
                recommendation_mode_basis="broad_exploration",
                recommendation_count=2,
            ),
            candidates=(
                DisplayedCandidateRef(
                    product_id=91,
                    ordinal=1,
                    skin_match="unknown",
                    matched_efficacies=(),
                ),
                DisplayedCandidateRef(
                    product_id=38,
                    ordinal=2,
                    skin_match="unknown",
                    matched_efficacies=(),
                ),
            ),
            card_display=card_display,
        ),
    )

    completion = feedback_completion_from_snapshot(snapshot)

    assert completion is not None
    assert completion.conversation_version == 3
    assert completion.card_display == card_display


def test_feedback_completion_uses_full_mixed_comparison_display() -> None:
    snapshot = _mixed_image_product_comparison_snapshot(
        image_ids=(53,),
        product_ids=(53, 55),
    )

    completion = feedback_completion_from_snapshot(snapshot)

    assert completion is not None
    assert completion.card_display == CardDisplayContract(
        mode="comparison",
        visible_product_ids=(53, 55),
        max_cards=2,
        reason="comparison",
    )


def test_feedback_completion_supports_multi_image_identity_display() -> None:
    terminal_display = CardDisplayContract(
        mode="recommendation",
        visible_product_ids=(57, 53),
        max_cards=2,
        reason="recommendation",
    )
    snapshot = _image_identity_snapshot(
        product_ids=(53, 55, 57),
        terminal_display=terminal_display,
    )

    completion = feedback_completion_from_snapshot(snapshot)

    assert completion is not None
    assert completion.card_display == terminal_display


def test_feedback_completion_ignores_dormant_slot_display() -> None:
    dormant_display = CardDisplayContract(
        mode="recommendation",
        visible_product_ids=(91, 38),
        max_cards=2,
        reason="recommendation",
    )
    snapshot = ConversationSnapshot(
        session_id="dormant-display",
        version=5,
        active_owner=Responsibility.IMAGE_IDENTITY,
        active_focus=ActiveFocus(slot="image"),
        recommendation_slot=RecommendationSlotState(
            query_context=RecommendationQueryContext(
                category="serum",
                recommendation_mode="explore",
                recommendation_mode_basis="broad_exploration",
                recommendation_count=2,
            ),
            candidates=(_candidate(91, 1), _candidate(38, 2)),
            card_display=dormant_display,
        ),
        image_slot=ImageSlotState(
            confirmed_products=(
                ConfirmedImageProductRef(
                    image_ordinal=1,
                    product_id=53,
                ),
            ),
        ),
    )

    assert feedback_completion_from_snapshot(snapshot) is None


def test_service_prepares_receipt_without_persisting_until_committed() -> None:
    targets = _Targets()
    profiles = _Profiles(version=7)
    service = TrustedFeedbackService(
        targets=targets,
        profiles=profiles,
        recorder=_Recorder(),
    )

    prepared = service.prepare_completed(
        actor=_ACTOR,
        completion=_completion(),
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

    receipt = service.register_completed(
        actor=_ACTOR,
        completion=_completion(),
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
