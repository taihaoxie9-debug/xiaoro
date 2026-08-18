from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import sqlite3
import stat
from threading import Barrier

from app.guide_runtime import request_limits


class Clock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _limiter(
    tmp_path: Path,
    *,
    clock: Clock | None = None,
    limit: int = 12,
    window_seconds: float = 60.0,
    entry_ttl_seconds: float = 120.0,
    max_entries: int = 32,
):
    return request_limits.SqliteImageUploadRateLimiter(
        tmp_path / "rate-state" / "image_upload_rate.sqlite3",
        limit=limit,
        window_seconds=window_seconds,
        entry_ttl_seconds=entry_ttl_seconds,
        max_entries=max_entries,
        clock=clock or Clock(),
    )


def _stored_rows(database_path: Path) -> list[tuple[str, int, float]]:
    with sqlite3.connect(database_path) as connection:
        return connection.execute(
            """
            SELECT client_key_sha256, request_count, last_seen_at
            FROM image_upload_rate_windows
            ORDER BY client_key_sha256
            """
        ).fetchall()


def test_fixed_window_flips_at_exact_boundary_and_survives_reopen(
    tmp_path: Path,
) -> None:
    clock = Clock(1_020.0)
    limiter = _limiter(tmp_path, clock=clock, limit=2)

    assert limiter.consume("client-a") is True
    assert limiter.consume("client-a") is True
    assert limiter.consume("client-a") is False

    reopened = _limiter(tmp_path, clock=clock, limit=2)
    assert reopened.consume("client-a") is False

    clock.advance(60.0)
    assert reopened.consume("client-a") is True


def test_begin_immediate_serializes_concurrent_consumers(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "rate-state" / "concurrent.sqlite3"
    limiters = [
        request_limits.SqliteImageUploadRateLimiter(
            database_path,
            limit=12,
            window_seconds=60.0,
            entry_ttl_seconds=120.0,
            max_entries=32,
            clock=Clock(),
        )
        for _ in range(24)
    ]
    barrier = Barrier(len(limiters))

    def consume(limiter) -> bool:
        barrier.wait(timeout=5)
        return limiter.consume("same-client")

    with ThreadPoolExecutor(max_workers=len(limiters)) as pool:
        accepted = list(pool.map(consume, limiters))

    assert accepted.count(True) == 12
    assert accepted.count(False) == 12
    rows = _stored_rows(database_path)
    assert len(rows) == 1
    assert rows[0][1] == 12


def test_registry_cleans_old_windows_without_evicting_active_entries(
    tmp_path: Path,
) -> None:
    clock = Clock()
    limiter = _limiter(
        tmp_path,
        clock=clock,
        window_seconds=5.0,
        entry_ttl_seconds=10.0,
        max_entries=3,
    )
    for index in range(3):
        assert limiter.consume(f"client-{index}") is True
        clock.advance(1.0)

    assert limiter.consume("client-3") is False
    rows = _stored_rows(limiter.database_path)
    assert len(rows) == 3
    assert hashlib.sha256(b"client-0").hexdigest() in {
        row[0] for row in rows
    }

    clock.advance(3.0)
    assert limiter.consume("client-3") is True
    rows = _stored_rows(limiter.database_path)
    assert len(rows) == 1
    assert rows[0][0] == hashlib.sha256(b"client-3").hexdigest()

    clock.advance(11.0)
    assert limiter.consume("client-after-ttl") is True
    rows = _stored_rows(limiter.database_path)
    assert len(rows) == 1
    assert rows[0][0] == hashlib.sha256(
        b"client-after-ttl"
    ).hexdigest()


def test_limited_client_stays_limited_when_other_clients_fill_capacity(
    tmp_path: Path,
) -> None:
    limiter = _limiter(
        tmp_path,
        limit=2,
        max_entries=3,
    )

    assert limiter.consume("client-a") is True
    assert limiter.consume("client-a") is True
    assert limiter.consume("client-a") is False
    assert limiter.consume("client-b") is True
    assert limiter.consume("client-c") is True

    assert limiter.consume("client-d") is False
    assert limiter.consume("client-a") is False
    rows = _stored_rows(limiter.database_path)
    assert len(rows) == 3
    assert (
        hashlib.sha256(b"client-a").hexdigest(),
        2,
        1_000.0,
    ) in rows


def test_clock_rollback_preserves_future_window_and_fails_closed(
    tmp_path: Path,
) -> None:
    clock = Clock(1_120.0)
    limiter = _limiter(
        tmp_path,
        clock=clock,
        limit=2,
        max_entries=1,
    )

    assert limiter.consume("future-client") is True
    assert limiter.consume("future-client") is True
    assert limiter.consume("future-client") is False

    clock.now = 1_000.0
    assert limiter.consume("new-client") is False
    assert limiter.consume("future-client") is False
    assert _stored_rows(limiter.database_path) == [
        (
            hashlib.sha256(b"future-client").hexdigest(),
            2,
            1_120.0,
        )
    ]


def test_one_thousand_random_clients_never_exceed_hard_capacity(
    tmp_path: Path,
) -> None:
    capacity = request_limits.IMAGE_UPLOAD_RATE_MAX_CLIENTS
    limiter = _limiter(
        tmp_path,
        max_entries=capacity,
    )

    accepted = [
        limiter.consume(f"random-client-{index:04d}")
        for index in range(1_000)
    ]

    assert accepted == [True] * capacity + [False] * (1_000 - capacity)
    rows = _stored_rows(limiter.database_path)
    assert len(rows) == capacity
    assert {row[0] for row in rows} == {
        hashlib.sha256(
            f"random-client-{index:04d}".encode("utf-8")
        ).hexdigest()
        for index in range(capacity)
    }
    database_bytes = limiter.database_path.read_bytes()
    assert b"random-client-" not in database_bytes
    assert all(len(row[0]) == 64 for row in rows)
    assert stat.S_IMODE(
        limiter.database_path.parent.stat().st_mode
    ) == 0o700
    assert stat.S_IMODE(limiter.database_path.stat().st_mode) == 0o600
