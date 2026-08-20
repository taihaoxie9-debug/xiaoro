from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.guide_data.audit_product_evidence_uses import (
    EvidenceUseAuditError,
    audit_product_evidence_uses,
)


def _write_rows(path: Path, rows: list[dict[str, object]]) -> None:
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


def test_audit_reports_missing_and_illegal_selection_reviews(
    tmp_path: Path,
) -> None:
    path = tmp_path / "skincare_batch_001.jsonl"
    _write_rows(
        path,
        [
            {
                "product_id": 78,
                "review_status": "accepted",
                "selection_review": {
                    "decision": "projected",
                    "visual_confirmed": True,
                    "rationale": "商家保湿宣称允许弱软排。",
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
                "product_id": 79,
                "review_status": "accepted",
            },
            {
                "product_id": 80,
                "review_status": "ambiguous",
                "selection_review": {
                    "decision": "answer_only",
                    "visual_confirmed": True,
                    "rationale": "关系不清。",
                    "projections": [],
                },
            },
        ],
    )

    result = audit_product_evidence_uses((path,))

    assert result.accepted_total == 2
    assert result.accepted_reviewed == 1
    assert result.accepted_missing == 1
    assert result.nonaccepted_with_review == 1
    assert result.projected == 1
    assert result.projections_by_field == {"efficacy": 1}
    with pytest.raises(
        EvidenceUseAuditError,
        match="evidence use audit is incomplete",
    ):
        result.assert_clean()


def test_audit_rejects_duplicate_projection_keys(tmp_path: Path) -> None:
    path = tmp_path / "skincare_batch_001.jsonl"
    projection = {
        "field_key": "efficacy",
        "normalized_value": "保湿",
        "capabilities": ["soft_rank"],
        "rank_strength": 1,
        "safety_role": "ordinary",
    }
    _write_rows(
        path,
        [
            {
                "product_id": 78,
                "review_status": "accepted",
                "selection_review": {
                    "decision": "projected",
                    "visual_confirmed": True,
                    "rationale": "重复投影必须被发现。",
                    "projections": [projection, projection],
                },
            }
        ],
    )

    result = audit_product_evidence_uses((path,))

    assert result.duplicate_projection_keys == 1
    with pytest.raises(
        EvidenceUseAuditError,
        match="evidence use audit is incomplete",
    ):
        result.assert_clean()


def test_audit_rejects_projection_beyond_allowed_uses(
    tmp_path: Path,
) -> None:
    path = tmp_path / "skincare_batch_001.jsonl"
    _write_rows(
        path,
        [
            {
                "product_id": 78,
                "review_status": "accepted",
                "allowed_uses": ["answer", "display"],
                "selection_review": {
                    "decision": "projected",
                    "visual_confirmed": True,
                    "rationale": "未同步放权的错误夹具。",
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
            }
        ],
    )

    result = audit_product_evidence_uses((path,))

    assert result.authorization_mismatches == 1
    with pytest.raises(
        EvidenceUseAuditError,
        match="evidence use audit is incomplete",
    ):
        result.assert_clean()


def test_audit_reports_unique_capacity_relation_without_projection(
    tmp_path: Path,
) -> None:
    path = tmp_path / "skincare_batch_001.jsonl"
    _write_rows(
        path,
        [
            {
                "product_id": 78,
                "review_status": "accepted",
                "subject_scope": "exact_product",
                "variant_scope": None,
                "management_label": "product_specification",
                "relations": [
                    {
                        "predicate": "merchant_net_content",
                        "object": "50ml",
                    }
                ],
                "allowed_uses": ["answer", "compare", "display"],
                "selection_review": {
                    "decision": "comparison_only",
                    "visual_confirmed": True,
                    "rationale": "规格关系清楚，但漏投影。",
                    "projections": [],
                },
            }
        ],
    )

    result = audit_product_evidence_uses((path,))

    assert result.specification_projection_gap_count == 1
    assert result.unique_specification_projection_gap_count == 1
    assert result.specification_projection_gaps[0].capacity_values == (
        "50ml",
    )
    with pytest.raises(
        EvidenceUseAuditError,
        match="evidence use audit is incomplete",
    ):
        result.assert_clean()


def test_audit_keeps_multi_sku_product_capacity_as_ambiguous(
    tmp_path: Path,
) -> None:
    path = tmp_path / "skincare_batch_001.jsonl"
    _write_rows(
        path,
        [
            {
                "product_id": 78,
                "review_status": "accepted",
                "subject_scope": "exact_product",
                "variant_scope": None,
                "management_label": "product_specification",
                "relations": [
                    {
                        "predicate": "merchant_product_size_options",
                        "object": "150ml和450ml",
                    }
                ],
                "allowed_uses": ["answer", "compare", "display"],
                "selection_review": {
                    "decision": "comparison_only",
                    "visual_confirmed": True,
                    "rationale": "两个SKU不能投影为一个商品规格。",
                    "projections": [],
                },
            }
        ],
    )

    result = audit_product_evidence_uses((path,))

    assert result.specification_projection_gap_count == 1
    assert result.unique_specification_projection_gap_count == 0
    result.assert_clean()


def test_audit_accepts_capacity_relation_with_net_content_projection(
    tmp_path: Path,
) -> None:
    path = tmp_path / "skincare_batch_001.jsonl"
    _write_rows(
        path,
        [
            {
                "product_id": 78,
                "review_status": "accepted",
                "subject_scope": "exact_variant",
                "variant_scope": "50ml常规装",
                "management_label": "product_specification",
                "relations": [
                    {
                        "predicate": "observed_package_net_content",
                        "object": "50ml",
                    }
                ],
                "allowed_uses": ["answer", "compare", "display"],
                "selection_review": {
                    "decision": "projected",
                    "visual_confirmed": True,
                    "rationale": "包装明确给出当前SKU容量。",
                    "projections": [
                        {
                            "field_key": "net_content",
                            "normalized_value": "50ml",
                            "capabilities": ["compare"],
                            "rank_strength": None,
                            "safety_role": "ordinary",
                        }
                    ],
                },
            }
        ],
    )

    result = audit_product_evidence_uses((path,))

    assert result.specification_projection_gap_count == 0
    assert result.unique_specification_projection_gap_count == 0
    result.assert_clean()
