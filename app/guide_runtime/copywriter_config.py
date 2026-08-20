from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
import math
import os
from typing import Self
from urllib.parse import urlsplit


class CopywriterConfigErrorCode(str, Enum):
    API_KEY_MISSING = "api_key_missing"
    INVALID_API_KEY = "invalid_api_key"
    INVALID_BASE_URL = "invalid_base_url"
    INVALID_MODEL = "invalid_model"
    MODEL_UNSELECTED = "model_unselected"
    INVALID_TIMEOUT = "invalid_timeout"
    INVALID_MAX_TOKENS = "invalid_max_tokens"
    INVALID_TEMPERATURE = "invalid_temperature"
    INVALID_DAILY_BUDGET = "invalid_daily_budget"
    INVALID_DAILY_CALL_CAP = "invalid_daily_call_cap"


class CopywriterConfigError(ValueError):
    def __init__(self, code: CopywriterConfigErrorCode) -> None:
        self.code = code
        super().__init__(
            f"Guide copywriter configuration invalid: {code.value}"
        )


@dataclass(frozen=True, slots=True)
class CopywriterLlmConfig:
    api_key: str | None = field(repr=False)
    base_url: str
    model: str | None
    timeout_seconds: float
    max_tokens: int
    temperature: float
    daily_budget_cny: Decimal
    daily_call_cap: int

    @property
    def is_ready(self) -> bool:
        return self.api_key is not None and self.model is not None

    def require_ready(self) -> Self:
        if self.api_key is None:
            raise CopywriterConfigError(
                CopywriterConfigErrorCode.API_KEY_MISSING
            )
        if self.model is None:
            raise CopywriterConfigError(
                CopywriterConfigErrorCode.MODEL_UNSELECTED
            )
        return self

    @classmethod
    def from_environment(cls) -> Self:
        return cls(
            api_key=_read_key(),
            base_url=_read_url(),
            model=_read_model(),
            timeout_seconds=_read_float(
                "GUIDE_COPY_LLM_TIMEOUT_SECONDS",
                default="15",
                minimum=0.5,
                maximum=30.0,
                code=CopywriterConfigErrorCode.INVALID_TIMEOUT,
            ),
            max_tokens=_read_int(
                "GUIDE_COPY_LLM_MAX_TOKENS",
                default="1536",
                minimum=64,
                maximum=4096,
                code=CopywriterConfigErrorCode.INVALID_MAX_TOKENS,
            ),
            temperature=_read_float(
                "GUIDE_COPY_LLM_TEMPERATURE",
                default="0.3",
                minimum=0.0,
                maximum=1.0,
                code=CopywriterConfigErrorCode.INVALID_TEMPERATURE,
            ),
            daily_budget_cny=_read_decimal(
                "GUIDE_COPY_LLM_DAILY_BUDGET_CNY",
                default="2.00",
                minimum=Decimal("0.01"),
                maximum=Decimal("10000"),
                code=CopywriterConfigErrorCode.INVALID_DAILY_BUDGET,
            ),
            daily_call_cap=_read_int(
                "GUIDE_COPY_LLM_DAILY_CALL_CAP",
                default="200",
                minimum=1,
                maximum=100000,
                code=CopywriterConfigErrorCode.INVALID_DAILY_CALL_CAP,
            ),
        )


def _read_key() -> str | None:
    raw = os.environ.get("GUIDE_COPY_LLM_API_KEY")
    if raw is None or not raw.strip():
        return None
    value = raw.strip()
    if len(value) > 1024 or _contains_control(value):
        raise CopywriterConfigError(
            CopywriterConfigErrorCode.INVALID_API_KEY
        )
    return value


def _read_url() -> str:
    raw = os.environ.get(
        "GUIDE_COPY_LLM_BASE_URL",
        "https://api.siliconflow.cn/v1",
    )
    value = raw.rstrip("/")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise CopywriterConfigError(
            CopywriterConfigErrorCode.INVALID_BASE_URL
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
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise CopywriterConfigError(
            CopywriterConfigErrorCode.INVALID_BASE_URL
        )
    return value


def _read_model() -> str | None:
    raw = os.environ.get("GUIDE_COPY_LLM_MODEL")
    if raw is None:
        return None
    value = raw.strip()
    if (
        not value
        or len(value) > 256
        or _contains_control(value)
    ):
        raise CopywriterConfigError(
            CopywriterConfigErrorCode.INVALID_MODEL
        )
    return value


def _read_float(
    name: str,
    *,
    default: str,
    minimum: float,
    maximum: float,
    code: CopywriterConfigErrorCode,
) -> float:
    try:
        value = float(os.environ.get(name, default))
    except (TypeError, ValueError):
        raise CopywriterConfigError(code) from None
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise CopywriterConfigError(code)
    return value


def _read_int(
    name: str,
    *,
    default: str,
    minimum: int,
    maximum: int,
    code: CopywriterConfigErrorCode,
) -> int:
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        raise CopywriterConfigError(code) from None
    if not minimum <= value <= maximum:
        raise CopywriterConfigError(code)
    return value


def _read_decimal(
    name: str,
    *,
    default: str,
    minimum: Decimal,
    maximum: Decimal,
    code: CopywriterConfigErrorCode,
) -> Decimal:
    try:
        value = Decimal(os.environ.get(name, default))
    except (InvalidOperation, TypeError, ValueError):
        raise CopywriterConfigError(code) from None
    if not value.is_finite() or not minimum <= value <= maximum:
        raise CopywriterConfigError(code)
    return value


def _contains_control(value: str) -> bool:
    return any(
        ord(character) < 32 or ord(character) == 127
        for character in value
    )


__all__ = [
    "CopywriterConfigError",
    "CopywriterConfigErrorCode",
    "CopywriterLlmConfig",
]
