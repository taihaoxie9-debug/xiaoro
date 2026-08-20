from __future__ import annotations

import json
from pathlib import Path

from app.guide.retrieval.category_profiles import CategoryProfile
from tools.guide_data.curate_ocr_review_candidates import (
    curate_ocr_review_candidates,
)


def _write_source(
    root: Path,
    *,
    pid: int,
    image_file: str,
    ocr_text: str,
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"detail_{pid}_ocr.json").write_text(
        json.dumps(
            {
                "pid": pid,
                "images": [
                    {
                        "file": image_file,
                        "ocr_text": ocr_text,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_curates_agent_schemas_without_discovering_claims(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "ocr"
    _write_source(
        source_root,
        pid=114,
        image_file="lip.jpg",
        ocr_text="一抹\n显色 践行零残忍",
    )
    _write_source(
        source_root,
        pid=58,
        image_file="sun.jpg",
        ocr_text="户外首选 一抹成膜自然哑光",
    )
    review = tmp_path / "review.jsonl"
    rows = [
        {
            "pid": 114,
            "field_key": "color_payoff",
            "display_claim": "一抹 显色",
            "normalized_value": "显色",
            "scope": {"level": "product"},
            "source_basename": "detail_114_ocr.json",
            "image_file": "lip.jpg",
            "image_index": 1,
            "rationale": "彩妆显色度审查",
        },
        {
            "pid": 114,
            "field_key": "safety_claim",
            "display_claim": "践行零残忍",
            "normalized_value": "品牌宣称拒绝动物实验",
            "scope": "brand_safety",
            "source_basename": "detail_114_ocr.json",
            "image_file": "lip.jpg",
            "image_index": 1,
            "rationale": "商家安全宣称仅转录",
        },
        {
            "product_id": 58,
            "field_key": "usage_scenario",
            "display_claim": "户外首选",
            "normalized_value": "户外",
            "claim_scope": "exact_product",
            "source_json": "detail_58_ocr.json",
            "image_file": "sun.jpg",
            "image_index": 1,
            "rationale": "防晒使用场景",
        },
        {
            "product_id": 58,
            "field_key": "finish",
            "display_claim": "一抹成膜自然哑光",
            "normalized_value": "自然哑光",
            "claim_scope": "exact_product",
            "source_json": "detail_58_ocr.json",
            "image_file": "sun.jpg",
            "image_index": 1,
            "rationale": "防晒成膜后的表面效果",
        },
        {
            "product_id": 58,
            "field_key": "texture",
            "display_claim": "并不存在于原文",
            "normalized_value": "清爽",
            "claim_scope": "exact_product",
            "source_json": "detail_58_ocr.json",
            "image_file": "sun.jpg",
            "image_index": 1,
            "rationale": "错误候选必须拒绝",
        },
    ]
    review.write_text(
        "\n".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True)
            for row in rows
        ),
        encoding="utf-8",
    )

    result = curate_ocr_review_candidates(
        source_root=source_root,
        review_paths=(review,),
        output_root=tmp_path / "curated",
        product_profiles={
            114: CategoryProfile.COLOR_MAKEUP,
            58: CategoryProfile.SUNCARE,
        },
    )
    accepted = [
        json.loads(line)
        for line in result.candidates_path.read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    rejected = [
        json.loads(line)
        for line in result.rejections_path.read_text(
            encoding="utf-8"
        ).splitlines()
    ]

    assert result.accepted_count == 4
    assert result.rejected_count == 1
    assert result.rejection_counts == {
        "display_claim_not_exact": 1,
    }
    assert {
        (row["product_id"], row["field_key"], row["claim_scope"])
        for row in accepted
    } == {
        (114, "color_payoff", "ordinary"),
        (114, "safety_claim", "safety_transcript"),
        (58, "usage_context", "ordinary"),
        (58, "finish", "ordinary"),
    }
    assert next(
        row
        for row in accepted
        if row["field_key"] == "color_payoff"
    )["display_claim"] == "一抹\n显色"
    assert all(row["image_index"] == 0 for row in accepted)
    assert rejected[0]["reason"] == "display_claim_not_exact"


def test_rejects_consumer_testimonial_instead_of_upgrading_it(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "ocr"
    _write_source(
        source_root,
        pid=68,
        image_file="review.jpg",
        ocr_text="泡沫真的好绵密",
    )
    review = tmp_path / "review.jsonl"
    review.write_text(
        json.dumps(
            {
                "product_id": 68,
                "field_key": "texture",
                "display_claim": "泡沫真的好绵密",
                "normalized_value": "泡沫绵密",
                "claim_scope": "review_transcript",
                "source": "detail_68_ocr.json",
                "image_file": "review.jpg",
                "image_index": 0,
                "rationale": "详情页用户证言",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = curate_ocr_review_candidates(
        source_root=source_root,
        review_paths=(review,),
        output_root=tmp_path / "curated",
        product_profiles={68: CategoryProfile.CLEANSER},
    )

    assert result.accepted_count == 0
    assert result.rejection_counts == {
        "consumer_review_transcript": 1,
    }


def test_applies_explicit_row_decisions_without_keyword_scanning(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "ocr"
    _write_source(
        source_root,
        pid=55,
        image_file="sun.jpg",
        ocr_text="敏感肌适用 清爽易推开",
    )
    review = tmp_path / "review.jsonl"
    review.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "product_id": 55,
                        "field_key": "suitable_skin",
                        "display_claim": "敏感肌适用",
                        "normalized_value": "敏感肌",
                        "claim_scope": "exact_product",
                        "source_json": "detail_55_ocr.json",
                        "image_file": "sun.jpg",
                        "image_index": 1,
                        "rationale": "代理提名为普通肤质",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "product_id": 55,
                        "field_key": "finish",
                        "display_claim": "清爽易推开",
                        "normalized_value": "清爽",
                        "claim_scope": "exact_product",
                        "source_json": "detail_55_ocr.json",
                        "image_file": "sun.jpg",
                        "image_index": 1,
                        "rationale": "代理提名为表面效果",
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )
    decisions = tmp_path / "decisions.jsonl"
    decisions.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "source_review_file": "review.jsonl",
                        "source_line": 1,
                        "action": "safety_transcript",
                        "target_field": None,
                        "rationale": "敏感肌适用属于安全风格宣称",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "source_review_file": "review.jsonl",
                        "source_line": 2,
                        "action": "remap_field",
                        "target_field": "texture",
                        "rationale": "防晒易推开描述的是肤感",
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )

    result = curate_ocr_review_candidates(
        source_root=source_root,
        review_paths=(review,),
        decision_path=decisions,
        output_root=tmp_path / "curated",
        product_profiles={55: CategoryProfile.SUNCARE},
    )
    accepted = [
        json.loads(line)
        for line in result.candidates_path.read_text(
            encoding="utf-8"
        ).splitlines()
    ]

    assert {
        (
            row["field_key"],
            row["claim_scope"],
            row["normalized_value"],
        )
        for row in accepted
    } == {
        ("safety_claim", "safety_transcript", "商家安全宣称"),
        ("texture", "ordinary", "清爽"),
    }
    assert all(
        "主线程裁决" in row["rationale"] for row in accepted
    )


def test_applies_exact_source_recovery_to_one_review_row(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "ocr"
    _write_source(
        source_root,
        pid=59,
        image_file="claim.jpg",
        ocr_text="1周更细腻\nSK-I\n紧致透亮",
    )
    review = tmp_path / "review.jsonl"
    review.write_text(
        json.dumps(
            {
                "pid": 59,
                "field_key": "efficacy",
                "exact_display_claim": "1周更细腻\n紧致透亮",
                "normalized_value": "一周改善细腻度、紧致度和透亮度",
                "scope": "product_claim",
                "source": "detail_59_ocr.json",
                "image_file": "claim.jpg",
                "image_index": 0,
                "rationale": "代理整理了 OCR 排版",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    recovery = tmp_path / "recovery.jsonl"
    recovery.write_text(
        json.dumps(
            {
                "source_review_file": "review.jsonl",
                "source_line": 1,
                "replacement_display_claim": (
                    "1周更细腻\nSK-I\n紧致透亮"
                ),
                "replacement_normalized_value": None,
                "rationale": "按源 OCR 恢复品牌插行",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = curate_ocr_review_candidates(
        source_root=source_root,
        review_paths=(review,),
        recovery_path=recovery,
        output_root=tmp_path / "curated",
        product_profiles={59: CategoryProfile.SKINCARE},
    )
    accepted = [
        json.loads(line)
        for line in result.candidates_path.read_text(
            encoding="utf-8"
        ).splitlines()
    ]

    assert result.accepted_count == 1
    assert result.rejected_count == 0
    assert accepted[0]["display_claim"] == (
        "1周更细腻\nSK-I\n紧致透亮"
    )
    assert accepted[0]["normalized_value"] == (
        "一周改善细腻度、紧致度和透亮度"
    )
    assert "主线程恢复" in accepted[0]["rationale"]
