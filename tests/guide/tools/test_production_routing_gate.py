from __future__ import annotations

import json
from pathlib import Path

from app.guide.adapters.llm.contracts import (
    SemanticProviderFailure,
    SemanticProviderFailureCode,
)
from app.guide.application.contracts import UserTurn
from app.guide.feedback.contracts import ConversationSnapshot
from app.guide.presentation.sse_events import (
    ClarifyData,
    ClarifyEvent,
    EndData,
    EndEvent,
    IntentData,
    IntentEvent,
    StartData,
    StartEvent,
)
from app.guide.understanding.semantic_contracts import (
    ClarificationCode,
    SemanticIntentProposal,
)
from tools.guide_gates.intent_model_ab import IntentCase, load_cases
from tools.guide_gates.production_routing_gate import (
    CLOSED_OPERATION_CASE_IDS,
    OPEN_SEMANTIC_CASE_IDS,
    WRONG_CARD_CASE_IDS,
    ProductionRoutingGate,
    build_fixture_snapshot,
)


CASES_PATH = Path(
    "tests/fixtures/guide/intent/semantic_intent_ab_v2.jsonl"
)


def _cases() -> dict[str, IntentCase]:
    return {case.case_id: case for case in load_cases(CASES_PATH)}


def _proposal_for(case: IntentCase) -> SemanticIntentProposal:
    return SemanticIntentProposal.model_validate_json(
        json.dumps(
            {
                "goal": case.expected.goal.value,
                "topic": (
                    case.expected.topic.value
                    if case.expected.topic is not None
                    else None
                ),
                "concerns": [
                    item.value for item in case.expected.concerns
                ],
                "observations": [
                    item.model_dump(mode="json")
                    for item in case.expected.observations
                ],
                "references": [
                    item.model_dump(mode="json")
                    for item in case.expected.references
                ],
                "confidence": 0.99,
                "clarification_hint": (
                    ClarificationCode.GOAL.value
                    if case.expected.must_clarify
                    else None
                ),
            },
            ensure_ascii=False,
        ),
        strict=True,
    )


def test_fixture_snapshot_round_trips_semantic_context(
    tmp_path: Path,
) -> None:
    cases = _cases()

    for case_id in OPEN_SEMANTIC_CASE_IDS:
        case = cases[case_id]
        result = build_fixture_snapshot(
            case=case,
            state_dir=tmp_path / case_id,
            session_id=f"task6-{case_id}",
        )

        assert result.status == "BUILT"
        assert isinstance(result.snapshot, ConversationSnapshot)
        assert result.snapshot.profile_owner is not None
        assert result.semantic_context == case.context
        assert tuple(
            candidate.product_id
            for candidate in result.snapshot.candidates
        ) == result.canonical_product_ids
        assert len(result.canonical_product_ids) == (
            case.context.visible_candidate_count
        )


def test_four_candidate_context_round_trips_through_snapshot(
    tmp_path: Path,
) -> None:
    case = _cases()["follow-004-fourth-candidate"]

    result = build_fixture_snapshot(
        case=case,
        state_dir=tmp_path,
        session_id="task6-four-candidates",
    )

    assert result.status == "BUILT"
    assert result.reason is None
    assert result.snapshot is not None
    assert len(result.snapshot.candidates) == 4


def test_14_open_cases_call_semantic_once_through_real_stream(
    tmp_path: Path,
) -> None:
    cases = _cases()
    observations = [
        ProductionRoutingGate().evaluate(
            case=cases[case_id],
            proposal=_proposal_for(cases[case_id]),
            state_dir=tmp_path / case_id,
        )
        for case_id in OPEN_SEMANTIC_CASE_IDS
    ]

    assert len(observations) == 14
    assert all(item.entrypoint == "stream" for item in observations)
    assert all(item.snapshot_status == "BUILT" for item in observations)
    assert all(item.semantic_invocation_count == 1 for item in observations)
    assert all(item.legacy_fallback_count == 0 for item in observations)
    assert all(item.terminal_event == "end" for item in observations)


class ProductionOnlyOrchestrator:
    def __init__(self, semantic, context) -> None:
        self._semantic = semantic
        self._context = context

    def stream(self, turn: UserTurn):
        self._semantic.propose(turn.message, self._context)
        yield StartEvent(data=StartData(session_id=turn.session_id))
        yield IntentEvent(data=IntentData(mode="clarify"))
        yield ClarifyEvent(
            data=ClarifyData(
                question="请确认要完成的导购任务。",
                clarification_code=ClarificationCode.GOAL,
            )
        )
        yield EndEvent(
            data=EndData(
                conversation_version=turn.conversation_version,
            )
        )

    def stream_text_vertical(self, turn: UserTurn):
        del turn
        raise AssertionError(
            "production routing must not call model vertical"
        )


def test_production_gate_calls_stream_not_model_vertical(
    tmp_path: Path,
) -> None:
    case = _cases()["clar-004-low-info-question"]
    observed = ProductionRoutingGate(
        orchestrator_factory=lambda **kwargs: ProductionOnlyOrchestrator(
            kwargs["semantic_intent"],
            case.context,
        )
    ).evaluate(
        case=case,
        proposal=_proposal_for(case),
        state_dir=tmp_path,
    )

    assert observed.entrypoint == "stream"
    assert observed.semantic_invocation_count == 1


def test_open_reference_cases_never_emit_wrong_cards(
    tmp_path: Path,
) -> None:
    cases = _cases()

    observations = [
        ProductionRoutingGate().evaluate(
            case=cases[case_id],
            proposal=_proposal_for(cases[case_id]),
            state_dir=tmp_path / case_id,
        )
        for case_id in WRONG_CARD_CASE_IDS
    ]

    assert len(observations) == 5
    assert all(item.semantic_invocation_count == 1 for item in observations)
    unsupported = observations[:2]
    assert all(item.selection_event_count == 0 for item in unsupported)
    assert all("products" not in item.event_types for item in unsupported)

    bound_references = observations[2:]
    assert all(
        item.selection_event_count == 1 for item in bound_references
    )
    assert all("products" in item.event_types for item in bound_references)
    for item in bound_references:
        assert item.snapshot_before is not None
        assert item.snapshot_after is not None
        expected = item.snapshot_before.candidates[1].product_id
        assert item.product_event_ids == (expected,)
        assert (
            item.snapshot_after.candidates
            == item.snapshot_before.candidates
        )
        assert item.snapshot_after.focused_candidate_ordinal == 2


def test_candidate_ordinal_suitability_emits_only_bound_product(
    tmp_path: Path,
) -> None:
    case = _cases()["suit-011-candidate-ordinal"]

    observed = ProductionRoutingGate().evaluate(
        case=case,
        proposal=_proposal_for(case),
        state_dir=tmp_path,
    )

    assert observed.task_plan_mode == "suitability"
    assert observed.selection_event_count == 1
    assert "products" in observed.event_types
    assert observed.snapshot_before is not None
    assert observed.snapshot_after is not None
    expected_product_id = (
        observed.snapshot_before.candidates[2].product_id
    )
    assert observed.product_event_ids == (expected_product_id,)
    assert (
        observed.snapshot_after.candidates
        == observed.snapshot_before.candidates
    )
    assert observed.snapshot_after.focused_candidate_ordinal == 3


def test_focused_and_ordinal_comparison_emit_only_bound_products(
    tmp_path: Path,
) -> None:
    case = _cases()["cmp-012-pronoun-second"]

    observed = ProductionRoutingGate().evaluate(
        case=case,
        proposal=_proposal_for(case),
        state_dir=tmp_path,
    )

    assert observed.task_plan_mode == "comparison"
    assert observed.selection_event_count == 1
    assert "products" in observed.event_types
    assert observed.snapshot_before is not None
    assert observed.snapshot_after is not None
    expected_product_ids = {
        observed.snapshot_before.candidates[0].product_id,
        observed.snapshot_before.candidates[1].product_id,
    }
    assert {
        item.product_id
        for item in observed.snapshot_after.candidates
    } == expected_product_ids


def test_closed_operations_skip_semantic_with_full_message_proof(
    tmp_path: Path,
) -> None:
    cases = _cases()

    observations = [
        ProductionRoutingGate().evaluate(
            case=cases[case_id],
            proposal=_proposal_for(cases[case_id]),
            state_dir=tmp_path / case_id,
        )
        for case_id in CLOSED_OPERATION_CASE_IDS
    ]

    assert len(observations) == 2
    assert all(item.semantic_invocation_count == 0 for item in observations)
    assert all(
        item.operation_source_span == (0, len(item.message))
        for item in observations
    )
    assert all(item.selection_event_count == 1 for item in observations)


def test_missing_state_is_real_empty_state_and_does_not_fabricate_candidates(
    tmp_path: Path,
) -> None:
    case = _cases()["clar-004-low-info-question"]

    observed = ProductionRoutingGate().evaluate(
        case=case,
        proposal=_proposal_for(case),
        state_dir=tmp_path,
    )

    assert observed.snapshot_status == "EMPTY"
    assert observed.snapshot_before is None
    assert observed.snapshot_after is None
    assert observed.semantic_invocation_count == 1
    assert observed.selection_event_count == 0
    assert observed.event_types[-2:] == ("clarify", "end")


class FailingSemanticPort:
    def __init__(self) -> None:
        self.invocation_count = 0

    def propose(self, message, context):
        del message, context
        self.invocation_count += 1
        raise SemanticProviderFailure(
            SemanticProviderFailureCode.PROVIDER_UNAVAILABLE
        )


def test_provider_failure_on_production_stream_never_calls_legacy(
    tmp_path: Path,
) -> None:
    case = _cases()["know-012-candidate-reference"]
    semantic = FailingSemanticPort()

    observed = ProductionRoutingGate().evaluate(
        case=case,
        semantic_port=semantic,
        state_dir=tmp_path,
    )

    assert observed.entrypoint == "stream"
    assert observed.semantic_invocation_count == 1
    assert observed.legacy_fallback_count == 0
    assert observed.selection_event_count == 0
    assert "error" not in observed.event_types
    assert observed.terminal_event == "end"
