from __future__ import annotations

from app.guide.understanding.contracts import CategoryDraft, TopicCode
from app.guide.understanding.exact_parsing import parse_exact_constraints
from app.guide.understanding.parallel_understanding import (
    ParallelUnderstanding,
)
from app.guide.understanding.semantic_contracts import (
    SemanticContext,
    SemanticGoal,
    SemanticIntentProposal,
)


class ExactEchoSemanticPort:
    """Offline semantic test double for exact-topic integration fixtures."""

    def propose(
        self,
        message: str,
        context: SemanticContext,
    ) -> SemanticIntentProposal:
        del context
        constraints, _ = parse_exact_constraints(message)
        topics = list(
            dict.fromkeys(
                item.value
                for item in constraints
                if isinstance(item, CategoryDraft)
            )
        )
        topic: TopicCode | None = topics[0] if len(topics) == 1 else None
        goal = (
            SemanticGoal.RECOMMENDATION
            if topic is not None
            else SemanticGoal.CLARIFICATION
        )
        return SemanticIntentProposal(
            goal=goal,
            topic=topic,
            concerns=(),
            observations=(),
            references=(),
            confidence=0.99,
            clarification_hint=None,
        )


def exact_echo_understanding() -> ParallelUnderstanding:
    return ParallelUnderstanding(semantic=ExactEchoSemanticPort())
