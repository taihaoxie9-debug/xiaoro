from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from multiprocessing import get_context
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

from app.guide.adapters.llm import provider_common
from app.guide.adapters.llm.contracts import (
    SemanticProviderFailure,
    SemanticProviderFailureCode,
)
from app.guide.adapters.llm.provider_common import (
    DailyUsageLimiter,
    OpenAIJsonClient,
)
from app.guide.adapters.llm.siliconflow_turn_meaning import (
    SiliconFlowTurnMeaningAdapter,
)
from app.guide_runtime.composition import (
    build_presentation_copywriter,
    build_text_understanding,
)
from app.guide_runtime.copywriter_config import (
    CopywriterConfigError,
    CopywriterConfigErrorCode,
)
from app.guide_runtime.llm_config import (
    GuideLlmConfig,
    GuideLlmConfigError,
    GuideLlmConfigErrorCode,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
FIXED_NOW = datetime(2026, 8, 27, 12, tzinfo=UTC)


def _reserve_shared_quota(
    state_root: str,
    start: Any,
    ready: Any,
    results: Any,
) -> None:
    limiter_class = getattr(
        provider_common,
        "SqliteDailyUsageLimiter",
        None,
    )
    if limiter_class is None:
        results.put("sqlite_limiter_missing")
        return
    limiter = limiter_class(
        Path(state_root) / "provider_quota.sqlite3",
        trusted_state_root=state_root,
        provider="siliconflow",
        daily_budget_cny=Decimal("1.00"),
        daily_call_cap=2,
        clock=lambda: FIXED_NOW,
    )
    ready.put(True)
    if not start.wait(timeout=5):
        raise RuntimeError("provider quota start barrier timed out")
    try:
        reservation = limiter.reserve()
        limiter.record_actual_cost(reservation, Decimal("0.10"))
    except SemanticProviderFailure as error:
        results.put(error.code.value)
    else:
        results.put("reserved")


@pytest.mark.parametrize(
    ("environment", "code"),
    (
        (
            {"GUIDE_LLM_API_KEY": "partial-provider-key"},
            GuideLlmConfigErrorCode.MODEL_UNSELECTED,
        ),
        (
            {"GUIDE_LLM_MODEL": "provider/model"},
            GuideLlmConfigErrorCode.API_KEY_MISSING,
        ),
    ),
)
def test_partial_turn_meaning_configuration_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    environment: dict[str, str],
    code: GuideLlmConfigErrorCode,
) -> None:
    monkeypatch.delenv("GUIDE_LLM_API_KEY", raising=False)
    monkeypatch.delenv("GUIDE_LLM_MODEL", raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(GuideLlmConfigError) as caught:
        build_text_understanding()

    assert caught.value.code is code
    assert "partial-provider-key" not in str(caught.value)


@pytest.mark.parametrize(
    ("environment", "code"),
    (
        (
            {"GUIDE_COPY_LLM_API_KEY": "partial-copy-key"},
            CopywriterConfigErrorCode.MODEL_UNSELECTED,
        ),
        (
            {"GUIDE_COPY_LLM_MODEL": "provider/copy-model"},
            CopywriterConfigErrorCode.API_KEY_MISSING,
        ),
    ),
)
def test_partial_copywriter_configuration_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    environment: dict[str, str],
    code: CopywriterConfigErrorCode,
) -> None:
    monkeypatch.delenv("GUIDE_COPY_LLM_API_KEY", raising=False)
    monkeypatch.delenv("GUIDE_COPY_LLM_MODEL", raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(CopywriterConfigError) as caught:
        build_presentation_copywriter()

    assert caught.value.code is code
    assert "partial-copy-key" not in str(caught.value)


def test_provider_quota_is_shared_across_processes_and_restarts(
    tmp_path: Path,
) -> None:
    limiter_class = getattr(
        provider_common,
        "SqliteDailyUsageLimiter",
        None,
    )
    assert limiter_class is not None
    state_root = tmp_path / "guide-state"
    context = get_context("spawn")
    start = context.Event()
    ready = context.Queue()
    results = context.Queue()
    processes = [
        context.Process(
            target=_reserve_shared_quota,
            args=(str(state_root), start, ready, results),
        )
        for _ in range(4)
    ]

    try:
        for process in processes:
            process.start()
        for _ in processes:
            assert ready.get(timeout=10) is True
        start.set()
        outcomes = [results.get(timeout=10) for _ in processes]
    finally:
        start.set()
        for process in processes:
            process.join(timeout=10)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        ready.close()
        ready.join_thread()
        results.close()
        results.join_thread()

    assert [process.exitcode for process in processes] == [0, 0, 0, 0]
    assert outcomes.count("reserved") == 2
    assert outcomes.count(
        SemanticProviderFailureCode.DAILY_CALL_CAP_EXCEEDED.value
    ) == 2

    restarted = limiter_class(
        state_root / "provider_quota.sqlite3",
        trusted_state_root=state_root,
        provider="siliconflow",
        daily_budget_cny=Decimal("1.00"),
        daily_call_cap=2,
        clock=lambda: FIXED_NOW,
    )
    with pytest.raises(SemanticProviderFailure) as caught:
        restarted.reserve()
    assert (
        caught.value.code
        is SemanticProviderFailureCode.DAILY_CALL_CAP_EXCEEDED
    )

    other_provider = limiter_class(
        state_root / "provider_quota.sqlite3",
        trusted_state_root=state_root,
        provider="deepseek_official",
        daily_budget_cny=Decimal("1.00"),
        daily_call_cap=2,
        clock=lambda: FIXED_NOW,
    )
    reservation = other_provider.reserve()
    other_provider.record_actual_cost(reservation, Decimal("0.10"))


def test_runtime_provider_uses_persistent_quota_and_retains_in_memory_injection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    limiter_class = getattr(
        provider_common,
        "SqliteDailyUsageLimiter",
        None,
    )
    assert limiter_class is not None
    monkeypatch.setenv("GUIDE_LLM_API_KEY", "runtime-provider-key")
    monkeypatch.setenv("GUIDE_LLM_MODEL", "provider/model")
    understanding = build_text_understanding(state_dir=tmp_path)

    assert isinstance(
        understanding._semantic._usage_limiter,
        limiter_class,
    )
    assert (
        understanding._semantic._usage_limiter.database_path
        == tmp_path / "provider_quota.sqlite3"
    )

    in_memory = DailyUsageLimiter(
        daily_budget_cny=Decimal("1.00"),
        daily_call_cap=2,
        clock=lambda: FIXED_NOW,
    )
    adapter = SiliconFlowTurnMeaningAdapter.from_config(
        GuideLlmConfig.from_environment(),
        concept_catalog=("texture.refreshing",),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503)
        ),
        usage_limiter=in_memory,
    )
    assert adapter._usage_limiter is in_memory
    adapter.close()


def test_provider_response_body_limit_fails_closed() -> None:
    oversized_body = (
        b'{"choices":[{"message":{"content":"'
        + (b"x" * (64 * 1024))
        + b'"}}]}'
    )
    client = OpenAIJsonClient(
        api_key="not-a-real-key",
        base_url="https://provider.example/v1",
        timeout_seconds=2.0,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=oversized_body,
                headers={"content-type": "application/json"},
            )
        ),
    )

    with pytest.raises(SemanticProviderFailure) as caught:
        client.request({"model": "provider/model"})

    assert caught.value.code is SemanticProviderFailureCode.INVALID_RESPONSE
    assert caught.value.raw_content is None
    client.close()


def test_production_deployment_has_one_capacity_managed_image_model_owner() -> None:
    compose = yaml.safe_load(
        (REPO_ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    )
    app = compose["services"]["app"]
    command = app["command"]
    environment = {
        key: value
        for item in app["environment"]
        for key, value in [item.split("=", 1)]
    }

    assert command.count("--workers") == 1
    assert command.endswith("--workers 1")
    assert app["deploy"]["replicas"] == 1
    assert app["deploy"]["resources"]["limits"]["memory"] == "3G"
    assert app["deploy"]["resources"]["reservations"]["memory"] == "2G"
    assert environment["XIAORO_GUIDE_STATE_DIR"] == (
        "/var/lib/xiaoro/guide-state"
    )
    assert environment["XIAORO_IMAGE_INFERENCE_LOCK_DIR"] == (
        "/var/lib/xiaoro/guide-state/image-inference-locks"
    )
    assert "guide_state:/var/lib/xiaoro/guide-state" in app["volumes"]
    assert "guide_state" in compose["volumes"]
