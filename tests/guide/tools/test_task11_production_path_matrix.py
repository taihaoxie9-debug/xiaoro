from __future__ import annotations

import json

import pytest

from app.guide.feedback.contracts import (
    ConversationSnapshot,
    DisplayedCandidateRef,
    ImageSlotState,
    RecommendationQueryContext,
    RecommendationSlotState,
)
from app.guide.feedback.focus_state import (
    ActiveFocus,
    ConfirmedImageProductRef,
)
from app.guide.intent.responsibility_matrix import Responsibility
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
    _derive_state_coverage,
    _parse_sse,
    run_production_path_matrix,
    summarize_production_path,
    validate_bounded_turns,
    load_production_path_cases,
    validate_production_path_trace,
    validate_state_edge_coverage,
)


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
        "result_decision_digest": "a" * 64,
        "decision_identity_violation_count": 0,
        "execution_result_count": 1,
        "reducer_call_count": 1,
        "state_save_count": 1,
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
    }
    values.update(updates)
    return ProductionPathTurnTrace(**values)


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


def test_state_coverage_classifies_image_batch_as_current_batch() -> None:
    point = _derive_state_coverage(
        current=None,
        meaning=TurnMeaning(
            operation_hint="comparison",
            topic_hint="sunscreen",
            continuity_hint="continue",
            subject_scope_hint="self",
            reference_mentions=(
                {
                    "raw_text": "这两张图",
                    "object_family_hint": "image",
                    "ordinal_hint": None,
                    "plurality_hint": "batch",
                    "batch_size_hint": 2,
                },
            ),
            question_meaning="比较当前两张图片中的商品",
            safety_language="ordinary",
        ),
        processor="comparison",
    )

    assert point.reference_source == "current_batch"
    assert point.semantic_act == "explicit_product_question"


def test_state_coverage_classifies_sole_unnumbered_image_reference() -> None:
    point = _derive_state_coverage(
        current=ConversationSnapshot(
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
                        product_id=38,
                    ),
                ),
                focused_image_ordinal=1,
            ),
        ),
        meaning=TurnMeaning(
            operation_hint="comparison",
            topic_hint="serum",
            continuity_hint="continue",
            subject_scope_hint="self",
            reference_mentions=(
                {
                    "raw_text": "图片里的",
                    "object_family_hint": "image",
                    "ordinal_hint": None,
                    "plurality_hint": "single",
                },
                {
                    "raw_text": "第一款",
                    "object_family_hint": "product",
                    "ordinal_hint": 1,
                    "plurality_hint": "single",
                },
            ),
            question_meaning="比较图片原品和第一款",
            safety_language="ordinary",
        ),
        processor="comparison",
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


def test_semantic_partition_accepts_one_reviewed_initial_snapshot(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GUIDE_LLM_API_KEY", raising=False)
    monkeypatch.delenv("GUIDE_COPY_LLM_API_KEY", raising=False)
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
    case = ProductionPathCase(
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
    runtime = Task11ProductionPathRuntime(
        repo_root=REPO_ROOT,
        state_root=tmp_path / "state",
    )

    trace = runtime.execute(case)

    validate_production_path_trace(trace)
    assert (trace.loaded_version, trace.committed_version) == (1, 2)


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

    summary = summarize_production_path(
        (*semantic, *stateful),
        required_state_edges=tuple(
            f"edge-{index:02d}" for index in range(40)
        ),
    )

    assert type(summary) is ProductionPathSummary
    assert summary.passed is True
    assert summary.expected_contract_case_count == 128
    assert summary.actual_equivalence_case_count == 128
    assert summary.trajectory_count == 12
    assert summary.stateful_turn_count == 48
    assert summary.turn_count == 176
    assert summary.state_edge_count == 40
    assert summary.required_state_edge_count == 40
    assert summary.bounded_turn_count == 9
    assert summary.translation_injection_count == 176


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

    assert len(cases) == 176
    assert len({case.case_id for case in cases}) == 176
    assert len(semantic) == 128
    assert len(stateful) == 48
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
    snapshots = tuple(
        payload["starting_snapshot"]
        for line in DEFAULT_CASES_PATH.read_text(
            encoding="utf-8"
        ).splitlines()
        if (
            payload := json.loads(line)
        )["starting_snapshot"] is not None
    )

    assert snapshots
    assert all(set(snapshot) == current_keys for snapshot in snapshots)
    assert all(
        not legacy_keys.intersection(snapshot)
        for snapshot in snapshots
    )
    for snapshot in snapshots:
        product_slot = snapshot["product_slot"]
        if product_slot is None:
            continue
        assert [
            product["ordinal"]
            for product in product_slot["products"]
        ] == list(range(1, len(product_slot["products"]) + 1))


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
                "给我推荐一款 900 到 1100 元的精华，"
                "我是油敏肌，换季容易泛红"
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
                "以图片里的理肤泉新B5多效修护精华为参照，"
                "给我找两款相似的，我最近换季泛红，T 区出油。"
            ),
        ),
        (
            "bounded-image-context",
            "bounded-image-context-t3",
            (
                "理肤泉新B5多效修护精华和第一款"
                "玉泽皮肤屏障修护精华乳哪个更适合我的肤质？"
            ),
        ),
    ]
    assert bounded[6].image_action == "identify"
    assert bounded[6].image_paths == (
        "tests/fixtures/guide/images/product-38-index-control.png",
    )


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
    )

    assert summary.passed is True
    assert summary.turn_count == 176
    assert summary.actual_equivalence_case_count == 128
    assert summary.actual_equivalence_failure_count == 0
    assert summary.stateful_turn_count == 48
    assert summary.trajectory_count == 12
    assert summary.state_edge_count == 40
    assert summary.required_state_edge_count == 40
    assert summary.bounded_turn_count == 9
    assert summary.bounded_failure_count == 0
    assert summary.translation_injection_count == 176
    assert summary.outbound_network_attempt_count == 0
    assert summary.provider_call_count == 0
    assert len(summary.turn_traces) == 176
