from __future__ import annotations

import json
from pathlib import Path

from app.guide.understanding.contracts import (
    TopicCode,
    UnderstandingGoal,
)
from tools.guide_gates.intent_model_ab import (
    IntentExpected,
    PipelineEvaluation,
    load_cases,
)


HISTORICAL_CASES_PATH = Path(
    "tests/fixtures/guide/intent/semantic_intent_ab_v1.jsonl"
)
CASES_PATH = Path(
    "tests/fixtures/guide/intent/semantic_intent_ab_v2.jsonl"
)


def test_gate_contract_evaluates_final_state_not_model_acts() -> None:
    assert "acts" not in IntentExpected.model_fields
    assert (
        "unauthorized_constraint_transition_count"
        in PipelineEvaluation.model_fields
    )


def test_frozen_cases_cover_required_semantic_matrix() -> None:
    raw_rows = [
        json.loads(line)
        for line in CASES_PATH.read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert all(
        {"concerns", "observations"} <= set(row["expected"])
        for row in raw_rows
    )

    cases = load_cases(CASES_PATH)

    assert len(cases) == 128
    assert {case.expected.goal for case in cases} == (
        set(UnderstandingGoal) - {UnderstandingGoal.IMAGE_IDENTITY}
    )
    paraphrase_topics = {
        case.expected.topic
        for case in cases
        if "category_paraphrase" in case.tags
        and case.expected.topic is not None
    }
    assert len(paraphrase_topics) >= 6
    assert paraphrase_topics <= set(TopicCode)

    required_tags = {
        "alcohol",
        "alcohol_budget_revision",
        "assessment",
        "budget",
        "conflict",
        "low_information",
        "ordinal",
        "out_of_scope",
        "prompt_injection",
        "pronoun",
        "revision",
        "round9",
    }
    present_tags = {
        tag
        for case in cases
        for tag in case.tags
    }
    assert required_tags <= present_tags
    assert len({case.case_id for case in cases}) == len(cases)
    assert {
        reference.kind
        for case in cases
        for reference in case.expected.references
    } == {
        "current_item",
        "current_batch",
        "candidate_ordinal",
        "image_ordinal",
        "current_topic",
        "previous_constraint",
    }
    by_id = {case.case_id: case for case in cases}
    expected_reference_kinds = {
        "cmp-002-two-serums": ("current_batch",),
        "suit-001-sensitive-sunscreen": ("current_item",),
        "assess-013-pronoun-current": ("current_item",),
        "assess-014-revision-observation": ("previous_constraint",),
        "follow-010-budget-lower": ("previous_constraint",),
        "follow-016-colloquial-more": ("current_item",),
        "know-011-current-topic": ("current_topic",),
    }
    assert {
        case_id: tuple(
            reference.kind
            for reference in by_id[case_id].expected.references
        )
        for case_id in expected_reference_kinds
    } == expected_reference_kinds
    assert all("acts" not in row["expected"] for row in raw_rows)
    assessment_cases = [
        case
        for case in cases
        if "assessment" in case.tags
        and case.expected.goal is UnderstandingGoal.ASSESSMENT
    ]
    assert assessment_cases
    assert all(case.expected.concerns for case in assessment_cases)
    assert all(case.expected.observations for case in assessment_cases)


def test_v2_freeze_preserves_ids_and_limits_expected_label_changes() -> None:
    historical = [
        json.loads(line)
        for line in HISTORICAL_CASES_PATH.read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    current = [
        json.loads(line)
        for line in CASES_PATH.read_text(
            encoding="utf-8"
        ).splitlines()
    ]

    assert [row["case_id"] for row in current] == [
        row["case_id"] for row in historical
    ]
    assert len(current) == 128
    allowed_expected_changes = {
        "assess-001-post-cleanse-tight",
        "assess-004-cleanser-reaction",
        "assess-005-sunscreen-stinging",
        "assess-006-serum-redness",
        "suit-008-paraphrase-sunscreen",
        "clar-015-revision-missing-target",
        "follow-009-budget-revision",
        "follow-010-budget-lower",
        "follow-011-skin-revision",
    }
    historical_by_id = {
        row["case_id"]: row for row in historical
    }

    def without_contract_migration_fields(
        expected: dict[str, object],
    ) -> dict[str, object]:
        normalized = json.loads(json.dumps(expected))
        normalized.pop("acts", None)
        for reference in normalized.get("references", []):
            reference.pop("raw_text", None)
            reference.pop("start", None)
            reference.pop("end", None)
        return normalized

    for row in current:
        case_id = row["case_id"]
        if case_id not in allowed_expected_changes:
            assert without_contract_migration_fields(
                row["expected"]
            ) == without_contract_migration_fields(
                historical_by_id[case_id]["expected"]
            )
        assert set(row["context"]) == {
            "conversation_version",
            "active_topic",
            "visible_candidate_count",
            "focused_candidate_ordinal",
            "image_count",
            "focused_image_ordinal",
            "active_constraint_kinds",
            "confirmed_profile_fields",
        }
