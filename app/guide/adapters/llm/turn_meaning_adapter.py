from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
import json
import logging
from typing import Self

import httpx
from pydantic import ValidationError

from app.guide.adapters.llm.contracts import (
    SemanticProviderFailure,
    SemanticProviderFailureCode,
    SemanticTokenUsage,
    TurnMeaningCallResult,
)
from app.guide.adapters.llm.provider_common import (
    DailyUsageLimiter,
    OpenAIJsonClient,
    validate_adapter_settings,
    validation_failure_code,
)
from app.guide.adapters.llm.turn_meaning_prompt import (
    TURN_MEANING_PROMPT_VERSION,
    authority_from_context,
    build_turn_meaning_messages,
)
from app.guide.understanding.semantic_contracts import SemanticContext
from app.guide.understanding.source_grounding import ground_unique_text
from app.guide.understanding.turn_meaning_contracts import TurnMeaning


logger = logging.getLogger(__name__)


class TurnMeaningAdapterBase:
    prompt_version = TURN_MEANING_PROMPT_VERSION
    response_tool_name: str | None = None

    def __init__(
        self,
        *,
        provider: str,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
        max_tokens: int,
        concept_catalog: tuple[str, ...],
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
        if (
            not isinstance(provider, str)
            or not provider.strip()
        ):
            raise ValueError("provider must be nonempty")
        if (
            not concept_catalog
            or concept_catalog != tuple(
                sorted(set(concept_catalog))
            )
        ):
            raise ValueError(
                "concept catalog must be sorted and unique"
            )
        self.provider = provider
        self.model = model
        self._max_tokens = max_tokens
        self._concept_catalog = concept_catalog
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

    def propose(
        self,
        message: str,
        context: SemanticContext,
    ) -> TurnMeaning:
        return self.propose_with_result(message, context).meaning

    def propose_with_result(
        self,
        message: str,
        context: SemanticContext,
    ) -> TurnMeaningCallResult:
        try:
            completion = self._request(
                build_turn_meaning_messages(
                    message,
                    authority_from_context(context),
                    concept_catalog=self._concept_catalog,
                )
            )
            try:
                payload = json.loads(completion.content)
                if not isinstance(payload, dict):
                    raise ValueError(
                        "turn meaning output must be a JSON object"
                    )
                expected_keys = set(TurnMeaning.model_fields)
                actual_keys = set(payload)
                if actual_keys != expected_keys:
                    extra_keys = actual_keys - expected_keys
                    code = (
                        SemanticProviderFailureCode.FORBIDDEN_OUTPUT
                        if extra_keys
                        else SemanticProviderFailureCode.INVALID_OUTPUT
                    )
                    raise SemanticProviderFailure(
                        code,
                        diagnostic=(
                            "turn meaning output keys do not match schema"
                        ),
                        raw_content=completion.content,
                        trace_id=completion.trace_id,
                        usage=SemanticTokenUsage.model_validate(
                            completion.usage,
                            strict=True,
                        ),
                    )
                meaning = TurnMeaning.model_validate(
                    payload,
                    strict=True,
                )
                if meaning.recommendation_mode_basis is not None:
                    ground_unique_text(
                        message.strip(),
                        meaning.recommendation_mode_basis.source_text,
                    )
                if (
                    meaning.recommendation_mode == "fit"
                    and not _has_usable_fit_signal(
                        meaning,
                        context=context,
                    )
                ):
                    meaning = TurnMeaning.model_validate(
                        {
                            **meaning.model_dump(mode="python"),
                            "recommendation_mode": "explore",
                            "recommendation_count": None,
                            "recommendation_mode_basis": {
                                "basis": "broad_exploration",
                                "source_text": (
                                    meaning.recommendation_mode_basis
                                    .source_text
                                ),
                            },
                        },
                        strict=True,
                    )
                if (
                    meaning.operation_hint
                    in {"recommendation", "image_similarity"}
                    and meaning.recommendation_mode is None
                ):
                    raise ValueError(
                        "provider recommendation requires recommendation_mode"
                    )
            except (json.JSONDecodeError, TypeError, ValueError) as error:
                code = (
                    validation_failure_code(error)
                    if isinstance(error, ValidationError)
                    else SemanticProviderFailureCode.INVALID_OUTPUT
                )
                self._log_failure(code)
                raise SemanticProviderFailure(
                    code,
                    raw_content=completion.content,
                    trace_id=completion.trace_id,
                    usage=SemanticTokenUsage.model_validate(
                        completion.usage,
                        strict=True,
                    ),
                ) from None
            logger.info(
                "Guide turn meaning call succeeded "
                "provider=%s model=%s trace_id=%s",
                self.provider,
                self.model,
                completion.trace_id,
            )
            return TurnMeaningCallResult(
                meaning=meaning,
                usage=SemanticTokenUsage.model_validate(
                    completion.usage,
                    strict=True,
                ),
                raw_content=completion.content,
                trace_id=completion.trace_id,
            )
        except SemanticProviderFailure as failure:
            code = failure.code
            status = failure.status_code
            diagnostic = failure.diagnostic
            raw_content = failure.raw_content
            trace_id = failure.trace_id
            usage = failure.usage
        del self, message, context
        raise SemanticProviderFailure(
            code,
            status_code=status,
            diagnostic=diagnostic,
            raw_content=raw_content,
            trace_id=trace_id,
            usage=usage,
        ) from None

    def _request(
        self,
        messages: tuple[dict[str, str], dict[str, str]],
    ):
        reservation = self._usage_limiter.reserve()
        actual_cost: Decimal | None = None
        try:
            try:
                completion = self._client.request(
                    self._request_body(messages),
                    tool_name=self.response_tool_name,
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
            "temperature": 0,
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
            "Guide turn meaning call failed "
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


def _has_usable_fit_signal(
    meaning: TurnMeaning,
    *,
    context: SemanticContext,
) -> bool:
    non_selection_observations = {
        "current_budget_unknown",
        "goal_unclear",
        "topic_unclear",
        "reference_unclear",
    }
    return bool(
        context.confirmed_profile_fields
        or meaning.preference_candidates
        or meaning.relative_candidates
        or meaning.constraint_changes
        or any(
            item.code not in non_selection_observations
            for item in meaning.observation_candidates
        )
    )


__all__ = ["TurnMeaningAdapterBase"]
