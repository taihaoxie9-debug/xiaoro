from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.guide.feedback.contracts import ConversationVersionRef
from app.guide.feedback.contracts import ConversationSnapshot
from app.guide.feedback.event_contracts import (
    FeedbackActorContext,
    FeedbackEventId,
    FeedbackEventRequest,
    FeedbackPayload,
    FeedbackProfileVersionRef,
    IdempotencyKey,
)
from app.guide.feedback.profile_state import ProfileStatePort
from app.guide.feedback.target_contracts import (
    TrustedFeedbackTarget,
    feedback_target_from_completed_response,
)
from app.guide.feedback.target_ports import FeedbackTargetRegistryPort
from app.guide.presentation.contracts import CardDisplayContract


FeedbackEventType = Literal[
    "click",
    "favorite",
    "compare",
    "negative_feedback",
]


class _FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class FeedbackCompletion(_FrozenContract):
    conversation_version: int = Field(ge=0)
    card_display: CardDisplayContract


class FeedbackTargetReceipt(_FrozenContract):
    conversation_version: int = Field(ge=0)
    displayed_product_ids: tuple[int, ...] = Field(
        min_length=1,
        max_length=4,
    )
    profile_version: int | None = Field(default=None, ge=1)


class FeedbackTargetRegistrationRequest(_FrozenContract):
    conversation_version: int = Field(ge=1)


class PreparedFeedbackTarget(_FrozenContract):
    target: TrustedFeedbackTarget
    receipt: FeedbackTargetReceipt


class FeedbackEventSubmission(_FrozenContract):
    conversation_version: int = Field(ge=0)
    profile_version: int | None = Field(default=None, ge=1)
    idempotency_key: IdempotencyKey
    payload: FeedbackPayload


class FeedbackEventReceipt(_FrozenContract):
    event_id: FeedbackEventId
    event_type: FeedbackEventType
    occurred_at: datetime


def feedback_completion_from_snapshot(
    snapshot: ConversationSnapshot,
) -> FeedbackCompletion | None:
    if type(snapshot) is not ConversationSnapshot:
        raise TypeError("snapshot must be an exact ConversationSnapshot")
    card_display = _active_card_display(snapshot)
    if (
        card_display is None
        or card_display.mode == "none"
        or card_display.max_cards == 0
    ):
        return None
    return FeedbackCompletion(
        conversation_version=snapshot.version,
        card_display=card_display,
    )


def _active_card_display(
    snapshot: ConversationSnapshot,
) -> CardDisplayContract | None:
    focus = snapshot.active_focus
    if focus is None:
        return None
    slot = {
        "recommendation": snapshot.recommendation_slot,
        "product": snapshot.product_slot,
        "image": snapshot.image_slot,
        "consultation": snapshot.consultation_slot,
        "knowledge": snapshot.knowledge_slot,
        "reply": None,
    }[focus.slot]
    return slot.card_display if slot is not None else None


class TrustedFeedbackService:
    """Persist trusted targets and record actor-scoped typed events."""

    def __init__(
        self,
        *,
        targets: FeedbackTargetRegistryPort,
        profiles: ProfileStatePort,
        recorder,
    ) -> None:
        self._targets = targets
        self._profiles = profiles
        self._recorder = recorder

    def register_completed(
        self,
        *,
        actor: FeedbackActorContext,
        completion: FeedbackCompletion | None,
    ) -> FeedbackTargetReceipt | None:
        prepared = self.prepare_completed(
            actor=actor,
            completion=completion,
        )
        if prepared is None:
            return None
        return self.persist_prepared(prepared)

    def prepare_completed(
        self,
        *,
        actor: FeedbackActorContext,
        completion: FeedbackCompletion | None,
    ) -> PreparedFeedbackTarget | None:
        if completion is None:
            return None
        profile = self._profiles.load(actor.owner)
        if (
            profile is not None
            and (
                profile.owner != actor.owner
                or not isinstance(profile.version, int)
                or isinstance(profile.version, bool)
                or profile.version < 1
            )
        ):
            raise RuntimeError("profile authority is invalid")
        profile_reference = (
            FeedbackProfileVersionRef(
                profile_version=profile.version
            )
            if profile is not None
            else None
        )
        target = feedback_target_from_completed_response(
            owner=actor.owner,
            conversation=ConversationVersionRef(
                session_id=actor.authorized_session_id,
                conversation_version=completion.conversation_version,
            ),
            card_display=completion.card_display,
            profile=profile_reference,
        )
        if target is None:
            return None
        return PreparedFeedbackTarget(
            target=target,
            receipt=self._receipt_for_target(target),
        )

    def persist_prepared(
        self,
        prepared: PreparedFeedbackTarget,
    ) -> FeedbackTargetReceipt:
        if not isinstance(prepared, PreparedFeedbackTarget):
            raise TypeError(
                "prepared must be a PreparedFeedbackTarget"
            )
        stored = self._targets.record_once(prepared.target)
        receipt = self._receipt_for_target(stored)
        if receipt != prepared.receipt:
            raise RuntimeError(
                "persisted feedback target differs from prepared receipt"
            )
        return receipt

    @staticmethod
    def _receipt_for_target(
        target: TrustedFeedbackTarget,
    ) -> FeedbackTargetReceipt:
        return FeedbackTargetReceipt(
            conversation_version=(
                target.conversation.conversation_version
            ),
            displayed_product_ids=target.displayed_product_ids,
            profile_version=(
                target.profile.profile_version
                if target.profile is not None
                else None
            ),
        )

    def record(
        self,
        submission: FeedbackEventSubmission,
        *,
        actor: FeedbackActorContext,
    ) -> FeedbackEventReceipt:
        profile = (
            FeedbackProfileVersionRef(
                profile_version=submission.profile_version
            )
            if submission.profile_version is not None
            else None
        )
        request = FeedbackEventRequest(
            conversation=ConversationVersionRef(
                session_id=actor.authorized_session_id,
                conversation_version=(
                    submission.conversation_version
                ),
            ),
            profile=profile,
            idempotency_key=submission.idempotency_key,
            payload=submission.payload,
        )
        recorded = self._recorder.record(request, actor=actor)
        return FeedbackEventReceipt(
            event_id=recorded.event_id,
            event_type=recorded.payload.event_type,
            occurred_at=recorded.occurred_at,
        )
