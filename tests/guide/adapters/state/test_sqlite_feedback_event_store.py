from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import os
from pathlib import Path
import sqlite3
from threading import Barrier

import pytest

from app.guide.adapters.state.sqlite_feedback_event_store import (
    SqliteFeedbackEventStore,
)
from app.guide.feedback.contracts import ConversationVersionRef
from app.guide.feedback.event_contracts import (
    ClickFeedbackPayload,
    FeedbackEventRequest,
    RecordedFeedbackEvent,
)
from app.guide.feedback.event_ports import (
    FeedbackEventStoreCorrupt,
    FeedbackIdempotencyConflict,
)
from app.guide.feedback.profile_contracts import ProfileOwnerRef


def _owner(subject_id: str = "profile_0123456789abcdef") -> ProfileOwnerRef:
    return ProfileOwnerRef(
        scope="local_demo",
        subject_id=subject_id,
    )


def _event(
    *,
    event_id: str = "feedback_event_0123456789abcdef",
    product_id: int = 11,
    owner: ProfileOwnerRef | None = None,
    idempotency_key: str = "feedback-idempotency-key-0001",
) -> RecordedFeedbackEvent:
    event_owner = owner or _owner()
    request = FeedbackEventRequest(
        conversation=ConversationVersionRef(
            session_id="session-feedback-owner",
            conversation_version=7,
        ),
        profile=None,
        idempotency_key=idempotency_key,
        payload=ClickFeedbackPayload(product_id=product_id),
    )
    return RecordedFeedbackEvent(
        **request.model_dump(),
        owner=event_owner,
        event_id=event_id,
        occurred_at=datetime(2026, 8, 9, 4, 30, tzinfo=UTC),
    )


def _store(tmp_path: Path) -> SqliteFeedbackEventStore:
    return SqliteFeedbackEventStore(
        tmp_path / "state" / "feedback_events.sqlite3"
    )


def _row_count(store: SqliteFeedbackEventStore) -> int:
    with sqlite3.connect(store.database_path) as connection:
        return connection.execute(
            "SELECT COUNT(*) FROM feedback_events"
        ).fetchone()[0]


def test_sqlite_store_persists_and_replays_original_across_instances(
    tmp_path: Path,
) -> None:
    first = _store(tmp_path)
    event = _event()

    recorded = first.record_once(event)
    event.payload.product_id = 22
    recorded.payload.product_id = 33

    reopened = _store(tmp_path)
    loaded = reopened.load(
        owner=_owner(),
        idempotency_key="feedback-idempotency-key-0001",
    )

    assert loaded == _event()
    assert reopened.record_once(_event()) == loaded
    assert _row_count(reopened) == 1


def test_sqlite_store_rejects_idempotency_payload_conflicts(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    original = _event()
    store.record_once(original)

    with pytest.raises(FeedbackIdempotencyConflict):
        store.record_once(
            _event(
                event_id="feedback_event_fedcba9876543210",
                product_id=22,
            )
        )

    assert store.load(
        owner=_owner(),
        idempotency_key=original.idempotency_key,
    ) == original
    assert _row_count(store) == 1


def test_sqlite_store_scopes_idempotency_keys_to_stable_owner(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    first = _event()
    second = _event(
        event_id="feedback_event_fedcba9876543210",
        owner=_owner("profile_second_0123456789abcdef"),
    )

    store.record_once(first)
    store.record_once(second)

    assert _row_count(store) == 2
    assert store.load(
        owner=first.owner,
        idempotency_key=first.idempotency_key,
    ) == first
    assert store.load(
        owner=second.owner,
        idempotency_key=second.idempotency_key,
    ) == second


def test_concurrent_same_request_records_exactly_once_and_returns_one_event(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    first = _event()
    second = _event(event_id="feedback_event_fedcba9876543210")

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(store.record_once, (first, second)))

    assert len({result.event_id for result in results}) == 1
    assert results[0] == results[1]
    assert _row_count(store) == 1


def test_store_never_chmods_transient_sqlite_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    store.record_once(_event())
    chmod_paths: list[str] = []
    real_chmod = os.chmod

    with sqlite3.connect(store.database_path) as keeper:
        keeper.execute("PRAGMA journal_mode = WAL")
        keeper.execute(
            "CREATE TABLE IF NOT EXISTS keep_wal_open (value INTEGER)"
        )
        keeper.commit()
        assert Path(f"{store.database_path}-wal").exists()
        assert Path(f"{store.database_path}-shm").exists()

        def track_chmod(path: os.PathLike[str] | str, mode: int) -> None:
            chmod_paths.append(os.fspath(path))
            real_chmod(path, mode)

        monkeypatch.setattr(os, "chmod", track_chmod)
        store.load(
            owner=_owner(),
            idempotency_key="feedback-idempotency-key-0001",
        )

    assert not any(
        path.endswith(("-wal", "-shm")) for path in chmod_paths
    )


def test_concurrent_cold_start_is_private_and_exactly_once(
    tmp_path: Path,
) -> None:
    database_path = (
        tmp_path / "cold-state" / "feedback_events.sqlite3"
    )
    worker_count = 8
    barrier = Barrier(worker_count)

    def start_and_record(index: int) -> RecordedFeedbackEvent:
        barrier.wait()
        store = SqliteFeedbackEventStore(database_path)
        return store.record_once(
            _event(
                event_id=f"feedback_event_{index:024d}",
            )
        )

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        events = list(executor.map(start_and_record, range(worker_count)))

    assert len({event.event_id for event in events}) == 1
    assert database_path.parent.stat().st_mode & 0o777 == 0o700
    assert database_path.stat().st_mode & 0o777 == 0o600
    assert _row_count(SqliteFeedbackEventStore(database_path)) == 1


def test_malformed_stored_event_fails_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    event = _event()
    store.record_once(event)
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            """
            UPDATE feedback_events
            SET event_json = ?
            WHERE owner_subject_id = ? AND idempotency_key = ?
            """,
            (
                "{malformed-json",
                event.owner.subject_id,
                event.idempotency_key,
            ),
        )
        connection.commit()

    with pytest.raises(FeedbackEventStoreCorrupt):
        store.load(
            owner=event.owner,
            idempotency_key=event.idempotency_key,
        )


def test_invalid_sqlite_database_is_mapped_to_store_corruption(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "invalid-state" / "feedback_events.sqlite3"
    database_path.parent.mkdir()
    database_path.write_bytes(b"not-a-sqlite-database")

    with pytest.raises(FeedbackEventStoreCorrupt):
        SqliteFeedbackEventStore(database_path)


def test_incompatible_existing_schema_is_rejected_as_corrupt(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "wrong-schema" / "feedback_events.sqlite3"
    database_path.parent.mkdir()
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE feedback_events (unexpected_column TEXT)"
        )

    with pytest.raises(FeedbackEventStoreCorrupt):
        SqliteFeedbackEventStore(database_path)


@pytest.mark.parametrize("operation", ["load", "record"])
def test_runtime_schema_errors_are_mapped_to_store_corruption(
    tmp_path: Path,
    operation: str,
) -> None:
    store = _store(tmp_path)
    with sqlite3.connect(store.database_path) as connection:
        connection.execute("DROP TABLE feedback_events")

    with pytest.raises(FeedbackEventStoreCorrupt):
        if operation == "load":
            store.load(
                owner=_owner(),
                idempotency_key="feedback-idempotency-key-0001",
            )
        else:
            store.record_once(_event())


def test_store_uses_private_files_and_rejects_symlinks(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.record_once(_event())

    assert store.database_path.parent.stat().st_mode & 0o777 == 0o700
    assert store.database_path.stat().st_mode & 0o777 == 0o600

    target = tmp_path / "target.sqlite3"
    target.touch()
    linked_directory = tmp_path / "linked-state"
    linked_directory.mkdir()
    linked_database = linked_directory / "feedback_events.sqlite3"
    linked_database.symlink_to(target)
    with pytest.raises(ValueError, match="database.*symlink"):
        SqliteFeedbackEventStore(linked_database)


def test_from_environment_stays_under_guide_state_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_directory = tmp_path / "guide-state"
    monkeypatch.setenv(
        "XIAORO_GUIDE_STATE_DIR",
        os.fspath(state_directory),
    )

    store = SqliteFeedbackEventStore.from_environment()

    assert store.database_path == (
        state_directory / "feedback_events.sqlite3"
    ).absolute()


def test_from_environment_rejects_missing_or_relative_state_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("XIAORO_GUIDE_STATE_DIR", raising=False)
    with pytest.raises(ValueError, match="XIAORO_GUIDE_STATE_DIR"):
        SqliteFeedbackEventStore.from_environment()

    monkeypatch.setenv("XIAORO_GUIDE_STATE_DIR", "relative-state")
    with pytest.raises(ValueError, match="absolute"):
        SqliteFeedbackEventStore.from_environment()
