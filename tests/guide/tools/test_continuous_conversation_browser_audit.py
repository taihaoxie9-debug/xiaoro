from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from tools.guide_gates.continuous_conversation_browser_audit import (
    BrowserHealthError,
    BrowserTurnTimeout,
    MAX_BROWSER_POLL_SECONDS,
    MAX_HEALTH_INTERVAL_SECONDS,
    MAX_PROVIDER_TIMEOUT_SECONDS,
    MAX_TURN_TIMEOUT_SECONDS,
    wait_for_browser_turn,
    write_partial_browser_artifact,
)


def test_browser_audit_module_exists() -> None:
    assert importlib.util.find_spec(
        "tools.guide_gates.continuous_conversation_browser_audit"
    ) is not None


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_browser_turn_waits_for_terminal_and_zero_active_requests() -> None:
    clock = FakeClock()
    health_calls: list[float] = []

    result = wait_for_browser_turn(
        terminal_probe=lambda: clock.now >= 4,
        active_request_count=lambda: 0 if clock.now >= 6 else 1,
        health_probe=lambda: health_calls.append(clock.now) is None,
        timeout_seconds=10,
        health_interval_seconds=2,
        browser_poll_seconds=1,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert result.elapsed_seconds == 6
    assert result.health_probe_count == 4
    assert health_calls == [0, 2, 4, 6]


def test_browser_turn_timeout_captures_evidence_before_failure() -> None:
    clock = FakeClock()
    captured: list[float] = []

    with pytest.raises(BrowserTurnTimeout):
        wait_for_browser_turn(
            terminal_probe=lambda: False,
            active_request_count=lambda: 1,
            health_probe=lambda: None,
            timeout_seconds=5,
            health_interval_seconds=2,
            browser_poll_seconds=1,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
            capture_timeout_evidence=lambda: captured.append(clock.now),
        )

    assert captured == [5]


def test_browser_turn_fails_when_independent_health_probe_blocks() -> None:
    clock = FakeClock()

    with pytest.raises(BrowserHealthError):
        wait_for_browser_turn(
            terminal_probe=lambda: False,
            active_request_count=lambda: 1,
            health_probe=lambda: False,
            timeout_seconds=5,
            health_interval_seconds=2,
            browser_poll_seconds=1,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )

    assert clock.now == 0


def test_browser_partial_artifact_is_atomic_json(tmp_path: Path) -> None:
    destination = tmp_path / "partial.json"

    write_partial_browser_artifact(
        destination,
        {
            "completed_turn_count": 1,
            "last_turn_id": "browser-t1",
        },
    )

    assert json.loads(destination.read_text(encoding="utf-8")) == {
        "completed_turn_count": 1,
        "last_turn_id": "browser-t1",
    }
    assert not (tmp_path / ".partial.json.tmp").exists()


def test_browser_watchdog_limits_match_acceptance_contract() -> None:
    assert MAX_PROVIDER_TIMEOUT_SECONDS == 30
    assert MAX_TURN_TIMEOUT_SECONDS == 90
    assert MAX_HEALTH_INTERVAL_SECONDS == 10
    assert MAX_BROWSER_POLL_SECONDS == 2
