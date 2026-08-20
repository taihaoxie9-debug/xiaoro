from __future__ import annotations

from app.guide.intent.concept_preferences import (
    ConceptCatalogEntry,
    ConceptPreferenceCatalog,
)
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.understanding.contracts import (
    TopicCode,
    UnderstandingGoal,
)
from app.guide.understanding.semantic_contracts import SemanticContext
from app.guide.understanding.single_call_understanding import (
    SingleCallUnderstanding,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning


class FakeTurnMeaningPort:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def propose(self, message, context):
        del context
        self.calls += 1
        if self.fail:
            raise RuntimeError("provider unavailable")
        return TurnMeaning.model_validate(
            {
                "operation_hint": "recommendation",
                "topic_hint": "sunscreen",
                "reference_mentions": [],
                "product_mentions": [],
                "budget_candidates": [],
                "observation_candidates": [],
                "preference_candidates": [
                    {
                        "field_key": "texture",
                        "concept_id": "texture.refreshing",
                        "raw_text": "清爽",
                        "polarity": "prefer",
                        "strength": "ordinary",
                    }
                ],
                "relative_candidates": [],
                "question_meaning": message,
                "safety_language": "ordinary",
            },
            strict=True,
        )


def _context() -> SemanticContext:
    return SemanticContext(
        conversation_version=0,
        active_topic=None,
        visible_candidate_count=0,
        confirmed_profile_fields=(),
    )


def _concept_catalog() -> ConceptPreferenceCatalog:
    return ConceptPreferenceCatalog(
        entries=(
            ConceptCatalogEntry(
                profile=CategoryProfile.SUNCARE,
                field_key="texture",
                concept_id="texture.refreshing",
            ),
        )
    )


def test_single_call_understanding_invokes_model_once() -> None:
    semantic = FakeTurnMeaningPort()
    understanding = SingleCallUnderstanding(
        semantic=semantic,
        concept_catalog=_concept_catalog(),
    )

    result = understanding.understand(
        "推荐清爽防晒",
        context=_context(),
    )

    assert semantic.calls == 1
    assert result.goal is UnderstandingGoal.RECOMMENDATION
    assert result.topic is TopicCode.SUNSCREEN
    assert result.preference_drafts[0].value == "清爽"


def test_translate_returns_meaning_and_compilation_from_same_call() -> None:
    semantic = FakeTurnMeaningPort()
    understanding = SingleCallUnderstanding(
        semantic=semantic,
        concept_catalog=_concept_catalog(),
    )

    meaning, compiled = understanding.translate(
        "推荐清爽防晒",
        context=_context(),
    )

    assert semantic.calls == 1
    assert meaning.operation_hint == "recommendation"
    assert compiled.goal is UnderstandingGoal.RECOMMENDATION
    assert compiled.topic is TopicCode.SUNSCREEN


def test_single_call_provider_failure_fails_closed() -> None:
    semantic = FakeTurnMeaningPort(fail=True)
    understanding = SingleCallUnderstanding(
        semantic=semantic,
        concept_catalog=_concept_catalog(),
    )

    result = understanding.understand(
        "推荐清爽防晒",
        context=_context(),
    )

    assert semantic.calls == 1
    assert result.goal is UnderstandingGoal.CLARIFICATION
    assert result.uncertainties


def test_closed_exact_control_skips_model() -> None:
    semantic = FakeTurnMeaningPort()
    understanding = SingleCallUnderstanding(
        semantic=semantic,
        concept_catalog=_concept_catalog(),
    )

    result = understanding.understand(
        "后来改选洁面！！！",
        context=_context(),
        semantic_required=False,
    )

    assert semantic.calls == 0
    assert result.goal is UnderstandingGoal.RECOMMENDATION
    assert result.topic is TopicCode.CLEANSER
