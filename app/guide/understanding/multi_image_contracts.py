from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.guide.understanding.contracts import OpaqueBundleId, OpaqueImageId
from app.guide.understanding.image_contracts import IdentityState


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ImageTaskReference(_Strict):
    image_id: OpaqueImageId
    ordinal: int = Field(ge=1, le=4)
    confirmed_product_id: int | None = None
    identity_state: IdentityState


class MultiImageTaskContext(_Strict):
    mode: Literal["identify", "similar", "suitability", "compare"]
    bundle_id: OpaqueBundleId
    references: list[ImageTaskReference] = Field(
        min_length=1,
        max_length=4,
    )

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        ordinals = [item.ordinal for item in self.references]
        if ordinals != list(range(1, len(ordinals) + 1)):
            raise ValueError("image ordinals must be contiguous")

        image_ids = [item.image_id for item in self.references]
        if len(image_ids) != len(set(image_ids)):
            raise ValueError("image references must be unique")

        for reference in self.references:
            if (
                reference.identity_state is IdentityState.CONFIRMED
                and reference.confirmed_product_id is None
            ):
                raise ValueError(
                    "confirmed identity requires product ID"
                )
            if (
                reference.identity_state is not IdentityState.CONFIRMED
                and reference.confirmed_product_id is not None
            ):
                raise ValueError(
                    "unconfirmed identity forbids product ID"
                )

        if self.mode == "compare" and len(self.references) < 2:
            raise ValueError("compare requires at least two images")
        if self.mode != "compare" and len(self.references) != 1:
            raise ValueError(
                f"{self.mode} requires exactly one image"
            )

        return self
