from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.guide.decision.contracts import DecisionProductFacts, FactState
from app.guide.decision.image_compare import ImageCompareDecisionFoundation
from app.guide.decision.image_compare_contracts import (
    ImageCompareDecisionInput,
    ImageCompareDecisionItem,
)
from app.guide.retrieval.category_fact_contracts import (
    AuthorizedCategoryFact,
    SourceClass,
)
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.understanding.contracts import TopicCode


def _facts(
    product_id: int,
    *,
    price: Decimal | None,
    price_state: FactState = FactState.KNOWN,
    price_source_refs: tuple[str, ...] | None = None,
    efficacy: tuple[str, ...] | None = ("防晒",),
    efficacy_state: FactState = FactState.KNOWN,
    suitable_skin: tuple[str, ...] | None = ("多种肤质",),
    suitable_skin_state: FactState = FactState.KNOWN,
) -> DecisionProductFacts:
    return DecisionProductFacts(
        product_id=product_id,
        category_profile=CategoryProfile.SUNCARE,
        category_fields=(),
        price=price,
        price_state=price_state,
        efficacy=efficacy,
        efficacy_state=efficacy_state,
        suitable_skin=suitable_skin,
        suitable_skin_state=suitable_skin_state,
        ingredients_present=("水",),
        ingredients_present_state=FactState.KNOWN,
        verified_absences=None,
        verified_absences_state=FactState.UNKNOWN,
        price_source_refs=(
            price_source_refs
            if price_source_refs is not None
            else (f"price-source:{product_id}",)
        ),
    )


def _request(
    first: DecisionProductFacts,
    second: DecisionProductFacts,
) -> ImageCompareDecisionInput:
    return ImageCompareDecisionInput(
        bundle_id="bundle_" + "a" * 32,
        topic=TopicCode.SUNSCREEN,
        items=(
            ImageCompareDecisionItem(
                ordinal=1,
                image_id="image_" + "b" * 32,
                product_id=first.product_id,
                canonical_category="防晒乳",
                facts=first,
            ),
            ImageCompareDecisionItem(
                ordinal=2,
                image_id="image_" + "c" * 32,
                product_id=second.product_id,
                canonical_category="防晒霜",
                facts=second,
            ),
        ),
    )


def test_unique_deterministic_winner_preserves_second_image_identity() -> None:
    request = _request(
        _facts(53, price=Decimal("159")),
        _facts(55, price=Decimal("88.11")),
    )

    result = ImageCompareDecisionFoundation().decide(request)

    assert result.outcome.status == "winner"
    assert result.outcome.winner_reference == result.references[1]
    assert (
        result.outcome.winner_reference.ordinal,
        result.outcome.winner_reference.image_id,
        result.outcome.winner_reference.product_id,
    ) == (
        request.items[1].ordinal,
        request.items[1].image_id,
        request.items[1].product_id,
    )
    assert result.comparison_dimensions == ("price",)
    assert result.outcome.evidence_refs == (
        "price-source:53",
        "price-source:55",
    )
    assert tuple(
        (
            fact.reference.ordinal,
            fact.reference.image_id,
            fact.reference.product_id,
            fact.state,
            fact.value,
            fact.source_refs,
        )
        for fact in result.outcome.evaluated_price_facts
    ) == (
        (
            1,
            request.items[0].image_id,
            53,
            FactState.KNOWN,
            Decimal("159"),
            ("price-source:53",),
        ),
        (
            2,
            request.items[1].image_id,
            55,
            FactState.KNOWN,
            Decimal("88.11"),
            ("price-source:55",),
        ),
    )


def test_outcome_contract_rejects_status_outside_frozen_three_states() -> None:
    request = _request(
        _facts(53, price=Decimal("159")),
        _facts(55, price=Decimal("88.11")),
    )
    outcome = ImageCompareDecisionFoundation().decide(request).outcome
    payload = outcome.model_dump()

    for invalid_status in ("selected", "ready_for_outcome", "no_candidate"):
        payload["status"] = invalid_status
        with pytest.raises(ValidationError):
            type(outcome).model_validate(payload)


def test_equal_decisive_evidence_is_a_tie_without_id_winner() -> None:
    request = _request(
        _facts(53, price=Decimal("100")),
        _facts(55, price=Decimal("100")),
    )

    result = ImageCompareDecisionFoundation().decide(request)

    assert result.outcome.status == "tie"
    assert result.outcome.winner_reference is None
    assert result.outcome.tie_reason == "equal_price"
    assert result.comparison_dimensions == ("price",)
    assert result.outcome.evidence_refs == (
        "price-source:53",
        "price-source:55",
    )
    tie_metadata = result.outcome.model_dump_json()
    assert "skin_rank" not in tie_metadata
    assert "selected_product_id" not in tie_metadata
    assert "efficacy" not in tie_metadata
    assert "suitable_skin" not in tie_metadata
    assert tuple(
        (reference.ordinal, reference.product_id)
        for reference in result.references
    ) == ((1, 53), (2, 55))


@pytest.mark.parametrize(
    ("price", "price_state"),
    [
        (None, FactState.UNKNOWN),
        (None, FactState.CONFLICT),
        (None, FactState.NOT_APPLICABLE),
    ],
)
def test_missing_or_non_comparable_evidence_is_insufficient(
    price: Decimal | None,
    price_state: FactState,
) -> None:
    request = _request(
        _facts(53, price=Decimal("100")),
        _facts(55, price=price, price_state=price_state),
    )

    result = ImageCompareDecisionFoundation().decide(request)

    assert result.outcome.status == "insufficient_evidence"
    assert result.outcome.winner_reference is None
    assert result.outcome.tie_reason is None
    assert result.comparison_dimensions == ("price",)
    assert result.outcome.evidence_refs == (
        "price-source:53",
        "price-source:55",
    )
    assert tuple(
        (fact.state, fact.value)
        for fact in result.outcome.evaluated_price_facts
    ) == (
        (FactState.KNOWN, Decimal("100")),
        (price_state, None),
    )
    assert tuple(
        (reference.ordinal, reference.product_id)
        for reference in result.references
    ) == ((1, 53), (2, 55))


def test_price_outcome_does_not_claim_unevaluated_efficacy_or_skin() -> None:
    request = _request(
        _facts(
            53,
            price=Decimal("80.00"),
            efficacy=None,
            efficacy_state=FactState.UNKNOWN,
            suitable_skin=None,
            suitable_skin_state=FactState.CONFLICT,
        ),
        _facts(
            55,
            price=Decimal("120"),
            efficacy=None,
            efficacy_state=FactState.CONFLICT,
            suitable_skin=None,
            suitable_skin_state=FactState.UNKNOWN,
        ),
    )

    result = ImageCompareDecisionFoundation().decide(request)

    assert result.outcome.status == "winner"
    assert result.outcome.winner_reference == result.references[0]
    assert result.comparison_dimensions == ("price",)
    assert result.outcome.evidence_refs == (
        "price-source:53",
        "price-source:55",
    )
    assert all(
        "efficacy" not in reference and "skin" not in reference
        for reference in result.outcome.evidence_refs
    )


def test_known_prices_without_auditable_sources_are_insufficient() -> None:
    request = _request(
        _facts(
            53,
            price=Decimal("80"),
            price_source_refs=("approved-price:53",),
        ),
        _facts(55, price=Decimal("120"), price_source_refs=()),
    )

    result = ImageCompareDecisionFoundation().decide(request)

    assert result.outcome.status == "insufficient_evidence"
    assert result.outcome.winner_reference is None
    assert result.outcome.tie_reason is None
    assert result.outcome.evidence_refs == ("approved-price:53",)
    assert all(
        not reference.startswith("canonical_price:")
        for reference in result.outcome.evidence_refs
    )
    assert result.outcome.evaluated_price_facts[1].value == Decimal("120")
    assert result.outcome.evaluated_price_facts[1].source_refs == ()


def test_compare_only_category_fact_does_not_change_two_image_outcome() -> None:
    first = _facts(53, price=Decimal("159"))
    second = _facts(55, price=Decimal("88.11"))
    baseline = ImageCompareDecisionFoundation().decide(
        _request(first, second)
    )
    compare_only = AuthorizedCategoryFact(
        category_profile=CategoryProfile.SUNCARE,
        field_key="water_resistance",
        value="compare-only poison",
        resolved_state="known",
        source_classes=(SourceClass.OFFICIAL_PACKAGING,),
        source_refs=("urn:task9:image-compare",),
        capabilities=frozenset({"evidence", "compare"}),
    )
    poisoned_second = second.model_copy(
        update={"category_fields": (compare_only,)},
        deep=True,
    )

    poisoned = ImageCompareDecisionFoundation().decide(
        _request(first, poisoned_second)
    )

    assert poisoned.model_dump(mode="json") == baseline.model_dump(
        mode="json"
    )
