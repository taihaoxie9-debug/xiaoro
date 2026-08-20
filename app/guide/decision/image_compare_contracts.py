from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.guide.decision.contracts import DecisionProductFacts, FactState
from app.guide.retrieval.category_taxonomy import canonical_categories_for
from app.guide.understanding.contracts import (
    OpaqueBundleId,
    OpaqueImageId,
    TopicCode,
)


CanonicalCategory = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
]
ComparisonDimension = Literal["price"]


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ImageCompareDecisionItem(_StrictFrozen):
    ordinal: int = Field(ge=1, le=2)
    image_id: OpaqueImageId
    product_id: int = Field(ge=1)
    canonical_category: CanonicalCategory
    facts: DecisionProductFacts

    @model_validator(mode="after")
    def validate_fact_identity(self) -> Self:
        if self.facts.product_id != self.product_id:
            raise ValueError("facts product_id must match comparison item")
        return self


class ImageCompareDecisionInput(_StrictFrozen):
    bundle_id: OpaqueBundleId
    topic: TopicCode
    items: tuple[ImageCompareDecisionItem, ImageCompareDecisionItem]

    @model_validator(mode="after")
    def validate_items(self) -> Self:
        if tuple(item.ordinal for item in self.items) != (1, 2):
            raise ValueError("image compare ordinals must be exactly 1, 2")
        product_ids = tuple(item.product_id for item in self.items)
        if len(set(product_ids)) != 2:
            raise ValueError("image compare product IDs must be unique")
        allowed_categories = canonical_categories_for(self.topic)
        if any(
            item.canonical_category not in allowed_categories
            for item in self.items
        ):
            raise ValueError(
                "image compare categories must match the comparison topic"
            )
        return self


class ImageCompareDecisionReference(_StrictFrozen):
    ordinal: int = Field(ge=1, le=2)
    image_id: OpaqueImageId
    product_id: int = Field(ge=1)


class ImageCompareEvaluatedPriceFact(_StrictFrozen):
    reference: ImageCompareDecisionReference
    state: FactState
    value: Decimal | None
    source_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_price_fact(self) -> Self:
        if self.state is FactState.KNOWN:
            if self.value is None:
                raise ValueError("known evaluated price requires value")
        elif self.value is not None:
            raise ValueError("unevaluated price state forbids value")
        if any(not reference.strip() for reference in self.source_refs):
            raise ValueError("price evidence references must not be empty")
        if len(set(self.source_refs)) != len(self.source_refs):
            raise ValueError("price evidence references must be unique")
        return self


class ImageCompareOutcome(_StrictFrozen):
    status: Literal["winner", "tie", "insufficient_evidence"]
    winner_reference: ImageCompareDecisionReference | None = None
    evidence_refs: tuple[str, ...]
    evaluated_price_facts: tuple[
        ImageCompareEvaluatedPriceFact,
        ImageCompareEvaluatedPriceFact,
    ]
    tie_reason: Literal["equal_price"] | None = None

    @model_validator(mode="after")
    def validate_status_fields(self) -> Self:
        expected_evidence_refs = tuple(
            source_ref
            for fact in self.evaluated_price_facts
            for source_ref in fact.source_refs
        )
        if self.evidence_refs != expected_evidence_refs:
            raise ValueError(
                "evidence references must match evaluated price facts"
            )
        support_is_auditable = all(
            fact.state is FactState.KNOWN
            and fact.value is not None
            and bool(fact.source_refs)
            for fact in self.evaluated_price_facts
        )

        if self.status == "winner":
            if self.winner_reference is None:
                raise ValueError("winner outcome requires winner reference")
            if not support_is_auditable:
                raise ValueError("winner outcome requires auditable prices")
            matching_facts = [
                fact
                for fact in self.evaluated_price_facts
                if fact.reference == self.winner_reference
            ]
            if len(matching_facts) != 1:
                raise ValueError(
                    "winner reference must match one evaluated price fact"
                )
            winner_value = matching_facts[0].value
            assert winner_value is not None
            other_values = [
                fact.value
                for fact in self.evaluated_price_facts
                if fact.reference != self.winner_reference
            ]
            if not other_values or any(
                value is None or winner_value >= value
                for value in other_values
            ):
                raise ValueError(
                    "winner reference must have the unique lower price"
                )
        elif self.winner_reference is not None:
            raise ValueError(
                "winner reference is only valid for winner outcome"
            )

        if self.status == "tie":
            if not self.tie_reason:
                raise ValueError("tie outcome requires tie reason")
            if not support_is_auditable:
                raise ValueError("tie outcome requires auditable prices")
            first, second = self.evaluated_price_facts
            if first.value != second.value:
                raise ValueError("tie outcome requires equal prices")
        elif self.tie_reason is not None:
            raise ValueError("tie reason is only valid for tie outcome")
        return self


class ImageCompareDecisionResult(_StrictFrozen):
    status: Literal["ready_for_outcome"]
    bundle_id: OpaqueBundleId
    topic: TopicCode
    references: tuple[
        ImageCompareDecisionReference,
        ImageCompareDecisionReference,
    ]
    ordered_product_ids: tuple[int, int]
    comparison_dimensions: tuple[ComparisonDimension, ...]
    outcome: ImageCompareOutcome

    @model_validator(mode="after")
    def validate_mapping(self) -> Self:
        if self.comparison_dimensions != ("price",):
            raise ValueError(
                "comparison dimensions must be exactly price"
            )
        if tuple(item.ordinal for item in self.references) != (1, 2):
            raise ValueError("image compare result ordinals must be 1, 2")
        referenced_ids = tuple(
            item.product_id for item in self.references
        )
        if len(set(referenced_ids)) != 2:
            raise ValueError(
                "image compare result product IDs must be unique"
            )
        if self.ordered_product_ids != referenced_ids:
            raise ValueError(
                "ordered product IDs must match ordinal references"
            )
        evaluated_references = tuple(
            fact.reference for fact in self.outcome.evaluated_price_facts
        )
        if evaluated_references != self.references:
            raise ValueError(
                "evaluated price facts must match result references"
            )
        if self.outcome.status == "winner":
            winner = self.outcome.winner_reference
            if sum(
                reference == winner for reference in self.references
            ) != 1:
                raise ValueError(
                    "winner reference must be exactly one result reference"
                )
        return self
