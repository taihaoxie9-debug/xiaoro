from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
import math
import os
from typing import Self
from urllib.parse import urlsplit


class GuideLlmConfigErrorCode(str, Enum):
    API_KEY_MISSING = "api_key_missing"
    INVALID_API_KEY = "invalid_api_key"
    INVALID_BASE_URL = "invalid_base_url"
    INVALID_MODEL = "invalid_model"
    MODEL_UNSELECTED = "model_unselected"
    INVALID_TIMEOUT = "invalid_timeout"
    INVALID_MAX_TOKENS = "invalid_max_tokens"
    INVALID_DAILY_BUDGET = "invalid_daily_budget"
    INVALID_DAILY_CALL_CAP = "invalid_daily_call_cap"
    INVALID_FORMAT_REPAIR_ATTEMPTS = (
        "invalid_format_repair_attempts"
    )


class GuideLlmConfigError(ValueError):
    def __init__(self, code: GuideLlmConfigErrorCode) -> None:
        self.code = code
        super().__init__(f"Guide LLM configuration invalid: {code.value}")


@dataclass(frozen=True, slots=True)
class GuideLlmConfig:
    api_key: str | None = field(repr=False)
    base_url: str
    model: str | None
    timeout_seconds: float
    max_tokens: int
    daily_budget_cny: Decimal
    daily_call_cap: int
    format_repair_attempts: int
    enable_thinking: bool = False

    @property
    def is_ready(self) -> bool:
        return self.api_key is not None and self.model is not None

    def require_ready(self) -> Self:
        if self.api_key is None:
            raise GuideLlmConfigError(
                GuideLlmConfigErrorCode.API_KEY_MISSING
            )
        if self.model is None:
            raise GuideLlmConfigError(
                GuideLlmConfigErrorCode.MODEL_UNSELECTED
            )
        return self

    @classmethod
    def from_environment(cls) -> Self:
        return cls(
            api_key=_read_api_key(),
            base_url=_read_base_url(),
            model=_read_model(),
            timeout_seconds=_read_float(
                "GUIDE_LLM_TIMEOUT_SECONDS",
                default="12",
                minimum=0.5,
                maximum=30.0,
                code=GuideLlmConfigErrorCode.INVALID_TIMEOUT,
            ),
            max_tokens=_read_int(
                "GUIDE_LLM_MAX_TOKENS",
                default="1024",
                minimum=64,
                maximum=2048,
                code=GuideLlmConfigErrorCode.INVALID_MAX_TOKENS,
            ),
            daily_budget_cny=_read_decimal(
                "GUIDE_LLM_DAILY_BUDGET_CNY",
                default="1.00",
                minimum=Decimal("0.01"),
                maximum=Decimal("10000"),
                code=GuideLlmConfigErrorCode.INVALID_DAILY_BUDGET,
            ),
            daily_call_cap=_read_int(
                "GUIDE_LLM_DAILY_CALL_CAP",
                default="200",
                minimum=1,
                maximum=100000,
                code=GuideLlmConfigErrorCode.INVALID_DAILY_CALL_CAP,
            ),
            format_repair_attempts=_read_int(
                "GUIDE_LLM_FORMAT_REPAIR_ATTEMPTS",
                default="0",
                minimum=0,
                maximum=1,
                code=(
                    GuideLlmConfigErrorCode
                    .INVALID_FORMAT_REPAIR_ATTEMPTS
                ),
            ),
            enable_thinking=False,
        )


def _read_api_key() -> str | None:
    raw_value = os.environ.get("GUIDE_LLM_API_KEY")
    if raw_value is None or not raw_value.strip():
        return None
    value = raw_value.strip()
    if len(value) > 1024 or _contains_control(value):
        raise GuideLlmConfigError(
            GuideLlmConfigErrorCode.INVALID_API_KEY
        )
    return value


def _read_base_url() -> str:
    raw_value = os.environ.get(
        "GUIDE_LLM_BASE_URL",
        "https://api.siliconflow.cn/v1",
    )
    value = raw_value.rstrip("/")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise GuideLlmConfigError(
            GuideLlmConfigErrorCode.INVALID_BASE_URL
        ) from None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or _contains_control(value)
        or any(character.isspace() for character in value)
        or (
            port is not None
            and not 1 <= port <= 65535
        )
    ):
        raise GuideLlmConfigError(
            GuideLlmConfigErrorCode.INVALID_BASE_URL
        )
    return value


def _read_model() -> str | None:
    raw_value = os.environ.get("GUIDE_LLM_MODEL")
    if raw_value is None:
        return None
    value = raw_value.strip()
    if (
        not value
        or len(value) > 256
        or _contains_control(value)
    ):
        raise GuideLlmConfigError(
            GuideLlmConfigErrorCode.INVALID_MODEL
        )
    return value


def _read_float(
    name: str,
    *,
    default: str,
    minimum: float,
    maximum: float,
    code: GuideLlmConfigErrorCode,
) -> float:
    try:
        value = float(os.environ.get(name, default))
    except (TypeError, ValueError):
        raise GuideLlmConfigError(code) from None
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise GuideLlmConfigError(code)
    return value


def _read_int(
    name: str,
    *,
    default: str,
    minimum: int,
    maximum: int,
    code: GuideLlmConfigErrorCode,
) -> int:
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        raise GuideLlmConfigError(code) from None
    if not minimum <= value <= maximum:
        raise GuideLlmConfigError(code)
    return value


def _read_decimal(
    name: str,
    *,
    default: str,
    minimum: Decimal,
    maximum: Decimal,
    code: GuideLlmConfigErrorCode,
) -> Decimal:
    try:
        value = Decimal(os.environ.get(name, default))
    except (InvalidOperation, TypeError, ValueError):
        raise GuideLlmConfigError(code) from None
    if not value.is_finite() or not minimum <= value <= maximum:
        raise GuideLlmConfigError(code)
    return value


def _contains_control(value: str) -> bool:
    return any(
        ord(character) < 32 or ord(character) == 127
        for character in value
    )
