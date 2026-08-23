from collections.abc import Mapping
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from app.guide.understanding.contracts import (
    EfficacyTarget,
    FollowupAction,
    ProductMentionDraft,
    ReferenceDraft,
    SkinTarget,
    TopicCode,
)
from app.guide.understanding.semantic_contracts import ClarificationCode
from app.guide.understanding.turn_meaning_contracts import (
    EXPLORE_RECOMMENDATION_BASES,
    FIT_RECOMMENDATION_BASES,
    RecommendationMode,
    RecommendationModeBasis,
)


class _StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class BudgetConstraint(_StrictContract):
    kind: Literal["budget"] = "budget"
    minimum: Decimal | None = None
    maximum: Decimal | None = None

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.minimum is None and self.maximum is None:
            raise ValueError("budget requires minimum or maximum")
        if self.minimum is not None and self.minimum <= 0:
            raise ValueError("budget minimum must be positive")
        if self.maximum is not None and self.maximum <= 0:
            raise ValueError("budget maximum must be positive")
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError("budget minimum must not exceed maximum")
        return self


class CategoryConstraint(_StrictContract):
    kind: Literal["category"] = "category"
    value: TopicCode


class SkinConstraint(_StrictContract):
    kind: Literal["skin"] = "skin"
    value: SkinTarget


class ExclusionConstraint(_StrictContract):
    kind: Literal["exclude"] = "exclude"
    value: str = Field(min_length=1, max_length=64)


class InclusionConstraint(_StrictContract):
    kind: Literal["include"] = "include"
    field_key: Literal[
        "ingredients_present"
    ] = "ingredients_present"
    value: str = Field(min_length=1, max_length=128)


class EfficacyConstraint(_StrictContract):
    kind: Literal["efficacy"] = "efficacy"
    value: EfficacyTarget


class FacetConstraint(_StrictContract):
    kind: Literal["facet"] = "facet"
    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    value: str = Field(min_length=1, max_length=128)


class ConceptConstraint(_StrictContract):
    kind: Literal["concept"] = "concept"
    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    concept_id: str = Field(
        pattern=r"^[a-z][a-z0-9_]{1,63}\.[a-z][a-z0-9_]{1,63}$"
    )
    polarity: Literal["prefer", "avoid"]

    @model_validator(mode="after")
    def validate_field_scope(self) -> Self:
        if not self.concept_id.startswith(f"{self.field_key}."):
            raise ValueError("concept constraint must be field-scoped")
        return self


class FreeDescriptor(_StrictContract):
    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    value: str = Field(min_length=1, max_length=128)
    polarity: Literal["prefer", "avoid"]


class RelativeRequirement(_StrictContract):
    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    concept_id: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_]{1,63}\.[a-z][a-z0-9_]{1,63}$",
    )
    direction: Literal["higher", "lower"]
    baseline: ReferenceDraft

    @model_validator(mode="after")
    def validate_relative_requirement(self) -> Self:
        if (
            self.concept_id is not None
            and not self.concept_id.startswith(f"{self.field_key}.")
        ):
            raise ValueError(
                "relative requirement must be field-scoped"
            )
        if self.baseline.kind not in {
            "candidate_ordinal",
            "image_ordinal",
            "current_item",
        }:
            raise ValueError(
                "relative requirement needs one bound baseline"
            )
        return self


TaskConstraint = Annotated[
    BudgetConstraint
    | CategoryConstraint
    | SkinConstraint
    | ExclusionConstraint
    | InclusionConstraint
    | EfficacyConstraint
    | FacetConstraint
    | ConceptConstraint,
    Field(discriminator="kind"),
]


class TaskPlan(_StrictContract):
    mode: Literal[
        "recommend",
        "comparison",
        "suitability",
        "knowledge",
        "followup",
        "clarify",
    ]
    recommendation_mode: RecommendationMode | None = None
    recommendation_mode_basis: RecommendationModeBasis | None = None
    recommendation_count: int | None = Field(
        default=None,
        ge=1,
        le=4,
    )
    referenced_image_ids: list[str]
    constraints: list[TaskConstraint]
    references: list[ReferenceDraft] = Field(default_factory=list)
    product_mentions: list[ProductMentionDraft] = Field(
        default_factory=list,
        max_length=4,
    )
    product_ids: list[int] = Field(default_factory=list, max_length=4)
    similarity_anchor_product_id: int | None = Field(
        default=None,
        gt=0,
    )
    required_evidence: list[Literal["canonical_product"]]
    free_descriptors: list[FreeDescriptor] = Field(
        default_factory=list,
        max_length=8,
    )
    relative_requirements: list[RelativeRequirement] = Field(
        default_factory=list,
        max_length=4,
    )
    requested_comparison_dimensions: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=12,
    )
    question_meaning: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
    )
    safety_sensitive: bool = False
    clarification: str | None = None
    clarification_code: ClarificationCode | None = None

    @field_validator(
        "requested_comparison_dimensions",
        mode="before",
    )
    @classmethod
    def freeze_requested_comparison_dimensions(
        cls,
        value: object,
    ) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="before")
    @classmethod
    def default_code_owned_recommendation_outcome(
        cls,
        value: object,
    ) -> object:
        if not isinstance(value, dict) or value.get("mode") != "recommend":
            return value
        normalized = dict(value)
        if normalized.get("recommendation_mode") is None:
            normalized["recommendation_mode"] = "explore"
        if normalized.get("recommendation_count") is None:
            normalized["recommendation_count"] = (
                1
                if normalized["recommendation_mode"] == "fit"
                else 3
            )
        return normalized

    @model_validator(mode="after")
    def validate_mode(self) -> Self:
        if self.mode == "clarify":
            if not self.clarification or self.clarification_code is None:
                raise ValueError(
                    "clarify mode requires clarification and typed code"
                )
        elif (
            self.clarification is not None
            or self.clarification_code is not None
        ):
            raise ValueError(
                "executable mode forbids clarification metadata"
            )
        has_recommendation_outcome = any(
            value is not None
            for value in (
                self.recommendation_mode,
                self.recommendation_mode_basis,
                self.recommendation_count,
            )
        )
        if (
            self.mode not in {"recommend", "clarify"}
            and has_recommendation_outcome
        ):
            raise ValueError(
                "non-recommend plan forbids recommendation outcome"
            )
        if self.mode == "recommend" or has_recommendation_outcome:
            if self.recommendation_mode is None:
                raise ValueError(
                    "recommendation outcome requires recommendation mode"
                )
            if self.recommendation_mode_basis is None:
                raise ValueError(
                    "recommend plan requires recommendation mode basis"
                )
            if self.recommendation_mode == "fit":
                if (
                    self.recommendation_mode_basis
                    not in FIT_RECOMMENDATION_BASES
                ):
                    raise ValueError(
                        "recommendation mode basis must be "
                        "parent-scoped"
                    )
                if self.recommendation_count != 1:
                    raise ValueError(
                        "fit recommendation requires one result"
                    )
            else:
                if (
                    self.recommendation_mode_basis
                    not in EXPLORE_RECOMMENDATION_BASES
                ):
                    raise ValueError(
                        "recommendation mode basis must be "
                        "parent-scoped"
                    )
                if self.recommendation_count not in {2, 3, 4}:
                    raise ValueError(
                        "explore recommendation requires "
                        "two to four results"
                    )
        if any(product_id <= 0 for product_id in self.product_ids):
            raise ValueError("product IDs must be positive")
        if len(self.product_ids) != len(set(self.product_ids)):
            raise ValueError("product IDs must be unique")
        if (
            self.requested_comparison_dimensions
            != tuple(dict.fromkeys(
                self.requested_comparison_dimensions
            ))
            or any(
                not value
                or value != value.strip()
                for value in self.requested_comparison_dimensions
            )
        ):
            raise ValueError(
                "requested comparison dimensions must be ordered "
                "unique values"
            )
        if (
            self.similarity_anchor_product_id is not None
            and self.mode != "recommend"
        ):
            raise ValueError(
                "similarity anchor requires recommend mode"
            )
        if self.similarity_anchor_product_id in self.product_ids:
            raise ValueError(
                "similarity anchor cannot be a recommendation result"
            )
        descriptor_keys = tuple(
            (
                item.field_key,
                item.value.casefold(),
                item.polarity,
            )
            for item in self.free_descriptors
        )
        if len(descriptor_keys) != len(set(descriptor_keys)):
            raise ValueError("free descriptors must be unique")
        if self.mode == "comparison" and self.product_ids:
            if not 2 <= len(self.product_ids) <= 4:
                raise ValueError(
                    "direct comparison requires two to four products"
                )
        if self.mode == "suitability" and self.product_ids:
            if len(self.product_ids) != 1:
                raise ValueError(
                    "direct suitability requires one product"
                )
        return self


def revalidate_task_plan(
    task: TaskPlan,
    *,
    update: Mapping[str, object],
) -> TaskPlan:
    if type(task) is not TaskPlan:
        raise TypeError("task must be an exact TaskPlan")
    if not isinstance(update, Mapping):
        raise TypeError("task update must be a mapping")
    payload = task.model_dump(mode="python")
    payload.update(dict(update))
    return TaskPlan.model_validate(payload, strict=True)


class BudgetRevisionPlan(_StrictContract):
    mode: Literal["revise", "clarify"]
    recommendation_mode: RecommendationMode | None = None
    recommendation_mode_basis: RecommendationModeBasis | None = None
    recommendation_count: int | None = Field(
        default=None,
        ge=1,
        le=4,
    )
    constraints: list[TaskConstraint]
    clarification: str | None = None
    clarification_code: ClarificationCode | None = None

    @model_validator(mode="after")
    def validate_revision_mode(self) -> Self:
        if self.mode == "revise":
            if (
                self.clarification is not None
                or self.clarification_code is not None
            ):
                raise ValueError(
                    "revise mode forbids clarification metadata"
                )
            if not self.constraints:
                raise ValueError("revise mode requires constraints")
            _validate_revision_recommendation_outcome(
                recommendation_mode=self.recommendation_mode,
                recommendation_mode_basis=(
                    self.recommendation_mode_basis
                ),
                recommendation_count=self.recommendation_count,
            )
        else:
            if any(
                value is not None
                for value in (
                    self.recommendation_mode,
                    self.recommendation_mode_basis,
                    self.recommendation_count,
                )
            ):
                raise ValueError(
                    "clarify revision forbids recommendation outcome"
                )
            if not self.clarification or self.clarification_code is None:
                raise ValueError(
                    "clarify mode requires clarification and typed code"
                )
            if self.constraints:
                raise ValueError(
                    "clarify mode forbids constraints"
                )
        return self


class SkinRevisionPlan(_StrictContract):
    mode: Literal["revise", "clarify"]
    recommendation_mode: RecommendationMode | None = None
    recommendation_mode_basis: RecommendationModeBasis | None = None
    recommendation_count: int | None = Field(
        default=None,
        ge=1,
        le=4,
    )
    constraints: list[TaskConstraint]
    clarification: str | None = None
    clarification_code: ClarificationCode | None = None

    @model_validator(mode="after")
    def validate_revision_mode(self) -> Self:
        if self.mode == "revise":
            if (
                self.clarification is not None
                or self.clarification_code is not None
            ):
                raise ValueError(
                    "revise mode forbids clarification metadata"
                )
            if not self.constraints:
                raise ValueError("revise mode requires constraints")
            _validate_revision_recommendation_outcome(
                recommendation_mode=self.recommendation_mode,
                recommendation_mode_basis=(
                    self.recommendation_mode_basis
                ),
                recommendation_count=self.recommendation_count,
            )
        else:
            if any(
                value is not None
                for value in (
                    self.recommendation_mode,
                    self.recommendation_mode_basis,
                    self.recommendation_count,
                )
            ):
                raise ValueError(
                    "clarify revision forbids recommendation outcome"
                )
            if not self.clarification or self.clarification_code is None:
                raise ValueError(
                    "clarify mode requires clarification and typed code"
                )
            if self.constraints:
                raise ValueError(
                    "clarify mode forbids constraints"
                )
        return self


def _validate_revision_recommendation_outcome(
    *,
    recommendation_mode: RecommendationMode | None,
    recommendation_mode_basis: RecommendationModeBasis | None,
    recommendation_count: int | None,
) -> None:
    if (
        recommendation_mode is None
        or recommendation_mode_basis is None
        or recommendation_count is None
    ):
        raise ValueError(
            "revision requires complete recommendation outcome"
        )
    if recommendation_mode == "fit":
        if recommendation_mode_basis not in FIT_RECOMMENDATION_BASES:
            raise ValueError(
                "revision recommendation basis must be parent-scoped"
            )
        if recommendation_count != 1:
            raise ValueError("fit revision requires one result")
        return
    if recommendation_mode_basis not in EXPLORE_RECOMMENDATION_BASES:
        raise ValueError(
            "revision recommendation basis must be parent-scoped"
        )
    if recommendation_count not in {2, 3, 4}:
        raise ValueError("explore revision requires multiple results")


class FollowupPlan(_StrictContract):
    mode: Literal["followup", "clarify"]
    action: FollowupAction | None = None
    ordinal: int | None = Field(default=None, ge=1, le=9)
    clarification: str | None = None
    clarification_code: ClarificationCode | None = None

    @model_validator(mode="after")
    def validate_followup_mode(self) -> Self:
        if self.mode == "followup":
            if (
                self.action is None
                or self.clarification is not None
                or self.clarification_code is not None
            ):
                raise ValueError("followup mode requires action")
            if (
                self.action is FollowupAction.ORDINAL_REFERENCE
                and self.ordinal is None
            ):
                raise ValueError("ordinal followup requires ordinal")
            if (
                self.action is FollowupAction.CHEAPEST
                and self.ordinal is not None
            ):
                raise ValueError("cheapest followup forbids ordinal")
        else:
            if (
                self.clarification is None
                or self.clarification_code is None
            ):
                raise ValueError(
                    "clarify mode requires clarification and typed code"
                )
            if self.action is not None or self.ordinal is not None:
                raise ValueError("clarify mode forbids action")
        return self
