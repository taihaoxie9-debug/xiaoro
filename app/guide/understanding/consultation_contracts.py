from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


class _Strict(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )


class ConsultationObservation(_Strict):
    observation_id: str = Field(
        pattern=r"^obs_[a-z0-9_]{1,48}$",
    )
    dimension: Literal[
        "oiliness",
        "dryness",
        "tightness",
        "flaking",
        "redness",
        "stinging",
        "burning",
        "pain",
        "swelling",
        "broken_skin",
        "oozing",
        "product_tolerance",
    ]
    state: Literal[
        "present",
        "absent",
        "sometimes",
        "unknown",
    ]
    location: Literal[
        "t_zone",
        "forehead",
        "nose",
        "cheeks",
        "whole_face",
        "eye_area",
        "lips",
        "unknown",
    ] | None = None
    trigger: Literal[
        "post_cleanse",
        "seasonal",
        "acid",
        "new_product",
        "ordinary_skincare",
        "unknown",
    ] | None = None
    duration: Literal[
        "current",
        "recurrent",
        "persistent",
        "unknown",
    ] | None = None
    severity: Literal[
        "mild",
        "moderate",
        "severe",
        "unknown",
    ] | None = None
    source_text: str = Field(
        min_length=1,
        max_length=256,
    )
    source_turn_id: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=16,
            max_length=160,
        ),
    ]

class ProvisionalConsultationConclusion(_Strict):
    skin_target: Literal[
        "oily_sensitive",
        "oily",
        "dry",
        "combination",
        "sensitive",
        "normal",
    ] | None
    stable_tendencies: tuple[
        Literal[
            "sensitivity",
            "seasonal_redness",
            "acid_triggered_irritation",
            "dehydration",
            "other",
        ],
        ...,
    ] = Field(default_factory=tuple, max_length=5)
    current_conditions: tuple[
        Literal[
            "redness",
            "stinging",
            "flaking",
            "tightness",
            "swelling",
            "broken_skin",
            "oozing",
            "persistent_pain",
        ],
        ...,
    ] = Field(default_factory=tuple, max_length=8)
    confidence: Literal["low", "medium", "high"]
    evidence: tuple[str, ...] = Field(min_length=1, max_length=8)
    uncertainties: tuple[str, ...] = Field(max_length=8)
    escalation: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=240,
        ),
    ]
    confirmed_by_user: bool

    @field_validator(
        "stable_tendencies",
        "current_conditions",
        "evidence",
        "uncertainties",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_conclusion_facts(self) -> Self:
        if len(self.stable_tendencies) != len(
            set(self.stable_tendencies)
        ):
            raise ValueError("stable tendencies must be unique")
        if len(self.current_conditions) != len(
            set(self.current_conditions)
        ):
            raise ValueError("current conditions must be unique")
        return self
