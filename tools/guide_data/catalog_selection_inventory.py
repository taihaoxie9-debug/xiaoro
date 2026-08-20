"""Build a review-only portfolio inventory from Canonical product records."""

from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping, Sequence

from app.guide.retrieval.category_profiles import (
    CategoryProfile,
    category_profile_for,
)
from tools.guide_data.smzdm_capture_queue import (
    CAPTURE_PRIORITY_FIELDS,
)


_SCHEMA_VERSION = "catalog-selection-inventory-v1"
_UNUSABLE_IDENTITIES = frozenset({
    "",
    "-",
    "--",
    "n/a",
    "na",
    "无",
    "未知",
    "000",
})
_CJK = re.compile(r"[\u3400-\u9fff]+")
_ASCII = re.compile(r"[a-z0-9]+")


class CatalogSelectionInventoryError(ValueError):
    """Raised when a Canonical product cannot be included in the inventory."""


def build_catalog_selection_inventory(
    *,
    products: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Return review lanes without selecting, dropping, or promoting products."""
    provisional: list[dict[str, object]] = []
    seen_ids: set[int] = set()
    for product in products:
        product_id, fields = _validate_product(product)
        if product_id in seen_ids:
            raise CatalogSelectionInventoryError(
                "canonical product IDs must be unique"
            )
        seen_ids.add(product_id)
        category = _known_text(fields.get("category"))
        brand = _known_text(fields.get("brand"))
        identity = _known_text(fields.get("product_identity"))
        row: dict[str, object] = {
            "product_id": product_id,
            "category_profile": None,
            "brand_key": _brand_key(brand),
            "canonical_identity": identity,
            "price_band": _price_band(fields.get("price")),
            "missing_data_fields": [],
            "selection_lane": "candidate_for_retention",
            "review_reasons": [],
        }
        if category is None:
            row["selection_lane"] = "category_review_required"
            row["review_reasons"] = [
                "canonical_category_unusable",
            ]
            provisional.append(row)
            continue
        try:
            profile = category_profile_for(category)
        except KeyError:
            row["selection_lane"] = "category_review_required"
            row["review_reasons"] = [
                "canonical_category_unmapped",
            ]
            provisional.append(row)
            continue
        row["category_profile"] = profile.value
        if identity is None or _identity_is_unusable(identity):
            row["selection_lane"] = "identity_review_required"
            row["review_reasons"] = [
                "canonical_product_identity_unusable",
            ]
            provisional.append(row)
            continue
        row["missing_data_fields"] = [
            field_key
            for field_key in CAPTURE_PRIORITY_FIELDS[profile]
            if not _has_known_value(fields.get(field_key))
        ]
        provisional.append(row)

    series_counts = Counter(
        (
            row["category_profile"],
            row["brand_key"],
        )
        for row in provisional
        if (
            row["selection_lane"] == "candidate_for_retention"
            and isinstance(row["category_profile"], str)
            and isinstance(row["brand_key"], str)
            and row["brand_key"]
        )
    )
    for row in provisional:
        key = (row["category_profile"], row["brand_key"])
        if (
            row["selection_lane"] == "candidate_for_retention"
            and series_counts[key] > 1
        ):
            row["selection_lane"] = "series_or_variant_review"
            row["review_reasons"] = [
                "same_brand_profile_multiple_products",
            ]

    rows = sorted(provisional, key=lambda row: int(row["product_id"]))
    profile_counts = Counter(
        row["category_profile"]
        for row in rows
        if isinstance(row["category_profile"], str)
    )
    lane_counts = Counter(str(row["selection_lane"]) for row in rows)
    return {
        "schema_version": _SCHEMA_VERSION,
        "product_count": len(rows),
        "profile_counts": dict(sorted(profile_counts.items())),
        "selection_lane_counts": dict(sorted(lane_counts.items())),
        "products": rows,
    }


def _validate_product(
    product: Mapping[str, object],
) -> tuple[int, Mapping[str, object]]:
    product_id = product.get("product_id")
    fields = product.get("fields")
    if (
        type(product_id) is not int
        or product_id < 1
        or not isinstance(fields, Mapping)
    ):
        raise CatalogSelectionInventoryError(
            "canonical product must have positive product_id and fields"
        )
    return product_id, fields


def _known_text(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    if value.get("resolved_state") != "known":
        return None
    raw = value.get("value")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw.strip()


def _has_known_value(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    if value.get("resolved_state") != "known":
        return False
    raw = value.get("value")
    if raw is None:
        return False
    if isinstance(raw, str):
        return bool(raw.strip())
    if isinstance(raw, Mapping):
        return bool(raw)
    if isinstance(raw, (list, tuple, set, frozenset)):
        return bool(raw)
    return True


def _brand_key(brand: str | None) -> str:
    if brand is None:
        return ""
    cjk = "".join(_CJK.findall(brand))
    if cjk:
        return cjk
    return "".join(_ASCII.findall(brand.casefold()))


def _identity_is_unusable(identity: str) -> bool:
    return identity.casefold() in _UNUSABLE_IDENTITIES


def _price_band(field: object) -> str:
    if not isinstance(field, Mapping):
        return "unknown"
    if field.get("resolved_state") != "known":
        return "unknown"
    try:
        price = Decimal(str(field.get("value")))
    except (InvalidOperation, TypeError, ValueError):
        return "unknown"
    if not price.is_finite() or price < 0:
        return "unknown"
    if price < 100:
        return "0-99"
    if price < 300:
        return "100-299"
    if price < 600:
        return "300-599"
    if price < 1000:
        return "600-999"
    return "1000+"


def _load_products(path: Path) -> tuple[dict[str, object], ...]:
    try:
        return tuple(
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogSelectionInventoryError(
            "canonical products file is invalid"
        ) from exc


def _write_inventory(
    *,
    source_path: Path,
    output_path: Path,
) -> dict[str, object]:
    source = source_path.read_bytes()
    inventory = build_catalog_selection_inventory(
        products=_load_products(source_path),
    )
    payload = {
        **inventory,
        "canonical_products_sha256": hashlib.sha256(source).hexdigest(),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a review-only Canonical product selection inventory."
    )
    parser.add_argument("--canonical-products", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    inventory = _write_inventory(
        source_path=args.canonical_products,
        output_path=args.output,
    )
    print(json.dumps({
        "product_count": inventory["product_count"],
        "selection_lane_counts": inventory["selection_lane_counts"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
