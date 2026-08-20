from __future__ import annotations

from app.guide.understanding.semantic_contracts import (
    SemanticIntentProposal,
)
from app.guide.understanding.semantic_detail_contracts import (
    AssessmentDetails,
    ComparisonDetails,
    FollowupDetails,
    ImageDetails,
    KnowledgeDetails,
    RecommendationDetails,
    SemanticDetailsProposal,
)
from app.guide.understanding.semantic_route_contracts import (
    SemanticDetailStage,
    SemanticRouteProposal,
)


_DETAIL_TYPE_BY_STAGE: dict[
    SemanticDetailStage,
    type[SemanticDetailsProposal],
] = {
    SemanticDetailStage.RECOMMENDATION: RecommendationDetails,
    SemanticDetailStage.ASSESSMENT: AssessmentDetails,
    SemanticDetailStage.COMPARISON: ComparisonDetails,
    SemanticDetailStage.FOLLOWUP: FollowupDetails,
    SemanticDetailStage.KNOWLEDGE: KnowledgeDetails,
    SemanticDetailStage.IMAGE: ImageDetails,
}


def compose_semantic_proposal(
    route: SemanticRouteProposal,
    details: SemanticDetailsProposal | None,
) -> SemanticIntentProposal:
    if not isinstance(route, SemanticRouteProposal):
        raise TypeError("route must be a SemanticRouteProposal")
    if route.detail_stage is SemanticDetailStage.NONE:
        if details is not None:
            raise ValueError("clarification route forbids details")
        return SemanticIntentProposal(
            goal=route.goal,
            topic=route.topic,
            concerns=(),
            observations=(),
            references=(),
            product_mentions=(),
            number_candidates=(),
            preference_candidates=(),
            confidence=route.confidence,
            clarification_hint=route.clarification_hint,
            question_meaning=None,
            safety_sensitive=False,
        )
    if details is None:
        raise ValueError("routed semantic proposal requires details")
    expected_type = _DETAIL_TYPE_BY_STAGE[route.detail_stage]
    if type(details) is not expected_type:
        raise ValueError("detail type must match route stage")
    return SemanticIntentProposal(
        goal=route.goal,
        topic=route.topic,
        concerns=getattr(details, "concerns", ()),
        observations=getattr(details, "observations", ()),
        references=getattr(details, "references", ()),
        product_mentions=getattr(details, "product_mentions", ()),
        number_candidates=getattr(details, "number_candidates", ()),
        preference_candidates=getattr(
            details,
            "preference_candidates",
            (),
        ),
        confidence=route.confidence,
        clarification_hint=route.clarification_hint,
        question_meaning=details.question_meaning,
        safety_sensitive=details.safety_sensitive,
    )


def detail_type_for_stage(
    stage: SemanticDetailStage,
) -> type[SemanticDetailsProposal]:
    try:
        return _DETAIL_TYPE_BY_STAGE[stage]
    except KeyError:
        raise ValueError("detail stage does not have details") from None


__all__ = [
    "compose_semantic_proposal",
    "detail_type_for_stage",
]
