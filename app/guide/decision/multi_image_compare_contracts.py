from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
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
EvidenceRef = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
ComparisonDimension = Literal["price"]


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class FrozenDecisionProductFacts(DecisionProductFacts):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    @classmethod
    def project(
        cls,
        facts: DecisionProductFacts,
    ) -> FrozenDecisionProductFacts:
        return cls.model_validate(facts.model_dump(mode="python"))


class MultiImageCompareDecisionItem(_StrictFrozen):
    ordinal: int = Field(ge=1, le=4)
    image_id: OpaqueImageId
    product_id: int = Field(ge=1)
    canonical_category: CanonicalCategory
    facts: FrozenDecisionProductFacts

    @field_validator("facts", mode="before")
    @classmethod
    def project_facts(
        cls,
        value: object,
    ) -> object:
        if isinstance(value, FrozenDecisionProductFacts):
            return value
        if isinstance(value, DecisionProductFacts):
            return FrozenDecisionProductFacts.project(value)
        return value

    @model_validator(mode="after")
    def validate_fact_identity(self) -> Self:
        if self.facts.product_id != self.product_id:
            raise ValueError("facts product_id must match comparison item")
        return self


class MultiImageCompareDecisionInput(_StrictFrozen):
    bundle_id: OpaqueBundleId
    topic: TopicCode
    items: tuple[MultiImageCompareDecisionItem, ...]

    @model_validator(mode="after")
    def validate_items(self) -> Self:
        count = len(self.items)
        if count not in (3, 4):
            raise ValueError(
                "multi-image compare requires exactly three or four items"
            )
        if tuple(item.ordinal for item in self.items) != tuple(
            range(1, count + 1)
        ):
            raise ValueError(
                "multi-image compare ordinals must be contiguous"
            )
        product_ids = tuple(item.product_id for item in self.items)
        if len(set(product_ids)) != count:
            raise ValueError(
                "multi-image compare product IDs must be unique"
            )
        allowed_categories = canonical_categories_for(self.topic)
        if any(
            item.canonical_category not in allowed_categories
            for item in self.items
        ):
            raise ValueError(
                "multi-image compare categories must match the topic"
            )
        return self


class MultiImageCompareDecisionReference(_StrictFrozen):
    ordinal: int = Field(ge=1, le=4)
    image_id: OpaqueImageId
    product_id: int = Field(ge=1)


class MultiImageCompareEvaluatedPriceFact(_StrictFrozen):
    reference: MultiImageCompareDecisionReference
    state: FactState
    value: Decimal | None
    source_refs: tuple[EvidenceRef, ...] = ()

    @model_validator(mode="after")
    def validate_price_fact(self) -> Self:
        if self.state is FactState.KNOWN:
            if self.value is None:
                raise ValueError("known evaluated price requires value")
        elif self.value is not None:
            raise ValueError("unevaluated price state forbids value")
        if len(set(self.source_refs)) != len(self.source_refs):
            raise ValueError("price evidence references must be unique")
        return self


class MultiImageComparisonCardIntent(_StrictFrozen):
    mode: Literal["comparison"]
    visible_product_ids: tuple[int, ...]
    reason: Literal["comparison"]

    @model_validator(mode="after")
    def validate_products(self) -> Self:
        count = len(self.visible_product_ids)
        if count not in (3, 4):
            raise ValueError(
                "multi-image card intent requires three or four products"
            )
        if (
            len(set(self.visible_product_ids)) != count
            or any(product_id < 1 for product_id in self.visible_product_ids)
        ):
            raise ValueError(
                "multi-image card intent requires unique product IDs"
            )
        return self


class MultiImageCompareOutcome(_StrictFrozen):
    status: Literal["winner", "tie", "insufficient_evidence"]
    winner_reference: MultiImageCompareDecisionReference | None = None
    evidence_refs: tuple[EvidenceRef, ...]
    evaluated_price_facts: tuple[
        MultiImageCompareEvaluatedPriceFact,
        ...,
    ]
    tie_reason: Literal["equal_lowest_price"] | None = None

    @model_validator(mode="after")
    def validate_status_fields(self) -> Self:
        count = len(self.evaluated_price_facts)
        if count not in (3, 4):
            raise ValueError(
                "multi-image outcome requires three or four price facts"
            )
        expected_refs = tuple(
            source_ref
            for fact in self.evaluated_price_facts
            for source_ref in fact.source_refs
        )
        if self.evidence_refs != expected_refs:
            raise ValueError(
                "evidence references must match evaluated price facts"
            )
        auditable_prices = all(
            fact.state is FactState.KNOWN
            and fact.value is not None
            and bool(fact.source_refs)
            for fact in self.evaluated_price_facts
        )

        if self.status == "insufficient_evidence":
            if self.winner_reference is not None or self.tie_reason is not None:
                raise ValueError(
                    "insufficient outcome forbids winner and tie metadata"
                )
            if auditable_prices:
                raise ValueError(
                    "complete audited prices require winner or tie"
                )
            return self

        if not auditable_prices:
            raise ValueError(
                "winner and tie outcomes require audited prices"
            )
        prices = tuple(
            fact.value for fact in self.evaluated_price_facts
        )
        assert all(price is not None for price in prices)
        minimum = min(price for price in prices if price is not None)
        lowest_facts = tuple(
            fact
            for fact in self.evaluated_price_facts
            if fact.value == minimum
        )

        if self.status == "winner":
            if self.tie_reason is not None:
                raise ValueError("winner outcome forbids tie reason")
            if self.winner_reference is None:
                raise ValueError("winner outcome requires winner reference")
            if (
                len(lowest_facts) != 1
                or lowest_facts[0].reference != self.winner_reference
            ):
                raise ValueError(
                    "winner reference must have the unique lowest price"
                )
            return self

        if self.winner_reference is not None:
            raise ValueError("tie outcome forbids winner reference")
        if self.tie_reason != "equal_lowest_price":
            raise ValueError("tie outcome requires equal lowest price reason")
        if len(lowest_facts) < 2:
            raise ValueError("tie outcome requires equal lowest prices")
        return self


class MultiImageCompareDecisionResult(_StrictFrozen):
    status: Literal["ready_for_outcome"]
    bundle_id: OpaqueBundleId
    topic: TopicCode
    references: tuple[MultiImageCompareDecisionReference, ...]
    ordered_product_ids: tuple[int, ...]
    comparison_dimensions: tuple[ComparisonDimension, ...]
    outcome: MultiImageCompareOutcome
    card_intent: MultiImageComparisonCardIntent

    @model_validator(mode="after")
    def validate_mapping(self) -> Self:
        count = len(self.references)
        if count not in (3, 4):
            raise ValueError(
                "multi-image result requires three or four references"
            )
        if self.comparison_dimensions != ("price",):
            raise ValueError(
                "comparison dimensions must be exactly price"
            )
        if tuple(item.ordinal for item in self.references) != tuple(
            range(1, count + 1)
        ):
            raise ValueError(
                "multi-image result ordinals must be contiguous"
            )
        referenced_ids = tuple(
            item.product_id for item in self.references
        )
        if len(set(referenced_ids)) != count:
            raise ValueError(
                "multi-image result product IDs must be unique"
            )
        if self.ordered_product_ids != referenced_ids:
            raise ValueError(
                "ordered product IDs must match ordinal references"
            )
        if self.card_intent.visible_product_ids != referenced_ids:
            raise ValueError(
                "card intent must match ordinal product references"
            )
        evaluated_references = tuple(
            fact.reference for fact in self.outcome.evaluated_price_facts
        )
        if evaluated_references != self.references:
            raise ValueError(
                "evaluated price facts must match result references"
            )
        if (
            self.outcome.status == "winner"
            and self.outcome.winner_reference not in self.references
        ):
            raise ValueError(
                "winner reference must be one result reference"
            )
        return self
