from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.guide.retrieval.product_evidence_assets import (
    load_product_evidence_assets,
)
from tools.guide_data.build_product_evidence import (
    ProductEvidenceBuildError,
    build_product_evidence,
)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(
            json.dumps(
                row,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    source_root = tmp_path / "source_ocr"
    image_root = tmp_path / "source_images"
    product_images = image_root / "78"
    source_root.mkdir()
    product_images.mkdir(parents=True)

    texts = [
        "舒敏保湿面膜适用于哪些肌肤问题？\n适合干痒泛红不适。",
        "91%消费者认同水润舒缓\n35名敏感肌消费者自评。",
        "适合敏感肌及特殊美容项目后使用。",
        "91%\n88%\n水润舒缓\n缓解刺痛",
        "会员满额礼，立即抢购。",
        "舒敏保湿面膜适用于哪些肌肤问题？\n适合干痒泛红不适。",
    ]
    images: list[dict[str, object]] = []
    for index, text in enumerate(texts):
        content = (
            b"same-image" if index in {0, 5} else f"image-{index}".encode()
        )
        image_sha = hashlib.sha256(content).hexdigest()
        file_name = f"{index:03d}_{image_sha[:16]}.jpg"
        (product_images / file_name).write_bytes(content)
        images.append(
            {
                "file": file_name,
                "image_sha256": image_sha,
                "local_image": f"source_images/78/{file_name}",
                "ocr_text": text,
                "size": [790, 1000],
                "size_kb": len(content) / 1024,
                "source_url": f"https://example.com/{file_name}",
            }
        )
    source_payload = {
        "pid": 78,
        "name": "测试面膜",
        "images": images,
        "source_origin": "https://item.example.com/78",
    }
    (source_root / "detail_78_ocr.json").write_text(
        json.dumps(
            source_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    audit_path = tmp_path / "audit.jsonl"
    _write_jsonl(
        audit_path,
        [
            {
                "product_id": 78,
                "source_file": "detail_78_ocr.json",
                "image_file": images[index]["file"],
                "image_index": index,
                "review_status": status,
                "rationale": rationale,
                "recovery_attempts": [],
                "duplicate_of_image_sha256": duplicate,
            }
            for index, status, rationale, duplicate in [
                (0, "accepted", "FAQ关系清晰。", None),
                (1, "accepted", "消费者自评与样本脚注清晰。", None),
                (2, "accepted", "安全风格商家宣称仅转录。", None),
                (3, "ambiguous", "多栏对应关系无法可靠确认。", None),
                (4, "irrelevant", "仅促销活动，无商品知识。", None),
                (
                    5,
                    "duplicate",
                    "与第0张图片字节相同。",
                    images[0]["image_sha256"],
                ),
            ]
        ],
    )

    review_path = tmp_path / "review.jsonl"
    common = {
        "product_id": 78,
        "source_file": "detail_78_ocr.json",
        "subject_scope": "exact_product",
        "variant_scope": None,
    }
    _write_jsonl(
        review_path,
        [
            {
                **common,
                "image_file": images[0]["file"],
                "image_index": 0,
                "image_region": [0, 0, 790, 1000],
                "management_label": "faq",
                "exact_text": texts[0],
                "plain_meaning": "该面膜适合干痒和泛红不适问题。",
                "relations": [
                    {
                        "subject": "舒敏保湿面膜",
                        "predicate": "answers_question",
                        "object": "适用于干痒泛红不适",
                    }
                ],
                "qualifiers": {},
                "free_descriptors": ["适用问题", "干痒", "泛红"],
                "review_status": "accepted",
                "allowed_uses": ["answer", "display"],
                "forbidden_uses": ["hard_filter", "safety_guarantee"],
                "review_rationale": "原图完整保留问答关系。",
                "selection_review": {
                    "decision": "answer_only",
                    "visual_confirmed": True,
                    "rationale": "FAQ适用问题保留回答，不在夹具中投影。",
                    "projections": [],
                },
            },
            {
                **common,
                "image_file": images[1]["file"],
                "image_index": 1,
                "image_region": [0, 0, 790, 1000],
                "management_label": "consumer_self_report",
                "exact_text": texts[1],
                "plain_meaning": "35名敏感肌消费者中91%认同水润舒缓。",
                "relations": [
                    {
                        "subject": "91%",
                        "predicate": "consumer_agrees",
                        "object": "水润舒缓",
                    }
                ],
                "qualifiers": {
                    "sample_size": 35,
                    "population": "敏感肌消费者",
                    "method": "消费者自评",
                    "disclaimer": "实际结果因人而异",
                },
                "free_descriptors": ["水润舒缓", "消费者认同"],
                "supporting_sources": [
                    {
                        "source_file": "detail_78_ocr.json",
                        "image_file": images[0]["file"],
                        "image_index": 0,
                        "image_region": [0, 0, 790, 1000],
                    }
                ],
                "review_status": "accepted",
                "allowed_uses": ["answer", "display", "weak_soft_rank"],
                "forbidden_uses": [
                    "hard_filter",
                    "safety_guarantee",
                    "clinical_effectiveness",
                ],
                "review_rationale": "百分比、结论和样本关系清晰。",
                "selection_review": {
                    "decision": "projected",
                    "visual_confirmed": True,
                    "rationale": "消费者自评可作为保湿偏好的弱软排证据。",
                    "projections": [
                        {
                            "field_key": "efficacy",
                            "normalized_value": "保湿",
                            "capabilities": ["soft_rank"],
                            "rank_strength": 1,
                            "safety_role": "ordinary",
                        }
                    ],
                },
            },
            {
                **common,
                "image_file": images[2]["file"],
                "image_index": 2,
                "image_region": [0, 0, 790, 1000],
                "management_label": "safety_transcript",
                "exact_text": texts[2],
                "plain_meaning": "商家称适合敏感肌及特殊美容项目后使用。",
                "relations": [],
                "qualifiers": {},
                "free_descriptors": ["敏感肌", "特殊美容项目后"],
                "review_status": "accepted",
                "allowed_uses": ["answer", "display"],
                "forbidden_uses": ["hard_filter", "safety_guarantee"],
                "review_rationale": "仅按安全宣传原文转录。",
                "selection_review": {
                    "decision": "answer_only",
                    "visual_confirmed": True,
                    "rationale": "夹具暂不授权安全宣传进入排序。",
                    "projections": [],
                },
            },
            {
                **common,
                "image_file": images[3]["file"],
                "image_index": 3,
                "image_region": [0, 0, 790, 1000],
                "management_label": "consumer_self_report",
                "exact_text": texts[3],
                "plain_meaning": "两个百分比与两个结论的对应关系不清楚。",
                "relations": [],
                "qualifiers": {},
                "free_descriptors": ["水润舒缓", "缓解刺痛"],
                "review_status": "ambiguous",
                "allowed_uses": [],
                "forbidden_uses": [
                    "hard_filter",
                    "safety_guarantee",
                    "clinical_effectiveness",
                ],
                "review_rationale": "线性文字不足以确认多栏对应关系。",
            },
        ],
    )
    return source_root, image_root, audit_path, review_path


def test_builder_is_deterministic_and_accounts_for_every_image(
    tmp_path: Path,
) -> None:
    source_root, image_root, audit_path, review_path = _fixture(tmp_path)

    first = build_product_evidence(
        source_root=source_root,
        image_root=image_root,
        audit_paths=(audit_path,),
        review_paths=(review_path,),
        output_root=tmp_path / "first",
    )
    second = build_product_evidence(
        source_root=source_root,
        image_root=image_root,
        audit_paths=(audit_path,),
        review_paths=(review_path,),
        output_root=tmp_path / "second",
    )

    assert first.evidence_path.read_bytes() == second.evidence_path.read_bytes()
    assert first.audit_path.read_bytes() == second.audit_path.read_bytes()
    assert first.manifest_path.read_bytes() == second.manifest_path.read_bytes()

    assets = load_product_evidence_assets(
        manifest_path=first.manifest_path,
        evidence_path=first.evidence_path,
        audit_path=first.audit_path,
    )
    assert assets.manifest.evidence_count == 4
    assert assets.manifest.image_count == 6
    assert assets.manifest.status_counts == {
        "accepted": 3,
        "ambiguous": 1,
        "duplicate": 1,
        "irrelevant": 1,
    }
    ambiguous = next(
        item for item in assets.evidence if item.review_status == "ambiguous"
    )
    assert not ambiguous.allowed_uses
    assert any(
        ambiguous.evidence_id in audit.evidence_ids
        for audit in assets.audit
    )
    consumer = next(
        item
        for item in assets.evidence
        if item.management_label == "consumer_self_report"
        and item.review_status == "accepted"
    )
    assert consumer.supporting_sources[0].image_index == 0
    assert consumer.selection_review is not None
    assert consumer.selection_review.projections[0].field_key == "efficacy"
    assert consumer.selection_review.projections[0].rank_strength == 1


def test_concept_audit_normalizes_and_deduplicates_selection_projections(
    tmp_path: Path,
) -> None:
    source_root, image_root, audit_path, review_path = _fixture(tmp_path)
    rows = [
        json.loads(line)
        for line in review_path.read_text(encoding="utf-8").splitlines()
    ]
    rows[1]["selection_review"]["projections"] = [
        {
            "field_key": "efficacy",
            "normalized_value": old_value,
            "capabilities": ["soft_rank"],
            "rank_strength": 1,
            "safety_role": "ordinary",
        }
        for old_value in ("skin_refining", "smoothing")
    ]
    _write_jsonl(review_path, rows)
    concept_audit_path = tmp_path / "concept-audit.jsonl"
    _write_jsonl(
        concept_audit_path,
        [
            {
                "product_id": 78,
                "subject_scope": "exact_product",
                "variant_scope": None,
                "field_key": "efficacy",
                "old_value": old_value,
                "decision": "normalize",
                "new_field_key": "texture",
                "new_value": "平滑细腻",
                "rationale": "同一消费者肤感概念归入纹理槽。",
            }
            for old_value in ("skin_refining", "smoothing")
        ],
    )

    result = build_product_evidence(
        source_root=source_root,
        image_root=image_root,
        audit_paths=(audit_path,),
        review_paths=(review_path,),
        output_root=tmp_path / "output",
        concept_audit_path=concept_audit_path,
    )
    assets = load_product_evidence_assets(
        manifest_path=result.manifest_path,
        evidence_path=result.evidence_path,
        audit_path=result.audit_path,
    )
    consumer = next(
        row
        for row in assets.evidence
        if row.management_label == "consumer_self_report"
        and row.review_status == "accepted"
    )

    assert consumer.selection_review is not None
    assert [
        (
            projection.field_key,
            projection.normalized_value,
            projection.rank_strength,
        )
        for projection in consumer.selection_review.projections
    ] == [("texture", "平滑细腻", 1)]


def test_jsonl_serialization_is_stable_across_python_hash_seeds() -> None:
    script = """
from tools.guide_data.build_product_evidence import _jsonl_bytes
value = list(frozenset({"answer", "display", "compare", "weak_soft_rank"}))
print(_jsonl_bytes([{"allowed_uses": value}]).decode("utf-8"), end="")
"""
    outputs = []
    for seed in ("1", "2"):
        environment = dict(os.environ)
        environment["PYTHONHASHSEED"] = seed
        outputs.append(
            subprocess.check_output(
                [sys.executable, "-c", script],
                cwd=Path(__file__).resolve().parents[3],
                env=environment,
                text=True,
            )
        )

    assert outputs[0] == outputs[1]


def test_builder_rejects_unreviewed_source_image(tmp_path: Path) -> None:
    source_root, image_root, audit_path, review_path = _fixture(tmp_path)
    audit_rows = audit_path.read_text(encoding="utf-8").splitlines()
    audit_path.write_text(
        "\n".join(audit_rows[:-1]) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ProductEvidenceBuildError,
        match="source image is missing an audit decision",
    ):
        build_product_evidence(
            source_root=source_root,
            image_root=image_root,
            audit_paths=(audit_path,),
            review_paths=(review_path,),
            output_root=tmp_path / "out",
        )


def test_builder_rejects_review_bound_to_wrong_image(tmp_path: Path) -> None:
    source_root, image_root, audit_path, review_path = _fixture(tmp_path)
    rows = [
        json.loads(line)
        for line in review_path.read_text(encoding="utf-8").splitlines()
    ]
    rows[0]["image_file"] = "wrong.jpg"
    _write_jsonl(review_path, rows)

    with pytest.raises(
        ProductEvidenceBuildError,
        match="review image binding is invalid",
    ):
        build_product_evidence(
            source_root=source_root,
            image_root=image_root,
            audit_paths=(audit_path,),
            review_paths=(review_path,),
            output_root=tmp_path / "out",
        )


def test_builder_accepts_explicit_visual_transcription(
    tmp_path: Path,
) -> None:
    source_root, image_root, audit_path, review_path = _fixture(tmp_path)
    rows = [
        json.loads(line)
        for line in review_path.read_text(encoding="utf-8").splitlines()
    ]
    rows[0]["exact_text"] = "人工逐图核验的清晰原文"
    rows[0]["transcription_basis"] = "visual_transcription"
    _write_jsonl(review_path, rows)

    result = build_product_evidence(
        source_root=source_root,
        image_root=image_root,
        audit_paths=(audit_path,),
        review_paths=(review_path,),
        output_root=tmp_path / "out",
    )
    assets = load_product_evidence_assets(
        manifest_path=result.manifest_path,
        evidence_path=result.evidence_path,
        audit_path=result.audit_path,
    )

    assert any(
        item.exact_text == "人工逐图核验的清晰原文"
        and item.transcription_basis == "visual_transcription"
        for item in assets.evidence
    )


def test_accepted_image_can_preserve_an_ambiguous_content_block(
    tmp_path: Path,
) -> None:
    source_root, image_root, audit_path, review_path = _fixture(tmp_path)
    rows = [
        json.loads(line)
        for line in review_path.read_text(encoding="utf-8").splitlines()
    ]
    rows.append(
        {
            **rows[0],
            "exact_text": "适合干痒泛红不适。",
            "plain_meaning": "图中另一个小字限定无法可靠确认。",
            "relations": [],
            "free_descriptors": ["小字限定"],
            "review_status": "ambiguous",
            "allowed_uses": [],
            "review_rationale": "同一张图的主体问答清楚，小字限定仍有歧义。",
            "selection_review": None,
        }
    )
    _write_jsonl(review_path, rows)

    result = build_product_evidence(
        source_root=source_root,
        image_root=image_root,
        audit_paths=(audit_path,),
        review_paths=(review_path,),
        output_root=tmp_path / "out",
    )
    assets = load_product_evidence_assets(
        manifest_path=result.manifest_path,
        evidence_path=result.evidence_path,
        audit_path=result.audit_path,
    )

    image_audit = next(item for item in assets.audit if item.image_index == 0)
    bound = [
        item
        for item in assets.evidence
        if item.evidence_id in image_audit.evidence_ids
    ]
    assert {item.review_status for item in bound} == {
        "accepted",
        "ambiguous",
    }


def test_accepted_image_requires_at_least_one_accepted_content_block(
    tmp_path: Path,
) -> None:
    source_root, image_root, audit_path, review_path = _fixture(tmp_path)
    rows = [
        json.loads(line)
        for line in review_path.read_text(encoding="utf-8").splitlines()
    ]
    rows[0]["review_status"] = "ambiguous"
    rows[0]["allowed_uses"] = []
    rows[0]["selection_review"] = None
    _write_jsonl(review_path, rows)

    with pytest.raises(
        ProductEvidenceBuildError,
        match="accepted image audit requires accepted evidence",
    ):
        build_product_evidence(
            source_root=source_root,
            image_root=image_root,
            audit_paths=(audit_path,),
            review_paths=(review_path,),
            output_root=tmp_path / "out",
        )


def test_builder_resolves_current_version_from_recovery_manifest(
    tmp_path: Path,
) -> None:
    source_root, image_root, audit_path, review_path = _fixture(tmp_path)
    source_path = source_root / "detail_78_ocr.json"
    source_payload = json.loads(source_path.read_text(encoding="utf-8"))
    image = source_payload["images"][0]
    old_file = str(image["file"])
    image_sha = str(image["image_sha256"])
    current_file = f"000_current_{image_sha[:16]}.jpg"
    (image_root / "78" / old_file).rename(
        image_root / "78" / current_file
    )
    historical_file = "historical_detail_image.avif"
    image.update(
        {
            "file": historical_file,
            "image_sha256": None,
            "local_image": None,
            "source_url": None,
        }
    )
    source_path.write_text(
        json.dumps(
            source_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()

    audit_rows = [
        json.loads(line)
        for line in audit_path.read_text(encoding="utf-8").splitlines()
    ]
    audit_rows[0]["image_file"] = historical_file
    _write_jsonl(audit_path, audit_rows)

    review_rows = [
        json.loads(line)
        for line in review_path.read_text(encoding="utf-8").splitlines()
    ]
    review_rows[0]["image_file"] = historical_file
    for row in review_rows:
        for supporting in row.get("supporting_sources", []):
            if supporting["image_index"] == 0:
                supporting["image_file"] = historical_file
    _write_jsonl(review_path, review_rows)

    recovery_path = tmp_path / "recovery.jsonl"
    _write_jsonl(
        recovery_path,
        [
            {
                "attempts": [
                    "existing_local",
                    "old_asset",
                    "saved_html",
                    "current_source",
                ],
                "historical_file": historical_file,
                "image_index": 0,
                "image_sha256": image_sha,
                "local_image": f"source_images/78/{current_file}",
                "product_id": 78,
                "reason": None,
                "recovered_file": "downloaded-current-version.jpg",
                "recovery_source": "current_source",
                "source_file": "detail_78_ocr.json",
                "source_sha256": source_sha,
                "source_url": "https://example.com/current-version.jpg",
                "status": "current_new_version",
            }
        ],
    )

    result = build_product_evidence(
        source_root=source_root,
        image_root=image_root,
        audit_paths=(audit_path,),
        review_paths=(review_path,),
        output_root=tmp_path / "out",
        recovery_paths=(recovery_path,),
    )
    assets = load_product_evidence_assets(
        manifest_path=result.manifest_path,
        evidence_path=result.evidence_path,
        audit_path=result.audit_path,
    )

    faq = next(item for item in assets.evidence if item.source.image_index == 0)
    assert faq.source.image_file == historical_file
    assert faq.source.resolved_image_file == current_file
    assert faq.source.recovery_status == "current_new_version"
    assert faq.source.source_url == "https://example.com/current-version.jpg"
