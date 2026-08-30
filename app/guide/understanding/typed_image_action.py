from __future__ import annotations

from app.guide.application.contracts import ImageAction
from app.guide.understanding.turn_meaning_contracts import (
    TurnMeaning,
    TurnReferenceMention,
)


def turn_meaning_for_image_action(
    *,
    action: ImageAction,
    image_count: int,
    question_summary: str,
) -> TurnMeaning:
    if action == "identify":
        if image_count != 1:
            raise ValueError(
                "identify image action requires exactly one image"
            )
        operation_hint = "image_identity"
    else:
        if not 2 <= image_count <= 4:
            raise ValueError(
                "compare image action requires two to four images"
            )
        operation_hint = "comparison"
    return TurnMeaning(
        operation_hint=operation_hint,
        topic_hint=None,
        continuity_hint="continue",
        subject_scope_hint="unknown",
        reference_mentions=(
            TurnReferenceMention(
                raw_text=question_summary,
                object_family_hint="image",
                ordinal_hint=1 if action == "identify" else None,
                plurality_hint=(
                    "single" if action == "identify" else "batch"
                ),
                batch_size_hint=(
                    image_count if action == "compare" else None
                ),
            ),
        ),
        product_mentions=(),
        budget_candidates=(),
        observation_candidates=(),
        preference_candidates=(),
        relative_candidates=(),
        consultation_hypothesis=None,
        next_observation_gap=None,
        question_meaning=question_summary,
        safety_language="unknown",
    )


__all__ = ["turn_meaning_for_image_action"]
