from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import logging
from typing import TYPE_CHECKING, Callable, Self

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
    DailyUsageLimiter as _DailyUsageLimiter,
    UsageReservation as _UsageReservation,
    extract_content as _extract_content,
    extract_usage as _extract_usage,
    http_failure_code as _http_failure_code,
    safe_trace_id as _safe_trace_id,
    validate_adapter_settings as _validate_adapter_settings,
    validation_failure_code as _validation_failure_code,
)
from app.guide.understanding.semantic_contracts import (
    SemanticContext,
    SemanticIntentProposal,
)

if TYPE_CHECKING:
    from app.guide_runtime.llm_config import GuideLlmConfig


logger = logging.getLogger(__name__)

_PROVIDER = "siliconflow"


class SiliconFlowIntentAdapter:
    provider = _PROVIDER
    prompt_version = INTENT_PROMPT_VERSION

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        max_tokens: int = 256,
        enable_thinking: bool = False,
        format_repair_attempts: int = 1,
        daily_budget_cny: Decimal = Decimal("1.00"),
        daily_call_cap: int = 200,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        _validate_adapter_settings(
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout_seconds=timeout_seconds,
            max_tokens=max_tokens,
            enable_thinking=enable_thinking,
            format_repair_attempts=format_repair_attempts,
        )
        self.model = model
        self._max_tokens = max_tokens
        self._enable_thinking = enable_thinking
        self._format_repair_attempts = format_repair_attempts
        self._usage_limiter = _DailyUsageLimiter(
            daily_budget_cny=daily_budget_cny,
            daily_call_cap=daily_call_cap,
            clock=clock,
        )
        self._client = httpx.Client(
            base_url=f"{base_url.rstrip('/')}/",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            f"provider={self.provider!r}, "
            f"model={self.model!r}, "
            f"prompt_version={self.prompt_version!r})"
        )

    @classmethod
    def from_config(
        cls,
        config: GuideLlmConfig,
        *,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> Self:
        ready = config.require_ready()
        api_key = ready.api_key
        model = ready.model
        if api_key is None or model is None:
            raise AssertionError(
                "ready Guide LLM configuration is incomplete"
            )
        return cls(
            api_key=api_key,
            base_url=ready.base_url,
            model=model,
            timeout_seconds=ready.timeout_seconds,
            max_tokens=ready.max_tokens,
            enable_thinking=ready.enable_thinking,
            format_repair_attempts=ready.format_repair_attempts,
            daily_budget_cny=ready.daily_budget_cny,
            daily_call_cap=ready.daily_call_cap,
            transport=transport,
            clock=clock,
        )

    def propose(
        self,
        message: str,
        context: SemanticContext,
    ) -> SemanticIntentProposal:
        failure_code: SemanticProviderFailureCode | None = None
        failure_status: int | None = None
        failure_diagnostic: SemanticSchemaDiagnostic | None = None
        try:
            return self.propose_with_result(message, context).proposal
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
        )

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
            content, trace_id, usage = self._request(
                message,
                context,
                format_repair=attempt > 0,
                repair_diagnostic=repair_diagnostic,
            )
            try:
                proposal = SemanticIntentProposal.model_validate_json(
                    content,
                    strict=True,
                )
            except ValidationError as error:
                code = _validation_failure_code(error)
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
                        else (
                            SemanticSchemaRepairOutcome
                            .NOT_ATTEMPTED
                        )
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
                "provider=%s model=%s trace_id=%s "
                "prompt_tokens=%s completion_tokens=%s",
                self.provider,
                self.model,
                trace_id,
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
            )
            return SemanticIntentCallResult(
                proposal=proposal,
                usage=SemanticTokenUsage.model_validate(
                    usage,
                    strict=True,
                ),
            )
        raise AssertionError("format repair loop ended unexpectedly")

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _request(
        self,
        message: str,
        context: SemanticContext,
        *,
        format_repair: bool,
        repair_diagnostic: SemanticSchemaDiagnostic | None,
    ) -> tuple[str, str, dict[str, int | None]]:
        messages = build_intent_messages(
            message,
            context,
            format_repair=format_repair,
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
        reservation = self._reserve_request()
        actual_cost: Decimal | None = None
        try:
            try:
                response = self._client.post(
                    "chat/completions",
                    json={
                        "model": self.model,
                        "messages": list(messages),
                        "response_format": {"type": "json_object"},
                        "temperature": 0,
                        "max_tokens": self._max_tokens,
                        "enable_thinking": self._enable_thinking,
                        "stream": False,
                    },
                )
            except httpx.TimeoutException:
                self._log_failure(SemanticProviderFailureCode.TIMEOUT)
                raise SemanticProviderFailure(
                    SemanticProviderFailureCode.TIMEOUT
                ) from None
            except httpx.HTTPError:
                self._log_failure(
                    SemanticProviderFailureCode.PROVIDER_UNAVAILABLE
                )
                raise SemanticProviderFailure(
                    SemanticProviderFailureCode.PROVIDER_UNAVAILABLE
                ) from None

            if not 200 <= response.status_code < 300:
                code = _http_failure_code(response.status_code)
                self._log_failure(
                    code,
                    status_code=response.status_code,
                )
                raise SemanticProviderFailure(
                    code,
                    status_code=response.status_code,
                ) from None

            if not response.content:
                self._log_failure(
                    SemanticProviderFailureCode.EMPTY_RESPONSE
                )
                raise SemanticProviderFailure(
                    SemanticProviderFailureCode.EMPTY_RESPONSE
                )
            try:
                envelope = response.json()
            except ValueError:
                self._log_failure(
                    SemanticProviderFailureCode.INVALID_RESPONSE
                )
                raise SemanticProviderFailure(
                    SemanticProviderFailureCode.INVALID_RESPONSE
                ) from None

            content = _extract_content(envelope)
            usage, actual_cost = _extract_usage(envelope)
            trace_id = _safe_trace_id(
                response.headers.get("x-request-id")
                or response.headers.get("request-id")
            )
            return content, trace_id, usage
        finally:
            self._usage_limiter.record_actual_cost(
                reservation,
                actual_cost,
            )

    def _reserve_request(self) -> _UsageReservation:
        try:
            return self._usage_limiter.reserve()
        except SemanticProviderFailure as error:
            self._log_failure(error.code)
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
