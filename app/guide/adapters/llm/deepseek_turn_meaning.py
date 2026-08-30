from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal

import httpx

from app.guide.adapters.llm.deepseek_intent import (
    DEEPSEEK_OFFICIAL_BASE_URL,
)
from app.guide.adapters.llm.provider_common import UsageLimiter
from app.guide.adapters.llm.turn_meaning_adapter import (
    TurnMeaningAdapterBase,
)
from app.guide.understanding.turn_meaning_contracts import (
    EXPLORE_RECOMMENDATION_BASES,
    FIT_RECOMMENDATION_BASES,
    TurnMeaning,
)


_DEEPSEEK_STRICT_TOOLS_BASE_URL = (
    f"{DEEPSEEK_OFFICIAL_BASE_URL}/beta"
)
_TURN_MEANING_TOOL_NAME = "emit_turn_meaning"


class DeepSeekTurnMeaningAdapter(TurnMeaningAdapterBase):
    response_tool_name = _TURN_MEANING_TOOL_NAME

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        max_tokens: int,
        concept_catalog: tuple[str, ...],
        daily_budget_cny: Decimal = Decimal("1.00"),
        daily_call_cap: int = 200,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        usage_limiter: UsageLimiter | None = None,
    ) -> None:
        super().__init__(
            provider="deepseek_official",
            api_key=api_key,
            base_url=_DEEPSEEK_STRICT_TOOLS_BASE_URL,
            model=model,
            timeout_seconds=timeout_seconds,
            max_tokens=max_tokens,
            concept_catalog=concept_catalog,
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
        body = self._base_request_body(messages)
        body.pop("response_format")
        return {
            **body,
            "thinking": {"type": "disabled"},
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": _TURN_MEANING_TOOL_NAME,
                        "description": (
                            "Emit one typed turn-meaning contract."
                        ),
                        "strict": True,
                        "parameters": _strict_turn_meaning_schema(),
                    },
                }
            ],
            "tool_choice": {
                "type": "function",
                "function": {"name": _TURN_MEANING_TOOL_NAME},
            },
        }


def _strict_turn_meaning_schema() -> dict[str, object]:
    raw_schema = TurnMeaning.model_json_schema()
    raw_definitions = raw_schema.pop("$defs", {})
    if not isinstance(raw_definitions, dict):
        raise ValueError("turn meaning schema definitions are invalid")
    schema = _inline_strict_schema(
        raw_schema,
        definitions=raw_definitions,
    )
    if not isinstance(schema, dict):
        raise AssertionError("strict turn meaning schema is not an object")

    root_properties = schema.get("properties")
    if not isinstance(root_properties, dict):
        raise AssertionError("turn meaning properties are invalid")
    operation_schema = root_properties.get("operation_hint")
    if not isinstance(operation_schema, dict):
        raise AssertionError("turn meaning operation schema is invalid")
    operation_values = operation_schema.get("enum")
    if not isinstance(operation_values, list):
        raise AssertionError("turn meaning operation values are invalid")
    non_recommendation_operations = tuple(
        operation
        for operation in operation_values
        if operation not in {"recommendation", "image_similarity"}
    )

    variants: list[dict[str, object]] = []
    for operations, mode, count, bases in (
        (non_recommendation_operations, "none", None, ()),
        (
            ("recommendation",),
            "explore",
            {
                "anyOf": [
                    {"type": "null"},
                    {"type": "integer", "enum": [2, 3, 4]},
                ]
            },
            tuple(sorted(
                EXPLORE_RECOMMENDATION_BASES
                - {"similar_alternatives"}
            )),
        ),
        (
            ("image_similarity",),
            "explore",
            {
                "anyOf": [
                    {"type": "null"},
                    {"type": "integer", "enum": [2, 3, 4]},
                ]
            },
            ("similar_alternatives",),
        ),
        (
            ("recommendation", "image_similarity"),
            "fit",
            {"type": "integer", "enum": [1]},
            tuple(sorted(FIT_RECOMMENDATION_BASES)),
        ),
    ):
        variant: dict[str, object] = {"properties": {}}
        properties = variant["properties"]
        assert isinstance(properties, dict)
        properties["operation_hint"] = {
            "type": "string",
            "enum": list(operations),
        }
        if mode == "none":
            properties["recommendation_mode"] = {"type": "null"}
            properties["recommendation_count"] = {"type": "null"}
            properties["recommendation_mode_basis"] = {"type": "null"}
        else:
            properties["recommendation_mode"] = {
                "type": "string",
                "enum": [mode],
            }
            properties["recommendation_count"] = count
            properties["recommendation_mode_basis"] = (
                _recommendation_basis_schema(
                    schema=schema,
                    allowed_bases=bases,
                )
            )
        variants.append(variant)
    return {**schema, "anyOf": variants}


def _recommendation_basis_schema(
    *,
    schema: dict[str, object],
    allowed_bases: tuple[str, ...],
) -> dict[str, object]:
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        raise AssertionError("turn meaning properties are invalid")
    candidate = properties.get("recommendation_mode_basis")
    if not isinstance(candidate, dict):
        raise AssertionError("recommendation basis schema is invalid")
    options = candidate.get("anyOf")
    if not isinstance(options, list):
        raise AssertionError("recommendation basis options are invalid")
    basis_schema = next(
        (
            deepcopy(option)
            for option in options
            if isinstance(option, dict) and option.get("type") == "object"
        ),
        None,
    )
    if basis_schema is None:
        raise AssertionError("recommendation basis object is unavailable")
    basis_properties = basis_schema.get("properties")
    if not isinstance(basis_properties, dict):
        raise AssertionError("recommendation basis properties are invalid")
    basis_properties["basis"] = {
        "type": "string",
        "enum": list(allowed_bases),
    }
    return basis_schema


def _inline_strict_schema(
    value: object,
    *,
    definitions: dict[str, object],
) -> object:
    if isinstance(value, list):
        return [
            _inline_strict_schema(item, definitions=definitions)
            for item in value
        ]
    if not isinstance(value, dict):
        return value
    reference = value.get("$ref")
    if isinstance(reference, str):
        prefix = "#/$defs/"
        if not reference.startswith(prefix):
            raise ValueError("turn meaning schema reference is unsupported")
        definition_name = reference.removeprefix(prefix)
        definition = definitions.get(definition_name)
        if definition is None:
            raise ValueError("turn meaning schema reference is missing")
        merged = {
            **deepcopy(definition),
            **{
                key: item
                for key, item in value.items()
                if key != "$ref"
            },
        }
        return _inline_strict_schema(
            merged,
            definitions=definitions,
        )
    output = {
        key: _inline_strict_schema(item, definitions=definitions)
        for key, item in value.items()
        if key
        not in {
            "default",
            "maxItems",
            "maxLength",
            "minItems",
            "minLength",
            "title",
        }
    }
    if output.get("type") == "object":
        properties = output.get("properties")
        if isinstance(properties, dict):
            output["required"] = list(properties)
            output["additionalProperties"] = False
    return output


__all__ = ["DeepSeekTurnMeaningAdapter"]
