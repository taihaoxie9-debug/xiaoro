from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.guide.understanding.contracts import (
    EfficacyTarget,
    FollowupAction,
    ProductMentionDraft,
    ReferenceDraft,
    SkinTarget,
    TopicCode,
)
from app.guide.understanding.semantic_contracts import ClarificationCode


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
    question_meaning: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
    )
    safety_sensitive: bool = False
    clarification: str | None = None
    clarification_code: ClarificationCode | None = None

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
        if any(product_id <= 0 for product_id in self.product_ids):
            raise ValueError("product IDs must be positive")
        if len(self.product_ids) != len(set(self.product_ids)):
            raise ValueError("product IDs must be unique")
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


class BudgetRevisionPlan(_StrictContract):
    mode: Literal["revise", "clarify"]
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
        else:
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
        else:
            if not self.clarification or self.clarification_code is None:
                raise ValueError(
                    "clarify mode requires clarification and typed code"
                )
            if self.constraints:
                raise ValueError(
                    "clarify mode forbids constraints"
                )
        return self


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
