from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.guide.adapters.llm.deepseek_turn_meaning import (
    DeepSeekTurnMeaningAdapter,
)
from app.guide.adapters.llm.siliconflow_turn_meaning import (
    SiliconFlowTurnMeaningAdapter,
)
from app.guide.application.contracts import TurnIdentity, UserTurn
from app.guide.understanding.contracts import (
    TopicCode,
    UnderstandingGoal,
)
from app.guide.understanding.single_call_understanding import (
    SingleCallUnderstanding,
)
from app.guide.understanding.semantic_contracts import (
    SemanticContext,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning
from app.guide.understanding.text_understanding import (
    ExactOnlyTextUnderstanding,
)
from app.guide_runtime.composition import (
    build_consultation_vertical_runtime,
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
    ) -> TurnMeaning:
        del context
        self.calls += 1
        return TurnMeaning(
            operation_hint="recommendation",
            recommendation_mode="explore",
            recommendation_count=None,
            recommendation_mode_basis={
                "basis": "broad_exploration",
                "source_text": message,
            },
            topic_hint=self.topic.value,
            continuity_hint="new_task",
            subject_scope_hint="self",
            question_meaning=message,
            safety_language="ordinary",
        )


def _turn(message: str, *, version: int = 0) -> UserTurn:
    session_id = "composition-understanding"
    return UserTurn(
        identity=TurnIdentity(
            session_id=session_id,
            request_id=f"request_{session_id}_{version:04d}",
            turn_id=f"turn_{session_id}_{version:04d}",
        ),
        session_id=session_id,
        message=message,
        image_bundle_id=None,
        conversation_version=version,
    )


def _events(frames) -> list[tuple[str, dict]]:
    events = []
    for frame in frames:
        lines = frame.decode("utf-8").splitlines()
        name = next(
            line.removeprefix("event: ")
            for line in lines
            if line.startswith("event: ")
        )
        payload = "".join(
            line.removeprefix("data: ")
            for line in lines
            if line.startswith("data: ")
        )
        events.append((name, json.loads(payload)))
    return events


def test_build_text_understanding_without_key_fails_closed_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GUIDE_LLM_API_KEY", raising=False)

    understanding = build_text_understanding()

    assert isinstance(understanding, ExactOnlyTextUnderstanding)
    result = understanding.translate(
        "500 内适合油敏肌的防晒",
        context=SemanticContext(
            conversation_version=0,
            active_topic=None,
            visible_candidate_count=0,
            confirmed_profile_fields=(),
        ),
    )
    assert type(result) is TurnMeaning
    assert result.operation_hint == "clarification"
    assert result.topic_hint is None


def test_build_text_understanding_without_key_returns_fallback_meaning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GUIDE_LLM_API_KEY", raising=False)
    understanding = build_text_understanding()

    result = understanding.translate(
        "后来改选洁面！！！",
        context=SemanticContext(
            conversation_version=0,
            active_topic=None,
            visible_candidate_count=0,
            confirmed_profile_fields=(),
        ),
    )

    assert type(result) is TurnMeaning
    assert result.operation_hint == "clarification"
    assert result.topic_hint is None


def test_build_text_understanding_with_injected_turn_meaning_port_is_single_call(
    tmp_path: Path,
) -> None:
    semantic = FakeSemanticPort(TopicCode.FRAGRANCE)

    understanding = build_text_understanding(
        semantic_intent=semantic,
        state_dir=tmp_path / "cache-state",
    )

    assert isinstance(understanding, SingleCallUnderstanding)
    assert understanding._semantic is semantic
    result = understanding.translate(
        "夏天涂的味道好闻的东西",
        context=SemanticContext(
            conversation_version=0,
            active_topic=None,
            visible_candidate_count=0,
            confirmed_profile_fields=(),
        ),
    )
    assert type(result) is TurnMeaning
    assert result.topic_hint == TopicCode.FRAGRANCE.value
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

    assert isinstance(understanding, SingleCallUnderstanding)
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


def test_consultation_runtime_uses_injected_single_call_understanding(
    tmp_path: Path,
) -> None:
    semantic = FakeSemanticPort(TopicCode.FRAGRANCE)

    runtime = build_consultation_vertical_runtime(
        state_dir=tmp_path / "consultation-state",
        semantic_intent=semantic,
    )

    assert isinstance(
        runtime.unified._understanding._understanding,
        SingleCallUnderstanding,
    )
    session_id = "consultation-semantic-recommendation"
    events = _events(
        runtime.unified.stream(
            UserTurn(
                identity=TurnIdentity(
                    session_id=session_id,
                    request_id=f"request_{session_id}_0000",
                    turn_id=f"turn_{session_id}_0000",
                ),
                session_id=session_id,
                message="夏天闻起来清爽的东西",
                profile_owner=runtime.profile_owner(session_id),
                image_bundle_id=None,
                conversation_version=0,
            )
        )
    )
    intent = next(data for name, data in events if name == "intent")
    assert intent["intent"] == "recommend"
    assert intent["category_profile"] == "fragrance"
    assert semantic.calls == 1


def test_unified_runtime_accepts_injected_turn_meaning_port_offline(
    tmp_path: Path,
) -> None:
    semantic = FakeSemanticPort(TopicCode.FRAGRANCE)

    runtime = build_consultation_vertical_runtime(
        state_dir=tmp_path / "runtime-state",
        semantic_intent=semantic,
    )
    events = _events(
        runtime.unified.stream(_turn("夏天涂的味道好闻的东西"))
    )

    intent = next(data for name, data in events if name == "intent")
    assert intent["intent"] == "recommend"
    assert intent["category_profile"] == "fragrance"
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
