from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

import pytest

from app.guide.retrieval.category_profiles import (
    CategoryProfile,
    category_profile_for,
)
from app.guide.retrieval.category_taxonomy import raw_category_mapping


CANONICAL_PRODUCTS = Path("data/canonical/core_products_v1.jsonl")

EXPECTED_RAW_CATEGORIES = {
    "乳液": CategoryProfile.SKINCARE,
    "乳霜": CategoryProfile.SKINCARE,
    "爽肤水": CategoryProfile.SKINCARE,
    "眼部精华": CategoryProfile.SKINCARE,
    "眼霜": CategoryProfile.SKINCARE,
    "精华": CategoryProfile.SKINCARE,
    "精华水": CategoryProfile.SKINCARE,
    "精华液": CategoryProfile.SKINCARE,
    "面膜": CategoryProfile.SKINCARE,
    "面霜": CategoryProfile.SKINCARE,
    "防晒": CategoryProfile.SUNCARE,
    "防晒乳": CategoryProfile.SUNCARE,
    "防晒乳液": CategoryProfile.SUNCARE,
    "防晒隔离": CategoryProfile.SUNCARE,
    "防晒霜": CategoryProfile.SUNCARE,
    "妆前乳": CategoryProfile.BASE_MAKEUP,
    "散粉": CategoryProfile.BASE_MAKEUP,
    "气垫": CategoryProfile.BASE_MAKEUP,
    "气垫粉底": CategoryProfile.BASE_MAKEUP,
    "气垫粉底液": CategoryProfile.BASE_MAKEUP,
    "粉底液": CategoryProfile.BASE_MAKEUP,
    "蜜粉": CategoryProfile.BASE_MAKEUP,
    "遮瑕膏": CategoryProfile.BASE_MAKEUP,
    "单色眼影": CategoryProfile.COLOR_MAKEUP,
    "口红": CategoryProfile.COLOR_MAKEUP,
    "唇膏": CategoryProfile.COLOR_MAKEUP,
    "腮红": CategoryProfile.COLOR_MAKEUP,
    "卸妆": CategoryProfile.CLEANSER,
    "卸妆水/洁肤液": CategoryProfile.CLEANSER,
    "卸妆洁肤液/卸妆水": CategoryProfile.CLEANSER,
    "卸妆膏": CategoryProfile.CLEANSER,
    "洁面/清洁": CategoryProfile.CLEANSER,
    "洁面乳/泡沫洁面乳": CategoryProfile.CLEANSER,
    "洁面乳/洁面泡沫": CategoryProfile.CLEANSER,
    "洁面泡沫": CategoryProfile.CLEANSER,
    "洁面霜/洁面": CategoryProfile.CLEANSER,
    "洁颜油/卸妆油": CategoryProfile.CLEANSER,
    "洁颜霜/卸妆膏": CategoryProfile.CLEANSER,
    "香水": CategoryProfile.FRAGRANCE,
}


def _canonical_categories() -> list[str]:
    return [
        json.loads(line)["fields"]["category"]["value"]
        for line in CANONICAL_PRODUCTS.read_text(encoding="utf-8").splitlines()
    ]


def test_all_six_profiles_are_stable() -> None:
    assert {item.value for item in CategoryProfile} == {
        "skincare",
        "suncare",
        "base_makeup",
        "color_makeup",
        "cleanser",
        "fragrance",
    }


def test_all_39_canonical_categories_map_exactly_once() -> None:
    mapping = raw_category_mapping()
    canonical_categories = _canonical_categories()

    assert mapping == EXPECTED_RAW_CATEGORIES
    assert len(mapping) == 39
    assert set(mapping) == set(canonical_categories)
    assert all(category_profile_for(value) in CategoryProfile for value in mapping)


def test_canonical_product_counts_match_each_profile() -> None:
    counts = Counter(
        category_profile_for(category) for category in _canonical_categories()
    )

    assert counts == {
        CategoryProfile.SKINCARE: 51,
        CategoryProfile.SUNCARE: 12,
        CategoryProfile.BASE_MAKEUP: 19,
        CategoryProfile.COLOR_MAKEUP: 6,
        CategoryProfile.CLEANSER: 12,
        CategoryProfile.FRAGRANCE: 3,
    }


def test_raw_category_mapping_is_immutable() -> None:
    mapping = raw_category_mapping()

    with pytest.raises(TypeError):
        mapping["美容仪"] = CategoryProfile.SKINCARE  # type: ignore[index]


def test_unknown_category_fails_closed() -> None:
    with pytest.raises(KeyError):
        category_profile_for("美容仪")
