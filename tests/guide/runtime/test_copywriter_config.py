from __future__ import annotations

from decimal import Decimal

import pytest

from app.guide_runtime.copywriter_config import (
    CopywriterConfigError,
    CopywriterConfigErrorCode,
    CopywriterLlmConfig,
)


ENVIRONMENT = (
    "GUIDE_COPY_LLM_API_KEY",
    "GUIDE_COPY_LLM_BASE_URL",
    "GUIDE_COPY_LLM_MODEL",
    "GUIDE_COPY_LLM_TIMEOUT_SECONDS",
    "GUIDE_COPY_LLM_MAX_TOKENS",
    "GUIDE_COPY_LLM_TEMPERATURE",
    "GUIDE_COPY_LLM_DAILY_BUDGET_CNY",
    "GUIDE_COPY_LLM_DAILY_CALL_CAP",
)


def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)


def test_copywriter_defaults_to_explicit_deterministic_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear(monkeypatch)

    config = CopywriterLlmConfig.from_environment()

    assert config.api_key is None
    assert config.model is None
    assert config.base_url == "https://api.siliconflow.cn/v1"
    assert config.timeout_seconds == 15.0
    assert config.max_tokens == 1536
    assert config.temperature == 0.3
    assert config.daily_budget_cny == Decimal("2.00")
    assert config.daily_call_cap == 200
    assert not config.is_ready


def test_copywriter_reads_only_its_own_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("GUIDE_LLM_API_KEY", "translator-key")
    monkeypatch.setenv("GUIDE_LLM_MODEL", "translator-model")
    monkeypatch.setenv("GUIDE_COPY_LLM_API_KEY", " copy-key ")
    monkeypatch.setenv(
        "GUIDE_COPY_LLM_BASE_URL",
        "https://copy.example/v1/",
    )
    monkeypatch.setenv("GUIDE_COPY_LLM_MODEL", "provider/copy-model")
    monkeypatch.setenv("GUIDE_COPY_LLM_TIMEOUT_SECONDS", "4")
    monkeypatch.setenv("GUIDE_COPY_LLM_MAX_TOKENS", "400")
    monkeypatch.setenv("GUIDE_COPY_LLM_TEMPERATURE", "0.45")
    monkeypatch.setenv("GUIDE_COPY_LLM_DAILY_BUDGET_CNY", "3.5")
    monkeypatch.setenv("GUIDE_COPY_LLM_DAILY_CALL_CAP", "17")

    config = CopywriterLlmConfig.from_environment().require_ready()

    assert config.api_key == "copy-key"
    assert config.model == "provider/copy-model"
    assert config.base_url == "https://copy.example/v1"
    assert config.timeout_seconds == 4.0
    assert config.max_tokens == 400
    assert config.temperature == 0.45
    assert config.daily_budget_cny == Decimal("3.5")
    assert config.daily_call_cap == 17
    assert "copy-key" not in repr(config)
    assert "translator-key" not in repr(config)


@pytest.mark.parametrize(
    ("name", "value", "code"),
    [
        (
            "GUIDE_COPY_LLM_BASE_URL",
            "http://copy.example/v1",
            CopywriterConfigErrorCode.INVALID_BASE_URL,
        ),
        (
            "GUIDE_COPY_LLM_MAX_TOKENS",
            "4097",
            CopywriterConfigErrorCode.INVALID_MAX_TOKENS,
        ),
        (
            "GUIDE_COPY_LLM_TEMPERATURE",
            "1.01",
            CopywriterConfigErrorCode.INVALID_TEMPERATURE,
        ),
        (
            "GUIDE_COPY_LLM_DAILY_CALL_CAP",
            "0",
            CopywriterConfigErrorCode.INVALID_DAILY_CALL_CAP,
        ),
    ],
)
def test_invalid_copywriter_environment_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
    code: CopywriterConfigErrorCode,
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("GUIDE_COPY_LLM_API_KEY", "secret-copy-key")
    monkeypatch.setenv(name, value)

    with pytest.raises(CopywriterConfigError) as caught:
        CopywriterLlmConfig.from_environment()

    assert caught.value.code is code
    assert "secret-copy-key" not in str(caught.value)
    assert value not in str(caught.value)


def test_require_ready_rejects_half_configured_copywriter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("GUIDE_COPY_LLM_API_KEY", "secret-copy-key")
    config = CopywriterLlmConfig.from_environment()

    with pytest.raises(CopywriterConfigError) as caught:
        config.require_ready()

    assert caught.value.code is CopywriterConfigErrorCode.MODEL_UNSELECTED
