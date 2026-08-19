from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import json
import logging
from typing import Callable, Self

import httpx
from pydantic import BaseModel, ValidationError

from app.guide.adapters.llm.contracts import (
    LLMCacheEntry,
    LLMCacheKey,
    LLMThinkingContract,
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
from app.guide.adapters.llm.deepseek_intent import (
    DEEPSEEK_OFFICIAL_BASE_URL,
    DEEPSEEK_V4_PRO_MODEL,
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
from app.guide.adapters.llm.provider_common import (
    DailyUsageLimiter,
    JsonCompletion,
    OpenAIJsonClient,
    UsageReservation,
    sum_usage,
    validate_adapter_settings,
    validation_failure_code,
)
from app.guide.understanding.semantic_contracts import (
    SemanticContext,
    SemanticIntentProposal,
)
from app.guide.understanding.semantic_route_contracts import (
    SemanticDetailStage,
    SemanticRouteProposal,
)
from app.guide.understanding.two_stage_semantic import (
    compose_semantic_proposal,
    detail_type_for_stage,
)


logger = logging.getLogger(__name__)

DEEPSEEK_V4_FLASH_MODEL = "deepseek-v4-flash"
_PROVIDER = "deepseek_official"
_MAX_TOKENS = 256
_THINKING = {"type": "disabled"}
_SUPPORTED_MODELS = frozenset(
    {DEEPSEEK_V4_FLASH_MODEL, DEEPSEEK_V4_PRO_MODEL}
)


class DeepSeekTwoStageIntentAdapter:
    provider = _PROVIDER
    prompt_version = (
        f"{ROUTE_PROMPT_VERSION}+{DETAIL_PROMPT_VERSION}"
    )

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
        cache: IntentProposalCache | None = None,
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
        if model not in _SUPPORTED_MODELS:
            raise ValueError("unsupported DeepSeek official V4 model")
        if cache is not None and not isinstance(
            cache,
            IntentProposalCache,
        ):
            raise TypeError("cache must be an IntentProposalCache")
        self.base_url = normalized_base_url
        self.model = model
        self._format_repair_attempts = format_repair_attempts
        self._cache = cache
        self._thinking_contract = LLMThinkingContract(type="disabled")
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
            proposal=compose_semantic_proposal(route, details),
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
            completion = self._request(
                message_builder(attempt > 0, repair_diagnostic)
            )
            usages.append(
                SemanticTokenUsage.model_validate(
                    completion.usage,
                    strict=True,
                )
            )
            try:
                result = result_schema.model_validate_json(
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
                completion.trace_id,
            )
            return result, sum_usage(usages), attempt > 0
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
        key = self._cache_key(
            stage=stage,
            result_schema=result_schema,
            prompt_version=prompt_version,
            message=message,
            context=context,
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
        key = self._cache_key(
            stage=stage,
            result_schema=result_schema,
            prompt_version=prompt_version,
            message=message,
            context=context,
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

    def _cache_key(
        self,
        *,
        stage: str,
        result_schema: type[BaseModel],
        prompt_version: str,
        message: str,
        context: SemanticContext,
        stage_identity: BaseModel | None,
    ) -> LLMCacheKey:
        return build_intent_cache_key(
            stage=stage,
            result_schema=result_schema,
            provider=self.provider,
            base_url=self.base_url,
            model=self.model,
            prompt_version=prompt_version,
            message=message,
            context=context,
            temperature=0.0,
            max_tokens=_MAX_TOKENS,
            enable_thinking=None,
            thinking=self._thinking_contract,
            stage_identity=stage_identity,
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
    "DEEPSEEK_V4_FLASH_MODEL",
    "DeepSeekTwoStageIntentAdapter",
]
