from __future__ import annotations

from pathlib import Path
import ast
import inspect

import app.guide.presentation.sse_events as sse_events
from app.guide.application.contracts import TurnIdentity, UserTurn
from app.guide.application.dynamic_consultation import (
    PreparedConsultationEvidence,
)
from app.guide.application.execution_contracts import (
    ExecutionResult,
    OpaqueRetrievalQuery,
    PreRoutingEvidence,
    PresentationTerminal,
    ProcessorExecutionInput,
)
from app.guide.application.text_recommendation_flow import (
    TextRecommendationOrchestrator,
)
from app.guide.feedback.contracts import (
    ConversationSnapshot,
    DisplayedCandidateRef,
    KnowledgeSlotState,
    ProductSlotState,
    RecommendationQueryContext,
    RecommendationSlotState,
)
from app.guide.feedback.focus_state import ActiveFocus
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.feedback.profile_policy import (
    ResolvedProfileContext,
)
from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.intent.task_planning import plan_task
from app.guide.intent.unified_turn_router import UnifiedRouteDecision
from app.guide.presentation.sse_events import EndData, EndEvent
from app.guide.retrieval.product_evidence_retrieval import (
    EvidenceQuery,
    ProductEvidenceRetriever,
)
from app.guide.retrieval.product_name_resolver import (
    ProductMentionResolution,
)
from app.guide.retrieval.general_knowledge_retrieval import (
    GeneralKnowledgeRetriever,
)
from app.guide.understanding.contracts import (
    CategoryDraft,
    ProductMentionDraft,
    ReferenceDraft,
    SourceSpan,
    StructuredUnderstanding,
    TopicCode,
    UnderstandingGoal,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning
from app.guide_runtime.composition import (
    build_category_fact_reader,
    build_general_knowledge_assets,
    build_product_evidence_reader,
    compose_text_recommendation_orchestrator,
)




















def _product_goal_understanding(
    message: str,
    *,
    goal: UnderstandingGoal,
    topic: TopicCode,
    names: tuple[str, ...],
    question_meaning: str | None = None,
    safety_sensitive: bool = False,
) -> StructuredUnderstanding:
    mentions = []
    for name in names:
        start = message.index(name)
        mentions.append(
            ProductMentionDraft(
                text=name,
                source_span=SourceSpan(
                    start=start,
                    end=start + len(name),
                ),
            )
        )
    return StructuredUnderstanding(
        goal=goal,
        topic=topic,
        observations=[],
        exact_constraints=[CategoryDraft(value=topic)],
        semantic_proposals=[],
        signal_trace=[],
        product_mentions=mentions,
        image_references=[],
        uncertainties=[],
        confidence=0.95,
        question_meaning=question_meaning,
        safety_sensitive=safety_sensitive,
    )




def _flow_general_knowledge_retriever() -> GeneralKnowledgeRetriever:
    return GeneralKnowledgeRetriever(
        build_general_knowledge_assets().blocks
    )














def test_processor_returns_execution_result_with_same_decision(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    message = "SPF和PA分别是什么意思"
    understanding = StructuredUnderstanding(
        goal=UnderstandingGoal.KNOWLEDGE,
        topic=TopicCode.SUNSCREEN,
        observations=[],
        exact_constraints=[
            CategoryDraft(value=TopicCode.SUNSCREEN),
        ],
        semantic_proposals=[],
        signal_trace=[],
        image_references=[],
        uncertainties=[],
        confidence=0.95,
        question_meaning="询问SPF和PA防晒指标的含义",
    )
    meaning = TurnMeaning.model_validate(
        {
            "operation_hint": "knowledge",
            "topic_hint": "sunscreen",
            "continuity_hint": "new_task",
            "subject_scope_hint": "self",
            "pending_response_hint": "unknown",
            "reference_mentions": [],
            "product_mentions": [],
            "budget_candidates": [],
            "observation_candidates": [],
            "preference_candidates": [],
            "relative_candidates": [],
            "consultation_hypothesis": None,
            "next_observation_gap": None,
            "question_meaning": "询问SPF和PA防晒指标的含义",
            "safety_language": "ordinary",
        },
        strict=True,
    )
    decision = UnifiedRouteDecision(
        processor="general_knowledge",
        responsibility=Responsibility.GENERAL_KNOWLEDGE,
        presentation_mode="general_knowledge",
        continuity="replace_task",
        focus_source="none",
    )
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        general_knowledge=_flow_general_knowledge_retriever(),
    )

    turn = _turn(message)
    product_resolution = ProductMentionResolution(bindings=())
    result = orchestrator.execute(
        ProcessorExecutionInput(
            turn_identity=turn.identity,
            understanding=understanding,
            decision=decision,
            current_snapshot=None,
            routing_evidence=PreRoutingEvidence(
                query=OpaqueRetrievalQuery(value=message),
                conversation_version=0,
                profile_context=ResolvedProfileContext(values=()),
                product_resolution=product_resolution,
                task_plan=plan_task(
                    understanding,
                    responsibility=decision.responsibility,
                    message=message,
                ),
                consultation=PreparedConsultationEvidence(),
            ),
        ),
    )

    assert type(result) is ExecutionResult
    assert result.decision is decision
    assert isinstance(result.terminal, PresentationTerminal)
    assert result.terminal.data.mode == "general_knowledge"
    assert result.state_delta.knowledge.action == "replace"
    assert result.state_delta.knowledge.value.question == message
    assert result.state_delta.clarification.action == "clear"
    assert all(
        event.event
        not in {
            "start",
            "presentation_contract",
            "clarify",
            "error",
            "end",
        }
        for event in result.audit_events
    )
    assert conversation_state.load("s-1") is None


def test_text_processor_has_no_legacy_stream_or_state_owner() -> None:
    source = inspect.getsource(TextRecommendationOrchestrator)

    assert not hasattr(TextRecommendationOrchestrator, "orchestrate")
    assert not hasattr(TextRecommendationOrchestrator, "stream")
    assert not hasattr(
        TextRecommendationOrchestrator,
        "stream_pending_reply",
    )
    assert not hasattr(
        TextRecommendationOrchestrator,
        "stream_text_vertical",
    )
    assert not hasattr(
        TextRecommendationOrchestrator,
        "stream_understanding",
    )
    assert not hasattr(
        TextRecommendationOrchestrator,
        "stream_understanding_body",
    )
    assert "_conversation_state" not in source
    assert "_session_locks" not in source
    assert "_bind_route_decision_if_absent" not in source
















def test_current_item_reference_uses_product_slot() -> None:
    candidates = (
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
    )
    snapshot = ConversationSnapshot(
        session_id="focus-current-item",
        version=1,
        active_owner=Responsibility.PRODUCT_KNOWLEDGE,
        active_focus=ActiveFocus(
            slot="product",
            object_id=91,
        ),
        recommendation_slot=RecommendationSlotState(
            query_context=RecommendationQueryContext(
                category="serum",
                recommendation_mode_basis="broad_exploration",
            ),
            candidates=candidates,
        ),
        product_slot=ProductSlotState(
            products=candidates,
            focused_product_id=91,
        ),
    )

    resolution = TextRecommendationOrchestrator._resolve_reference_products(
        (
            ReferenceDraft(
                kind="current_item",
                source_span=SourceSpan(start=0, end=4),
            ),
        ),
        snapshot=snapshot,
    )

    assert resolution.issue is None
    assert [item.product_id for item in resolution.bindings] == [91]


def test_current_item_reference_uses_standalone_product_lane() -> None:
    snapshot = ConversationSnapshot(
        session_id="standalone-current-item",
        version=1,
        active_owner=Responsibility.PRODUCT_KNOWLEDGE,
        active_focus=ActiveFocus(
            slot="product",
            object_id=78,
        ),
        product_slot=ProductSlotState(
            products=(
                DisplayedCandidateRef(
                    product_id=78,
                    ordinal=1,
                    skin_match="unknown",
                    matched_efficacies=(),
                ),
            ),
            focused_product_id=78,
        ),
    )

    resolution = TextRecommendationOrchestrator._resolve_reference_products(
        (ReferenceDraft(kind="current_item"),),
        snapshot=snapshot,
    )

    assert resolution.issue is None
    assert [item.product_id for item in resolution.bindings] == [78]
    assert resolution.bindings[0].source_text == "current_item:1"


def test_failed_product_surface_falls_back_to_typed_current_reference(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    message = "回到玉泽那支，继续查它的资料"
    candidates = (
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
    )
    understanding = _product_goal_understanding(
        message,
        goal=UnderstandingGoal.FOLLOWUP,
        topic=TopicCode.SERUM,
        names=("玉泽那支",),
        question_meaning="继续查询当前商品资料",
    ).model_copy(
        update={
            "references": [
                ReferenceDraft(
                    kind="current_item",
                    source_span=SourceSpan(start=2, end=6),
                )
            ]
        },
        deep=True,
    )
    snapshot = ConversationSnapshot(
        session_id="fallback-current-item",
        version=2,
        active_owner=Responsibility.GENERAL_KNOWLEDGE,
        active_focus=ActiveFocus(slot="knowledge"),
        recommendation_slot=RecommendationSlotState(
            query_context=RecommendationQueryContext(
                category="serum",
                recommendation_mode_basis="broad_exploration",
            ),
            candidates=candidates,
            focused_candidate_ordinal=2,
        ),
        product_slot=ProductSlotState(
            products=candidates,
            focused_product_id=91,
        ),
        knowledge_slot=KnowledgeSlotState(
            question="此前知识问题",
        ),
    )
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
    )

    resolution = orchestrator.resolve_product_resolution(
        message=message,
        understanding=understanding,
        snapshot=snapshot,
    )

    assert resolution.issue is None
    assert [item.product_id for item in resolution.bindings] == [91]
    assert resolution.bindings[0].source_text == "current_item:2"


def test_duplicate_reference_forms_to_same_product_are_deduplicated() -> None:
    candidates = (
        DisplayedCandidateRef(
            product_id=56,
            ordinal=1,
            skin_match="not_applicable",
            matched_efficacies=(),
        ),
        DisplayedCandidateRef(
            product_id=51,
            ordinal=2,
            skin_match="not_applicable",
            matched_efficacies=(),
        ),
    )
    snapshot = ConversationSnapshot(
        session_id="same-product-references",
        version=1,
        active_owner=Responsibility.GENERAL_KNOWLEDGE,
        active_focus=ActiveFocus(slot="knowledge"),
        recommendation_slot=RecommendationSlotState(
            query_context=RecommendationQueryContext(
                category="sunscreen",
                recommendation_mode_basis="broad_exploration",
            ),
            candidates=candidates,
            focused_candidate_ordinal=2,
        ),
        product_slot=ProductSlotState(
            products=candidates,
            focused_product_id=51,
        ),
        knowledge_slot=KnowledgeSlotState(
            question="此前知识问题",
        ),
    )

    resolution = TextRecommendationOrchestrator._resolve_reference_products(
        (
            ReferenceDraft(kind="current_item"),
            ReferenceDraft(kind="candidate_ordinal", ordinal=2),
        ),
        snapshot=snapshot,
    )

    assert resolution.issue is None
    assert [item.product_id for item in resolution.bindings] == [51]


def test_specific_ordinal_inside_batch_overrides_batch_resolution() -> None:
    snapshot = ConversationSnapshot(
        session_id="specific-reference-over-batch",
        version=1,
        active_owner=Responsibility.RECOMMENDATION,
        active_focus=ActiveFocus(slot="recommendation"),
        recommendation_slot=RecommendationSlotState(
            query_context=RecommendationQueryContext(
                category="sunscreen",
                recommendation_mode_basis="broad_exploration",
            ),
            candidates=(
                DisplayedCandidateRef(
                    product_id=56,
                    ordinal=1,
                    skin_match="not_applicable",
                    matched_efficacies=(),
                ),
                DisplayedCandidateRef(
                    product_id=51,
                    ordinal=2,
                    skin_match="not_applicable",
                    matched_efficacies=(),
                ),
            ),
        ),
    )

    resolution = TextRecommendationOrchestrator._resolve_reference_products(
        (
            ReferenceDraft(kind="current_batch"),
            ReferenceDraft(kind="candidate_ordinal", ordinal=2),
        ),
        snapshot=snapshot,
    )

    assert resolution.issue is None
    assert [item.product_id for item in resolution.bindings] == [51]
    assert resolution.bindings[0].source_text == "candidate_ordinal:2"


def test_reference_forms_to_different_products_remain_distinct() -> None:
    candidates = (
        DisplayedCandidateRef(
            product_id=56,
            ordinal=1,
            skin_match="not_applicable",
            matched_efficacies=(),
        ),
        DisplayedCandidateRef(
            product_id=51,
            ordinal=2,
            skin_match="not_applicable",
            matched_efficacies=(),
        ),
    )
    snapshot = ConversationSnapshot(
        session_id="different-product-references",
        version=1,
        active_owner=Responsibility.PRODUCT_KNOWLEDGE,
        active_focus=ActiveFocus(
            slot="product",
            object_id=56,
        ),
        recommendation_slot=RecommendationSlotState(
            query_context=RecommendationQueryContext(
                category="sunscreen",
                recommendation_mode_basis="broad_exploration",
            ),
            candidates=candidates,
            focused_candidate_ordinal=1,
        ),
        product_slot=ProductSlotState(
            products=candidates,
            focused_product_id=56,
        ),
    )

    resolution = TextRecommendationOrchestrator._resolve_reference_products(
        (
            ReferenceDraft(kind="current_item"),
            ReferenceDraft(kind="candidate_ordinal", ordinal=2),
        ),
        snapshot=snapshot,
    )

    assert resolution.issue is None
    assert [
        item.product_id for item in resolution.bindings
    ] == [56, 51]












































def test_application_layer_does_not_import_siliconflow_adapter() -> None:
    source = (
        Path(__file__).resolve().parents[3]
        / "app"
        / "guide"
        / "application"
        / "text_recommendation_flow.py"
    ).read_text(encoding="utf-8")
    assert "siliconflow" not in source.casefold()
    assert "httpx" not in source.casefold()


def test_application_does_not_mutate_task_plan_with_profile_values() -> None:
    source_path = (
        Path(__file__).resolve().parents[3]
        / "app"
        / "guide"
        / "application"
        / "text_recommendation_flow.py"
    )
    tree = ast.parse(
        source_path.read_text(encoding="utf-8"),
        filename=str(source_path),
    )

    assert not any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_fill_profile_skin"
        for node in ast.walk(tree)
    )




def _turn(
    message: str,
    *,
    conversation_version: int = 0,
    profile_owner: ProfileOwnerRef | None = None,
) -> UserTurn:
    values = {
        "identity": TurnIdentity(
            session_id="s-1",
            request_id=f"request_test_s-1_{conversation_version:04d}",
            turn_id=f"turn_test_s-1_{conversation_version:04d}",
        ),
        "session_id": "s-1",
        "message": message,
        "image_bundle_id": None,
        "conversation_version": conversation_version,
    }
    if profile_owner is not None:
        values["profile_owner"] = profile_owner
    return UserTurn(**values)








def test_end_event_requires_conversation_version() -> None:
    event = EndEvent(data=EndData(conversation_version=2))
    assert event.data.conversation_version == 2


def test_decision_process_accepts_strict_selection_slot_payload() -> None:
    assert hasattr(sse_events, "SelectionSlotData")

    slot = sse_events.SelectionSlotData(
        product_id=55,
        field_key="suitable_skin",
        requested_value="敏感肌",
        matched_value="敏感肌",
        match_status="matched",
        rank_strength=1,
        source_refs=["evidence-a"],
        attribution="merchant_claim",
    )
    data = sse_events.DecisionProcessData(
        ordered_product_ids=[55],
        winner_status="SELECTED",
        evidence_refs=["facet=suitable_skin:敏感肌"],
        selection_slots=[slot],
    )

    assert data.selection_slots == [slot]










def test_merchant_projection_keeps_all_reviewed_ordinary_dimensions(
    real_reader,
) -> None:
    from app.guide.application.text_recommendation_flow import (
        _project_merchant_claims,
    )

    root = Path(__file__).resolve().parents[3]
    category_facts = build_category_fact_reader(
        real_reader,
        repo_root=root,
    )

    projected = _project_merchant_claims(
        category_facts.claims,
        product_ids=(52,),
        constraints=[],
    )
    ordinary = [
        item for item in projected if item.claim_scope == "ordinary"
    ]

    assert len(ordinary) == 5
    assert all(item.normalized_value for item in ordinary)
    assert {
        item.field_key for item in ordinary
    } >= {
        "texture",
        "film_speed",
        "tone_effect",
        "finish",
    }


def test_complete_consumer_self_report_becomes_one_numeric_proof(
    real_reader,
) -> None:
    from app.guide.application.text_recommendation_flow import (
        _presentation_proof_points,
    )

    root = Path(__file__).resolve().parents[3]
    retriever = ProductEvidenceRetriever(
        build_product_evidence_reader(root)
    )
    packet = retriever.retrieve(
        EvidenceQuery(
            product_ids=(58,),
            raw_question="轻薄不厚重、清爽不油腻的消费者测试",
            question_meaning="询问轻薄清爽的消费者认同",
            safety_sensitive=False,
        )
    )
    event = sse_events.ProductEvidenceEvent(
        data=sse_events.ProductEvidenceData(packet=packet)
    )

    proof_points = _presentation_proof_points(event)

    assert len(proof_points) == 1
    assert proof_points[0].product_id == 58
    assert proof_points[0].kind == "numeric"
    assert proof_points[0].label == "用户测试"
    assert proof_points[0].display_value.startswith("商家引用：")
    assert "62名" in proof_points[0].display_value
    assert "连续2周" in proof_points[0].display_value
    assert "消费者认同" in proof_points[0].display_value
    assert "100%" in proof_points[0].display_value
    assert (
        "第三方检测中年轻受试者"
        in proof_points[0].display_value
    )
    assert (
        "62名18-25岁受试者连续测试2周后"
        not in proof_points[0].display_value
    )
