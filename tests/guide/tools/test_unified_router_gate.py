from __future__ import annotations

import json

import pytest

from app.guide.feedback.contracts import (
    ConversationSnapshot,
    KnowledgeSlotState,
)
from app.guide.feedback.focus_state import ActiveFocus
from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.retrieval.product_name_resolver import (
    ResolvedProductBinding,
)
from tools.guide_gates import unified_router_gate
from tools.guide_gates.unified_router_gate import (
    FailureLayer,
    LayerEvidence,
    ReplayCase,
    ReplayTrace,
    build_replay_manifest,
    classify_earliest_failure,
    evaluate_replay_trace,
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

    assert classify_earliest_failure(
        LayerEvidence.model_validate(values, strict=True)
    ) is expected


def test_detects_product_card_outside_decision_order() -> None:
    events = [
        ("decision_process", {"ordered_product_ids": [38]}),
        ("products", {"products": [{"id": 91}]}),
    ]

    assert unified_router_gate.detect_hard_condition_override(
        events=events,
        card_ids=(91,),
    )
    assert not unified_router_gate.detect_hard_condition_override(
        events=events,
        card_ids=(38,),
    )


def test_detects_changed_or_deleted_isolation_sentinel() -> None:
    expected = ConversationSnapshot(
        session_id="isolation-sentinel",
        version=1,
        active_owner=Responsibility.GENERAL_KNOWLEDGE,
        active_focus=ActiveFocus(slot="knowledge"),
        knowledge_slot=KnowledgeSlotState(
            question="isolation-sentinel",
        ),
    )

    assert unified_router_gate.detect_cross_session_leak(
        expected=expected,
        actual=expected.model_copy(update={"version": 2}, deep=True),
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
            "recommendation_mode": "explore",
            "recommendation_count": None,
            "recommendation_mode_basis": {
                "basis": "bounded_exploration",
                "source_text": "150元以内",
            },
            "topic_hint": "sunscreen",
            "continuity_hint": "new_task",
            "subject_scope_hint": "self",
            "pending_response_hint": "unknown",
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
            "constraint_changes": [],
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
            "active_owner": "recommendation",
            "active_focus": {"slot": "recommendation"},
        },
        "expected_task_plan": {
            "mode": "recommend",
        },
        "expected_card_ids": [54],
        "expected_safety": False,
        "expected_clarification": False,
        "expected_presentation_mode": "recommendation",
    }


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
            "active_owner": "recommendation",
            "active_focus": {"slot": "recommendation"},
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
            "end",
        ),
        error_code=None,
        hard_condition_override=False,
        cross_session_leak=False,
    )


def test_replay_artifact_loads_only_with_matching_manifest(
    tmp_path,
) -> None:
    case = ReplayCase.model_validate(_replay_payload(), strict=True)
    raw = case.model_dump_json(exclude_none=False).encode() + b"\n"
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_bytes(raw)
    manifest = build_replay_manifest(raw, cases=(case,))
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        manifest.model_dump_json(),
        encoding="utf-8",
    )

    assert load_replay_cases(
        cases_path,
        manifest_path=manifest_path,
    ) == (case,)

    cases_path.write_bytes(raw.replace(b"150", b"151", 1))
    with pytest.raises(ValueError, match="SHA-256"):
        load_replay_cases(
            cases_path,
            manifest_path=manifest_path,
        )


def test_replay_trace_evaluation_preserves_layer_boundaries() -> None:
    case = ReplayCase.model_validate(_replay_payload(), strict=True)

    passed = evaluate_replay_trace(
        case=case,
        trace=_passing_trace(),
    )
    admission_failure = evaluate_replay_trace(
        case=case,
        trace=_passing_trace().model_copy(
            update={
                "semantic_admission_passed": False,
                "bindings": (
                    ResolvedProductBinding(
                        product_id=999,
                        variant_scope=None,
                        source_text="wrong",
                    ),
                ),
            },
            deep=True,
        ),
    )

    assert passed.passed
    assert passed.failure_layer is None
    assert (
        admission_failure.failure_layer
        is FailureLayer.SEMANTIC_ADMISSION
    )
    assert not admission_failure.passed


def test_replay_summary_counts_zero_tolerance_violations() -> None:
    case = ReplayCase.model_validate(_replay_payload(), strict=True)
    passed = evaluate_replay_trace(
        case=case,
        trace=_passing_trace(),
    )
    unexpected_card = evaluate_replay_trace(
        case=case.model_copy(
            update={"case_id": "offline-recommend-sunscreen-002"},
            deep=True,
        ),
        trace=_passing_trace().model_copy(
            update={"card_ids": (999,)},
            deep=True,
        ),
    )

    summary = summarize_replay((passed, unexpected_card))

    assert summary.case_count == 2
    assert summary.passed_count == 1
    assert summary.wrong_product_selection_count == 1
    assert not summary.passed


def test_run_replay_uses_only_the_injected_layer_executor() -> None:
    first = ReplayCase.model_validate(_replay_payload(), strict=True)
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
    assert summary.passed
