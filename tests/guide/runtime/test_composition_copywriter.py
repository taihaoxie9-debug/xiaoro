from __future__ import annotations

from app.guide.adapters.llm.deepseek_presentation_copywriter import (
    DeepSeekPresentationCopywriterAdapter,
)
from app.guide.adapters.llm.siliconflow_presentation_copywriter import (
    SiliconFlowPresentationCopywriterAdapter,
)
from app.guide_runtime.composition import build_presentation_copywriter


COPY_ENV = (
    "GUIDE_COPY_LLM_API_KEY",
    "GUIDE_COPY_LLM_BASE_URL",
    "GUIDE_COPY_LLM_MODEL",
    "GUIDE_COPY_LLM_TIMEOUT_SECONDS",
    "GUIDE_COPY_LLM_MAX_TOKENS",
    "GUIDE_COPY_LLM_TEMPERATURE",
    "GUIDE_COPY_LLM_DAILY_BUDGET_CNY",
    "GUIDE_COPY_LLM_DAILY_CALL_CAP",
)


def _clear(monkeypatch) -> None:
    for name in COPY_ENV:
        monkeypatch.delenv(name, raising=False)


def test_missing_copywriter_config_builds_explicit_disabled_port(
    monkeypatch,
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("GUIDE_LLM_API_KEY", "translator-only-key")
    monkeypatch.setenv("GUIDE_LLM_MODEL", "translator-model")

    assert build_presentation_copywriter() is None


def test_siliconflow_copywriter_uses_independent_configuration(
    monkeypatch,
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("GUIDE_COPY_LLM_API_KEY", "copy-key")
    monkeypatch.setenv(
        "GUIDE_COPY_LLM_MODEL",
        "provider/copy-model",
    )

    copywriter = build_presentation_copywriter()

    assert isinstance(
        copywriter,
        SiliconFlowPresentationCopywriterAdapter,
    )
    assert copywriter.model == "provider/copy-model"
    copywriter.close()


def test_deepseek_copywriter_selected_by_official_base_url(
    monkeypatch,
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("GUIDE_COPY_LLM_API_KEY", "copy-key")
    monkeypatch.setenv(
        "GUIDE_COPY_LLM_BASE_URL",
        "https://api.deepseek.com",
    )
    monkeypatch.setenv("GUIDE_COPY_LLM_MODEL", "deepseek-chat")

    copywriter = build_presentation_copywriter()

    assert isinstance(
        copywriter,
        DeepSeekPresentationCopywriterAdapter,
    )
    assert copywriter.model == "deepseek-chat"
    copywriter.close()
