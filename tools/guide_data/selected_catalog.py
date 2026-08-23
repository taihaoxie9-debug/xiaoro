"""Compile explicit product-selection decisions into a capture-safe catalog."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Mapping, Sequence


class SelectedCatalogError(ValueError):
    """Raised when a product-selection decision is incomplete or unsafe."""


_RETAIN = "retain"
_EXCLUDE = "exclude_from_capture"
_IDENTITY = "needs_identity_resolution"
_DISPOSITIONS = frozenset({_RETAIN, _EXCLUDE, _IDENTITY})


def build_selected_catalog(
    *,
    inventory: Mapping[str, object],
    decisions: Sequence[Mapping[str, object]],
    target_quotas: Mapping[str, int],
) -> dict[str, object]:
    """Compile auditable selection decisions without changing product data."""
    inventory_rows = _inventory_rows(inventory)
    decision_by_id = _decision_index(decisions)
    inventory_ids = {row["product_id"] for row in inventory_rows}
    if set(decision_by_id) != inventory_ids:
        raise SelectedCatalogError(
            "selection decisions must cover every inventory product exactly"
        )
    quotas = _normalize_quotas(target_quotas)
    selected_products: list[dict[str, object]] = []
    needs_identity_resolution: list[int] = []
    excluded_products: list[int] = []

    for row in inventory_rows:
        product_id = row["product_id"]
        decision = decision_by_id[product_id]
        lane = row["selection_lane"]
        disposition = decision["disposition"]
        if lane == "identity_review_required" and disposition == _RETAIN:
            raise SelectedCatalogError(
                "identity_review_required product cannot be retained"
            )
        if disposition == _RETAIN:
            selected_products.append({
                "product_id": product_id,
                "category_profile": row["category_profile"],
                "portfolio_role": decision["portfolio_role"],
                "sku_scope": decision["sku_scope"],
                "rationale": decision["rationale"],
            })
        elif disposition == _IDENTITY:
            needs_identity_resolution.append(product_id)
        else:
            excluded_products.append(product_id)

    selected_counts = {
        profile: sum(
            item["category_profile"] == profile
            for item in selected_products
        )
        for profile in quotas
    }
    if any(selected_counts[profile] > quotas[profile] for profile in quotas):
        raise SelectedCatalogError(
            "selected catalog exceeds a category target quota"
        )
    unfilled_slots = {
        profile: quotas[profile] - selected_counts[profile]
        for profile in quotas
    }
    return {
        "schema_version": "smzdm-capture-scope-v1",
        "target_quotas": quotas,
        "selected_count": len(selected_products),
        "selected_profile_counts": selected_counts,
        "unfilled_slots": unfilled_slots,
        "selected_products": selected_products,
        "needs_identity_resolution": needs_identity_resolution,
        "excluded_products": excluded_products,
    }


def _inventory_rows(
    inventory: Mapping[str, object],
) -> tuple[dict[str, object], ...]:
    raw_rows = inventory.get("products")
    if not isinstance(raw_rows, list) or not raw_rows:
        raise SelectedCatalogError(
            "selection inventory must contain nonempty products"
        )
    rows: list[dict[str, object]] = []
    seen_ids: set[int] = set()
    for raw in raw_rows:
        if not isinstance(raw, Mapping):
            raise SelectedCatalogError(
                "selection inventory product must be an object"
            )
        product_id = raw.get("product_id")
        profile = raw.get("category_profile")
        lane = raw.get("selection_lane")
        if (
            type(product_id) is not int
            or product_id < 1
            or not isinstance(profile, str)
            or not profile
            or not isinstance(lane, str)
            or not lane
            or product_id in seen_ids
        ):
            raise SelectedCatalogError(
                "selection inventory product is invalid"
            )
        seen_ids.add(product_id)
        rows.append({
            "product_id": product_id,
            "category_profile": profile,
            "selection_lane": lane,
        })
    return tuple(sorted(rows, key=lambda item: int(item["product_id"])))


def _decision_index(
    decisions: Sequence[Mapping[str, object]],
) -> dict[int, dict[str, object]]:
    indexed: dict[int, dict[str, object]] = {}
    for raw in decisions:
        if not isinstance(raw, Mapping):
            raise SelectedCatalogError(
                "selection decision must be an object"
            )
        product_id = raw.get("product_id")
        disposition = raw.get("disposition")
        rationale = raw.get("rationale")
        role = raw.get("portfolio_role")
        sku_scope = raw.get("sku_scope")
        if (
            type(product_id) is not int
            or product_id < 1
            or not isinstance(disposition, str)
            or disposition not in _DISPOSITIONS
            or not isinstance(rationale, str)
            or not rationale.strip()
            or product_id in indexed
        ):
            raise SelectedCatalogError("selection decision is invalid")
        if disposition == _RETAIN:
            if (
                not isinstance(role, str)
                or not role.strip()
                or not isinstance(sku_scope, str)
                or not sku_scope.strip()
            ):
                raise SelectedCatalogError(
                    "retained product requires role and sku scope"
                )
        elif role is not None or sku_scope is not None:
            raise SelectedCatalogError(
                "non-retained product forbids role and sku scope"
            )
        indexed[product_id] = {
            "disposition": disposition,
            "portfolio_role": role.strip()
            if isinstance(role, str)
            else None,
            "sku_scope": sku_scope.strip()
            if isinstance(sku_scope, str)
            else None,
            "rationale": rationale.strip(),
        }
    return indexed


def _normalize_quotas(
    target_quotas: Mapping[str, int],
) -> dict[str, int]:
    if not target_quotas:
        raise SelectedCatalogError("target quotas must be nonempty")
    quotas: dict[str, int] = {}
    for profile, count in target_quotas.items():
        if (
            not isinstance(profile, str)
            or not profile
            or type(count) is not int
            or count < 0
        ):
            raise SelectedCatalogError("target quota is invalid")
        quotas[profile] = count
    return dict(sorted(quotas.items()))


def _read_json(path: Path) -> Mapping[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SelectedCatalogError("selection input file is invalid") from exc
    if not isinstance(data, Mapping):
        raise SelectedCatalogError("selection input must be an object")
    return data


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compile selection decisions into a retained catalog."
    )
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    inventory = _read_json(args.inventory)
    review = _read_json(args.review)
    decisions = review.get("decisions")
    quotas = review.get("target_quotas")
    if not isinstance(decisions, list) or not isinstance(quotas, Mapping):
        raise SelectedCatalogError(
            "selection review requires decisions and target_quotas"
        )
    catalog = build_selected_catalog(
        inventory=inventory,
        decisions=decisions,
        target_quotas=quotas,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            catalog,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "selected_count": catalog["selected_count"],
        "unfilled_slots": catalog["unfilled_slots"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
