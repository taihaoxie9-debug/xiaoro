from __future__ import annotations

from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


ProcessorKind = Literal[
    "recommendation",
    "comparison",
    "product_knowledge",
    "general_knowledge",
    "image_identity",
    "consultation",
    "clarification",
    "safety_escalation",
]


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ConfirmedImageProductRef(_StrictFrozen):
    image_ordinal: int = Field(ge=1, le=4)
    product_id: int = Field(gt=0)
    variant_scope: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
    )


class FocusState(_StrictFrozen):
    active_processor: ProcessorKind | None = None
    current_product_id: int | None = Field(default=None, gt=0)
    confirmed_image_products: tuple[
        ConfirmedImageProductRef,
        ...,
    ] = Field(default_factory=tuple, max_length=3)
    current_knowledge_topic: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
    )
    last_question_meaning: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
    )

    @field_validator("confirmed_image_products", mode="before")
    @classmethod
    def freeze_confirmed_images(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_confirmed_images(self) -> Self:
        ordinals = [
            item.image_ordinal
            for item in self.confirmed_image_products
        ]
        if len(ordinals) != len(set(ordinals)):
            raise ValueError(
                "confirmed image ordinal must be unique"
            )
        return self


__all__ = [
    "ConfirmedImageProductRef",
    "FocusState",
    "ProcessorKind",
]
