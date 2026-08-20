from __future__ import annotations

import re
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ImageReferenceDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    ordinal: int | None = Field(default=None, ge=1, le=4)
    issue: Literal["ambiguous_image_reference"] | None = None

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if (self.ordinal is None) == (self.issue is None):
            raise ValueError(
                "image reference requires exactly one ordinal or issue"
            )
        return self


_IMAGE_ORDINAL = re.compile(r"第\s*([一二三四])\s*张")
_ORDINALS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
}


def parse_image_reference(message: str) -> ImageReferenceDraft | None:
    ordinals = tuple(
        dict.fromkeys(
            _ORDINALS[match.group(1)]
            for match in _IMAGE_ORDINAL.finditer(message.strip())
        )
    )
    if not ordinals:
        return None
    if len(ordinals) > 1:
        return ImageReferenceDraft(issue="ambiguous_image_reference")
    return ImageReferenceDraft(ordinal=ordinals[0])
