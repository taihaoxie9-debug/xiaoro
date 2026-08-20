from __future__ import annotations

from typing import ClassVar, Self, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.guide.understanding.semantic_contracts import (
    ConcernCode,
    SemanticNumberCandidate,
    SemanticObservation,
    SemanticPreferenceCandidate,
    SemanticProductMention,
    SemanticReference,
    drop_misplaced_observation_concerns,
    drop_unknown_soft_preference_candidates,
)


class _DetailModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    question_meaning: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
    )
    safety_sensitive: bool = False

    @field_validator("concerns", mode="before", check_fields=False)
    @classmethod
    def drop_misplaced_observation_concern(cls, value: object) -> object:
        return drop_misplaced_observation_concerns(value)

    @field_validator(
        "preference_candidates",
        mode="before",
        check_fields=False,
    )
    @classmethod
    def drop_unknown_soft_preference_candidate_fields(
        cls,
        value: object,
    ) -> object:
        return drop_unknown_soft_preference_candidates(value)

    @model_validator(mode="after")
    def validate_unique_values(self) -> Self:
        for field_name in (
            "concerns",
            "observations",
            "references",
            "product_mentions",
            "number_candidates",
            "preference_candidates",
        ):
            values = getattr(self, field_name, ())
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} must contain unique values")
        return self


class RecommendationDetails(_DetailModel):
    schema_version: ClassVar[str] = "guide-detail-recommendation-v5"
    concerns: tuple[ConcernCode, ...] = Field(
        default_factory=tuple,
        max_length=16,
    )
    observations: tuple[SemanticObservation, ...] = Field(
        default_factory=tuple,
        max_length=16,
    )
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


class AssessmentDetails(_DetailModel):
    schema_version: ClassVar[str] = "guide-detail-assessment-v3"
    concerns: tuple[ConcernCode, ...] = Field(
        default_factory=tuple,
        max_length=16,
    )
    observations: tuple[SemanticObservation, ...] = Field(
        default_factory=tuple,
        max_length=16,
    )
    product_mentions: tuple[SemanticProductMention, ...] = Field(
        default_factory=tuple,
        max_length=4,
    )


class ComparisonDetails(_DetailModel):
    schema_version: ClassVar[str] = "guide-detail-comparison-v3"
    references: tuple[SemanticReference, ...] = Field(
        default_factory=tuple,
        max_length=4,
    )
    product_mentions: tuple[SemanticProductMention, ...] = Field(
        default_factory=tuple,
        max_length=4,
    )


class FollowupDetails(_DetailModel):
    schema_version: ClassVar[str] = "guide-detail-followup-v6"
    references: tuple[SemanticReference, ...] = Field(
        default_factory=tuple,
        max_length=4,
    )
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


class KnowledgeDetails(_DetailModel):
    schema_version: ClassVar[str] = "guide-detail-knowledge-v3"
    concerns: tuple[ConcernCode, ...] = Field(
        default_factory=tuple,
        max_length=16,
    )
    product_mentions: tuple[SemanticProductMention, ...] = Field(
        default_factory=tuple,
        max_length=4,
    )


class ImageDetails(_DetailModel):
    schema_version: ClassVar[str] = "guide-detail-image-v1"
    references: tuple[SemanticReference, ...] = Field(
        min_length=1,
        max_length=4,
    )
    observations: tuple[SemanticObservation, ...] = Field(
        default_factory=tuple,
        max_length=16,
    )


SemanticDetailsProposal: TypeAlias = (
    RecommendationDetails
    | AssessmentDetails
    | ComparisonDetails
    | FollowupDetails
    | KnowledgeDetails
    | ImageDetails
)


__all__ = [
    "AssessmentDetails",
    "ComparisonDetails",
    "FollowupDetails",
    "ImageDetails",
    "KnowledgeDetails",
    "RecommendationDetails",
    "SemanticDetailsProposal",
]
