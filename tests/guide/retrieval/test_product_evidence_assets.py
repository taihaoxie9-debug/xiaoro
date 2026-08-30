from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.guide.retrieval.product_evidence_assets import (
    ImageAuditRecord,
    ProductEvidenceAssetIntegrityError,
    ProductEvidenceBlock,
    load_product_evidence_assets,
    product_evidence_id,
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _source() -> dict[str, object]:
    return {
        "source_file": "detail_78_ocr.json",
        "source_sha256": "1" * 64,
        "image_file": "004_claim.jpg",
        "image_index": 4,
        "image_sha256": "2" * 64,
        "source_locator": (
            "urn:xiaoro:product-detail-image:pid:78:"
            f"source-sha256:{'1' * 64}:image-sha256:{'2' * 64}"
        ),
        "source_url": "https://example.com/claim.jpg",
        "recovery_status": "source_record",
        "resolved_image_file": "004_claim.jpg",
        "image_region": [0, 0, 790, 1364],
    }


def _accepted_payload(
    *,
    management_label: str = "consumer_self_report",
    allowed_uses: list[str] | None = None,
    forbidden_uses: list[str] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "product_id": 78,
        "subject_scope": "exact_product",
        "variant_scope": None,
        "management_label": management_label,
        "exact_text": "91%消费者认同水润舒缓",
        "plain_meaning": "消费者认同水润舒缓",
        "relations": [
            {
                "subject": "91%",
                "predicate": "consumer_agrees",
                "object": "水润舒缓",
            }
        ],
        "qualifiers": {
            "sample_size": 35,
            "population": "18-35岁中国敏感肌消费者",
            "method": "消费者自评",
            "baseline": None,
            "duration": None,
            "disclaimer": "结果仅供参考，实际结果因人而异",
            "footnotes": ["来源于第三方测试报告"],
        },
        "free_descriptors": ["消费者认同", "水润舒缓"],
        "review_status": "accepted",
        "allowed_uses": (
            ["answer", "display", "weak_soft_rank"]
            if allowed_uses is None
            else allowed_uses
        ),
        "forbidden_uses": (
            [
                "hard_filter",
                "safety_guarantee",
                "clinical_effectiveness",
            ]
            if forbidden_uses is None
            else forbidden_uses
        ),
        "review_rationale": "图片与脚注共同给出消费者自评关系。",
        "selection_review": {
            "decision": "answer_only",
            "visual_confirmed": True,
            "rationale": "测试夹具默认不投影到选择事实。",
            "projections": [],
        },
        "source": _source(),
    }
    return payload


def _block(**overrides: object) -> ProductEvidenceBlock:
    payload = _accepted_payload()
    payload.update(overrides)
    return ProductEvidenceBlock.model_validate(
        {
            "evidence_id": product_evidence_id(payload),
            **payload,
        },
        strict=True,
    )


def test_accepted_evidence_is_answerable_and_content_addressed() -> None:
    block = _block()

    assert "answer" in block.allowed_uses
    assert block.qualifiers.sample_size == 35
    assert block.relations[0].predicate == "consumer_agrees"
    assert block.source.image_region == (0, 0, 790, 1364)


def test_accepted_evidence_requires_selection_use_review() -> None:
    payload = _accepted_payload()
    payload.pop("selection_review")

    with pytest.raises(
        ValidationError,
        match="accepted evidence requires selection use review",
    ):
        ProductEvidenceBlock.model_validate(
            {
                "evidence_id": product_evidence_id(payload),
                **payload,
            },
            strict=True,
        )


def test_reviewed_projection_is_visually_confirmed_and_bounded() -> None:
    payload = _accepted_payload(
        allowed_uses=[
            "answer",
            "compare",
            "display",
            "weak_soft_rank",
        ]
    )
    payload["selection_review"] = {
        "decision": "projected",
        "visual_confirmed": True,
        "rationale": "消费者自评可作为保湿偏好的弱软排证据。",
        "projections": [
            {
                "field_key": "efficacy",
                "normalized_value": "保湿",
                "capabilities": ["compare", "soft_rank"],
                "rank_strength": 1,
                "safety_role": "ordinary",
            }
        ],
    }

    block = ProductEvidenceBlock.model_validate(
        {
            "evidence_id": product_evidence_id(payload),
            **payload,
        },
        strict=True,
    )

    assert block.selection_review is not None
    assert block.selection_review.visual_confirmed is True
    assert block.selection_review.projections[0].rank_strength == 1


def test_selection_projection_json_capabilities_are_sorted() -> None:
    payload = _accepted_payload(
        allowed_uses=[
            "answer",
            "compare",
            "display",
            "weak_soft_rank",
        ]
    )
    payload["selection_review"] = {
        "decision": "projected",
        "visual_confirmed": True,
        "rationale": "消费者自评可作为保湿偏好的弱软排证据。",
        "projections": [
            {
                "field_key": "efficacy",
                "normalized_value": "保湿",
                "capabilities": ["soft_rank", "compare"],
                "rank_strength": 1,
                "safety_role": "ordinary",
            }
        ],
    }

    block = ProductEvidenceBlock.model_validate(
        {
            "evidence_id": product_evidence_id(payload),
            **payload,
        },
        strict=True,
    )

    assert block.model_dump(mode="json")["selection_review"][
        "projections"
    ][0]["capabilities"] == ["compare", "soft_rank"]


def test_nonfacet_comparison_can_skip_rank_projection() -> None:
    payload = _accepted_payload(
        management_label="product_specification",
        allowed_uses=["answer", "compare", "display"],
        forbidden_uses=["hard_filter", "safety_guarantee"],
    )
    payload["selection_review"] = {
        "decision": "comparison_only",
        "visual_confirmed": True,
        "rationale": "版本映射可用于逐项比较，但不是通用排序维度。",
        "projections": [],
    }

    block = ProductEvidenceBlock.model_validate(
        {
            "evidence_id": product_evidence_id(payload),
            **payload,
        },
        strict=True,
    )

    assert block.selection_review is not None
    assert block.selection_review.decision == "comparison_only"
    assert not block.selection_review.projections


def test_complete_ingredient_label_can_project_more_than_32_items() -> None:
    payload = _accepted_payload(
        management_label="packaging_information",
        allowed_uses=["answer", "compare", "display", "hard_filter"],
        forbidden_uses=["safety_guarantee"],
    )
    payload["selection_review"] = {
        "decision": "projected",
        "visual_confirmed": True,
        "rationale": "完整中文标签成分逐项投影，保留硬包含查询能力。",
        "projections": [
            {
                "field_key": "ingredients_present",
                "normalized_value": f"标签成分{index}",
                "capabilities": ["compare", "hard_filter"],
                "rank_strength": None,
                "safety_role": "ordinary",
            }
            for index in range(40)
        ],
    }

    block = ProductEvidenceBlock.model_validate(
        {
            "evidence_id": product_evidence_id(payload),
            **payload,
        },
        strict=True,
    )

    assert block.selection_review is not None
    assert len(block.selection_review.projections) == 40


def test_nonaccepted_evidence_forbids_selection_use_review() -> None:
    payload = _accepted_payload(allowed_uses=[])
    payload.update(
        {
            "review_status": "ambiguous",
            "selection_review": {
                "decision": "answer_only",
                "visual_confirmed": True,
                "rationale": "关系仍有歧义。",
                "projections": [],
            },
        }
    )

    with pytest.raises(
        ValidationError,
        match="nonaccepted evidence forbids selection use review",
    ):
        ProductEvidenceBlock.model_validate(
            {
                "evidence_id": product_evidence_id(payload),
                **payload,
            },
            strict=True,
        )


def test_evidence_can_bind_a_distinct_supporting_footnote_image() -> None:
    supporting = {
        **_source(),
        "image_file": "012_footnotes.jpg",
        "image_index": 12,
        "image_sha256": "4" * 64,
        "source_locator": (
            "urn:xiaoro:product-detail-image:pid:78:"
            f"source-sha256:{'1' * 64}:image-sha256:{'4' * 64}"
        ),
        "source_url": "https://example.com/footnotes.jpg",
        "image_region": [0, 0, 790, 496],
    }
    block = _block(supporting_sources=[supporting])

    assert len(block.supporting_sources) == 1
    assert block.supporting_sources[0].image_index == 12


def test_visual_transcription_is_an_explicit_evidence_property() -> None:
    block = _block(
        exact_text="100%消费者认同膜布不易滑落",
        transcription_basis="visual_transcription",
    )

    assert block.transcription_basis == "visual_transcription"


def test_current_source_version_cannot_masquerade_as_historical_image() -> None:
    payload = _accepted_payload()
    payload["source"] = {
        **_source(),
        "recovery_status": "current_new_version",
        "resolved_image_file": "000_current_sha.jpg",
    }

    block = ProductEvidenceBlock.model_validate(
        {
            "evidence_id": product_evidence_id(payload),
            **payload,
        },
        strict=True,
    )

    assert block.source.image_file == "004_claim.jpg"
    assert block.source.resolved_image_file == "000_current_sha.jpg"
    assert block.source.recovery_status == "current_new_version"


def test_accepted_evidence_without_answer_capability_is_rejected() -> None:
    payload = _accepted_payload(allowed_uses=["display"])

    with pytest.raises(
        ValidationError,
        match="accepted evidence must be answerable",
    ):
        ProductEvidenceBlock.model_validate(
            {
                "evidence_id": product_evidence_id(payload),
                **payload,
            },
            strict=True,
        )


@pytest.mark.parametrize(
    "status",
    [
        "ambiguous",
        "irrelevant",
        "expired",
        "cross_product",
        "duplicate",
        "blocked",
    ],
)
def test_nonaccepted_evidence_cannot_expose_capabilities(status: str) -> None:
    payload = _accepted_payload()
    payload.update(
        {
            "review_status": status,
            "allowed_uses": ["answer"],
        }
    )

    with pytest.raises(
        ValidationError,
        match="nonaccepted evidence forbids allowed uses",
    ):
        ProductEvidenceBlock.model_validate(
            {
                "evidence_id": product_evidence_id(payload),
                **payload,
            },
            strict=True,
        )


def test_consumer_self_report_cannot_claim_clinical_effectiveness() -> None:
    payload = _accepted_payload(forbidden_uses=["hard_filter"])

    with pytest.raises(
        ValidationError,
        match="consumer self-report must forbid clinical effectiveness",
    ):
        ProductEvidenceBlock.model_validate(
            {
                "evidence_id": product_evidence_id(payload),
                **payload,
            },
            strict=True,
        )


def test_safety_transcript_cannot_hard_filter() -> None:
    payload = _accepted_payload(
        management_label="safety_transcript",
        allowed_uses=["answer", "display", "hard_filter"],
        forbidden_uses=["safety_guarantee"],
    )

    with pytest.raises(
        ValidationError,
        match="safety transcript cannot hard filter",
    ):
        ProductEvidenceBlock.model_validate(
            {
                "evidence_id": product_evidence_id(payload),
                **payload,
            },
            strict=True,
        )


def test_image_audit_requires_blocked_attempts_and_duplicate_reference() -> None:
    base = {
        "audit_id": "3" * 64,
        "product_id": 78,
        "source_file": "detail_78_ocr.json",
        "source_sha256": "1" * 64,
        "image_file": "004_claim.jpg",
        "image_index": 4,
        "image_sha256": None,
        "local_image": None,
        "review_status": "blocked",
        "rationale": "历史原图尚未恢复。",
        "recovery_attempts": [],
        "evidence_ids": [],
        "duplicate_of_image_sha256": None,
    }

    with pytest.raises(
        ValidationError,
        match="blocked audit requires recovery attempts",
    ):
        ImageAuditRecord.model_validate(base, strict=True)

    duplicate = {
        **base,
        "review_status": "duplicate",
        "recovery_attempts": [],
    }
    with pytest.raises(
        ValidationError,
        match="duplicate audit requires duplicate image SHA",
    ):
        ImageAuditRecord.model_validate(duplicate, strict=True)


def test_loader_rejects_manifest_or_jsonl_tampering(tmp_path: Path) -> None:
    block = _block()
    evidence_bytes = (
        _canonical_json(block.model_dump(mode="json")) + "\n"
    ).encode("utf-8")
    evidence_sha = hashlib.sha256(evidence_bytes).hexdigest()
    evidence_path = tmp_path / f"product_evidence_v1.{evidence_sha}.jsonl"
    evidence_path.write_bytes(evidence_bytes)

    audit_payload = {
        "audit_id": "3" * 64,
        "product_id": 78,
        "source_file": "detail_78_ocr.json",
        "source_sha256": "1" * 64,
        "image_file": "004_claim.jpg",
        "image_index": 4,
        "image_sha256": "2" * 64,
        "local_image": "source_images/78/004_claim.jpg",
        "review_status": "accepted",
        "rationale": "逐图核验完成。",
        "recovery_attempts": [],
        "evidence_ids": [block.evidence_id],
        "duplicate_of_image_sha256": None,
    }
    audit_bytes = (_canonical_json(audit_payload) + "\n").encode("utf-8")
    audit_sha = hashlib.sha256(audit_bytes).hexdigest()
    audit_path = tmp_path / f"image_audit_v1.{audit_sha}.jsonl"
    audit_path.write_bytes(audit_bytes)

    unsigned_manifest = {
        "schema_version": "product-evidence-v1",
        "asset_id": "guide-product-evidence-v1",
        "asset_version": f"product-evidence-v1:sha256:{evidence_sha}",
        "evidence_file": evidence_path.name,
        "evidence_sha256": evidence_sha,
        "audit_file": audit_path.name,
        "audit_sha256": audit_sha,
        "evidence_count": 1,
        "product_count": 1,
        "image_count": 1,
        "status_counts": {"accepted": 1},
        "allowed_use_counts": {
            "answer": 1,
            "display": 1,
            "weak_soft_rank": 1,
        },
    }
    manifest_payload = {
        **unsigned_manifest,
        "manifest_sha256": hashlib.sha256(
            _canonical_json(unsigned_manifest).encode("utf-8")
        ).hexdigest(),
    }
    manifest_path = tmp_path / "product_evidence_v1_manifest.json"
    manifest_path.write_text(
        _canonical_json(manifest_payload),
        encoding="utf-8",
    )

    assets = load_product_evidence_assets(
        manifest_path=manifest_path,
        evidence_path=evidence_path,
        audit_path=audit_path,
        expected_manifest_sha256=manifest_payload["manifest_sha256"],
    )
    assert assets.evidence == (block,)
    assert assets.audit[0].evidence_ids == (block.evidence_id,)

    evidence_path.write_bytes(evidence_bytes + b"\n")
    with pytest.raises(
        ProductEvidenceAssetIntegrityError,
        match="evidence JSONL SHA mismatch",
    ):
        load_product_evidence_assets(
            manifest_path=manifest_path,
            evidence_path=evidence_path,
            audit_path=audit_path,
        )
