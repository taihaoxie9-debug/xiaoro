from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ProfileOwnerRef(_Strict):
    scope: Literal[
        "authenticated_user",
        "local_demo",
        "anonymous_browser",
    ]
    subject_id: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=16,
            max_length=160,
        ),
    ]


class ConfirmedProfileFact(_Strict):
    owner: ProfileOwnerRef
    field: Literal[
        "skin_type",
        "skin_concern",
        "ingredient_exclusion",
        "preferred_brand",
        "preferred_category",
    ]
    value: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=128,
        ),
    ]
    source_turn_id: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=16,
            max_length=160,
        ),
    ]
    source_kind: Literal[
        "explicit_user",
        "confirmed_consultation",
    ]
    confirmed_at: datetime
    profile_version: int = Field(ge=1)

    @field_validator("confirmed_at")
    @classmethod
    def validate_confirmed_at_utc(cls, value: datetime) -> datetime:
        if value.utcoffset() is None or value.utcoffset() != UTC.utcoffset(
            value
        ):
            raise ValueError("confirmed_at must be UTC")
        return value
