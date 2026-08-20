from __future__ import annotations

import json
from pathlib import Path
import stat

import pytest

from app.guide.retrieval.category_fact_contracts import (
    category_field_registry,
)
from app.guide.retrieval.category_profiles import CategoryProfile
from tools.guide_data.report_pilot_field_coverage import (
    TARGET_PRODUCT_IDS,
    build_pilot_field_coverage,
    build_product_coverage,
)


ROOT = Path(__file__).resolve().parents[3]
CANONICAL_MANIFEST = ROOT / "data/canonical/core_products_v1_manifest.json"
CANONICAL_PRODUCTS = ROOT / "data/canonical/core_products_v1.jsonl"
CATEGORY_MANIFEST = (
    ROOT / "data/guide_category_facts/category_facts_v1_manifest.json"
)
REVIEW_MANIFEST = (
    ROOT
    / "data/guide_review_sources/"
    "approved_tmall_feed_reviews_v1_manifest.json"
)
CORE_FIELDS = {"product_identity", "brand", "category", "price"}


def _field(state: str, value: object = None) -> dict[str, object]:
    return {"resolved_state": state, "value": value}


def _product(
    *,
    product_id: int = 120,
    field_states: dict[str, str] | None = None,
    binding_states: dict[str, str] | None = None,
) -> dict[str, object]:
    states = field_states or {}
    bindings = binding_states or {}
    return {
        "bindings": {
            "item": _field(bindings.get("item", "unknown"), "item-secret"),
            "product": _field(
                bindings.get("product", "known"),
                "product-secret",
            ),
            "sku": _field(bindings.get("sku", "unknown"), "sku-secret"),
        },
        "fields": {
            "brand": _field(
                states.get("brand", "known"),
                "Jo Malone London/secret",
            ),
            "category": _field(
                states.get("category", "known"),
                "secret-category",
            ),
            "price": _field(states.get("price", "known"), 309.74),
            "product_identity": _field(
                states.get("product_identity", "known"),
                "secret-product-name",
            ),
            "longevity": _field(
                states.get("longevity", "unknown"),
                "secret-longevity",
            ),
            "texture": _field(
                states.get("texture", "unknown"),
                "secret-texture",
            ),
        },
        "product_id": product_id,
    }


def _assert_no_value_key(value: object) -> None:
    if isinstance(value, dict):
        assert "value" not in value
        for child in value.values():
            _assert_no_value_key(child)
    elif isinstance(value, list | tuple):
        for child in value:
            _assert_no_value_key(child)


def test_missing_optional_field_keeps_product_unknown() -> None:
    report = build_product_coverage(
        _product(field_states={"longevity": "unknown"}),
        profile=CategoryProfile.FRAGRANCE,
    )

    assert report["product_status"] == "retained"
    assert report["fields"]["longevity"] == {
        "action": "source_recovery",
        "state": "unknown",
    }


def test_optional_conflict_discards_candidate_but_keeps_product() -> None:
    report = build_product_coverage(
        _product(field_states={"longevity": "conflict"}),
        profile=CategoryProfile.FRAGRANCE,
    )

    assert report["product_status"] == "retained"
    assert report["fields"]["longevity"] == {
        "action": "discard_candidate",
        "state": "conflict",
    }


@pytest.mark.parametrize(
    "core_field",
    ["product_identity", "brand", "category", "price"],
)
def test_core_field_conflict_quarantines_whole_product(
    core_field: str,
) -> None:
    report = build_product_coverage(
        _product(field_states={core_field: "conflict"}),
        profile=CategoryProfile.FRAGRANCE,
    )

    assert report["product_status"] == "quarantine"
    public_key = (
        "identity" if core_field == "product_identity" else core_field
    )
    assert report["core"][public_key] == "conflict"


@pytest.mark.parametrize("binding", ["product", "item", "sku"])
def test_binding_conflict_quarantines_whole_product(
    binding: str,
) -> None:
    report = build_product_coverage(
        _product(binding_states={binding: "conflict"}),
        profile=CategoryProfile.FRAGRANCE,
    )

    assert report["product_status"] == "quarantine"
    assert report["bindings"][binding] == "conflict"


def test_report_never_copies_original_field_or_binding_values() -> None:
    report = build_product_coverage(
        _product(field_states={"longevity": "known"}),
        profile=CategoryProfile.FRAGRANCE,
    )

    _assert_no_value_key(report)
    serialized = json.dumps(report, ensure_ascii=False)
    assert "secret" not in serialized
    assert "309.74" not in serialized


def test_report_fields_come_from_profile_registry() -> None:
    report = build_product_coverage(
        _product(),
        profile=CategoryProfile.FRAGRANCE,
    )
    expected = {
        definition.key
        for definition in category_field_registry().for_profile(
            CategoryProfile.FRAGRANCE
        )
        if definition.key not in CORE_FIELDS
    }

    assert set(report["fields"]) == expected


def test_real_report_contains_exactly_fifteen_targets_without_values(
    tmp_path: Path,
) -> None:
    output = tmp_path / "pilot-field-coverage.json"

    result = build_pilot_field_coverage(
        canonical_manifest_path=CANONICAL_MANIFEST,
        canonical_products_path=CANONICAL_PRODUCTS,
        category_manifest_path=CATEGORY_MANIFEST,
        review_manifest_path=REVIEW_MANIFEST,
        output_path=output,
        product_ids=TARGET_PRODUCT_IDS,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert result.target_product_count == 15
    assert payload["target_product_count"] == 15
    assert {
        product["product_id"]
        for product in payload["products"]
    } == set(TARGET_PRODUCT_IDS)
    assert all(
        product["product_status"] == "retained"
        for product in payload["products"]
    )
    review_product = next(
        product
        for product in payload["products"]
        if product["product_id"] == 42
    )
    pilot_product = next(
        product
        for product in payload["products"]
        if product["product_id"] == 38
    )
    assert review_product["bindings"] == {
        "item": "known",
        "product": "known",
        "sku": "known",
    }
    assert pilot_product["bindings"] == {
        "item": "unknown",
        "product": "known",
        "sku": "unknown",
    }
    _assert_no_value_key(payload)
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
