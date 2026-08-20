from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.guide.feedback.contracts import ConversationVersionRef
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.session_contract import SessionId


class _StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


IdempotencyKey = Annotated[
    str,
    StringConstraints(
        min_length=16,
        max_length=160,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
]
FeedbackEventId = Annotated[
    str,
    StringConstraints(
        min_length=24,
        max_length=160,
        pattern=r"^feedback_event_[A-Za-z0-9_-]+$",
    ),
]


class FeedbackProfileVersionRef(_StrictContract):
    profile_version: int = Field(ge=1)


class FeedbackActorContext(_StrictContract):
    """Trusted server-side identity and authorized conversation."""

    owner: ProfileOwnerRef
    authorized_session_id: SessionId


class ClickFeedbackPayload(_StrictContract):
    event_type: Literal["click"] = "click"
    product_id: int = Field(gt=0)


class FavoriteFeedbackPayload(_StrictContract):
    event_type: Literal["favorite"] = "favorite"
    product_id: int = Field(gt=0)


class CompareFeedbackPayload(_StrictContract):
    event_type: Literal["compare"] = "compare"
    product_ids: list[int] = Field(min_length=2, max_length=4)

    @model_validator(mode="after")
    def validate_products(self) -> Self:
        if any(product_id <= 0 for product_id in self.product_ids):
            raise ValueError("compare product IDs must be positive")
        if len(self.product_ids) != len(set(self.product_ids)):
            raise ValueError("compare product IDs must be unique")
        return self


class NegativeFeedbackPayload(_StrictContract):
    event_type: Literal["negative_feedback"] = "negative_feedback"
    product_id: int | None = Field(default=None, gt=0)
    reason: Literal[
        "not_helpful",
        "not_relevant",
        "wrong_product",
        "too_expensive",
        "other",
    ]


FeedbackPayload = Annotated[
    ClickFeedbackPayload
    | FavoriteFeedbackPayload
    | CompareFeedbackPayload
    | NegativeFeedbackPayload,
    Field(discriminator="event_type"),
]


class FeedbackEventRequest(_StrictContract):
    conversation: ConversationVersionRef
    profile: FeedbackProfileVersionRef | None = None
    idempotency_key: IdempotencyKey
    payload: FeedbackPayload


class RecordedFeedbackEvent(FeedbackEventRequest):
    owner: ProfileOwnerRef
    event_id: FeedbackEventId
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def validate_utc_timestamp(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("occurred_at must be a UTC timestamp")
        if value.utcoffset() != timedelta(0):
            raise ValueError("occurred_at must be a UTC timestamp")
        return value

    def to_request(self) -> FeedbackEventRequest:
        return FeedbackEventRequest.model_validate(
            self.model_dump(
                exclude={"owner", "event_id", "occurred_at"}
            )
        )


class FeedbackConversationContext(_StrictContract):
    reference: ConversationVersionRef
    owner: ProfileOwnerRef
    product_ids: list[int] = Field(default_factory=list, max_length=4)
    profile: FeedbackProfileVersionRef | None = None

    @model_validator(mode="after")
    def validate_products(self) -> Self:
        if any(product_id <= 0 for product_id in self.product_ids):
            raise ValueError("conversation product IDs must be positive")
        if len(self.product_ids) != len(set(self.product_ids)):
            raise ValueError("conversation product IDs must be unique")
        return self
