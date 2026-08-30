from __future__ import annotations

import inspect

import app.guide.intent.unified_turn_router as unified_turn_router
from app.guide.application.task_plan_enrichment import (
    promote_single_image_similarity_task,
)
from app.guide.feedback.focus_state import ConfirmedImageProductRef
from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.intent.task_planning import plan_task
from app.guide.intent.unified_turn_router import route_unified_turn
from app.guide.understanding.contracts import (
    StructuredUnderstanding,
    TopicCode,
    UnderstandingGoal,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning


def test_current_image_batch_selects_image_comparison_processor() -> None:
    understanding = StructuredUnderstanding(
        goal=UnderstandingGoal.COMPARISON,
        topic=TopicCode.SUNSCREEN,
        observations=[],
        exact_constraints=[],
        semantic_proposals=[],
        image_references=[],
        uncertainties=[],
        confidence=1.0,
        semantic_authoritative=True,
    )
    decision = route_unified_turn(
        meaning=TurnMeaning(
            operation_hint="comparison",
            topic_hint="sunscreen",
            continuity_hint="continue",
            subject_scope_hint="self",
            safety_language="ordinary",
        ),
        understanding=understanding,
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
        task_plan=plan_task(
            understanding,
            resolved_product_ids=(53, 55),
        ),
    )

    assert decision.responsibility is Responsibility.COMPARISON
    assert decision.processor == "image_comparison"


def test_four_current_images_select_image_comparison_processor() -> None:
    understanding = StructuredUnderstanding(
        goal=UnderstandingGoal.COMPARISON,
        topic=TopicCode.SUNSCREEN,
        observations=[],
        exact_constraints=[],
        semantic_proposals=[],
        image_references=[],
        uncertainties=[],
        confidence=1.0,
        semantic_authoritative=True,
    )
    decision = route_unified_turn(
        meaning=TurnMeaning(
            operation_hint="comparison",
            topic_hint="sunscreen",
            continuity_hint="continue",
            subject_scope_hint="self",
            safety_language="ordinary",
        ),
        understanding=understanding,
        snapshot=None,
        current_image_products=tuple(
            ConfirmedImageProductRef(
                image_ordinal=ordinal,
                product_id=50 + ordinal,
            )
            for ordinal in range(1, 5)
        ),
        task_plan=plan_task(
            understanding,
            resolved_product_ids=(51, 52, 53, 54),
        ),
    )

    assert decision.responsibility is Responsibility.COMPARISON
    assert decision.processor == "image_comparison"
    assert decision.focus_source == "confirmed_image"
    assert len(decision.product_bindings) == 4
    assert decision.task_plan is not None
    assert decision.task_plan.mode == "comparison"
    assert decision.task_plan.product_ids == [51, 52, 53, 54]


def test_single_image_comparison_request_becomes_similarity_task() -> None:
    understanding = StructuredUnderstanding(
        goal=UnderstandingGoal.COMPARISON,
        topic=TopicCode.SUNSCREEN,
        observations=[],
        exact_constraints=[],
        semantic_proposals=[],
        image_references=[],
        uncertainties=[],
        confidence=1.0,
        semantic_authoritative=True,
    )
    task_plan = promote_single_image_similarity_task(
        plan_task(
            understanding,
            resolved_product_ids=(53,),
        ),
        similarity_anchor_product_id=53,
        topic=understanding.topic,
    )
    decision = route_unified_turn(
        meaning=TurnMeaning(
            operation_hint="comparison",
            topic_hint="sunscreen",
            continuity_hint="continue",
            subject_scope_hint="self",
            safety_language="ordinary",
        ),
        understanding=understanding,
        snapshot=None,
        current_image_products=(
            ConfirmedImageProductRef(
                image_ordinal=1,
                product_id=53,
            ),
        ),
        task_plan=task_plan,
    )

    assert decision.processor == "recommendation"
    assert decision.task_plan is not None
    assert decision.task_plan.mode == "recommend"
    assert decision.task_plan.recommendation_mode == "explore"
    assert (
        decision.task_plan.recommendation_mode_basis
        == "similar_alternatives"
    )
    assert decision.task_plan.similarity_anchor_product_id == 53
    assert decision.task_plan.product_ids == []


def test_router_does_not_override_matrix_selected_image_processor() -> None:
    source = inspect.getsource(
        unified_turn_router._select_unified_route
    )

    assert 'processor = "image_comparison"' not in source
