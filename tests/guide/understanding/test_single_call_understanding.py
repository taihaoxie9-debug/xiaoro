from __future__ import annotations

import app.guide.understanding.single_call_understanding as single_call_module

from app.guide.intent.concept_preferences import (
    ConceptCatalogEntry,
    ConceptPreferenceCatalog,
)
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.understanding.semantic_contracts import SemanticContext
from app.guide.understanding.single_call_understanding import (
    SingleCallUnderstanding,
)
from app.guide.understanding.text_understanding import (
    ExactOnlyTextUnderstanding,
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

    result = understanding.translate(
        "推荐清爽防晒",
        context=_context(),
    )

    assert semantic.calls == 1
    assert result.operation_hint == "recommendation"
    assert result.topic_hint == "sunscreen"
    assert result.preference_candidates[0].raw_text == "清爽"


def test_provider_success_translation_returns_only_turn_meaning_without_compiling(
    monkeypatch,
) -> None:
    semantic = FakeTurnMeaningPort()
    understanding = SingleCallUnderstanding(
        semantic=semantic,
        concept_catalog=_concept_catalog(),
    )

    def reject_hidden_compiler(**kwargs):
        del kwargs
        raise AssertionError("translation must not compile")

    monkeypatch.setattr(
        single_call_module,
        "compile_turn_meaning",
        reject_hidden_compiler,
        raising=False,
    )

    meaning = understanding.translate(
        "推荐清爽防晒",
        context=_context(),
    )

    assert semantic.calls == 1
    assert type(meaning) is TurnMeaning
    assert meaning.operation_hint == "recommendation"


def test_provider_failure_translation_returns_exact_turn_meaning_without_compiling(
    monkeypatch,
) -> None:
    understanding = SingleCallUnderstanding(
        semantic=FakeTurnMeaningPort(fail=True),
        concept_catalog=_concept_catalog(),
    )

    def reject_hidden_compiler(**kwargs):
        del kwargs
        raise AssertionError("translation fallback must not compile")

    monkeypatch.setattr(
        single_call_module,
        "compile_turn_meaning",
        reject_hidden_compiler,
        raising=False,
    )

    meaning = understanding.translate(
        "推荐清爽防晒",
        context=_context(),
    )

    assert type(meaning) is TurnMeaning
    assert meaning.operation_hint == "clarification"
    assert meaning.question_meaning == "推荐清爽防晒"


def test_single_call_provider_failure_fails_closed() -> None:
    semantic = FakeTurnMeaningPort(fail=True)
    understanding = SingleCallUnderstanding(
        semantic=semantic,
        concept_catalog=_concept_catalog(),
    )

    result = understanding.translate(
        "推荐清爽防晒",
        context=_context(),
    )

    assert semantic.calls == 1
    assert result.operation_hint == "clarification"


def test_exact_only_translation_returns_fallback_turn_meaning() -> None:
    understanding = ExactOnlyTextUnderstanding()

    result = understanding.translate(
        "后来改选洁面！！！",
        context=_context(),
    )

    assert type(result) is TurnMeaning
    assert result.operation_hint == "clarification"
