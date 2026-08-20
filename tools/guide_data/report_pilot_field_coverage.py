"""Report field states for the twelve pilots and three review products."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

from app.guide.adapters.catalog.canonical_product_reader import (
    CanonicalProductReader,
)
from app.guide.retrieval.category_fact_assets import (
    load_category_fact_assets,
)
from app.guide.retrieval.category_fact_contracts import (
    category_field_registry,
)
from app.guide.retrieval.category_profiles import (
    CategoryProfile,
    category_profile_for,
)
from tools.guide_data.inventory_local_sources import (
    SourceInventoryError,
    atomic_write_private,
)


_SCHEMA_VERSION = "pilot-field-coverage-v1"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_CORE_FIELD_KEYS = (
    "product_identity",
    "brand",
    "category",
    "price",
)
_CORE_OUTPUT_KEYS = {
    "product_identity": "identity",
    "brand": "brand",
    "category": "category",
    "price": "price",
}
_BINDING_KEYS = ("product", "item", "sku")
_ALLOWED_STATES = {
    "known",
    "unknown",
    "conflict",
    "not_applicable",
}
_REVIEW_PRODUCT_IDS = frozenset({42, 49, 55})
TARGET_PRODUCT_IDS = tuple(
    sorted(
        {
            38,
            91,
            53,
            57,
            79,
            80,
            86,
            114,
            69,
            103,
            120,
            121,
            42,
            49,
            55,
        }
    )
)


class PilotCoverageError(ValueError):
    """Raised when coverage inputs violate the fixed reporting contract."""


@dataclass(frozen=True, slots=True)
class PilotCoverageResult:
    target_product_count: int
    retained_count: int
    quarantine_count: int
    unknown_field_count: int
    conflict_field_count: int
    report_sha256: str
    products: tuple[dict[str, object], ...]


def build_product_coverage(
    product: Mapping[str, object],
    *,
    profile: CategoryProfile,
) -> dict[str, object]:
    """Classify one product without copying any source field value."""

    if not isinstance(product, Mapping):
        raise PilotCoverageError("product coverage input must be a mapping")
    product_id = product.get("product_id")
    if type(product_id) is not int or product_id <= 0:
        raise PilotCoverageError(
            "product coverage requires a positive product_id"
        )
    if not isinstance(profile, CategoryProfile):
        raise PilotCoverageError(
            "product coverage requires a CategoryProfile"
        )

    raw_fields = product.get("fields", {})
    if not isinstance(raw_fields, Mapping):
        raise PilotCoverageError("product fields must be a mapping")
    core = {
        _CORE_OUTPUT_KEYS[field_key]: _field_state(
            raw_fields.get(field_key),
            default="unknown",
        )
        for field_key in _CORE_FIELD_KEYS
    }

    raw_bindings = product.get("bindings", {})
    if not isinstance(raw_bindings, Mapping):
        raise PilotCoverageError("product bindings must be a mapping")
    bindings = {
        binding: _field_state(
            raw_bindings.get(binding),
            default=("known" if binding == "product" else "unknown"),
        )
        for binding in _BINDING_KEYS
    }

    fields: dict[str, dict[str, str]] = {}
    for definition in category_field_registry().for_profile(profile):
        if definition.key in _CORE_FIELD_KEYS:
            continue
        state = _field_state(
            raw_fields.get(definition.key),
            default="unknown",
        )
        fields[definition.key] = {
            "action": _action_for_state(state),
            "state": state,
        }

    core_is_trusted = all(state == "known" for state in core.values())
    binding_conflict = any(
        state == "conflict" for state in bindings.values()
    )
    product_binding_is_known = bindings["product"] == "known"
    product_status = (
        "retained"
        if core_is_trusted
        and product_binding_is_known
        and not binding_conflict
        else "quarantine"
    )
    return {
        "bindings": bindings,
        "category_profile": profile.value,
        "core": core,
        "fields": fields,
        "product_id": product_id,
        "product_status": product_status,
    }


def build_pilot_field_coverage(
    *,
    canonical_manifest_path: str | Path,
    canonical_products_path: str | Path,
    category_manifest_path: str | Path,
    review_manifest_path: str | Path,
    output_path: str | Path,
    product_ids: Sequence[int] = TARGET_PRODUCT_IDS,
    category_facts_path: str | Path | None = None,
) -> PilotCoverageResult:
    """Build the deterministic aggregate-only report for all 15 targets."""

    normalized_ids = _validate_target_product_ids(product_ids)
    canonical_reader = CanonicalProductReader.from_files(
        manifest_path=canonical_manifest_path,
        products_path=canonical_products_path,
    )
    category_assets = load_category_fact_assets(
        manifest_path=category_manifest_path,
        facts_path=category_facts_path,
        canonical_reader=canonical_reader,
        field_registry=category_field_registry(),
    )
    pilot_profiles = {
        binding.product_id: binding.category_profile
        for binding in category_assets.manifest.pilot_bindings
    }
    review_binding_states = _load_review_binding_states(
        Path(review_manifest_path)
    )
    fact_states = _category_fact_states(category_assets.facts)

    products: list[dict[str, object]] = []
    for product_id in normalized_ids:
        canonical = canonical_reader.get(product_id)
        profile = pilot_profiles.get(product_id)
        if profile is None:
            profile = _profile_from_canonical(canonical.fields)
        raw_product = canonical.model_dump(mode="python")
        raw_fields = raw_product["fields"]
        for (
            fact_product_id,
            field_key,
        ), state in fact_states.items():
            if fact_product_id == product_id:
                raw_fields[field_key] = {"resolved_state": state}
        raw_product["bindings"] = review_binding_states.get(
            product_id,
            {
                "item": {"resolved_state": "unknown"},
                "product": {"resolved_state": "known"},
                "sku": {"resolved_state": "unknown"},
            },
        )
        products.append(
            build_product_coverage(raw_product, profile=profile)
        )

    retained_count = sum(
        item["product_status"] == "retained" for item in products
    )
    quarantine_count = len(products) - retained_count
    unknown_field_count = sum(
        field["state"] == "unknown"
        for product in products
        for field in product["fields"].values()
    )
    conflict_field_count = sum(
        field["state"] == "conflict"
        for product in products
        for field in product["fields"].values()
    )
    payload = {
        "conflict_field_count": conflict_field_count,
        "products": products,
        "quarantine_count": quarantine_count,
        "retained_count": retained_count,
        "schema_version": _SCHEMA_VERSION,
        "target_product_count": len(products),
        "unknown_field_count": unknown_field_count,
    }
    report_bytes = (
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    try:
        atomic_write_private(output_path, report_bytes)
    except SourceInventoryError as exc:
        raise PilotCoverageError(
            "pilot coverage output could not be published"
        ) from exc
    return PilotCoverageResult(
        target_product_count=len(products),
        retained_count=retained_count,
        quarantine_count=quarantine_count,
        unknown_field_count=unknown_field_count,
        conflict_field_count=conflict_field_count,
        report_sha256=hashlib.sha256(report_bytes).hexdigest(),
        products=tuple(products),
    )


def _field_state(value: object, *, default: str) -> str:
    if value is None:
        return default
    if not isinstance(value, Mapping):
        raise PilotCoverageError(
            "coverage field metadata must be a mapping"
        )
    state = value.get("resolved_state")
    if not isinstance(state, str) or state not in _ALLOWED_STATES:
        raise PilotCoverageError(
            "coverage field resolved_state is invalid"
        )
    return state


def _action_for_state(state: str) -> str:
    if state == "known":
        return "keep"
    if state == "unknown":
        return "source_recovery"
    return "discard_candidate"


def _validate_target_product_ids(
    product_ids: Sequence[int],
) -> tuple[int, ...]:
    values = tuple(product_ids)
    if (
        any(type(product_id) is not int for product_id in values)
        or len(values) != len(set(values))
        or set(values) != set(TARGET_PRODUCT_IDS)
    ):
        raise PilotCoverageError(
            "coverage requires the fixed fifteen target products"
        )
    return tuple(sorted(values))


def _category_fact_states(
    facts: Sequence[object],
) -> dict[tuple[int, str], str]:
    normalized_values: dict[tuple[int, str], set[str]] = {}
    for fact in facts:
        key = (fact.product_id, fact.field_key)
        normalized_values.setdefault(key, set()).add(
            json.dumps(
                fact.value,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
    return {
        key: ("known" if len(values) == 1 else "conflict")
        for key, values in normalized_values.items()
    }


def _profile_from_canonical(
    fields: Mapping[str, object],
) -> CategoryProfile:
    category = fields.get("category")
    if (
        category is None
        or category.resolved_state != "known"
        or not isinstance(category.value, str)
    ):
        raise PilotCoverageError(
            "review product requires a known canonical category"
        )
    try:
        return category_profile_for(category.value)
    except KeyError as exc:
        raise PilotCoverageError(
            "review product canonical category is unmapped"
        ) from exc


def _load_review_binding_states(
    path: Path,
) -> dict[int, dict[str, dict[str, str]]]:
    payload = _read_json_object(path)
    if payload.get("schema_version") != "approved-review-sources-v1":
        raise PilotCoverageError("review manifest schema is invalid")
    _validate_manifest_digest(payload)
    raw_bindings = payload.get("product_bindings")
    if not isinstance(raw_bindings, list):
        raise PilotCoverageError("review manifest bindings are invalid")

    bindings: list[tuple[int, str, str]] = []
    for raw in raw_bindings:
        if not isinstance(raw, dict):
            raise PilotCoverageError(
                "review manifest binding is invalid"
            )
        product_id = raw.get("product_id")
        item_id = raw.get("item_id")
        sku_id = raw.get("sku_id")
        html_sha256 = raw.get("html_sha256")
        if (
            type(product_id) is not int
            or product_id <= 0
            or not isinstance(item_id, str)
            or not item_id.isdigit()
            or not isinstance(sku_id, str)
            or not sku_id.isdigit()
            or not isinstance(html_sha256, str)
            or not _SHA256_PATTERN.fullmatch(html_sha256)
        ):
            raise PilotCoverageError(
                "review manifest binding is invalid"
            )
        bindings.append((product_id, item_id, sku_id))

    by_product: dict[int, list[tuple[str, str]]] = {}
    for product_id, item_id, sku_id in bindings:
        by_product.setdefault(product_id, []).append((item_id, sku_id))
    item_owners: dict[str, set[int]] = {}
    sku_owners: dict[str, set[int]] = {}
    for product_id, item_id, sku_id in bindings:
        item_owners.setdefault(item_id, set()).add(product_id)
        sku_owners.setdefault(sku_id, set()).add(product_id)

    states: dict[int, dict[str, dict[str, str]]] = {}
    for product_id in _REVIEW_PRODUCT_IDS:
        product_bindings = by_product.get(product_id, [])
        product_state = (
            "known" if len(product_bindings) == 1 else "conflict"
        )
        item_state = product_state
        sku_state = product_state
        if len(product_bindings) == 1:
            item_id, sku_id = product_bindings[0]
            if len(item_owners[item_id]) != 1:
                item_state = "conflict"
            if len(sku_owners[sku_id]) != 1:
                sku_state = "conflict"
        states[product_id] = {
            "item": {"resolved_state": item_state},
            "product": {"resolved_state": product_state},
            "sku": {"resolved_state": sku_state},
        }
    return states


def _read_json_object(path: Path) -> dict[str, object]:
    descriptor = -1
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(
            metadata.st_mode
        ):
            raise PilotCoverageError(
                "review manifest must be a regular file"
            )
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != metadata.st_dev
            or opened.st_ino != metadata.st_ino
        ):
            raise PilotCoverageError(
                "review manifest must be a stable regular file"
            )
        with os.fdopen(descriptor, "rb") as source:
            descriptor = -1
            content = source.read()
    except PilotCoverageError:
        raise
    except OSError as exc:
        raise PilotCoverageError(
            "review manifest could not be read"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PilotCoverageError("review manifest is invalid") from exc
    if not isinstance(payload, dict):
        raise PilotCoverageError("review manifest is invalid")
    return payload


def _validate_manifest_digest(payload: dict[str, object]) -> None:
    expected = payload.get("manifest_sha256")
    if not isinstance(expected, str) or not _SHA256_PATTERN.fullmatch(
        expected
    ):
        raise PilotCoverageError("review manifest digest is invalid")
    unsigned = {
        key: value
        for key, value in payload.items()
        if key != "manifest_sha256"
    }
    actual = hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    if actual != expected:
        raise PilotCoverageError("review manifest digest is invalid")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Report aggregate field states for the fixed fifteen Guide "
            "data targets without exposing raw values."
        )
    )
    parser.add_argument("--canonical-manifest", required=True)
    parser.add_argument("--canonical-products", required=True)
    parser.add_argument("--category-manifest", required=True)
    parser.add_argument("--category-facts")
    parser.add_argument(
        "--approved-review-manifest",
        default=(
            "data/guide_review_sources/"
            "approved_tmall_feed_reviews_v1_manifest.json"
        ),
    )
    parser.add_argument(
        "--product-id",
        action="append",
        type=int,
    )
    parser.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_pilot_field_coverage(
            canonical_manifest_path=args.canonical_manifest,
            canonical_products_path=args.canonical_products,
            category_manifest_path=args.category_manifest,
            category_facts_path=args.category_facts,
            review_manifest_path=args.approved_review_manifest,
            output_path=args.output,
            product_ids=(
                tuple(args.product_id)
                if args.product_id is not None
                else TARGET_PRODUCT_IDS
            ),
        )
    except (PilotCoverageError, RuntimeError, KeyError, ValueError):
        print(
            json.dumps(
                {"status": "error", "type": "pilot_coverage_error"},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "conflict_field_count": result.conflict_field_count,
                "quarantine_count": result.quarantine_count,
                "report_sha256": result.report_sha256,
                "retained_count": result.retained_count,
                "target_product_count": result.target_product_count,
                "unknown_field_count": result.unknown_field_count,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
