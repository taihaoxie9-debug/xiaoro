from __future__ import annotations

from enum import Enum
from typing import ClassVar, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.guide.understanding.contracts import (
    TopicCode,
    UnderstandingGoal,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


SemanticGoal = UnderstandingGoal
ActiveDialogue = Literal[
    "recommendation",
    "comparison",
    "product_knowledge",
    "general_knowledge",
    "image_identity",
    "consultation",
    "clarification",
    "safety_escalation",
]


class SemanticLaneDisposition(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    SKIPPED_BY_CONTRACT = "skipped_by_contract"


class ConcernCode(str, Enum):
    SKIN = "skin"
    SENSITIVITY = "sensitivity"
    EFFICACY = "efficacy"
    TEXTURE = "texture"
    SUN_PROTECTION = "sun_protection"
    WATER_RESISTANCE = "water_resistance"
    SHADE = "shade"
    FINISH = "finish"
    COVERAGE = "coverage"
    LONGEVITY = "longevity"
    CLEANSING = "cleansing"
    FRAGRANCE = "fragrance"
    SILLAGE = "sillage"
    PRICE = "price"
    BUDGET = "budget"


class ObservationCode(str, Enum):
    TIGHTNESS = "tightness"
    OILINESS = "oiliness"
    REDNESS = "redness"
    STINGING = "stinging"
    FLAKING = "flaking"
    CURRENT_BUDGET_UNKNOWN = "current_budget_unknown"
    GOAL_UNCLEAR = "goal_unclear"
    TOPIC_UNCLEAR = "topic_unclear"
    REFERENCE_UNCLEAR = "reference_unclear"


class ObservationQualifier(str, Enum):
    POST_CLEANSE = "post_cleanse"
    T_ZONE = "t_zone"
    RECURRENT = "recurrent"
    BASIC_SKINCARE = "basic_skincare"
    MINIMUM = "minimum"
    MAXIMUM = "maximum"
    RANGE = "range"
    CANDIDATE = "candidate"
    IMAGE = "image"
    CURRENT_TOPIC = "current_topic"


class ClarificationCode(str, Enum):
    GOAL = "goal"
    TOPIC = "topic"
    REFERENCE = "reference"
    BUDGET = "budget"
    CONCERN = "concern"


class ConfirmedProfileField(str, Enum):
    SKIN_TYPE = "skin_type"
    SKIN_CONCERN = "skin_concern"
    INGREDIENT_EXCLUSION = "ingredient_exclusion"
    PREFERRED_BRAND = "preferred_brand"
    PREFERRED_CATEGORY = "preferred_category"


class ActiveConstraintKind(str, Enum):
    BUDGET = "budget"
    CATEGORY = "category"
    SKIN = "skin"
    INGREDIENT_EXCLUSION = "ingredient_exclusion"
    EFFICACY = "efficacy"


class SemanticPreferenceField(str, Enum):
    TEXTURE = "texture"
    FRAGRANCE_DESCRIPTION = "fragrance_description"
    FINISH = "finish"
    BRAND = "brand"
    EFFICACY = "efficacy"
    SUITABLE_SKIN = "suitable_skin"
    SKIN_CONCERN = "skin_concern"
    USAGE_CONTEXT = "usage_context"
    INGREDIENT_PRESENCE = "ingredient_presence"
    INGREDIENT_EXCLUSION = "ingredient_exclusion"


class SemanticPreferenceStrength(str, Enum):
    PREFERENCE = "preference"
    SAFETY = "safety"
    UNKNOWN = "unknown"


def drop_misplaced_observation_concerns(value: object) -> object:
    """Drop observation enums misplaced in concerns; reject other unknowns."""
    if not isinstance(value, (list, tuple)):
        return value
    filtered: list[object] = []
    for item in value:
        if isinstance(item, ConcernCode):
            filtered.append(item)
            continue
        if isinstance(item, str):
            try:
                filtered.append(ConcernCode(item))
            except ValueError:
                try:
                    ObservationCode(item)
                except ValueError:
                    filtered.append(item)
            continue
        filtered.append(item)
    return tuple(filtered)


def drop_unknown_soft_preference_candidates(value: object) -> object:
    """Drop only unknown soft fields; safety/unknown fields stay strict."""
    if not isinstance(value, (list, tuple)):
        return value
    filtered: list[object] = []
    for item in value:
        if not isinstance(item, dict):
            filtered.append(item)
            continue
        normalized = dict(item)
        raw_strength = normalized.get("strength")
        strength: SemanticPreferenceStrength | object = raw_strength
        if isinstance(raw_strength, str):
            try:
                strength = SemanticPreferenceStrength(raw_strength)
                normalized["strength"] = strength
            except ValueError:
                pass
        raw_field = normalized.get("field")
        if isinstance(raw_field, str):
            try:
                normalized["field"] = SemanticPreferenceField(raw_field)
            except ValueError:
                if strength is SemanticPreferenceStrength.PREFERENCE:
                    continue
        filtered.append(normalized)
    return tuple(filtered)


class SemanticObservation(_StrictModel):
    code: ObservationCode
    present: bool
    qualifier: ObservationQualifier | None = None


class SemanticReference(_StrictModel):
    kind: Literal[
        "candidate_ordinal",
        "image_ordinal",
        "current_item",
        "current_batch",
        "current_topic",
        "previous_constraint",
    ]
    ordinal: int | None = Field(default=None, ge=1, le=4)
    raw_text: str = Field(min_length=1, max_length=64)
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_kind_and_ordinal(self) -> Self:
        if self.end <= self.start:
            raise ValueError("reference end must exceed start")
        if self.kind in {"candidate_ordinal", "image_ordinal"}:
            if self.ordinal is None:
                raise ValueError(f"{self.kind} requires ordinal")
        elif self.ordinal is not None:
            raise ValueError(f"{self.kind} forbids ordinal")
        return self


class SemanticProductMention(_StrictModel):
    text: str = Field(min_length=1, max_length=160)
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_span(self) -> Self:
        if self.end <= self.start:
            raise ValueError("product mention end must exceed start")
        return self


class SemanticPreferenceCandidate(_StrictModel):
    field: SemanticPreferenceField
    raw_text: str = Field(min_length=1, max_length=128)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    strength: SemanticPreferenceStrength

    @model_validator(mode="after")
    def validate_span(self) -> Self:
        if self.end <= self.start:
            raise ValueError("preference candidate end must exceed start")
        return self


class SemanticNumberCandidate(_StrictModel):
    kind: Literal["budget"] = "budget"
    relation: Literal[
        "maximum",
        "minimum",
        "range",
        "approximate",
    ]
    raw_text: str = Field(min_length=1, max_length=64)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    minimum: str | None = Field(default=None, max_length=32)
    maximum: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def validate_candidate_shape(self) -> Self:
        if self.end <= self.start:
            raise ValueError("number candidate end must exceed start")
        actual_bounds = (
            self.minimum is not None,
            self.maximum is not None,
        )
        if not any(actual_bounds):
            # The model may nominate only the exact source span for ambiguous
            # wording. Code still owns all numeric validation and will either
            # accept an exact-lane result or request typed clarification.
            return self
        if self.relation == "approximate":
            return self
        expected_bounds = {
            "maximum": (False, True),
            "minimum": (True, False),
            "range": (True, True),
        }[self.relation]
        if actual_bounds != expected_bounds:
            raise ValueError(
                "number candidate bounds must match relation"
            )
        return self


class SemanticIntentProposal(_StrictModel):
    schema_version: ClassVar[str] = "guide-semantic-intent-v7"
    goal: SemanticGoal
    topic: TopicCode | None
    concerns: tuple[ConcernCode, ...] = Field(max_length=16)
    observations: tuple[SemanticObservation, ...] = Field(max_length=16)
    references: tuple[SemanticReference, ...] = Field(max_length=4)
    product_mentions: tuple[SemanticProductMention, ...] = Field(
        default_factory=tuple,
        max_length=4,
    )
    number_candidates: tuple[SemanticNumberCandidate, ...] = Field(
        default_factory=tuple,
        max_length=4,
    )
    preference_candidates: tuple[
        SemanticPreferenceCandidate,
        ...,
    ] = Field(default_factory=tuple, max_length=8)
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    clarification_hint: ClarificationCode | None = None
    question_meaning: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
    )
    safety_sensitive: bool = False

    @field_validator("concerns", mode="before")
    @classmethod
    def drop_misplaced_observation_concern(cls, value: object) -> object:
        return drop_misplaced_observation_concerns(value)

    @field_validator("preference_candidates", mode="before")
    @classmethod
    def drop_unknown_soft_preference_candidate_fields(
        cls,
        value: object,
    ) -> object:
        return drop_unknown_soft_preference_candidates(value)


class SemanticContext(_StrictModel):
    conversation_version: int = Field(ge=0)
    active_topic: TopicCode | None
    active_dialogue: ActiveDialogue | None = None
    awaiting_reply: bool = False
    visible_candidate_count: int = Field(ge=0, le=4)
    focused_candidate_ordinal: int | None = Field(
        default=None,
        ge=1,
        le=4,
    )
    image_count: int = Field(default=0, ge=0, le=4)
    focused_image_ordinal: int | None = Field(
        default=None,
        ge=1,
        le=4,
    )
    active_constraint_kinds: tuple[
        ActiveConstraintKind,
        ...,
    ] = Field(default_factory=tuple, max_length=5)
    confirmed_profile_fields: tuple[
        ConfirmedProfileField,
        ...,
    ] = Field(max_length=5)
    pending_clarification: ClarificationCode | None = None

    @model_validator(mode="after")
    def validate_typed_context(self) -> Self:
        if (
            self.focused_candidate_ordinal is not None
            and self.focused_candidate_ordinal
            > self.visible_candidate_count
        ):
            raise ValueError(
                "focused candidate ordinal must reference a visible candidate"
            )
        if (
            self.focused_image_ordinal is not None
            and self.focused_image_ordinal > self.image_count
        ):
            raise ValueError(
                "focused image ordinal must reference a current image"
            )
        if len(self.active_constraint_kinds) != len(
            set(self.active_constraint_kinds)
        ):
            raise ValueError("active constraint kinds must be unique")
        if len(self.confirmed_profile_fields) != len(
            set(self.confirmed_profile_fields)
        ):
            raise ValueError("confirmed profile fields must be unique")
        return self
