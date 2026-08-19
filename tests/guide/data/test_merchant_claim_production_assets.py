from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from app.guide.retrieval.merchant_claim_assets import (
    load_merchant_claim_assets,
)


ROOT = Path(__file__).resolve().parents[3]
ASSET_ROOT = ROOT / "data" / "guide_merchant_claims"
EXPECTED_MANIFEST_SHA256 = (
    "d906c0a6d42636c89d1ccb408413c786b817cbb2ddf44678143c427228a21e75"
)
EXPECTED_CLAIMS_SHA256 = (
    "8b90f33d45368c269076d96a8b0ca76fd1c5fcac988fd96cc93937da7d4207fd"
)
EXPECTED_CONCEPT_AUDIT_SHA256 = (
    "7093fe8bfd4051d177ed6cd7121c8e368b7fd8ba2c5807cfc684e88633724413"
)


def test_production_claims_are_self_contained_and_backed_by_exact_ocr() -> None:
    manifest_path = ASSET_ROOT / "merchant_claims_v1_manifest.json"
    claims_path = (
        ASSET_ROOT
        / f"merchant_claims_v1.{EXPECTED_CLAIMS_SHA256}.jsonl"
    )
    assets = load_merchant_claim_assets(
        manifest_path=manifest_path,
        claims_path=claims_path,
        expected_manifest_sha256=EXPECTED_MANIFEST_SHA256,
    )

    assert assets.manifest.claim_count == len(assets.claims) == 1129
    assert assets.manifest.product_count == 98
    assert assets.manifest.source_file_count == 103
    assert assets.manifest.review_file_count == 2
    assert EXPECTED_CONCEPT_AUDIT_SHA256 in (
        assets.manifest.review_file_sha256s
    )

    source_paths = sorted(
        (ASSET_ROOT / "source_ocr").glob("detail_*_ocr.json")
    )
    assert len(source_paths) == 103
    sources: dict[int, tuple[str, list[dict[str, object]]]] = {}
    for path in source_paths:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
        sources[payload["pid"]] = (
            hashlib.sha256(raw).hexdigest(),
            payload["images"],
        )
    assert sorted(value[0] for value in sources.values()) == list(
        assets.manifest.source_file_sha256s
    )

    for claim in assets.claims:
        source_sha, images = sources[claim.product_id]
        assert claim.source_sha256 == source_sha
        matching_records = [
            image
            for image in images
            if hashlib.sha256(
                json.dumps(
                    image,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            == claim.record_sha256
        ]
        assert len(matching_records) == 1
        assert claim.display_claim in matching_records[0]["ocr_text"]
        assert "/Users/" not in claim.source_locator
        assert "hard_filter" not in claim.capabilities
        if claim.claim_scope == "safety_transcript":
            assert claim.capabilities == frozenset(
                {"evidence", "display"}
            )

    review_path = (
        ASSET_ROOT
        / (
            "merchant_claim_reviews_v1."
            "82cbbc22971cb3aca366076b37adde7a9c03a5c96bf34e200de947364a4d6664"
            ".jsonl"
        )
    )
    assert hashlib.sha256(review_path.read_bytes()).hexdigest() in (
        assets.manifest.review_file_sha256s
    )
    assert len(
        list(
            (ASSET_ROOT / "raw_reviews").glob(
                "xiaoro_ocr_review_*.jsonl"
            )
        )
    ) == 23
    assert len(
        list(
            (ASSET_ROOT / "raw_reviews").glob(
                "xiaoro_ocr_review_*_summary.md"
            )
        )
    ) == 23

    recovery_rows = (
        ASSET_ROOT / "recovery_decisions_v1.jsonl"
    ).read_text(encoding="utf-8").splitlines()
    assert len(recovery_rows) == 90

    rejection_path = (
        ASSET_ROOT
        / (
            "merchant_claim_review_rejections_v1."
            "b3525a6f2253bd6fcf990255363070584c3fce00074ecb30112e5fb88a34f3f0"
            ".jsonl"
        )
    )
    rejections = [
        json.loads(line)
        for line in rejection_path.read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert Counter(item["reason"] for item in rejections) == {
        "consumer_review_transcript": 5,
        "display_claim_not_exact": 4,
    }
