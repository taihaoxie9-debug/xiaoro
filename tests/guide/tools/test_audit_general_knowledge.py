from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.guide_data.audit_general_knowledge import (
    KnowledgeAuditError,
    audit_general_knowledge,
    materialize_general_knowledge_reviews,
)
from tools.guide_data.build_general_knowledge import (
    parse_knowledge_document,
)


_SOURCE = """# 防晒怎么选

## 原理

SPF针对UVB，PA针对UVA。
"""

_FORBIDDEN = [
    "hard_filter",
    "product_fact",
    "profile_write",
    "safety_guarantee",
    "soft_rank",
]


def _candidate_file(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    source = tmp_path / "data" / "knowledge_docs" / "06-防晒怎么选.md"
    source.parent.mkdir(parents=True)
    source.write_text(_SOURCE, encoding="utf-8")
    parsed = parse_knowledge_document(source, repo_root=tmp_path)
    candidate = parsed.blocks[0].model_dump(mode="json")
    path = tmp_path / "candidates.jsonl"
    path.write_text(
        json.dumps(
            candidate,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return path, candidate


def _review(
    candidate: dict[str, object],
    **overrides: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "candidate_id": candidate["candidate_id"],
        "source_sha256": candidate["source_sha256"],
        "block_sha256": candidate["block_sha256"],
        "content_scope": "general",
        "review_decision": "general_answer",
        "allowed_uses": ["answer", "citation", "followup"],
        "forbidden_uses": list(_FORBIDDEN),
        "review_rationale": "通用指标解释，不指向具体商品。",
    }
    payload.update(overrides)
    return payload


def _write_reviews(
    tmp_path: Path,
    reviews: list[dict[str, object]],
) -> Path:
    path = tmp_path / "reviews.jsonl"
    path.write_text(
        "".join(
            json.dumps(
                row,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
            for row in reviews
        ),
        encoding="utf-8",
    )
    return path


def test_clean_audit_publishes_one_reviewed_block(
    tmp_path: Path,
) -> None:
    candidates, candidate = _candidate_file(tmp_path)
    reviews = _write_reviews(tmp_path, [_review(candidate)])

    audit = audit_general_knowledge(
        candidate_path=candidates,
        review_paths=(reviews,),
    )

    assert audit.report.model_dump(mode="json") == {
        "candidate_total": 1,
        "reviewed_total": 1,
        "missing_total": 0,
        "general_answer": 1,
        "escalation_only": 0,
        "product_specific_redirect": 0,
        "rejected": 0,
        "permission_mismatches": 0,
        "invalid_reviews": 0,
        "duplicate_reviews": 0,
        "unknown_reviews": 0,
        "source_mismatches": 0,
        "clean": True,
    }
    assert len(audit.blocks) == 1
    assert audit.blocks[0].knowledge_id == candidate["candidate_id"]


def test_missing_review_is_reported(tmp_path: Path) -> None:
    candidates, _ = _candidate_file(tmp_path)
    reviews = _write_reviews(tmp_path, [])

    report = audit_general_knowledge(
        candidate_path=candidates,
        review_paths=(reviews,),
    ).report

    assert report.missing_total == 1
    assert report.reviewed_total == 0
    assert not report.clean


def test_duplicate_and_unknown_reviews_are_rejected(
    tmp_path: Path,
) -> None:
    candidates, candidate = _candidate_file(tmp_path)
    unknown = _review(
        candidate,
        candidate_id="f" * 64,
    )
    review = _review(candidate)
    reviews = _write_reviews(
        tmp_path,
        [review, review, unknown],
    )

    report = audit_general_knowledge(
        candidate_path=candidates,
        review_paths=(reviews,),
    ).report

    assert report.duplicate_reviews == 1
    assert report.unknown_reviews == 1
    assert not report.clean


def test_empty_rationale_is_invalid(tmp_path: Path) -> None:
    candidates, candidate = _candidate_file(tmp_path)
    reviews = _write_reviews(
        tmp_path,
        [_review(candidate, review_rationale="")],
    )

    report = audit_general_knowledge(
        candidate_path=candidates,
        review_paths=(reviews,),
    ).report

    assert report.invalid_reviews == 1
    assert report.missing_total == 1
    assert not report.clean


def test_escalation_only_cannot_gain_answer_permission(
    tmp_path: Path,
) -> None:
    candidates, candidate = _candidate_file(tmp_path)
    reviews = _write_reviews(
        tmp_path,
        [
            _review(
                candidate,
                content_scope="medical_boundary",
                review_decision="escalation_only",
                allowed_uses=[
                    "answer",
                    "citation",
                    "medical_escalation",
                ],
            )
        ],
    )

    report = audit_general_knowledge(
        candidate_path=candidates,
        review_paths=(reviews,),
    ).report

    assert report.permission_mismatches == 1
    assert not report.clean


def test_product_specific_scope_cannot_be_general_answer(
    tmp_path: Path,
) -> None:
    candidates, candidate = _candidate_file(tmp_path)
    reviews = _write_reviews(
        tmp_path,
        [_review(candidate, content_scope="product_specific")],
    )

    report = audit_general_knowledge(
        candidate_path=candidates,
        review_paths=(reviews,),
    ).report

    assert report.permission_mismatches == 1
    assert not report.clean


def test_missing_mandatory_forbidden_use_is_permission_mismatch(
    tmp_path: Path,
) -> None:
    candidates, candidate = _candidate_file(tmp_path)
    reviews = _write_reviews(
        tmp_path,
        [
            _review(
                candidate,
                forbidden_uses=[
                    value
                    for value in _FORBIDDEN
                    if value != "soft_rank"
                ],
            )
        ],
    )

    report = audit_general_knowledge(
        candidate_path=candidates,
        review_paths=(reviews,),
    ).report

    assert report.permission_mismatches == 1
    assert not report.clean


def test_source_sha_mismatch_is_not_a_valid_review(
    tmp_path: Path,
) -> None:
    candidates, candidate = _candidate_file(tmp_path)
    reviews = _write_reviews(
        tmp_path,
        [_review(candidate, source_sha256="e" * 64)],
    )

    report = audit_general_knowledge(
        candidate_path=candidates,
        review_paths=(reviews,),
    ).report

    assert report.source_mismatches == 1
    assert report.missing_total == 1
    assert not report.clean


def test_manual_dispositions_materialize_content_bound_reviews(
    tmp_path: Path,
) -> None:
    candidates, candidate = _candidate_file(tmp_path)
    decisions = tmp_path / "decisions.jsonl"
    decisions.write_text(
        json.dumps(
            {
                "source_path": candidate["source_path"],
                "dispositions": ["general_answer"],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    review_dir = tmp_path / "review-output"

    paths = materialize_general_knowledge_reviews(
        candidate_path=candidates,
        decision_catalog_path=decisions,
        review_dir=review_dir,
    )

    assert len(paths) == 1
    row = json.loads(paths[0].read_text(encoding="utf-8"))
    assert row == {
        "allowed_uses": ["answer", "citation", "followup"],
        "block_sha256": candidate["block_sha256"],
        "candidate_id": candidate["candidate_id"],
        "content_scope": "general",
        "forbidden_uses": _FORBIDDEN,
        "review_decision": "general_answer",
        "review_rationale": (
            "逐块核验为通用教育内容，不指向具体商品，"
            "不提供诊断或安全保证。"
        ),
        "source_sha256": candidate["source_sha256"],
    }
    assert audit_general_knowledge(
        candidate_path=candidates,
        review_paths=paths,
    ).report.clean


def test_manual_disposition_count_must_match_every_candidate(
    tmp_path: Path,
) -> None:
    candidates, candidate = _candidate_file(tmp_path)
    decisions = tmp_path / "decisions.jsonl"
    decisions.write_text(
        json.dumps(
            {
                "source_path": candidate["source_path"],
                "dispositions": [],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        KnowledgeAuditError,
        match="disposition count",
    ):
        materialize_general_knowledge_reviews(
            candidate_path=candidates,
            decision_catalog_path=decisions,
            review_dir=tmp_path / "reviews",
        )
