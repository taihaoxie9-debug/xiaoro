from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
from threading import Condition
from typing import Iterator, Protocol, Self
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from pydantic import ValidationError

from app.guide.adapters.llm.contracts import (
    SemanticProviderFailure,
    SemanticProviderFailureCode,
    SemanticTokenUsage,
)
from app.guide.adapters.state.trusted_sqlite_storage import (
    TrustedSqliteStorage,
)


_TRACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_PROVIDER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
MAX_PROVIDER_RESPONSE_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class UsageReservation:
    day: date
    amount_cny: Decimal
    provider: str | None = None
    reservation_id: str | None = None


@dataclass(frozen=True, slots=True)
class JsonCompletion:
    content: str
    trace_id: str
    usage: dict[str, int | None]
    actual_cost_cny: Decimal | None


class UsageLimiter(Protocol):
    def reserve(self) -> UsageReservation: ...

    def record_actual_cost(
        self,
        reservation: UsageReservation,
        actual_cost_cny: Decimal | None,
    ) -> None: ...


class DailyUsageLimiter:
    def __init__(
        self,
        *,
        daily_budget_cny: Decimal,
        daily_call_cap: int,
        clock: Callable[[], datetime],
    ) -> None:
        if (
            not isinstance(daily_budget_cny, Decimal)
            or not daily_budget_cny.is_finite()
            or daily_budget_cny <= 0
        ):
            raise ValueError("daily budget must be a positive Decimal")
        if (
            not isinstance(daily_call_cap, int)
            or isinstance(daily_call_cap, bool)
            or daily_call_cap <= 0
        ):
            raise ValueError("daily call cap must be a positive integer")
        self._daily_budget_cny = daily_budget_cny
        self._daily_call_cap = daily_call_cap
        self._reservation_cny = daily_budget_cny / daily_call_cap
        self._clock = clock
        self._condition = Condition()
        self._day: date | None = None
        self._call_count = 0
        self._reserved_or_spent_cny = Decimal("0")
        self._request_in_flight = False

    def reserve(self) -> UsageReservation:
        with self._condition:
            while self._request_in_flight:
                self._condition.wait()
            day = self._current_day()
            self._reset_if_needed(day)
            if self._call_count >= self._daily_call_cap:
                raise SemanticProviderFailure(
                    SemanticProviderFailureCode.DAILY_CALL_CAP_EXCEEDED
                )
            if (
                self._reserved_or_spent_cny >= self._daily_budget_cny
                or self._reserved_or_spent_cny + self._reservation_cny
                > self._daily_budget_cny
            ):
                raise SemanticProviderFailure(
                    SemanticProviderFailureCode.DAILY_BUDGET_EXCEEDED
                )
            self._call_count += 1
            self._reserved_or_spent_cny += self._reservation_cny
            self._request_in_flight = True
            if self._day is None:
                raise AssertionError("usage limiter day is unavailable")
            return UsageReservation(
                day=self._day,
                amount_cny=self._reservation_cny,
            )

    def record_actual_cost(
        self,
        reservation: UsageReservation,
        actual_cost_cny: Decimal | None,
    ) -> None:
        with self._condition:
            if (
                self._day == reservation.day
                and actual_cost_cny is not None
                and actual_cost_cny.is_finite()
                and actual_cost_cny >= 0
            ):
                self._reserved_or_spent_cny += (
                    actual_cost_cny - reservation.amount_cny
                )
            self._request_in_flight = False
            self._condition.notify_all()

    def _current_day(self) -> date:
        current = self._clock()
        if not isinstance(current, datetime):
            raise RuntimeError("usage limiter clock must return datetime")
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        return current.astimezone(UTC).date()

    def _reset_if_needed(self, day: date) -> None:
        if self._day is not None and day <= self._day:
            return
        self._day = day
        self._call_count = 0
        self._reserved_or_spent_cny = Decimal("0")


class SqliteDailyUsageLimiter:
    """Atomic provider/day quota stored below one trusted state root."""

    def __init__(
        self,
        database_path: str | os.PathLike[str],
        *,
        trusted_state_root: str | os.PathLike[str],
        provider: str,
        daily_budget_cny: Decimal,
        daily_call_cap: int,
        clock: Callable[[], datetime],
    ) -> None:
        _validate_usage_limits(
            daily_budget_cny=daily_budget_cny,
            daily_call_cap=daily_call_cap,
        )
        if (
            not isinstance(provider, str)
            or _PROVIDER_PATTERN.fullmatch(provider) is None
        ):
            raise ValueError("provider must be a bounded identifier")
        self._provider = provider
        self._daily_budget_cny = daily_budget_cny
        self._daily_call_cap = daily_call_cap
        self._reservation_cny = daily_budget_cny / daily_call_cap
        self._clock = clock
        self._storage = TrustedSqliteStorage(
            database_path,
            trusted_state_root=trusted_state_root,
        )
        with self._storage.initialize() as (connection, _created):
            journal_mode = connection.execute(
                "PRAGMA journal_mode = WAL"
            ).fetchone()
            if journal_mode != ("wal",):
                raise sqlite3.DatabaseError("WAL mode is unavailable")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS provider_daily_usage (
                    provider TEXT NOT NULL,
                    usage_day TEXT NOT NULL,
                    call_count INTEGER NOT NULL
                        CHECK (call_count >= 0),
                    reserved_or_spent_cny TEXT NOT NULL,
                    PRIMARY KEY (provider, usage_day)
                );
                CREATE TABLE IF NOT EXISTS provider_usage_reservations (
                    reservation_id TEXT PRIMARY KEY
                        CHECK (length(reservation_id) = 32),
                    provider TEXT NOT NULL,
                    usage_day TEXT NOT NULL,
                    reserved_cny TEXT NOT NULL,
                    settled INTEGER NOT NULL DEFAULT 0
                        CHECK (settled IN (0, 1))
                );
                CREATE INDEX IF NOT EXISTS
                    provider_usage_reservation_day_idx
                ON provider_usage_reservations (provider, usage_day);
                """
            )

    @property
    def database_path(self) -> Path:
        return self._storage.database_path

    @property
    def provider(self) -> str:
        return self._provider

    def reserve(self) -> UsageReservation:
        day = _utc_day(self._clock)
        reservation_id = uuid4().hex
        try:
            with self._transaction() as connection:
                row = connection.execute(
                    """
                    SELECT call_count, reserved_or_spent_cny
                    FROM provider_daily_usage
                    WHERE provider = ? AND usage_day = ?
                    """,
                    (self._provider, day.isoformat()),
                ).fetchone()
                call_count, accounted_cost = self._usage_values(row)
                if call_count >= self._daily_call_cap:
                    raise SemanticProviderFailure(
                        SemanticProviderFailureCode
                        .DAILY_CALL_CAP_EXCEEDED
                    )
                if (
                    accounted_cost >= self._daily_budget_cny
                    or accounted_cost + self._reservation_cny
                    > self._daily_budget_cny
                ):
                    raise SemanticProviderFailure(
                        SemanticProviderFailureCode
                        .DAILY_BUDGET_EXCEEDED
                    )
                next_cost = accounted_cost + self._reservation_cny
                connection.execute(
                    """
                    INSERT INTO provider_daily_usage (
                        provider,
                        usage_day,
                        call_count,
                        reserved_or_spent_cny
                    )
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(provider, usage_day) DO UPDATE SET
                        call_count = excluded.call_count,
                        reserved_or_spent_cny = (
                            excluded.reserved_or_spent_cny
                        )
                    """,
                    (
                        self._provider,
                        day.isoformat(),
                        call_count + 1,
                        str(next_cost),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO provider_usage_reservations (
                        reservation_id,
                        provider,
                        usage_day,
                        reserved_cny,
                        settled
                    )
                    VALUES (?, ?, ?, ?, 0)
                    """,
                    (
                        reservation_id,
                        self._provider,
                        day.isoformat(),
                        str(self._reservation_cny),
                    ),
                )
        except SemanticProviderFailure:
            raise
        except (OSError, RuntimeError, sqlite3.Error, ValueError):
            raise SemanticProviderFailure(
                SemanticProviderFailureCode.PROVIDER_UNAVAILABLE
            ) from None
        return UsageReservation(
            day=day,
            amount_cny=self._reservation_cny,
            provider=self._provider,
            reservation_id=reservation_id,
        )

    def record_actual_cost(
        self,
        reservation: UsageReservation,
        actual_cost_cny: Decimal | None,
    ) -> None:
        if (
            not isinstance(reservation, UsageReservation)
            or reservation.provider != self._provider
            or reservation.reservation_id is None
        ):
            raise ValueError(
                "reservation does not belong to this provider quota"
            )
        try:
            with self._transaction() as connection:
                row = connection.execute(
                    """
                    SELECT reserved_cny, settled
                    FROM provider_usage_reservations
                    WHERE reservation_id = ?
                      AND provider = ?
                      AND usage_day = ?
                    """,
                    (
                        reservation.reservation_id,
                        self._provider,
                        reservation.day.isoformat(),
                    ),
                ).fetchone()
                if row is None:
                    raise ValueError("provider reservation is unavailable")
                reserved_cost = _stored_decimal(row[0])
                if int(row[1]) == 1:
                    return
                final_cost = (
                    actual_cost_cny
                    if (
                        actual_cost_cny is not None
                        and actual_cost_cny.is_finite()
                        and actual_cost_cny >= 0
                    )
                    else reserved_cost
                )
                usage_row = connection.execute(
                    """
                    SELECT reserved_or_spent_cny
                    FROM provider_daily_usage
                    WHERE provider = ? AND usage_day = ?
                    """,
                    (self._provider, reservation.day.isoformat()),
                ).fetchone()
                if usage_row is None:
                    raise ValueError("provider usage row is unavailable")
                accounted_cost = _stored_decimal(usage_row[0])
                connection.execute(
                    """
                    UPDATE provider_daily_usage
                    SET reserved_or_spent_cny = ?
                    WHERE provider = ? AND usage_day = ?
                    """,
                    (
                        str(accounted_cost + final_cost - reserved_cost),
                        self._provider,
                        reservation.day.isoformat(),
                    ),
                )
                connection.execute(
                    """
                    UPDATE provider_usage_reservations
                    SET settled = 1
                    WHERE reservation_id = ?
                    """,
                    (reservation.reservation_id,),
                )
        except SemanticProviderFailure:
            raise
        except (OSError, RuntimeError, sqlite3.Error, ValueError):
            raise SemanticProviderFailure(
                SemanticProviderFailureCode.PROVIDER_UNAVAILABLE
            ) from None

    @staticmethod
    def _usage_values(row: object) -> tuple[int, Decimal]:
        if row is None:
            return 0, Decimal("0")
        if (
            not isinstance(row, tuple)
            or len(row) != 2
            or not isinstance(row[0], int)
            or isinstance(row[0], bool)
            or row[0] < 0
        ):
            raise ValueError("invalid provider usage row")
        return row[0], _stored_decimal(row[1])

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._storage.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()


class OpenAIJsonClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None,
    ) -> None:
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

    def request(
        self,
        body: Mapping[str, object],
        *,
        tool_name: str | None = None,
    ) -> JsonCompletion:
        try:
            with self._client.stream(
                "POST",
                "chat/completions",
                json=dict(body),
            ) as response:
                if not 200 <= response.status_code < 300:
                    code = http_failure_code(response.status_code)
                    raise SemanticProviderFailure(
                        code,
                        status_code=response.status_code,
                    ) from None
                payload = _read_bounded_response(response)
                trace_header = (
                    response.headers.get("x-request-id")
                    or response.headers.get("request-id")
                )
        except httpx.TimeoutException:
            raise SemanticProviderFailure(
                SemanticProviderFailureCode.TIMEOUT
            ) from None
        except httpx.HTTPError:
            raise SemanticProviderFailure(
                SemanticProviderFailureCode.PROVIDER_UNAVAILABLE
            ) from None

        try:
            envelope = json.loads(payload)
        except ValueError:
            raise SemanticProviderFailure(
                SemanticProviderFailureCode.INVALID_RESPONSE
            ) from None

        content = (
            extract_tool_arguments(envelope, tool_name)
            if tool_name is not None
            else extract_content(envelope)
        )
        usage, actual_cost = extract_usage(envelope)
        trace_id = safe_trace_id(trace_header)
        return JsonCompletion(
            content=content,
            trace_id=trace_id,
            usage=usage,
            actual_cost_cny=actual_cost,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def _read_bounded_response(response: httpx.Response) -> bytes:
    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError:
            raise SemanticProviderFailure(
                SemanticProviderFailureCode.INVALID_RESPONSE
            ) from None
        if (
            declared_length < 0
            or declared_length > MAX_PROVIDER_RESPONSE_BYTES
        ):
            raise SemanticProviderFailure(
                SemanticProviderFailureCode.INVALID_RESPONSE
            )

    chunks: list[bytes] = []
    observed_length = 0
    for chunk in response.iter_bytes():
        observed_length += len(chunk)
        if observed_length > MAX_PROVIDER_RESPONSE_BYTES:
            raise SemanticProviderFailure(
                SemanticProviderFailureCode.INVALID_RESPONSE
            )
        chunks.append(chunk)
    payload = b"".join(chunks)
    if not payload:
        raise SemanticProviderFailure(
            SemanticProviderFailureCode.EMPTY_RESPONSE
        )
    return payload


def _validate_usage_limits(
    *,
    daily_budget_cny: Decimal,
    daily_call_cap: int,
) -> None:
    if (
        not isinstance(daily_budget_cny, Decimal)
        or not daily_budget_cny.is_finite()
        or daily_budget_cny <= 0
    ):
        raise ValueError("daily budget must be a positive Decimal")
    if (
        not isinstance(daily_call_cap, int)
        or isinstance(daily_call_cap, bool)
        or daily_call_cap <= 0
    ):
        raise ValueError("daily call cap must be a positive integer")


def _utc_day(clock: Callable[[], datetime]) -> date:
    current = clock()
    if not isinstance(current, datetime):
        raise RuntimeError("usage limiter clock must return datetime")
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).date()


def _stored_decimal(value: object) -> Decimal:
    try:
        parsed = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("invalid stored provider quota") from None
    if not parsed.is_finite() or parsed < 0:
        raise ValueError("invalid stored provider quota")
    return parsed


def validate_adapter_settings(
    *,
    api_key: str,
    base_url: str,
    model: str,
    timeout_seconds: float,
    max_tokens: int,
    format_repair_attempts: int,
    enable_thinking: bool | None = None,
) -> str:
    if (
        not isinstance(api_key, str)
        or not api_key.strip()
        or contains_control(api_key)
    ):
        raise ValueError("invalid adapter API key")
    if (
        not isinstance(model, str)
        or not model.strip()
        or contains_control(model)
    ):
        raise ValueError("invalid adapter model")
    try:
        parsed = urlsplit(base_url)
    except (TypeError, ValueError):
        raise ValueError("invalid adapter base URL") from None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("invalid adapter base URL")
    if (
        not isinstance(timeout_seconds, (int, float))
        or isinstance(timeout_seconds, bool)
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise ValueError("invalid adapter timeout")
    if (
        not isinstance(max_tokens, int)
        or isinstance(max_tokens, bool)
        or not 1 <= max_tokens <= 2048
    ):
        raise ValueError("invalid adapter max tokens")
    if enable_thinking is not None and not isinstance(
        enable_thinking,
        bool,
    ):
        raise ValueError("invalid adapter thinking mode")
    if (
        not isinstance(format_repair_attempts, int)
        or isinstance(format_repair_attempts, bool)
        or not 0 <= format_repair_attempts <= 1
    ):
        raise ValueError("invalid adapter format repair attempts")
    return base_url.rstrip("/")


def http_failure_code(status_code: int) -> SemanticProviderFailureCode:
    if status_code in {401, 403}:
        return SemanticProviderFailureCode.AUTHENTICATION_FAILED
    if status_code == 429:
        return SemanticProviderFailureCode.RATE_LIMITED
    if 500 <= status_code <= 599:
        return SemanticProviderFailureCode.PROVIDER_UNAVAILABLE
    return SemanticProviderFailureCode.PROVIDER_REJECTED


def extract_content(envelope: object) -> str:
    if not isinstance(envelope, Mapping):
        raise SemanticProviderFailure(
            SemanticProviderFailureCode.INVALID_RESPONSE
        )
    choices = envelope.get("choices")
    if not isinstance(choices, list) or not choices:
        raise SemanticProviderFailure(
            SemanticProviderFailureCode.EMPTY_RESPONSE
        )
    choice = choices[0]
    if not isinstance(choice, Mapping):
        raise SemanticProviderFailure(
            SemanticProviderFailureCode.INVALID_RESPONSE
        )
    message = choice.get("message")
    if not isinstance(message, Mapping):
        raise SemanticProviderFailure(
            SemanticProviderFailureCode.EMPTY_RESPONSE
        )
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise SemanticProviderFailure(
            SemanticProviderFailureCode.EMPTY_RESPONSE
        )
    return content


def extract_tool_arguments(
    envelope: object,
    expected_tool_name: str,
) -> str:
    if not isinstance(envelope, Mapping):
        raise SemanticProviderFailure(
            SemanticProviderFailureCode.INVALID_RESPONSE
        )
    choices = envelope.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise SemanticProviderFailure(
            SemanticProviderFailureCode.INVALID_RESPONSE
        )
    choice = choices[0]
    if not isinstance(choice, Mapping):
        raise SemanticProviderFailure(
            SemanticProviderFailureCode.INVALID_RESPONSE
        )
    message = choice.get("message")
    if not isinstance(message, Mapping):
        raise SemanticProviderFailure(
            SemanticProviderFailureCode.INVALID_RESPONSE
        )
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list) or len(tool_calls) != 1:
        raise SemanticProviderFailure(
            SemanticProviderFailureCode.INVALID_RESPONSE
        )
    tool_call = tool_calls[0]
    if not isinstance(tool_call, Mapping):
        raise SemanticProviderFailure(
            SemanticProviderFailureCode.INVALID_RESPONSE
        )
    function = tool_call.get("function")
    if (
        not isinstance(function, Mapping)
        or function.get("name") != expected_tool_name
    ):
        raise SemanticProviderFailure(
            SemanticProviderFailureCode.INVALID_RESPONSE
        )
    arguments = function.get("arguments")
    if not isinstance(arguments, str) or not arguments.strip():
        raise SemanticProviderFailure(
            SemanticProviderFailureCode.EMPTY_RESPONSE
        )
    return arguments


def extract_usage(
    envelope: object,
) -> tuple[dict[str, int | None], Decimal | None]:
    empty_usage: dict[str, int | None] = {
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "cached_tokens": None,
    }
    if not isinstance(envelope, Mapping):
        return empty_usage, None
    raw_usage = envelope.get("usage")
    if not isinstance(raw_usage, Mapping):
        return empty_usage, None
    usage = {
        name: non_negative_int(raw_usage.get(name))
        for name in empty_usage
    }
    return usage, non_negative_decimal(raw_usage.get("cost_cny"))


def validation_failure_code(
    error: ValidationError,
) -> SemanticProviderFailureCode:
    if any(item["type"] == "extra_forbidden" for item in error.errors()):
        return SemanticProviderFailureCode.FORBIDDEN_OUTPUT
    return SemanticProviderFailureCode.INVALID_OUTPUT


def sum_usage(usages: list[SemanticTokenUsage]) -> SemanticTokenUsage:
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


def safe_trace_id(value: str | None) -> str:
    if value is not None and _TRACE_ID_PATTERN.fullmatch(value):
        digest = hashlib.sha256(value.encode("ascii")).hexdigest()
        return f"sha256:{digest[:16]}"
    return "unavailable"


def non_negative_int(value: object) -> int | None:
    if (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value >= 0
    ):
        return value
    return None


def non_negative_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite() or parsed < 0:
        return None
    return parsed


def contains_control(value: str) -> bool:
    return any(
        ord(character) < 32 or ord(character) == 127
        for character in value
    )


__all__ = [
    "DailyUsageLimiter",
    "extract_tool_arguments",
    "JsonCompletion",
    "MAX_PROVIDER_RESPONSE_BYTES",
    "OpenAIJsonClient",
    "SqliteDailyUsageLimiter",
    "UsageLimiter",
    "UsageReservation",
    "sum_usage",
    "validate_adapter_settings",
    "validation_failure_code",
]
