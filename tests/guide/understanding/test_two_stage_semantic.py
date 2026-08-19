from __future__ import annotations

import pytest

from app.guide.understanding.contracts import (
    TopicCode,
    UnderstandingGoal,
)
from app.guide.understanding.semantic_contracts import (
    ClarificationCode,
    ConcernCode,
    SemanticProductMention,
    SemanticReference,
)
from app.guide.understanding.semantic_detail_contracts import (
    ComparisonDetails,
    KnowledgeDetails,
    RecommendationDetails,
)
from app.guide.understanding.semantic_route_contracts import (
    SemanticDetailStage,
    SemanticRouteProposal,
)
from app.guide.understanding.two_stage_semantic import (
    compose_semantic_proposal,
)


def _route(
    *,
    goal: UnderstandingGoal = UnderstandingGoal.RECOMMENDATION,
    stage: SemanticDetailStage = SemanticDetailStage.RECOMMENDATION,
) -> SemanticRouteProposal:
    return SemanticRouteProposal(
        goal=goal,
        topic=TopicCode.SUNSCREEN,
        detail_stage=stage,
        confidence=0.93,
        clarification_hint=None,
    )


def test_projection_returns_current_semantic_proposal() -> None:
    proposal = compose_semantic_proposal(
        _route(),
        RecommendationDetails(
            concerns=(ConcernCode.SUN_PROTECTION,),
            observations=(),
        ),
    )

    assert proposal.schema_version == "guide-semantic-intent-v7"
    assert proposal.goal is UnderstandingGoal.RECOMMENDATION
    assert proposal.topic is TopicCode.SUNSCREEN
    assert proposal.concerns == (ConcernCode.SUN_PROTECTION,)
    assert proposal.references == ()


def test_comparison_projection_preserves_source_bound_product_mentions(
) -> None:
    mention = SemanticProductMention(
        text="理肤泉特护清盈防晒乳",
        start=2,
        end=12,
    )
    proposal = compose_semantic_proposal(
        _route(
            goal=UnderstandingGoal.COMPARISON,
            stage=SemanticDetailStage.COMPARISON,
        ),
        ComparisonDetails(
            references=(),
            product_mentions=(mention,),
        ),
    )

    assert proposal.goal is UnderstandingGoal.COMPARISON
    assert proposal.product_mentions == (mention,)


def test_knowledge_projection_preserves_question_translation() -> None:
    proposal = compose_semantic_proposal(
        _route(
            goal=UnderstandingGoal.KNOWLEDGE,
            stage=SemanticDetailStage.KNOWLEDGE,
        ),
        KnowledgeDetails(
            concerns=(),
            question_meaning="询问面膜是否容易滑落",
            safety_sensitive=False,
        ),
    )

    assert proposal.question_meaning == "询问面膜是否容易滑落"
    assert not proposal.safety_sensitive


def test_projection_requires_exact_detail_type_for_route_stage() -> None:
    with pytest.raises(ValueError, match="detail type"):
        compose_semantic_proposal(
            _route(),
            ComparisonDetails(
                references=(
                    SemanticReference(
                        kind="current_batch",
                        ordinal=None,
                        raw_text="这两款",
                        start=0,
                        end=3,
                    ),
                )
            ),
        )


def test_projection_requires_detail_for_non_clarification_route() -> None:
    with pytest.raises(ValueError, match="requires details"):
        compose_semantic_proposal(_route(), None)


def test_clarification_projection_forbids_details() -> None:
    route = SemanticRouteProposal(
        goal=UnderstandingGoal.CLARIFICATION,
        topic=None,
        detail_stage=SemanticDetailStage.NONE,
        confidence=0.35,
        clarification_hint=ClarificationCode.GOAL,
    )

    proposal = compose_semantic_proposal(route, None)
    assert proposal.goal is UnderstandingGoal.CLARIFICATION
    assert proposal.clarification_hint is ClarificationCode.GOAL

    with pytest.raises(ValueError, match="forbids details"):
        compose_semantic_proposal(
            route,
            RecommendationDetails(
                concerns=(),
                observations=(),
            ),
        )
