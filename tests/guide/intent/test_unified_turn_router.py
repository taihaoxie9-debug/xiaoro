from __future__ import annotations

from decimal import Decimal

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
from app.guide.intent.unified_turn_router import route_unified_turn
from app.guide.retrieval.product_name_resolver import (
    ResolvedProductBinding,
)
from app.guide.understanding.contracts import (
    ProductMentionDraft,
    ReferenceDraft,
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
    return TurnMeaning.model_validate(
        {
            "operation_hint": operation,
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
    return StructuredUnderstanding(
        goal=goal,
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
    )


def _snapshot(
    *,
    processor: str = "recommendation",
    product_ids: tuple[int, ...] = (51, 55, 101),
    current_product_id: int | None = None,
    pending_turn: PendingTurn | None = None,
    confirmed_images: tuple[ConfirmedImageProductRef, ...] = (),
) -> ConversationSnapshot:
    return ConversationSnapshot(
        session_id="router-session",
        version=2,
        query_context=RecommendationQueryContext(
            category="sunscreen",
            budget_minimum=None,
            budget_maximum=Decimal("500"),
            skin=None,
            efficacy=None,
            exclusions=(),
        ),
        candidates=tuple(
            DisplayedCandidateRef(
                product_id=product_id,
                ordinal=index,
                skin_match="unknown",
                matched_efficacies=(),
            )
            for index, product_id in enumerate(product_ids, start=1)
        ),
        focused_candidate_ordinal=(
            product_ids.index(current_product_id) + 1
            if current_product_id in product_ids
            else None
        ),
        pending_turn=pending_turn,
        focus_state=FocusState(
            active_processor=processor,
            current_product_id=current_product_id,
            confirmed_image_products=confirmed_images,
            current_knowledge_topic=(
                "视黄醇"
                if processor == "general_knowledge"
                else None
            ),
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
        clarification=ClarificationProgress(
            gap=ClarificationCode.REFERENCE,
            attempts=1,
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
def test_confirmed_image_reuses_standard_processor(
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


def test_multiple_current_images_route_to_standard_comparison_when_explicit(
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

    assert decision.processor == "comparison"
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
