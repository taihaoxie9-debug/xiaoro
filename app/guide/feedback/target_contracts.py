from __future__ import annotations

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from app.guide.feedback.contracts import ConversationVersionRef
from app.guide.feedback.event_contracts import (
    FeedbackProfileVersionRef,
)
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.presentation.contracts import CardDisplayContract


class _TargetConversationVersionRef(ConversationVersionRef):
    """Frozen target-local snapshot of a conversation authority."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ConversationVersionRef):
            return (
                self.session_id,
                self.conversation_version,
            ) == (
                other.session_id,
                other.conversation_version,
            )
        return super().__eq__(other)


class _TargetProfileVersionRef(FeedbackProfileVersionRef):
    """Frozen target-local snapshot of a profile authority."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    def __eq__(self, other: object) -> bool:
        if isinstance(other, FeedbackProfileVersionRef):
            return self.profile_version == other.profile_version
        return super().__eq__(other)


class TrustedFeedbackTarget(BaseModel):
    """Server-authoritative feedback scope for one completed response."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    owner: ProfileOwnerRef
    conversation: ConversationVersionRef
    displayed_product_ids: tuple[int, ...] = Field(
        min_length=1,
        max_length=4,
    )
    profile: FeedbackProfileVersionRef | None = None

    @field_validator("owner", mode="before")
    @classmethod
    def snapshot_owner(cls, value: object) -> object:
        if isinstance(value, ProfileOwnerRef):
            return value.model_dump(mode="python")
        return value

    @field_validator("conversation", mode="before")
    @classmethod
    def freeze_conversation(
        cls,
        value: object,
    ) -> _TargetConversationVersionRef:
        if isinstance(value, ConversationVersionRef):
            value = value.model_dump(mode="python")
        return _TargetConversationVersionRef.model_validate(value)

    @field_validator("displayed_product_ids", mode="before")
    @classmethod
    def freeze_product_ids(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @field_validator("profile", mode="before")
    @classmethod
    def freeze_profile(
        cls,
        value: object,
    ) -> _TargetProfileVersionRef | None:
        if value is None:
            return None
        if isinstance(value, FeedbackProfileVersionRef):
            value = value.model_dump(mode="python")
        return _TargetProfileVersionRef.model_validate(value)

    @field_validator("displayed_product_ids")
    @classmethod
    def validate_product_ids(
        cls,
        value: tuple[int, ...],
    ) -> tuple[int, ...]:
        if any(product_id <= 0 for product_id in value):
            raise ValueError("displayed product IDs must be positive")
        if len(value) != len(set(value)):
            raise ValueError("displayed product IDs must be unique")
        return value


def feedback_target_from_completed_response(
    *,
    owner: ProfileOwnerRef,
    conversation: ConversationVersionRef,
    card_display: CardDisplayContract,
    profile: FeedbackProfileVersionRef | None = None,
) -> TrustedFeedbackTarget | None:
    """Map a successful validated response to durable feedback authority."""

    if not isinstance(owner, ProfileOwnerRef):
        raise TypeError("owner must be a ProfileOwnerRef")
    if not isinstance(conversation, ConversationVersionRef):
        raise TypeError(
            "conversation must be a ConversationVersionRef"
        )
    if not isinstance(card_display, CardDisplayContract):
        raise TypeError(
            "card_display must be a CardDisplayContract"
        )
    if (
        profile is not None
        and not isinstance(profile, FeedbackProfileVersionRef)
    ):
        raise TypeError(
            "profile must be a FeedbackProfileVersionRef"
        )
    validated_card_display = CardDisplayContract.model_validate(
        card_display.model_dump(mode="python")
    )
    if validated_card_display.mode == "none":
        return None
    return TrustedFeedbackTarget(
        owner=owner,
        conversation=conversation,
        displayed_product_ids=tuple(
            validated_card_display.visible_product_ids
        ),
        profile=profile,
    )
