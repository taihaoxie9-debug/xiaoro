from __future__ import annotations

import pytest

from tools.guide_data.selected_catalog import (
    SelectedCatalogError,
    build_selected_catalog,
)


def _inventory() -> dict[str, object]:
    return {
        "schema_version": "catalog-selection-inventory-v1",
        "products": [
            {
                "product_id": 11,
                "category_profile": "skincare",
                "selection_lane": "candidate_for_retention",
            },
            {
                "product_id": 12,
                "category_profile": "skincare",
                "selection_lane": "identity_review_required",
            },
            {
                "product_id": 13,
                "category_profile": "suncare",
                "selection_lane": "series_or_variant_review",
            },
        ],
    }


def test_selected_catalog_keeps_explicit_decisions_and_unfilled_slots() -> None:
    catalog = build_selected_catalog(
        inventory=_inventory(),
        decisions=(
            {
                "product_id": 11,
                "disposition": "retain",
                "portfolio_role": "barrier_serum",
                "sku_scope": "single_product",
                "rationale": "保留修护精华路线。",
            },
            {
                "product_id": 12,
                "disposition": "needs_identity_resolution",
                "portfolio_role": None,
                "sku_scope": None,
                "rationale": "Canonical 商品身份不可用。",
            },
            {
                "product_id": 13,
                "disposition": "retain",
                "portfolio_role": "daily_sunscreen",
                "sku_scope": "single_product",
                "rationale": "保留日常防晒路线。",
            },
        ),
        target_quotas={"skincare": 2, "suncare": 1},
    )

    assert [
        row["product_id"] for row in catalog["selected_products"]
    ] == [11, 13]
    assert catalog["selected_count"] == 2
    assert catalog["unfilled_slots"] == {
        "skincare": 1,
        "suncare": 0,
    }
    assert catalog["needs_identity_resolution"] == [12]


def test_selected_catalog_rejects_retaining_ambiguous_identity() -> None:
    with pytest.raises(
        SelectedCatalogError,
        match="identity_review_required product cannot be retained",
    ):
        build_selected_catalog(
            inventory=_inventory(),
            decisions=(
                {
                    "product_id": 11,
                    "disposition": "retain",
                    "portfolio_role": "barrier_serum",
                    "sku_scope": "single_product",
                    "rationale": "保留修护精华路线。",
                },
                {
                    "product_id": 12,
                    "disposition": "retain",
                    "portfolio_role": "unknown",
                    "sku_scope": "single_product",
                    "rationale": "不应允许。",
                },
                {
                    "product_id": 13,
                    "disposition": "exclude_from_capture",
                    "portfolio_role": None,
                    "sku_scope": None,
                    "rationale": "不进入本轮。",
                },
            ),
            target_quotas={"skincare": 2, "suncare": 1},
        )
