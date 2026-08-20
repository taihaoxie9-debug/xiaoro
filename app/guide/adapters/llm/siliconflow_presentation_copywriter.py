from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime

import httpx

from app.guide.adapters.llm.presentation_copywriter_adapter import (
    PresentationCopywriterAdapterBase,
)
from app.guide_runtime.copywriter_config import CopywriterLlmConfig


class SiliconFlowPresentationCopywriterAdapter(
    PresentationCopywriterAdapterBase
):
    @classmethod
    def from_config(
        cls,
        config: CopywriterLlmConfig,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> SiliconFlowPresentationCopywriterAdapter:
        ready = config.require_ready()
        api_key = ready.api_key
        model = ready.model
        if api_key is None or model is None:
            raise AssertionError(
                "ready copywriter configuration is incomplete"
            )
        return cls(
            api_key=api_key,
            base_url=ready.base_url,
            model=model,
            timeout_seconds=ready.timeout_seconds,
            max_tokens=ready.max_tokens,
            temperature=ready.temperature,
            daily_budget_cny=ready.daily_budget_cny,
            daily_call_cap=ready.daily_call_cap,
            transport=transport,
            clock=clock,
        )

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        max_tokens: int,
        temperature: float,
        daily_budget_cny,
        daily_call_cap: int,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        super().__init__(
            provider="siliconflow",
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout_seconds=timeout_seconds,
            max_tokens=max_tokens,
            temperature=temperature,
            daily_budget_cny=daily_budget_cny,
            daily_call_cap=daily_call_cap,
            transport=transport,
            clock=clock,
        )

    def _request_body(
        self,
        messages: tuple[dict[str, str], dict[str, str]],
    ) -> Mapping[str, object]:
        return {
            **self._base_request_body(messages),
            "enable_thinking": False,
        }


__all__ = ["SiliconFlowPresentationCopywriterAdapter"]
