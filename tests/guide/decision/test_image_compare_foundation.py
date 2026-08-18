from __future__ import annotations

import importlib
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.guide.decision.contracts import DecisionProductFacts, FactState
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.understanding.contracts import TopicCode


def _contracts():
    try:
        return importlib.import_module(
            "app.guide.decision.image_compare_contracts"
        )
    except ModuleNotFoundError:
        pytest.fail("image compare decision contracts are missing")


def _decision():
    try:
        return importlib.import_module(
            "app.guide.decision.image_compare"
        )
    except ModuleNotFoundError:
        pytest.fail("image compare decision foundation is missing")


def _facts(product_id: int, price: str) -> DecisionProductFacts:
    return DecisionProductFacts(
        product_id=product_id,
        category_profile=CategoryProfile.SUNCARE,
        category_fields=(),
        price=Decimal(price),
        price_state=FactState.KNOWN,
        efficacy=("防晒",),
        efficacy_state=FactState.KNOWN,
        suitable_skin=("多种肤质",),
        suitable_skin_state=FactState.KNOWN,
        ingredients_present=("水",),
        ingredients_present_state=FactState.KNOWN,
        verified_absences=None,
        verified_absences_state=FactState.UNKNOWN,
        price_source_refs=(f"price-source:{product_id}",),
    )


def _decision_input():
    contracts = _contracts()
    return contracts.ImageCompareDecisionInput(
        bundle_id="bundle_" + "a" * 32,
        topic=TopicCode.SUNSCREEN,
        items=(
            contracts.ImageCompareDecisionItem(
                ordinal=1,
                image_id="image_" + "b" * 32,
                product_id=53,
                canonical_category="防晒乳",
                facts=_facts(53, "159"),
            ),
            contracts.ImageCompareDecisionItem(
                ordinal=2,
                image_id="image_" + "c" * 32,
                product_id=55,
                canonical_category="防晒霜",
                facts=_facts(55, "88.11"),
            ),
        ),
    )


def test_decision_input_is_exactly_two_ordered_unique_products() -> None:
    contracts = _contracts()
    valid = _decision_input()

    assert tuple(item.ordinal for item in valid.items) == (1, 2)
    assert tuple(item.product_id for item in valid.items) == (53, 55)

    payload = valid.model_dump()
    payload["items"] = (payload["items"][0],)
    with pytest.raises(ValidationError):
        contracts.ImageCompareDecisionInput.model_validate(payload)

    payload = valid.model_dump()
    payload["items"][1]["ordinal"] = 1
    with pytest.raises(ValidationError, match="ordinals"):
        contracts.ImageCompareDecisionInput.model_validate(payload)

    payload = valid.model_dump()
    payload["items"][1]["product_id"] = 53
    payload["items"][1]["facts"]["product_id"] = 53
    with pytest.raises(ValidationError, match="unique"):
        contracts.ImageCompareDecisionInput.model_validate(payload)


def test_decision_item_rejects_fact_product_mismatch() -> None:
    contracts = _contracts()

    with pytest.raises(ValidationError, match="facts product_id"):
        contracts.ImageCompareDecisionItem(
            ordinal=1,
            image_id="image_" + "b" * 32,
            product_id=53,
            canonical_category="防晒乳",
            facts=_facts(55, "88.11"),
        )


def test_foundation_result_preserves_exact_ordinal_product_mapping() -> None:
    request = _decision_input()

    result = _decision().ImageCompareDecisionFoundation().decide(request)

    assert result.status == "ready_for_outcome"
    assert result.bundle_id == request.bundle_id
    assert result.topic is TopicCode.SUNSCREEN
    assert result.ordered_product_ids == (53, 55)
    assert [
        (item.ordinal, item.image_id, item.product_id)
        for item in result.references
    ] == [
        (1, "image_" + "b" * 32, 53),
        (2, "image_" + "c" * 32, 55),
    ]
    assert result.comparison_dimensions == ("price",)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("ordinal", 1),
        ("image_id", "image_" + "d" * 32),
        ("product_id", 53),
    ],
)
def test_result_rejects_winner_reference_not_exactly_in_references(
    field: str,
    invalid_value: object,
) -> None:
    result = _decision().ImageCompareDecisionFoundation().decide(
        _decision_input()
    )
    payload = result.model_dump()
    payload["outcome"]["winner_reference"][field] = invalid_value

    with pytest.raises(ValidationError, match="winner reference"):
        type(result).model_validate(payload)


@pytest.mark.parametrize(
    "dimensions",
    [
        (),
        ("price", "price"),
    ],
)
def test_result_requires_exactly_one_price_comparison_dimension(
    dimensions: tuple[str, ...],
) -> None:
    result = _decision().ImageCompareDecisionFoundation().decide(
        _decision_input()
    )
    payload = result.model_dump()
    payload["comparison_dimensions"] = dimensions

    with pytest.raises(ValidationError, match="comparison dimensions"):
        type(result).model_validate(payload)
