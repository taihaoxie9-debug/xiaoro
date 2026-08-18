from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path

import pytest

from app.guide.feedback.contracts import (
    ClarificationProgress,
    ConversationSnapshot,
    DisplayedCandidateRef,
    PendingBudgetRange,
    PendingRecommendationContext,
    PendingTurn,
    RecommendationQueryContext,
)
from app.guide.feedback.focus_state import (
    ConfirmedImageProductRef,
    FocusState,
)
from app.guide.feedback.session_profile import (
    SessionProfile,
    SessionProfileFact,
)
from app.guide.retrieval.product_name_resolver import (
    ResolvedProductBinding,
)
from app.guide.understanding.semantic_contracts import ClarificationCode
from tools.guide_gates import unified_router_gate
from tools.guide_gates.unified_router_gate import (
    FailureLayer,
    LayerEvidence,
    ReplayCase,
    ReplayTrace,
    build_replay_manifest,
    classify_earliest_failure,
    evaluate_replay_trace,
    execute_replay_case,
    load_replay_cases,
    run_replay,
    summarize_replay,
)


@pytest.mark.parametrize(
    ("failed_field", "expected"),
    (
        ("model_translation", FailureLayer.MODEL_TRANSLATION),
        ("semantic_admission", FailureLayer.SEMANTIC_ADMISSION),
        ("identity_binding", FailureLayer.IDENTITY_BINDING),
        ("route_selection", FailureLayer.ROUTE_SELECTION),
        ("state_transition", FailureLayer.STATE_TRANSITION),
        ("decision_execution", FailureLayer.DECISION_EXECUTION),
        ("presentation", FailureLayer.PRESENTATION),
    ),
)
def test_classifies_exactly_one_earliest_failure_layer(
    failed_field: str,
    expected: FailureLayer,
) -> None:
    values = {
        "model_translation": True,
        "semantic_admission": True,
        "identity_binding": True,
        "route_selection": True,
        "state_transition": True,
        "decision_execution": True,
        "presentation": True,
    }
    values[failed_field] = False
    evidence = LayerEvidence.model_validate(values, strict=True)

    assert classify_earliest_failure(evidence) is expected


def test_reasonable_model_rejected_by_code_is_admission_failure() -> None:
    evidence = LayerEvidence(
        model_translation=True,
        semantic_admission=False,
        identity_binding=False,
        route_selection=False,
        state_transition=False,
        decision_execution=False,
        presentation=False,
    )

    assert (
        classify_earliest_failure(evidence)
        is FailureLayer.SEMANTIC_ADMISSION
    )


def test_all_layers_pass_has_no_failure() -> None:
    evidence = LayerEvidence(
        model_translation=True,
        semantic_admission=True,
        identity_binding=True,
        route_selection=True,
        state_transition=True,
        decision_execution=True,
        presentation=True,
    )

    assert classify_earliest_failure(evidence) is None


def test_detects_product_card_outside_decision_order() -> None:
    events = [
        (
            "decision_process",
            {"ordered_product_ids": [38]},
        ),
        (
            "products",
            {"products": [{"id": 91}]},
        ),
    ]

    assert unified_router_gate.detect_hard_condition_override(
        events=events,
        card_ids=(91,),
    )
    assert not unified_router_gate.detect_hard_condition_override(
        events=events,
        card_ids=(38,),
    )


def test_product_knowledge_card_does_not_require_selection_decision() -> None:
    events = [
        (
            "products",
            {"products": [{"id": 38}]},
        ),
    ]

    assert not unified_router_gate.detect_hard_condition_override(
        events=events,
        card_ids=(38,),
    )


def test_detects_changed_or_deleted_isolation_sentinel() -> None:
    expected = ConversationSnapshot(
        session_id="isolation-sentinel",
        version=1,
        focus_state=FocusState(
            active_processor="general_knowledge",
            current_knowledge_topic="isolation-sentinel",
        ),
    )
    changed = expected.model_copy(
        update={"version": 2},
        deep=True,
    )

    assert unified_router_gate.detect_cross_session_leak(
        expected=expected,
        actual=changed,
    )
    assert unified_router_gate.detect_cross_session_leak(
        expected=expected,
        actual=None,
    )
    assert not unified_router_gate.detect_cross_session_leak(
        expected=expected,
        actual=expected.model_copy(deep=True),
    )


def _replay_payload() -> dict[str, object]:
    return {
        "schema_version": "guide-unified-router-replay-case-v1",
        "case_id": "offline-recommend-sunscreen-001",
        "message": "150元以内推荐防晒",
        "starting_snapshot": None,
        "raw_turn_meaning": {
            "operation_hint": "recommendation",
            "topic_hint": "sunscreen",
            "continuity_hint": "new_task",
            "subject_scope_hint": "self",
            "reference_mentions": [],
            "product_mentions": [],
            "budget_candidates": [
                {
                    "raw_text": "150元以内",
                    "relation": "maximum",
                    "minimum": None,
                    "maximum": "150",
                }
            ],
            "observation_candidates": [],
            "preference_candidates": [],
            "relative_candidates": [],
            "consultation_hypothesis": None,
            "next_observation_gap": None,
            "question_meaning": "推荐预算内防晒",
            "safety_language": "ordinary",
        },
        "acceptable_semantic": {
            "operation_hints": ["recommendation"],
            "topic_hints": ["sunscreen"],
            "continuity_hints": ["new_task"],
            "subject_scope_hints": ["self", "unknown"],
        },
        "expected_bindings": [],
        "expected_route": {
            "processor": "recommendation",
            "continuity": "replace_task",
            "focus_source": "none",
        },
        "expected_final_snapshot": {
            "focus_state": {
                "active_processor": "recommendation",
            }
        },
        "expected_task_plan": {
            "mode": "recommend",
        },
        "expected_card_ids": [54],
        "expected_safety": False,
        "expected_clarification": False,
        "expected_presentation_mode": "recommendation",
    }


def test_replay_artifact_loads_only_with_matching_manifest(
    tmp_path: Path,
) -> None:
    case = ReplayCase.model_validate(
        _replay_payload(),
        strict=True,
    )
    cases_path = tmp_path / "cases.jsonl"
    case_bytes = (
        case.model_dump_json(exclude_none=False).encode("utf-8")
        + b"\n"
    )
    cases_path.write_bytes(case_bytes)
    manifest = build_replay_manifest(case_bytes, cases=(case,))
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            manifest.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    loaded = load_replay_cases(
        cases_path,
        manifest_path=manifest_path,
    )

    assert loaded == (case,)
    assert manifest.case_count == 1


def test_replay_manifest_rejects_tampered_case_bytes(
    tmp_path: Path,
) -> None:
    case = ReplayCase.model_validate(
        _replay_payload(),
        strict=True,
    )
    original = case.model_dump_json().encode("utf-8") + b"\n"
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_bytes(original)
    manifest = build_replay_manifest(original, cases=(case,))
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        manifest.model_dump_json(),
        encoding="utf-8",
    )
    cases_path.write_bytes(
        original.replace(b"150", b"151", 1)
    )

    with pytest.raises(ValueError, match="SHA-256"):
        load_replay_cases(
            cases_path,
            manifest_path=manifest_path,
        )


def _passing_trace() -> ReplayTrace:
    return ReplayTrace(
        semantic_admission_passed=True,
        bindings=(),
        route={
            "processor": "recommendation",
            "continuity": "replace_task",
            "focus_source": "none",
        },
        final_snapshot={
            "version": 1,
            "focus_state": {
                "active_processor": "recommendation",
                "current_product_id": None,
            },
        },
        task_plan={
            "mode": "recommend",
            "constraints": [],
        },
        card_ids=(54,),
        safety=False,
        clarification=False,
        presentation_mode="recommendation",
        event_names=(
            "start",
            "intent",
            "products",
            "presentation_contract",
            "message",
            "end",
        ),
        error_code=None,
        hard_condition_override=False,
        cross_session_leak=False,
    )


def test_replay_trace_passes_with_expected_nested_subsets() -> None:
    case = ReplayCase.model_validate(
        _replay_payload(),
        strict=True,
    )

    result = evaluate_replay_trace(
        case=case,
        trace=_passing_trace(),
    )

    assert result.passed
    assert result.failure_layer is None
    assert result.layer_evidence == LayerEvidence(
        model_translation=True,
        semantic_admission=True,
        identity_binding=True,
        route_selection=True,
        state_transition=True,
        decision_execution=True,
        presentation=True,
    )


def test_replay_trace_reports_admission_before_downstream_mismatch() -> None:
    case = ReplayCase.model_validate(
        _replay_payload(),
        strict=True,
    )
    trace = _passing_trace().model_copy(
        update={
            "semantic_admission_passed": False,
            "bindings": (
                ResolvedProductBinding(
                    product_id=999,
                    variant_scope=None,
                    source_text="错误商品",
                ),
            ),
        },
        deep=True,
    )

    result = evaluate_replay_trace(case=case, trace=trace)

    assert result.failure_layer is FailureLayer.SEMANTIC_ADMISSION
    assert not result.passed


def test_missing_expected_card_is_not_a_wrong_product_selection() -> None:
    case = ReplayCase.model_validate(
        _replay_payload(),
        strict=True,
    )
    trace = _passing_trace().model_copy(
        update={"card_ids": ()},
        deep=True,
    )

    result = evaluate_replay_trace(case=case, trace=trace)

    assert result.failure_layer is FailureLayer.DECISION_EXECUTION
    assert result.wrong_product_selection_count == 0
    assert not result.passed


def test_unexpected_rendered_card_is_a_wrong_product_selection() -> None:
    case = ReplayCase.model_validate(
        _replay_payload(),
        strict=True,
    )
    trace = _passing_trace().model_copy(
        update={"card_ids": (999,)},
        deep=True,
    )

    result = evaluate_replay_trace(case=case, trace=trace)

    assert result.wrong_product_selection_count == 1
    assert not result.passed


def test_missing_final_snapshot_is_not_an_unauthorized_state_write() -> None:
    case = ReplayCase.model_validate(
        _replay_payload(),
        strict=True,
    )
    trace = _passing_trace().model_copy(
        update={"final_snapshot": {}},
        deep=True,
    )

    result = evaluate_replay_trace(case=case, trace=trace)

    assert result.failure_layer is FailureLayer.STATE_TRANSITION
    assert result.unauthorized_state_transition_count == 0
    assert not result.passed


def test_contradictory_final_snapshot_is_an_unauthorized_state_write() -> None:
    case = ReplayCase.model_validate(
        _replay_payload(),
        strict=True,
    )
    trace = _passing_trace().model_copy(
        update={
            "final_snapshot": {
                "focus_state": {
                    "active_processor": "comparison",
                }
            }
        },
        deep=True,
    )

    result = evaluate_replay_trace(case=case, trace=trace)

    assert result.unauthorized_state_transition_count == 1
    assert not result.passed


def test_fail_closed_clarification_is_not_an_unauthorized_state_write(
) -> None:
    case = ReplayCase.model_validate(
        _replay_payload(),
        strict=True,
    )
    trace = _passing_trace().model_copy(
        update={
            "route": unified_router_gate.RouteExpectation(
                processor="clarification",
                continuity="replace_task",
                focus_source="none",
            ),
            "final_snapshot": {
                "version": 1,
                "session_profile": None,
                "query_context": None,
                "candidates": [],
                "focus_state": None,
                "has_image_delivery": False,
                "empty_result": False,
                "focused_candidate_ordinal": None,
                "focused_evidence_ids": [],
                "focused_general_knowledge_ids": [],
                "last_general_knowledge_question": None,
                "consultation": None,
                "clarification": {
                    "gap": "reference",
                    "attempts": 1,
                },
            },
            "card_ids": (),
            "clarification": True,
            "presentation_mode": None,
        },
        deep=True,
    )

    result = evaluate_replay_trace(case=case, trace=trace)

    assert result.failure_layer is FailureLayer.ROUTE_SELECTION
    assert result.unauthorized_state_transition_count == 0
    assert not result.passed


def test_replay_summary_counts_zero_tolerance_violations() -> None:
    case = ReplayCase.model_validate(
        _replay_payload(),
        strict=True,
    )
    passed = evaluate_replay_trace(
        case=case,
        trace=_passing_trace(),
    )
    unsafe = evaluate_replay_trace(
        case=case.model_copy(
            update={
                "case_id": "offline-recommend-sunscreen-unsafe-002",
                "expected_safety": True,
            },
            deep=True,
        ),
        trace=_passing_trace(),
    )

    summary = summarize_replay((passed, unsafe))

    assert summary.case_count == 2
    assert summary.passed_count == 1
    assert summary.unsafe_downgrade_count == 1
    assert summary.wrong_product_selection_count == 0
    assert summary.unauthorized_state_transition_count == 0
    assert summary.cross_session_leak_count == 0
    assert not summary.passed


def test_execute_replay_case_runs_real_backend_without_provider(
    tmp_path: Path,
) -> None:
    payload = _replay_payload()
    payload.update(
        {
            "case_id": "offline-real-recommend-serum-001",
            "message": "500元内敏感肌修护精华",
            "raw_turn_meaning": {
                **payload["raw_turn_meaning"],
                "topic_hint": "serum",
                "budget_candidates": [
                    {
                        "raw_text": "500元内",
                        "relation": "maximum",
                        "minimum": None,
                        "maximum": "500",
                    }
                ],
                "question_meaning": "推荐预算内敏感肌修护精华",
            },
            "acceptable_semantic": {
                **payload["acceptable_semantic"],
                "topic_hints": ["serum"],
            },
            "expected_card_ids": [38, 91],
        }
    )
    case = ReplayCase.model_validate(payload, strict=True)

    trace = execute_replay_case(
        case,
        repo_root=Path.cwd(),
        state_root=tmp_path / "state",
    )
    result = evaluate_replay_trace(case=case, trace=trace)

    assert trace.card_ids == (38, 91)
    assert trace.presentation_mode == "recommendation"
    assert trace.route.processor == "recommendation"
    assert trace.event_names[-1] == "end"
    assert trace.error_code is None
    assert trace.final_snapshot["focus_state"][
        "active_processor"
    ] == "recommendation"
    assert result.passed


def test_run_replay_executes_each_case_once_and_summarizes() -> None:
    first = ReplayCase.model_validate(
        _replay_payload(),
        strict=True,
    )
    second = first.model_copy(
        update={"case_id": "offline-recommend-sunscreen-002"},
        deep=True,
    )
    calls: list[str] = []

    def execute(case: ReplayCase) -> ReplayTrace:
        calls.append(case.case_id)
        return _passing_trace()

    summary, results = run_replay(
        (first, second),
        executor=execute,
    )

    assert calls == [first.case_id, second.case_id]
    assert [item.case_id for item in results] == calls
    assert summary.case_count == 2
    assert summary.passed_count == 2
    assert summary.passed


def test_execute_general_knowledge_replay_keeps_zero_card_contract(
    tmp_path: Path,
) -> None:
    cases = load_replay_cases(
        "tests/fixtures/guide/intent/unified_router_offline_v1.jsonl",
        manifest_path=(
            "tests/fixtures/guide/intent/"
            "unified_router_offline_v1_manifest.json"
        ),
    )
    case = next(
        item
        for item in cases
        if item.case_id == "offline-general-knowledge-001"
    )

    trace = execute_replay_case(
        case,
        repo_root=Path.cwd(),
        state_root=tmp_path / "general-state",
    )
    result = evaluate_replay_trace(case=case, trace=trace)

    assert trace.event_names[-1] == "end"
    assert trace.card_ids == ()
    assert trace.presentation_mode == "general_knowledge"
    assert result.passed


def test_execute_ambiguous_product_replay_clarifies_without_cards(
    tmp_path: Path,
) -> None:
    cases = load_replay_cases(
        "tests/fixtures/guide/intent/unified_router_offline_v1.jsonl",
        manifest_path=(
            "tests/fixtures/guide/intent/"
            "unified_router_offline_v1_manifest.json"
        ),
    )
    case = next(
        item
        for item in cases
        if item.case_id == "offline-ambiguous-b5-clarification-001"
    )

    trace = execute_replay_case(
        case,
        repo_root=Path.cwd(),
        state_root=tmp_path / "ambiguous-state",
    )
    result = evaluate_replay_trace(case=case, trace=trace)

    assert trace.route.processor == "clarification"
    assert trace.clarification
    assert trace.card_ids == ()
    assert trace.presentation_mode is None
    assert result.passed


def test_execute_focused_followup_preserves_recommendation_batch(
    tmp_path: Path,
) -> None:
    cases = load_replay_cases(
        "tests/fixtures/guide/intent/unified_router_offline_v1.jsonl",
        manifest_path=(
            "tests/fixtures/guide/intent/"
            "unified_router_offline_v1_manifest.json"
        ),
    )
    case = next(
        item
        for item in cases
        if item.case_id == "offline-followup-second-product-001"
    )

    trace = execute_replay_case(
        case,
        repo_root=Path.cwd(),
        state_root=tmp_path / "followup-state",
    )

    assert trace.final_snapshot["query_context"][
        "budget_maximum"
    ] == "500"
    assert [
        item["product_id"]
        for item in trace.final_snapshot["candidates"]
    ] == [38, 91]
    assert trace.final_snapshot["focus_state"][
        "current_product_id"
    ] == 91


@pytest.mark.parametrize(
    ("case_id", "message", "raw_text"),
    (
        (
            "offline-budget-revision-001",
            "预算降到 100 元呢",
            "100 元",
        ),
        (
            "blind-budget-revision-colloquial-001",
            "太贵了，最多一百吧",
            "最多一百",
        ),
    ),
)
def test_execute_budget_revision_reports_code_owned_correction(
    tmp_path: Path,
    case_id: str,
    message: str,
    raw_text: str,
) -> None:
    cases = load_replay_cases(
        "tests/fixtures/guide/intent/unified_router_offline_v1.jsonl",
        manifest_path=(
            "tests/fixtures/guide/intent/"
            "unified_router_offline_v1_manifest.json"
        ),
    )
    starting = next(
        item.starting_snapshot
        for item in cases
        if item.case_id == "offline-followup-second-product-001"
    )
    assert starting is not None
    case = ReplayCase.model_validate(
        {
            "schema_version": "guide-unified-router-replay-case-v1",
            "case_id": case_id,
            "message": message,
            "starting_snapshot": starting,
            "raw_turn_meaning": {
                "operation_hint": "recommendation",
                "topic_hint": "serum",
                "continuity_hint": "continue",
                "subject_scope_hint": "self",
                "reference_mentions": (
                    []
                    if case_id == "blind-budget-revision-colloquial-001"
                    else [
                        {
                            "raw_text": "预算",
                            "object_family_hint": "constraint",
                            "ordinal_hint": None,
                            "plurality_hint": "single",
                        }
                    ]
                ),
                "product_mentions": [],
                "budget_candidates": [
                    {
                        "raw_text": raw_text,
                        "relation": "maximum",
                        "minimum": None,
                        "maximum": "100",
                    }
                ],
                "observation_candidates": [],
                "preference_candidates": [],
                "relative_candidates": [],
                "consultation_hypothesis": None,
                "next_observation_gap": None,
                "question_meaning": "把原推荐预算上限改为100元",
                "safety_language": "ordinary",
            },
            "acceptable_semantic": {
                "operation_hints": ["recommendation", "followup"],
                "topic_hints": ["serum"],
                "continuity_hints": ["continue"],
                "subject_scope_hints": ["self", "unknown"],
            },
            "expected_bindings": [],
            "expected_route": {
                "processor": "recommendation",
                "continuity": "correct",
                "focus_source": "none",
            },
            "expected_final_snapshot": {
                "query_context": {
                    "category": "serum",
                    "budget_maximum": "100",
                    "skin": "sensitive",
                    "efficacy": "repair",
                },
                "focus_state": {
                    "active_processor": "recommendation",
                },
            },
            "expected_task_plan": {
                "mode": "recommend",
            },
            "expected_card_ids": [91],
            "expected_safety": False,
            "expected_clarification": False,
            "expected_presentation_mode": "revision",
        },
        strict=True,
    )

    trace = execute_replay_case(
        case,
        repo_root=Path.cwd(),
        state_root=tmp_path / "budget-revision-state",
    )
    result = evaluate_replay_trace(case=case, trace=trace)

    assert trace.route.continuity == "correct"
    assert trace.card_ids == (91,), trace.model_dump_json(indent=2)
    assert result.failure_layer is None, result.model_dump_json(
        indent=2
    )
    assert result.passed, (result, trace)


def test_execute_return_to_product_focus_preserves_other_focuses(
    tmp_path: Path,
) -> None:
    cases = load_replay_cases(
        "tests/fixtures/guide/intent/unified_router_offline_v1.jsonl",
        manifest_path=(
            "tests/fixtures/guide/intent/"
            "unified_router_offline_v1_manifest.json"
        ),
    )
    base = next(
        item.starting_snapshot
        for item in cases
        if item.case_id == "offline-followup-second-product-001"
    )
    assert base is not None
    starting = base.model_copy(
        update={
            "last_general_knowledge_question": "视黄醇是什么",
            "focus_state": FocusState(
                active_processor="general_knowledge",
                current_product_id=91,
                current_knowledge_topic="视黄醇",
                last_question_meaning="视黄醇是什么",
            ),
        },
        deep=True,
    )
    case = ReplayCase.model_validate(
        {
            "schema_version": "guide-unified-router-replay-case-v1",
            "case_id": "offline-return-product-focus-001",
            "message": "回到刚才那款，它的用法呢",
            "starting_snapshot": starting,
            "raw_turn_meaning": {
                "operation_hint": "knowledge",
                "topic_hint": "serum",
                "continuity_hint": "return_to_focus",
                "subject_scope_hint": "self",
                "reference_mentions": [],
                "product_mentions": [],
                "budget_candidates": [],
                "observation_candidates": [],
                "preference_candidates": [],
                "relative_candidates": [],
                "consultation_hypothesis": None,
                "next_observation_gap": None,
                "question_meaning": "询问之前聚焦商品的用法",
                "safety_language": "ordinary",
            },
            "acceptable_semantic": {
                "operation_hints": ["knowledge", "followup"],
                "topic_hints": ["serum", None],
                "continuity_hints": ["return_to_focus"],
                "subject_scope_hints": ["self", "unknown"],
            },
            "expected_bindings": [
                {
                    "product_id": 91,
                    "variant_scope": None,
                    "source_text": "current_product",
                }
            ],
            "expected_route": {
                "processor": "product_knowledge",
                "continuity": "return_to_focus",
                "focus_source": "current_product",
            },
            "expected_final_snapshot": {
                "query_context": {
                    "category": "serum",
                    "budget_maximum": "500",
                },
                "focus_state": {
                    "active_processor": "product_knowledge",
                    "current_product_id": 91,
                    "current_knowledge_topic": "视黄醇",
                },
            },
            "expected_task_plan": {
                "mode": "followup",
                "product_ids": [91],
            },
            "expected_card_ids": [91],
            "expected_safety": False,
            "expected_clarification": False,
            "expected_presentation_mode": "followup",
        },
        strict=True,
    )

    trace = execute_replay_case(
        case,
        repo_root=Path.cwd(),
        state_root=tmp_path / "return-product-focus-state",
    )
    result = evaluate_replay_trace(case=case, trace=trace)

    assert result.failure_layer is None, trace.model_dump_json(indent=2)
    assert result.passed, (
        result.model_dump_json(indent=2),
        trace.model_dump_json(indent=2),
    )


def _pending_replay_snapshot() -> ConversationSnapshot:
    pending = PendingTurn(
        gap=ClarificationCode.BUDGET,
        attempts=1,
        source_conversation_version=0,
        source_message="敏感肌修护精华，预算500以内",
        expected_response="confirm_or_correct",
        resume_mode="recommendation",
        resume_context=PendingRecommendationContext(
            category="serum",
            skin="sensitive",
            efficacy="repair",
        ),
        proposed_budget=PendingBudgetRange(
            minimum=Decimal("1"),
            maximum=Decimal("500"),
        ),
    )
    starting = ConversationSnapshot(
        session_id="replay-pending-affirmation",
        version=1,
        query_context=RecommendationQueryContext(
            category="serum",
            budget_maximum=Decimal("500"),
            skin="sensitive",
            efficacy="repair",
        ),
        candidates=(
            DisplayedCandidateRef(
                product_id=38,
                ordinal=1,
                skin_match="matched",
                matched_efficacies=("修护",),
            ),
            DisplayedCandidateRef(
                product_id=91,
                ordinal=2,
                skin_match="matched",
                matched_efficacies=("修护",),
            ),
        ),
        pending_turn=pending,
        clarification=ClarificationProgress(
            gap=ClarificationCode.BUDGET,
            attempts=1,
        ),
        focus_state=FocusState(
            active_processor="clarification",
        ),
    )
    return starting


def test_execute_pending_affirmation_records_resumed_task(
    tmp_path: Path,
) -> None:
    starting = _pending_replay_snapshot()
    case = ReplayCase.model_validate(
        {
            "schema_version": "guide-unified-router-replay-case-v1",
            "case_id": "offline-pending-affirmation-001",
            "message": "是的",
            "starting_snapshot": starting,
            "raw_turn_meaning": {
                "operation_hint": "clarification",
                "topic_hint": "serum",
                "continuity_hint": "continue",
                "subject_scope_hint": "self",
                "reference_mentions": [],
                "product_mentions": [],
                "budget_candidates": [],
                "observation_candidates": [],
                "preference_candidates": [],
                "relative_candidates": [],
                "consultation_hypothesis": None,
                "next_observation_gap": None,
                "question_meaning": "确认上一轮预算",
                "safety_language": "ordinary",
            },
            "acceptable_semantic": {
                "operation_hints": ["clarification", "followup"],
                "topic_hints": ["serum", None],
                "continuity_hints": ["continue", "unknown"],
                "subject_scope_hints": ["self", "unknown"],
            },
            "expected_bindings": [],
            "expected_route": {
                "processor": "recommendation",
                "continuity": "continue",
                "focus_source": "none",
            },
            "expected_final_snapshot": {
                "query_context": {
                    "category": "serum",
                    "budget_minimum": "1",
                    "budget_maximum": "500",
                    "skin": "sensitive",
                    "efficacy": "repair",
                },
                "pending_turn": None,
                "focus_state": {
                    "active_processor": "recommendation",
                },
            },
            "expected_task_plan": {
                "mode": "recommend",
            },
            "expected_card_ids": [38, 91],
            "expected_safety": False,
            "expected_clarification": False,
            "expected_presentation_mode": "recommendation",
        },
        strict=True,
    )

    trace = execute_replay_case(
        case,
        repo_root=Path.cwd(),
        state_root=tmp_path / "pending-affirmation-state",
    )
    result = evaluate_replay_trace(case=case, trace=trace)

    assert result.failure_layer is None, trace.model_dump_json(indent=2)
    assert result.passed, (
        result.model_dump_json(indent=2),
        trace.model_dump_json(indent=2),
    )


def test_execute_pending_rejection_keeps_task_pending(
    tmp_path: Path,
) -> None:
    case = ReplayCase.model_validate(
        {
            "schema_version": "guide-unified-router-replay-case-v1",
            "case_id": "offline-pending-rejection-001",
            "message": "不是",
            "starting_snapshot": _pending_replay_snapshot(),
            "raw_turn_meaning": {
                "operation_hint": "clarification",
                "topic_hint": "serum",
                "continuity_hint": "continue",
                "subject_scope_hint": "self",
                "reference_mentions": [],
                "product_mentions": [],
                "budget_candidates": [],
                "observation_candidates": [],
                "preference_candidates": [],
                "relative_candidates": [],
                "consultation_hypothesis": None,
                "next_observation_gap": None,
                "question_meaning": "否认上一轮预算",
                "safety_language": "ordinary",
            },
            "acceptable_semantic": {
                "operation_hints": ["clarification", "followup"],
                "topic_hints": ["serum", None],
                "continuity_hints": ["continue", "unknown"],
                "subject_scope_hints": ["self", "unknown"],
            },
            "expected_bindings": [],
            "expected_route": {
                "processor": "clarification",
                "continuity": "continue",
                "focus_source": "none",
            },
            "expected_final_snapshot": {
                "version": 2,
                "query_context": {
                    "category": "serum",
                    "budget_maximum": "500",
                },
                "clarification": {
                    "gap": "budget",
                    "attempts": 2,
                },
                "pending_turn": {
                    "gap": "budget",
                    "attempts": 2,
                    "expected_response": "supply_value",
                    "proposed_budget": None,
                },
                "focus_state": {
                    "active_processor": "clarification",
                },
            },
            "expected_task_plan": {
                "mode": "clarify",
            },
            "expected_card_ids": [],
            "expected_safety": False,
            "expected_clarification": True,
            "expected_presentation_mode": None,
        },
        strict=True,
    )

    trace = execute_replay_case(
        case,
        repo_root=Path.cwd(),
        state_root=tmp_path / "pending-rejection-state",
    )
    result = evaluate_replay_trace(case=case, trace=trace)

    assert result.passed, (
        result.model_dump_json(indent=2),
        trace.model_dump_json(indent=2),
    )


def test_execute_named_constraint_withdrawal_removes_only_target(
    tmp_path: Path,
) -> None:
    base = _pending_replay_snapshot()
    assert base.query_context is not None
    starting = base.model_copy(
        update={
            "session_id": "replay-withdraw-exclusion",
            "query_context": base.query_context.model_copy(
                update={"exclusions": ("酒精",)},
                deep=True,
            ),
            "pending_turn": None,
            "clarification": None,
            "focus_state": FocusState(
                active_processor="recommendation",
            ),
        },
        deep=True,
    )
    case = ReplayCase.model_validate(
        {
            "schema_version": "guide-unified-router-replay-case-v1",
            "case_id": "offline-withdraw-exclusion-001",
            "message": "取消酒精排除",
            "starting_snapshot": starting,
            "raw_turn_meaning": {
                "operation_hint": "followup",
                "topic_hint": "serum",
                "continuity_hint": "continue",
                "subject_scope_hint": "self",
                "reference_mentions": [
                    {
                        "raw_text": "酒精排除",
                        "object_family_hint": "constraint",
                        "ordinal_hint": None,
                        "plurality_hint": "single",
                    }
                ],
                "product_mentions": [],
                "budget_candidates": [],
                "observation_candidates": [],
                "preference_candidates": [],
                "relative_candidates": [],
                "consultation_hypothesis": None,
                "next_observation_gap": None,
                "question_meaning": "撤销酒精排除条件",
                "safety_language": "ordinary",
            },
            "acceptable_semantic": {
                "operation_hints": ["followup", "recommendation"],
                "topic_hints": ["serum", None],
                "continuity_hints": ["continue"],
                "subject_scope_hints": ["self", "unknown"],
            },
            "expected_bindings": [],
            "expected_route": {
                "processor": "recommendation",
                "continuity": "withdraw",
                "focus_source": "none",
            },
            "expected_final_snapshot": {
                "query_context": {
                    "category": "serum",
                    "budget_maximum": "500",
                    "skin": "sensitive",
                    "efficacy": "repair",
                    "exclusions": [],
                },
                "focus_state": {
                    "active_processor": "recommendation",
                },
            },
            "expected_task_plan": {
                "mode": "recommend",
            },
            "expected_card_ids": [38, 91],
            "expected_safety": False,
            "expected_clarification": False,
            "expected_presentation_mode": "recommendation",
        },
        strict=True,
    )

    trace = execute_replay_case(
        case,
        repo_root=Path.cwd(),
        state_root=tmp_path / "withdraw-exclusion-state",
    )
    result = evaluate_replay_trace(case=case, trace=trace)

    assert result.passed, (
        result.model_dump_json(indent=2),
        trace.model_dump_json(indent=2),
    )


def test_execute_confirmed_session_profile_projects_into_recommendation(
    tmp_path: Path,
) -> None:
    starting = ConversationSnapshot(
        session_id="replay-session-profile",
        version=1,
        session_profile=SessionProfile(
            stable_tendencies=(
                SessionProfileFact(
                    value="sensitivity",
                    confirmation="confirmed",
                    source_turn_id="turn_profile_source_0001",
                ),
            ),
        ),
    )
    case = ReplayCase.model_validate(
        {
            "schema_version": "guide-unified-router-replay-case-v1",
            "case_id": "offline-session-profile-projection-001",
            "message": "500元内修护精华",
            "starting_snapshot": starting,
            "raw_turn_meaning": {
                "operation_hint": "recommendation",
                "topic_hint": "serum",
                "continuity_hint": "new_task",
                "subject_scope_hint": "self",
                "reference_mentions": [],
                "product_mentions": [],
                "budget_candidates": [
                    {
                        "raw_text": "500元内",
                        "relation": "maximum",
                        "minimum": None,
                        "maximum": "500",
                    }
                ],
                "observation_candidates": [],
                "preference_candidates": [],
                "relative_candidates": [],
                "consultation_hypothesis": None,
                "next_observation_gap": None,
                "question_meaning": "推荐预算内修护精华",
                "safety_language": "ordinary",
            },
            "acceptable_semantic": {
                "operation_hints": ["recommendation"],
                "topic_hints": ["serum"],
                "continuity_hints": ["new_task"],
                "subject_scope_hints": ["self", "unknown"],
            },
            "expected_bindings": [],
            "expected_route": {
                "processor": "recommendation",
                "continuity": "replace_task",
                "focus_source": "none",
            },
            "expected_final_snapshot": {
                "session_profile": {
                    "stable_tendencies": [
                        {
                            "value": "sensitivity",
                            "confirmation": "confirmed",
                            "source_turn_id": "turn_profile_source_0001",
                        }
                    ]
                },
                "query_context": {
                    "category": "serum",
                    "budget_maximum": "500",
                    "skin": "sensitive",
                    "efficacy": "repair",
                },
                "focus_state": {
                    "active_processor": "recommendation",
                },
            },
            "expected_task_plan": {
                "mode": "recommend",
            },
            "expected_card_ids": [38, 91],
            "expected_safety": False,
            "expected_clarification": False,
            "expected_presentation_mode": "recommendation",
        },
        strict=True,
    )

    trace = execute_replay_case(
        case,
        repo_root=Path.cwd(),
        state_root=tmp_path / "session-profile-state",
    )
    result = evaluate_replay_trace(case=case, trace=trace)

    assert result.passed, (
        result.model_dump_json(indent=2),
        trace.model_dump_json(indent=2),
    )


def test_execute_friend_request_does_not_mutate_self_profile(
    tmp_path: Path,
) -> None:
    profile = SessionProfile(
        stable_tendencies=(
            SessionProfileFact(
                value="sensitivity",
                confirmation="confirmed",
                source_turn_id="turn_profile_source_0002",
            ),
        ),
    )
    starting = ConversationSnapshot(
        session_id="replay-friend-profile-isolation",
        version=1,
        session_profile=profile,
    )
    case = ReplayCase.model_validate(
        {
            "schema_version": "guide-unified-router-replay-case-v1",
            "case_id": "offline-friend-profile-isolation-001",
            "message": "给朋友找500内适合油敏肌的防晒",
            "starting_snapshot": starting,
            "raw_turn_meaning": {
                "operation_hint": "recommendation",
                "topic_hint": "sunscreen",
                "continuity_hint": "new_task",
                "subject_scope_hint": "other",
                "reference_mentions": [],
                "product_mentions": [],
                "budget_candidates": [
                    {
                        "raw_text": "500内",
                        "relation": "maximum",
                        "minimum": None,
                        "maximum": "500",
                    }
                ],
                "observation_candidates": [],
                "preference_candidates": [],
                "relative_candidates": [],
                "consultation_hypothesis": None,
                "next_observation_gap": None,
                "question_meaning": "为朋友推荐预算内油敏肌防晒",
                "safety_language": "ordinary",
            },
            "acceptable_semantic": {
                "operation_hints": ["recommendation"],
                "topic_hints": ["sunscreen"],
                "continuity_hints": ["new_task"],
                "subject_scope_hints": ["other"],
            },
            "expected_bindings": [],
            "expected_route": {
                "processor": "recommendation",
                "continuity": "replace_task",
                "focus_source": "none",
            },
            "expected_final_snapshot": {
                "session_profile": {
                    "stable_tendencies": [
                        {
                            "value": "sensitivity",
                            "confirmation": "confirmed",
                            "source_turn_id": "turn_profile_source_0002",
                        }
                    ]
                },
                "query_context": {
                    "category": "sunscreen",
                    "budget_maximum": "500",
                    "skin": "oily_sensitive",
                },
                "focus_state": {
                    "active_processor": "recommendation",
                },
            },
            "expected_task_plan": {
                "mode": "recommend",
            },
            "expected_card_ids": [101, 26, 52],
            "expected_safety": False,
            "expected_clarification": False,
            "expected_presentation_mode": "recommendation",
        },
        strict=True,
    )

    trace = execute_replay_case(
        case,
        repo_root=Path.cwd(),
        state_root=tmp_path / "friend-profile-isolation-state",
    )
    result = evaluate_replay_trace(case=case, trace=trace)

    assert result.passed, (
        result.model_dump_json(indent=2),
        trace.model_dump_json(indent=2),
    )


@pytest.mark.parametrize(
    (
        "topic_hint",
        "operation_hint",
        "expected_task_mode",
        "expected_presentation_mode",
        "message",
        "reference_text",
        "reference_family",
        "reference_ordinal",
        "product_text",
    ),
    (
        (
            "sunscreen",
            "suitability",
            "suitability",
            "single_product",
            "图里这款适合敏感肌吗",
            "图里这款",
            "image",
            1,
            None,
        ),
        (
            None,
            "suitability",
            "suitability",
            "single_product",
            "图里这款适合敏感肌吗",
            "图里这款",
            "image",
            1,
            None,
        ),
        (
            None,
            "followup",
            "followup",
            "followup",
            "图一那款对敏感皮友好吗",
            "图一",
            "image",
            1,
            None,
        ),
        (
            "sunscreen",
            "suitability",
            "suitability",
            "single_product",
            "刚识别的这支防晒适不适合敏感肌",
            "这支防晒",
            "product",
            None,
            "这支防晒",
        ),
        (
            "sunscreen",
            "suitability",
            "suitability",
            "single_product",
            "上张图识别出的防晒，敏感肌可以选吗",
            "上张图",
            "image",
            1,
            "防晒",
        ),
    ),
)
def test_execute_confirmed_image_context_reuses_product_processor(
    tmp_path: Path,
    topic_hint: str | None,
    operation_hint: str,
    expected_task_mode: str,
    expected_presentation_mode: str,
    message: str,
    reference_text: str,
    reference_family: str,
    reference_ordinal: int | None,
    product_text: str | None,
) -> None:
    image = ConfirmedImageProductRef(
        image_ordinal=1,
        product_id=53,
    )
    starting = ConversationSnapshot(
        session_id="replay-confirmed-image-context",
        version=1,
        has_image_delivery=True,
        focus_state=FocusState(
            active_processor="image_identity",
            current_product_id=53,
            confirmed_image_products=(image,),
        ),
    )
    case = ReplayCase.model_validate(
        {
            "schema_version": "guide-unified-router-replay-case-v1",
            "case_id": "offline-confirmed-image-suitability-001",
            "message": message,
            "starting_snapshot": starting,
            "raw_turn_meaning": {
                "operation_hint": operation_hint,
                "topic_hint": topic_hint,
                "continuity_hint": "continue",
                "subject_scope_hint": "self",
                "reference_mentions": [
                    {
                        "raw_text": reference_text,
                        "object_family_hint": reference_family,
                        "ordinal_hint": reference_ordinal,
                        "plurality_hint": "single",
                    }
                ],
                "product_mentions": (
                    []
                    if product_text is None
                    else [{"raw_text": product_text}]
                ),
                "budget_candidates": [],
                "observation_candidates": [],
                "preference_candidates": [],
                "relative_candidates": [],
                "consultation_hypothesis": None,
                "next_observation_gap": None,
                "question_meaning": "判断图中商品是否适合敏感肌",
                "safety_language": "ordinary",
            },
            "acceptable_semantic": {
                "operation_hints": [operation_hint],
                "topic_hints": ["sunscreen", None],
                "continuity_hints": ["continue"],
                "subject_scope_hints": ["self", "unknown"],
            },
            "expected_bindings": [
                {
                    "product_id": 53,
                    "variant_scope": None,
                    "source_text": "image_ordinal:1",
                }
            ],
            "expected_route": {
                "processor": "product_knowledge",
                "continuity": "continue",
                "focus_source": "confirmed_image",
            },
            "expected_final_snapshot": {
                "has_image_delivery": True,
                "focus_state": {
                    "active_processor": "product_knowledge",
                    "current_product_id": 53,
                    "confirmed_image_products": [
                        {
                            "image_ordinal": 1,
                            "product_id": 53,
                            "variant_scope": None,
                        }
                    ],
                },
            },
            "expected_task_plan": {
                "mode": expected_task_mode,
                "product_ids": [53],
            },
            "expected_card_ids": [53],
            "expected_safety": False,
            "expected_clarification": False,
            "expected_presentation_mode": expected_presentation_mode,
        },
        strict=True,
    )

    trace = execute_replay_case(
        case,
        repo_root=Path.cwd(),
        state_root=tmp_path / "confirmed-image-context-state",
    )
    result = evaluate_replay_trace(case=case, trace=trace)

    assert result.passed, (
        result.model_dump_json(indent=2),
        trace.model_dump_json(indent=2),
    )


def test_cli_prints_machine_readable_passing_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    case = ReplayCase.model_validate(
        _replay_payload(),
        strict=True,
    )
    cases_path = tmp_path / "cases.jsonl"
    raw = case.model_dump_json().encode("utf-8") + b"\n"
    cases_path.write_bytes(raw)
    manifest = build_replay_manifest(raw, cases=(case,))
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        manifest.model_dump_json(),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        unified_router_gate,
        "execute_replay_case",
        lambda case, **kwargs: _passing_trace(),
    )

    exit_code = unified_router_gate.main(
        [
            "--cases",
            str(cases_path),
            "--manifest",
            str(manifest_path),
            "--repo-root",
            str(Path.cwd()),
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["passed"] is True
    assert output["case_count"] == 1
