from __future__ import annotations

from pathlib import Path

import pytest

from app.guide.adapters.llm.deepseek_turn_meaning import (
    DeepSeekTurnMeaningAdapter,
)
from app.guide.adapters.llm.siliconflow_turn_meaning import (
    SiliconFlowTurnMeaningAdapter,
)
from app.guide.application.contracts import UserTurn
from app.guide.understanding.contracts import (
    TopicCode,
    UnderstandingGoal,
)
from app.guide.understanding.parallel_understanding import (
    ParallelUnderstanding,
)
from app.guide.understanding.single_call_understanding import (
    SingleCallUnderstanding,
)
from app.guide.understanding.semantic_contracts import (
    SemanticContext,
    SemanticGoal,
    SemanticIntentProposal,
)
from app.guide.understanding.text_understanding import (
    ExactOnlyTextUnderstanding,
)
from app.guide_runtime.composition import (
    build_consultation_vertical_runtime,
    build_runtime_orchestrator,
    build_text_understanding,
)
from app.guide_runtime.llm_config import (
    GuideLlmConfigError,
    GuideLlmConfigErrorCode,
)


class FakeSemanticPort:
    def __init__(self, topic: TopicCode) -> None:
        self.topic = topic
        self.calls = 0

    def propose(
        self,
        message: str,
        context: SemanticContext,
    ) -> SemanticIntentProposal:
        del message, context
        self.calls += 1
        return SemanticIntentProposal(
            goal=SemanticGoal.RECOMMENDATION,
            topic=self.topic,
            concerns=(),
            observations=(),
            references=(),
            confidence=0.99,
            clarification_hint=None,
        )


def _turn(message: str, *, version: int = 0) -> UserTurn:
    return UserTurn(
        session_id="composition-understanding",
        message=message,
        image_bundle_id=None,
        conversation_version=version,
    )


def test_build_text_understanding_without_key_fails_closed_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GUIDE_LLM_API_KEY", raising=False)

    understanding = build_text_understanding()

    assert isinstance(understanding, ExactOnlyTextUnderstanding)
    result = understanding.understand(
        "500 内适合油敏肌的防晒",
        context=SemanticContext(
            conversation_version=0,
            active_topic=None,
            visible_candidate_count=0,
            confirmed_profile_fields=(),
        ),
    )
    assert result.topic is TopicCode.SUNSCREEN
    assert result.goal is UnderstandingGoal.CLARIFICATION
    assert result.uncertainties
    assert any(
        trace.resolution == "semantic_unavailable"
        for trace in result.signal_trace
    )


def test_build_text_understanding_without_key_allows_closed_exact_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GUIDE_LLM_API_KEY", raising=False)
    understanding = build_text_understanding()

    result = understanding.understand(
        "后来改选洁面！！！",
        context=SemanticContext(
            conversation_version=0,
            active_topic=None,
            visible_candidate_count=0,
            confirmed_profile_fields=(),
        ),
        semantic_required=False,
    )

    assert result.topic is TopicCode.CLEANSER
    assert result.goal is UnderstandingGoal.RECOMMENDATION
    assert result.uncertainties == []
    assert any(
        trace.resolution == "semantic_skipped_by_contract"
        for trace in result.signal_trace
    )


def test_build_text_understanding_with_injected_semantic_port_is_parallel(
    tmp_path: Path,
) -> None:
    semantic = FakeSemanticPort(TopicCode.FRAGRANCE)

    understanding = build_text_understanding(
        semantic_intent=semantic,
        state_dir=tmp_path / "cache-state",
    )

    assert isinstance(understanding, ParallelUnderstanding)
    assert understanding._semantic is semantic
    result = understanding.understand(
        "夏天涂的味道好闻的东西",
        context=SemanticContext(
            conversation_version=0,
            active_topic=None,
            visible_candidate_count=0,
            confirmed_profile_fields=(),
        ),
    )
    assert result.topic is TopicCode.FRAGRANCE
    assert semantic.calls == 1


def test_key_without_selected_model_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "GUIDE_LLM_API_KEY",
        "composition-test-key-not-a-real-secret",
    )
    monkeypatch.delenv("GUIDE_LLM_MODEL", raising=False)

    with pytest.raises(GuideLlmConfigError) as caught:
        build_text_understanding()

    assert caught.value.code is GuideLlmConfigErrorCode.MODEL_UNSELECTED
    assert "composition-test-key-not-a-real-secret" not in str(caught.value)


def test_explicit_semantic_port_needs_no_fabricated_model_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("GUIDE_LLM_API_KEY", raising=False)
    monkeypatch.delenv("GUIDE_LLM_MODEL", raising=False)
    semantic = FakeSemanticPort(TopicCode.FRAGRANCE)

    understanding = build_text_understanding(
        semantic_intent=semantic,
        state_dir=tmp_path / "cache-state",
    )

    assert isinstance(understanding, ParallelUnderstanding)
    assert understanding._semantic is semantic
    source = (
        Path(__file__).resolve().parents[3]
        / "app"
        / "guide_runtime"
        / "composition.py"
    ).read_text(encoding="utf-8")
    assert "guide-semantic-fake" not in source


def test_ready_config_builds_single_call_turn_meaning_adapter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(
        "GUIDE_LLM_API_KEY",
        "composition-test-key-not-a-real-secret",
    )
    monkeypatch.setenv(
        "GUIDE_LLM_MODEL",
        "deepseek-ai/DeepSeek-V3.2",
    )
    monkeypatch.setenv("GUIDE_LLM_FORMAT_REPAIR_ATTEMPTS", "0")
    state_root = tmp_path / "cache-state"

    understanding = build_text_understanding(state_dir=state_root)

    assert isinstance(understanding, SingleCallUnderstanding)
    assert isinstance(
        understanding._semantic,
        SiliconFlowTurnMeaningAdapter,
    )
    assert not (state_root / "intent_cache.sqlite3").exists()


def test_official_deepseek_config_builds_deepseek_turn_meaning_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "GUIDE_LLM_API_KEY",
        "composition-test-key-not-a-real-secret",
    )
    monkeypatch.setenv(
        "GUIDE_LLM_BASE_URL",
        "https://api.deepseek.com",
    )
    monkeypatch.setenv("GUIDE_LLM_MODEL", "deepseek-v4-pro")
    monkeypatch.setenv("GUIDE_LLM_FORMAT_REPAIR_ATTEMPTS", "0")

    understanding = build_text_understanding()

    assert isinstance(understanding, SingleCallUnderstanding)
    assert isinstance(
        understanding._semantic,
        DeepSeekTurnMeaningAdapter,
    )
    understanding._semantic.close()


def test_consultation_recommendation_uses_injected_parallel_understanding(
    tmp_path: Path,
) -> None:
    semantic = FakeSemanticPort(TopicCode.FRAGRANCE)

    runtime = build_consultation_vertical_runtime(
        state_dir=tmp_path / "consultation-state",
        semantic_intent=semantic,
    )

    assert isinstance(
        runtime.recommendation._understanding,
        ParallelUnderstanding,
    )
    events = list(
        runtime.recommendation.stream(
            UserTurn(
                session_id="consultation-semantic-recommendation",
                message="夏天闻起来清爽的东西",
                profile_owner=runtime.profile_owner(
                    "consultation-semantic-recommendation"
                ),
                image_bundle_id=None,
                conversation_version=0,
            )
        )
    )
    intent = next(event for event in events if event.event == "intent")
    assert intent.data.mode == "recommend"
    assert intent.data.category_profile.value == "fragrance"
    assert semantic.calls == 1


def test_runtime_orchestrator_accepts_injected_semantic_port_offline(
    tmp_path: Path,
) -> None:
    semantic = FakeSemanticPort(TopicCode.FRAGRANCE)

    orchestrator = build_runtime_orchestrator(
        state_dir=tmp_path / "runtime-state",
        semantic_intent=semantic,
    )
    events = list(
        orchestrator.stream(_turn("夏天涂的味道好闻的东西"))
    )

    intent = next(event for event in events if event.event == "intent")
    assert intent.data.mode == "recommend"
    assert intent.data.category_profile.value == "fragrance"
    assert semantic.calls >= 1


def test_composition_has_no_legacy_semantic_or_cache_dependencies() -> None:
    source = (
        Path(__file__).resolve().parents[3]
        / "app"
        / "guide_runtime"
        / "composition.py"
    ).read_text(encoding="utf-8")
    assert "app.services" not in source
    assert "SiliconFlowIntentAdapter" not in source
    assert "INTENT_PROMPT_VERSION" not in source
    assert "_build_intent_cache" not in source
    assert "TwoStageCachedSemanticPort" not in source
