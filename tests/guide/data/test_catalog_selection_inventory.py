from __future__ import annotations

import json
from pathlib import Path

from tools.guide_data.catalog_selection_inventory import (
    build_catalog_selection_inventory,
)


def _product(
    product_id: int,
    *,
    brand: str,
    category: str,
    identity: str,
    price: float,
    ingredients: str | None = None,
    texture: str | None = None,
) -> dict[str, object]:
    def known(value: object) -> dict[str, object]:
        return {
            "resolved_state": "known" if value is not None else "unknown",
            "value": value,
        }

    return {
        "product_id": product_id,
        "fields": {
            "brand": known(brand),
            "category": known(category),
            "product_identity": known(identity),
            "price": known(price),
            "ingredients_present": known(ingredients),
            "texture": known(texture),
        },
    }


def test_inventory_normalizes_brand_variants_and_flags_series_review() -> None:
    inventory = build_catalog_selection_inventory(
        products=(
            _product(
                11,
                brand="示例牌/Example",
                category="精华",
                identity="示例修护精华",
                price=299,
            ),
            _product(
                12,
                brand="示例牌（Example）",
                category="精华",
                identity="示例抗氧精华",
                price=399,
            ),
            _product(
                13,
                brand="另一个品牌",
                category="防晒",
                identity="无",
                price=99,
            ),
        ),
    )
    by_id = {
        row["product_id"]: row for row in inventory["products"]
    }

    assert by_id[11]["brand_key"] == "示例牌"
    assert by_id[12]["brand_key"] == "示例牌"
    assert by_id[11]["selection_lane"] == "series_or_variant_review"
    assert by_id[12]["selection_lane"] == "series_or_variant_review"
    assert by_id[13]["selection_lane"] == "identity_review_required"
    assert by_id[13]["review_reasons"] == [
        "canonical_product_identity_unusable",
    ]
    assert by_id[11]["price_band"] == "100-299"
    assert by_id[11]["missing_data_fields"] == [
        "net_content",
        "ingredients_present",
        "texture",
        "efficacy",
    ]


def test_inventory_does_not_mark_known_list_values_as_missing() -> None:
    product = _product(
        11,
        brand="示例牌",
        category="精华",
        identity="示例修护精华",
        price=299,
        ingredients=["神经酰胺", "甘油"],
    )

    inventory = build_catalog_selection_inventory(products=(product,))

    assert inventory["products"][0]["missing_data_fields"] == [
        "net_content",
        "texture",
        "efficacy",
    ]


def test_production_catalog_inventory_covers_all_products_without_selection() -> None:
    root = Path(__file__).resolve().parents[3]
    products = tuple(
        json.loads(line)
        for line in (
            root / "data/canonical/core_products_v1.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line
    )

    inventory = build_catalog_selection_inventory(products=products)

    assert inventory["product_count"] == 103
    assert len(inventory["products"]) == 103
    assert inventory["profile_counts"] == {
        "base_makeup": 19,
        "cleanser": 12,
        "color_makeup": 6,
        "fragrance": 3,
        "skincare": 51,
        "suncare": 12,
    }
    assert {
        row["product_id"]
        for row in inventory["products"]
        if row["selection_lane"] == "identity_review_required"
    } == {26, 100}
