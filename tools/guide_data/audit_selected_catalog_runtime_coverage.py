"""Audit selected-product data coverage through the runtime fact readers."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Mapping, Sequence

from app.guide.adapters.catalog import CanonicalProductReader
from app.guide.adapters.catalog.canonical_guide_catalog import (
    CanonicalGuideCatalog,
)
from app.guide.retrieval.category_profiles import category_profile_for
from app.guide_runtime.composition import (
    build_category_fact_reader,
    build_product_evidence_reader,
    build_selection_fact_reader,
)
from tools.guide_data.smzdm_capture_queue import CAPTURE_PRIORITY_FIELDS


class SelectedCatalogRuntimeCoverageError(ValueError):
    """Raised when selected products cannot be audited safely."""


def build_selected_catalog_runtime_coverage(
    *,
    reader: object,
    catalog: object,
    scope: Mapping[str, object],
) -> dict[str, object]:
    """Return source-aware coverage without promoting any source value."""
    selected = scope.get("selected_products")
    if not isinstance(selected, list) or not selected:
        raise SelectedCatalogRuntimeCoverageError(
            "scope must contain selected_products"
        )

    rows: list[dict[str, object]] = []
    seen_ids: set[int] = set()
    for item in selected:
        if not isinstance(item, Mapping):
            raise SelectedCatalogRuntimeCoverageError(
                "selected product must be an object"
            )
        product_id = item.get("product_id")
        if (
            type(product_id) is not int
            or product_id < 1
            or product_id in seen_ids
        ):
            raise SelectedCatalogRuntimeCoverageError(
                "selected product IDs must be unique positive integers"
            )
        seen_ids.add(product_id)
        product = reader.get(product_id)
        category = _known_text(product.fields.get("category"))
        if category is None:
            raise SelectedCatalogRuntimeCoverageError(
                f"selected product category is unavailable: {product_id}"
            )
        profile = category_profile_for(category)
        declared_profile = item.get("category_profile")
        if declared_profile != profile.value:
            raise SelectedCatalogRuntimeCoverageError(
                f"selected product profile mismatch: {product_id}"
            )
        presentation = catalog.get_presentation_facts(product_id)
        category_facts = {
            fact.field_key: fact
            for fact in presentation.category_fields
        }
        field_sources: dict[str, str] = {}
        for field_key in CAPTURE_PRIORITY_FIELDS[profile]:
            field_sources[field_key] = _field_source(
                field=product.fields.get(field_key),
                field_key=field_key,
                specification=presentation.specification,
                category_fact=category_facts.get(field_key),
            )
        rows.append({
            "product_id": product_id,
            "category_profile": profile.value,
            "field_sources": dict(sorted(field_sources.items())),
            "missing_fields": [
                field_key
                for field_key, source in field_sources.items()
                if source == "missing"
            ],
        })

    rows.sort(key=lambda row: int(row["product_id"]))
    return _report(rows)


def _field_source(
    *,
    field: object,
    field_key: str,
    specification: object,
    category_fact: object,
) -> str:
    if _has_known_value(field):
        return "canonical"
    if field_key == "net_content" and _nonempty_value(specification):
        return "reviewed_specification"
    if (
        category_fact is not None
        and getattr(category_fact, "resolved_state", None) == "known"
        and _nonempty_value(getattr(category_fact, "value", None))
    ):
        source_classes = {
            _source_name(value)
            for value in getattr(category_fact, "source_classes", ())
        }
        return (
            "merchant_claim"
            if "merchant_description_ocr" in source_classes
            else "approved_category_fact"
        )
    return "missing"


def _report(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    coverage = Counter()
    by_field: dict[str, Counter[str]] = {}
    by_profile: dict[str, Counter[str]] = {}
    for row in rows:
        profile = str(row["category_profile"])
        profile_counts = by_profile.setdefault(profile, Counter())
        field_sources = row["field_sources"]
        assert isinstance(field_sources, Mapping)
        for field_key, source in field_sources.items():
            if not isinstance(field_key, str) or not isinstance(source, str):
                raise SelectedCatalogRuntimeCoverageError(
                    "field sources must be strings"
                )
            coverage[source] += 1
            by_field.setdefault(field_key, Counter())[source] += 1
            profile_counts[source] += 1
    return {
        "schema_version": "selected-catalog-runtime-coverage-v1",
        "selected_product_count": len(rows),
        "field_slot_count": sum(coverage.values()),
        "coverage_counts": dict(sorted(coverage.items())),
        "by_field": {
            field_key: dict(sorted(counts.items()))
            for field_key, counts in sorted(by_field.items())
        },
        "by_profile": {
            profile: dict(sorted(counts.items()))
            for profile, counts in sorted(by_profile.items())
        },
        "products": list(rows),
    }


def _known_text(value: object) -> str | None:
    if getattr(value, "resolved_state", None) != "known":
        return None
    raw = getattr(value, "value", None)
    if not isinstance(raw, str) or not raw.strip():
        return None
    return raw.strip()


def _has_known_value(value: object) -> bool:
    return (
        getattr(value, "resolved_state", None) == "known"
        and _nonempty_value(getattr(value, "value", None))
    )


def _nonempty_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return bool(value)
    if isinstance(value, (list, tuple, set, frozenset)):
        return bool(value)
    return True


def _source_name(value: object) -> str:
    candidate = getattr(value, "value", value)
    return candidate if isinstance(candidate, str) else ""


def _load_scope(path: Path) -> Mapping[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SelectedCatalogRuntimeCoverageError(
            "scope file is invalid"
        ) from exc
    if not isinstance(value, Mapping):
        raise SelectedCatalogRuntimeCoverageError(
            "scope file must be an object"
        )
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--scope", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    reader = CanonicalProductReader.from_files(
        manifest_path=root / "data/canonical/core_products_v1_manifest.json",
        products_path=root / "data/canonical/core_products_v1.jsonl",
    )
    category_facts = build_category_fact_reader(reader, repo_root=root)
    catalog = CanonicalGuideCatalog(
        reader,
        category_fact_port=category_facts,
        selection_fact_port=build_selection_fact_reader(
            category_facts=category_facts,
            product_evidence=build_product_evidence_reader(root),
        ),
    )
    scope = _load_scope(args.scope)
    report = build_selected_catalog_runtime_coverage(
        reader=reader,
        catalog=catalog,
        scope=scope,
    )
    report["scope_sha256"] = hashlib.sha256(
        args.scope.read_bytes()
    ).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "field_slot_count": report["field_slot_count"],
        "coverage_counts": report["coverage_counts"],
        "selected_product_count": report["selected_product_count"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
