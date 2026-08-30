from __future__ import annotations

from app.guide.understanding.contracts import (
    ReferenceDraft,
    StructuredUnderstanding,
    UnderstandingGoal,
)
from app.guide.understanding.exact_parsing import parse_exact_constraints


def understand_text(message: str) -> StructuredUnderstanding:
    """Build legacy exact-only test input outside the production package."""
    text = message.strip()
    if not 1 <= len(text) <= 4000:
        raise ValueError("message length must be between 1 and 4000")
    exact_constraints, uncertainties = parse_exact_constraints(text)
    topic = next(
        (
            item.value
            for item in exact_constraints
            if item.kind == "category"
        ),
        None,
    )
    return StructuredUnderstanding(
        goal=UnderstandingGoal.RECOMMENDATION,
        recommendation_mode="explore",
        recommendation_mode_basis="broad_exploration",
        recommendation_count=3,
        topic=topic,
        observations=[f"raw_message={text}"],
        exact_constraints=exact_constraints,
        semantic_proposals=[],
        signal_trace=[],
        references=[
            item
            for item in exact_constraints
            if isinstance(item, ReferenceDraft)
        ],
        image_references=[],
        uncertainties=uncertainties,
        confidence=1.0 if exact_constraints and not uncertainties else 0.0,
    )


__all__ = ["understand_text"]
