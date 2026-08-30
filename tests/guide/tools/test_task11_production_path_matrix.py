from __future__ import annotations

import ast
from hashlib import sha256
import inspect
import json
from pathlib import Path
import subprocess
import textwrap

import pytest

from tools.guide_gates import (
    attempt_ledger,
    run_task11_production_path_matrix as production_matrix,
)
from app.guide.feedback.contracts import (
    ConversationSnapshot,
    DisplayedCandidateRef,
    ImageSlotState,
    ProductSlotState,
    RecommendationQueryContext,
    RecommendationSlotState,
)
from app.guide.feedback.focus_state import (
    ActiveFocus,
    ConfirmedImageProductRef,
)
from app.guide.application.consultation_chat_flow import (
    ConsultationChatFlow,
)
from app.guide.application.image_recommendation_flow import (
    ImageRecommendationOrchestrator,
)
from app.guide.application.text_recommendation_flow import (
    TextRecommendationOrchestrator,
)
from app.guide.application.unified_guide_flow import UnifiedGuideFlow
from app.guide.intent.contracts import SkinConstraint
from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.intent.task_planning import plan_task
from app.guide.intent.unified_turn_router import UnifiedRouteDecision
from app.guide.retrieval.product_name_resolver import ResolvedProductBinding
from app.guide.understanding.contracts import (
    ReferenceDraft,
    StructuredUnderstanding,
    TopicCode,
    UnderstandingGoal,
)
from app.guide.understanding.typed_image_action import (
    turn_meaning_for_image_action,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning
from app.guide_runtime.composition import REPO_ROOT
from tools.guide_gates.run_task11_production_path_matrix import (
    DEFAULT_CASES_PATH,
    ProductionPathCase,
    ProductionPathInvariantError,
    ProductionPathSummary,
    StateCoveragePoint,
    Task11ProductionPathRuntime,
    ProductionPathTurnTrace,
    _ProductionPathObserver,
    _derive_state_coverage,
    _parse_sse,
    _validate_bounded_trajectory_contract,
    run_production_path_matrix,
    summarize_production_path,
    validate_bounded_turns,
    load_production_path_cases,
    validate_production_path_trace,
    validate_state_edge_coverage,
)
from tools.guide_gates.build_task11_readiness import (
    canonical_payload_sha256,
)


def _candidate_manifest_for_verifier(
    tmp_path: Path,
) -> tuple[Path, Path, Path]:
    root = tmp_path / "repo"
    cases = root / "tests/fixtures/guide/cases.jsonl"
    tool = root / "tools/guide_gates/run_task11_production_path_matrix.py"
    plan = root / "docs/superpowers/plans/task11.md"
    for path, content in (
        (cases, "{}\n"),
        (tool, "VALUE = 1\n"),
        (
            plan,
            "Task 11 evidence epoch: repair-epoch-54\n",
        ),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    protected = sorted(
        path.relative_to(root).as_posix()
        for path in (cases, tool, plan)
    )
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "tests@example.com"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Tests"],
        cwd=root,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "candidate"],
        cwd=root,
        check=True,
    )
    candidate_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    ledger = (
        root
        / "docs/audits/final-release/mainline-contract-closure"
        / "smoke-attempt-ledger.json"
    )
    attempt_ledger.initialize_ledger(ledger)
    ledger_bytes = ledger.read_bytes()
    ledger_anchor = attempt_ledger.ledger_anchor(
        attempt_ledger.read_ledger(ledger)
    )
    payload_sha256 = canonical_payload_sha256(root, protected)
    manifest = (
        root
        / "docs/audits/final-release/mainline-contract-closure"
        / "repair-epoch-54"
        / "task11-candidate-manifest.json"
    )
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "schema_version": (
                    "guide-task11-candidate-manifest-v1"
                ),
                "repository_root": str(root.resolve()),
                "plan_revision": "2026-08-27-task11-r33",
                "repair_epoch": 54,
                "candidate_head": candidate_head,
                "source_paths": [],
                "test_paths": [],
                "tool_paths": [tool.relative_to(root).as_posix()],
                "plan_paths": [plan.relative_to(root).as_posix()],
                "fixture_paths": [cases.relative_to(root).as_posix()],
                "deleted_paths": [],
                "deleted_base_blob_sha256_by_path": {},
                "mutable_evidence_paths": [
                    "docs/audits/final-release/"
                    "mainline-contract-closure/"
                    "smoke-attempt-ledger.json"
                ],
                "excluded_paths": [],
                "protected_paths": protected,
                "change_paths": [],
                "candidate_payload_sha256": payload_sha256,
                "protected_payload_sha256": payload_sha256,
                "fixture_runtime_public_keys": [
                    "A" * 43,
                    "Kay64UG8yvCyLhqU000LxzYeUm0L_hLIl5S8kyKWbdc",
                ],
                "fixture_runtime_private_key_paths": [
                    str((tmp_path / "runtime-key.json").resolve()),
                    str(
                        (
                            tmp_path / "runtime-key.retry-2.json"
                        ).resolve()
                    ),
                ],
                "pre_checkpoint_ledger": {
                    "path": str(ledger.resolve()),
                    "sha256": sha256(ledger_bytes).hexdigest(),
                    "revision": ledger_anchor["revision"],
                    "revision_hash": ledger_anchor["revision_hash"],
                },
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return root, manifest, cases


def _trace(**updates) -> ProductionPathTurnTrace:
    values = {
        "turn_id": "trajectory-1-t1",
        "trajectory_id": "trajectory-1",
        "partition": "state",
        "translation_injection_count": 1,
        "structured_understanding_injection_count": 0,
        "compiler_call_count": 1,
        "direct_router_bypass_count": 0,
        "legacy_entrypoint_count": 0,
        "router_call_count": 1,
        "route_decision_digest": "a" * 64,
        "selected_processor_decision_digest": "a" * 64,
        "result_decision_digest": "a" * 64,
        "sse_decision_digest": "a" * 64,
        "validated_sse_sha256": "b" * 64,
        "emitted_sse_sha256": "b" * 64,
        "selected_processor": "recommendation",
        "processor_invocation_counts": {
            "recommendation": 1,
            "comparison": 0,
        },
        "processor_implementation_counts": {
            "TextRecommendationOrchestrator": 1,
        },
        "selected_processor_instance_entry_count": 1,
        "unregistered_processor_invocation_count": 0,
        "decision_identity_violation_count": 0,
        "execution_result_count": 1,
        "reducer_call_count": 1,
        "state_save_count": 1,
        "state_save_completed_count": 1,
        "state_backend": "SqliteConversationState",
        "processor_state_write_count": 0,
        "event_state_projection_count": 0,
        "provider_call_count": 0,
        "outbound_network_attempt_count": 0,
        "loaded_version": 0,
        "committed_version": 1,
        "expected_state_edge": "none->recommendation",
        "observed_state_edge": "none->recommendation",
        "terminal_event": "end",
        "bounded": False,
        "semantic_equivalence_passed": True,
        "observed_layers": (
            "translation",
            "compiler",
            "router",
            "processor",
            "reducer",
            "sqlite",
            "sse",
        ),
    }
    values.update(updates)
    return ProductionPathTurnTrace(**values)


def _comparison_understanding(
    *references: ReferenceDraft,
    topic: TopicCode,
) -> StructuredUnderstanding:
    return StructuredUnderstanding(
        goal=UnderstandingGoal.COMPARISON,
        topic=topic,
        observations=[],
        exact_constraints=[],
        semantic_proposals=[],
        references=list(references),
        image_references=[],
        uncertainties=[],
        confidence=1.0,
        question_meaning="比较当前已确认商品",
    )


def _comparison_decision(
    understanding: StructuredUnderstanding,
    *,
    focus_source: str,
) -> UnifiedRouteDecision:
    product_ids = (53, 38)
    return UnifiedRouteDecision(
        processor="comparison",
        responsibility=Responsibility.COMPARISON,
        presentation_mode="comparison",
        public_intent_mode="comparison",
        continuity="continue",
        focus_source=focus_source,
        product_bindings=tuple(
            ResolvedProductBinding(
                product_id=product_id,
                source_text=f"observed:{index}",
                source_kind="explicit_product",
            )
            for index, product_id in enumerate(product_ids, start=1)
        ),
        task_plan=plan_task(
            understanding,
            responsibility=Responsibility.COMPARISON,
            resolved_product_ids=product_ids,
        ),
    )


def _committed_comparison_snapshot(
    *,
    session_id: str,
    version: int,
) -> ConversationSnapshot:
    products = (
        DisplayedCandidateRef(
            product_id=53,
            ordinal=1,
            skin_match="unknown",
            matched_efficacies=(),
        ),
        DisplayedCandidateRef(
            product_id=38,
            ordinal=2,
            skin_match="unknown",
            matched_efficacies=(),
        ),
    )
    return ConversationSnapshot(
        session_id=session_id,
        version=version,
        active_owner=Responsibility.COMPARISON,
        active_focus=ActiveFocus(slot="product", object_id=53),
        product_slot=ProductSlotState(
            products=products,
            focused_product_id=53,
        ),
    )


def test_sse_bytes_are_decoded_only_at_assertion_boundary() -> None:
    frame = b'event: start\ndata: {"session_id":"session-1"}\n\n'

    assert _parse_sse(frame) == (
        ("start", {"session_id": "session-1"}),
    )
    with pytest.raises(TypeError, match="SSE payload must be bytes"):
        _parse_sse(frame.decode("utf-8"))


def test_matrix_rejects_structured_understanding_injection() -> None:
    trace = _trace(structured_understanding_injection_count=1)

    with pytest.raises(
        ProductionPathInvariantError,
        match="StructuredUnderstanding injection",
    ):
        validate_production_path_trace(trace)


def test_matrix_rejects_direct_router_bypass() -> None:
    trace = _trace(direct_router_bypass_count=1)

    with pytest.raises(
        ProductionPathInvariantError,
        match="direct router bypass",
    ):
        validate_production_path_trace(trace)


def test_matrix_covers_all_expected_and_required_state_edges() -> None:
    traces = (
        _trace(
            expected_state_edge="none->recommendation",
            coverage_edges=(
                "active_owner=recommendation|"
                "reply_state=not_awaiting",
            ),
        ),
        _trace(
            turn_id="trajectory-1-t2",
            expected_state_edge="recommendation->product_knowledge",
            observed_state_edge="recommendation->product_knowledge",
            coverage_edges=(
                "active_owner=product_knowledge|"
                "reference_source=candidate_ordinal",
            ),
        ),
    )

    validate_state_edge_coverage(
        traces,
        required_state_edges=(
            "active_owner=recommendation|"
            "reply_state=not_awaiting",
            "active_owner=product_knowledge|"
            "reference_source=candidate_ordinal",
        ),
    )

    with pytest.raises(
        ProductionPathInvariantError,
        match="missing required state edges",
    ):
        validate_state_edge_coverage(
            traces,
            required_state_edges=(
                "active_owner=recommendation|"
                "reply_state=not_awaiting",
                "active_owner=product_knowledge|"
                "reference_source=candidate_ordinal",
                "reply_state=pending_clarification|"
                "reference_source=ambiguous_reference",
            ),
        )


def test_matrix_rejects_reassigned_per_case_coverage() -> None:
    cases = load_production_path_cases(DEFAULT_CASES_PATH)
    first, second = cases[120:122]
    assert first.expected_coverage is not None
    assert second.expected_coverage is not None
    traces = (
        _trace(
            turn_id=first.case_id,
            trajectory_id=first.trajectory_id,
            partition=first.partition,
            expected_state_edge=first.expected_state_edge,
            observed_state_edge=first.expected_state_edge,
            coverage_edges=second.expected_coverage.edge_ids(),
            actual_processor=first.expected_processor or "recommendation",
        ),
        _trace(
            turn_id=second.case_id,
            trajectory_id=second.trajectory_id,
            partition=second.partition,
            expected_state_edge=second.expected_state_edge,
            observed_state_edge=second.expected_state_edge,
            selected_processor=(
                second.expected_processor or "recommendation"
            ),
            processor_invocation_counts={
                second.expected_processor or "recommendation": 1,
            },
            coverage_edges=first.expected_coverage.edge_ids(),
            actual_processor=second.expected_processor or "recommendation",
            card_ids=second.expected_card_ids or (),
        ),
    )
    validator = getattr(
        production_matrix,
        "validate_case_trace_bindings",
        None,
    )
    assert callable(validator)

    with pytest.raises(
        ProductionPathInvariantError,
        match="coverage",
    ):
        validator(cases=(first, second), traces=traces)


def test_matrix_runs_all_nine_bounded_turns_without_provider_calls() -> None:
    traces = tuple(
        _trace(
            turn_id=f"bounded-{index}",
            trajectory_id="bounded",
            partition="bounded",
            bounded=True,
        )
        for index in range(9)
    )

    validate_bounded_turns(traces)


def test_matrix_rejects_legacy_production_entrypoint() -> None:
    trace = _trace(legacy_entrypoint_count=1)

    with pytest.raises(
        ProductionPathInvariantError,
        match="legacy production entrypoint",
    ):
        validate_production_path_trace(trace)


def test_matrix_rejects_multiple_compiler_calls_per_turn() -> None:
    trace = _trace(compiler_call_count=2)

    with pytest.raises(
        ProductionPathInvariantError,
        match="exactly one compiler call",
    ):
        validate_production_path_trace(trace)


def test_matrix_rejects_multiple_router_calls_per_turn() -> None:
    trace = _trace(router_call_count=2)

    with pytest.raises(
        ProductionPathInvariantError,
        match="exactly one router call",
    ):
        validate_production_path_trace(trace)


@pytest.mark.parametrize("execution_result_count", (0, 2))
def test_matrix_rejects_missing_or_multiple_execution_results(
    execution_result_count: int,
) -> None:
    trace = _trace(execution_result_count=execution_result_count)

    with pytest.raises(
        ProductionPathInvariantError,
        match="exactly one ExecutionResult",
    ):
        validate_production_path_trace(trace)


def test_matrix_accepts_pre_decision_rejection_trace_contract() -> None:
    trace = ProductionPathTurnTrace(
        turn_id="predecision-stale-version-rejection-001",
        trajectory_id="coverage-image-consultation",
        partition="pre_decision_rejection",
        rejection_stage="pre_decision",
        translation_injection_count=0,
        structured_understanding_injection_count=0,
        compiler_call_count=0,
        direct_router_bypass_count=0,
        legacy_entrypoint_count=0,
        router_call_count=0,
        route_decision_digest="0" * 64,
        selected_processor_decision_digest="0" * 64,
        result_decision_digest="0" * 64,
        sse_decision_digest="0" * 64,
        validated_sse_sha256="b" * 64,
        emitted_sse_sha256="b" * 64,
        selected_processor="none",
        processor_invocation_counts={
            "recommendation": 0,
            "comparison": 0,
        },
        processor_implementation_counts={},
        selected_processor_instance_entry_count=0,
        unregistered_processor_invocation_count=0,
        decision_identity_violation_count=0,
        execution_result_count=0,
        reducer_call_count=0,
        state_save_count=0,
        state_save_completed_count=0,
        state_backend="SqliteConversationState",
        processor_state_write_count=0,
        event_state_projection_count=0,
        provider_call_count=0,
        outbound_network_attempt_count=0,
        loaded_version=3,
        committed_version=3,
        expected_state_edge="recommendation->recommendation",
        observed_state_edge="recommendation->recommendation",
        terminal_event="error",
        bounded=False,
        semantic_equivalence_passed=True,
        accepted=False,
        coverage_edges=(),
        actual_processor="none",
        actual_intent="",
        card_ids=(),
        event_names=("start", "error"),
        observed_layers=("http", "sse"),
    )

    validate_production_path_trace(trace)


@pytest.mark.parametrize("reducer_call_count", (0, 2))
def test_matrix_rejects_missing_or_multiple_reducer_calls(
    reducer_call_count: int,
) -> None:
    trace = _trace(reducer_call_count=reducer_call_count)

    with pytest.raises(
        ProductionPathInvariantError,
        match="exactly one reducer call",
    ):
        validate_production_path_trace(trace)


@pytest.mark.parametrize("state_save_count", (0, 2))
def test_matrix_rejects_missing_or_multiple_state_save_per_accepted_turn(
    state_save_count: int,
) -> None:
    trace = _trace(state_save_count=state_save_count)

    with pytest.raises(
        ProductionPathInvariantError,
        match="exactly one state save",
    ):
        validate_production_path_trace(trace)


def test_matrix_rejects_event_to_state_projection() -> None:
    trace = _trace(event_state_projection_count=1)

    with pytest.raises(
        ProductionPathInvariantError,
        match="event-to-state projection",
    ):
        validate_production_path_trace(trace)


def test_matrix_rejects_copied_execution_decision() -> None:
    trace = _trace(decision_identity_violation_count=1)

    with pytest.raises(
        ProductionPathInvariantError,
        match="exact route decision object",
    ):
        validate_production_path_trace(trace)


def test_matrix_rejects_nonselected_processor_invocation() -> None:
    trace = _trace(
        processor_invocation_counts={
            "recommendation": 1,
            "comparison": 1,
        }
    )

    with pytest.raises(
        ProductionPathInvariantError,
        match="non-selected processor invocation",
    ):
        validate_production_path_trace(trace)


def test_matrix_rejects_emitted_bytes_that_differ_from_envelope() -> None:
    trace = _trace(emitted_sse_sha256="c" * 64)

    with pytest.raises(
        ProductionPathInvariantError,
        match="emitted SSE bytes",
    ):
        validate_production_path_trace(trace)


def test_state_coverage_classifies_image_batch_as_current_batch() -> None:
    understanding = _comparison_understanding(
        ReferenceDraft(kind="current_batch"),
        topic=TopicCode.SUNSCREEN,
    )
    point = _derive_state_coverage(
        current=None,
        understanding=understanding,
        decision=_comparison_decision(
            understanding,
            focus_source="confirmed_image",
        ),
        committed=_committed_comparison_snapshot(
            session_id="coverage-image-batch",
            version=1,
        ),
    )

    assert point.reference_source == "current_batch"
    assert point.semantic_act == "explicit_product_question"


def test_state_coverage_classifies_sole_unnumbered_image_reference() -> None:
    current = ConversationSnapshot(
        session_id="coverage-image-reference",
        version=2,
        active_owner=Responsibility.RECOMMENDATION,
        active_focus=ActiveFocus(slot="recommendation"),
        recommendation_slot=RecommendationSlotState(
            query_context=RecommendationQueryContext(
                category="serum",
                recommendation_mode="explore",
                recommendation_mode_basis="broad_exploration",
                recommendation_count=3,
            ),
            candidates=(
                DisplayedCandidateRef(
                    product_id=38,
                    ordinal=1,
                    skin_match="unknown",
                    matched_efficacies=(),
                ),
                DisplayedCandidateRef(
                    product_id=91,
                    ordinal=2,
                    skin_match="unknown",
                    matched_efficacies=(),
                ),
            ),
        ),
        image_slot=ImageSlotState(
            confirmed_products=(
                ConfirmedImageProductRef(
                    image_ordinal=1,
                    product_id=53,
                ),
            ),
            focused_image_ordinal=1,
        ),
    )
    understanding = _comparison_understanding(
        ReferenceDraft(kind="image_ordinal", ordinal=1),
        ReferenceDraft(kind="candidate_ordinal", ordinal=1),
        topic=TopicCode.SERUM,
    )
    point = _derive_state_coverage(
        current=current,
        understanding=understanding,
        decision=_comparison_decision(
            understanding,
            focus_source="candidate_batch",
        ),
        committed=_committed_comparison_snapshot(
            session_id=current.session_id,
            version=current.version + 1,
        ),
    )

    assert point.reference_source == "image_ordinal"
    assert point.semantic_act == "explicit_image_question"


def test_matrix_invokes_real_http_entrypoint_and_persists_once(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GUIDE_LLM_API_KEY", raising=False)
    monkeypatch.delenv("GUIDE_COPY_LLM_API_KEY", raising=False)
    case = ProductionPathCase(
        case_id="semantic-recommendation-001",
        trajectory_id="semantic-recommendation-001",
        partition="semantic",
        message="推荐500元内适合敏感肌的修护精华",
        meaning=TurnMeaning(
            operation_hint="recommendation",
            recommendation_mode="explore",
            recommendation_count=None,
            recommendation_mode_basis={
                "basis": "broad_exploration",
                "source_text": "推荐",
            },
            topic_hint="serum",
            continuity_hint="new_task",
            subject_scope_hint="self",
            budget_candidates=(
                {
                    "raw_text": "500元内",
                    "relation": "maximum",
                    "maximum": "500",
                },
            ),
            safety_language="ordinary",
        ),
        expected_state_edge="none->recommendation",
        expected_intent="recommend",
        expected_card_ids=(38, 91),
    )
    runtime = Task11ProductionPathRuntime(
        repo_root=REPO_ROOT,
        state_root=tmp_path / "state",
    )
    registry = runtime._vertical.unified._processor_registry

    assert registry["image_identity"] is runtime._vertical.image_processor
    assert registry["image_comparison"] is runtime._vertical.image_processor
    assert (
        runtime._vertical.image_bundle_service
        is runtime._client.app.state.image_bundle_service
    )

    trace = runtime.execute(case)

    validate_production_path_trace(trace)
    assert trace.partition == "semantic"
    assert trace.translation_injection_count == 1
    assert trace.compiler_call_count == 1
    assert trace.router_call_count == 1
    assert trace.execution_result_count == 1
    assert trace.reducer_call_count == 1
    assert trace.state_save_count == 1
    assert trace.loaded_version == 0
    assert trace.committed_version == 1
    assert trace.route_decision_digest == trace.result_decision_digest
    assert trace.observed_state_edge == "none->recommendation"
    assert trace.actual_processor == "recommendation"
    assert trace.actual_intent == "recommend"
    assert trace.card_ids == (38, 91)
    assert trace.event_names[0] == "start"
    assert trace.event_names[-1] == "end"


def test_matrix_exercises_stale_version_pre_decision_rejection(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GUIDE_LLM_API_KEY", raising=False)
    monkeypatch.delenv("GUIDE_COPY_LLM_API_KEY", raising=False)
    accepted = ProductionPathCase(
        case_id="stale-rejection-seed-t1",
        trajectory_id="stale-rejection-seed",
        partition="semantic",
        message="推荐500元内适合敏感肌的修护精华",
        meaning=TurnMeaning(
            operation_hint="recommendation",
            recommendation_mode="explore",
            recommendation_count=None,
            recommendation_mode_basis={
                "basis": "broad_exploration",
                "source_text": "推荐",
            },
            topic_hint="serum",
            continuity_hint="new_task",
            subject_scope_hint="self",
            budget_candidates=(
                {
                    "raw_text": "500元内",
                    "relation": "maximum",
                    "maximum": "500",
                },
            ),
            safety_language="ordinary",
        ),
        expected_state_edge="none->recommendation",
        expected_processor="recommendation",
        expected_intent="recommend",
        expected_card_ids=(38, 91),
    )
    stale = ProductionPathCase(
        case_id="predecision-stale-version-rejection-001",
        trajectory_id=accepted.trajectory_id,
        partition="pre_decision_rejection",
        message="这条请求使用旧版本，应该被拒绝",
        conversation_version_delta=-1,
        expected_terminal_event="error",
        expected_rejection_stage="pre_decision",
        meaning=TurnMeaning(
            operation_hint="recommendation",
            recommendation_mode="explore",
            recommendation_count=None,
            recommendation_mode_basis={
                "basis": "broad_exploration",
                "source_text": "推荐",
            },
            topic_hint="serum",
            continuity_hint="new_task",
            subject_scope_hint="self",
            safety_language="ordinary",
        ),
        expected_state_edge="recommendation->recommendation",
        expected_processor="none",
    )
    runtime = Task11ProductionPathRuntime(
        repo_root=REPO_ROOT,
        state_root=tmp_path / "state",
    )

    accepted_trace = runtime.execute(accepted)
    stale_trace = runtime.execute(stale)

    validate_production_path_trace(accepted_trace)
    validate_production_path_trace(stale_trace)
    assert stale_trace.event_names == ("start", "error")
    assert stale_trace.translation_injection_count == 0
    assert stale_trace.compiler_call_count == 0
    assert stale_trace.router_call_count == 0
    assert stale_trace.execution_result_count == 0
    assert stale_trace.reducer_call_count == 0
    assert stale_trace.state_save_count == 0
    assert stale_trace.loaded_version == 1
    assert stale_trace.committed_version == 1


def test_semantic_partition_does_not_duplicate_ranking_contract(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GUIDE_LLM_API_KEY", raising=False)
    monkeypatch.delenv("GUIDE_COPY_LLM_API_KEY", raising=False)
    case = ProductionPathCase(
        case_id="semantic-recommendation-unpinned-cards",
        trajectory_id="semantic-recommendation-unpinned-cards",
        partition="semantic",
        message="推荐500元内适合敏感肌的修护精华",
        meaning=TurnMeaning(
            operation_hint="recommendation",
            recommendation_mode="explore",
            recommendation_count=None,
            recommendation_mode_basis={
                "basis": "broad_exploration",
                "source_text": "推荐",
            },
            topic_hint="serum",
            continuity_hint="new_task",
            subject_scope_hint="self",
            budget_candidates=(
                {
                    "raw_text": "500元内",
                    "relation": "maximum",
                    "maximum": "500",
                },
            ),
            safety_language="ordinary",
        ),
        expected_state_edge="none->recommendation",
        expected_intent="recommend",
        expected_card_ids=None,
    )
    runtime = Task11ProductionPathRuntime(
        repo_root=REPO_ROOT,
        state_root=tmp_path / "state",
    )

    trace = runtime.execute(case)

    validate_production_path_trace(trace)
    assert trace.card_ids


def test_matrix_typed_image_action_reaches_cross_source_comparison(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GUIDE_LLM_API_KEY", raising=False)
    monkeypatch.delenv("GUIDE_COPY_LLM_API_KEY", raising=False)
    question_summary = "识别上传图片中的商品"
    case = ProductionPathCase(
        case_id="bounded-image-context-t1",
        trajectory_id="bounded-image-context",
        partition="bounded",
        message="",
        image_action="identify",
        image_paths=(
            "tests/fixtures/guide/images/"
            "product-38-index-control.png",
        ),
        meaning=turn_meaning_for_image_action(
            action="identify",
            image_count=1,
            question_summary=question_summary,
        ),
        expected_state_edge="none->image_identity",
        expected_coverage=StateCoveragePoint(
            active_owner="none",
            reply_state="not_awaiting",
            preserved_authority="none",
            semantic_act="explicit_image_question",
            reference_source="image_ordinal",
        ),
        required_state_edges=(
            "active_owner=none|"
            "reference_source=image_ordinal",
        ),
        expected_processor="image_identity",
        expected_intent="image_identity",
        expected_card_ids=(38,),
        bounded=True,
    )
    runtime = Task11ProductionPathRuntime(
        repo_root=REPO_ROOT,
        state_root=tmp_path / "state",
    )

    identity_trace = runtime.execute(case)
    image_product_name = "理肤泉新B5多效修护精华"
    similarity = ProductionPathCase(
        case_id="bounded-image-context-t2",
        trajectory_id="bounded-image-context",
        partition="bounded",
        message=(
            f"以图片里的{image_product_name}为参照，给我找两款相似的，"
            "我最近换季泛红，T 区出油。"
        ),
        meaning=TurnMeaning(
            operation_hint="image_similarity",
            recommendation_mode="explore",
            recommendation_count=2,
            recommendation_mode_basis={
                "basis": "similar_alternatives",
                "source_text": "两款相似",
            },
            topic_hint="serum",
            continuity_hint="continue",
            subject_scope_hint="self",
            reference_mentions=(
                {
                    "raw_text": "图片里的",
                    "object_family_hint": "image",
                    "ordinal_hint": 1,
                    "plurality_hint": "single",
                },
            ),
            product_mentions=(
                {"raw_text": image_product_name},
            ),
            observation_candidates=(
                {
                    "observation_id": "obs_redness",
                    "code": "redness",
                    "present": True,
                    "qualifier": None,
                    "raw_text": "换季泛红",
                    "trigger": "seasonal",
                    "duration": "current",
                },
                {
                    "observation_id": "obs_oiliness",
                    "code": "oiliness",
                    "present": True,
                    "qualifier": "t_zone",
                    "raw_text": "T 区出油",
                    "location": "t_zone",
                    "duration": "current",
                },
            ),
            preference_candidates=(
                {
                    "field_key": "efficacy",
                    "concept_id": "efficacy.soothing",
                    "raw_text": "换季泛红",
                    "polarity": "prefer",
                    "strength": "ordinary",
                },
            ),
            question_meaning=(
                "基于图片原品寻找两款适合换季泛红和"
                "T区出油的相似精华"
            ),
            safety_language="ordinary",
        ),
        expected_state_edge="image_identity->recommendation",
        expected_coverage=StateCoveragePoint(
            active_owner="image_identity",
            reply_state="not_awaiting",
            preserved_authority="one_confirmed_image",
            semantic_act="explicit_image_question",
            reference_source="image_ordinal",
        ),
        required_state_edges=(
            "active_owner=image_identity|"
            "preserved_authority=one_confirmed_image",
        ),
        expected_processor="recommendation",
        expected_intent="recommend",
        expected_card_ids=(91, 39),
        bounded=True,
    )
    similarity_trace = runtime.execute(similarity)
    first_result_name = "玉泽皮肤屏障修护精华乳"
    comparison = ProductionPathCase(
        case_id="bounded-image-context-t3",
        trajectory_id="bounded-image-context",
        partition="bounded",
        message=(
            f"{image_product_name}和第一款{first_result_name}"
            "哪个更适合我的肤质？"
        ),
        meaning=TurnMeaning(
            operation_hint="comparison",
            topic_hint="serum",
            continuity_hint="continue",
            subject_scope_hint="self",
            product_mentions=(
                {"raw_text": image_product_name},
                {"raw_text": first_result_name},
            ),
            reference_mentions=(
                {
                    "raw_text": "第一款",
                    "object_family_hint": "product",
                    "ordinal_hint": 1,
                    "plurality_hint": "single",
                },
            ),
            question_meaning=(
                "比较图片里的B5和相似结果第一款"
                "哪个更适合当前肤质"
            ),
            safety_language="ordinary",
        ),
        expected_state_edge="recommendation->comparison",
        expected_coverage=StateCoveragePoint(
            active_owner="recommendation",
            reply_state="not_awaiting",
            preserved_authority="one_confirmed_image",
            semantic_act="explicit_product_question",
            reference_source="candidate_ordinal",
        ),
        required_state_edges=(
            "active_owner=recommendation|"
            "reference_source=candidate_ordinal",
        ),
        expected_processor="comparison",
        expected_intent="comparison",
        expected_card_ids=(38, 91),
        bounded=True,
    )
    comparison_trace = runtime.execute(comparison)

    for trace in (
        identity_trace,
        similarity_trace,
        comparison_trace,
    ):
        validate_production_path_trace(trace)
        assert trace.translation_injection_count == 1
        assert trace.compiler_call_count == 1
        assert trace.router_call_count == 1
        assert trace.execution_result_count == 1
        assert trace.reducer_call_count == 1
        assert trace.state_save_count == 1
    assert identity_trace.actual_processor == "image_identity"
    assert identity_trace.card_ids == (38,)
    assert similarity_trace.actual_processor == "recommendation"
    assert similarity_trace.card_ids == (91, 39)
    assert comparison_trace.actual_processor == "comparison"
    assert comparison_trace.card_ids == (38, 91)


def test_persisted_image_similarity_prepares_scenario_inputs_before_routing(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GUIDE_LLM_API_KEY", raising=False)
    monkeypatch.delenv("GUIDE_COPY_LLM_API_KEY", raising=False)
    cases = load_production_path_cases(DEFAULT_CASES_PATH)
    identity = next(
        case
        for case in cases
        if case.case_id == "bounded-image-context-t1"
    )
    similarity = next(
        case
        for case in cases
        if case.case_id == "bounded-image-context-t2"
    )
    comparison = next(
        case
        for case in cases
        if case.case_id == "bounded-image-context-t3"
    )
    runtime = Task11ProductionPathRuntime(
        repo_root=REPO_ROOT,
        state_root=tmp_path / "state",
    )

    identity_trace = runtime.execute(identity)
    similarity_trace = runtime.execute(similarity)
    comparison_trace = runtime.execute(comparison)

    validate_production_path_trace(identity_trace)
    validate_production_path_trace(similarity_trace)
    validate_production_path_trace(comparison_trace)
    assert similarity_trace.actual_processor == "recommendation"
    assert similarity_trace.card_ids == (91, 129)
    assert similarity_trace.loaded_version == 1
    assert similarity_trace.committed_version == 2
    assert comparison_trace.actual_processor == "comparison"
    assert comparison_trace.card_ids == (38, 91)
    assert comparison_trace.loaded_version == 2
    assert comparison_trace.committed_version == 3


def test_matrix_text_turn_can_carry_current_image_evidence(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GUIDE_LLM_API_KEY", raising=False)
    monkeypatch.delenv("GUIDE_COPY_LLM_API_KEY", raising=False)
    message = "图片里的B5精华和玉泽皮肤屏障修护精华乳哪个更适合？"
    case = ProductionPathCase(
        case_id="mixed-image-product-comparison-t1",
        trajectory_id="mixed-image-product-comparison",
        partition="state",
        message=message,
        image_paths=(
            "tests/fixtures/guide/images/"
            "product-38-index-control.png",
        ),
        meaning=TurnMeaning(
            operation_hint="comparison",
            topic_hint="serum",
            continuity_hint="new_task",
            subject_scope_hint="self",
            reference_mentions=(
                {
                    "raw_text": "图片里的",
                    "object_family_hint": "image",
                    "ordinal_hint": 1,
                    "plurality_hint": "single",
                },
            ),
            product_mentions=(
                {"raw_text": "玉泽皮肤屏障修护精华乳"},
            ),
            question_meaning=(
                "比较上传图片中的B5精华和"
                "玉泽皮肤屏障修护精华乳"
            ),
            safety_language="ordinary",
        ),
        expected_state_edge="none->comparison",
        expected_coverage=StateCoveragePoint(
            active_owner="none",
            reply_state="not_awaiting",
            preserved_authority="none",
            semantic_act="explicit_image_question",
            reference_source="image_ordinal",
        ),
        expected_processor="comparison",
        expected_intent="comparison",
        expected_card_ids=(38, 91),
    )
    runtime = Task11ProductionPathRuntime(
        repo_root=REPO_ROOT,
        state_root=tmp_path / "state",
    )

    trace = runtime.execute(case)

    validate_production_path_trace(trace)
    assert trace.actual_processor == "comparison"
    assert trace.card_ids == (38, 91)


def test_matrix_typed_multi_image_action_reaches_comparison(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GUIDE_LLM_API_KEY", raising=False)
    monkeypatch.delenv("GUIDE_COPY_LLM_API_KEY", raising=False)
    case = ProductionPathCase(
        case_id="coverage-multi-image-t1",
        trajectory_id="coverage-multi-image",
        partition="state",
        message="",
        image_action="compare",
        image_paths=(
            "tests/fixtures/guide/images/"
            "product-38-index-control.png",
            "app/static/images/products/"
            "jd_v3_10069603621835.png",
        ),
        meaning=turn_meaning_for_image_action(
            action="compare",
            image_count=2,
            question_summary="比较上传图片中的商品",
        ),
        expected_state_edge="none->comparison",
        expected_coverage=StateCoveragePoint(
            active_owner="none",
            reply_state="not_awaiting",
            preserved_authority="none",
            semantic_act="explicit_product_question",
            reference_source="current_batch",
        ),
        required_state_edges=(
            "semantic_act=explicit_product_question|"
            "reference_source=current_batch",
        ),
        expected_processor="image_comparison",
        expected_intent="image_compare",
        expected_card_ids=(38, 91),
    )
    runtime = Task11ProductionPathRuntime(
        repo_root=REPO_ROOT,
        state_root=tmp_path / "state",
    )

    trace = runtime.execute(case)

    validate_production_path_trace(trace)
    assert trace.actual_processor == "image_comparison"
    assert trace.card_ids == (38, 91)


def test_matrix_loads_next_turn_only_from_committed_snapshot(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GUIDE_LLM_API_KEY", raising=False)
    monkeypatch.delenv("GUIDE_COPY_LLM_API_KEY", raising=False)
    runtime = Task11ProductionPathRuntime(
        repo_root=REPO_ROOT,
        state_root=tmp_path / "state",
    )
    first = ProductionPathCase(
        case_id="state-recommendation-t1",
        trajectory_id="state-recommendation",
        partition="state",
        message="推荐500元内适合敏感肌的修护精华",
        meaning=TurnMeaning(
            operation_hint="recommendation",
            recommendation_mode="explore",
            recommendation_count=None,
            recommendation_mode_basis={
                "basis": "broad_exploration",
                "source_text": "推荐",
            },
            topic_hint="serum",
            continuity_hint="new_task",
            subject_scope_hint="self",
            budget_candidates=(
                {
                    "raw_text": "500元内",
                    "relation": "maximum",
                    "maximum": "500",
                },
            ),
            safety_language="ordinary",
        ),
        expected_state_edge="none->recommendation",
        expected_coverage=StateCoveragePoint(
            active_owner="none",
            reply_state="not_awaiting",
            preserved_authority="none",
            semantic_act="recommendation_request",
            reference_source="none",
        ),
        required_state_edges=(
            "active_owner=none|"
            "semantic_act=recommendation_request",
        ),
        expected_intent="recommend",
        expected_card_ids=(38, 91),
    )
    second = ProductionPathCase(
        case_id="state-recommendation-t2",
        trajectory_id="state-recommendation",
        partition="state",
        message="第二款怎么用",
        meaning=TurnMeaning(
            operation_hint="followup",
            topic_hint="serum",
            continuity_hint="continue",
            subject_scope_hint="self",
            reference_mentions=(
                {
                    "raw_text": "第二款",
                    "object_family_hint": "product",
                    "ordinal_hint": 2,
                    "plurality_hint": "single",
                },
            ),
            question_meaning="询问第二款的使用方法",
            safety_language="ordinary",
        ),
        expected_state_edge=(
            "recommendation->product_knowledge"
        ),
        expected_coverage=StateCoveragePoint(
            active_owner="recommendation",
            reply_state="not_awaiting",
            preserved_authority="candidate_batch",
            semantic_act="explicit_product_question",
            reference_source="candidate_ordinal",
        ),
        required_state_edges=(
            "active_owner=recommendation|"
            "reference_source=candidate_ordinal",
        ),
        expected_intent="followup",
        expected_card_ids=(91,),
    )

    first_trace = runtime.execute(first)
    second_trace = runtime.execute(second)

    validate_production_path_trace(first_trace)
    validate_production_path_trace(second_trace)
    assert (first_trace.loaded_version, first_trace.committed_version) == (
        0,
        1,
    )
    assert (
        second_trace.loaded_version,
        second_trace.committed_version,
    ) == (1, 2)
    assert second_trace.observed_state_edge == (
        "recommendation->product_knowledge"
    )
    assert second_trace.card_ids == (91,)
    assert set(first.required_state_edges).issubset(
        first_trace.coverage_edges
    )
    assert set(second.required_state_edges).issubset(
        second_trace.coverage_edges
    )


def test_matrix_rejects_committed_state_that_differs_from_reducer_output() -> None:
    reduced = ConversationSnapshot(
        session_id="committed-shape",
        version=2,
        active_owner=Responsibility.PRODUCT_KNOWLEDGE,
        active_focus=ActiveFocus(
            slot="product",
            object_id=51,
        ),
        product_slot=ProductSlotState(
            products=(
                DisplayedCandidateRef(
                    product_id=51,
                    ordinal=1,
                    skin_match="unknown",
                    matched_efficacies=(),
                ),
            ),
            focused_product_id=51,
        ),
    )
    committed = reduced.model_copy(
        update={"product_slot": None},
        deep=True,
    )

    with pytest.raises(
        ProductionPathInvariantError,
        match="committed snapshot differs from reducer output",
    ):
        production_matrix._validate_committed_snapshot(
            reduced=reduced,
            committed=committed,
        )


def test_state_partition_requires_declared_observable_coverage() -> None:
    with pytest.raises(
        ValueError,
        match="state partition requires expected coverage",
    ):
        ProductionPathCase(
            case_id="state-missing-coverage",
            trajectory_id="state-missing-coverage",
            partition="state",
            message="防晒为什么需要补涂",
            meaning=TurnMeaning(
                operation_hint="knowledge",
                topic_hint="sunscreen",
                continuity_hint="new_task",
                subject_scope_hint="self",
                question_meaning="防晒为什么需要补涂",
                safety_language="ordinary",
            ),
            expected_state_edge="none->general_knowledge",
            expected_processor="general_knowledge",
        )


def test_production_path_case_rejects_direct_initial_snapshot(
) -> None:
    session_id = "semantic-seeded-followup"
    starting_snapshot = ConversationSnapshot(
        session_id=session_id,
        version=1,
        active_owner=Responsibility.RECOMMENDATION,
        active_focus=ActiveFocus(slot="recommendation"),
        recommendation_slot=RecommendationSlotState(
            query_context=RecommendationQueryContext(
                category="serum",
                recommendation_mode="explore",
                recommendation_mode_basis="broad_exploration",
                recommendation_count=3,
            ),
            candidates=(
                DisplayedCandidateRef(
                    product_id=38,
                    ordinal=1,
                    skin_match="unknown",
                    matched_efficacies=("修护",),
                ),
                DisplayedCandidateRef(
                    product_id=91,
                    ordinal=2,
                    skin_match="unknown",
                    matched_efficacies=("修护",),
                ),
            ),
        ),
    )
    with pytest.raises(
        ValueError,
        match="direct state setup is forbidden",
    ):
        ProductionPathCase(
            case_id="semantic-seeded-followup-t1",
            trajectory_id=session_id,
            partition="semantic",
            message="第二款怎么用",
            meaning=TurnMeaning(
                operation_hint="followup",
                topic_hint="serum",
                continuity_hint="continue",
                subject_scope_hint="self",
                reference_mentions=(
                    {
                        "raw_text": "第二款",
                        "object_family_hint": "product",
                        "ordinal_hint": 2,
                        "plurality_hint": "single",
                    },
                ),
                question_meaning="询问第二款的使用方法",
                safety_language="ordinary",
            ),
            starting_snapshot=starting_snapshot,
            expected_state_edge=(
                "recommendation->product_knowledge"
            ),
            expected_intent="followup",
            expected_card_ids=(91,),
        )


def test_processor_observer_counts_each_actual_entry() -> None:
    observer = _ProductionPathObserver()
    recommendation = object()
    comparison = object()
    observer.bind(
        state=None,
        session_id="processor-entry-count",
        loaded_version=0,
        registered_processors={
            "recommendation": recommendation,
            "comparison": comparison,
        },
    )
    values = {
        "processor": "recommendation",
        "decision": object(),
        "implementation": type(recommendation).__qualname__,
        "instance": recommendation,
    }

    observer.processor_entered(**values)
    observer.processor_entered(**values)

    assert observer.processor_invocation_counts == {
        "recommendation": 2,
        "comparison": 0,
    }
    assert observer.processor_implementation_counts == {
        "object": 2,
    }
    assert observer.selected_processor_instance_entry_count == 2
    assert observer.unregistered_processor_invocation_count == 0


def test_processor_observer_rejects_non_registry_instance_entry() -> None:
    observer = _ProductionPathObserver()
    recommendation = object()
    observer.bind(
        state=None,
        session_id="processor-entry-identity",
        loaded_version=0,
        registered_processors={"recommendation": recommendation},
    )

    observer.processor_entered(
        processor="recommendation",
        decision=object(),
        implementation="TextRecommendationOrchestrator",
        instance=object(),
    )

    assert observer.processor_invocation_counts == {
        "recommendation": 0,
    }
    assert observer.selected_processor_instance_entry_count == 0
    assert observer.unregistered_processor_invocation_count == 1


def test_processor_entry_observation_occurs_inside_concrete_execute() -> None:
    dispatch_source = inspect.getsource(UnifiedGuideFlow._dispatch)
    assert '"processor_entered"' not in dispatch_source

    for processor in (
        TextRecommendationOrchestrator,
        ConsultationChatFlow,
        ImageRecommendationOrchestrator,
    ):
        assert "notify_processor_entry(" in inspect.getsource(
            processor.execute
        )


def test_matrix_runtime_does_not_seed_state_or_hard_code_zero_counts() -> None:
    source = inspect.getsource(Task11ProductionPathRuntime.execute)
    tree = ast.parse(textwrap.dedent(source))
    coverage_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_derive_state_coverage"
    ]

    assert ".conversation_state.save(" not in source
    assert len(coverage_calls) == 1
    coverage_arguments = {
        keyword.arg: ast.unparse(keyword.value)
        for keyword in coverage_calls[0].keywords
    }
    assert coverage_arguments == {
        "current": "before",
        "understanding": "self._observer.compiled_understanding",
        "decision": "self._observer.route_decision",
        "committed": "after",
        "current_image_action": "case.image_action",
    }
    assert "structured_understanding_injection_count=0" not in source
    assert "direct_router_bypass_count=0" not in source
    assert "legacy_entrypoint_count=0" not in source
    assert "provider_call_count=0" not in source
    assert "outbound_network_attempt_count=0" not in source


def test_matrix_summary_requires_exact_production_path_counts() -> None:
    semantic = tuple(
        _trace(
            turn_id=f"semantic-{index:03d}",
            trajectory_id=f"semantic-{index:03d}",
            partition="semantic",
        )
        for index in range(128)
    )
    stateful = tuple(
        _trace(
            turn_id=f"state-{index // 4:02d}-t{index % 4 + 1}",
            trajectory_id=f"state-{index // 4:02d}",
            partition="bounded" if index < 9 else "state",
            bounded=index < 9,
            expected_state_edge=f"edge-{index % 40:02d}",
            observed_state_edge=f"edge-{index % 40:02d}",
            coverage_edges=(f"edge-{index % 40:02d}",),
        )
        for index in range(48)
    )
    pre_decision_rejection = _trace(
        turn_id="predecision-stale-version-rejection-001",
        trajectory_id="state-11",
        partition="pre_decision_rejection",
        rejection_stage="pre_decision",
        translation_injection_count=0,
        compiler_call_count=0,
        router_call_count=0,
        execution_result_count=0,
        reducer_call_count=0,
        state_save_count=0,
        state_save_completed_count=0,
        route_decision_digest="0" * 64,
        selected_processor_decision_digest="0" * 64,
        result_decision_digest="0" * 64,
        sse_decision_digest="0" * 64,
        selected_processor="none",
        processor_invocation_counts={"recommendation": 0},
        processor_implementation_counts={},
        selected_processor_instance_entry_count=0,
        loaded_version=4,
        committed_version=4,
        expected_state_edge="recommendation->recommendation",
        observed_state_edge="recommendation->recommendation",
        terminal_event="error",
        accepted=False,
        coverage_edges=(),
        actual_processor="none",
        actual_intent="",
        card_ids=(),
        event_names=("start", "error"),
        observed_layers=("http", "sse"),
    )

    summary = summarize_production_path(
        (*semantic, *stateful, pre_decision_rejection),
        required_state_edges=tuple(
            f"edge-{index:02d}" for index in range(40)
        ),
        candidate_manifest_sha256="c" * 64,
        protected_payload_sha256="d" * 64,
        cases_sha256="e" * 64,
    )

    assert type(summary) is ProductionPathSummary
    assert summary.passed is True
    assert summary.candidate_manifest_sha256 == "c" * 64
    assert summary.protected_payload_sha256 == "d" * 64
    assert summary.cases_sha256 == "e" * 64
    assert summary.expected_contract_case_count == 128
    assert summary.actual_equivalence_case_count == 128
    assert summary.trajectory_count == 12
    assert summary.stateful_turn_count == 48
    assert summary.turn_count == 177
    assert summary.state_edge_count == 40
    assert summary.required_state_edge_count == 40
    assert summary.bounded_turn_count == 9
    assert summary.pre_decision_rejection_count == 1
    assert summary.pre_decision_rejection_failure_count == 0
    assert summary.translation_injection_count == 176
    assert summary.observed_layers == (
        "translation",
        "compiler",
        "router",
        "processor",
        "reducer",
        "sqlite",
        "sse",
    )


def test_matrix_rejects_missing_observed_runtime_layer() -> None:
    trace = _trace(
        observed_layers=(
            "translation",
            "compiler",
            "router",
            "processor",
            "reducer",
            "sse",
        )
    )

    with pytest.raises(
        ProductionPathInvariantError,
        match="observed runtime layers",
    ):
        validate_production_path_trace(trace)


def test_frozen_matrix_has_exact_partition_counts() -> None:
    cases = load_production_path_cases(DEFAULT_CASES_PATH)
    semantic = tuple(
        case for case in cases if case.partition == "semantic"
    )
    stateful = tuple(
        case
        for case in cases
        if case.partition in {"state", "bounded"}
    )
    pre_decision_rejections = tuple(
        case
        for case in cases
        if case.partition == "pre_decision_rejection"
    )

    assert len(cases) == 177
    assert len({case.case_id for case in cases}) == 177
    assert len(semantic) == 128
    assert len(stateful) == 48
    assert len(pre_decision_rejections) == 1
    assert pre_decision_rejections[0].conversation_version_delta == -1
    assert pre_decision_rejections[0].expected_terminal_event == "error"
    assert pre_decision_rejections[0].expected_rejection_stage == (
        "pre_decision"
    )
    assert len({case.trajectory_id for case in stateful}) == 12
    assert sum(case.bounded for case in cases) == 9
    assert all(case.expected_coverage is not None for case in stateful)
    required_edges = {
        edge
        for case in stateful
        for edge in case.required_state_edges
    }
    assert len(required_edges) == 40


def test_frozen_matrix_stores_only_current_snapshot_slots() -> None:
    legacy_keys = {
        "focus_state",
        "has_image_delivery",
        "query_context",
        "empty_result",
        "candidates",
        "focused_candidate_ordinal",
        "focused_evidence_ids",
        "focused_general_knowledge_ids",
        "last_general_knowledge_question",
        "consultation",
        "clarification",
        "pending_turn",
    }
    current_keys = set(ConversationSnapshot.model_fields)
    payloads = tuple(
        payload
        for line in DEFAULT_CASES_PATH.read_text(
            encoding="utf-8"
        ).splitlines()
        if (payload := json.loads(line))
    )

    assert len(payloads) == 177
    assert all("starting_snapshot" not in payload for payload in payloads)
    assert not legacy_keys.intersection(
        ProductionPathCase.model_fields
    )
    assert "starting_snapshot" not in ProductionPathCase.model_fields
    assert current_keys


def test_frozen_matrix_contains_exact_bounded_trajectories() -> None:
    cases = load_production_path_cases(DEFAULT_CASES_PATH)
    bounded = tuple(case for case in cases if case.bounded)

    assert [
        (case.trajectory_id, case.case_id, case.message)
        for case in bounded
    ] == [
        (
            "bounded-text-fit",
            "bounded-text-fit-t1",
            (
                "给我推荐一款最适合油敏肌、"
                "换季泛红的 900 到 1100 元精华"
            ),
        ),
        (
            "bounded-text-context",
            "bounded-text-context-t1",
            "给我推荐 900 到 1100 元的精华",
        ),
        (
            "bounded-text-context",
            "bounded-text-context-t2",
            "第二款的质地适合什么肤质？",
        ),
        (
            "bounded-text-context",
            "bounded-text-context-t3",
            "我现在有点换季泛红，T 区出油，我可能是什么肤质？",
        ),
        (
            "bounded-text-context",
            "bounded-text-context-t4",
            "确认",
        ),
        (
            "bounded-text-context",
            "bounded-text-context-t5",
            (
                "回到刚才的推荐，第一款和第二款"
                "哪个更适合我的肤质？"
            ),
        ),
        (
            "bounded-image-context",
            "bounded-image-context-t1",
            "",
        ),
        (
            "bounded-image-context",
            "bounded-image-context-t2",
            (
                "给我找两款相似的，我最近换季泛红，"
                "T 区出油。"
            ),
        ),
        (
            "bounded-image-context",
            "bounded-image-context-t3",
            (
                "图片里的 B5 和第一款哪个更适合我的肤质？"
            ),
        ),
    ]
    assert bounded[6].image_action == "identify"
    assert bounded[6].image_paths == (
        "tests/fixtures/guide/images/product-38-index-control.png",
    )


def test_bounded_profile_trajectory_confirms_and_reuses_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GUIDE_LLM_API_KEY", raising=False)
    monkeypatch.delenv("GUIDE_COPY_LLM_API_KEY", raising=False)
    cases = tuple(
        case
        for case in load_production_path_cases(DEFAULT_CASES_PATH)
        if case.trajectory_id == "bounded-text-context"
    )
    parsed_turns: list[tuple[tuple[str, dict], ...]] = []
    parse_sse = production_matrix._parse_sse

    def record_sse(payload: bytes) -> tuple[tuple[str, dict], ...]:
        events = parse_sse(payload)
        parsed_turns.append(events)
        return events

    monkeypatch.setattr(production_matrix, "_parse_sse", record_sse)
    runtime = Task11ProductionPathRuntime(
        repo_root=REPO_ROOT,
        state_root=tmp_path / "profile-state",
    )

    traces = []
    confirmed_snapshot = None
    for case in cases:
        traces.append(runtime.execute(case))
        if case.case_id == "bounded-text-context-t4":
            confirmed_snapshot = (
                runtime._vertical.conversation_state.load(
                    case.trajectory_id
                )
            )

    assert tuple(trace.actual_intent for trace in traces[2:4]) == (
        "consultation_provisional",
        "consultation_confirmation",
    )
    assert confirmed_snapshot is not None
    assert confirmed_snapshot.session_profile is not None
    assert any(
        item.value == "sensitivity"
        and item.confirmation == "confirmed"
        for item in confirmed_snapshot.session_profile.stable_tendencies
    )

    routed_task = runtime._observer.route_decision.task_plan
    assert any(
        isinstance(item, SkinConstraint)
        and item.value.value == "sensitive"
        for item in routed_task.constraints
    )
    presentation = next(
        data
        for name, data in parsed_turns[-1]
        if name == "presentation_contract"
    )
    assert "profile_match" not in {
        row["dimension_id"]
        for row in presentation["comparison_rows"]
    }


def test_bounded_trajectory_contract_rejects_message_drift() -> None:
    cases = list(load_production_path_cases(DEFAULT_CASES_PATH))
    index = next(
        index
        for index, case in enumerate(cases)
        if case.case_id == "bounded-image-context-t2"
    )
    cases[index] = cases[index].model_copy(
        update={"message": "给我找三款相似的。"}
    )

    with pytest.raises(
        ProductionPathInvariantError,
        match="bounded trajectory contract",
    ):
        _validate_bounded_trajectory_contract(cases)


def test_frozen_state_matrix_covers_each_declared_dimension_value() -> None:
    cases = load_production_path_cases(DEFAULT_CASES_PATH)
    points = tuple(
        case.expected_coverage
        for case in cases
        if case.partition in {"state", "bounded"}
    )

    assert {point.active_owner for point in points} == {
        "none",
        "recommendation",
        "product_knowledge",
        "consultation",
        "general_knowledge",
        "image_identity",
        "clarification",
        "safety_escalation",
        "comparison",
    }
    assert {point.reply_state for point in points} == {
        "not_awaiting",
        "collecting_consultation",
        "confirmable_consultation",
        "pending_clarification",
    }
    assert {point.preserved_authority for point in points} == {
        "none",
        "product",
        "candidate_batch",
        "one_confirmed_image",
        "multiple_confirmed_images",
        "product_plus_active_consultation",
    }
    assert {point.semantic_act for point in points} == {
        "recommendation_request",
        "observation_answer",
        "ambiguous_continuation",
        "explicit_product_question",
        "explicit_image_question",
        "explicit_general_knowledge_question",
        "recommendation_revision",
        "explicit_return",
        "safety_escalation",
    }
    assert {point.reference_source for point in points} == {
        "none",
        "explicit_current_item",
        "candidate_ordinal",
        "image_ordinal",
        "current_batch",
        "ambiguous_reference",
    }


def test_frozen_matrix_runs_full_http_production_path(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GUIDE_LLM_API_KEY", raising=False)
    monkeypatch.delenv("GUIDE_COPY_LLM_API_KEY", raising=False)

    summary = run_production_path_matrix(
        repo_root=REPO_ROOT,
        cases_path=DEFAULT_CASES_PATH,
        state_root=tmp_path / "state",
        candidate_manifest_sha256="c" * 64,
        protected_payload_sha256="d" * 64,
        cases_sha256="e" * 64,
    )

    assert summary.passed is True
    assert summary.turn_count == 177
    assert summary.actual_equivalence_case_count == 128
    assert summary.actual_equivalence_failure_count == 0
    assert summary.stateful_turn_count == 48
    assert summary.trajectory_count == 12
    assert summary.state_edge_count == 40
    assert summary.required_state_edge_count == 40
    assert summary.bounded_turn_count == 9
    assert summary.bounded_failure_count == 0
    assert summary.pre_decision_rejection_count == 1
    assert summary.pre_decision_rejection_failure_count == 0
    assert summary.translation_injection_count == 176
    assert summary.outbound_network_attempt_count == 0
    assert summary.provider_call_count == 0
    assert len(summary.turn_traces) == 177


def test_production_matrix_requires_reviewed_manifest_sha256(
    tmp_path: Path,
) -> None:
    root, manifest, cases = _candidate_manifest_for_verifier(tmp_path)

    with pytest.raises(
        ProductionPathInvariantError,
        match="reviewed SHA-256",
    ):
        production_matrix._verify_candidate_manifest(
            repo_root=root,
            manifest_path=manifest,
            cases_path=cases,
            expected_manifest_sha256="0" * 64,
        )


def test_production_matrix_accepts_canonical_reviewed_manifest(
    tmp_path: Path,
) -> None:
    root, manifest, cases = _candidate_manifest_for_verifier(tmp_path)
    expected_manifest_sha256 = sha256(manifest.read_bytes()).hexdigest()

    manifest_sha256, payload_sha256, cases_sha256 = (
        production_matrix._verify_candidate_manifest(
            repo_root=root,
            manifest_path=manifest,
            cases_path=cases,
            expected_manifest_sha256=expected_manifest_sha256,
        )
    )

    assert manifest_sha256 == expected_manifest_sha256
    assert payload_sha256 == canonical_payload_sha256(
        root,
        json.loads(manifest.read_text(encoding="utf-8"))[
            "protected_paths"
        ],
    )
    assert cases_sha256 == sha256(cases.read_bytes()).hexdigest()


def test_production_matrix_rejects_sibling_candidate_manifest(
    tmp_path: Path,
) -> None:
    root, manifest, cases = _candidate_manifest_for_verifier(tmp_path)
    sibling = manifest.with_name("attacker-manifest.json")
    sibling.write_bytes(manifest.read_bytes())

    with pytest.raises(
        ProductionPathInvariantError,
        match="canonical path",
    ):
        production_matrix._verify_candidate_manifest(
            repo_root=root,
            manifest_path=sibling,
            cases_path=cases,
            expected_manifest_sha256=(
                production_matrix.sha256(sibling.read_bytes()).hexdigest()
            ),
        )


def test_production_matrix_rejects_symlinked_epoch_directory(
    tmp_path: Path,
) -> None:
    root, manifest, cases = _candidate_manifest_for_verifier(tmp_path)
    epoch = manifest.parent
    real_epoch = epoch.with_name("repair-epoch-54-real")
    epoch.rename(real_epoch)
    epoch.symlink_to(real_epoch, target_is_directory=True)
    aliased_manifest = epoch / manifest.name

    with pytest.raises(
        ProductionPathInvariantError,
        match="symlink",
    ):
        production_matrix._verify_candidate_manifest(
            repo_root=root,
            manifest_path=aliased_manifest,
            cases_path=cases,
            expected_manifest_sha256=(
                production_matrix.sha256(
                    aliased_manifest.read_bytes()
                ).hexdigest()
            ),
        )


def test_production_matrix_hashes_the_same_bytes_it_parses(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root, manifest, cases = _candidate_manifest_for_verifier(tmp_path)
    reviewed_bytes = manifest.read_bytes()
    attacker = json.loads(reviewed_bytes)
    attacker["attacker_controlled"] = True
    manifest.write_text(
        json.dumps(attacker, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    original_read_bytes = Path.read_bytes

    def stale_hash_bytes(path: Path) -> bytes:
        if path == manifest:
            return reviewed_bytes
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", stale_hash_bytes)

    with pytest.raises(
        ProductionPathInvariantError,
        match="reviewed SHA-256",
    ):
        production_matrix._verify_candidate_manifest(
            repo_root=root,
            manifest_path=manifest,
            cases_path=cases,
            expected_manifest_sha256=sha256(
                reviewed_bytes
            ).hexdigest(),
        )


def test_production_matrix_cli_requires_reviewed_manifest_sha256(
    tmp_path: Path,
) -> None:
    root, manifest, cases = _candidate_manifest_for_verifier(tmp_path)
    output = tmp_path / "production-summary.json"

    with pytest.raises(SystemExit):
        production_matrix.main([
            "--repo-root",
            str(root),
            "--manifest",
            str(manifest),
            "--cases",
            str(cases),
            "--output",
            str(output),
        ])

    with pytest.raises(
        ProductionPathInvariantError,
        match="reviewed SHA-256",
    ):
        production_matrix.main([
            "--repo-root",
            str(root),
            "--manifest",
            str(manifest),
            "--expected-manifest-sha256",
            "0" * 64,
            "--cases",
            str(cases),
            "--output",
            str(output),
        ])

    assert not output.exists()
