from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ASSET_ROOT = ROOT / "data" / "guide_product_evidence"
BASELINE_PATH = ROOT / "docs" / "audits" / "evidence-use" / "baseline.json"
BASELINE_EVIDENCE_SHA256 = (
    "2c573584788fea81fbe6b6acc33e917f4354b611494bbc52f97c581fed1be517"
)
BASELINE_AUDIT_SHA256 = (
    "7118c769fc8189f8fa9fcdcd55d49ecce72ba3ae0c8d3a89329095528259f4a6"
)


def test_evidence_use_baseline_is_explicit() -> None:
    assert json.loads(BASELINE_PATH.read_text(encoding="utf-8")) == {
        "accepted": 1079,
        "active_soft_facts": 398,
        "compare": 534,
        "evidence_total": 1262,
        "hard_filter": 144,
        "merchant_claims": 1136,
        "merchant_soft_claims": 778,
        "products_with_active_soft_fact": 100,
        "soft_or_weak": 299,
    }
    evidence = (
        ASSET_ROOT
        / f"product_evidence_v1.{BASELINE_EVIDENCE_SHA256}.jsonl"
    )
    audit = (
        ASSET_ROOT
        / f"image_audit_v1.{BASELINE_AUDIT_SHA256}.jsonl"
    )
    assert hashlib.sha256(evidence.read_bytes()).hexdigest() == (
        BASELINE_EVIDENCE_SHA256
    )
    assert hashlib.sha256(audit.read_bytes()).hexdigest() == (
        BASELINE_AUDIT_SHA256
    )
