from __future__ import annotations

from pathlib import Path

from app.guide.intent.concept_preferences import (
    ConceptPreferenceCatalog,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning
from app.guide_runtime.composition import build_selection_concept_assets
from tools.guide_gates.turn_meaning_gate import (
    TurnMeaningGateRow,
    evaluate_gate_case,
    load_gate_cases,
    summarize_gate,
)


_FIXTURE = Path(
    "tests/fixtures/guide/intent/turn_meaning_gate_v1.jsonl"
)
_REVIEW = Path(
    "tests/fixtures/guide/intent/turn_meaning_gate_review_v1.jsonl"
)


def _catalog() -> ConceptPreferenceCatalog:
    return ConceptPreferenceCatalog.from_projections(
        build_selection_concept_assets().projections
    )


def _meaning(**updates) -> TurnMeaning:
    payload = {
        "operation_hint": "recommendation",
        "recommendation_mode": "explore",
        "recommendation_count": 3,
        "recommendation_mode_basis": {
            "basis": "broad_exploration",
            "source_text": "推荐",
        },
        "topic_hint": None,
        "reference_mentions": [],
        "product_mentions": [],
        "budget_candidates": [],
        "observation_candidates": [],
        "preference_candidates": [],
        "relative_candidates": [],
        "question_meaning": None,
        "safety_language": "ordinary",
    }
    payload.update(updates)
    if payload["operation_hint"] == "image_similarity":
        payload.update(
            {
                "recommendation_mode": "explore",
                "recommendation_count": None,
                "recommendation_mode_basis": {
                    "basis": "similar_alternatives",
                    "source_text": payload["reference_mentions"][0][
                        "raw_text"
                    ],
                },
            }
        )
    elif payload["operation_hint"] != "recommendation":
        payload.update(
            {
                "recommendation_mode": None,
                "recommendation_count": None,
                "recommendation_mode_basis": None,
            }
        )
    return TurnMeaning.model_validate(payload, strict=True)


def test_reaudited_fixture_has_128_unique_four_layer_rows() -> None:
    cases = load_gate_cases(_FIXTURE)
    reviews = [
        line
        for line in _REVIEW.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert len(cases) == 128
    assert len({case.case_id for case in cases}) == 128
    assert len(reviews) == 128
    assert {case.family for case in cases} == {
        "recommendation",
        "comparison",
        "suitability",
        "image",
        "knowledge",
        "assessment",
        "followup",
        "clarification",
    }
    assert all(case.translation.required_fields for case in cases)
    assert all(case.binding is not None for case in cases)
    assert all(case.execution is not None for case in cases)


def test_known_false_truths_are_explicitly_corrected() -> None:
    by_id = {case.case_id: case for case in load_gate_cases(_FIXTURE)}

    assert set(
        by_id["assess-001-post-cleanse-tight"]
        .translation.allowed_topic_hints
    ) == {"skincare", "cleanser"}
    assert (
        by_id["img-001-find-similar-first"]
        .binding.expected_objects
    ) == ("image:1",)
    assert set(
        by_id["clar-015-revision-missing-target"]
        .translation.allowed_operation_hints
    ) == {"followup", "clarification"}
    assert (
        by_id["clar-015-revision-missing-target"]
        .execution.expected_task_mode
    ) == "clarify"
    assert (
        by_id["follow-009-budget-revision"]
        .execution.expected_transitions
    ) == (
        "budget:replace",
        "exclusion:酒精:retain",
    )
    assert set(
        by_id["suit-005-post-cleanse-tight"]
        .translation.allowed_operation_hints
    ) == {"suitability", "assessment"}
    assert set(
        by_id["know-012-candidate-reference"]
        .translation.allowed_operation_hints
    ) == {"knowledge", "clarification"}
    assert set(
        by_id["follow-006-second-image"]
        .translation.allowed_operation_hints
    ) == {"followup", "image_similarity"}


def test_equivalent_image_raw_text_is_scored_by_binding_not_json() -> None:
    case = next(
        case
        for case in load_gate_cases(_FIXTURE)
        if case.case_id == "img-001-find-similar-first"
    )
    meaning = _meaning(
        operation_hint="image_similarity",
        reference_mentions=[
            {
                "raw_text": "第一张图",
                "object_family_hint": "image",
                "ordinal_hint": 1,
                "plurality_hint": "single",
            }
        ],
        question_meaning="寻找与第一张图片相似的商品",
    )

    result = evaluate_gate_case(
        case=case,
        meaning=meaning,
        concept_catalog=_catalog(),
        provider_call_count=1,
    )

    assert result.translation_passed
    assert result.source_grounded
    assert result.binding_passed
    assert result.semantic_actual_outcome is not None
    assert result.semantic_actual_outcome["recommendation_mode"] == (
        "explore"
    )
    assert result.semantic_actual_outcome[
        "recommendation_mode_basis"
    ] == "similar_alternatives"
    assert result.full_json_equality_used is False


def test_product_knowledge_reference_accepts_followup_operation() -> None:
    case = next(
        case
        for case in load_gate_cases(_FIXTURE)
        if case.case_id == "know-012-candidate-reference"
    )
    meaning = _meaning(
        operation_hint="followup",
        topic_hint="sunscreen",
        continuity_hint="continue",
        reference_mentions=[
            {
                "raw_text": "第二款",
                "object_family_hint": "product",
                "ordinal_hint": 2,
                "plurality_hint": "single",
            }
        ],
        question_meaning="第二款提到的水感质地是什么意思",
    )

    result = evaluate_gate_case(
        case=case,
        meaning=meaning,
        concept_catalog=_catalog(),
        provider_call_count=1,
    )

    assert result.translation_passed
    assert result.binding_passed
    assert result.task_plan_passed


def test_budget_revision_accepts_recommendation_operation() -> None:
    case = next(
        case
        for case in load_gate_cases(_FIXTURE)
        if case.case_id == "follow-009-budget-revision"
    )
    meaning = _meaning(
        operation_hint="recommendation",
        recommendation_mode="explore",
        recommendation_count=None,
        recommendation_mode_basis={
            "basis": "bounded_exploration",
            "source_text": "三百以内",
        },
        topic_hint="sunscreen",
        continuity_hint="continue",
        budget_candidates=[
            {
                "raw_text": "三百以内",
                "relation": "maximum",
                "minimum": None,
                "maximum": "300",
            }
        ],
        preference_candidates=[
            {
                "field_key": "ingredient_exclusion",
                "concept_id": None,
                "polarity": "avoid",
                "raw_text": "酒精",
                "strength": "ordinary",
            }
        ],
    )

    result = evaluate_gate_case(
        case=case,
        meaning=meaning,
        concept_catalog=_catalog(),
        provider_call_count=1,
    )

    assert result.translation_passed
    assert result.task_plan_passed


def test_referenced_constraint_followup_does_not_hide_recommendation_route() -> None:
    case = next(
        case
        for case in load_gate_cases(_FIXTURE)
        if case.case_id == "follow-012-alcohol-followup"
    )
    meaning = _meaning(
        operation_hint="recommendation",
        recommendation_count=None,
        recommendation_mode_basis={
            "basis": "broad_exploration",
            "source_text": "第二款",
        },
        topic_hint="serum",
        continuity_hint="continue",
        reference_mentions=[
            {
                "raw_text": "第二款",
                "object_family_hint": "product",
                "ordinal_hint": 2,
                "plurality_hint": "single",
            }
        ],
        preference_candidates=[
            {
                "field_key": "ingredient_exclusion",
                "concept_id": None,
                "polarity": "avoid",
                "raw_text": "酒精",
                "strength": "ordinary",
            }
        ],
        question_meaning="询问第二款产品是否不含酒精",
    )

    result = evaluate_gate_case(
        case=case,
        meaning=meaning,
        concept_catalog=_catalog(),
        provider_call_count=1,
    )

    assert not result.translation_passed
    assert result.binding_passed
    assert not result.task_plan_passed
    assert result.semantic_equivalence_passed is False
    assert result.semantic_mismatch_code == "responsibility"


def test_extra_unasserted_semantics_do_not_fail_translation() -> None:
    case = next(
        case
        for case in load_gate_cases(_FIXTURE)
        if case.case_id == "rec-006-paraphrase-sunscreen"
    )
    meaning = _meaning(
        operation_hint="recommendation",
        recommendation_mode="fit",
        recommendation_count=1,
        recommendation_mode_basis={
            "basis": "personal_suitability",
            "source_text": "最适合",
        },
        topic_hint="sunscreen",
        preference_candidates=[
            {
                "field_key": "usage_context",
                "concept_id": None,
                "raw_text": "通勤",
                "polarity": "prefer",
                "strength": "ordinary",
            },
            {
                "field_key": "texture",
                "concept_id": None,
                "raw_text": "不搓泥",
                "polarity": "prefer",
                "strength": "ordinary",
            },
        ],
        question_meaning="寻找通勤防晒且不搓泥",
    )

    result = evaluate_gate_case(
        case=case,
        meaning=meaning,
        concept_catalog=_catalog(),
        provider_call_count=1,
    )

    assert result.translation_passed
    assert result.source_grounded


def test_invented_raw_text_is_a_hard_grounding_failure() -> None:
    case = next(
        case
        for case in load_gate_cases(_FIXTURE)
        if case.case_id == "img-001-find-similar-first"
    )
    meaning = _meaning(
        operation_hint="image_similarity",
        reference_mentions=[
            {
                "raw_text": "第二张",
                "object_family_hint": "image",
                "ordinal_hint": 2,
                "plurality_hint": "single",
            }
        ],
    )

    result = evaluate_gate_case(
        case=case,
        meaning=meaning,
        concept_catalog=_catalog(),
        provider_call_count=1,
    )

    assert not result.source_grounded
    assert result.invented_source_atom_count == 1
    assert not result.passed


def test_repeated_existing_source_is_ambiguous_not_invented() -> None:
    case = next(
        case
        for case in load_gate_cases(_FIXTURE)
        if case.case_id == "clar-009-conflict-alcohol"
    )
    meaning = _meaning(
        operation_hint="clarification",
        topic_hint="skincare",
        preference_candidates=[
            {
                "field_key": "ingredients",
                "concept_id": None,
                "raw_text": "酒精",
                "polarity": "avoid",
                "strength": "safety",
            }
        ],
        safety_language="safety",
    )

    result = evaluate_gate_case(
        case=case,
        meaning=meaning,
        concept_catalog=_catalog(),
        provider_call_count=1,
    )

    assert result.invented_source_atom_count == 0
    assert result.ambiguous_source_atom_count == 1
    assert result.source_grounded
    assert result.task_plan_passed


def test_gate_requires_one_call_and_zero_hard_errors() -> None:
    rows = [
        TurnMeaningGateRow.passing(f"case-{index:03d}")
        for index in range(128)
    ]

    passed = summarize_gate(rows)
    assert passed.end_to_end_rate == 1.0
    assert passed.passed

    rows[0] = rows[0].model_copy(
        update={"provider_call_count": 2},
        deep=True,
    )
    rows[1] = rows[1].model_copy(
        update={"unauthorized_state_transition_count": 1},
        deep=True,
    )
    failed = summarize_gate(rows)

    assert not failed.passed
    assert failed.provider_call_violation_count == 1
    assert failed.unauthorized_state_transition_count == 1
