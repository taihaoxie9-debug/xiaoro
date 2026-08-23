import pytest
from pydantic import ValidationError

from app.guide.presentation.card_display import (
    recommendation_card_display,
)
from app.guide.presentation.contracts import (
    CardDisplayContract,
    ProductCard,
)
from app.guide.presentation.sse_events import (
    CardDisplayContractEvent,
)
from app.guide.retrieval.category_profiles import CategoryProfile


def _card(product_id: int) -> ProductCard:
    return ProductCard(
        product_id=product_id,
        category_profile=CategoryProfile.SKINCARE,
        category_facts=(),
        name=None,
        brand=None,
        category=None,
        price=None,
        skin_match="unknown",
        matched_efficacies=[],
        fact_warnings=[],
    )


@pytest.mark.parametrize(
    ("mode", "ids", "reason"),
    [
        ("none", [], None),
        ("single", [91], "product"),
        ("single", [91], "recommendation"),
        ("recommendation", [91, 38], "recommendation"),
        ("recommendation", [55, 57, 54], "recommendation"),
        ("recommendation", [51, 52, 53, 54], "recommendation"),
        ("comparison", [53, 55], "comparison"),
        ("comparison", [53, 55, 57], "comparison"),
    ],
)
def test_card_display_contract_accepts_exact_visible_ids(
    mode,
    ids,
    reason,
) -> None:
    contract = CardDisplayContract(
        mode=mode,
        visible_product_ids=ids,
        max_cards=len(ids),
        reason=reason,
    )

    assert contract.visible_product_ids == tuple(ids)
    assert isinstance(contract.visible_product_ids, tuple)


def test_card_display_contract_is_detached_from_constructor_list() -> None:
    visible_ids = [91]
    contract = CardDisplayContract(
        mode="single",
        visible_product_ids=visible_ids,
        max_cards=1,
        reason="product",
    )

    visible_ids[0] = 99
    visible_ids.append(38)

    assert contract.visible_product_ids == (91,)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("mode", "comparison"),
        ("visible_product_ids", (99, 91)),
        ("max_cards", 2),
        ("reason", "comparison"),
    ],
)
def test_card_display_contract_rejects_field_replacement(
    field: str,
    replacement: object,
) -> None:
    contract = CardDisplayContract(
        mode="single",
        visible_product_ids=[91],
        max_cards=1,
        reason="product",
    )
    before = contract.model_dump(mode="json")

    with pytest.raises(ValidationError, match="frozen"):
        setattr(contract, field, replacement)

    assert contract.model_dump(mode="json") == before


def test_card_display_contract_rejects_nested_id_mutation() -> None:
    contract = CardDisplayContract(
        mode="comparison",
        visible_product_ids=[91, 38],
        max_cards=2,
        reason="comparison",
    )

    with pytest.raises(AttributeError):
        contract.visible_product_ids.append(99)
    with pytest.raises(TypeError):
        contract.visible_product_ids[0] = 99

    assert contract.visible_product_ids == (91, 38)


@pytest.mark.parametrize(
    ("mode", "ids", "reason"),
    [
        ("single", [91], "comparison"),
        ("recommendation", [91, 38], "product"),
        ("recommendation", [91, 38], "comparison"),
        ("comparison", [53, 55], "product"),
        ("comparison", [53, 55], "recommendation"),
    ],
)
def test_card_display_contract_rejects_illegal_mode_reason_pairs(
    mode,
    ids,
    reason,
) -> None:
    with pytest.raises(ValidationError):
        CardDisplayContract(
            mode=mode,
            visible_product_ids=ids,
            max_cards=len(ids),
            reason=reason,
        )


@pytest.mark.parametrize(
    "payload",
    [
        {
            "mode": "none",
            "visible_product_ids": [91],
            "max_cards": 1,
            "reason": None,
        },
        {
            "mode": "single",
            "visible_product_ids": [91, 38],
            "max_cards": 2,
            "reason": "product",
        },
        {
            "mode": "recommendation",
            "visible_product_ids": [55, 55],
            "max_cards": 2,
            "reason": "recommendation",
        },
        {
            "mode": "comparison",
            "visible_product_ids": [53],
            "max_cards": 1,
            "reason": "comparison",
        },
        {
            "mode": "recommendation",
            "visible_product_ids": [55, 57],
            "max_cards": 1,
            "reason": "recommendation",
        },
        {
            "mode": "comparison",
            "visible_product_ids": [51, 52, 53, 54],
            "max_cards": 4,
            "reason": "comparison",
        },
    ],
)
def test_card_display_contract_rejects_ambiguous_shapes(payload) -> None:
    with pytest.raises(ValidationError):
        CardDisplayContract(**payload)


@pytest.mark.parametrize(
    ("product_ids", "mode"),
    [
        ([], "none"),
        ([91], "single"),
        ([91, 38], "recommendation"),
        ([55, 57, 54], "recommendation"),
        ([51, 52, 53, 54], "recommendation"),
    ],
)
def test_recommendation_card_display_uses_exact_card_order(
    product_ids,
    mode,
) -> None:
    contract = recommendation_card_display(
        [_card(product_id) for product_id in product_ids]
    )

    assert contract.mode == mode
    assert contract.visible_product_ids == tuple(product_ids)
    assert contract.max_cards == len(product_ids)
    assert contract.reason == (
        None if not product_ids else "recommendation"
    )


def test_card_display_contract_event_is_typed_sse() -> None:
    event = CardDisplayContractEvent(
        data=recommendation_card_display([_card(91), _card(38)])
    )

    assert event.model_dump(mode="json") == {
        "event": "card_display_contract",
        "data": {
            "mode": "recommendation",
            "visible_product_ids": [91, 38],
            "max_cards": 2,
            "reason": "recommendation",
        },
    }
