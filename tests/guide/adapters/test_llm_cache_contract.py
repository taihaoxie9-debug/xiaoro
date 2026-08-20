from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import ClassVar

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from app.guide.adapters.llm.contracts import (
    LLMCacheEntry,
    LLMCacheKey,
    LLMGenerationParameters,
    LLMSuccessStatus,
)


class ValidatedRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: ClassVar[str] = "structured-understanding-v2"

    goal: str
    candidate_ids: list[str]
    confidence: float
    attributes: dict[str, str]


class OtherSchemaRecommendation(ValidatedRecommendation):
    schema_version: ClassVar[str] = "structured-understanding-v3"


class DifferentModelSameVersion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: ClassVar[str] = ValidatedRecommendation.schema_version

    unrelated_value: int


class UnversionedResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    goal: str


def valid_key_data() -> dict[str, object]:
    return {
        "stage": "legacy-intent-v3",
        "provider": "primary-provider",
        "base_url": "https://primary.invalid",
        "model": "primary-model",
        "prompt_version": "recommendation-v3",
        "schema_version": ValidatedRecommendation.schema_version,
        "context_sha256": "a" * 64,
        "generation_parameters": LLMGenerationParameters(
            temperature=0.2,
            max_tokens=512,
            enable_thinking=False,
        ),
    }


def valid_key() -> LLMCacheKey:
    return LLMCacheKey(**valid_key_data())


def validated_result(
    *,
    attributes: dict[str, str] | None = None,
) -> ValidatedRecommendation:
    return ValidatedRecommendation(
        goal="compare",
        candidate_ids=["sku-1", "sku-2"],
        confidence=0.91,
        attributes=attributes or {"material": "steel", "size": "compact"},
    )


def create_entry(
    *,
    key: LLMCacheKey | None = None,
    result: BaseModel | object | None = None,
    result_schema: type[BaseModel] | object = ValidatedRecommendation,
    actual_provider: object = "primary-provider",
    actual_model: object = "primary-model",
    status: object = LLMSuccessStatus.PRIMARY_SUCCESS,
) -> LLMCacheEntry:
    return LLMCacheEntry.from_validated_result(
        key=key or valid_key(),
        result=result or validated_result(),
        result_schema=result_schema,
        actual_provider=actual_provider,
        actual_model=actual_model,
        status=status,
    )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("stage", "detail:recommendation"),
        ("provider", "fallback-provider"),
        ("base_url", "https://fallback.invalid"),
        ("model", "fallback-model"),
        ("prompt_version", "recommendation-v4"),
        ("schema_version", "structured-understanding-v3"),
        ("context_sha256", "b" * 64),
        ("temperature", 0.7),
        ("max_tokens", 1024),
        ("enable_thinking", True),
    ],
)
def test_cache_key_fingerprint_isolates_every_identity_dimension(
    field: str,
    replacement: object,
) -> None:
    baseline_data = valid_key_data()
    changed_data = deepcopy(baseline_data)

    if field in {"temperature", "max_tokens", "enable_thinking"}:
        parameters = changed_data["generation_parameters"]
        assert isinstance(parameters, LLMGenerationParameters)
        changed_data["generation_parameters"] = parameters.model_copy(
            update={field: replacement}
        )
    else:
        changed_data[field] = replacement

    baseline = LLMCacheKey(**baseline_data)
    changed = LLMCacheKey(**changed_data)

    assert baseline.fingerprint() != changed.fingerprint()


def test_cache_key_fingerprint_distinguishes_thinking_mode() -> None:
    baseline = valid_key()
    enabled = baseline.model_copy(
        update={
            "generation_parameters": baseline.generation_parameters.model_copy(
                update={"enable_thinking": True}
            )
        }
    )

    assert baseline.generation_parameters.enable_thinking is False
    assert enabled.generation_parameters.enable_thinking is True
    assert baseline.fingerprint() != enabled.fingerprint()


def test_cache_key_isolates_base_url_and_official_thinking_contract() -> None:
    common = {
        **valid_key_data(),
        "provider": "deepseek_official",
        "model": "deepseek-v4-pro",
        "base_url": "https://api.deepseek.com",
        "generation_parameters": LLMGenerationParameters(
            temperature=0.0,
            max_tokens=128,
            enable_thinking=None,
            thinking={"type": "disabled"},
        ),
    }

    baseline = LLMCacheKey(**common)
    other_base_url = LLMCacheKey(
        **{
            **common,
            "base_url": "https://other.invalid",
        }
    )
    other_thinking_contract = LLMCacheKey(
        **{
            **common,
            "generation_parameters": LLMGenerationParameters(
                temperature=0.0,
                max_tokens=128,
                enable_thinking=False,
            ),
        }
    )

    assert baseline.base_url == "https://api.deepseek.com"
    assert baseline.generation_parameters.thinking is not None
    assert baseline.generation_parameters.thinking.type == "disabled"
    assert baseline.fingerprint() != other_base_url.fingerprint()
    assert baseline.fingerprint() != other_thinking_contract.fingerprint()


def test_cache_key_fingerprint_is_deterministic_canonical_sha256() -> None:
    key = valid_key()
    canonical_json = json.dumps(
        key.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    expected = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    assert key.fingerprint() == expected
    assert key.model_copy(deep=True).fingerprint() == expected
    assert len(expected) == 64


def test_fallback_entry_records_actual_provider_and_model() -> None:
    entry = create_entry(
        actual_provider="fallback-provider",
        actual_model="fallback-model",
        status=LLMSuccessStatus.FALLBACK_SUCCESS,
    )

    assert entry.actual_provider == "fallback-provider"
    assert entry.actual_model == "fallback-model"
    assert entry.status is LLMSuccessStatus.FALLBACK_SUCCESS


def test_all_cache_contract_models_enable_global_strict_mode() -> None:
    for model_type in (LLMGenerationParameters, LLMCacheKey, LLMCacheEntry):
        assert model_type.model_config["strict"] is True


@pytest.mark.parametrize(
    "parameters",
    [
        {"temperature": "0.2", "max_tokens": 512},
        {"temperature": 0.2, "max_tokens": "512"},
        {"temperature": 0.2, "max_tokens": True},
        {"temperature": 0.2, "max_tokens": 512.0},
        {"temperature": True, "max_tokens": 512},
        {
            "temperature": 0.2,
            "max_tokens": 512,
            "enable_thinking": "false",
        },
        {
            "temperature": 0.2,
            "max_tokens": 512,
            "enable_thinking": 0,
        },
    ],
)
def test_generation_parameters_reject_coercible_numbers(
    parameters: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        LLMGenerationParameters(**parameters)


@pytest.mark.parametrize(
    "temperature",
    [float("nan"), float("inf"), float("-inf")],
)
def test_generation_parameters_reject_non_finite_temperature(
    temperature: float,
) -> None:
    with pytest.raises(ValidationError):
        LLMGenerationParameters(temperature=temperature, max_tokens=512)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("stage", b"legacy-intent-v3"),
        ("provider", b"primary-provider"),
        ("base_url", b"https://primary.invalid"),
        ("model", b"primary-model"),
        ("prompt_version", b"recommendation-v3"),
        ("schema_version", b"structured-understanding-v2"),
        ("context_sha256", b"a" * 64),
    ],
)
def test_cache_key_rejects_bytes_for_string_fields(
    field: str,
    replacement: bytes,
) -> None:
    key_data = valid_key_data()
    key_data[field] = replacement

    with pytest.raises(ValidationError):
        LLMCacheKey(**key_data)


def test_cache_entry_rejects_coercible_factory_fields() -> None:
    with pytest.raises(ValidationError):
        create_entry(actual_provider=b"primary-provider")

    with pytest.raises(ValidationError):
        create_entry(actual_model=b"primary-model")

    with pytest.raises(ValidationError):
        create_entry(status="primary_success")


def test_cache_entry_factory_binds_schema_version_to_key() -> None:
    key = valid_key()

    entry = create_entry(key=key)

    assert entry.schema_version == key.schema_version
    assert entry.result == validated_result().model_dump(mode="json")


def test_cache_entry_factory_requires_exact_result_schema_identity() -> None:
    mismatched_result = OtherSchemaRecommendation(
        goal="compare",
        candidate_ids=["sku-1", "sku-2"],
        confidence=0.91,
        attributes={"material": "steel"},
    )

    with pytest.raises(ValueError, match="schema version"):
        create_entry(
            result=mismatched_result,
            result_schema=OtherSchemaRecommendation,
        )


def test_cache_entry_factory_requires_result_schema_protocol() -> None:
    with pytest.raises(TypeError, match="schema_version"):
        create_entry(
            result=UnversionedResult(goal="compare"),
            result_schema=UnversionedResult,
        )


@pytest.mark.parametrize("result_schema", [dict, validated_result()])
def test_cache_entry_factory_requires_pydantic_result_schema(
    result_schema: object,
) -> None:
    with pytest.raises(TypeError, match="BaseModel subclass"):
        create_entry(result_schema=result_schema)


def test_cache_entry_factory_rejects_different_model_with_same_version() -> None:
    different_result = DifferentModelSameVersion(unrelated_value=7)

    with pytest.raises(TypeError, match="exactly result_schema"):
        create_entry(result=different_result)


def test_cache_entry_factory_does_not_accept_caller_schema_version() -> None:
    with pytest.raises(TypeError):
        LLMCacheEntry.from_validated_result(
            key=valid_key(),
            result=validated_result(),
            result_schema=ValidatedRecommendation,
            actual_provider="primary-provider",
            actual_model="primary-model",
            status=LLMSuccessStatus.PRIMARY_SUCCESS,
            schema_version="forged-schema-v9",
        )


@pytest.mark.parametrize(
    "result",
    [
        {"goal": "compare"},
        "unvalidated prose",
        ["not", "an", "object"],
    ],
)
def test_cache_entry_factory_rejects_non_model_results(result: object) -> None:
    with pytest.raises(TypeError, match="Pydantic model"):
        create_entry(result=result)


def test_cache_entry_factory_revalidates_model_payload() -> None:
    invalid_result = ValidatedRecommendation.model_construct(
        goal=123,
        candidate_ids=["sku-1"],
        confidence=0.91,
        attributes={"material": "steel"},
    )

    with pytest.raises(ValidationError):
        create_entry(result=invalid_result)


def test_cache_entry_factory_is_the_only_normal_construction_path() -> None:
    with pytest.raises(ValidationError, match="from_validated_result"):
        LLMCacheEntry(
            result=validated_result().model_dump(mode="json"),
            schema_version=valid_key().schema_version,
            actual_provider="primary-provider",
            actual_model="primary-model",
            status=LLMSuccessStatus.PRIMARY_SUCCESS,
        )


def test_cache_entry_serialization_is_deterministic_and_json_compatible() -> None:
    first = create_entry(
        result=validated_result(attributes={"size": "compact", "material": "steel"})
    )
    second = create_entry(
        result=validated_result(attributes={"material": "steel", "size": "compact"})
    )

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.model_dump_json() == second.model_dump_json()
    assert json.loads(first.model_dump_json()) == first.model_dump(mode="json")


@pytest.mark.parametrize("status", ["failure", "timeout", "fallback_failure"])
def test_cache_entry_rejects_non_success_statuses(status: str) -> None:
    with pytest.raises(ValidationError):
        create_entry(status=status)


def test_cache_contracts_forbid_extra_fields() -> None:
    with pytest.raises(ValidationError):
        LLMGenerationParameters(
            temperature=0.2,
            max_tokens=512,
            top_p=0.9,
        )

    with pytest.raises(ValidationError):
        LLMCacheKey(**valid_key_data(), cache_namespace="guide")

    with pytest.raises(ValidationError, match="from_validated_result"):
        LLMCacheEntry(
            result=validated_result().model_dump(mode="json"),
            schema_version=valid_key().schema_version,
            actual_provider="primary-provider",
            actual_model="primary-model",
            status=LLMSuccessStatus.PRIMARY_SUCCESS,
            expires_at="2099-01-01T00:00:00Z",
        )
