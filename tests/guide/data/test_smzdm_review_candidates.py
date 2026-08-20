from __future__ import annotations

import json
from pathlib import Path
import hashlib

import pytest

from tools.guide_data.build_smzdm_review_candidates import (
    SmzdmReviewCandidateBuildError,
    build_smzdm_review_candidates,
)
from tools.guide_data.review_smzdm_product import (
    SmzdmProductReviewPacketError,
    build_product_review_packet,
    validate_reviewed_product_packet,
)


def _raw(product_id: int) -> dict[str, object]:
    return {
        "canonical_product_id": product_id,
        "page_url": f"https://www.smzdm.com/p/{product_id}/",
        "captured_at": "2026-08-19T00:00:00+00:00",
        "page_title": "示例精华 30ml",
        "product_title": "示例精华 30ml",
        "page_specification": "30ml",
        "main_image_url": f"https://qny.smzdm.com/{product_id}.jpg",
        "main_image_sha256": "a" * 64,
        "raw_product_introduction": "核心成分：泛醇。",
        "excluded_sections": [
            "Powered by ZDM-AIGC Engine v0.3",
            "优势",
            "建议",
        ],
        "raw_page_text_sha256": "b" * 64,
    }


def _review(product_id: int) -> dict[str, object]:
    return {
        "canonical_product_id": product_id,
        "category": "skincare",
        "sku_match_evidence": ["页面标题包含 30ml"],
        "candidate_fields": {
            "net_content": "30ml",
            "efficacy_positioning": ["修护"],
            "hero_ingredients": ["泛醇"],
            "brand_technology": ["示例技术"],
        },
        "image_review": {
            "status": "approved",
            "background_assessment": "clean_white",
            "sku_match_assessment": "same_product_30ml",
        },
        "existing_asset_conflicts": [],
        "reviewed_by": "human",
        "reviewed_at": "2026-08-19T00:10:00+00:00",
        "review_reason": "页面规格明确。",
    }


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True)
            for row in rows
        )
        + "\n",
        encoding="utf-8",
    )


def test_candidate_builder_requires_one_human_review_per_raw_page(
    tmp_path: Path,
) -> None:
    raw_pages = tmp_path / "raw_pages.jsonl"
    reviews = tmp_path / "human_reviews.jsonl"
    _write_jsonl(raw_pages, [_raw(11)])
    _write_jsonl(reviews, [])

    with pytest.raises(
        SmzdmReviewCandidateBuildError,
        match="raw capture requires exactly one human review",
    ):
        build_smzdm_review_candidates(
            raw_pages_path=raw_pages,
            reviews_path=reviews,
            output_dir=tmp_path / "output",
        )


def test_candidate_builder_writes_hash_bound_candidate_manifest(
    tmp_path: Path,
) -> None:
    raw_pages = tmp_path / "raw_pages.jsonl"
    reviews = tmp_path / "human_reviews.jsonl"
    _write_jsonl(raw_pages, [_raw(11)])
    _write_jsonl(reviews, [_review(11)])

    result = build_smzdm_review_candidates(
        raw_pages_path=raw_pages,
        reviews_path=reviews,
        output_dir=tmp_path / "output",
    )
    candidate = json.loads(
        (result.output_dir / "review_candidates.jsonl")
        .read_text(encoding="utf-8")
        .strip()
    )
    manifest = json.loads(
        (result.output_dir / "manifest.json").read_text(encoding="utf-8")
    )

    assert candidate["canonical_product_id"] == 11
    assert candidate["fact_promotion_status"] == "pending"
    assert candidate["review_policy_fields"] == [
        "net_content",
        "ingredients_present",
        "texture",
        "efficacy",
        "usage",
    ]
    assert manifest["raw_page_count"] == 1
    assert manifest["review_count"] == 1
    assert manifest["candidate_count"] == 1


def test_review_packet_binds_queue_raw_and_local_detail_images(
    tmp_path: Path,
) -> None:
    image_content = b"review-detail-image"
    image_sha256 = hashlib.sha256(image_content).hexdigest()
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    image_path = image_dir / f"001_{image_sha256[:16]}.jpg"
    image_path.write_bytes(image_content)

    packet = build_product_review_packet(
        target={
            "canonical_product_id": 46,
            "canonical_product_identity": "理肤泉B5霜",
            "category_profile": "skincare",
            "portfolio_role": "entry_repair_cream",
            "sku_scope": "canonical_single_product_40ml",
            "missing_fields": ["texture", "efficacy"],
        },
        raw_capture={
            "canonical_product_id": 46,
            "page_url": "https://wiki.smzdm.com/p/example/",
            "captured_at": "2026-08-20T00:00:00+00:00",
            "page_title": "理肤泉B5霜 40ml",
            "product_title": "理肤泉B5霜 40ml",
            "parameter_text": "净含量 40ml",
            "product_introduction": "柔润乳霜质地",
            "raw_page_text_sha256": "a" * 64,
            "detail_image_count": 1,
            "detail_image_status": "present",
            "review_sources": [
                "parameter_table",
                "product_introduction",
                "detail_images",
            ],
            "detail_images": [
                {
                    "ordinal": 1,
                    "source_url": "https://y.zdmimg.com/detail.jpg",
                    "sha256": image_sha256,
                    "width": 600,
                    "height": 800,
                }
            ],
        },
        detail_image_dir=image_dir,
        source_match="exact",
        canonical_specification="40ml",
        source_sku="40ml",
        reference_price_sku="40ml",
        display_specification="40ml",
        price_specification_alignment="aligned",
    )

    assert packet["product_id"] == 46
    assert packet["canonical_specification"] == "40ml"
    assert packet["source_match"] == "exact"
    assert packet["sku_audit"] == {
        "identity_status": "exact_product",
        "source_sku": "40ml",
        "canonical_sku": "40ml",
        "reference_price_sku": "40ml",
        "display_specification": "40ml",
        "price_specification_alignment": "aligned",
    }
    assert packet["detail_image_status"] == "present"
    assert packet["detail_images"] == [
        {
            "ordinal": 1,
            "local_path": str(image_path),
            "sha256": image_sha256,
            "width": 600,
            "height": 800,
        }
    ]
    assert packet["candidate_facts"] == []
    assert packet["review_status"] == "human_review_required"


def test_review_packet_without_long_images_stays_reviewable(
    tmp_path: Path,
) -> None:
    packet = build_product_review_packet(
        target={
            "canonical_product_id": 66,
            "canonical_product_identity": "珂润润浸保湿洁颜泡沫",
            "category_profile": "cleanser",
            "portfolio_role": "foam_cleanser",
            "sku_scope": "canonical_single_product_pending_source",
            "missing_fields": ["net_content", "cleansing_power"],
        },
        raw_capture={
            "canonical_product_id": 66,
            "page_url": "https://wiki.smzdm.com/p/2j5jr7/",
            "captured_at": "2026-08-20T00:00:00+00:00",
            "page_title": "珂润润浸保湿洁颜泡沫",
            "product_title": "珂润润浸保湿洁颜泡沫",
            "parameter_text": "净含量 150ml",
            "product_introduction": "按压式泡沫洁面",
            "raw_page_text_sha256": "b" * 64,
            "detail_image_count": 0,
            "detail_image_status": "absent",
            "review_sources": [
                "parameter_table",
                "product_introduction",
            ],
            "detail_images": [],
        },
        detail_image_dir=tmp_path / "missing-images",
        source_match="exact",
        canonical_specification=None,
        source_sku="150ml",
        reference_price_sku="unresolved",
        display_specification=None,
        price_specification_alignment="unresolved",
    )

    assert packet["detail_image_status"] == "absent"
    assert packet["detail_images"] == []
    assert packet["candidate_facts"] == []


def test_review_packet_rejects_local_image_hash_mismatch(
    tmp_path: Path,
) -> None:
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    (image_dir / "001_wrong.jpg").write_bytes(b"wrong")

    with pytest.raises(
        SmzdmProductReviewPacketError,
        match="detail image file does not match raw capture",
    ):
        build_product_review_packet(
            target={
                "canonical_product_id": 46,
                "canonical_product_identity": "理肤泉B5霜",
                "category_profile": "skincare",
                "portfolio_role": "entry_repair_cream",
                "sku_scope": "canonical_single_product_40ml",
                "missing_fields": ["texture"],
            },
            raw_capture={
                "canonical_product_id": 46,
                "page_url": "https://wiki.smzdm.com/p/example/",
                "captured_at": "2026-08-20T00:00:00+00:00",
                "page_title": "理肤泉B5霜 40ml",
                "product_title": "理肤泉B5霜 40ml",
                "parameter_text": "净含量 40ml",
                "product_introduction": "柔润乳霜质地",
                "raw_page_text_sha256": "a" * 64,
                "detail_image_count": 1,
                "detail_image_status": "present",
                "review_sources": [
                    "parameter_table",
                    "product_introduction",
                    "detail_images",
                ],
                "detail_images": [
                    {
                        "ordinal": 1,
                        "source_url": "https://y.zdmimg.com/detail.jpg",
                        "sha256": "c" * 64,
                        "width": 600,
                        "height": 800,
                    }
                ],
            },
            detail_image_dir=image_dir,
            source_match="exact",
            canonical_specification="40ml",
            source_sku="40ml",
            reference_price_sku="40ml",
            display_specification="40ml",
            price_specification_alignment="aligned",
        )


def test_reviewed_product_46_passes_manual_decision_integrity() -> None:
    root = Path(__file__).resolve().parents[3]
    packet = json.loads(
        (
            root
            / "docs/audits/smzdm-data/reviewed-products/product-46-v1.json"
        ).read_text(encoding="utf-8")
    )

    validated = validate_reviewed_product_packet(packet)

    assert validated["review_status"] == "human_review_complete"
    assert [
        fact["decision"]
        for fact in validated["candidate_facts"]
    ] == [
        "reject",
        "leave_free",
        "map",
        "map",
        "leave_free",
    ]


def test_every_completed_smzdm_product_review_passes_integrity() -> None:
    root = Path(__file__).resolve().parents[3]
    review_paths = tuple(sorted(
        (
            root / "docs/audits/smzdm-data/reviewed-products"
        ).glob("product-*.json")
    ))

    assert review_paths
    for path in review_paths:
        packet = json.loads(path.read_text(encoding="utf-8"))
        validate_reviewed_product_packet(packet)


def test_manual_review_rejects_map_without_concept() -> None:
    with pytest.raises(
        SmzdmProductReviewPacketError,
        match="map decision requires concept_id",
    ):
        validate_reviewed_product_packet({
            "product_id": 46,
            "review_status": "human_review_complete",
            "review_field_policy": ["texture"],
            "source_page_text_sha256": "a" * 64,
            "detail_images": [],
            "sku_audit": {
                "identity_status": "exact_product",
                "source_sku": "40ml",
                "canonical_sku": "40ml",
                "reference_price_sku": "40ml",
                "display_specification": "40ml",
                "price_specification_alignment": "aligned",
            },
            "candidate_facts": [
                {
                    "fact_id": "reviewed:product:46:texture:test-v1",
                    "field_key": "texture",
                    "public_text": "绵密乳霜",
                    "source_kind": "product_introduction",
                    "source_ordinal": None,
                    "source_refs": ["smzdm-browser-body:" + "a" * 64],
                    "sku_status": "exact",
                    "decision": "map",
                    "concept_id": None,
                    "allowed_uses": ["comparison"],
                    "promotion_status": "approved_non_price_fact",
                    "review_rationale": "用于测试。",
                }
            ],
        })


def test_manual_review_rejects_source_ref_not_owned_by_packet() -> None:
    with pytest.raises(
        SmzdmProductReviewPacketError,
        match="source_refs are not owned by review packet",
    ):
        validate_reviewed_product_packet({
            "product_id": 52,
            "review_status": "human_review_complete",
            "review_field_policy": ["spf_pa"],
            "source_page_text_sha256": "a" * 64,
            "detail_images": [],
            "sku_audit": {
                "identity_status": "exact_product",
                "source_sku": "30ml",
                "canonical_sku": "30ml",
                "reference_price_sku": "30ml",
                "display_specification": "30ml",
                "price_specification_alignment": "aligned",
            },
            "candidate_facts": [
                {
                    "fact_id": "reviewed:product:52:spf-pa:test-v1",
                    "field_key": "spf_pa",
                    "public_text": "SPF50+ / PA++++",
                    "source_kind": "parameter_table",
                    "source_ordinal": None,
                    "source_refs": ["smzdm-browser-body:" + "b" * 64],
                    "sku_status": "exact",
                    "decision": "leave_free",
                    "concept_id": None,
                    "allowed_uses": ["product_knowledge"],
                    "promotion_status": "approved_non_price_fact",
                    "review_rationale": "用于测试。",
                }
            ],
        })


def test_manual_review_rejects_detail_ref_from_different_ordinal() -> None:
    with pytest.raises(
        SmzdmProductReviewPacketError,
        match="source_ordinal does not match source_refs",
    ):
        validate_reviewed_product_packet({
            "product_id": 52,
            "review_status": "human_review_complete",
            "review_field_policy": ["texture"],
            "source_page_text_sha256": "a" * 64,
            "detail_images": [
                {"ordinal": 1, "sha256": "b" * 64},
                {"ordinal": 2, "sha256": "c" * 64},
            ],
            "sku_audit": {
                "identity_status": "exact_product",
                "source_sku": "30ml",
                "canonical_sku": "30ml",
                "reference_price_sku": "30ml",
                "display_specification": "30ml",
                "price_specification_alignment": "aligned",
            },
            "candidate_facts": [
                {
                    "fact_id": "reviewed:product:52:texture:test-v1",
                    "field_key": "texture",
                    "public_text": "轻盈乳液",
                    "source_kind": "detail_image",
                    "source_ordinal": 1,
                    "source_refs": ["smzdm-detail-image:" + "c" * 64],
                    "sku_status": "exact",
                    "decision": "map",
                    "concept_id": "texture.lightweight",
                    "allowed_uses": ["comparison"],
                    "promotion_status": "approved_non_price_fact",
                    "review_rationale": "用于测试。",
                }
            ],
        })


def test_manual_review_rejects_detail_image_without_ordinal() -> None:
    with pytest.raises(
        SmzdmProductReviewPacketError,
        match="detail image source requires source_ordinal",
    ):
        validate_reviewed_product_packet({
            "product_id": 52,
            "review_status": "human_review_complete",
            "review_field_policy": ["texture"],
            "source_page_text_sha256": "a" * 64,
            "detail_images": [
                {"ordinal": 1, "sha256": "b" * 64},
            ],
            "sku_audit": {
                "identity_status": "exact_product",
                "source_sku": "30ml",
                "canonical_sku": "30ml",
                "reference_price_sku": "30ml",
                "display_specification": "30ml",
                "price_specification_alignment": "aligned",
            },
            "candidate_facts": [
                {
                    "fact_id": "reviewed:product:52:texture:test-v1",
                    "field_key": "texture",
                    "public_text": "轻盈乳液",
                    "source_kind": "detail_image",
                    "source_ordinal": None,
                    "source_refs": ["smzdm-detail-image:" + "b" * 64],
                    "sku_status": "exact",
                    "decision": "map",
                    "concept_id": "texture.lightweight",
                    "allowed_uses": ["comparison"],
                    "promotion_status": "approved_non_price_fact",
                    "review_rationale": "用于测试。",
                }
            ],
        })


def test_manual_review_rejects_text_source_without_body_ref() -> None:
    with pytest.raises(
        SmzdmProductReviewPacketError,
        match="text source requires browser body ref",
    ):
        validate_reviewed_product_packet({
            "product_id": 52,
            "review_status": "human_review_complete",
            "review_field_policy": ["spf_pa"],
            "source_page_text_sha256": "a" * 64,
            "detail_images": [
                {"ordinal": 1, "sha256": "b" * 64},
            ],
            "sku_audit": {
                "identity_status": "exact_product",
                "source_sku": "30ml",
                "canonical_sku": "30ml",
                "reference_price_sku": "30ml",
                "display_specification": "30ml",
                "price_specification_alignment": "aligned",
            },
            "candidate_facts": [
                {
                    "fact_id": "reviewed:product:52:spf-pa:test-v1",
                    "field_key": "spf_pa",
                    "public_text": "SPF50+ / PA++++",
                    "source_kind": "parameter_table",
                    "source_ordinal": None,
                    "source_refs": ["smzdm-detail-image:" + "b" * 64],
                    "sku_status": "exact",
                    "decision": "leave_free",
                    "concept_id": None,
                    "allowed_uses": ["product_knowledge"],
                    "promotion_status": "approved_non_price_fact",
                    "review_rationale": "用于测试。",
                }
            ],
        })


def test_completed_review_requires_explicit_sku_audit() -> None:
    with pytest.raises(
        SmzdmProductReviewPacketError,
        match="sku_audit must be an object",
    ):
        validate_reviewed_product_packet({
            "product_id": 73,
            "review_status": "no_promotion",
            "review_field_policy": ["texture"],
            "detail_images": [],
            "candidate_facts": [],
        })


def test_aligned_price_and_specification_require_one_exact_sku() -> None:
    with pytest.raises(
        SmzdmProductReviewPacketError,
        match="aligned price and specification require one exact SKU",
    ):
        validate_reviewed_product_packet({
            "product_id": 73,
            "review_status": "no_promotion",
            "review_field_policy": ["texture"],
            "detail_images": [],
            "candidate_facts": [],
            "sku_audit": {
                "identity_status": "exact_product",
                "source_sku": "15ml",
                "canonical_sku": "30ml",
                "reference_price_sku": "30ml",
                "display_specification": "30ml",
                "price_specification_alignment": "aligned",
            },
        })
