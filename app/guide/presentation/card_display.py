from collections.abc import Sequence

from app.guide.presentation.contracts import (
    CardDisplayContract,
    ProductCard,
)


def recommendation_card_display(
    cards: Sequence[ProductCard],
) -> CardDisplayContract:
    product_ids = [card.product_id for card in cards]
    if not product_ids:
        return CardDisplayContract(
            mode="none",
            visible_product_ids=[],
            max_cards=0,
            reason=None,
        )
    return CardDisplayContract(
        mode=(
            "single"
            if len(product_ids) == 1
            else "recommendation"
        ),
        visible_product_ids=product_ids,
        max_cards=len(product_ids),
        reason="recommendation",
    )


def comparison_card_display(
    cards: Sequence[ProductCard],
) -> CardDisplayContract:
    product_ids = [card.product_id for card in cards]
    if not 2 <= len(product_ids) <= 3:
        raise ValueError("comparison requires two or three cards")
    return CardDisplayContract(
        mode="comparison",
        visible_product_ids=product_ids,
        max_cards=len(product_ids),
        reason="comparison",
    )


def single_product_card_display(
    card: ProductCard,
) -> CardDisplayContract:
    return CardDisplayContract(
        mode="single",
        visible_product_ids=[card.product_id],
        max_cards=1,
        reason="product",
    )
