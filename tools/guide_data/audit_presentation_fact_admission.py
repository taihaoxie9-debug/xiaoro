from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re

from app.guide.adapters.catalog import CanonicalProductReader
from app.guide.adapters.catalog.canonical_guide_catalog import (
    CanonicalGuideCatalog,
)
from app.guide.presentation.copywriter_validation import (
    is_safe_soft_fact_text,
)
from app.guide.presentation.fact_admission import (
    presentation_fact_role,
)
from app.guide.retrieval.merchant_claim_assets import (
    load_merchant_claim_assets,
)
from app.guide_runtime.composition import (
    GUIDE_MERCHANT_CLAIM_ASSET_RELATIVE_PATH,
    GUIDE_MERCHANT_CLAIM_MANIFEST_SHA256,
    GUIDE_MERCHANT_CLAIM_RELATIVE_PATH,
    REPO_ROOT,
    build_category_fact_reader,
    build_product_evidence_reader,
    build_review_evidence_reader,
    build_selection_fact_reader,
)


_CJK = re.compile(r"[\u3400-\u9fff]")


def build_audit_report(repo_root: str | Path = REPO_ROOT) -> dict:
    root = Path(repo_root)
    assets = load_merchant_claim_assets(
        manifest_path=root / GUIDE_MERCHANT_CLAIM_RELATIVE_PATH,
        claims_path=root / GUIDE_MERCHANT_CLAIM_ASSET_RELATIVE_PATH,
        expected_manifest_sha256=GUIDE_MERCHANT_CLAIM_MANIFEST_SHA256,
    )
    rows = []
    for claim in sorted(
        assets.claims,
        key=lambda item: (item.product_id, item.claim_id),
    ):
        role = (
            "caution"
            if claim.claim_scope == "safety_transcript"
            else presentation_fact_role(claim.field_key)
        )
        selected_meaning = claim.display_claim
        selected_meaning_source = "not_applicable"
        validator_admitted = None
        rejection_code = None
        if role == "narrative":
            normalized_admitted = (
                _CJK.search(claim.normalized_value)
                and is_safe_soft_fact_text(
                    claim.normalized_value,
                    attribution="merchant_claim",
                    field_key=claim.field_key,
                )
            )
            if normalized_admitted:
                selected_meaning = claim.normalized_value
                selected_meaning_source = "normalized_value"
                validator_admitted = True
            elif is_safe_soft_fact_text(
                claim.display_claim,
                attribution="merchant_claim",
                field_key=claim.field_key,
            ):
                selected_meaning_source = "display_claim"
                validator_admitted = True
            else:
                selected_meaning_source = "rejected"
                rejection_code = _soft_fact_rejection_code(
                    claim.display_claim,
                    field_key=claim.field_key,
                )
        disposition = {
            "caution": "caution",
            "direct_fact": "direct_fact",
            "question_only": "question_only",
            "narrative": (
                "positioning" if validator_admitted else "excluded"
            ),
        }[role]
        reason_code = {
            "caution": "safety_scope",
            "direct_fact": "direct_field_policy",
            "question_only": "question_specific_field",
            "narrative": (
                (
                    "approved_narrative"
                    if selected_meaning_source == "display_claim"
                    else "approved_narrative_normalized"
                )
                if validator_admitted
                else f"validator_rejected:{rejection_code}"
            ),
        }[role]
        rows.append({
            "claim_id": claim.claim_id,
            "product_id": claim.product_id,
            "source_kind": "merchant_claim",
            "field_key": claim.field_key,
            "attribution": "merchant_claim",
            "allowed_use": (
                "soft_rank_and_display"
                if "soft_rank" in claim.capabilities
                else "display_only"
            ),
            "source_refs": [claim.source_locator],
            "plain_meaning": selected_meaning,
            "original_display_claim": claim.display_claim,
            "selected_meaning_source": selected_meaning_source,
            "disposition": disposition,
            "reason_code": reason_code,
            "packet_fact_id": (
                claim.claim_id
                if disposition == "positioning"
                else None
            ),
        })

    disposition_counts = Counter(
        row["disposition"] for row in rows
    )
    reason_counts = Counter(row["reason_code"] for row in rows)
    selected_source_counts = Counter(
        row["selected_meaning_source"] for row in rows
    )
    field_counts = Counter(row["field_key"] for row in rows)
    excluded_field_counts = Counter(
        row["field_key"]
        for row in rows
        if row["disposition"] == "excluded"
    )
    canonical_root = root / "data" / "canonical"
    canonical_reader = CanonicalProductReader.from_files(
        manifest_path=canonical_root / "core_products_v1_manifest.json",
        products_path=canonical_root / "core_products_v1.jsonl",
    )
    category_reader = build_category_fact_reader(
        canonical_reader,
        repo_root=root,
    )
    product_evidence_reader = build_product_evidence_reader(root)
    catalog = CanonicalGuideCatalog(
        canonical_reader,
        category_fact_port=category_reader,
        selection_fact_port=build_selection_fact_reader(
            category_facts=category_reader,
            product_evidence=product_evidence_reader,
        ),
    )
    category_inventory = []
    specifications_by_product = {}
    for product_id in sorted(canonical_reader.product_ids):
        facts = catalog.get_presentation_facts(product_id)
        specifications_by_product[product_id] = facts.specification
        for fact in facts.category_fields:
            if fact.resolved_state != "known":
                continue
            category_inventory.append({
                "product_id": product_id,
                "field_key": fact.field_key,
                "value": fact.value,
                "capabilities": sorted(fact.capabilities),
                "source_refs": list(fact.source_refs),
                "presentation_role": presentation_fact_role(
                    fact.field_key
                ),
            })

    review_reader = build_review_evidence_reader(root)
    review_inventory = []
    for product_id in sorted(canonical_reader.product_ids):
        result = review_reader.read(product_id=product_id)
        for evidence in result.evidence:
            review_inventory.append({
                "product_id": product_id,
                "source_id": evidence.source_id,
                "source_locator": evidence.source_locator,
                "content_sha256": evidence.content_sha256,
                "content": evidence.content,
            })
    category_pairs = {
        (row["product_id"], row["field_key"])
        for row in category_inventory
    }
    direct_rows = tuple(
        row for row in rows if row["disposition"] == "direct_fact"
    )
    unresolved_direct = tuple(
        row
        for row in direct_rows
        if (
            (row["product_id"], row["field_key"])
            not in category_pairs
            and not (
                row["field_key"] == "net_content"
                and specifications_by_product.get(row["product_id"])
            )
        )
    )
    unexplained_drops = tuple(
        row
        for row in rows
        if (
            row["disposition"] == "excluded"
            and row["reason_code"].endswith(":unknown")
        )
    )
    return {
        "schema_version": (
            "guide-presentation-fact-admission-audit-v1"
        ),
        "merchant_manifest_sha256": (
            assets.manifest.manifest_sha256
        ),
        "summary": {
            "claim_count": len(rows),
            "product_count": len({
                row["product_id"] for row in rows
            }),
            "missing_source_ref_count": sum(
                not row["source_refs"] for row in rows
            ),
            "field_whitelist_only_drop_count": 0,
            "validator_only_drop_count": disposition_counts["excluded"],
            "normalized_fallback_count": selected_source_counts[
                "normalized_value"
            ],
            "disposition_counts": dict(sorted(
                disposition_counts.items()
            )),
            "reason_counts": dict(sorted(reason_counts.items())),
            "selected_meaning_source_counts": dict(sorted(
                selected_source_counts.items()
            )),
            "field_counts": dict(sorted(field_counts.items())),
            "excluded_field_counts": dict(sorted(
                excluded_field_counts.items()
            )),
            "known_category_fact_count": len(category_inventory),
            "known_category_fact_missing_source_count": sum(
                not row["source_refs"] for row in category_inventory
            ),
            "approved_review_source_count": len(review_inventory),
            "review_product_count": len({
                row["product_id"] for row in review_inventory
            }),
            "direct_fact_unresolved_count": len(unresolved_direct),
            "unexplained_drop_count": len(unexplained_drops),
        },
        "rows": rows,
        "category_fact_inventory": category_inventory,
        "review_inventory": review_inventory,
        "unresolved_direct_fact_rows": list(unresolved_direct),
    }


def _soft_fact_rejection_code(
    text: str,
    *,
    field_key: str,
) -> str:
    del text, field_key
    return "copywriter_public_language"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report = build_audit_report(args.repo_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
