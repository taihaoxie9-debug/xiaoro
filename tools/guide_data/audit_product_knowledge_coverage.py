"""Build a deterministic inventory of answerable product knowledge."""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping, Sequence
import json
from pathlib import Path
import re

from app.guide.adapters.catalog import CanonicalProductReader
from app.guide.retrieval.category_profiles import (
    CategoryProfile,
    category_profile_for,
)
from app.guide.retrieval.product_evidence_retrieval import (
    product_evidence_dimensions,
)
from app.guide_runtime.composition import (
    build_category_fact_reader,
    build_product_evidence_reader,
)
from tools.guide_data.smzdm_capture_queue import CAPTURE_PRIORITY_FIELDS


SCHEMA_VERSION = "product-knowledge-coverage-v1"
_PLACEHOLDER_IDENTITIES = frozenset({"", "-", "--", "n/a", "na", "无", "未知", "000"})
_NON_CJK_ALNUM = re.compile(r"[^0-9a-z\u3400-\u9fff]+", re.IGNORECASE)
_BRAND_SUFFIX = re.compile(r"[（(].*$")


class ProductKnowledgeCoverageError(ValueError):
    """Raised when the runtime knowledge inventory cannot be audited."""


def build_product_knowledge_coverage(
    *,
    canonical_reader: object,
    category_fact_reader: object,
    evidence_reader: object,
) -> dict[str, object]:
    product_ids = getattr(canonical_reader, "product_ids", None)
    if not isinstance(product_ids, frozenset) or not product_ids:
        raise ProductKnowledgeCoverageError(
            "canonical reader must expose product IDs"
        )

    rows: list[dict[str, object]] = []
    evidence_product_count = 0
    category_product_count = 0
    union_product_count = 0
    answerable_count = 0
    faq_count = 0
    remediation_counts: Counter[str] = Counter()
    for product_id in sorted(product_ids):
        product = canonical_reader.get(product_id)
        fields = getattr(product, "fields", {})
        if not isinstance(fields, Mapping):
            raise ProductKnowledgeCoverageError(
                f"canonical fields are invalid: {product_id}"
            )
        identity = _known_text(fields.get("product_identity"))
        brand = _known_text(fields.get("brand"))
        category = _known_text(fields.get("category"))
        identity_status = _identity_status(identity, brand=brand)
        profile = _profile(category)

        answerable = tuple(
            evidence_reader.read_answerable(product_id=product_id)
        )
        all_evidence = tuple(evidence_reader.read(product_id=product_id))
        answerable_count += len(answerable)
        product_faq_count = sum(
            block.management_label == "faq"
            for block in answerable
        )
        faq_count += product_faq_count
        evidence_fields = {
            dimension
            for block in answerable
            for dimension in product_evidence_dimensions(block)
        }
        known_category_facts = (
            tuple(
                fact
                for fact in category_fact_reader.read(
                    product_id=product_id,
                    profile=profile,
                )
                if (
                    fact.resolved_state == "known"
                    and _nonempty_value(fact.value)
                )
            )
            if profile is not None
            else ()
        )
        category_fields = {
            fact.field_key for fact in known_category_facts
        }
        covered_fields = tuple(sorted(
            evidence_fields | category_fields
        ))
        priority_fields = (
            CAPTURE_PRIORITY_FIELDS[profile]
            if profile is not None
            else ()
        )
        missing_priority_fields = [
            field_key
            for field_key in priority_fields
            if field_key not in covered_fields
        ]
        remediation = _remediation(
            identity_status=identity_status,
            answerable=answerable,
            all_evidence=all_evidence,
            known_category_facts=known_category_facts,
        )
        remediation_counts[remediation] += 1
        if answerable:
            evidence_product_count += 1
        if known_category_facts:
            category_product_count += 1
        if answerable or known_category_facts:
            union_product_count += 1
        rows.append({
            "product_id": product_id,
            "identity": identity,
            "identity_status": identity_status,
            "category": category,
            "category_profile": (
                profile.value if profile is not None else None
            ),
            "answerable_evidence_count": len(answerable),
            "faq_count": product_faq_count,
            "evidence_management_labels": sorted({
                block.management_label for block in answerable
            }),
            "category_fact_count": len(known_category_facts),
            "category_fact_fields": sorted(category_fields),
            "covered_fields": list(covered_fields),
            "missing_priority_fields": missing_priority_fields,
            "remediation": remediation,
        })

    manifest = getattr(evidence_reader, "manifest", None)
    allowed_use_counts = getattr(manifest, "allowed_use_counts", {})
    manifest_answer_count = (
        allowed_use_counts.get("answer")
        if isinstance(allowed_use_counts, Mapping)
        else None
    )
    if (
        manifest_answer_count is not None
        and manifest_answer_count != answerable_count
    ):
        raise ProductKnowledgeCoverageError(
            "answerable evidence count does not match manifest"
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "canonical_product_count": len(rows),
        "answerable_evidence_count": answerable_count,
        "faq_count": faq_count,
        "product_evidence_product_count": evidence_product_count,
        "category_fact_product_count": category_product_count,
        "union_covered_product_count": union_product_count,
        "remediation_counts": dict(sorted(remediation_counts.items())),
        "products": rows,
    }


def write_product_knowledge_coverage(
    *,
    report: Mapping[str, object],
    json_output: Path,
    markdown_output: Path,
) -> None:
    if report.get("schema_version") != SCHEMA_VERSION:
        raise ProductKnowledgeCoverageError(
            "coverage report schema is invalid"
        )
    json_path = Path(json_output)
    markdown_path = Path(markdown_output)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(
        _render_markdown(report),
        encoding="utf-8",
    )


def _render_markdown(report: Mapping[str, object]) -> str:
    products = report.get("products")
    if not isinstance(products, list):
        raise ProductKnowledgeCoverageError(
            "coverage report products are invalid"
        )
    lines = [
        "# Product Knowledge Coverage",
        "",
        f"- Canonical products: {report['canonical_product_count']}",
        f"- Answerable evidence: {report['answerable_evidence_count']}",
        f"- FAQ evidence: {report['faq_count']}",
        (
            "- ProductEvidence products: "
            f"{report['product_evidence_product_count']}"
        ),
        (
            "- Category Facts products: "
            f"{report['category_fact_product_count']}"
        ),
        (
            "- Union-covered products: "
            f"{report['union_covered_product_count']}"
        ),
        "",
        "| Product | Identity | Status | Evidence | FAQ | Category facts | Missing priority fields | Remediation |",
        "|---:|---|---|---:|---:|---:|---|---|",
    ]
    for row in products:
        if not isinstance(row, Mapping):
            raise ProductKnowledgeCoverageError(
                "coverage report row is invalid"
            )
        missing = row["missing_priority_fields"]
        if not isinstance(missing, list):
            raise ProductKnowledgeCoverageError(
                "missing priority fields are invalid"
            )
        lines.append(
            f"| PID {row['product_id']} | "
            f"{row['identity'] or '(missing)'} | "
            f"{row['identity_status']} | "
            f"{row['answerable_evidence_count']} | "
            f"{row['faq_count']} | "
            f"{row['category_fact_count']} | "
            f"{', '.join(str(value) for value in missing) or '-'} | "
            f"{row['remediation']} |"
        )
    return "\n".join(lines) + "\n"


def _known_text(field: object) -> str | None:
    if getattr(field, "resolved_state", None) != "known":
        return None
    value = getattr(field, "value", None)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _nonempty_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (tuple, list, set, frozenset, Mapping)):
        return bool(value)
    return True


def _identity_status(
    identity: str | None,
    *,
    brand: str | None,
) -> str:
    normalized_identity = _normalized_identity(identity or "")
    if normalized_identity in _PLACEHOLDER_IDENTITIES:
        return "placeholder"
    normalized_brand = _normalized_identity(
        _BRAND_SUFFIX.sub("", brand or "")
    )
    if normalized_brand and normalized_identity == normalized_brand:
        return "underspecified"
    return "valid"


def _normalized_identity(value: str) -> str:
    return _NON_CJK_ALNUM.sub("", value.casefold())


def _profile(category: str | None) -> CategoryProfile | None:
    if category is None:
        return None
    try:
        return category_profile_for(category)
    except KeyError:
        return None


def _remediation(
    *,
    identity_status: str,
    answerable: tuple[object, ...],
    all_evidence: tuple[object, ...],
    known_category_facts: tuple[object, ...],
) -> str:
    if identity_status != "valid":
        return "catalog_cleanup"
    if answerable or known_category_facts:
        return "already_available"
    if all_evidence:
        return "review_required"
    return "honest_unknown"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.repo_root.resolve()
    canonical = CanonicalProductReader.from_files(
        manifest_path=(
            root / "data/canonical/core_products_v1_manifest.json"
        ),
        products_path=root / "data/canonical/core_products_v1.jsonl",
    )
    runtime_facts = build_category_fact_reader(
        canonical,
        repo_root=root,
    )
    report = build_product_knowledge_coverage(
        canonical_reader=canonical,
        category_fact_reader=runtime_facts.base,
        evidence_reader=build_product_evidence_reader(root),
    )
    write_product_knowledge_coverage(
        report=report,
        json_output=args.json_output,
        markdown_output=args.markdown_output,
    )
    print(json.dumps(
        {
            key: report[key]
            for key in (
                "canonical_product_count",
                "answerable_evidence_count",
                "faq_count",
                "product_evidence_product_count",
                "category_fact_product_count",
                "union_covered_product_count",
            )
        },
        ensure_ascii=False,
        sort_keys=True,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ProductKnowledgeCoverageError",
    "build_product_knowledge_coverage",
    "main",
    "write_product_knowledge_coverage",
]
