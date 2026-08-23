from __future__ import annotations

import json
from typing import ClassVar, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


TurnOperationHint = Literal[
    "recommendation",
    "comparison",
    "suitability",
    "image_identity",
    "image_similarity",
    "knowledge",
    "assessment",
    "followup",
    "clarification",
]
RecommendationMode = Literal["explore", "fit"]
RecommendationModeBasis = Literal[
    "broad_exploration",
    "bounded_exploration",
    "count_requested",
    "similar_alternatives",
    "single_best_request",
    "personal_suitability",
    "profile_match_choice",
    "best_among_candidates",
]
EXPLORE_RECOMMENDATION_BASES: frozenset[
    RecommendationModeBasis
] = frozenset(
    {
        "broad_exploration",
        "bounded_exploration",
        "count_requested",
        "similar_alternatives",
    }
)
FIT_RECOMMENDATION_BASES: frozenset[
    RecommendationModeBasis
] = frozenset(
    {
        "single_best_request",
        "personal_suitability",
        "profile_match_choice",
        "best_among_candidates",
    }
)
TurnContinuityHint = Literal[
    "continue",
    "return_to_focus",
    "new_task",
    "unknown",
]
TurnSubjectScopeHint = Literal["self", "other", "unknown"]
TurnTopicHint = Literal[
    "sunscreen",
    "serum",
    "skincare",
    "base_makeup",
    "color_makeup",
    "cleanser",
    "fragrance",
]
TurnObjectFamilyHint = Literal[
    "product",
    "image",
    "topic",
    "constraint",
    "unknown",
]
TurnPluralityHint = Literal["single", "batch", "unknown"]
TurnObservationCode = Literal[
    "tightness",
    "oiliness",
    "dryness",
    "redness",
    "stinging",
    "burning",
    "pain",
    "flaking",
    "swelling",
    "broken_skin",
    "oozing",
    "product_tolerance",
    "current_budget_unknown",
    "goal_unclear",
    "topic_unclear",
    "reference_unclear",
]
TurnObservationQualifier = Literal[
    "post_cleanse",
    "t_zone",
    "recurrent",
    "basic_skincare",
    "seasonal",
    "ordinary_skincare",
    "acid",
    "new_product",
    "unknown",
    "minimum",
    "maximum",
    "range",
    "candidate",
    "image",
    "current_topic",
]
TurnObservationLocation = Literal[
    "t_zone",
    "forehead",
    "nose",
    "cheeks",
    "whole_face",
    "eye_area",
    "lips",
    "unknown",
]
TurnObservationTrigger = Literal[
    "post_cleanse",
    "seasonal",
    "acid",
    "new_product",
    "ordinary_skincare",
    "unknown",
]
TurnObservationDuration = Literal[
    "current",
    "recurrent",
    "persistent",
    "unknown",
]
TurnObservationSeverity = Literal[
    "mild",
    "moderate",
    "severe",
    "unknown",
]
TurnConsultationBaseSkin = Literal[
    "oily",
    "dry",
    "combination",
    "normal",
    "unknown",
]
TurnConsultationTendency = Literal[
    "sensitivity",
    "seasonal_redness",
    "acid_triggered_irritation",
    "dehydration",
    "other",
]
TurnConsultationCondition = Literal[
    "redness",
    "stinging",
    "flaking",
    "tightness",
    "swelling",
    "broken_skin",
    "oozing",
    "persistent_pain",
]
TurnNextObservationGap = Literal[
    "location",
    "persistence_or_trigger",
    "ordinary_product_tolerance",
    "active_damage_risk",
    "confirmation",
]
TurnPreferencePolarity = Literal["prefer", "avoid"]
TurnPreferenceStrength = Literal["ordinary", "safety", "unknown"]
TurnSafetyLanguage = Literal["ordinary", "safety", "unknown"]
TurnRelativeDirection = Literal["higher", "lower"]
TurnRelativeBaselineHint = Literal[
    "current_item",
    "candidate_ordinal",
    "image_ordinal",
    "current_batch",
    "unknown",
]
TurnConstraintParent = Literal[
    "ingredient_exclusion",
    "efficacy",
    "skin",
]
TurnConstraintChange = Literal["remove", "replace"]
TurnPendingResponseHint = Literal[
    "affirm",
    "reject",
    "correct",
    "supplement",
    "replace_task",
    "unknown",
]


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )


class TurnRecommendationModeBasis(_StrictFrozenModel):
    basis: RecommendationModeBasis
    source_text: str = Field(min_length=1, max_length=160)


class TurnReferenceMention(_StrictFrozenModel):
    raw_text: str = Field(min_length=1, max_length=128)
    object_family_hint: TurnObjectFamilyHint
    ordinal_hint: int | None = Field(default=None, ge=1, le=4)
    plurality_hint: TurnPluralityHint
    batch_size_hint: int | None = Field(default=None, ge=2, le=4)

    @model_validator(mode="after")
    def validate_batch_size(self) -> Self:
        if (
            self.batch_size_hint is not None
            and self.plurality_hint != "batch"
        ):
            raise ValueError(
                "batch_size_hint requires batch plurality"
            )
        return self


class TurnProductMention(_StrictFrozenModel):
    raw_text: str = Field(min_length=1, max_length=160)


class TurnBudgetCandidate(_StrictFrozenModel):
    raw_text: str = Field(min_length=1, max_length=64)
    relation: Literal["maximum", "minimum", "range", "approximate"]
    minimum: str | None = Field(
        default=None,
        pattern=r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$",
    )
    maximum: str | None = Field(
        default=None,
        pattern=r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$",
    )


class TurnObservationCandidate(_StrictFrozenModel):
    observation_id: str | None = Field(
        default=None,
        pattern=r"^obs_[a-z0-9_]{1,48}$",
    )
    code: TurnObservationCode
    present: bool
    qualifier: TurnObservationQualifier | None
    raw_text: str = Field(min_length=1, max_length=128)
    location: TurnObservationLocation | None = None
    trigger: TurnObservationTrigger | None = None
    duration: TurnObservationDuration | None = None
    severity: TurnObservationSeverity | None = None


class TurnConsultationHypothesis(_StrictFrozenModel):
    base_skin_direction: TurnConsultationBaseSkin | None = None
    stable_tendencies: tuple[TurnConsultationTendency, ...] = Field(
        default_factory=tuple,
        max_length=5,
    )
    current_conditions: tuple[TurnConsultationCondition, ...] = Field(
        default_factory=tuple,
        max_length=8,
    )
    supporting_observation_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=16,
    )

    @field_validator(
        "stable_tendencies",
        "current_conditions",
        "supporting_observation_ids",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_hypothesis(self) -> Self:
        if len(self.stable_tendencies) != len(
            set(self.stable_tendencies)
        ):
            raise ValueError("stable tendencies must be unique")
        if len(self.current_conditions) != len(
            set(self.current_conditions)
        ):
            raise ValueError("current conditions must be unique")
        if len(self.supporting_observation_ids) != len(
            set(self.supporting_observation_ids)
        ):
            raise ValueError("supporting observation IDs must be unique")
        has_conclusion = (
            self.base_skin_direction is not None
            or bool(self.stable_tendencies)
            or bool(self.current_conditions)
        )
        if has_conclusion and not self.supporting_observation_ids:
            raise ValueError(
                "consultation hypothesis requires observation support"
            )
        if any(
            not item.startswith("obs_")
            for item in self.supporting_observation_ids
        ):
            raise ValueError("invalid supporting observation ID")
        return self


class TurnPreferenceCandidate(_StrictFrozenModel):
    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    concept_id: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_]{1,63}\.[a-z][a-z0-9_]{1,63}$",
    )
    raw_text: str = Field(min_length=1, max_length=160)
    polarity: TurnPreferencePolarity
    strength: TurnPreferenceStrength

    @model_validator(mode="after")
    def validate_concept_scope(self) -> Self:
        if self.field_key == "ingredient_exclusion":
            if (
                self.concept_id is not None
                or self.polarity != "avoid"
            ):
                raise ValueError(
                    "ingredient exclusion requires a bare avoid target"
                )
            return self
        if (
            self.concept_id is not None
            and not self.concept_id.startswith(f"{self.field_key}.")
        ):
            raise ValueError("concept_id must be field-scoped")
        return self


class TurnConstraintChangeCandidate(_StrictFrozenModel):
    parent_concept: TurnConstraintParent
    requested_change: TurnConstraintChange
    raw_text: str = Field(min_length=1, max_length=160)
    normalized_value: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_]{1,63}$",
    )

    @model_validator(mode="after")
    def validate_parent_change(self) -> Self:
        allowed_values = {
            "efficacy": {
                "hydration",
                "soothing",
                "repair",
                "anti_aging",
                "brightening",
                "oil_control",
                "acne_care",
            },
            "skin": {
                "oily_sensitive",
                "oily",
                "dry",
                "combination",
                "sensitive",
                "normal",
            },
        }
        if self.parent_concept == "ingredient_exclusion":
            if (
                self.requested_change != "remove"
                or self.normalized_value is not None
            ):
                raise ValueError(
                    "ingredient exclusion supports bare remove only"
                )
            return self
        if self.normalized_value not in allowed_values[
            self.parent_concept
        ]:
            raise ValueError(
                "constraint change normalized value is not parent-scoped"
            )
        if (
            self.parent_concept == "skin"
            and self.requested_change != "replace"
        ):
            raise ValueError("skin change supports replace only")
        return self


class TurnRelativeCandidate(_StrictFrozenModel):
    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    concept_id: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_]{1,63}\.[a-z][a-z0-9_]{1,63}$",
    )
    direction: TurnRelativeDirection
    raw_text: str = Field(min_length=1, max_length=160)
    baseline_hint: TurnRelativeBaselineHint

    @model_validator(mode="after")
    def validate_concept_scope(self) -> Self:
        if (
            self.concept_id is not None
            and not self.concept_id.startswith(f"{self.field_key}.")
        ):
            raise ValueError("concept_id must be field-scoped")
        return self


class TurnMeaning(_StrictFrozenModel):
    schema_version: ClassVar[str] = "guide-turn-meaning-v1"

    operation_hint: TurnOperationHint
    recommendation_mode: RecommendationMode | None = None
    recommendation_count: int | None = Field(
        default=None,
        ge=1,
        le=4,
    )
    recommendation_mode_basis: (
        TurnRecommendationModeBasis | None
    ) = None
    topic_hint: TurnTopicHint | None
    continuity_hint: TurnContinuityHint = "unknown"
    subject_scope_hint: TurnSubjectScopeHint = "unknown"
    pending_response_hint: TurnPendingResponseHint = "unknown"
    reference_mentions: tuple[TurnReferenceMention, ...] = Field(
        default_factory=tuple,
        max_length=4,
    )
    product_mentions: tuple[TurnProductMention, ...] = Field(
        default_factory=tuple,
        max_length=4,
    )
    budget_candidates: tuple[TurnBudgetCandidate, ...] = Field(
        default_factory=tuple,
        max_length=4,
    )
    observation_candidates: tuple[TurnObservationCandidate, ...] = Field(
        default_factory=tuple,
        max_length=16,
    )
    preference_candidates: tuple[TurnPreferenceCandidate, ...] = Field(
        default_factory=tuple,
        max_length=12,
    )
    constraint_changes: tuple[TurnConstraintChangeCandidate, ...] = Field(
        default_factory=tuple,
        max_length=4,
    )
    relative_candidates: tuple[TurnRelativeCandidate, ...] = Field(
        default_factory=tuple,
        max_length=4,
    )
    consultation_hypothesis: TurnConsultationHypothesis | None = None
    next_observation_gap: TurnNextObservationGap | None = None
    question_meaning: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
    )
    safety_language: TurnSafetyLanguage

    @field_validator("consultation_hypothesis", mode="before")
    @classmethod
    def normalize_empty_consultation_hypothesis(
        cls,
        value: object,
    ) -> object:
        if (
            isinstance(value, dict)
            and value.get("base_skin_direction") in {None, "unknown"}
            and not value.get("stable_tendencies")
            and not value.get("current_conditions")
            and not value.get("supporting_observation_ids")
        ):
            return None
        return value

    @field_validator(
        "reference_mentions",
        "product_mentions",
        "budget_candidates",
        "observation_candidates",
        "preference_candidates",
        "constraint_changes",
        "relative_candidates",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_unique_atoms(self) -> Self:
        for field_name in (
            "reference_mentions",
            "product_mentions",
            "budget_candidates",
            "observation_candidates",
            "preference_candidates",
            "constraint_changes",
            "relative_candidates",
        ):
            values = getattr(self, field_name)
            keys = {
                json.dumps(
                    item.model_dump(mode="json"),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                for item in values
            }
            if len(keys) != len(values):
                raise ValueError(
                    f"{field_name} must contain unique semantic atoms"
                )
        observation_ids = [
            item.observation_id
            for item in self.observation_candidates
            if item.observation_id is not None
        ]
        if len(observation_ids) != len(set(observation_ids)):
            raise ValueError(
                "observation IDs must be unique"
            )
        if self.consultation_hypothesis is not None:
            current_ids = set(observation_ids)
            support_ids = set(
                self.consultation_hypothesis
                .supporting_observation_ids
            )
            if not support_ids <= current_ids:
                raise ValueError(
                    "consultation hypothesis must reference a "
                    "current observation ID"
                )
        recommendation_operation = self.operation_hint in {
            "recommendation",
            "image_similarity",
        }
        if not recommendation_operation and (
            self.recommendation_mode is not None
            or self.recommendation_count is not None
        ):
            raise ValueError(
                "non-recommendation forbids recommendation outcome"
            )
        if (
            self.recommendation_mode is None
            and (
                self.recommendation_count is not None
                or self.recommendation_mode_basis is not None
            )
        ):
            raise ValueError(
                "recommendation basis/count requires "
                "recommendation mode"
            )
        if (
            self.recommendation_mode is not None
            and self.recommendation_mode_basis is None
        ):
            raise ValueError(
                "recommendation requires recommendation basis"
            )
        if self.recommendation_mode == "fit":
            if self.recommendation_count != 1:
                raise ValueError(
                    "fit recommendation requires one result"
                )
            assert self.recommendation_mode_basis is not None
            if (
                self.recommendation_mode_basis.basis
                not in FIT_RECOMMENDATION_BASES
            ):
                raise ValueError(
                    "recommendation basis must be parent-scoped"
                )
        elif self.recommendation_mode == "explore":
            if self.recommendation_count == 1:
                raise ValueError(
                    "explore recommendation requires multiple results"
                )
            assert self.recommendation_mode_basis is not None
            if (
                self.recommendation_mode_basis.basis
                not in EXPLORE_RECOMMENDATION_BASES
            ):
                raise ValueError(
                    "recommendation basis must be parent-scoped"
                )
        return self


__all__ = [
    "EXPLORE_RECOMMENDATION_BASES",
    "FIT_RECOMMENDATION_BASES",
    "RecommendationMode",
    "RecommendationModeBasis",
    "TurnBudgetCandidate",
    "TurnConsultationHypothesis",
    "TurnConstraintChangeCandidate",
    "TurnContinuityHint",
    "TurnMeaning",
    "TurnNextObservationGap",
    "TurnObjectFamilyHint",
    "TurnObservationCandidate",
    "TurnOperationHint",
    "TurnPreferenceCandidate",
    "TurnProductMention",
    "TurnReferenceMention",
    "TurnRecommendationModeBasis",
    "TurnRelativeCandidate",
    "TurnSafetyLanguage",
    "TurnSubjectScopeHint",
    "TurnTopicHint",
]
