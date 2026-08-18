from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError


SCHEMA_VERSION = "guide-frontend-product-image-inventory-v1"
_UNUSABLE_IDENTITIES = {"", "无", "未知", "unknown", "none"}


def audit_frontend_product_images(
    *,
    repo_root: str | Path,
    canonical_products_path: str | Path,
    assets_path: str | Path,
    manifest_path: str | Path,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    canonical_path = Path(canonical_products_path)
    assets_file = Path(assets_path)
    manifest_file = Path(manifest_path)
    canonical_rows = _read_jsonl(canonical_path)
    asset_rows = _read_jsonl(assets_file)
    manifest = _read_json(manifest_file)
    _validate_asset_manifest(
        manifest,
        assets_file=assets_file,
        asset_rows=asset_rows,
    )

    assets_by_id = {
        _positive_id(row.get("product_id")): row
        for row in asset_rows
    }
    if len(assets_by_id) != len(asset_rows):
        raise ValueError("frontend image assets require unique product IDs")

    products = []
    for canonical in sorted(
        canonical_rows,
        key=lambda row: _positive_id(row.get("product_id")),
    ):
        product_id = _positive_id(canonical.get("product_id"))
        products.append(
            _audit_product(
                root=root,
                canonical=canonical,
                asset=assets_by_id.get(product_id),
            )
        )
    statuses = {
        status: sum(row["status"] == status for row in products)
        for status in ("broken", "mismatched", "missing", "ok")
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "canonical_seed_changed": False,
        "source_files": {
            "canonical_products_sha256": _file_sha(canonical_path),
            "image_assets_sha256": _file_sha(assets_file),
            "image_manifest_sha256": _file_sha(manifest_file),
        },
        "summary": {
            **statuses,
            "product_count": len(products),
        },
        "orphan_asset_ids": sorted(
            set(assets_by_id)
            - {
                _positive_id(row.get("product_id"))
                for row in canonical_rows
            }
        ),
        "products": products,
    }
    report["inventory_sha256"] = hashlib.sha256(
        _canonical_json(products).encode("utf-8")
    ).hexdigest()
    return report


def _audit_product(
    *,
    root: Path,
    canonical: dict[str, Any],
    asset: dict[str, Any] | None,
) -> dict[str, Any]:
    product_id = _positive_id(canonical.get("product_id"))
    identity = _canonical_identity(canonical)
    base = {
        "product_id": product_id,
        "canonical_identity": identity,
        "image_path": None,
        "image_url": None,
        "media_type": None,
        "source_kind": None,
        "source_url": None,
        "source_sha256": None,
        "file_sha256": None,
        "expected_bytes": None,
        "actual_bytes": None,
        "pixel_dimensions": None,
        "review_status": "not_reviewed",
        "identity_review": "unbound",
        "status": "missing",
    }
    if asset is None:
        return base
    relative_path = asset.get("relative_path")
    if not isinstance(relative_path, str) or not relative_path:
        return {**base, "status": "mismatched"}
    image_path = (root / relative_path).resolve()
    row = {
        **base,
        "image_path": relative_path,
        "image_url": asset.get("image_url"),
        "media_type": asset.get("media_type"),
        "source_kind": "fresh_content_addressed_asset",
        "source_url": _source_url(asset.get("image_url")),
        "source_sha256": asset.get("source_image_sha256"),
        "expected_bytes": asset.get("bytes"),
        "identity_review": "bound_by_product_id_manifest",
    }
    if not image_path.is_relative_to(root) or not image_path.is_file():
        return row
    try:
        payload = image_path.read_bytes()
    except OSError:
        return row
    actual_sha = hashlib.sha256(payload).hexdigest()
    row["actual_bytes"] = len(payload)
    row["file_sha256"] = actual_sha
    if (
        asset.get("bytes") != len(payload)
        or asset.get("source_image_sha256") != actual_sha
    ):
        row["status"] = "mismatched"
        return row
    try:
        with Image.open(image_path) as image:
            image.load()
            width, height = image.size
    except (OSError, UnidentifiedImageError):
        row["status"] = "broken"
        return row
    if width < 1 or height < 1:
        row["status"] = "broken"
        return row
    row["pixel_dimensions"] = {
        "height": height,
        "width": width,
    }
    row["review_status"] = "approved_manifest_lock"
    row["status"] = "ok"
    return row


def _canonical_identity(row: dict[str, Any]) -> str:
    fields = row.get("fields")
    if not isinstance(fields, dict):
        return f"商品 {row.get('product_id')}"
    identity = _known_field(fields.get("product_identity"))
    if identity.casefold() not in _UNUSABLE_IDENTITIES:
        return identity
    brand = _known_field(fields.get("brand"))
    category = _known_field(fields.get("category"))
    fallback = " ".join(value for value in (brand, category) if value)
    return fallback or f"商品 {row.get('product_id')}"


def _known_field(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    if value.get("resolved_state") != "known":
        return ""
    raw = value.get("value")
    return str(raw).strip() if raw is not None else ""


def _source_url(image_url: object) -> str | None:
    if not isinstance(image_url, str):
        return None
    stem = Path(image_url).stem
    item_id = stem.split("_")[-1]
    if not item_id.isdigit():
        return None
    if stem.startswith("jd_"):
        return f"https://item.jd.com/{item_id}.html"
    if stem.startswith("tmall_"):
        return f"https://detail.tmall.com/item.htm?id={item_id}"
    if stem.startswith("taobao_"):
        return f"https://item.taobao.com/item.htm?id={item_id}"
    return None


def _validate_asset_manifest(
    manifest: dict[str, Any],
    *,
    assets_file: Path,
    asset_rows: list[dict[str, Any]],
) -> None:
    if manifest.get("schema_version") != "seed-product-images-v1":
        raise ValueError("unsupported frontend image manifest")
    if manifest.get("products_file") != assets_file.name:
        raise ValueError("frontend image manifest file mismatch")
    if manifest.get("product_count") != len(asset_rows):
        raise ValueError("frontend image manifest count mismatch")
    if manifest.get("products_sha256") != _file_sha(assets_file):
        raise ValueError("frontend image manifest SHA mismatch")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line:
            raise ValueError(f"blank JSONL line {line_number}: {path}")
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"invalid JSONL row {line_number}: {path}")
        rows.append(value)
    return rows


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"invalid JSON object: {path}")
    return value


def _positive_id(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError("product ID must be a positive integer")
    return value


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--canonical-products",
        default="data/canonical/core_products_v1.jsonl",
    )
    parser.add_argument(
        "--assets",
        default="data/canonical/seed_product_images_v1.jsonl",
    )
    parser.add_argument(
        "--manifest",
        default=(
            "data/canonical/seed_product_images_v1_manifest.json"
        ),
    )
    parser.add_argument(
        "--output",
        default=(
            "docs/audits/frontend-integration/"
            "product_image_inventory_v1.json"
        ),
    )
    args = parser.parse_args()
    report = audit_frontend_product_images(
        repo_root=args.repo_root,
        canonical_products_path=args.canonical_products,
        assets_path=args.assets,
        manifest_path=args.manifest,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_canonical_json(report) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

