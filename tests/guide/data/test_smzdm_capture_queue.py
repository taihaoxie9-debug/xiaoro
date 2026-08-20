from __future__ import annotations

import json
from pathlib import Path

from tools.guide_data.smzdm_capture_queue import (
    build_capture_queue,
    build_capture_queue_for_scope,
)


def _product(
    product_id: int,
    *,
    category: str,
    identity: str,
    ingredients: str | None = None,
    texture: str | None = None,
) -> dict[str, object]:
    def field(value: object) -> dict[str, object]:
        return {
            "resolved_state": "known" if value is not None else "unknown",
            "value": value,
        }

    return {
        "product_id": product_id,
        "fields": {
            "brand": field("示例品牌"),
            "category": field(category),
            "product_identity": field(identity),
            "ingredients_present": field(ingredients),
            "texture": field(texture),
        },
    }


def test_queue_keeps_ambiguous_identity_out_of_automated_capture() -> None:
    queue = build_capture_queue(
        products=(
            _product(
                11,
                category="精华",
                identity="示例修护精华",
            ),
            _product(
                12,
                category="精华",
                identity="无",
            ),
            _product(
                13,
                category="防晒",
                identity="示例防晒乳",
            ),
        ),
        target_count=2,
    )

    assert [row["canonical_product_id"] for row in queue["targets"]] == [
        11,
        13,
    ]
    assert queue["manual_identity_resolution"] == [
        {
            "canonical_product_id": 12,
            "reason": "canonical_product_identity_unusable",
        },
    ]
    assert queue["targets"][0]["missing_fields"] == [
        "net_content",
        "ingredients_present",
        "texture",
        "efficacy",
    ]
    assert queue["targets"][1]["category_profile"] == "suncare"
    assert queue["targets"][1]["missing_fields"] == [
        "net_content",
        "spf_pa",
        "texture",
        "water_resistance",
    ]


def test_queue_does_not_requeue_known_list_values() -> None:
    product = _product(
        11,
        category="精华",
        identity="示例修护精华",
        ingredients=["神经酰胺", "甘油"],
    )

    queue = build_capture_queue(products=(product,), target_count=1)

    assert queue["targets"][0]["missing_fields"] == [
        "net_content",
        "texture",
        "efficacy",
    ]


def test_production_catalog_builds_stratified_eighty_product_queue() -> None:
    root = Path(__file__).resolve().parents[3]
    products = tuple(
        json.loads(line)
        for line in (
            root / "data/canonical/core_products_v1.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line
    )

    queue = build_capture_queue(products=products, target_count=80)
    target_profiles = {
        row["category_profile"] for row in queue["targets"]
    }

    assert queue["target_count"] == 80
    assert len(queue["targets"]) == 80
    assert len({
        row["canonical_product_id"] for row in queue["targets"]
    }) == 80
    assert target_profiles == {
        "skincare",
        "suncare",
        "base_makeup",
        "color_makeup",
        "cleanser",
        "fragrance",
    }
    assert all(
        row["search_query"].endswith("什么值得买 商品百科")
        for row in queue["targets"]
    )
    assert all(
        row["missing_fields"] for row in queue["targets"]
    )


def test_capture_queue_only_consumes_retained_scope_products() -> None:
    products = (
        _product(
            11,
            category="精华",
            identity="示例修护精华",
        ),
        _product(
            12,
            category="精华",
            identity="示例抗氧精华",
        ),
    )
    scope = {
        "selected_products": [
            {
                "product_id": 12,
                "portfolio_role": "antioxidant_serum",
                "sku_scope": "single_product",
            }
        ]
    }

    queue = build_capture_queue_for_scope(
        products=products,
        scope=scope,
    )

    assert [row["canonical_product_id"] for row in queue["targets"]] == [12]
    assert queue["targets"][0]["portfolio_role"] == "antioxidant_serum"
    assert queue["targets"][0]["sku_scope"] == "single_product"
