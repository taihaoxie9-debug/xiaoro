from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)


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


ActiveFocusSlot = Literal[
    "recommendation",
    "product",
    "image",
    "consultation",
    "knowledge",
    "reply",
]
ActiveFocusObjectId = int | Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=256,
    ),
]


class ActiveFocus(_StrictFrozen):
    slot: ActiveFocusSlot
    object_id: ActiveFocusObjectId | None = None
    ordinal: int | None = Field(default=None, ge=1, le=4)

    @model_validator(mode="after")
    def validate_focus_shape(self) -> Self:
        if self.slot in {"recommendation", "image"}:
            return self
        if self.ordinal is not None:
            raise ValueError(
                f"{self.slot} focus forbids ordinal"
            )
        return self


__all__ = [
    "ActiveFocus",
    "ConfirmedImageProductRef",
]
