from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal

import httpx

from app.guide.adapters.llm.deepseek_intent import (
    DEEPSEEK_OFFICIAL_BASE_URL,
)
from app.guide.adapters.llm.provider_common import UsageLimiter
from app.guide.adapters.llm.presentation_copywriter_adapter import (
    PresentationCopywriterAdapterBase,
)


class DeepSeekPresentationCopywriterAdapter(
    PresentationCopywriterAdapterBase
):
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        max_tokens: int,
        temperature: float,
        daily_budget_cny: Decimal = Decimal("2.00"),
        daily_call_cap: int = 200,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        usage_limiter: UsageLimiter | None = None,
    ) -> None:
        super().__init__(
            provider="deepseek_official",
            api_key=api_key,
            base_url=DEEPSEEK_OFFICIAL_BASE_URL,
            model=model,
            timeout_seconds=timeout_seconds,
            max_tokens=max_tokens,
            temperature=temperature,
            daily_budget_cny=daily_budget_cny,
            daily_call_cap=daily_call_cap,
            transport=transport,
            clock=clock,
            usage_limiter=usage_limiter,
        )

    def _request_body(
        self,
        messages: tuple[dict[str, str], dict[str, str]],
    ) -> Mapping[str, object]:
        return {
            **self._base_request_body(messages),
            "thinking": {"type": "disabled"},
        }


__all__ = ["DeepSeekPresentationCopywriterAdapter"]
