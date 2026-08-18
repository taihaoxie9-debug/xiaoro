from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from tools.guide_data.audit_frontend_product_images import (
    audit_frontend_product_images,
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _write_fixture(root: Path) -> tuple[Path, Path, Path]:
    image_path = root / "app/static/images/products/jd_v3_123.png"
    image_path.parent.mkdir(parents=True)
    Image.new("RGB", (64, 48), color=(120, 80, 90)).save(
        image_path,
        format="PNG",
    )
    payload = image_path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    canonical_path = root / "data/canonical/core.jsonl"
    canonical_path.parent.mkdir(parents=True)
    canonical_path.write_text(
        _canonical_json(
            {
                "product_id": 7,
                "fields": {
                    "product_identity": {
                        "resolved_state": "known",
                        "value": "测试商品",
                    },
                    "brand": {
                        "resolved_state": "known",
                        "value": "测试品牌",
                    },
                    "category": {
                        "resolved_state": "known",
                        "value": "面霜",
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assets_path = root / "data/canonical/assets.jsonl"
    asset_row = {
        "bytes": len(payload),
        "image_url": "/static/images/products/jd_v3_123.png",
        "media_type": "image/png",
        "product_id": 7,
        "relative_path": (
            "app/static/images/products/jd_v3_123.png"
        ),
        "source_image_sha256": digest,
    }
    assets_text = _canonical_json(asset_row) + "\n"
    assets_path.write_text(assets_text, encoding="utf-8")
    manifest_path = root / "data/canonical/assets_manifest.json"
    manifest_path.write_text(
        _canonical_json(
            {
                "product_count": 1,
                "products_file": assets_path.name,
                "products_sha256": hashlib.sha256(
                    assets_text.encode("utf-8")
                ).hexdigest(),
                "schema_version": "seed-product-images-v1",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return canonical_path, assets_path, manifest_path


def test_audit_records_identity_hash_dimensions_and_source(tmp_path) -> None:
    canonical, assets, manifest = _write_fixture(tmp_path)

    report = audit_frontend_product_images(
        repo_root=tmp_path,
        canonical_products_path=canonical,
        assets_path=assets,
        manifest_path=manifest,
    )

    assert report["summary"] == {
        "broken": 0,
        "mismatched": 0,
        "missing": 0,
        "ok": 1,
        "product_count": 1,
    }
    assert report["canonical_seed_changed"] is False
    row = report["products"][0]
    assert row["product_id"] == 7
    assert row["canonical_identity"] == "测试商品"
    assert row["source_kind"] == "fresh_content_addressed_asset"
    assert row["source_url"] == "https://item.jd.com/123.html"
    assert row["source_sha256"] == row["file_sha256"]
    assert row["pixel_dimensions"] == {"height": 48, "width": 64}
    assert row["review_status"] == "approved_manifest_lock"
    assert row["identity_review"] == "bound_by_product_id_manifest"
    assert row["status"] == "ok"


def test_audit_is_byte_deterministic(tmp_path) -> None:
    canonical, assets, manifest = _write_fixture(tmp_path)

    first = audit_frontend_product_images(
        repo_root=tmp_path,
        canonical_products_path=canonical,
        assets_path=assets,
        manifest_path=manifest,
    )
    second = audit_frontend_product_images(
        repo_root=tmp_path,
        canonical_products_path=canonical,
        assets_path=assets,
        manifest_path=manifest,
    )

    assert _canonical_json(first) == _canonical_json(second)
