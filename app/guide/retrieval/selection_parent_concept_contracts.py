from __future__ import annotations

from hashlib import sha256
import json
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.guide.retrieval.category_fact_contracts import (
    category_field_registry,
)
from app.guide.retrieval.category_profiles import CategoryProfile


ConceptStance = Literal["supports", "opposes", "not_comparable"]
ConceptComparability = Literal["binary", "ordered", "numeric", "none"]
ConceptReviewDecision = Literal["map", "leave_free"]


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )


class SelectionConceptCandidate(_StrictFrozenModel):
    candidate_id: str = Field(pattern=r"^sc_[0-9a-f]{64}$")
    profile: CategoryProfile
    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    normalized_value: str = Field(min_length=1, max_length=512)
    product_ids: tuple[int, ...] = Field(min_length=1)
    rank_strengths: tuple[Literal[1, 2], ...] = Field(min_length=1)
    source_refs: tuple[str, ...] = Field(min_length=1)

    @field_validator("profile", mode="before")
    @classmethod
    def parse_profile(cls, value: object) -> object:
        if isinstance(value, str):
            try:
                return CategoryProfile(value)
            except ValueError:
                return value
        return value

    @field_validator(
        "product_ids",
        "rank_strengths",
        "source_refs",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_candidate(self) -> Self:
        if self.product_ids != tuple(sorted(set(self.product_ids))):
            raise ValueError("product_ids must be sorted and unique")
        if any(product_id <= 0 for product_id in self.product_ids):
            raise ValueError("product_ids must be positive")
        if self.rank_strengths != tuple(
            sorted(set(self.rank_strengths))
        ):
            raise ValueError("rank_strengths must be sorted and unique")
        if self.source_refs != tuple(sorted(set(self.source_refs))):
            raise ValueError("source_refs must be sorted and unique")
        if self.normalized_value != self.normalized_value.strip():
            raise ValueError("normalized_value must be trimmed")
        definitions = {
            definition.key: definition
            for definition in category_field_registry().definitions
        }
        definition = definitions.get(self.field_key)
        if (
            definition is None
            or self.profile not in definition.profiles
        ):
            raise ValueError("field_key is not valid for profile")
        expected = candidate_id_for(
            profile=self.profile.value,
            field_key=self.field_key,
            normalized_value=self.normalized_value,
            product_ids=self.product_ids,
            rank_strengths=self.rank_strengths,
            source_refs=self.source_refs,
        )
        if self.candidate_id != expected:
            raise ValueError("candidate_id does not match source inventory")
        return self


class SelectionConceptReview(SelectionConceptCandidate):
    decision: ConceptReviewDecision
    concept_id: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_]{1,63}\.[a-z][a-z0-9_]{1,63}$",
    )
    stance: ConceptStance
    comparability: ConceptComparability
    order_value: int | None = Field(default=None, ge=0, le=100)
    rationale: str = Field(min_length=8, max_length=512)

    @model_validator(mode="after")
    def validate_review(self) -> Self:
        if self.decision == "leave_free":
            if (
                self.concept_id is not None
                or self.stance != "not_comparable"
                or self.comparability != "none"
                or self.order_value is not None
            ):
                raise ValueError(
                    "leave_free review cannot publish concept semantics"
                )
            return self
        if self.concept_id is None:
            raise ValueError("mapped review requires concept_id")
        if not self.concept_id.startswith(f"{self.field_key}."):
            raise ValueError("concept_id must be field-scoped")
        if self.stance == "not_comparable":
            raise ValueError("mapped review requires supports or opposes")
        if self.comparability == "none":
            raise ValueError("mapped review requires comparability")
        if (
            self.comparability == "ordered"
            and self.order_value is None
        ):
            raise ValueError("ordered review requires order_value")
        if (
            self.comparability != "ordered"
            and self.order_value is not None
        ):
            raise ValueError(
                "order_value is allowed only for ordered review"
            )
        return self


class SelectionConceptProjection(SelectionConceptCandidate):
    concept_id: str = Field(
        pattern=r"^[a-z][a-z0-9_]{1,63}\.[a-z][a-z0-9_]{1,63}$"
    )
    stance: Literal["supports", "opposes"]
    comparability: Literal["binary", "ordered", "numeric"]
    order_value: int | None = Field(default=None, ge=0, le=100)
    rationale: str = Field(min_length=8, max_length=512)

    @model_validator(mode="after")
    def validate_projection(self) -> Self:
        if not self.concept_id.startswith(f"{self.field_key}."):
            raise ValueError("concept_id must be field-scoped")
        if (
            self.comparability == "ordered"
            and self.order_value is None
        ):
            raise ValueError("ordered projection requires order_value")
        if (
            self.comparability != "ordered"
            and self.order_value is not None
        ):
            raise ValueError(
                "order_value is allowed only for ordered projection"
            )
        return self

    @classmethod
    def from_review(
        cls,
        review: SelectionConceptReview,
    ) -> SelectionConceptProjection:
        if not isinstance(review, SelectionConceptReview):
            raise TypeError("review must be SelectionConceptReview")
        if review.decision != "map" or review.concept_id is None:
            raise ValueError("projection requires a mapped review")
        if review.stance == "not_comparable":
            raise ValueError("projection requires comparable stance")
        if review.comparability == "none":
            raise ValueError("projection requires comparability")
        return cls(
            candidate_id=review.candidate_id,
            profile=review.profile,
            field_key=review.field_key,
            normalized_value=review.normalized_value,
            product_ids=review.product_ids,
            rank_strengths=review.rank_strengths,
            source_refs=review.source_refs,
            concept_id=review.concept_id,
            stance=review.stance,
            comparability=review.comparability,
            order_value=review.order_value,
            rationale=review.rationale,
        )


class SelectionConceptFact(_StrictFrozenModel):
    product_id: int = Field(gt=0)
    profile: CategoryProfile
    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    concept_id: str = Field(
        pattern=r"^[a-z][a-z0-9_]{1,63}\.[a-z][a-z0-9_]{1,63}$"
    )
    stance: Literal["supports", "opposes"]
    comparability: Literal["binary", "ordered", "numeric"]
    order_value: int | None = Field(default=None, ge=0, le=100)
    rank_strength: Literal[1, 2]
    safety_roles: frozenset[
        Literal[
            "ordinary",
            "merchant_positive_safety",
            "verified_warning",
        ]
    ] = Field(min_length=1)
    source_values: tuple[str, ...] = Field(min_length=1)
    source_refs: tuple[str, ...] = Field(min_length=1)
    attributions: frozenset[
        Literal[
            "verified_fact",
            "merchant_claim",
            "consumer_report",
        ]
    ] = Field(min_length=1)

    @field_validator(
        "safety_roles",
        "attributions",
        mode="before",
    )
    @classmethod
    def freeze_sets(cls, value: object) -> object:
        if isinstance(value, (list, tuple, set)):
            return frozenset(value)
        return value

    @field_validator(
        "source_values",
        "source_refs",
        mode="before",
    )
    @classmethod
    def freeze_fact_sequences(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_concept_fact(self) -> Self:
        if not self.concept_id.startswith(f"{self.field_key}."):
            raise ValueError("concept_id must be field-scoped")
        if self.source_values != tuple(
            sorted(set(self.source_values), key=str.casefold)
        ):
            raise ValueError(
                "source_values must be sorted and unique"
            )
        if self.source_refs != tuple(sorted(set(self.source_refs))):
            raise ValueError("source_refs must be sorted and unique")
        if (
            self.comparability == "ordered"
            and self.order_value is None
        ):
            raise ValueError("ordered concept fact requires order_value")
        if (
            self.comparability != "ordered"
            and self.order_value is not None
        ):
            raise ValueError(
                "order_value is allowed only for ordered concept fact"
            )
        return self


def candidate_id_for(
    *,
    profile: str,
    field_key: str,
    normalized_value: str,
    product_ids: tuple[int, ...],
    rank_strengths: tuple[int, ...],
    source_refs: tuple[str, ...],
) -> str:
    payload = {
        "profile": profile,
        "field_key": field_key,
        "normalized_value": normalized_value,
        "product_ids": list(product_ids),
        "rank_strengths": list(rank_strengths),
        "source_refs": list(source_refs),
    }
    digest = sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return f"sc_{digest}"


__all__ = [
    "ConceptComparability",
    "ConceptReviewDecision",
    "ConceptStance",
    "SelectionConceptCandidate",
    "SelectionConceptFact",
    "SelectionConceptProjection",
    "SelectionConceptReview",
    "candidate_id_for",
]
