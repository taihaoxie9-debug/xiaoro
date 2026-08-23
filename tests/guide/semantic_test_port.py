from __future__ import annotations

from app.guide.understanding.contracts import CategoryDraft, TopicCode
from app.guide.understanding.exact_parsing import parse_exact_constraints
from app.guide.understanding.semantic_contracts import (
    SemanticContext,
    SemanticGoal,
    SemanticIntentProposal,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning


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


class TypedExactEchoUnderstanding:
    """Offline frozen TurnMeaning provider for production-path tests."""

    def translate(
        self,
        message: str,
        *,
        context: SemanticContext,
    ) -> TurnMeaning:
        constraints, _ = parse_exact_constraints(message)
        topics = list(
            dict.fromkeys(
                item.value
                for item in constraints
                if isinstance(item, CategoryDraft)
            )
        )
        topic = topics[0] if len(topics) == 1 else None
        recommendation = topic is not None
        return TurnMeaning(
            operation_hint=(
                "recommendation"
                if recommendation
                else "clarification"
            ),
            recommendation_mode=(
                "explore" if recommendation else None
            ),
            recommendation_count=None,
            recommendation_mode_basis=(
                {
                    "basis": "broad_exploration",
                    "source_text": message,
                }
                if recommendation
                else None
            ),
            topic_hint=topic.value if topic is not None else None,
            continuity_hint=(
                "new_task"
                if context.conversation_version == 0
                else "unknown"
            ),
            subject_scope_hint="self",
            reference_mentions=(),
            product_mentions=(),
            budget_candidates=(),
            observation_candidates=(),
            preference_candidates=(),
            relative_candidates=(),
            consultation_hypothesis=None,
            next_observation_gap=None,
            question_meaning=message,
            safety_language="ordinary",
        )


def exact_echo_understanding() -> TypedExactEchoUnderstanding:
    return TypedExactEchoUnderstanding()
