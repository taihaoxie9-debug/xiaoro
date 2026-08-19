from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import logging
from typing import Callable, Self

import httpx
from pydantic import ValidationError

from app.guide.adapters.llm.contracts import (
    SemanticIntentCallResult,
    SemanticProviderFailure,
    SemanticProviderFailureCode,
    SemanticSchemaDiagnostic,
    SemanticSchemaDiagnosticStage,
    SemanticSchemaRepairOutcome,
    SemanticTokenUsage,
    build_semantic_schema_diagnostic,
)
from app.guide.adapters.llm.intent_prompt import (
    INTENT_PROMPT_VERSION,
    build_intent_messages,
)
from app.guide.adapters.llm.provider_common import (
    DailyUsageLimiter,
    JsonCompletion,
    OpenAIJsonClient,
    UsageReservation,
    validate_adapter_settings,
    validation_failure_code,
)
from app.guide.understanding.semantic_contracts import (
    SemanticContext,
    SemanticIntentProposal,
)


logger = logging.getLogger(__name__)

DEEPSEEK_OFFICIAL_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_V4_PRO_MODEL = "deepseek-v4-pro"
_PROVIDER = "deepseek_official"
_MAX_TOKENS = 256
_THINKING = {"type": "disabled"}


class DeepSeekIntentAdapter:
    """V4-Pro single-stage control adapter; never a production route."""

    provider = _PROVIDER
    prompt_version = INTENT_PROMPT_VERSION

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        base_url: str = DEEPSEEK_OFFICIAL_BASE_URL,
        max_tokens: int = _MAX_TOKENS,
        format_repair_attempts: int = 1,
        daily_budget_cny: Decimal = Decimal("1.00"),
        daily_call_cap: int = 200,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        normalized_base_url = validate_adapter_settings(
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout_seconds=timeout_seconds,
            max_tokens=max_tokens,
            format_repair_attempts=format_repair_attempts,
        )
        if normalized_base_url != DEEPSEEK_OFFICIAL_BASE_URL:
            raise ValueError("DeepSeek official base URL is required")
        if max_tokens != _MAX_TOKENS:
            raise ValueError(
                "DeepSeek structured max tokens must be 256"
            )
        if model != DEEPSEEK_V4_PRO_MODEL:
            raise ValueError(
                "single-stage control requires DeepSeek V4-Pro"
            )
        self.base_url = normalized_base_url
        self.model = model
        self._format_repair_attempts = format_repair_attempts
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

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            f"provider={self.provider!r}, "
            f"base_url={self.base_url!r}, "
            f"model={self.model!r}, "
            f"prompt_version={self.prompt_version!r})"
        )

    def propose(
        self,
        message: str,
        context: SemanticContext,
    ) -> SemanticIntentProposal:
        return self.propose_with_result(message, context).proposal

    def propose_with_result(
        self,
        message: str,
        context: SemanticContext,
    ) -> SemanticIntentCallResult:
        failure_code: SemanticProviderFailureCode | None = None
        failure_status: int | None = None
        failure_diagnostic: SemanticSchemaDiagnostic | None = None
        try:
            return self._propose_with_result(message, context)
        except SemanticProviderFailure as failure:
            failure_code = failure.code
            failure_status = failure.status_code
            failure_diagnostic = failure.diagnostic

        if failure_code is None:
            raise AssertionError("semantic provider failure code is unavailable")
        del self, message, context
        raise SemanticProviderFailure(
            failure_code,
            status_code=failure_status,
            diagnostic=failure_diagnostic,
        ) from None

    def _propose_with_result(
        self,
        message: str,
        context: SemanticContext,
    ) -> SemanticIntentCallResult:
        repair_diagnostic: SemanticSchemaDiagnostic | None = None
        for attempt in range(self._format_repair_attempts + 1):
            completion = self._request(
                build_intent_messages(
                    message,
                    context,
                    format_repair=attempt > 0,
                    repair_kind=(
                        repair_diagnostic.kind
                        if repair_diagnostic is not None
                        else None
                    ),
                    repair_path=(
                        repair_diagnostic.path
                        if repair_diagnostic is not None
                        else None
                    ),
                )
            )
            try:
                proposal = SemanticIntentProposal.model_validate_json(
                    completion.content,
                    strict=True,
                )
            except ValidationError as error:
                code = validation_failure_code(error)
                diagnostic = build_semantic_schema_diagnostic(
                    error,
                    stage=(
                        SemanticSchemaDiagnosticStage.REPAIR
                        if attempt > 0
                        else SemanticSchemaDiagnosticStage.PRIMARY
                    ),
                    repair_outcome=(
                        SemanticSchemaRepairOutcome.FAILED
                        if attempt > 0
                        else SemanticSchemaRepairOutcome.NOT_ATTEMPTED
                    ),
                )
                if (
                    code is SemanticProviderFailureCode.FORBIDDEN_OUTPUT
                    or attempt >= self._format_repair_attempts
                ):
                    self._log_failure(code)
                    raise SemanticProviderFailure(
                        code,
                        diagnostic=diagnostic,
                    ) from None
                repair_diagnostic = diagnostic
                continue

            logger.info(
                "Guide semantic provider call succeeded "
                "provider=%s model=%s trace_id=%s",
                self.provider,
                self.model,
                completion.trace_id,
            )
            return SemanticIntentCallResult(
                proposal=proposal,
                usage=SemanticTokenUsage.model_validate(
                    completion.usage,
                    strict=True,
                ),
            )
        raise AssertionError("format repair loop ended unexpectedly")

    def _request(
        self,
        messages: tuple[dict[str, str], dict[str, str]],
    ) -> JsonCompletion:
        reservation = self._reserve_request()
        actual_cost: Decimal | None = None
        try:
            try:
                completion = self._client.request(
                    {
                        "model": self.model,
                        "messages": list(messages),
                        "response_format": {"type": "json_object"},
                        "temperature": 0,
                        "max_tokens": _MAX_TOKENS,
                        "thinking": dict(_THINKING),
                        "stream": False,
                    }
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

    def _reserve_request(self) -> UsageReservation:
        try:
            return self._usage_limiter.reserve()
        except SemanticProviderFailure as failure:
            self._log_failure(failure.code)
            raise

    def _log_failure(
        self,
        code: SemanticProviderFailureCode,
        *,
        status_code: int | None = None,
    ) -> None:
        logger.warning(
            "Guide semantic provider call failed "
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
    "DEEPSEEK_OFFICIAL_BASE_URL",
    "DEEPSEEK_V4_PRO_MODEL",
    "DeepSeekIntentAdapter",
]
