from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
import json
import logging
import math
from time import perf_counter
from typing import Protocol, Self

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.guide.adapters.llm.contracts import (
    SemanticProviderFailure,
    SemanticProviderFailureCode,
    SemanticTokenUsage,
)
from app.guide.adapters.llm.provider_common import (
    DailyUsageLimiter,
    OpenAIJsonClient,
    validate_adapter_settings,
    validation_failure_code,
)
from app.guide.presentation.copywriter_contracts import (
    CopywriterDraft,
    PresentationPacket,
    section_copy_blocks_include_winner_claim,
)
from app.guide.presentation.copywriter_prompt import (
    PRESENTATION_COPY_PROMPT_VERSION,
    build_presentation_copy_messages,
)


logger = logging.getLogger(__name__)


class CopywriterCallResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    draft: CopywriterDraft
    usage: SemanticTokenUsage
    provider: str
    model: str
    latency_ms: float
    raw_content: str | None = Field(
        default=None,
        min_length=1,
        max_length=65536,
    )
    trace_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
    )


class PresentationCopywriterPort(Protocol):
    def write(
        self,
        packet: PresentationPacket,
    ) -> CopywriterCallResult: ...


class PresentationCopywriterAdapterBase:
    prompt_version = PRESENTATION_COPY_PROMPT_VERSION

    def __init__(
        self,
        *,
        provider: str,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        max_tokens: int,
        temperature: float,
        daily_budget_cny: Decimal,
        daily_call_cap: int,
        transport: httpx.BaseTransport | None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.base_url = validate_adapter_settings(
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout_seconds=timeout_seconds,
            max_tokens=max_tokens,
            format_repair_attempts=0,
            enable_thinking=False,
        )
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError("provider must be nonempty")
        if (
            not isinstance(temperature, (int, float))
            or isinstance(temperature, bool)
            or not math.isfinite(temperature)
            or not 0.0 <= temperature <= 1.0
        ):
            raise ValueError("temperature must be between zero and one")
        self.provider = provider
        self.model = model
        self._max_tokens = max_tokens
        self._temperature = float(temperature)
        self._usage_limiter = DailyUsageLimiter(
            daily_budget_cny=daily_budget_cny,
            daily_call_cap=daily_call_cap,
            clock=clock,
        )
        self._client = OpenAIJsonClient(
            api_key=api_key,
            base_url=self.base_url,
            timeout_seconds=timeout_seconds,
            transport=transport,
        )

    def write(
        self,
        packet: PresentationPacket,
    ) -> CopywriterCallResult:
        if not isinstance(packet, PresentationPacket):
            raise TypeError("packet must be PresentationPacket")
        started = perf_counter()
        completion = self._request(
            build_presentation_copy_messages(packet)
        )
        usage = SemanticTokenUsage.model_validate(
            completion.usage,
            strict=True,
        )
        try:
            raw_output = json.loads(completion.content)
        except (TypeError, json.JSONDecodeError):
            raw_output = None
        if not section_copy_blocks_include_winner_claim(raw_output):
            code = SemanticProviderFailureCode.INVALID_OUTPUT
            self._log_failure(code)
            raise SemanticProviderFailure(
                code,
                raw_content=completion.content,
                trace_id=completion.trace_id,
                usage=usage,
            )
        try:
            draft = CopywriterDraft.model_validate_json(
                completion.content,
                strict=True,
            )
        except ValidationError as error:
            code = validation_failure_code(error)
            self._log_failure(code)
            raise SemanticProviderFailure(
                code,
                raw_content=completion.content,
                trace_id=completion.trace_id,
                usage=usage,
            ) from None
        if draft.summary_copy is not None:
            code = SemanticProviderFailureCode.FORBIDDEN_OUTPUT
            self._log_failure(code)
            raise SemanticProviderFailure(
                code,
                raw_content=completion.content,
                trace_id=completion.trace_id,
                usage=usage,
            )
        logger.info(
            "Guide presentation copy call succeeded "
            "provider=%s model=%s trace_id=%s",
            self.provider,
            self.model,
            completion.trace_id,
        )
        return CopywriterCallResult(
            draft=draft,
            usage=usage,
            provider=self.provider,
            model=self.model,
            latency_ms=(perf_counter() - started) * 1000,
            raw_content=completion.content,
            trace_id=completion.trace_id,
        )

    def _request(
        self,
        messages: tuple[dict[str, str], dict[str, str]],
    ):
        reservation = self._usage_limiter.reserve()
        actual_cost: Decimal | None = None
        try:
            try:
                completion = self._client.request(
                    self._request_body(messages)
                )
            except SemanticProviderFailure as failure:
                self._log_failure(
                    failure.code,
                    status_code=failure.status_code,
                )
                raise
            actual_cost = completion.actual_cost_cny
            return completion
        finally:
            self._usage_limiter.record_actual_cost(
                reservation,
                actual_cost,
            )

    def _request_body(
        self,
        messages: tuple[dict[str, str], dict[str, str]],
    ) -> Mapping[str, object]:
        raise NotImplementedError

    def _base_request_body(
        self,
        messages: tuple[dict[str, str], dict[str, str]],
    ) -> dict[str, object]:
        return {
            "model": self.model,
            "messages": list(messages),
            "response_format": {"type": "json_object"},
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "stream": False,
        }

    def _log_failure(
        self,
        code: SemanticProviderFailureCode,
        *,
        status_code: int | None = None,
    ) -> None:
        logger.warning(
            "Guide presentation copy call failed "
            "provider=%s model=%s code=%s status=%s",
            self.provider,
            self.model,
            code.value,
            status_code,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


__all__ = [
    "CopywriterCallResult",
    "PresentationCopywriterAdapterBase",
    "PresentationCopywriterPort",
]
