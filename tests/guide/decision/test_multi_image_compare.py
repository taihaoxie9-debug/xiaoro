from __future__ import annotations

import importlib
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.guide.decision.contracts import DecisionProductFacts, FactState
from app.guide.retrieval.category_fact_contracts import (
    AuthorizedCategoryFact,
    SourceClass,
)
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.understanding.contracts import TopicCode


_PRODUCT_IDS = (53, 55, 57, 54)
_CATEGORIES = ("防晒乳", "防晒霜", "防晒", "防晒乳液")


def _contracts():
    try:
        return importlib.import_module(
            "app.guide.decision.multi_image_compare_contracts"
        )
    except ModuleNotFoundError:
        pytest.fail("three/four-image compare contracts are missing")


def _decision():
    try:
        return importlib.import_module(
            "app.guide.decision.multi_image_compare"
        )
    except ModuleNotFoundError:
        pytest.fail("three/four-image compare decision is missing")


def _facts(
    product_id: int,
    price: str | None,
    *,
    price_state: FactState = FactState.KNOWN,
    source_refs: tuple[str, ...] | None = None,
) -> DecisionProductFacts:
    return DecisionProductFacts(
        product_id=product_id,
        category_profile=CategoryProfile.SUNCARE,
        category_fields=(),
        price=Decimal(price) if price is not None else None,
        price_state=price_state,
        efficacy=("防晒",),
        efficacy_state=FactState.KNOWN,
        suitable_skin=("多种肤质",),
        suitable_skin_state=FactState.KNOWN,
        ingredients_present=("水",),
        ingredients_present_state=FactState.KNOWN,
        verified_absences=None,
        verified_absences_state=FactState.UNKNOWN,
        price_source_refs=(
            source_refs
            if source_refs is not None
            else (f"price-source:{product_id}",)
        ),
    )


def _request(
    prices: tuple[str | None, ...],
    *,
    states: tuple[FactState, ...] | None = None,
    source_refs: tuple[tuple[str, ...], ...] | None = None,
):
    contracts = _contracts()
    count = len(prices)
    fact_states = states or (FactState.KNOWN,) * count
    audited_sources = source_refs or tuple(
        (f"price-source:{product_id}",)
        for product_id in _PRODUCT_IDS[:count]
    )
    return contracts.MultiImageCompareDecisionInput(
        bundle_id="bundle_" + "a" * 32,
        topic=TopicCode.SUNSCREEN,
        items=tuple(
            contracts.MultiImageCompareDecisionItem(
                ordinal=ordinal,
                image_id=f"image_{ordinal:032d}",
                product_id=product_id,
                canonical_category=category,
                facts=_facts(
                    product_id,
                    price,
                    price_state=state,
                    source_refs=refs,
                ),
            )
            for ordinal, (
                product_id,
                category,
                price,
                state,
                refs,
            ) in enumerate(
                zip(
                    _PRODUCT_IDS[:count],
                    _CATEGORIES[:count],
                    prices,
                    fact_states,
                    audited_sources,
                    strict=True,
                ),
                start=1,
            )
        ),
    )


@pytest.mark.parametrize(
    ("prices", "expected_ids"),
    [
        (("159", "88.11", "120"), (53, 55, 57)),
        (("159", "88.11", "120", "99"), (53, 55, 57, 54)),
    ],
)
def test_three_or_four_images_emit_exact_ordinal_card_intent(
    prices: tuple[str, ...],
    expected_ids: tuple[int, ...],
) -> None:
    request = _request(prices)

    result = _decision().MultiImageCompareDecisionFoundation().decide(
        request
    )

    assert result.status == "ready_for_outcome"
    assert result.bundle_id == request.bundle_id
    assert result.topic is TopicCode.SUNSCREEN
    assert result.ordered_product_ids == expected_ids
    assert tuple(
        (reference.ordinal, reference.image_id, reference.product_id)
        for reference in result.references
    ) == tuple(
        (item.ordinal, item.image_id, item.product_id)
        for item in request.items
    )
    assert result.card_intent.mode == "comparison"
    assert result.card_intent.visible_product_ids == expected_ids
    assert result.card_intent.reason == "comparison"
    assert result.comparison_dimensions == ("price",)


def test_unique_lowest_audited_price_is_the_deterministic_winner() -> None:
    request = _request(("159", "88.11", "120", "99"))

    result = _decision().MultiImageCompareDecisionFoundation().decide(
        request
    )

    assert result.outcome.status == "winner"
    assert result.outcome.winner_reference == result.references[1]
    assert (
        result.outcome.winner_reference.ordinal,
        result.outcome.winner_reference.image_id,
        result.outcome.winner_reference.product_id,
    ) == (2, request.items[1].image_id, 55)
    assert result.outcome.tie_reason is None
    assert result.outcome.evidence_refs == (
        "price-source:53",
        "price-source:55",
        "price-source:57",
        "price-source:54",
    )


def test_equal_lowest_audited_prices_are_a_tie_without_id_winner() -> None:
    request = _request(("80", "100", "80"))

    result = _decision().MultiImageCompareDecisionFoundation().decide(
        request
    )

    assert result.outcome.status == "tie"
    assert result.outcome.winner_reference is None
    assert result.outcome.tie_reason == "equal_lowest_price"
    assert result.outcome.evidence_refs == (
        "price-source:53",
        "price-source:55",
        "price-source:57",
    )
    assert result.card_intent.visible_product_ids == (53, 55, 57)


@pytest.mark.parametrize(
    "state",
    [
        FactState.UNKNOWN,
        FactState.CONFLICT,
        FactState.NOT_APPLICABLE,
    ],
)
def test_audited_non_comparable_price_is_insufficient_evidence(
    state: FactState,
) -> None:
    request = _request(
        ("80", "100", None),
        states=(FactState.KNOWN, FactState.KNOWN, state),
        source_refs=(
            ("price-source:53",),
            ("price-source:55",),
            (f"price-state-source:57:{state.value}",),
        ),
    )

    result = _decision().MultiImageCompareDecisionFoundation().decide(
        request
    )

    assert result.outcome.status == "insufficient_evidence"
    assert result.outcome.winner_reference is None
    assert result.outcome.tie_reason is None
    assert tuple(
        (fact.state, fact.value)
        for fact in result.outcome.evaluated_price_facts
    ) == (
        (FactState.KNOWN, Decimal("80")),
        (FactState.KNOWN, Decimal("100")),
        (state, None),
    )
    assert result.card_intent.visible_product_ids == (53, 55, 57)


def test_unaudited_price_cannot_produce_winner_or_tie() -> None:
    request = _request(
        ("80", "100", "120"),
        source_refs=(
            ("price-source:53",),
            (),
            ("price-source:57",),
        ),
    )

    result = _decision().MultiImageCompareDecisionFoundation().decide(
        request
    )

    assert result.outcome.status == "insufficient_evidence"
    assert result.outcome.winner_reference is None
    assert result.outcome.tie_reason is None
    assert result.outcome.evidence_refs == (
        "price-source:53",
        "price-source:57",
    )


@pytest.mark.parametrize("count", [2, 5])
def test_decision_input_rejects_counts_outside_three_or_four(
    count: int,
) -> None:
    contracts = _contracts()
    valid = _request(("80", "100", "120"))
    item = valid.items[0]

    with pytest.raises(ValidationError, match="three or four"):
        contracts.MultiImageCompareDecisionInput(
            bundle_id=valid.bundle_id,
            topic=valid.topic,
            items=tuple(item for _ in range(count)),
        )


def test_decision_input_rejects_reordered_or_duplicate_products() -> None:
    contracts = _contracts()
    valid = _request(("80", "100", "120"))

    payload = valid.model_dump()
    payload["items"][1]["ordinal"] = 3
    payload["items"][2]["ordinal"] = 2
    with pytest.raises(ValidationError, match="ordinals"):
        contracts.MultiImageCompareDecisionInput.model_validate(payload)

    payload = valid.model_dump()
    payload["items"][2]["product_id"] = 53
    payload["items"][2]["facts"]["product_id"] = 53
    with pytest.raises(ValidationError, match="unique"):
        contracts.MultiImageCompareDecisionInput.model_validate(payload)


def test_decision_input_rejects_category_conflict() -> None:
    contracts = _contracts()
    valid = _request(("80", "100", "120"))
    payload = valid.model_dump()
    payload["items"][2]["canonical_category"] = "精华液"

    with pytest.raises(ValidationError, match="categories"):
        contracts.MultiImageCompareDecisionInput.model_validate(payload)


def test_result_rejects_card_order_different_from_bundle_ordinals() -> None:
    result = _decision().MultiImageCompareDecisionFoundation().decide(
        _request(("80", "100", "120"))
    )
    payload = result.model_dump()
    payload["card_intent"]["visible_product_ids"] = (55, 53, 57)

    with pytest.raises(ValidationError, match="card intent"):
        type(result).model_validate(payload)


def test_rank_capabilities_do_not_change_multi_image_outcome_or_cards() -> None:
    request = _request(("80", "100", "120"))
    decision = _decision().MultiImageCompareDecisionFoundation()
    baseline = decision.decide(request)
    poison = AuthorizedCategoryFact(
        category_profile=CategoryProfile.SUNCARE,
        field_key="water_resistance",
        value="rank poison",
        resolved_state="known",
        source_classes=(SourceClass.STRUCTURED_OFFICIAL,),
        source_refs=("urn:task9:multi-image-rank",),
        capabilities=frozenset(
            {"evidence", "hard_filter", "soft_rank"}
        ),
    )
    payload = request.model_dump(mode="python")
    payload["items"][1]["facts"]["category_fields"] = (
        poison.model_dump(mode="python"),
    )
    poisoned_request = type(request).model_validate(payload)

    poisoned = decision.decide(poisoned_request)

    assert poisoned.model_dump(mode="json") == baseline.model_dump(
        mode="json"
    )
    assert poisoned.card_intent.visible_product_ids == (53, 55, 57)
