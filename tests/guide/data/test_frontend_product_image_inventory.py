from __future__ import annotations

import json
from pathlib import Path

from tools.guide_data.audit_frontend_product_images import (
    audit_frontend_product_images,
)


ROOT = Path(__file__).resolve().parents[3]
INVENTORY = ROOT / (
    "docs/audits/frontend-integration/"
    "product_image_inventory_v1.json"
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def test_frontend_product_image_inventory_covers_canonical_catalog() -> None:
    report = json.loads(INVENTORY.read_text(encoding="utf-8"))

    assert report["schema_version"] == (
        "guide-frontend-product-image-inventory-v1"
    )
    assert report["canonical_seed_changed"] is False
    assert report["summary"] == {
        "broken": 0,
        "mismatched": 0,
        "missing": 0,
        "ok": 103,
        "product_count": 103,
    }
    assert [row["product_id"] for row in report["products"]] == sorted(
        row["product_id"] for row in report["products"]
    )
    assert all(row["status"] == "ok" for row in report["products"])
    assert all(
        row["source_kind"] == "fresh_content_addressed_asset"
        for row in report["products"]
    )


def test_published_inventory_matches_deterministic_regeneration() -> None:
    published = json.loads(INVENTORY.read_text(encoding="utf-8"))
    regenerated = audit_frontend_product_images(
        repo_root=ROOT,
        canonical_products_path=(
            ROOT / "data/canonical/core_products_v1.jsonl"
        ),
        assets_path=(
            ROOT / "data/canonical/seed_product_images_v1.jsonl"
        ),
        manifest_path=(
            ROOT
            / "data/canonical/seed_product_images_v1_manifest.json"
        ),
    )

    assert _canonical_json(regenerated) == _canonical_json(published)
