"""Bounded browser-turn health and progress helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
import time
from typing import Any


MAX_PROVIDER_TIMEOUT_SECONDS = 30
MAX_TURN_TIMEOUT_SECONDS = 90
MAX_HEALTH_INTERVAL_SECONDS = 10
MAX_BROWSER_POLL_SECONDS = 2


class BrowserTurnTimeout(TimeoutError):
    pass


class BrowserHealthError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BrowserTurnWaitResult:
    elapsed_seconds: float
    health_probe_count: int
    browser_poll_count: int


def wait_for_browser_turn(
    *,
    terminal_probe: Callable[[], bool],
    active_request_count: Callable[[], int],
    health_probe: Callable[[], bool | None],
    timeout_seconds: float = MAX_TURN_TIMEOUT_SECONDS,
    health_interval_seconds: float = MAX_HEALTH_INTERVAL_SECONDS,
    browser_poll_seconds: float = MAX_BROWSER_POLL_SECONDS,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    capture_timeout_evidence: Callable[[], None] | None = None,
) -> BrowserTurnWaitResult:
    _bounded_interval(
        "timeout_seconds",
        timeout_seconds,
        maximum=MAX_TURN_TIMEOUT_SECONDS,
    )
    _bounded_interval(
        "health_interval_seconds",
        health_interval_seconds,
        maximum=MAX_HEALTH_INTERVAL_SECONDS,
    )
    _bounded_interval(
        "browser_poll_seconds",
        browser_poll_seconds,
        maximum=MAX_BROWSER_POLL_SECONDS,
    )
    started = monotonic()
    deadline = started + timeout_seconds
    next_health = started
    health_probe_count = 0
    browser_poll_count = 0

    while True:
        now = monotonic()
        if now >= deadline:
            try:
                if capture_timeout_evidence is not None:
                    capture_timeout_evidence()
            finally:
                raise BrowserTurnTimeout(
                    f"browser turn exceeded {timeout_seconds:g} seconds"
                )

        if now >= next_health:
            health_probe_count += 1
            try:
                healthy = health_probe()
            except Exception as exc:
                raise BrowserHealthError(
                    "independent health probe failed"
                ) from exc
            if healthy is False:
                raise BrowserHealthError(
                    "independent health probe reported unhealthy"
                )
            next_health = now + health_interval_seconds

        browser_poll_count += 1
        terminal = terminal_probe()
        requests = active_request_count()
        if (
            not isinstance(terminal, bool)
            or not isinstance(requests, int)
            or isinstance(requests, bool)
            or requests < 0
        ):
            raise TypeError(
                "browser probes must return bool and non-negative int"
            )
        if terminal and requests == 0:
            return BrowserTurnWaitResult(
                elapsed_seconds=monotonic() - started,
                health_probe_count=health_probe_count,
                browser_poll_count=browser_poll_count,
            )

        sleep_for = min(
            browser_poll_seconds,
            deadline - now,
            max(0.0, next_health - now),
        )
        sleep(max(0.001, sleep_for))


def write_partial_browser_artifact(
    destination: str | Path,
    payload: object,
) -> None:
    if _contains_sensitive_key(payload):
        raise ValueError(
            "browser partial artifact contains a sensitive key"
        )
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    temporary.replace(path)


def _bounded_interval(
    name: str,
    value: float,
    *,
    maximum: float,
) -> None:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or value <= 0
        or value > maximum
    ):
        raise ValueError(
            f"{name} must be positive and at most {maximum:g}"
        )


def _contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str) and (
                "authorization" in key.casefold()
                or "api_key" in key.casefold()
            ):
                return True
            if _contains_sensitive_key(item):
                return True
        return False
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return any(_contains_sensitive_key(item) for item in value)
    return False


__all__ = [
    "BrowserHealthError",
    "BrowserTurnTimeout",
    "BrowserTurnWaitResult",
    "MAX_BROWSER_POLL_SECONDS",
    "MAX_HEALTH_INTERVAL_SECONDS",
    "MAX_PROVIDER_TIMEOUT_SECONDS",
    "MAX_TURN_TIMEOUT_SECONDS",
    "wait_for_browser_turn",
    "write_partial_browser_artifact",
]
