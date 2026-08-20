from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter, ValidationError
import pytest

from app.guide.presentation.sse_events import SseEvent
from app.guide.retrieval.approved_review_assets import (
    load_approved_review_assets,
)
from app.guide.retrieval.review_reader import ReviewEvidenceReader
from app.guide.retrieval.review_summary import build_review_summary


ROOT = Path(__file__).resolve().parents[3]


def _scenario_record() -> dict[str, object]:
    return {
        "product_id": 55,
        "requirement_id": "scenario-v1:outdoor:water_resistance",
        "field": "water_resistance",
        "state": "unknown",
        "value": None,
        "source_refs": [],
        "reason": "canonical_unknown",
    }


def _review_absence(product_id: int) -> dict[str, object]:
    return {
        "product_id": product_id,
        "evidence": [],
        "verified_absence": {
            "kind": "verified_absence",
            "product_id": product_id,
            "reason": "no_approved_review_sources_for_product",
            "catalog_id": "phase2-review-source-audit",
            "catalog_version": "git-6123c7b-assets-v1",
            "audit_locator": (
                "docs/audits/phase2-scenario-feedback/"
                "review_source_audit.md"
            ),
        },
    }


def test_phase2_evidence_events_are_strict_typed_sse_contracts() -> None:
    adapter = TypeAdapter(SseEvent)

    scenario = adapter.validate_json(
        json.dumps(
            {
                "event": "scenario_evidence",
                "data": {"records": [_scenario_record()]},
            },
            ensure_ascii=False,
        )
    )
    review = adapter.validate_json(
        json.dumps(
            {
                "event": "review_evidence",
                "data": {
                    "approved_source_count": 0,
                    "results": [_review_absence(55)],
                    "summaries": [],
                },
            },
            ensure_ascii=False,
        )
    )
    pitfalls = adapter.validate_json(
        json.dumps(
            {
                "event": "pitfalls",
                "data": {
                    "pitfalls": [
                        {
                            "finding_id": (
                                "pitfall-v1:suitability:"
                                "sensitive_period_91"
                            ),
                            "product_id": 91,
                            "severity": "medium",
                            "claim_kind": "suitability",
                            "title": "敏感期适配证据不足",
                            "description": (
                                "现有审核适用肤质事实不能确认敏感期适配。"
                            ),
                            "evidence_refs": [
                                (
                                    "pitfall_evidence:canonical:91:"
                                    "015ec45ff9fe543c6b2137620dc953a7f"
                                    "050ed79b2b5b58e7f525079e975f433"
                                )
                            ],
                        }
                    ]
                },
            },
            ensure_ascii=False,
        )
    )

    assert scenario.event == "scenario_evidence"
    assert review.data.approved_source_count == 0
    assert review.data.summaries == []
    assert pitfalls.data.pitfalls[0].severity.value == "medium"
    assert pitfalls.data.pitfalls[0].evidence_refs


def test_review_event_accepts_typed_approved_source_summary() -> None:
    source_root = ROOT / "data" / "guide_review_sources"
    loaded = load_approved_review_assets(
        manifest_path=(
            source_root
            / "approved_tmall_feed_reviews_v1_manifest.json"
        ),
        sources_path=(
            source_root / "approved_tmall_feed_reviews_v1.jsonl"
        ),
        expected_manifest_sha256=(
            "823c249166e93b4ab709b3423fa8a97a23e3ab3e7677e5d39d74abc21c165113"
        ),
    )
    result = ReviewEvidenceReader(
        catalog=loaded.catalog,
        evidence=loaded.evidence,
    ).read(product_id=55)
    summary = build_review_summary(result)
    assert summary is not None

    review = TypeAdapter(SseEvent).validate_python(
        {
            "event": "review_evidence",
            "data": {
                "approved_source_count": 6,
                "results": [result],
                "summaries": [summary],
            },
        }
    )

    assert review.data.approved_source_count == 6
    assert len(review.data.results[0].evidence) == 2
    assert len(review.data.summaries) == 1
    assert len(review.data.summaries[0].source_facts) == 2


def test_zero_source_review_event_rejects_seeded_summary_content() -> None:
    adapter = TypeAdapter(SseEvent)
    payload = {
        "event": "review_evidence",
        "data": {
            "approved_source_count": 0,
            "results": [_review_absence(55)],
            "summaries": [
                {
                    "review_count": 123,
                    "description": "不能冒充评论总结",
                }
            ],
        },
    }

    with pytest.raises(ValidationError, match="summaries"):
        adapter.validate_python(payload)


def test_evidence_event_contracts_forbid_untyped_extra_fields() -> None:
    adapter = TypeAdapter(SseEvent)
    payload = {
        "event": "scenario_evidence",
        "data": {
            "records": [_scenario_record()],
            "ranking_bonus": 10,
        },
    }

    with pytest.raises(
        ValidationError,
        match="Extra inputs are not permitted",
    ):
        adapter.validate_python(payload)
