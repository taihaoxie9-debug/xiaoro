from __future__ import annotations

from decimal import Decimal
import inspect

import pytest
from pydantic import ValidationError

import app.guide.intent.unified_turn_router as unified_turn_router
from app.guide.feedback.contracts import (
    ClarificationProgress,
    ConsultationSlotState,
    ConversationSnapshot,
    DisplayedCandidateRef,
    ImageSlotState,
    KnowledgeSlotState,
    PendingBudgetRange,
    PendingClarificationSlot,
    PendingRecommendationContext,
    PendingReplySlot,
    PendingTurn,
    ProductSlotState,
    RecommendationQueryContext,
    RecommendationSlotState,
)
from app.guide.feedback.consultation_state import ConsultationSubstate
from app.guide.feedback.focus_state import (
    ActiveFocus,
    ConfirmedImageProductRef,
)
from app.guide.intent.contracts import (
    CategoryConstraint,
    SkinConstraint,
    TaskPlan,
)
from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.intent.task_planning import plan_task
from app.guide.intent.unified_turn_router import (
    UnifiedRouteDecision,
    route_unified_turn as _route_unified_turn,
)
from app.guide.presentation.contracts import CardDisplayContract
from app.guide.retrieval.product_name_resolver import (
    ResolvedProductBinding,
)
from app.guide.understanding.contracts import (
    ProductMentionDraft,
    ReferenceDraft,
    SkinTarget,
    SourceSpan,
    StructuredUnderstanding,
    TopicCode,
    UnderstandingGoal,
    UnderstandingIssue,
)
from app.guide.understanding.semantic_contracts import ClarificationCode
from app.guide.understanding.safety_admission import (
    admit_safety_signal,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning


def _meaning(
    operation: str,
    *,
    continuity: str = "unknown",
    observations: tuple[dict[str, object], ...] = (),
) -> TurnMeaning:
    recommendation = operation in {
        "recommendation",
        "image_similarity",
    }
    return TurnMeaning.model_validate(
        {
            "operation_hint": operation,
            "recommendation_mode": (
                "explore" if recommendation else None
            ),
            "recommendation_count": 3 if recommendation else None,
            "recommendation_mode_basis": (
                {
                    "basis": (
                        "similar_alternatives"
                        if operation == "image_similarity"
                        else "broad_exploration"
                    ),
                    "source_text": "当前问题",
                }
                if recommendation
                else None
            ),
            "topic_hint": "sunscreen",
            "continuity_hint": continuity,
            "subject_scope_hint": "self",
            "reference_mentions": [],
            "product_mentions": [],
            "budget_candidates": [],
            "observation_candidates": observations,
            "preference_candidates": [],
            "relative_candidates": [],
            "consultation_hypothesis": None,
            "next_observation_gap": None,
            "question_meaning": "当前问题",
            "safety_language": "ordinary",
        },
        strict=True,
    )


def _understanding(
    goal: UnderstandingGoal,
    *,
    references: tuple[ReferenceDraft, ...] = (),
    topic: TopicCode | None = TopicCode.SUNSCREEN,
) -> StructuredUnderstanding:
    recommendation = goal in {
        UnderstandingGoal.RECOMMENDATION,
        UnderstandingGoal.IMAGE_SIMILARITY,
    }
    return StructuredUnderstanding(
        goal=goal,
        recommendation_mode=(
            "explore" if recommendation else None
        ),
        recommendation_count=3 if recommendation else None,
        recommendation_mode_basis=(
            "similar_alternatives"
            if goal is UnderstandingGoal.IMAGE_SIMILARITY
            else (
                "broad_exploration"
                if recommendation
                else None
            )
        ),
        topic=topic,
        observations=[],
        exact_constraints=[],
        preference_drafts=[],
        relative_drafts=[],
        semantic_proposals=[],
        signal_trace=[],
        references=list(references),
        product_mentions=[],
        image_references=[],
        uncertainties=[],
        confidence=1.0,
        question_meaning="当前问题",
    )


def _reference(
    kind: str,
    ordinal: int | None = None,
) -> ReferenceDraft:
    return ReferenceDraft(
        kind=kind,
        ordinal=ordinal,
        source_span=SourceSpan(start=0, end=2),
    )


def _binding(product_id: int) -> ResolvedProductBinding:
    return ResolvedProductBinding(
        product_id=product_id,
        variant_scope=None,
        source_text=f"商品{product_id}",
        source_kind="explicit_product",
    )


def route_unified_turn(**kwargs) -> UnifiedRouteDecision:
    if "task_plan" not in kwargs:
        selected = unified_turn_router._select_unified_route(
            meaning=kwargs["meaning"],
            understanding=kwargs["understanding"],
            snapshot=kwargs["snapshot"],
            product_bindings=kwargs.get("product_bindings", ()),
            current_image_products=kwargs.get(
                "current_image_products",
                (),
            ),
            product_resolution_issue=kwargs.get(
                "product_resolution_issue"
            ),
            pending_reply_kind=kwargs.get("pending_reply_kind"),
            transition_operations=kwargs.get(
                "transition_operations",
                (),
            ),
            safety_signal=kwargs.get("safety_signal"),
        )
        kwargs["task_plan"] = plan_task(
            kwargs["understanding"],
            responsibility=selected.responsibility,
            resolved_product_ids=tuple(
                dict.fromkeys(
                    binding.product_id
                    for binding in selected.product_bindings
                )
            ),
            product_resolution_issue=kwargs.get(
                "product_resolution_issue"
            ),
        )
    return _route_unified_turn(**kwargs)


def _snapshot(
    *,
    processor: str = "recommendation",
    product_ids: tuple[int, ...] = (51, 55, 101),
    current_product_id: int | None = None,
    pending_turn: PendingTurn | None = None,
    confirmed_images: tuple[ConfirmedImageProductRef, ...] = (),
) -> ConversationSnapshot:
    candidates = tuple(
        DisplayedCandidateRef(
            product_id=product_id,
            ordinal=index,
            skin_match="unknown",
            matched_efficacies=(),
        )
        for index, product_id in enumerate(product_ids, start=1)
    )
    focused_candidate_ordinal = (
        product_ids.index(current_product_id) + 1
        if current_product_id in product_ids
        else None
    )
    product_slot = (
        ProductSlotState(
            products=candidates,
            focused_product_id=current_product_id,
        )
        if (
            processor in {"comparison", "product_knowledge"}
            or (
                current_product_id is not None
                and processor != "image_identity"
            )
        )
        else None
    )
    image_focus_ordinal = next(
        (
            item.image_ordinal
            for item in confirmed_images
            if item.product_id == current_product_id
        ),
        None,
    )
    image_slot = (
        ImageSlotState(
            confirmed_products=confirmed_images,
            focused_image_ordinal=image_focus_ordinal,
        )
        if confirmed_images
        else None
    )
    owner = {
        "recommendation": Responsibility.RECOMMENDATION,
        "comparison": Responsibility.COMPARISON,
        "product_knowledge": Responsibility.PRODUCT_KNOWLEDGE,
        "general_knowledge": Responsibility.GENERAL_KNOWLEDGE,
        "consultation": Responsibility.CONSULTATION,
        "image_identity": Responsibility.IMAGE_IDENTITY,
        "clarification": Responsibility.CLARIFICATION,
        "safety_escalation": Responsibility.SAFETY_ESCALATION,
    }[processor]
    active_focus = {
        "recommendation": ActiveFocus(
            slot="recommendation",
            ordinal=focused_candidate_ordinal,
        ),
        "comparison": ActiveFocus(
            slot="product",
            object_id=current_product_id,
        ),
        "product_knowledge": ActiveFocus(
            slot="product",
            object_id=current_product_id,
        ),
        "general_knowledge": ActiveFocus(slot="knowledge"),
        "consultation": ActiveFocus(slot="consultation"),
        "image_identity": ActiveFocus(
            slot="image",
            object_id=current_product_id,
            ordinal=image_focus_ordinal,
        ),
        "clarification": ActiveFocus(slot="reply"),
        "safety_escalation": ActiveFocus(slot="consultation"),
    }[processor]
    return ConversationSnapshot(
        session_id="router-session",
        version=2,
        active_owner=owner,
        active_focus=active_focus,
        recommendation_slot=RecommendationSlotState(
            query_context=RecommendationQueryContext(
                category="sunscreen",
                recommendation_mode_basis="broad_exploration",
                budget_minimum=None,
                budget_maximum=Decimal("500"),
                skin=None,
                efficacy=None,
                exclusions=(),
            ),
            candidates=candidates,
            focused_candidate_ordinal=focused_candidate_ordinal,
        ),
        product_slot=product_slot,
        image_slot=image_slot,
        consultation_slot=(
            ConsultationSlotState(
                state=ConsultationSubstate(
                    started_at_conversation_version=1,
                ),
            )
            if processor in {"consultation", "safety_escalation"}
            else None
        ),
        knowledge_slot=(
            KnowledgeSlotState(question="视黄醇是什么")
            if processor == "general_knowledge"
            else None
        ),
        reply_slot=(
            PendingReplySlot(value=pending_turn)
            if pending_turn is not None
            else None
        ),
    )


def _snapshot_with_dormant_product_and_active_image(
    *,
    dormant_product_id: int,
    active_image: ConfirmedImageProductRef,
) -> ConversationSnapshot:
    dormant = DisplayedCandidateRef(
        product_id=dormant_product_id,
        ordinal=1,
        skin_match="unknown",
        matched_efficacies=(),
    )
    return ConversationSnapshot(
        session_id="router-session",
        version=2,
        active_owner=Responsibility.IMAGE_IDENTITY,
        active_focus=ActiveFocus(
            slot="image",
            object_id=active_image.product_id,
            ordinal=active_image.image_ordinal,
        ),
        recommendation_slot=RecommendationSlotState(
            query_context=RecommendationQueryContext(
                category="sunscreen",
                recommendation_mode_basis="broad_exploration",
            ),
            candidates=(dormant,),
            focused_candidate_ordinal=1,
        ),
        product_slot=ProductSlotState(
            products=(dormant,),
            focused_product_id=dormant_product_id,
        ),
        image_slot=ImageSlotState(
            confirmed_products=(active_image,),
            focused_image_ordinal=active_image.image_ordinal,
        ),
    )


def test_recommendation_ordinal_routes_to_product_knowledge() -> None:
    decision = route_unified_turn(
        meaning=_meaning("knowledge", continuity="continue"),
        understanding=_understanding(
            UnderstandingGoal.KNOWLEDGE,
            references=(_reference("candidate_ordinal", 2),),
        ),
        snapshot=_snapshot(),
    )

    assert decision.processor == "product_knowledge"
    assert decision.continuity == "continue"
    assert decision.focus_source == "candidate_batch"
    assert [item.product_id for item in decision.product_bindings] == [55]


@pytest.mark.parametrize(
    ("message", "operation", "references"),
    [
        (
            "回到刚才的推荐，第一款和第二款哪个更适合我？",
            "suitability",
            (
                _reference("candidate_ordinal", 1),
                _reference("candidate_ordinal", 2),
            ),
        ),
        (
            "前面那两款按我的情况怎么选？",
            "recommendation",
            (_reference("current_batch"),),
        ),
        (
            "这两款里更适合我的是哪支？",
            "suitability",
            (_reference("current_batch"),),
        ),
    ],
)
def test_current_batch_suitability_maps_to_comparison(
    message: str,
    operation: str,
    references: tuple[ReferenceDraft, ...],
) -> None:
    decision = route_unified_turn(
        meaning=_meaning(
            operation,
            continuity="return_to_focus",
        ).model_copy(
            update={"question_meaning": message},
            deep=True,
        ),
        understanding=_understanding(
            UnderstandingGoal.COMPARISON,
            references=references,
        ).model_copy(
            update={"question_meaning": message},
            deep=True,
        ),
        snapshot=_snapshot(product_ids=(51, 55)),
    )

    assert decision.responsibility is Responsibility.COMPARISON
    assert decision.processor == "comparison"
    assert [item.product_id for item in decision.product_bindings] == [
        51,
        55,
    ]
    assert decision.task_plan is not None
    assert decision.task_plan.mode == "comparison"
    assert decision.task_plan.product_ids == [51, 55]


def test_unbound_general_knowledge_replaces_non_knowledge_focus() -> None:
    decision = route_unified_turn(
        meaning=_meaning("knowledge", continuity="continue"),
        understanding=_understanding(UnderstandingGoal.KNOWLEDGE),
        snapshot=_snapshot(processor="product_knowledge"),
    )

    assert decision.processor == "general_knowledge"
    assert decision.continuity == "replace_task"
    assert decision.focus_source == "knowledge_topic"


def test_unbound_general_knowledge_can_continue_knowledge_focus() -> None:
    decision = route_unified_turn(
        meaning=_meaning("knowledge", continuity="continue"),
        understanding=_understanding(UnderstandingGoal.KNOWLEDGE),
        snapshot=_snapshot(processor="general_knowledge"),
    )

    assert decision.processor == "general_knowledge"
    assert decision.continuity == "continue"
    assert decision.focus_source == "knowledge_topic"


def test_compiled_budget_clarification_overrides_recommendation_hint(
) -> None:
    understanding = _understanding(
        UnderstandingGoal.RECOMMENDATION,
        topic=TopicCode.SERUM,
    ).model_copy(
        update={
            "uncertainties": [
                UnderstandingIssue(
                    code="invalid_budget",
                    detail="请给一个明确数字或范围。",
                ),
            ],
        },
        deep=True,
    )

    decision = route_unified_turn(
        meaning=_meaning("recommendation", continuity="new_task"),
        understanding=understanding,
        snapshot=None,
    )

    assert decision.processor == "clarification"
    assert decision.continuity == "replace_task"
    assert decision.clarification_code is ClarificationCode.BUDGET


def test_return_to_focus_current_item_overrides_redundant_alias_issue(
) -> None:
    understanding = _understanding(
        UnderstandingGoal.FOLLOWUP,
        references=(_reference("current_item"),),
    ).model_copy(
        update={
            "product_mentions": [
                ProductMentionDraft(
                    text="B5那瓶",
                    source_span=SourceSpan(start=2, end=6),
                )
            ],
        },
        deep=True,
    )

    decision = route_unified_turn(
        meaning=_meaning("followup", continuity="return_to_focus"),
        understanding=understanding,
        snapshot=_snapshot(
            processor="general_knowledge",
            product_ids=(38,),
            current_product_id=38,
        ),
        product_resolution_issue="missing_reference",
    )

    assert decision.processor == "product_knowledge"
    assert decision.continuity == "return_to_focus"
    assert decision.focus_source == "current_product"
    assert [item.product_id for item in decision.product_bindings] == [38]


def test_continuing_current_item_overrides_scanned_alias_issue() -> None:
    understanding = _understanding(
        UnderstandingGoal.FOLLOWUP,
        references=(_reference("current_item"),),
    ).model_copy(
        update={
            "product_mentions": [
                ProductMentionDraft(
                    text="B5那瓶",
                    source_span=SourceSpan(start=2, end=6),
                )
            ],
        },
        deep=True,
    )

    decision = route_unified_turn(
        meaning=_meaning("followup", continuity="continue"),
        understanding=understanding,
        snapshot=_snapshot(
            processor="product_knowledge",
            product_ids=(38,),
            current_product_id=38,
        ),
        product_resolution_issue="missing_reference",
    )

    assert decision.processor == "product_knowledge"
    assert decision.continuity == "continue"
    assert decision.focus_source == "current_product"
    assert [item.product_id for item in decision.product_bindings] == [38]


def test_return_to_focus_current_item_overrides_scanned_ambiguous_alias() -> None:
    decision = route_unified_turn(
        meaning=_meaning("followup", continuity="return_to_focus"),
        understanding=_understanding(
            UnderstandingGoal.FOLLOWUP,
            references=(_reference("current_item"),),
        ),
        snapshot=_snapshot(
            processor="general_knowledge",
            product_ids=(38,),
            current_product_id=38,
        ),
        product_resolution_issue="ambiguous_reference",
    )

    assert decision.processor == "product_knowledge"
    assert decision.continuity == "return_to_focus"
    assert decision.focus_source == "current_product"
    assert [item.product_id for item in decision.product_bindings] == [38]


def test_named_product_comparison_replaces_noncomparison_focus() -> None:
    understanding = _understanding(
        UnderstandingGoal.COMPARISON,
    ).model_copy(
        update={
            "product_mentions": [
                ProductMentionDraft(
                    text="B5精华",
                    source_span=SourceSpan(start=2, end=6),
                ),
                ProductMentionDraft(
                    text="CE精华",
                    source_span=SourceSpan(start=7, end=11),
                ),
            ],
        },
        deep=True,
    )

    decision = route_unified_turn(
        meaning=_meaning("comparison", continuity="continue"),
        understanding=understanding,
        snapshot=_snapshot(processor="product_knowledge"),
        product_bindings=(_binding(38), _binding(34)),
    )

    assert decision.processor == "comparison"
    assert decision.continuity == "replace_task"
    assert decision.focus_source == "explicit_product"


def test_current_item_and_one_named_product_start_comparison() -> None:
    understanding = _understanding(
        UnderstandingGoal.COMPARISON,
    ).model_copy(
        update={
            "product_mentions": [
                ProductMentionDraft(
                    text="新商品",
                    source_span=SourceSpan(start=2, end=5),
                ),
            ],
        },
        deep=True,
    )

    decision = route_unified_turn(
        meaning=_meaning("comparison", continuity="continue"),
        understanding=understanding,
        snapshot=_snapshot(
            processor="product_knowledge",
            product_ids=(38,),
            current_product_id=38,
        ),
        product_bindings=(_binding(91),),
    )

    assert decision.processor == "comparison"
    assert decision.continuity == "replace_task"
    assert decision.focus_source == "explicit_product"
    assert [
        item.product_id for item in decision.product_bindings
    ] == [38, 91]


def test_current_batch_comparison_can_continue_noncomparison_focus() -> None:
    decision = route_unified_turn(
        meaning=_meaning("comparison", continuity="continue"),
        understanding=_understanding(
            UnderstandingGoal.COMPARISON,
            references=(_reference("current_batch"),),
        ),
        snapshot=_snapshot(
            processor="recommendation",
            product_ids=(38, 91),
        ),
    )

    assert decision.processor == "comparison"
    assert decision.continuity == "continue"
    assert decision.focus_source == "candidate_batch"


def test_batch_suitability_return_from_consultation_routes_to_comparison(
) -> None:
    decision = route_unified_turn(
        meaning=_meaning(
            "suitability",
            continuity="return_to_focus",
        ),
        understanding=_understanding(
            UnderstandingGoal.SUITABILITY,
            references=(_reference("current_batch"),),
            topic=TopicCode.SERUM,
        ),
        snapshot=_snapshot(
            processor="consultation",
            product_ids=(38, 91),
        ),
    )

    assert decision.processor == "comparison"
    assert decision.continuity == "return_to_focus"
    assert decision.focus_source == "candidate_batch"
    assert [item.product_id for item in decision.product_bindings] == [
        38,
        91,
    ]


def test_two_candidate_ordinals_suitability_uses_matrix_comparison(
) -> None:
    decision = route_unified_turn(
        meaning=_meaning("suitability", continuity="continue"),
        understanding=_understanding(
            UnderstandingGoal.SUITABILITY,
            references=(
                _reference("candidate_ordinal", 1),
                _reference("candidate_ordinal", 2),
            ),
            topic=TopicCode.SERUM,
        ),
        snapshot=_snapshot(product_ids=(38, 91, 34)),
    )

    assert decision.responsibility is Responsibility.COMPARISON
    assert decision.processor == "comparison"
    assert decision.presentation_mode == "comparison"
    assert [item.product_id for item in decision.product_bindings] == [
        38,
        91,
    ]


def test_one_candidate_suitability_uses_single_product_responsibility(
) -> None:
    decision = route_unified_turn(
        meaning=_meaning("suitability", continuity="continue"),
        understanding=_understanding(
            UnderstandingGoal.SUITABILITY,
            references=(_reference("candidate_ordinal", 1),),
            topic=TopicCode.SERUM,
        ),
        snapshot=_snapshot(product_ids=(38, 91)),
    )

    assert (
        decision.responsibility
        is Responsibility.SINGLE_PRODUCT_SUITABILITY
    )
    assert decision.processor == "product_knowledge"
    assert decision.presentation_mode == "single_product"


def test_two_image_ordinals_suitability_uses_matrix_comparison() -> None:
    images = (
        ConfirmedImageProductRef(image_ordinal=1, product_id=53),
        ConfirmedImageProductRef(image_ordinal=2, product_id=55),
    )
    decision = route_unified_turn(
        meaning=_meaning("suitability", continuity="continue"),
        understanding=_understanding(
            UnderstandingGoal.SUITABILITY,
            references=(
                _reference("image_ordinal", 1),
                _reference("image_ordinal", 2),
            ),
        ),
        snapshot=_snapshot(confirmed_images=images),
    )

    assert decision.responsibility is Responsibility.COMPARISON
    assert decision.processor == "comparison"
    assert [item.product_id for item in decision.product_bindings] == [
        53,
        55,
    ]


def test_two_candidate_knowledge_uses_comparison_responsibility() -> None:
    decision = route_unified_turn(
        meaning=_meaning("knowledge", continuity="continue"),
        understanding=_understanding(
            UnderstandingGoal.KNOWLEDGE,
            references=(
                _reference("candidate_ordinal", 1),
                _reference("candidate_ordinal", 2),
            ),
            topic=TopicCode.SERUM,
        ),
        snapshot=_snapshot(product_ids=(38, 91)),
    )

    assert decision.responsibility is Responsibility.COMPARISON
    assert decision.processor == "comparison"


def test_new_recommendation_drops_released_current_batch() -> None:
    decision = route_unified_turn(
        meaning=_meaning("recommendation", continuity="new_task"),
        understanding=_understanding(
            UnderstandingGoal.RECOMMENDATION,
            references=(_reference("current_batch"),),
            topic=TopicCode.SERUM,
        ),
        snapshot=_snapshot(
            processor="comparison",
            product_ids=(34, 38),
        ),
    )

    assert decision.processor == "recommendation"
    assert decision.continuity == "replace_task"
    assert decision.focus_source == "none"
    assert decision.product_bindings == ()


def test_new_recommendation_keeps_only_new_explicit_product() -> None:
    understanding = _understanding(
        UnderstandingGoal.RECOMMENDATION,
        references=(_reference("current_batch"),),
        topic=TopicCode.SERUM,
    ).model_copy(
        update={
            "product_mentions": [
                ProductMentionDraft(
                    text="新商品",
                    source_span=SourceSpan(start=3, end=6),
                ),
            ],
        },
        deep=True,
    )

    decision = route_unified_turn(
        meaning=_meaning("recommendation", continuity="new_task"),
        understanding=understanding,
        snapshot=_snapshot(
            processor="comparison",
            product_ids=(34, 38),
        ),
        product_bindings=(_binding(91),),
    )

    assert decision.processor == "recommendation"
    assert decision.continuity == "replace_task"
    assert decision.focus_source == "explicit_product"
    assert [
        binding.product_id for binding in decision.product_bindings
    ] == [91]


def test_general_knowledge_to_retained_product_restores_focus() -> None:
    decision = route_unified_turn(
        meaning=_meaning("followup", continuity="continue"),
        understanding=_understanding(
            UnderstandingGoal.FOLLOWUP,
            references=(_reference("current_item"),),
        ),
        snapshot=_snapshot(
            processor="general_knowledge",
            product_ids=(56, 51),
            current_product_id=51,
        ),
    )

    assert decision.processor == "product_knowledge"
    assert decision.continuity == "return_to_focus"
    assert decision.focus_source == "current_product"
    assert [item.product_id for item in decision.product_bindings] == [51]


def test_product_knowledge_to_retained_product_remains_continue() -> None:
    decision = route_unified_turn(
        meaning=_meaning("followup", continuity="continue"),
        understanding=_understanding(
            UnderstandingGoal.FOLLOWUP,
            references=(_reference("current_item"),),
        ),
        snapshot=_snapshot(
            processor="product_knowledge",
            product_ids=(56, 51),
            current_product_id=51,
        ),
    )

    assert decision.processor == "product_knowledge"
    assert decision.continuity == "continue"
    assert decision.focus_source == "current_product"


def test_explicit_product_resolves_reference_clarification_as_supplement(
) -> None:
    snapshot = ConversationSnapshot(
        session_id="router-session",
        version=1,
        active_owner=Responsibility.CLARIFICATION,
        active_focus=ActiveFocus(slot="reply"),
        reply_slot=PendingClarificationSlot(
            value=ClarificationProgress(
                gap=ClarificationCode.REFERENCE,
                attempts=1,
            ),
        ),
    )
    understanding = _understanding(
        UnderstandingGoal.KNOWLEDGE,
        topic=TopicCode.SERUM,
    ).model_copy(
        update={
            "product_mentions": [
                ProductMentionDraft(
                    text="理肤泉新B5多效修护精华",
                    source_span=SourceSpan(start=2, end=14),
                )
            ],
        },
        deep=True,
    )

    decision = route_unified_turn(
        meaning=_meaning("clarification", continuity="continue"),
        understanding=understanding,
        snapshot=snapshot,
        product_bindings=(_binding(38),),
    )

    assert decision.processor == "product_knowledge"
    assert decision.continuity == "supplement"
    assert decision.focus_source == "explicit_product"


def test_explicit_product_without_reference_clarification_stays_continue(
) -> None:
    understanding = _understanding(
        UnderstandingGoal.KNOWLEDGE,
        topic=TopicCode.SERUM,
    ).model_copy(
        update={
            "product_mentions": [
                ProductMentionDraft(
                    text="理肤泉新B5多效修护精华",
                    source_span=SourceSpan(start=2, end=14),
                )
            ],
        },
        deep=True,
    )

    decision = route_unified_turn(
        meaning=_meaning("knowledge", continuity="continue"),
        understanding=understanding,
        snapshot=_snapshot(processor="product_knowledge"),
        product_bindings=(_binding(38),),
    )

    assert decision.processor == "product_knowledge"
    assert decision.continuity == "continue"


def test_image_identity_operation_routes_without_phrase_matching() -> None:
    image = ConfirmedImageProductRef(
        image_ordinal=1,
        product_id=53,
        variant_scope=None,
    )
    decision = route_unified_turn(
        meaning=_meaning(
            "image_identity",
            continuity="new_task",
        ),
        understanding=_understanding(
            UnderstandingGoal.IMAGE_IDENTITY,
        ),
        snapshot=None,
        current_image_products=(image,),
    )

    assert decision.processor == "image_identity"
    assert decision.focus_source == "confirmed_image"
    assert [item.product_id for item in decision.product_bindings] == [53]


def test_current_image_authority_merges_distinct_explicit_product() -> None:
    image = ConfirmedImageProductRef(
        image_ordinal=1,
        product_id=53,
        variant_scope=None,
    )
    understanding = _understanding(
        UnderstandingGoal.COMPARISON,
        references=(_reference("image_ordinal", 1),),
    ).model_copy(
        update={
            "product_mentions": [
                ProductMentionDraft(
                    text="B5精华",
                    source_span=SourceSpan(start=6, end=10),
                )
            ]
        },
        deep=True,
    )

    decision = route_unified_turn(
        meaning=_meaning("comparison", continuity="new_task"),
        understanding=understanding,
        snapshot=None,
        product_bindings=(_binding(38),),
        current_image_products=(image,),
    )

    assert decision.processor == "comparison"
    assert decision.focus_source == "confirmed_image"
    assert [item.product_id for item in decision.product_bindings] == [53, 38]


def test_current_image_authority_deduplicates_matching_explicit_product(
) -> None:
    image = ConfirmedImageProductRef(
        image_ordinal=1,
        product_id=53,
        variant_scope=None,
    )
    understanding = _understanding(
        UnderstandingGoal.IMAGE_IDENTITY,
        references=(_reference("image_ordinal", 1),),
    ).model_copy(
        update={
            "product_mentions": [
                ProductMentionDraft(
                    text="清透防晒乳",
                    source_span=SourceSpan(start=5, end=11),
                )
            ]
        },
        deep=True,
    )

    decision = route_unified_turn(
        meaning=_meaning("image_identity", continuity="new_task"),
        understanding=understanding,
        snapshot=None,
        product_bindings=(_binding(53),),
        current_image_products=(image,),
    )

    assert decision.processor == "image_identity"
    assert decision.focus_source == "confirmed_image"
    assert len(decision.product_bindings) == 1
    assert decision.product_bindings[0].source_text == "image_ordinal:1"


def test_two_images_do_not_override_explicit_identity_operation() -> None:
    decision = route_unified_turn(
        meaning=_meaning(
            "image_identity",
            continuity="new_task",
        ),
        understanding=_understanding(
            UnderstandingGoal.IMAGE_IDENTITY,
        ),
        snapshot=None,
        current_image_products=(
            ConfirmedImageProductRef(
                image_ordinal=1,
                product_id=53,
            ),
            ConfirmedImageProductRef(
                image_ordinal=2,
                product_id=55,
            ),
        ),
    )

    assert decision.processor == "image_identity"
    assert decision.continuity == "replace_task"
    assert decision.focus_source == "confirmed_image"
    assert [
        item.product_id for item in decision.product_bindings
    ] == [53, 55]


@pytest.mark.parametrize(
    ("active_processor", "operation", "expected"),
    (
        ("product_knowledge", "suitability", "product_knowledge"),
        ("recommendation", "assessment", "consultation"),
        ("general_knowledge", "recommendation", "recommendation"),
        ("consultation", "recommendation", "recommendation"),
    ),
)
def test_cross_mode_processor_selection(
    active_processor: str,
    operation: str,
    expected: str,
) -> None:
    snapshot = _snapshot(
        processor=active_processor,
        current_product_id=(
            55 if active_processor == "product_knowledge" else None
        ),
    )
    references = (
        (_reference("current_item"),)
        if active_processor == "product_knowledge"
        else ()
    )
    goal = {
        "suitability": UnderstandingGoal.SUITABILITY,
        "assessment": UnderstandingGoal.ASSESSMENT,
        "recommendation": UnderstandingGoal.RECOMMENDATION,
    }[operation]

    decision = route_unified_turn(
        meaning=_meaning(
            operation,
            continuity="new_task",
        ),
        understanding=_understanding(goal, references=references),
        snapshot=snapshot,
    )

    assert decision.processor == expected
    assert decision.continuity == "replace_task"


def test_recommendation_interrupts_consultation_despite_continue_hint(
) -> None:
    decision = route_unified_turn(
        meaning=_meaning(
            "recommendation",
            continuity="continue",
        ),
        understanding=_understanding(
            UnderstandingGoal.RECOMMENDATION,
            topic=TopicCode.SKINCARE,
        ),
        snapshot=_snapshot(processor="consultation"),
        transition_operations=("add",),
    )

    assert decision.processor == "recommendation"
    assert decision.continuity == "replace_task"
    assert decision.focus_source == "none"


def test_return_to_earlier_product_preserves_product_focus() -> None:
    decision = route_unified_turn(
        meaning=_meaning("knowledge", continuity="return_to_focus"),
        understanding=_understanding(UnderstandingGoal.KNOWLEDGE),
        snapshot=_snapshot(
            processor="general_knowledge",
            current_product_id=55,
        ),
    )

    assert decision.processor == "product_knowledge"
    assert decision.continuity == "return_to_focus"
    assert decision.focus_source == "current_product"
    assert [item.product_id for item in decision.product_bindings] == [55]


def test_assessment_return_to_focus_restores_consultation_not_product() -> None:
    decision = route_unified_turn(
        meaning=_meaning(
            "assessment",
            continuity="return_to_focus",
            observations=(
                {
                    "observation_id": "obs_comedones",
                    "code": "oiliness",
                    "present": True,
                    "qualifier": "recurrent",
                    "raw_text": "闷痘",
                    "location": "unknown",
                    "trigger": "unknown",
                    "duration": "recurrent",
                    "severity": "unknown",
                },
            ),
        ),
        understanding=_understanding(
            UnderstandingGoal.ASSESSMENT,
            topic=None,
        ),
        snapshot=_snapshot(
            processor="product_knowledge",
            current_product_id=55,
        ),
    )

    assert decision.processor == "consultation"
    assert decision.product_bindings == ()


def test_assessment_image_reference_routes_consultation_without_product() -> None:
    meaning_payload = _meaning(
        "assessment",
        continuity="continue",
    ).model_dump(mode="python")
    meaning_payload["reference_mentions"] = [
        {
            "raw_text": "第一张图",
            "object_family_hint": "image",
            "ordinal_hint": 1,
            "plurality_hint": "single",
            "batch_size_hint": None,
        }
    ]
    meaning = TurnMeaning.model_validate(meaning_payload, strict=True)

    decision = route_unified_turn(
        meaning=meaning,
        understanding=_understanding(
            UnderstandingGoal.ASSESSMENT,
            references=(_reference("image_ordinal", 1),),
            topic=TopicCode.SKINCARE,
        ),
        snapshot=None,
        current_image_products=(
            ConfirmedImageProductRef(
                image_ordinal=1,
                product_id=38,
            ),
        ),
    )

    assert decision.processor == "consultation"
    assert decision.responsibility is Responsibility.CONSULTATION
    assert decision.product_bindings == ()
    assert decision.focus_source == "consultation"


def test_active_consultation_claims_ambiguous_continuation() -> None:
    decision = route_unified_turn(
        meaning=_meaning("clarification", continuity="continue"),
        understanding=_understanding(
            UnderstandingGoal.CLARIFICATION,
            topic=None,
        ),
        snapshot=_snapshot(processor="consultation"),
    )

    assert decision.processor == "consultation"
    assert decision.continuity == "continue"


@pytest.mark.parametrize(
    ("operation", "expected_processor"),
    (
        ("suitability", "product_knowledge"),
        ("image_similarity", "recommendation"),
    ),
)
def test_confirmed_image_routes_to_selected_processor(
    operation: str,
    expected_processor: str,
) -> None:
    image = ConfirmedImageProductRef(
        image_ordinal=1,
        product_id=53,
    )
    decision = route_unified_turn(
        meaning=_meaning(operation, continuity="continue"),
        understanding=_understanding(
            {
                "suitability": UnderstandingGoal.SUITABILITY,
                "image_similarity": UnderstandingGoal.IMAGE_SIMILARITY,
            }[operation],
            references=(_reference("image_ordinal", 1),),
        ),
        snapshot=_snapshot(confirmed_images=(image,)),
    )

    assert decision.processor == expected_processor
    assert decision.focus_source == "confirmed_image"
    assert [item.product_id for item in decision.product_bindings] == [53]


def test_current_item_preserves_unique_confirmed_image_provenance() -> None:
    image = ConfirmedImageProductRef(
        image_ordinal=1,
        product_id=53,
    )
    decision = route_unified_turn(
        meaning=_meaning("suitability", continuity="continue"),
        understanding=_understanding(
            UnderstandingGoal.SUITABILITY,
            references=(_reference("current_item"),),
        ),
        snapshot=_snapshot(
            processor="product_knowledge",
            product_ids=(53,),
            current_product_id=53,
            confirmed_images=(image,),
        ),
    )

    assert decision.processor == "product_knowledge"
    assert decision.focus_source == "confirmed_image"
    assert [item.product_id for item in decision.product_bindings] == [53]


def test_current_item_uses_active_image_before_dormant_product_slot() -> None:
    image = ConfirmedImageProductRef(
        image_ordinal=1,
        product_id=53,
        variant_scope="50ml",
    )
    snapshot = _snapshot_with_dormant_product_and_active_image(
        dormant_product_id=91,
        active_image=image,
    )

    decision = route_unified_turn(
        meaning=_meaning("suitability", continuity="continue"),
        understanding=_understanding(
            UnderstandingGoal.SUITABILITY,
            references=(_reference("current_item"),),
        ),
        snapshot=snapshot,
    )

    assert decision.focus_source == "confirmed_image"
    assert [
        (binding.product_id, binding.variant_scope)
        for binding in decision.product_bindings
    ] == [(53, "50ml")]


def test_comparison_ordinal_uses_current_product_batch_before_dormant_recommendation(
) -> None:
    image = ConfirmedImageProductRef(
        image_ordinal=1,
        product_id=53,
    )
    old_candidate = DisplayedCandidateRef(
        product_id=91,
        ordinal=1,
        skin_match="unknown",
        matched_efficacies=(),
    )
    current_products = (
        DisplayedCandidateRef(
            product_id=53,
            ordinal=1,
            skin_match="unknown",
            matched_efficacies=(),
        ),
        DisplayedCandidateRef(
            product_id=55,
            ordinal=2,
            skin_match="unknown",
            matched_efficacies=(),
        ),
    )
    snapshot = ConversationSnapshot(
        session_id="router-session",
        version=3,
        active_owner=Responsibility.COMPARISON,
        active_focus=ActiveFocus(slot="image", object_id=53, ordinal=1),
        recommendation_slot=RecommendationSlotState(
            query_context=RecommendationQueryContext(
                category="serum",
                recommendation_mode_basis="broad_exploration",
            ),
            candidates=(old_candidate,),
        ),
        product_slot=ProductSlotState(products=current_products),
        image_slot=ImageSlotState(
            confirmed_products=(image,),
            focused_image_ordinal=1,
            card_display=CardDisplayContract(
                mode="comparison",
                visible_product_ids=(53, 55),
                max_cards=2,
                reason="comparison",
            ),
        ),
    )

    decision = route_unified_turn(
        meaning=_meaning("knowledge", continuity="continue"),
        understanding=_understanding(
            UnderstandingGoal.KNOWLEDGE,
            references=(_reference("candidate_ordinal", 1),),
        ),
        snapshot=snapshot,
    )

    assert decision.processor == "product_knowledge"
    assert [item.product_id for item in decision.product_bindings] == [53]


def test_image_and_candidate_references_are_merged_in_source_order() -> None:
    image = ConfirmedImageProductRef(
        image_ordinal=1,
        product_id=53,
    )
    snapshot = _snapshot_with_dormant_product_and_active_image(
        dormant_product_id=91,
        active_image=image,
    )
    understanding = _understanding(
        UnderstandingGoal.COMPARISON,
        references=(
            ReferenceDraft(
                kind="image_ordinal",
                ordinal=1,
                source_span=SourceSpan(start=0, end=2),
            ),
            ReferenceDraft(
                kind="candidate_ordinal",
                ordinal=1,
                source_span=SourceSpan(start=3, end=5),
            ),
        ),
    )

    decision = route_unified_turn(
        meaning=_meaning("comparison", continuity="continue"),
        understanding=understanding,
        snapshot=snapshot,
        current_image_products=(image,),
    )

    assert decision.processor == "comparison"
    assert decision.focus_source == "confirmed_image"
    assert [binding.product_id for binding in decision.product_bindings] == [
        53,
        91,
    ]


def test_explicit_product_and_candidate_reference_are_merged_in_source_order(
) -> None:
    understanding = _understanding(
        UnderstandingGoal.COMPARISON,
        references=(
            ReferenceDraft(
                kind="candidate_ordinal",
                ordinal=1,
                source_span=SourceSpan(start=6, end=9),
            ),
        ),
    ).model_copy(
        update={
            "product_mentions": [
                ProductMentionDraft(
                    text="B5精华",
                    source_span=SourceSpan(start=0, end=4),
                )
            ]
        },
        deep=True,
    )

    decision = route_unified_turn(
        meaning=_meaning("comparison", continuity="continue"),
        understanding=understanding,
        snapshot=_snapshot(product_ids=(91, 39)),
        product_bindings=(
            ResolvedProductBinding(
                product_id=38,
                source_text="B5精华",
                source_span=SourceSpan(start=0, end=4),
                source_kind="explicit_product",
            ),
        ),
    )

    assert decision.processor == "comparison"
    assert decision.focus_source == "candidate_batch"
    assert [binding.product_id for binding in decision.product_bindings] == [
        38,
        91,
    ]


def test_single_confirmed_image_similarity_reuses_committed_identity() -> None:
    image = ConfirmedImageProductRef(
        image_ordinal=1,
        product_id=53,
    )
    decision = route_unified_turn(
        meaning=_meaning(
            "image_similarity",
            continuity="continue",
        ),
        understanding=_understanding(
            UnderstandingGoal.IMAGE_SIMILARITY,
            topic=None,
        ).model_copy(
            update={
                "recommendation_mode": "explore",
                "recommendation_mode_basis": "similar_alternatives",
                "recommendation_count": 2,
            },
            deep=True,
        ),
        snapshot=_snapshot(
            processor="image_identity",
            product_ids=(53,),
            current_product_id=53,
            confirmed_images=(image,),
        ),
    )

    assert decision.processor == "recommendation"
    assert decision.focus_source == "confirmed_image"
    assert [item.product_id for item in decision.product_bindings] == [53]
    assert decision.task_plan is not None
    assert decision.task_plan.mode == "recommend"
    assert decision.task_plan.similarity_anchor_product_id == 53


def test_unbound_suitability_clarification_is_finalized_by_router() -> None:
    decision = route_unified_turn(
        meaning=_meaning("suitability", continuity="new_task"),
        understanding=_understanding(
            UnderstandingGoal.SUITABILITY,
            topic=TopicCode.SERUM,
        ),
        snapshot=None,
    )

    assert decision.processor == "clarification"
    assert decision.task_plan is not None
    assert decision.task_plan.mode == "clarify"


def test_image_similarity_explicit_ordinal_overrides_generic_current_item(
) -> None:
    images = (
        ConfirmedImageProductRef(
            image_ordinal=1,
            product_id=53,
        ),
        ConfirmedImageProductRef(
            image_ordinal=2,
            product_id=55,
        ),
    )
    decision = route_unified_turn(
        meaning=_meaning(
            "image_similarity",
            continuity="continue",
        ),
        understanding=_understanding(
            UnderstandingGoal.IMAGE_SIMILARITY,
            topic=TopicCode.SUNSCREEN,
            references=(
                _reference("current_item"),
                _reference("image_ordinal", 2),
            ),
        ),
        snapshot=_snapshot(
            processor="product_knowledge",
            product_ids=(53,),
            current_product_id=53,
            confirmed_images=images,
        ),
    )

    assert decision.processor == "recommendation"
    assert decision.focus_source == "confirmed_image"
    assert [
        item.product_id for item in decision.product_bindings
    ] == [55]


def test_single_image_product_batch_quantity_routes_to_alternatives() -> None:
    meaning = TurnMeaning.model_validate(
        {
            "operation_hint": "comparison",
            "topic_hint": None,
            "continuity_hint": "continue",
            "subject_scope_hint": "unknown",
            "reference_mentions": [
                {
                    "raw_text": "两款",
                    "object_family_hint": "product",
                    "ordinal_hint": None,
                    "plurality_hint": "batch",
                }
            ],
            "product_mentions": [
                {"raw_text": "两款相似的产品"}
            ],
            "budget_candidates": [],
            "observation_candidates": [],
            "preference_candidates": [],
            "relative_candidates": [],
            "consultation_hypothesis": None,
            "next_observation_gap": None,
            "question_meaning": (
                "寻找两款相似的产品，并说明相似和不同之处"
            ),
            "safety_language": "unknown",
        },
        strict=True,
    )
    image = ConfirmedImageProductRef(
        image_ordinal=1,
        product_id=53,
    )

    decision = route_unified_turn(
        meaning=meaning,
        understanding=_understanding(
            UnderstandingGoal.COMPARISON,
            topic=None,
        ),
        snapshot=None,
        current_image_products=(image,),
    )

    assert decision.processor == "recommendation"
    assert decision.focus_source == "confirmed_image"
    assert [item.product_id for item in decision.product_bindings] == [53]


def test_single_image_atomless_comparison_discovers_alternatives() -> None:
    image = ConfirmedImageProductRef(
        image_ordinal=1,
        product_id=53,
    )

    decision = route_unified_turn(
        meaning=_meaning("comparison", continuity="continue"),
        understanding=_understanding(
            UnderstandingGoal.COMPARISON,
            topic=None,
        ),
        snapshot=None,
        current_image_products=(image,),
    )

    assert decision.processor == "recommendation"
    assert decision.focus_source == "confirmed_image"
    assert [item.product_id for item in decision.product_bindings] == [53]


def test_single_image_unbound_second_object_still_clarifies() -> None:
    image = ConfirmedImageProductRef(
        image_ordinal=1,
        product_id=53,
    )
    meaning = TurnMeaning.model_validate(
        {
            "operation_hint": "comparison",
            "topic_hint": None,
            "continuity_hint": "continue",
            "subject_scope_hint": "unknown",
            "reference_mentions": [
                {
                    "raw_text": "另一款",
                    "object_family_hint": "product",
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
            "question_meaning": "把图片商品和另一款商品比较",
            "safety_language": "unknown",
        },
        strict=True,
    )

    decision = route_unified_turn(
        meaning=meaning,
        understanding=_understanding(
            UnderstandingGoal.COMPARISON,
            topic=None,
        ),
        snapshot=None,
        current_image_products=(image,),
    )

    assert decision.processor == "clarification"
    assert decision.clarification_code is ClarificationCode.REFERENCE


def test_multiple_current_images_do_not_override_recommendation() -> None:
    images = (
        ConfirmedImageProductRef(
            image_ordinal=1,
            product_id=53,
        ),
        ConfirmedImageProductRef(
            image_ordinal=2,
            product_id=55,
        ),
    )

    decision = route_unified_turn(
        meaning=_meaning("recommendation", continuity="new_task"),
        understanding=_understanding(
            UnderstandingGoal.RECOMMENDATION,
            topic=TopicCode.SUNSCREEN,
        ),
        snapshot=None,
        current_image_products=images,
    )

    assert decision.processor == "recommendation"
    assert decision.focus_source == "confirmed_image"
    assert [item.product_id for item in decision.product_bindings] == [
        53,
        55,
    ]


def test_multiple_current_images_need_explicit_comparison_operation() -> None:
    images = (
        ConfirmedImageProductRef(
            image_ordinal=1,
            product_id=53,
        ),
        ConfirmedImageProductRef(
            image_ordinal=2,
            product_id=55,
        ),
    )

    decision = route_unified_turn(
        meaning=_meaning("clarification", continuity="continue"),
        understanding=_understanding(
            UnderstandingGoal.CLARIFICATION,
            topic=None,
        ),
        snapshot=None,
        current_image_products=images,
    )

    assert decision.processor == "clarification"
    assert decision.focus_source == "none"
    assert decision.product_bindings == ()


def test_multiple_current_images_route_to_image_comparison_when_explicit(
) -> None:
    images = (
        ConfirmedImageProductRef(
            image_ordinal=1,
            product_id=53,
        ),
        ConfirmedImageProductRef(
            image_ordinal=2,
            product_id=55,
        ),
    )

    decision = route_unified_turn(
        meaning=_meaning("comparison", continuity="continue"),
        understanding=_understanding(
            UnderstandingGoal.COMPARISON,
            topic=TopicCode.SUNSCREEN,
        ),
        snapshot=None,
        current_image_products=images,
    )

    assert decision.processor == "image_comparison"
    assert decision.focus_source == "confirmed_image"
    assert [item.product_id for item in decision.product_bindings] == [
        53,
        55,
    ]


def test_specific_ordinal_inside_current_batch_overrides_batch() -> None:
    decision = route_unified_turn(
        meaning=_meaning("knowledge", continuity="continue"),
        understanding=_understanding(
            UnderstandingGoal.KNOWLEDGE,
            references=(
                _reference("current_batch"),
                _reference("candidate_ordinal", 2),
            ),
        ),
        snapshot=_snapshot(product_ids=(51, 55, 101)),
    )

    assert decision.processor == "product_knowledge"
    assert decision.focus_source == "candidate_batch"
    assert [item.product_id for item in decision.product_bindings] == [55]


def test_explicit_product_inside_current_batch_overrides_batch() -> None:
    decision = route_unified_turn(
        meaning=_meaning("knowledge", continuity="continue"),
        understanding=_understanding(
            UnderstandingGoal.KNOWLEDGE,
            references=(_reference("current_batch"),),
        ),
        snapshot=_snapshot(product_ids=(51, 55, 101)),
        product_bindings=(_binding(55),),
    )

    assert decision.processor == "product_knowledge"
    assert decision.focus_source == "explicit_product"
    assert [item.product_id for item in decision.product_bindings] == [55]


def test_comparison_adds_third_and_rejects_fourth() -> None:
    third = route_unified_turn(
        meaning=_meaning("comparison", continuity="continue"),
        understanding=_understanding(
            UnderstandingGoal.COMPARISON,
            references=(_reference("current_batch"),),
        ),
        snapshot=_snapshot(
            processor="comparison",
            product_ids=(51, 55),
        ),
        product_bindings=(_binding(101),),
    )
    fourth = route_unified_turn(
        meaning=_meaning("comparison", continuity="continue"),
        understanding=_understanding(
            UnderstandingGoal.COMPARISON,
            references=(_reference("current_batch"),),
        ),
        snapshot=_snapshot(
            processor="comparison",
            product_ids=(51, 55, 101),
        ),
        product_bindings=(_binding(129),),
    )

    assert third.processor == "comparison"
    assert [item.product_id for item in third.product_bindings] == [
        51,
        55,
        101,
    ]
    assert fourth.processor == "clarification"
    assert fourth.clarification_code is ClarificationCode.REFERENCE
    assert "最多比较三款" in fourth.clarification


@pytest.mark.parametrize(
    ("operations", "expected"),
    (
        (("replace",), "correct"),
        (("remove",), "withdraw"),
        (("add",), "supplement"),
        (("remove", "add"), "correct"),
        (("replace", "remove"), "correct"),
    ),
)
def test_constraint_operations_control_continuity(
    operations: tuple[str, ...],
    expected: str,
) -> None:
    decision = route_unified_turn(
        meaning=_meaning("recommendation", continuity="continue"),
        understanding=_understanding(
            UnderstandingGoal.RECOMMENDATION
        ),
        snapshot=_snapshot(),
        transition_operations=operations,
    )

    assert decision.processor == "recommendation"
    assert decision.continuity == expected


def test_explicit_new_task_wins_over_initial_constraint_additions() -> None:
    decision = route_unified_turn(
        meaning=_meaning(
            "recommendation",
            continuity="new_task",
        ),
        understanding=_understanding(
            UnderstandingGoal.RECOMMENDATION
        ),
        snapshot=None,
        transition_operations=("add",),
    )

    assert decision.processor == "recommendation"
    assert decision.continuity == "replace_task"


def _pending() -> PendingTurn:
    return PendingTurn(
        gap=ClarificationCode.BUDGET,
        attempts=1,
        source_conversation_version=0,
        source_message="预算一千左右的精华",
        expected_response="confirm_or_correct",
        resume_mode="recommendation",
        resume_context=PendingRecommendationContext(
            category="serum",
            recommendation_mode_basis="broad_exploration",
        ),
        proposed_budget=PendingBudgetRange(
            minimum=Decimal("900"),
            maximum=Decimal("1100"),
        ),
    )


@pytest.mark.parametrize(
    ("reply_kind", "processor", "continuity"),
    (
        ("affirm", "recommendation", "continue"),
        ("correct", "recommendation", "correct"),
        ("supplement", "recommendation", "supplement"),
        ("reject", "clarification", "continue"),
        ("ambiguous", "clarification", "continue"),
    ),
)
def test_pending_reply_priority(
    reply_kind: str,
    processor: str,
    continuity: str,
) -> None:
    decision = route_unified_turn(
        meaning=_meaning("clarification", continuity="continue"),
        understanding=_understanding(
            UnderstandingGoal.CLARIFICATION,
            topic=None,
        ),
        snapshot=_snapshot(pending_turn=_pending()),
        pending_reply_kind=reply_kind,
    )

    assert decision.processor == processor
    assert decision.continuity == continuity


def _mild_burning_observation() -> dict[str, object]:
    return {
        "observation_id": "obs_heat",
        "code": "burning",
        "present": True,
        "qualifier": None,
        "raw_text": "发热",
        "location": None,
        "trigger": None,
        "duration": "current",
        "severity": "unknown",
    }


def test_mild_transient_burning_does_not_escalate_on_first_turn() -> None:
    meaning = _meaning(
        "assessment",
        continuity="new_task",
        observations=(_mild_burning_observation(),),
    )
    decision = route_unified_turn(
        meaning=meaning,
        safety_signal=admit_safety_signal(
            message="最近会发热",
            candidates=meaning.observation_candidates,
        ),
        understanding=_understanding(UnderstandingGoal.ASSESSMENT),
        snapshot=None,
    )

    assert decision.processor != "safety_escalation"


def test_new_product_burning_still_escalates() -> None:
    meaning = _meaning(
        "assessment",
        continuity="new_task",
        observations=(
            {
                **_mild_burning_observation(),
                "trigger": "new_product",
            },
        ),
    )
    decision = route_unified_turn(
        meaning=meaning,
        safety_signal=admit_safety_signal(
            message="换新产品后发热",
            candidates=meaning.observation_candidates,
        ),
        understanding=_understanding(UnderstandingGoal.ASSESSMENT),
        snapshot=None,
    )

    assert decision.processor == "safety_escalation"


def test_active_damage_routes_to_safety_before_other_modes() -> None:
    meaning = _meaning(
        "recommendation",
        continuity="new_task",
        observations=(
            {
                "observation_id": "obs_damage",
                "code": "broken_skin",
                "present": True,
                "qualifier": None,
                "raw_text": "已经破皮",
                "location": None,
                "trigger": None,
                "duration": "current",
                "severity": "severe",
            },
        ),
    )
    decision = route_unified_turn(
        meaning=meaning,
        safety_signal=admit_safety_signal(
            message="现在已经破皮",
            candidates=meaning.observation_candidates,
        ),
        understanding=_understanding(
            UnderstandingGoal.RECOMMENDATION
        ),
        snapshot=_snapshot(),
    )

    assert decision.processor == "safety_escalation"
    assert decision.continuity == "replace_task"
    assert decision.focus_source == "consultation"


def test_repeated_active_safety_observation_continues_escalation() -> None:
    meaning = _meaning(
        "assessment",
        continuity="new_task",
        observations=(
            {
                "observation_id": "obs_oozing",
                "code": "oozing",
                "present": True,
                "qualifier": None,
                "raw_text": "仍然在渗",
                "location": None,
                "trigger": None,
                "duration": "current",
                "severity": "severe",
            },
        ),
    )
    decision = route_unified_turn(
        meaning=meaning,
        safety_signal=admit_safety_signal(
            message="现在仍然在渗",
            candidates=meaning.observation_candidates,
        ),
        understanding=_understanding(
            UnderstandingGoal.ASSESSMENT,
            topic=None,
        ),
        snapshot=_snapshot(processor="safety_escalation"),
    )

    assert decision.processor == "safety_escalation"
    assert decision.continuity == "continue"
    assert decision.focus_source == "consultation"


def test_executable_route_decision_requires_router_owned_task_plan() -> None:
    with pytest.raises(ValidationError, match="task_plan"):
        UnifiedRouteDecision(
            processor="general_knowledge",
            responsibility=Responsibility.GENERAL_KNOWLEDGE,
            presentation_mode="general_knowledge",
            continuity="replace_task",
            focus_source="none",
        )


def test_comparison_finalization_preserves_pre_routing_task() -> None:
    understanding = _understanding(UnderstandingGoal.COMPARISON)
    enriched_task = TaskPlan(
        mode="clarify",
        referenced_image_ids=[],
        constraints=[
            CategoryConstraint(value=TopicCode.SUNSCREEN),
            SkinConstraint(value=SkinTarget.SENSITIVE),
        ],
        references=understanding.references,
        product_mentions=understanding.product_mentions,
        required_evidence=[],
        requested_comparison_dimensions=("texture",),
        question_meaning="保留富集后的比较问题",
        safety_sensitive=True,
        clarification="请明确要比较的商品。",
        clarification_code=ClarificationCode.REFERENCE,
    )

    decision = route_unified_turn(
        meaning=_meaning("comparison", continuity="new_task"),
        understanding=understanding,
        snapshot=None,
        product_bindings=(_binding(38), _binding(91)),
        task_plan=enriched_task,
    )

    assert decision.task_plan.model_dump(
        exclude={
            "mode",
            "recommendation_mode",
            "recommendation_mode_basis",
            "recommendation_count",
            "product_ids",
            "similarity_anchor_product_id",
            "required_evidence",
            "clarification",
            "clarification_code",
        },
        mode="python",
    ) == enriched_task.model_dump(
        exclude={
            "mode",
            "recommendation_mode",
            "recommendation_mode_basis",
            "recommendation_count",
            "product_ids",
            "similarity_anchor_product_id",
            "required_evidence",
            "clarification",
            "clarification_code",
        },
        mode="python",
    )
    assert decision.task_plan.mode == "comparison"
    assert decision.task_plan.product_ids == [38, 91]
    assert decision.task_plan.required_evidence == ["canonical_product"]
    assert decision.task_plan.clarification is None
    assert decision.task_plan.clarification_code is None


def test_duplicate_product_images_remain_independently_referenceable() -> None:
    bundle_id = "bundle_" + "a" * 32
    images = (
        ConfirmedImageProductRef(
            image_ordinal=1,
            product_id=53,
            source_bundle_id=bundle_id,
            source_image_id="image_" + "b" * 32,
        ),
        ConfirmedImageProductRef(
            image_ordinal=2,
            product_id=53,
            source_bundle_id=bundle_id,
            source_image_id="image_" + "c" * 32,
        ),
    )

    decision = route_unified_turn(
        meaning=_meaning("image_identity", continuity="continue"),
        understanding=_understanding(
            UnderstandingGoal.IMAGE_IDENTITY,
            references=(
                ReferenceDraft(
                    kind="image_ordinal",
                    ordinal=2,
                    source_span=SourceSpan(start=0, end=3),
                ),
            ),
        ),
        snapshot=_snapshot(
            processor="image_identity",
            current_product_id=53,
            confirmed_images=images,
        ),
    )

    assert decision.processor == "image_identity"
    assert len(decision.product_bindings) == 1
    assert decision.product_bindings[0].product_id == 53
    assert decision.product_bindings[0].source_text == "image_ordinal:2"


def test_router_requires_the_exact_pre_routing_task_plan() -> None:
    parameter = inspect.signature(_route_unified_turn).parameters["task_plan"]

    assert parameter.default is inspect.Parameter.empty
    assert "plan_task(" not in inspect.getsource(_route_unified_turn)


def test_duplicate_image_sources_reach_image_comparison_as_two_bindings() -> None:
    understanding = _understanding(UnderstandingGoal.COMPARISON)
    task_plan = plan_task(
        understanding,
        resolved_product_ids=(53,),
    )
    bundle_id = "bundle_" + "d" * 32
    images = (
        ConfirmedImageProductRef(
            image_ordinal=1,
            product_id=53,
            source_bundle_id=bundle_id,
            source_image_id="image_" + "e" * 32,
        ),
        ConfirmedImageProductRef(
            image_ordinal=2,
            product_id=53,
            source_bundle_id=bundle_id,
            source_image_id="image_" + "f" * 32,
        ),
    )

    decision = route_unified_turn(
        meaning=_meaning("comparison", continuity="continue"),
        understanding=understanding,
        snapshot=None,
        current_image_products=images,
        task_plan=task_plan,
    )

    assert decision.processor == "image_comparison"
    assert [binding.product_id for binding in decision.product_bindings] == [
        53,
        53,
    ]
    assert [binding.source_text for binding in decision.product_bindings] == [
        "image_ordinal:1",
        "image_ordinal:2",
    ]
    assert [
        (binding.source_kind, binding.source_ordinal)
        for binding in decision.product_bindings
    ] == [
        ("image_ordinal", 1),
        ("image_ordinal", 2),
    ]
    assert decision.public_intent_mode == "image_compare"
    assert decision.task_plan.mode == "comparison"
    assert decision.task_plan.product_ids == []
