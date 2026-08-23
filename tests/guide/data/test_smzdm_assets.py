from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.guide_data.smzdm_assets import (
    SmzdmAssetValidationError,
    build_review_candidate,
)


def _raw_page() -> dict[str, object]:
    return {
        "canonical_product_id": 33,
        "page_url": "https://www.smzdm.com/p/180595258/",
        "captured_at": "2026-08-19T07:36:28+00:00",
        "page_title": (
            "雅诗兰黛 小棕瓶修护系列 特润修护肌活精华露 "
            "第七代 100ml"
        ),
        "product_title": "雅诗兰黛小棕瓶第七代 100ml",
        "page_specification": "100ml",
        "main_image_url": (
            "https://qny.smzdm.com/202101/27/"
            "601116308b05b4959.jpg_d250.jpg"
        ),
        "main_image_sha256": (
            "454ad2e307c2e57e8dc9ba23aca9d8a10dbd5173bb1e111f5b2e1eff3096b25c"
        ),
        "raw_product_introduction": (
            "功效：抗衰老；适用人群：所有肤质；"
            "主打成分：三肽-32。"
        ),
        "excluded_sections": (
            "Powered by ZDM-AIGC Engine v0.3",
            "优势",
            "建议",
        ),
        "raw_page_text_sha256": "f" * 64,
    }


def _image_approved_review() -> dict[str, object]:
    return {
        "category": "skincare",
        "sku_match_evidence": (
            "页面标题包含第七代小棕瓶 100ml",
            "主图 alt 包含第七代 100ml",
        ),
        "candidate_fields": {
            "net_content": "100ml",
            "efficacy_positioning": ("抗衰老",),
            "hero_ingredients": ("三肽-32",),
            "brand_technology": (
                "Chronolux Power Signal 时钟基因信源科技",
            ),
        },
        "image_review": {
            "status": "approved",
            "background_assessment": "clean_white",
            "sku_match_assessment": "same_product_100ml",
        },
        "existing_asset_conflicts": (
            {
                "field": "net_content",
                "existing_value": "50ml",
                "source_value": "100ml",
                "resolution": "defer_fact_promotion",
            },
        ),
        "reviewed_by": "human",
        "reviewed_at": "2026-08-19T07:40:00+00:00",
        "review_reason": "页面标题和主图 alt 均明确为第七代 100ml。",
    }


def test_approved_image_with_variant_conflict_defers_fact_promotion() -> None:
    candidate = build_review_candidate(
        _raw_page(),
        _image_approved_review(),
    )

    assert candidate["image_review"]["status"] == "approved"
    assert candidate["fact_promotion_status"] == "deferred"
    assert candidate["candidate_fields"]["net_content"] == "100ml"
    assert candidate["existing_asset_conflicts"] == [
        {
            "field": "net_content",
            "existing_value": "50ml",
            "source_value": "100ml",
            "resolution": "defer_fact_promotion",
        },
    ]
    assert len(candidate["candidate_id"]) == 64


def test_candidate_rejects_aigc_text_in_promotable_fields() -> None:
    review = _image_approved_review()
    review["candidate_fields"] = {
        **review["candidate_fields"],
        "brand_technology": (
            "Powered by ZDM-AIGC Engine v0.3 的推荐理由",
        ),
    }

    with pytest.raises(
        SmzdmAssetValidationError,
        match="AIGC content cannot enter candidate fields",
    ):
        build_review_candidate(_raw_page(), review)


def test_approved_image_requires_sku_evidence_and_hash() -> None:
    raw = _raw_page()
    raw["main_image_sha256"] = ""
    review = _image_approved_review()
    review["sku_match_evidence"] = ()

    with pytest.raises(
        SmzdmAssetValidationError,
        match="approved image requires SKU evidence and image SHA-256",
    ):
        build_review_candidate(raw, review)


def test_reviewed_small_brown_bottle_candidate_is_hash_bound() -> None:
    root = Path(__file__).resolve().parents[3]
    asset_root = root / "data/guide_merchant_claims/smzdm_crawl_v1"
    raw = _first_row(asset_root / "raw_pages.jsonl")
    review = _first_row(asset_root / "human_reviews.jsonl")
    published = _first_row(asset_root / "review_candidates.jsonl")

    assert _canonical_json(
        build_review_candidate(raw, review)
    ) == _canonical_json(published)
    assert published["image_review"]["status"] == "approved"
    assert published["fact_promotion_status"] == "deferred"
    assert (
        root
        / "data/guide_merchant_claims/smzdm_crawl_v1/"
        "source_images/33/smzdm_180595258_main_250.jpg"
    ).is_file()


def test_smzdm_asset_manifest_hash_locks_review_artifacts() -> None:
    root = Path(__file__).resolve().parents[3]
    asset_root = root / "data/guide_merchant_claims/smzdm_crawl_v1"
    manifest = json.loads(
        (asset_root / "manifest.json").read_text(encoding="utf-8")
    )

    assert manifest["schema_version"] == "smzdm-crawl-review-v2"
    assert manifest["raw_page_count"] == 1
    assert manifest["review_count"] == 1
    assert manifest["candidate_count"] == 1
    assert manifest["image_candidate_count"] == 6
    assert "image_candidates.jsonl" in manifest["files"]
    for relative_path, digest in manifest["files"].items():
        assert _sha256(asset_root / relative_path) == digest


def _first_row(path: Path) -> dict[str, object]:
    return json.loads(
        path.read_text(encoding="utf-8").splitlines()[0]
    )


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()
