from __future__ import annotations

from app.guide.feedback.focus_state import ConfirmedImageProductRef
from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.intent.unified_turn_router import route_unified_turn
from app.guide.understanding.contracts import (
    StructuredUnderstanding,
    TopicCode,
    UnderstandingGoal,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning


def test_current_image_batch_selects_image_comparison_processor() -> None:
    decision = route_unified_turn(
        meaning=TurnMeaning(
            operation_hint="comparison",
            topic_hint="sunscreen",
            continuity_hint="continue",
            subject_scope_hint="self",
            safety_language="ordinary",
        ),
        understanding=StructuredUnderstanding(
            goal=UnderstandingGoal.COMPARISON,
            topic=TopicCode.SUNSCREEN,
            observations=[],
            exact_constraints=[],
            semantic_proposals=[],
            image_references=[],
            uncertainties=[],
            confidence=1.0,
            semantic_authoritative=True,
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

    assert decision.responsibility is Responsibility.COMPARISON
    assert decision.processor == "image_comparison"
