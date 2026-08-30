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
    source_bundle_id: Annotated[
        str,
        StringConstraints(
            min_length=39,
            max_length=160,
            pattern=r"^bundle_[A-Za-z0-9_-]{32,152}$",
        ),
    ] | None = None
    source_image_id: Annotated[
        str,
        StringConstraints(
            min_length=38,
            max_length=159,
            pattern=r"^image_[A-Za-z0-9_-]{32,152}$",
        ),
    ] | None = None

    @model_validator(mode="after")
    def validate_source_identity(self) -> Self:
        if (self.source_bundle_id is None) != (
            self.source_image_id is None
        ):
            raise ValueError(
                "confirmed image source identity must be complete"
            )
        return self


def validate_confirmed_image_batch(
    confirmed_products: tuple[ConfirmedImageProductRef, ...],
) -> None:
    if (
        type(confirmed_products) is not tuple
        or any(
            type(item) is not ConfirmedImageProductRef
            for item in confirmed_products
        )
        or not 1 <= len(confirmed_products) <= 4
    ):
        raise ValueError(
            "confirmed image batch requires one to four products"
        )
    ordinals = tuple(
        item.image_ordinal for item in confirmed_products
    )
    if (
        ordinals != tuple(range(1, len(confirmed_products) + 1))
    ):
        raise ValueError(
            "confirmed image batch ordinals must be contiguous and ordered"
        )
    source_identities = tuple(
        (item.source_bundle_id, item.source_image_id)
        for item in confirmed_products
    )
    complete = tuple(
        (bundle_id, image_id)
        for bundle_id, image_id in source_identities
        if bundle_id is not None and image_id is not None
    )
    if complete and len(complete) != len(source_identities):
        raise ValueError(
            "confirmed image source identity must be complete"
        )
    if complete and (
        len({bundle_id for bundle_id, _ in complete}) != 1
        or len({image_id for _, image_id in complete}) != len(complete)
    ):
        raise ValueError(
            "confirmed image source identities must name one unique batch"
        )
    if not complete and (
        len({item.product_id for item in confirmed_products})
        != len(confirmed_products)
    ):
        raise ValueError(
            "confirmed image products without source identities must be unique"
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
    "validate_confirmed_image_batch",
]
