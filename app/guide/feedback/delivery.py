from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.guide.feedback.contracts import ConversationVersionRef
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


class FeedbackDeliveryTracker:
    """Recognize one complete, non-clarifying response with visible cards."""

    def __init__(self) -> None:
        self._card_display: CardDisplayContract | None = None
        self._conversation_version: int | None = None
        self._blocked = False

    def observe(self, event_name: str, event_data: object) -> None:
        if self._conversation_version is not None:
            self._blocked = True
            return
        if event_name in {"clarify", "error"}:
            self._blocked = True
            return
        if (
            event_name == "message"
            and isinstance(event_data, dict)
            and event_data.get("clarify") is True
        ):
            self._blocked = True
            return
        if event_name == "card_display_contract":
            try:
                contract = CardDisplayContract.model_validate(event_data)
            except (TypeError, ValueError):
                self._blocked = True
                return
            if (
                self._card_display is not None
                or contract.mode == "none"
                or contract.max_cards == 0
            ):
                self._blocked = True
                return
            self._card_display = contract
            return
        if event_name == "end":
            if (
                not isinstance(event_data, dict)
                or not isinstance(
                    event_data.get("conversation_version"),
                    int,
                )
                or isinstance(
                    event_data.get("conversation_version"),
                    bool,
                )
                or event_data["conversation_version"] < 0
            ):
                self._blocked = True
                return
            self._conversation_version = event_data[
                "conversation_version"
            ]

    def completion(self) -> FeedbackCompletion | None:
        if (
            self._blocked
            or self._card_display is None
            or self._conversation_version is None
        ):
            return None
        return FeedbackCompletion(
            conversation_version=self._conversation_version,
            card_display=self._card_display,
        )


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
