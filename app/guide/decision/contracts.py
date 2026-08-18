from decimal import Decimal
from enum import Enum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.guide.retrieval.category_fact_contracts import (
    AuthorizedCategoryFact,
    revalidate_authorized_category_fact,
)
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.retrieval.selection_fact_contracts import SelectionFact
from app.guide.understanding.contracts import FollowupAction


class _StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class FactState(str, Enum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"
    NOT_APPLICABLE = "not_applicable"


class DecisionProductFacts(_StrictContract):
    product_id: int
    category_profile: CategoryProfile
    category_fields: tuple[AuthorizedCategoryFact, ...]
    price: Decimal | None
    price_state: FactState
    efficacy: tuple[str, ...] | None
    efficacy_state: FactState
    suitable_skin: tuple[str, ...] | None
    suitable_skin_state: FactState
    ingredients_present: tuple[str, ...] | None
    ingredients_present_state: FactState
    verified_absences: tuple[str, ...] | None
    verified_absences_state: FactState
    price_source_refs: tuple[str, ...] = ()
    suitable_skin_source_refs: tuple[str, ...] = ()
    selection_facts: tuple[SelectionFact, ...] = ()

    @model_validator(mode="after")
    def validate_state_values(self) -> Self:
        category_fields = tuple(
            revalidate_authorized_category_fact(item)
            for item in self.category_fields
        )
        if any(
            item.category_profile is not self.category_profile
            for item in category_fields
        ):
            raise ValueError(
                "category fact profile must match decision product profile"
            )
        object.__setattr__(self, "category_fields", category_fields)
        field_keys = tuple(
            item.field_key for item in category_fields
        )
        if field_keys != tuple(sorted(set(field_keys))):
            raise ValueError(
                "category fields must be sorted and unique"
            )
        selection_facts = tuple(
            SelectionFact.model_validate(
                item.model_dump(mode="python"),
                strict=True,
            )
            for item in self.selection_facts
        )
        if any(
            item.product_id != self.product_id
            for item in selection_facts
        ):
            raise ValueError(
                "selection fact product must match decision product"
            )
        if any(
            item.category_profile is not self.category_profile
            for item in selection_facts
        ):
            raise ValueError(
                "selection fact profile must match decision product"
            )
        selection_keys = tuple(
            item.selection_key for item in selection_facts
        )
        if len(selection_keys) != len(set(selection_keys)):
            raise ValueError(
                "selection facts must have unique identities"
            )
        expected_selection_facts = tuple(
            sorted(
                selection_facts,
                key=lambda item: (
                    item.product_id,
                    item.subject_scope,
                    item.variant_scope or "",
                    item.field_key,
                    item.normalized_value.casefold(),
                ),
            )
        )
        if selection_facts != expected_selection_facts:
            raise ValueError("selection facts must be sorted")
        object.__setattr__(
            self,
            "selection_facts",
            selection_facts,
        )
        pairs = (
            (self.price, self.price_state, "price"),
            (
                self.efficacy,
                self.efficacy_state,
                "efficacy",
            ),
            (
                self.suitable_skin,
                self.suitable_skin_state,
                "suitable_skin",
            ),
            (
                self.ingredients_present,
                self.ingredients_present_state,
                "ingredients_present",
            ),
            (
                self.verified_absences,
                self.verified_absences_state,
                "verified_absences",
            ),
        )
        for value, state, field_name in pairs:
            if state is FactState.KNOWN and value is None:
                raise ValueError(
                    f"{field_name} requires value when known"
                )
            if state is not FactState.KNOWN and value is not None:
                raise ValueError(
                    f"{field_name} forbids value unless known"
                )
        if any(not reference.strip() for reference in self.price_source_refs):
            raise ValueError("price source references must not be empty")
        if len(set(self.price_source_refs)) != len(self.price_source_refs):
            raise ValueError("price source references must be unique")
        if any(
            not reference.strip()
            for reference in self.suitable_skin_source_refs
        ):
            raise ValueError(
                "suitable skin source references must not be empty"
            )
        if (
            len(set(self.suitable_skin_source_refs))
            != len(self.suitable_skin_source_refs)
        ):
            raise ValueError(
                "suitable skin source references must be unique"
            )
        return self


class WinnerStatus(str, Enum):
    SELECTED = "SELECTED"
    TIED_BY_BUSINESS_EVIDENCE = "TIED_BY_BUSINESS_EVIDENCE"
    INSUFFICIENT_FOR_WINNER = "INSUFFICIENT_FOR_WINNER"
    NO_CANDIDATE = "NO_CANDIDATE"


class CandidateEvaluation(_StrictContract):
    product_id: int
    disposition: Literal[
        "eligible",
        "excluded_category_mismatch",
        "excluded_category_unknown",
        "excluded_price_unknown",
        "excluded_budget",
        "excluded_efficacy_mismatch",
        "excluded_efficacy_unknown",
        "excluded_skin_mismatch",
        "excluded_exclusion_match",
        "excluded_evidence_unknown",
    ]
    price: Decimal | None
    skin_match: Literal[
        "matched",
        "unknown",
        "mismatch",
        "not_applicable",
    ]
    efficacy_match: Literal[
        "matched",
        "unknown",
        "mismatch",
        "not_applicable",
    ]
    matched_efficacies: list[str]
    reasons: list[str]


class RiskFinding(_StrictContract):
    kind: Literal[
        "skin_match_unknown",
        "efficacy_evidence_unknown",
        "exclusion_evidence_unknown",
        "canonical_fact_conflict",
    ]
    product_id: int
    detail: str


class RelativeComparisonResult(_StrictContract):
    candidate_product_id: int
    baseline_product_id: int
    status: Literal[
        "better",
        "not_better",
        "evidence_gap",
    ]
    relation_kind: Literal[
        "numeric",
        "ordered",
        "better_preference_match",
        "better_evidence_support",
        "unsupported",
    ]
    source_refs: tuple[str, ...]
    effect_claim_supported: bool

    @model_validator(mode="after")
    def validate_source_refs(self) -> Self:
        if self.source_refs != tuple(sorted(set(self.source_refs))):
            raise ValueError(
                "relative source references must be sorted and unique"
            )
        return self


class DecisionResult(_StrictContract):
    ordered_product_ids: list[int]
    winner_status: WinnerStatus
    winner_product_id: int | None = None
    evaluations: list[CandidateEvaluation]
    comparison_dimensions: list[str]
    risk_findings: list[RiskFinding]
    evidence_refs: list[str]
    relative_comparisons: list[RelativeComparisonResult] = Field(
        default_factory=list
    )
    tie_reason: str | None = None

    @model_validator(mode="after")
    def validate_winner_consistency(self) -> Self:
        if (
            self.winner_status is WinnerStatus.SELECTED
            and self.winner_product_id is None
        ):
            raise ValueError(
                "winner_product_id is required when winner_status is SELECTED"
            )

        if (
            self.winner_status is not WinnerStatus.SELECTED
            and self.winner_product_id is not None
        ):
            raise ValueError(
                "winner_product_id is forbidden unless winner_status is SELECTED"
            )

        if (
            self.winner_status is WinnerStatus.TIED_BY_BUSINESS_EVIDENCE
            and not self.tie_reason
        ):
            raise ValueError("tie_reason is required for business tie")

        if (
            self.winner_status is not WinnerStatus.TIED_BY_BUSINESS_EVIDENCE
            and self.tie_reason is not None
        ):
            raise ValueError("tie_reason is only valid for business tie")

        return self


class FollowupDecisionResult(_StrictContract):
    action: FollowupAction
    ordinal: int | None = Field(default=None, ge=1, le=4)
    status: Literal["selected", "tied", "insufficient_evidence"]
    source_candidate_ids: list[int] = Field(min_length=1, max_length=4)
    selected_product_ids: list[int] = Field(max_length=4)
    evidence_refs: list[str]

    @model_validator(mode="after")
    def validate_selection(self) -> Self:
        if self.action is FollowupAction.ORDINAL_REFERENCE:
            if self.ordinal is None:
                raise ValueError("ordinal result requires ordinal")
        elif self.ordinal is not None:
            raise ValueError("cheapest result forbids ordinal")
        if self.status == "insufficient_evidence":
            if self.selected_product_ids:
                raise ValueError("insufficient evidence forbids selection")
        elif not self.selected_product_ids:
            raise ValueError("selected or tied status requires products")
        if not set(self.selected_product_ids) <= set(
            self.source_candidate_ids
        ):
            raise ValueError("selected product must come from snapshot")
        return self
