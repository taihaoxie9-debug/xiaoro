from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from app.guide_runtime.llm_config import (
    GuideLlmConfig,
    GuideLlmConfigError,
    GuideLlmConfigErrorCode,
)


_GUIDE_LLM_ENVIRONMENT = (
    "GUIDE_LLM_API_KEY",
    "GUIDE_LLM_BASE_URL",
    "GUIDE_LLM_MODEL",
    "GUIDE_LLM_TIMEOUT_SECONDS",
    "GUIDE_LLM_MAX_TOKENS",
    "GUIDE_LLM_DAILY_BUDGET_CNY",
    "GUIDE_LLM_DAILY_CALL_CAP",
    "GUIDE_LLM_FORMAT_REPAIR_ATTEMPTS",
)
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _clear_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _GUIDE_LLM_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)


def test_production_configuration_has_no_legacy_router_switch() -> None:
    source = (
        _REPO_ROOT / "app" / "guide_runtime" / "llm_config.py"
    ).read_text(encoding="utf-8")

    assert "GUIDE_UNIFIED_ROUTER_ENABLED" not in source
    assert "GuideRuntimeFlags" not in source


def test_default_configuration_is_disabled_and_model_unselected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_environment(monkeypatch)

    config = GuideLlmConfig.from_environment()

    assert config.api_key is None
    assert config.model is None
    assert config.base_url == "https://api.siliconflow.cn/v1"
    assert config.timeout_seconds == 12.0
    assert config.max_tokens == 1024
    assert config.enable_thinking is False
    assert config.daily_budget_cny == Decimal("1.00")
    assert config.daily_call_cap == 200
    assert config.format_repair_attempts == 0
    assert not config.is_ready


def test_configuration_reads_only_guide_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_environment(monkeypatch)
    monkeypatch.setenv("SILICONFLOW_API_KEY", "legacy-key-must-be-ignored")
    monkeypatch.setenv("GUIDE_LLM_API_KEY", " current-test-key ")
    monkeypatch.setenv("GUIDE_LLM_BASE_URL", "https://llm.example/v1/")
    monkeypatch.setenv("GUIDE_LLM_MODEL", "provider/model-a")
    monkeypatch.setenv("GUIDE_LLM_TIMEOUT_SECONDS", "2.5")
    monkeypatch.setenv("GUIDE_LLM_MAX_TOKENS", "128")
    monkeypatch.setenv("GUIDE_LLM_DAILY_BUDGET_CNY", "2.75")
    monkeypatch.setenv("GUIDE_LLM_DAILY_CALL_CAP", "17")
    monkeypatch.setenv("GUIDE_LLM_FORMAT_REPAIR_ATTEMPTS", "0")

    config = GuideLlmConfig.from_environment().require_ready()

    assert config.api_key == "current-test-key"
    assert config.base_url == "https://llm.example/v1"
    assert config.model == "provider/model-a"
    assert config.timeout_seconds == 2.5
    assert config.max_tokens == 128
    assert config.enable_thinking is False
    assert config.daily_budget_cny == Decimal("2.75")
    assert config.daily_call_cap == 17
    assert config.format_repair_attempts == 0
    assert config.is_ready
    assert "current-test-key" not in repr(config)
    assert "legacy-key-must-be-ignored" not in repr(config)


@pytest.mark.parametrize(
    ("environment", "code"),
    (
        (
            {"GUIDE_LLM_BASE_URL": "http://api.example/v1"},
            GuideLlmConfigErrorCode.INVALID_BASE_URL,
        ),
        (
            {"GUIDE_LLM_BASE_URL": "https://user:pass@api.example/v1"},
            GuideLlmConfigErrorCode.INVALID_BASE_URL,
        ),
        (
            {"GUIDE_LLM_BASE_URL": "https://api.example/v1?secret=value"},
            GuideLlmConfigErrorCode.INVALID_BASE_URL,
        ),
        (
            {"GUIDE_LLM_MODEL": "   "},
            GuideLlmConfigErrorCode.INVALID_MODEL,
        ),
        (
            {"GUIDE_LLM_TIMEOUT_SECONDS": "nan"},
            GuideLlmConfigErrorCode.INVALID_TIMEOUT,
        ),
        (
            {"GUIDE_LLM_TIMEOUT_SECONDS": "0.49"},
            GuideLlmConfigErrorCode.INVALID_TIMEOUT,
        ),
        (
            {"GUIDE_LLM_TIMEOUT_SECONDS": "30.01"},
            GuideLlmConfigErrorCode.INVALID_TIMEOUT,
        ),
        (
            {"GUIDE_LLM_MAX_TOKENS": "63"},
            GuideLlmConfigErrorCode.INVALID_MAX_TOKENS,
        ),
        (
            {"GUIDE_LLM_MAX_TOKENS": "2049"},
            GuideLlmConfigErrorCode.INVALID_MAX_TOKENS,
        ),
        (
            {"GUIDE_LLM_DAILY_BUDGET_CNY": "0"},
            GuideLlmConfigErrorCode.INVALID_DAILY_BUDGET,
        ),
        (
            {"GUIDE_LLM_DAILY_BUDGET_CNY": "Infinity"},
            GuideLlmConfigErrorCode.INVALID_DAILY_BUDGET,
        ),
        (
            {"GUIDE_LLM_DAILY_CALL_CAP": "0"},
            GuideLlmConfigErrorCode.INVALID_DAILY_CALL_CAP,
        ),
        (
            {"GUIDE_LLM_FORMAT_REPAIR_ATTEMPTS": "2"},
            GuideLlmConfigErrorCode.INVALID_FORMAT_REPAIR_ATTEMPTS,
        ),
    ),
)
def test_invalid_environment_fails_closed_without_echoing_values(
    monkeypatch: pytest.MonkeyPatch,
    environment: dict[str, str],
    code: GuideLlmConfigErrorCode,
) -> None:
    _clear_environment(monkeypatch)
    secret = "configuration-test-secret"
    monkeypatch.setenv("GUIDE_LLM_API_KEY", secret)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(GuideLlmConfigError) as caught:
        GuideLlmConfig.from_environment()

    assert caught.value.code is code
    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)
    assert all(value not in str(caught.value) for value in environment.values())


def test_require_ready_fails_closed_for_absent_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_environment(monkeypatch)
    config = GuideLlmConfig.from_environment()

    with pytest.raises(GuideLlmConfigError) as caught:
        config.require_ready()

    assert caught.value.code is GuideLlmConfigErrorCode.API_KEY_MISSING


def test_runtime_requirements_pin_httpx_for_intent_adapter() -> None:
    requirements = {
        line.strip()
        for line in (
            _REPO_ROOT / "requirements-guide-runtime.txt"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "httpx==0.27.2" in requirements
