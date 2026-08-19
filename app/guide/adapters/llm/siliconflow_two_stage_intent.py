from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import json
import logging
from typing import TYPE_CHECKING, Callable, Self

import httpx
from pydantic import BaseModel, ValidationError

from app.guide.adapters.llm.contracts import (
    LLMCacheEntry,
    LLMSuccessStatus,
    SemanticProviderFailure,
    SemanticProviderFailureCode,
    SemanticSchemaDiagnostic,
    SemanticSchemaDiagnosticStage,
    SemanticSchemaRepairOutcome,
    SemanticStageUsage,
    SemanticTokenUsage,
    TwoStageSemanticCallResult,
    build_semantic_schema_diagnostic,
)
from app.guide.adapters.llm.intent_cache import (
    IntentProposalCache,
    build_intent_cache_key,
)
from app.guide.adapters.llm.intent_detail_prompt import (
    DETAIL_PROMPT_VERSION,
    build_detail_messages,
)
from app.guide.adapters.llm.intent_route_prompt import (
    ROUTE_PROMPT_VERSION,
    build_route_messages,
)
from app.guide.adapters.llm.siliconflow_intent import (
    _DailyUsageLimiter,
    _extract_content,
    _extract_usage,
    _http_failure_code,
    _safe_trace_id,
    _validate_adapter_settings,
    _validation_failure_code,
)
from app.guide.understanding.semantic_contracts import (
    SemanticContext,
    SemanticIntentProposal,
)
from app.guide.understanding.semantic_detail_contracts import (
    SemanticDetailsProposal,
)
from app.guide.understanding.semantic_route_contracts import (
    SemanticDetailStage,
    SemanticRouteProposal,
)
from app.guide.understanding.two_stage_semantic import (
    compose_semantic_proposal,
    detail_type_for_stage,
)

if TYPE_CHECKING:
    from app.guide_runtime.llm_config import GuideLlmConfig


logger = logging.getLogger(__name__)


class SiliconFlowTwoStageIntentAdapter:
    provider = "siliconflow"
    prompt_version = (
        f"{ROUTE_PROMPT_VERSION}+{DETAIL_PROMPT_VERSION}"
    )

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        max_tokens: int = 128,
        enable_thinking: bool = False,
        format_repair_attempts: int = 1,
        daily_budget_cny: Decimal = Decimal("1.00"),
        daily_call_cap: int = 200,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        cache: IntentProposalCache | None = None,
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
        if cache is not None and not isinstance(
            cache,
            IntentProposalCache,
        ):
            raise TypeError("cache must be an IntentProposalCache")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._max_tokens = max_tokens
        self._enable_thinking = enable_thinking
        self._format_repair_attempts = format_repair_attempts
        self._cache = cache
        self._usage_limiter = _DailyUsageLimiter(
            daily_budget_cny=daily_budget_cny,
            daily_call_cap=daily_call_cap,
            clock=clock,
        )
        self._client = httpx.Client(
            base_url=f"{self.base_url}/",
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
        cache: IntentProposalCache | None = None,
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
            cache=cache,
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
    ) -> TwoStageSemanticCallResult:
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
    ) -> TwoStageSemanticCallResult:
        repair_available = self._format_repair_attempts == 1
        route = self._cache_get(
            stage="route",
            result_schema=SemanticRouteProposal,
            prompt_version=ROUTE_PROMPT_VERSION,
            message=message,
            context=context,
            stage_identity=None,
        )
        route_usage: SemanticTokenUsage | None = None
        route_repaired = False
        if route is None:
            route_result, route_usage, route_repaired = (
                self._request_validated(
                    result_schema=SemanticRouteProposal,
                    message_builder=lambda repair, diagnostic: (
                        build_route_messages(
                            message,
                            context,
                            format_repair=repair,
                            repair_kind=(
                                diagnostic.kind
                                if diagnostic is not None
                                else None
                            ),
                            repair_path=(
                                diagnostic.path
                                if diagnostic is not None
                                else None
                            ),
                        )
                    ),
                    allow_repair=repair_available,
                )
            )
            if not isinstance(route_result, SemanticRouteProposal):
                raise AssertionError("route schema returned wrong type")
            route = route_result
            self._cache_put(
                stage="route",
                result=route,
                result_schema=SemanticRouteProposal,
                prompt_version=ROUTE_PROMPT_VERSION,
                message=message,
                context=context,
                stage_identity=None,
            )
        if not isinstance(route, SemanticRouteProposal):
            raise AssertionError("route cache returned wrong type")

        stage_usage = [
            SemanticStageUsage(
                stage="route",
                usage=route_usage,
                repair_used=route_repaired,
            )
        ]
        repair_available = repair_available and not route_repaired
        if route.detail_stage is SemanticDetailStage.NONE:
            return TwoStageSemanticCallResult(
                proposal=compose_semantic_proposal(route, None),
                stage_usage=tuple(stage_usage),
            )

        detail_schema = detail_type_for_stage(route.detail_stage)
        detail_stage = f"detail:{route.detail_stage.value}"
        details = self._cache_get(
            stage=detail_stage,
            result_schema=detail_schema,
            prompt_version=DETAIL_PROMPT_VERSION,
            message=message,
            context=context,
            stage_identity=route,
        )
        detail_usage: SemanticTokenUsage | None = None
        detail_repaired = False
        if details is None:
            details, detail_usage, detail_repaired = (
                self._request_validated(
                    result_schema=detail_schema,
                    message_builder=lambda repair, diagnostic: (
                        build_detail_messages(
                            message,
                            context,
                            route,
                            format_repair=repair,
                            repair_kind=(
                                diagnostic.kind
                                if diagnostic is not None
                                else None
                            ),
                            repair_path=(
                                diagnostic.path
                                if diagnostic is not None
                                else None
                            ),
                        )
                    ),
                    allow_repair=repair_available,
                )
            )
            self._cache_put(
                stage=detail_stage,
                result=details,
                result_schema=detail_schema,
                prompt_version=DETAIL_PROMPT_VERSION,
                message=message,
                context=context,
                stage_identity=route,
            )
        stage_usage.append(
            SemanticStageUsage(
                stage="detail",
                usage=detail_usage,
                repair_used=detail_repaired,
            )
        )
        return TwoStageSemanticCallResult(
            proposal=compose_semantic_proposal(
                route,
                details,
            ),
            stage_usage=tuple(stage_usage),
        )

    def _request_validated(
        self,
        *,
        result_schema: type[BaseModel],
        message_builder: Callable[
            [bool, SemanticSchemaDiagnostic | None],
            tuple[dict[str, str], dict[str, str]],
        ],
        allow_repair: bool,
    ) -> tuple[BaseModel, SemanticTokenUsage, bool]:
        repair_diagnostic: SemanticSchemaDiagnostic | None = None
        usages: list[SemanticTokenUsage] = []
        for attempt in range(2 if allow_repair else 1):
            content, trace_id, raw_usage = self._request(
                message_builder(attempt > 0, repair_diagnostic)
            )
            usages.append(
                SemanticTokenUsage.model_validate(
                    raw_usage,
                    strict=True,
                )
            )
            try:
                result = result_schema.model_validate_json(
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
                        else SemanticSchemaRepairOutcome.NOT_ATTEMPTED
                    ),
                )
                if (
                    code is SemanticProviderFailureCode.FORBIDDEN_OUTPUT
                    or attempt > 0
                    or not allow_repair
                ):
                    self._log_failure(code)
                    raise SemanticProviderFailure(
                        code,
                        diagnostic=diagnostic,
                    ) from None
                repair_diagnostic = diagnostic
                continue

            logger.info(
                "Guide semantic provider stage succeeded "
                "provider=%s model=%s trace_id=%s",
                self.provider,
                self.model,
                trace_id,
            )
            return result, _sum_usage(usages), attempt > 0
        raise AssertionError("format repair loop ended unexpectedly")

    def _request(
        self,
        messages: tuple[dict[str, str], dict[str, str]],
    ) -> tuple[str, str, dict[str, int | None]]:
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
                self._log_failure(code, status_code=response.status_code)
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

    def _cache_get(
        self,
        *,
        stage: str,
        result_schema: type[BaseModel],
        prompt_version: str,
        message: str,
        context: SemanticContext,
        stage_identity: BaseModel | None,
    ) -> BaseModel | None:
        if self._cache is None:
            return None
        key = build_intent_cache_key(
            stage=stage,
            result_schema=result_schema,
            provider=self.provider,
            base_url=self.base_url,
            model=self.model,
            prompt_version=prompt_version,
            message=message,
            context=context,
            temperature=0.0,
            max_tokens=self._max_tokens,
            enable_thinking=self._enable_thinking,
            stage_identity=stage_identity,
        )
        entry = self._cache.get(key)
        if entry is None:
            return None
        try:
            return result_schema.model_validate_json(
                json.dumps(entry.result),
                strict=True,
            )
        except (TypeError, ValueError):
            return None

    def _cache_put(
        self,
        *,
        stage: str,
        result: BaseModel,
        result_schema: type[BaseModel],
        prompt_version: str,
        message: str,
        context: SemanticContext,
        stage_identity: BaseModel | None,
    ) -> None:
        if self._cache is None:
            return
        key = build_intent_cache_key(
            stage=stage,
            result_schema=result_schema,
            provider=self.provider,
            base_url=self.base_url,
            model=self.model,
            prompt_version=prompt_version,
            message=message,
            context=context,
            temperature=0.0,
            max_tokens=self._max_tokens,
            enable_thinking=self._enable_thinking,
            stage_identity=stage_identity,
        )
        self._cache.put(
            key,
            LLMCacheEntry.from_validated_result(
                key=key,
                result=result,
                result_schema=result_schema,
                actual_provider=self.provider,
                actual_model=self.model,
                status=LLMSuccessStatus.PRIMARY_SUCCESS,
            ),
        )

    def _reserve_request(self):
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

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def _sum_usage(usages: list[SemanticTokenUsage]) -> SemanticTokenUsage:
    values: dict[str, int | None] = {}
    for field_name in (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cached_tokens",
    ):
        observed = [
            value
            for usage in usages
            if (value := getattr(usage, field_name)) is not None
        ]
        values[field_name] = sum(observed) if observed else None
    return SemanticTokenUsage.model_validate(values, strict=True)


__all__ = ["SiliconFlowTwoStageIntentAdapter"]
