"""Build a category-balanced SMZDM capture queue from Canonical coverage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.guide.retrieval.category_profiles import (
    CategoryProfile,
    category_profile_for,
)


_SCHEMA_VERSION = "smzdm-capture-queue-v1"
_PROFILE_ORDER = (
    CategoryProfile.SKINCARE,
    CategoryProfile.SUNCARE,
    CategoryProfile.BASE_MAKEUP,
    CategoryProfile.COLOR_MAKEUP,
    CategoryProfile.CLEANSER,
    CategoryProfile.FRAGRANCE,
)
CAPTURE_PRIORITY_FIELDS = {
    CategoryProfile.SKINCARE: (
        "net_content",
        "ingredients_present",
        "texture",
        "efficacy",
    ),
    CategoryProfile.SUNCARE: (
        "net_content",
        "spf_pa",
        "texture",
        "water_resistance",
    ),
    CategoryProfile.BASE_MAKEUP: (
        "net_content",
        "shade",
        "finish",
        "texture",
    ),
    CategoryProfile.COLOR_MAKEUP: (
        "net_content",
        "shade",
        "color_family",
        "finish",
    ),
    CategoryProfile.CLEANSER: (
        "net_content",
        "ingredients_present",
        "cleansing_power",
        "texture",
    ),
    CategoryProfile.FRAGRANCE: (
        "net_content",
        "concentration",
        "top_notes",
        "heart_notes",
        "base_notes",
    ),
}
_UNUSABLE_IDENTITY_VALUES = frozenset({
    "",
    "-",
    "--",
    "n/a",
    "na",
    "无",
    "未知",
    "000",
})


class SmzdmCaptureQueueError(ValueError):
    """Raised when Canonical rows cannot form an auditable capture queue."""


def build_capture_queue(
    *,
    products: Sequence[Mapping[str, object]],
    target_count: int,
) -> dict[str, object]:
    """Return high-coverage-gap targets without fetching or promoting data."""
    if type(target_count) is not int or target_count < 1:
        raise SmzdmCaptureQueueError(
            "target_count must be a positive integer"
        )
    candidates: dict[CategoryProfile, list[dict[str, object]]] = {
        profile: [] for profile in _PROFILE_ORDER
    }
    manual_identity_resolution: list[dict[str, object]] = []
    seen_ids: set[int] = set()

    for product in products:
        product_id, fields = _validate_product(product)
        if product_id in seen_ids:
            raise SmzdmCaptureQueueError(
                "canonical product IDs must be unique"
            )
        seen_ids.add(product_id)
        identity = _known_text(fields.get("product_identity"))
        if identity is None or _identity_is_unusable(identity):
            manual_identity_resolution.append({
                "canonical_product_id": product_id,
                "reason": "canonical_product_identity_unusable",
            })
            continue
        category = _known_text(fields.get("category"))
        if category is None:
            manual_identity_resolution.append({
                "canonical_product_id": product_id,
                "reason": "canonical_category_unusable",
            })
            continue
        try:
            profile = category_profile_for(category)
        except KeyError:
            manual_identity_resolution.append({
                "canonical_product_id": product_id,
                "reason": "canonical_category_unmapped",
            })
            continue
        missing_fields = [
            key
            for key in CAPTURE_PRIORITY_FIELDS[profile]
            if not _has_known_value(fields.get(key))
        ]
        if not missing_fields:
            continue
        brand = _known_text(fields.get("brand")) or ""
        candidates[profile].append({
            "canonical_product_id": product_id,
            "category_profile": profile.value,
            "canonical_product_identity": identity,
            "missing_fields": missing_fields,
            "search_query": _search_query(brand, identity),
        })

    effective_target_count = min(
        target_count,
        sum(len(rows) for rows in candidates.values()),
    )
    allocations = _allocate_profiles(
        candidates=candidates,
        target_count=effective_target_count,
    )
    selected: list[dict[str, object]] = []
    selected_ids: set[int] = set()
    for profile in _PROFILE_ORDER:
        rows = _rank_candidates(candidates[profile])
        for row in rows[:allocations[profile]]:
            selected.append(row)
            selected_ids.add(int(row["canonical_product_id"]))

    if len(selected) < effective_target_count:
        remainder = sorted(
            (
                row
                for rows in candidates.values()
                for row in rows
                if int(row["canonical_product_id"]) not in selected_ids
            ),
            key=_candidate_sort_key,
        )
        selected.extend(
            remainder[: effective_target_count - len(selected)]
        )

    return {
        "schema_version": _SCHEMA_VERSION,
        "requested_target_count": target_count,
        "target_count": len(selected),
        "profile_target_counts": {
            profile.value: sum(
                row["category_profile"] == profile.value
                for row in selected
            )
            for profile in _PROFILE_ORDER
        },
        "targets": selected,
        "manual_identity_resolution": sorted(
            manual_identity_resolution,
            key=lambda row: int(row["canonical_product_id"]),
        ),
    }


def build_capture_queue_for_scope(
    *,
    products: Sequence[Mapping[str, object]],
    scope: Mapping[str, object],
) -> dict[str, object]:
    """Build capture targets only for explicitly retained scope products."""
    selected = scope.get("selected_products")
    if not isinstance(selected, list) or not selected:
        raise SmzdmCaptureQueueError(
            "capture scope must contain selected_products"
        )
    scope_by_id: dict[int, Mapping[str, object]] = {}
    for row in selected:
        if not isinstance(row, Mapping):
            raise SmzdmCaptureQueueError(
                "capture scope product must be an object"
            )
        product_id = row.get("product_id")
        if type(product_id) is not int or product_id < 1:
            raise SmzdmCaptureQueueError(
                "capture scope product_id is invalid"
            )
        if product_id in scope_by_id:
            raise SmzdmCaptureQueueError(
                "capture scope product IDs must be unique"
            )
        scope_by_id[product_id] = row

    scoped_products = tuple(
        product
        for product in products
        if product.get("product_id") in scope_by_id
    )
    if len(scoped_products) != len(scope_by_id):
        raise SmzdmCaptureQueueError(
            "capture scope references unknown canonical products"
        )
    queue = build_capture_queue(
        products=scoped_products,
        target_count=len(scoped_products),
    )
    for target in queue["targets"]:
        if not isinstance(target, dict):
            raise SmzdmCaptureQueueError(
                "capture queue target must be an object"
            )
        product_id = int(target["canonical_product_id"])
        scope_row = scope_by_id[product_id]
        target["portfolio_role"] = scope_row.get("portfolio_role")
        target["sku_scope"] = scope_row.get("sku_scope")
    queue["schema_version"] = "smzdm-capture-queue-from-scope-v1"
    queue["scope_selected_count"] = len(scope_by_id)
    return queue


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
        raise SmzdmCaptureQueueError(
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


def _identity_is_unusable(value: str) -> bool:
    return value.strip().casefold() in _UNUSABLE_IDENTITY_VALUES


def _search_query(brand: str, identity: str) -> str:
    components = [value for value in (brand.strip(), identity.strip()) if value]
    return " ".join(components) + " 什么值得买 商品百科"


def _allocate_profiles(
    *,
    candidates: Mapping[CategoryProfile, Sequence[dict[str, object]]],
    target_count: int,
) -> dict[CategoryProfile, int]:
    available = sum(len(rows) for rows in candidates.values())
    if available == 0:
        return {profile: 0 for profile in _PROFILE_ORDER}
    allocations = {
        profile: min(
            len(candidates[profile]),
            (len(candidates[profile]) * target_count) // available,
        )
        for profile in _PROFILE_ORDER
    }
    remaining = target_count - sum(allocations.values())
    while remaining:
        eligible = [
            profile
            for profile in _PROFILE_ORDER
            if allocations[profile] < len(candidates[profile])
        ]
        if not eligible:
            break
        profile = max(
            eligible,
            key=lambda item: (
                (len(candidates[item]) * target_count) % available,
                len(candidates[item]) - allocations[item],
                -_PROFILE_ORDER.index(item),
            ),
        )
        allocations[profile] += 1
        remaining -= 1
    return allocations


def _rank_candidates(
    rows: Sequence[dict[str, object]],
) -> list[dict[str, object]]:
    return sorted(rows, key=_candidate_sort_key)


def _candidate_sort_key(row: Mapping[str, object]) -> tuple[int, int]:
    missing = row.get("missing_fields")
    if not isinstance(missing, list):
        raise SmzdmCaptureQueueError(
            "capture target must include missing_fields"
        )
    return (-len(missing), int(row["canonical_product_id"]))


def _load_products(path: Path) -> tuple[dict[str, object], ...]:
    try:
        return tuple(
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise SmzdmCaptureQueueError(
            "canonical products file is invalid"
        ) from exc


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a category-balanced SMZDM capture queue."
    )
    parser.add_argument("--canonical-products", type=Path, required=True)
    parser.add_argument("--target-count", type=int, default=80)
    parser.add_argument("--scope", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    products = _load_products(args.canonical_products)
    if args.scope is not None:
        try:
            scope = json.loads(args.scope.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SmzdmCaptureQueueError(
                "capture scope file is invalid"
            ) from exc
        if not isinstance(scope, Mapping):
            raise SmzdmCaptureQueueError(
                "capture scope must be an object"
            )
        queue = build_capture_queue_for_scope(
            products=products,
            scope=scope,
        )
    else:
        queue = build_capture_queue(
            products=products,
            target_count=args.target_count,
        )
    _write_json(args.output, queue)
    print(json.dumps({
        "manual_identity_resolution_count": len(
            queue["manual_identity_resolution"]
        ),
        "target_count": queue["target_count"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
