from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Annotated, ClassVar, Literal, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError,
    ValidationInfo,
    model_validator,
)

from app.guide.understanding.semantic_contracts import (
    SemanticIntentProposal,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning


StrictString = Annotated[str, Field(strict=True, min_length=1)]
_ENTRY_FACTORY_CONTEXT_KEY = "llm_cache_entry_factory"
_ENTRY_FACTORY_TOKEN = object()


class LLMSchemaVersionedResult(Protocol):
    schema_version: ClassVar[str]


class LLMThinkingContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    type: Literal["disabled"]


class LLMGenerationParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    temperature: Annotated[float, Field(strict=True, ge=0.0)]
    max_tokens: Annotated[int, Field(strict=True, gt=0)]
    enable_thinking: Annotated[bool, Field(strict=True)] | None = False
    thinking: LLMThinkingContract | None = None

    @model_validator(mode="after")
    def _require_one_thinking_contract(self) -> LLMGenerationParameters:
        if self.enable_thinking is None and self.thinking is None:
            raise ValueError("a thinking contract is required")
        if self.enable_thinking is not None and self.thinking is not None:
            raise ValueError("thinking contracts are mutually exclusive")
        return self


class LLMCacheKey(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    stage: StrictString
    provider: StrictString
    base_url: StrictString
    model: StrictString
    prompt_version: StrictString
    schema_version: StrictString
    context_sha256: Annotated[
        str,
        Field(strict=True, pattern=r"^[0-9a-f]{64}$"),
    ]
    generation_parameters: LLMGenerationParameters

    def fingerprint(self) -> str:
        canonical_json = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class LLMSuccessStatus(str, Enum):
    PRIMARY_SUCCESS = "primary_success"
    FALLBACK_SUCCESS = "fallback_success"


class SemanticProviderFailureCode(str, Enum):
    AUTHENTICATION_FAILED = "authentication_failed"
    RATE_LIMITED = "rate_limited"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_REJECTED = "provider_rejected"
    TIMEOUT = "timeout"
    EMPTY_RESPONSE = "empty_response"
    INVALID_RESPONSE = "invalid_response"
    INVALID_OUTPUT = "invalid_output"
    FORBIDDEN_OUTPUT = "forbidden_output"
    DAILY_BUDGET_EXCEEDED = "daily_budget_exceeded"
    DAILY_CALL_CAP_EXCEEDED = "daily_call_cap_exceeded"


class SemanticSchemaDiagnosticStage(str, Enum):
    PRIMARY = "primary"
    REPAIR = "repair"


class SemanticSchemaDiagnosticKind(str, Enum):
    JSON_SYNTAX = "json_syntax"
    MISSING = "missing"
    EXTRA = "extra"
    ENUM = "enum"
    TYPE = "type"
    BOUNDS = "bounds"
    CARDINALITY = "cardinality"
    CROSS_FIELD = "cross_field"


class SemanticSchemaDiagnosticPath(str, Enum):
    ROOT = "root"
    GOAL = "goal"
    TOPIC = "topic"
    CONCERNS = "concerns"
    OBSERVATIONS = "observations"
    REFERENCES = "references"
    PRODUCT_MENTIONS = "product_mentions"
    NUMBER_CANDIDATES = "number_candidates"
    PREFERENCE_CANDIDATES = "preference_candidates"
    CONFIDENCE = "confidence"
    CLARIFICATION_HINT = "clarification_hint"


class SemanticSchemaRepairOutcome(str, Enum):
    NOT_ATTEMPTED = "not_attempted"
    FAILED = "failed"


class SemanticSchemaDiagnostic(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    stage: SemanticSchemaDiagnosticStage
    kind: SemanticSchemaDiagnosticKind
    path: SemanticSchemaDiagnosticPath
    count: int = Field(ge=1)
    truncated: bool
    repair_outcome: SemanticSchemaRepairOutcome


def build_semantic_schema_diagnostic(
    error: ValidationError,
    *,
    stage: SemanticSchemaDiagnosticStage,
    repair_outcome: SemanticSchemaRepairOutcome,
) -> SemanticSchemaDiagnostic:
    failures = error.errors(
        include_url=False,
        include_context=False,
        include_input=False,
    )
    first = failures[0] if failures else {"type": "model_type", "loc": ()}
    kind = _semantic_schema_failure_kind(first.get("type"))
    path = _semantic_schema_failure_path(
        first.get("loc"),
        hide_location=(
            kind is SemanticSchemaDiagnosticKind.EXTRA
        ),
    )
    return SemanticSchemaDiagnostic(
        stage=stage,
        kind=kind,
        path=path,
        count=max(1, len(failures)),
        truncated=len(failures) > 8,
        repair_outcome=repair_outcome,
    )


def _semantic_schema_failure_kind(
    failure_type: object,
) -> SemanticSchemaDiagnosticKind:
    if failure_type == "json_invalid":
        return SemanticSchemaDiagnosticKind.JSON_SYNTAX
    if failure_type == "missing":
        return SemanticSchemaDiagnosticKind.MISSING
    if failure_type == "extra_forbidden":
        return SemanticSchemaDiagnosticKind.EXTRA
    if failure_type in {"enum", "literal_error"}:
        return SemanticSchemaDiagnosticKind.ENUM
    if failure_type in {
        "greater_than",
        "greater_than_equal",
        "less_than",
        "less_than_equal",
        "finite_number",
    }:
        return SemanticSchemaDiagnosticKind.BOUNDS
    if failure_type in {"too_long", "too_short"}:
        return SemanticSchemaDiagnosticKind.CARDINALITY
    if failure_type in {"value_error", "assertion_error"}:
        return SemanticSchemaDiagnosticKind.CROSS_FIELD
    return SemanticSchemaDiagnosticKind.TYPE


def _semantic_schema_failure_path(
    location: object,
    *,
    hide_location: bool,
) -> SemanticSchemaDiagnosticPath:
    if hide_location or not isinstance(location, tuple) or not location:
        return SemanticSchemaDiagnosticPath.ROOT
    first = location[0]
    if not isinstance(first, str):
        return SemanticSchemaDiagnosticPath.ROOT
    try:
        return SemanticSchemaDiagnosticPath(first)
    except ValueError:
        return SemanticSchemaDiagnosticPath.ROOT


class SemanticProviderFailure(RuntimeError):
    def __init__(
        self,
        code: SemanticProviderFailureCode,
        *,
        status_code: int | None = None,
        diagnostic: SemanticSchemaDiagnostic | None = None,
        raw_content: str | None = None,
        trace_id: str | None = None,
        usage: SemanticTokenUsage | None = None,
    ) -> None:
        if diagnostic is not None and not isinstance(
            diagnostic,
            SemanticSchemaDiagnostic,
        ):
            raise TypeError(
                "diagnostic must be a SemanticSchemaDiagnostic"
            )
        if (
            raw_content is not None
            and (
                not isinstance(raw_content, str)
                or not 1 <= len(raw_content) <= 65536
            )
        ):
            raise ValueError(
                "raw_content must be a bounded string or None"
            )
        if (
            trace_id is not None
            and (
                not isinstance(trace_id, str)
                or not 1 <= len(trace_id) <= 80
            )
        ):
            raise ValueError(
                "trace_id must be a bounded string or None"
            )
        if usage is not None and not isinstance(
            usage,
            SemanticTokenUsage,
        ):
            raise TypeError(
                "usage must be SemanticTokenUsage or None"
            )
        self.code = code
        self.status_code = status_code
        self.diagnostic = diagnostic
        self.raw_content = raw_content
        self.trace_id = trace_id
        self.usage = usage
        super().__init__(f"semantic provider unavailable: {code.value}")


class SemanticTokenUsage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    cached_tokens: int | None = Field(default=None, ge=0)


class SemanticStageUsage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    stage: Literal["route", "detail"]
    usage: SemanticTokenUsage | None
    repair_used: bool


class TwoStageSemanticCallResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    proposal: SemanticIntentProposal
    stage_usage: tuple[SemanticStageUsage, ...] = Field(
        min_length=1,
        max_length=2,
    )


class SemanticIntentCallResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    proposal: SemanticIntentProposal
    usage: SemanticTokenUsage | None = None


class TurnMeaningCallResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    meaning: TurnMeaning
    usage: SemanticTokenUsage | None = None
    raw_content: str | None = Field(
        default=None,
        min_length=2,
        max_length=65536,
    )
    trace_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
    )


class LLMCacheEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    result: dict[str, JsonValue]
    schema_version: StrictString
    actual_provider: StrictString
    actual_model: StrictString
    status: LLMSuccessStatus

    @model_validator(mode="before")
    @classmethod
    def _require_validated_factory(
        cls,
        data: object,
        info: ValidationInfo,
    ) -> object:
        context = info.context
        if (
            not isinstance(context, dict)
            or context.get(_ENTRY_FACTORY_CONTEXT_KEY) is not _ENTRY_FACTORY_TOKEN
        ):
            raise ValueError(
                "LLMCacheEntry must be created with from_validated_result"
            )
        return data

    @classmethod
    def from_validated_result(
        cls,
        *,
        key: LLMCacheKey,
        result: BaseModel,
        result_schema: type[BaseModel],
        actual_provider: str,
        actual_model: str,
        status: LLMSuccessStatus,
    ) -> LLMCacheEntry:
        if not isinstance(key, LLMCacheKey):
            raise TypeError("key must be an LLMCacheKey instance")
        if not isinstance(result_schema, type) or not issubclass(
            result_schema, BaseModel
        ):
            raise TypeError("result_schema must be a BaseModel subclass")
        if not isinstance(result, BaseModel):
            raise TypeError("result must be an instantiated Pydantic model")

        result_schema_version = getattr(result_schema, "schema_version", None)
        if not isinstance(result_schema_version, str) or not result_schema_version:
            raise TypeError(
                "result_schema must define a non-empty schema_version ClassVar"
            )
        if result_schema_version != key.schema_version:
            raise ValueError(
                "result schema version does not match cache key schema version"
            )
        if type(result) is not result_schema:
            raise TypeError("result type must be exactly result_schema")

        result_payload = result.model_dump(
            mode="python",
            round_trip=True,
            warnings=False,
        )
        validated_result = result_schema.model_validate(result_payload, strict=True)
        json_result = validated_result.model_dump(mode="json")
        canonical_result = json.loads(
            json.dumps(
                json_result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
        if not isinstance(canonical_result, dict):
            raise TypeError("result Pydantic model must serialize to a JSON object")

        return cls.model_validate(
            {
                "result": canonical_result,
                "schema_version": key.schema_version,
                "actual_provider": actual_provider,
                "actual_model": actual_model,
                "status": status,
            },
            context={_ENTRY_FACTORY_CONTEXT_KEY: _ENTRY_FACTORY_TOKEN},
        )

    @classmethod
    def from_cache_payload(cls, payload: object) -> LLMCacheEntry:
        """Re-validate a previously persisted cache payload.

        This is the only supported way to rebuild a validated entry from a
        durable cache row. It still enforces the full strict schema, so a
        tampered row cannot bypass validation; it merely re-opens the
        factory gate for trusted cache reloads and coerces the persisted
        JSON status token back to the closed success enum.
        """
        if not isinstance(payload, dict):
            raise TypeError("cache payload must be a mapping")
        data = dict(payload)
        raw_status = data.get("status")
        if isinstance(raw_status, str):
            data["status"] = LLMSuccessStatus(raw_status)
        return cls.model_validate(
            data,
            strict=True,
            context={_ENTRY_FACTORY_CONTEXT_KEY: _ENTRY_FACTORY_TOKEN},
        )
