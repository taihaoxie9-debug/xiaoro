from __future__ import annotations

import json
from pathlib import Path

from app.guide.retrieval.product_evidence_assets import (
    load_product_evidence_assets,
)


ROOT = Path(__file__).resolve().parents[3]
ASSET_ROOT = ROOT / "data" / "guide_product_evidence"
EXPECTED_MANIFEST_SHA256 = (
    "ca5cee9dc0e70e64f3e30b2faf7aed35d45fae45272a299c540bfb79d071b351"
)
EXPECTED_EVIDENCE_SHA256 = (
    "52d236ad446309907368f21d74fa343132436ac509154bd7b035c6ce48178f81"
)
EXPECTED_AUDIT_SHA256 = (
    "1ded80381a5b225b53826fbde6958d8f9b94f216414ca66be135e522ba498200"
)
EXPECTED_CONCEPT_AUDIT_SHA256 = (
    "7093fe8bfd4051d177ed6cd7121c8e368b7fd8ba2c5807cfc684e88633724413"
)


def test_production_product_evidence_is_complete_and_hash_locked() -> None:
    manifest_path = ASSET_ROOT / "product_evidence_v1_manifest.json"
    evidence_path = (
        ASSET_ROOT
        / f"product_evidence_v1.{EXPECTED_EVIDENCE_SHA256}.jsonl"
    )
    audit_path = (
        ASSET_ROOT
        / f"image_audit_v1.{EXPECTED_AUDIT_SHA256}.jsonl"
    )
    assets = load_product_evidence_assets(
        manifest_path=manifest_path,
        evidence_path=evidence_path,
        audit_path=audit_path,
        expected_manifest_sha256=EXPECTED_MANIFEST_SHA256,
    )

    assert assets.manifest.image_count == len(assets.audit) == 972
    assert assets.manifest.evidence_count == len(assets.evidence) == 1262
    assert assets.manifest.product_count == 86
    assert assets.manifest.selection_concept_audit_sha256 == (
        EXPECTED_CONCEPT_AUDIT_SHA256
    )
    assert assets.manifest.status_counts == {
        "accepted": 668,
        "ambiguous": 18,
        "blocked": 80,
        "cross_product": 45,
        "duplicate": 66,
        "expired": 28,
        "irrelevant": 67,
    }
    assert assets.manifest.allowed_use_counts == {
        "answer": 1079,
        "compare": 666,
        "display": 1079,
        "hard_filter": 143,
        "safety_gate": 41,
        "soft_rank": 82,
        "weak_soft_rank": 348,
    }
    assert all(
        item.review_status != "accepted" or "answer" in item.allowed_uses
        for item in assets.evidence
    )
    accepted = [
        item
        for item in assets.evidence
        if item.review_status == "accepted"
    ]
    assert all(item.selection_review is not None for item in accepted)
    assert {
        decision: sum(
            item.selection_review is not None
            and item.selection_review.decision == decision
            for item in accepted
        )
        for decision in (
            "answer_only",
            "comparison_only",
            "projected",
            "safety_gate",
        )
    } == {
        "answer_only": 328,
        "comparison_only": 180,
        "projected": 530,
        "safety_gate": 41,
    }
    strengths = {
        strength: sum(
            projection.rank_strength == strength
            for item in accepted
            if item.selection_review is not None
            for projection in item.selection_review.projections
        )
        for strength in (1, 2)
    }
    assert strengths == {1: 953, 2: 341}

    progress = json.loads(
        (ASSET_ROOT / "review_progress_v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert progress["reviewed_available_images"] == 892
    assert progress["blocked_images"] == 80
    assert progress["unreviewed_available_images"] == 0
    assert (
        progress["reviewed_available_images"]
        + progress["blocked_images"]
        == progress["referenced_images"]
        == 972
    )
    assert progress["selection_use_audit"] == {
        "accepted_total": 1079,
        "accepted_reviewed": 1079,
        "accepted_missing": 0,
        "projected": 530,
        "answer_only": 328,
        "comparison_only": 180,
        "safety_gate": 41,
        "strength_1_projections": 953,
        "strength_2_projections": 341,
        "authorization_mismatches": 0,
        "duplicate_projection_keys": 0,
        "invalid_reviews": 0,
        "manifest_sha256": EXPECTED_MANIFEST_SHA256,
    }
    assert progress["selection_concept_audit"] == {
        "reviewed_total": 40,
        "keep_closed_enum": 6,
        "normalized": 30,
        "dropped_ordinary_duplicates": 4,
        "affected_products": 8,
        "unresolved_machine_soft_facts": 0,
        "audit_sha256": EXPECTED_CONCEPT_AUDIT_SHA256,
    }
