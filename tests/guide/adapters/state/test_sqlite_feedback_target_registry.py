from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import multiprocessing
import os
from pathlib import Path
import sqlite3
from threading import Barrier

import pytest
from pydantic import ValidationError

import app.guide.adapters.state.sqlite_feedback_target_registry as registry_module
from app.guide.adapters.state.sqlite_feedback_target_registry import (
    SqliteFeedbackTargetRegistry,
)
from app.guide.feedback.contracts import ConversationVersionRef
from app.guide.feedback.event_contracts import (
    FeedbackProfileVersionRef,
)
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.feedback.target_contracts import (
    TrustedFeedbackTarget,
    feedback_target_from_completed_response,
)
from app.guide.feedback.target_ports import (
    FeedbackTargetConflict,
    FeedbackTargetStoreCorrupt,
)
from app.guide.presentation.contracts import CardDisplayContract


def _owner(
    subject_id: str = "authenticated-user-0123456789",
) -> ProfileOwnerRef:
    return ProfileOwnerRef(
        scope="authenticated_user",
        subject_id=subject_id,
    )


def _reference(
    *,
    session_id: str = "session-feedback-target",
    version: int = 9,
) -> ConversationVersionRef:
    return ConversationVersionRef(
        session_id=session_id,
        conversation_version=version,
    )


def _target(
    *,
    owner: ProfileOwnerRef | None = None,
    product_ids: tuple[int, ...] = (11, 22, 33, 44),
    reference: ConversationVersionRef | None = None,
    profile_version: int | None = 3,
) -> TrustedFeedbackTarget:
    return TrustedFeedbackTarget(
        owner=owner or _owner(),
        conversation=reference or _reference(),
        displayed_product_ids=product_ids,
        profile=(
            FeedbackProfileVersionRef(
                profile_version=profile_version
            )
            if profile_version is not None
            else None
        ),
    )


def _store(tmp_path: Path) -> SqliteFeedbackTargetRegistry:
    state_root = tmp_path / "state"
    return SqliteFeedbackTargetRegistry(
        state_root / "feedback_targets.sqlite3",
        trusted_state_root=state_root,
    )


def _row_count(store: SqliteFeedbackTargetRegistry) -> int:
    with sqlite3.connect(store.database_path) as connection:
        return connection.execute(
            "SELECT COUNT(*) FROM feedback_targets"
        ).fetchone()[0]


def _process_record(
    database_path: str,
    state_root: str,
    start_event: object,
    result_queue: object,
) -> None:
    try:
        start_event.wait()
        stored = SqliteFeedbackTargetRegistry(
            database_path,
            trusted_state_root=state_root,
        ).record_once(_target())
        result_queue.put(("ok", stored.model_dump_json()))
    except BaseException as error:
        result_queue.put(
            ("error", type(error).__name__, str(error))
        )


def test_registry_persists_exact_target_and_replays_across_restart(
    tmp_path: Path,
) -> None:
    first = _store(tmp_path)
    candidate = _target()

    stored = first.record_once(candidate)
    with pytest.raises(ValidationError, match="frozen"):
        candidate.conversation.conversation_version = 10
    with pytest.raises(ValidationError, match="frozen"):
        stored.conversation.session_id = "session-feedback-mutated"
    assert candidate == _target()
    assert stored == _target()

    restarted = _store(tmp_path)
    loaded = restarted.load(
        owner=_owner(),
        reference=_reference(),
    )

    assert loaded == _target()
    assert loaded.profile is not None
    with pytest.raises(ValidationError, match="frozen"):
        loaded.profile.profile_version = 4
    with pytest.raises(ValidationError, match="frozen"):
        loaded.owner.subject_id = (
            "authenticated-user-fedcba9876543210"
        )
    assert loaded == _target()
    assert restarted.load(
        owner=_owner(),
        reference=_reference(),
    ) == _target()
    assert restarted.record_once(_target()) == loaded
    assert _row_count(restarted) == 1


def test_display_mutation_cannot_persist_unauthorized_product(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    display = CardDisplayContract(
        mode="single",
        visible_product_ids=[11],
        max_cards=1,
        reason="product",
    )

    with pytest.raises(AttributeError):
        display.visible_product_ids.insert(0, 99)

    target = feedback_target_from_completed_response(
        owner=_owner(),
        conversation=_reference(),
        card_display=display,
        profile=FeedbackProfileVersionRef(
            profile_version=3
        ),
    )
    assert target is not None
    assert target.displayed_product_ids == (11,)
    assert 99 not in target.displayed_product_ids

    store.record_once(target)
    loaded = store.load(owner=_owner(), reference=_reference())

    assert loaded is not None
    assert loaded.displayed_product_ids == (11,)
    assert 99 not in loaded.displayed_product_ids
    assert _row_count(store) == 1


@pytest.mark.parametrize(
    "conflicting",
    [
        _target(product_ids=(44, 33, 22, 11)),
        _target(profile_version=4),
        _target(profile_version=None),
    ],
)
def test_registry_rejects_non_exact_replay(
    tmp_path: Path,
    conflicting: TrustedFeedbackTarget,
) -> None:
    store = _store(tmp_path)
    original = _target()
    store.record_once(original)

    with pytest.raises(FeedbackTargetConflict):
        store.record_once(conflicting)

    assert store.load(
        owner=original.owner,
        reference=original.conversation,
    ) == original
    assert _row_count(store) == 1


def test_registry_scopes_same_session_version_to_server_owner(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    first = _target()
    second_owner = _owner(
        "authenticated-user-fedcba9876543210"
    )
    second = _target(owner=second_owner, product_ids=(55,))

    store.record_once(first)
    store.record_once(second)

    assert _row_count(store) == 2
    assert store.load(
        owner=first.owner,
        reference=first.conversation,
    ) == first
    assert store.load(
        owner=second.owner,
        reference=second.conversation,
    ) == second
    assert store.load(
        owner=_owner("authenticated-user-missing-012345"),
        reference=first.conversation,
    ) is None


def test_concurrent_thread_cold_start_records_exactly_once(
    tmp_path: Path,
) -> None:
    database_path = (
        tmp_path / "thread-state" / "feedback_targets.sqlite3"
    )
    state_root = database_path.parent
    worker_count = 8
    barrier = Barrier(worker_count)

    def start_and_record(_: int) -> TrustedFeedbackTarget:
        barrier.wait()
        return SqliteFeedbackTargetRegistry(
            database_path,
            trusted_state_root=state_root,
        ).record_once(_target())

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        results = list(
            executor.map(start_and_record, range(worker_count))
        )

    assert results == [_target()] * worker_count
    assert _row_count(
        SqliteFeedbackTargetRegistry(
            database_path,
            trusted_state_root=state_root,
        )
    ) == 1


def test_concurrent_process_cold_start_records_exactly_once(
    tmp_path: Path,
) -> None:
    context = multiprocessing.get_context("spawn")
    database_path = (
        tmp_path / "process-state" / "feedback_targets.sqlite3"
    )
    state_root = database_path.parent
    start_event = context.Event()
    result_queue = context.Queue()
    processes = [
        context.Process(
            target=_process_record,
            args=(
                os.fspath(database_path),
                os.fspath(state_root),
                start_event,
                result_queue,
            ),
        )
        for _ in range(4)
    ]
    for process in processes:
        process.start()
    start_event.set()
    results = [
        result_queue.get(timeout=20)
        for _ in processes
    ]
    for process in processes:
        process.join(timeout=20)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)

    assert results == [
        ("ok", _target().model_dump_json())
    ] * len(processes)
    assert all(process.exitcode == 0 for process in processes)
    assert _row_count(
        SqliteFeedbackTargetRegistry(
            database_path,
            trusted_state_root=state_root,
        )
    ) == 1


def test_concurrent_conflicting_writes_have_one_winner(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    barrier = Barrier(2)

    def record(target: TrustedFeedbackTarget) -> str:
        barrier.wait()
        try:
            store.record_once(target)
        except FeedbackTargetConflict:
            return "conflict"
        return "stored"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(
                record,
                (
                    _target(product_ids=(11,)),
                    _target(product_ids=(22,)),
                ),
            )
        )

    assert sorted(outcomes) == ["conflict", "stored"]
    assert _row_count(store) == 1


def test_invalid_database_and_schema_fail_closed(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "invalid-state"
    state_root.mkdir()
    database_path = state_root / "feedback_targets.sqlite3"
    database_path.write_bytes(b"not-a-sqlite-database")

    with pytest.raises(FeedbackTargetStoreCorrupt):
        SqliteFeedbackTargetRegistry(
            database_path,
            trusted_state_root=state_root,
        )

    wrong_state_root = tmp_path / "wrong-schema"
    wrong_state_root.mkdir()
    database_path = (
        wrong_state_root / "feedback_targets.sqlite3"
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE feedback_targets (unexpected TEXT)"
        )
        connection.execute("PRAGMA application_id = 123")
        connection.execute("PRAGMA user_version = 99")

    with pytest.raises(FeedbackTargetStoreCorrupt):
        SqliteFeedbackTargetRegistry(
            database_path,
            trusted_state_root=wrong_state_root,
        )


def test_malformed_row_and_runtime_schema_change_fail_closed(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.record_once(_target())
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(
            "UPDATE feedback_targets SET target_json = ?",
            ("{malformed-json",),
        )

    with pytest.raises(FeedbackTargetStoreCorrupt):
        store.load(owner=_owner(), reference=_reference())

    with sqlite3.connect(store.database_path) as connection:
        connection.execute("DROP TABLE feedback_targets")

    with pytest.raises(FeedbackTargetStoreCorrupt):
        store.record_once(_target())


def test_unexpected_schema_objects_fail_closed(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    with store._connect() as connection:
        connection.execute(
            """
            CREATE VIEW leaked_feedback_targets
            AS SELECT * FROM feedback_targets
            """
        )

    with pytest.raises(FeedbackTargetStoreCorrupt):
        SqliteFeedbackTargetRegistry(
            store.database_path,
            trusted_state_root=store.database_path.parent,
        )


def test_registry_uses_private_trusted_storage_without_cleanup(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "private-state"
    state_root.mkdir(mode=0o755)
    store = SqliteFeedbackTargetRegistry(
        state_root / "feedback_targets.sqlite3",
        trusted_state_root=state_root,
    )
    store.record_once(_target())

    assert state_root.stat().st_mode & 0o777 == 0o700
    assert store.database_path.stat().st_mode & 0o777 == 0o600
    assert not hasattr(store, "purge")
    assert not hasattr(store, "delete")
    assert not hasattr(store, "cleanup")


def test_registry_rejects_outside_and_symlinked_paths(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "trusted"
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(ValueError, match="outside trusted state root"):
        SqliteFeedbackTargetRegistry(
            outside / "feedback_targets.sqlite3",
            trusted_state_root=state_root,
        )

    state_root.mkdir(exist_ok=True)
    linked_directory = state_root / "linked"
    linked_directory.symlink_to(
        outside,
        target_is_directory=True,
    )
    with pytest.raises(ValueError, match="symlink"):
        SqliteFeedbackTargetRegistry(
            linked_directory / "feedback_targets.sqlite3",
            trusted_state_root=state_root,
        )

    target = outside / "target.sqlite3"
    target.write_bytes(b"unchanged")
    linked_database = state_root / "feedback_targets.sqlite3"
    linked_database.symlink_to(target)
    with pytest.raises(ValueError, match="database.*symlink"):
        SqliteFeedbackTargetRegistry(
            linked_database,
            trusted_state_root=state_root,
        )
    assert target.read_bytes() == b"unchanged"


def test_database_replaced_by_symlink_is_rejected_without_target_write(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.record_once(_target())
    outside = tmp_path / "replacement-target"
    outside.write_bytes(b"do-not-touch")
    store.database_path.unlink()
    store.database_path.symlink_to(outside)

    with pytest.raises(ValueError, match="database.*symlink"):
        store.load(owner=_owner(), reference=_reference())

    assert outside.read_bytes() == b"do-not-touch"


def test_sqlite_sidecar_symlink_is_rejected_without_following(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    victim = tmp_path / "sidecar-victim"
    victim.write_bytes(b"do-not-touch")
    victim.chmod(0o640)
    anchor = (
        store.database_path.parent
        / f".{store.database_path.name}.inode"
    )
    sidecar = Path(f"{anchor}-wal")
    sidecar.unlink(missing_ok=True)
    sidecar.symlink_to(victim)

    with pytest.raises(ValueError, match="database files.*symlinks"):
        store.load(owner=_owner(), reference=_reference())

    assert victim.read_bytes() == b"do-not-touch"
    assert victim.stat().st_mode & 0o777 == 0o640


def test_equivalent_root_alias_keeps_database_under_canonical_root(
    tmp_path: Path,
) -> None:
    real_root = tmp_path / "real-state"
    real_root.mkdir()
    root_alias = tmp_path / "state-alias"
    root_alias.symlink_to(real_root, target_is_directory=True)

    store = SqliteFeedbackTargetRegistry(
        root_alias / "nested" / "feedback_targets.sqlite3",
        trusted_state_root=root_alias,
    )

    assert store.database_path == (
        real_root / "nested" / "feedback_targets.sqlite3"
    )
    assert store.database_path.is_relative_to(real_root)


def test_quick_check_runs_at_initialization_not_online_read_write(
    tmp_path: Path,
    monkeypatch,
) -> None:
    statements: list[str] = []
    original_connect = registry_module.sqlite3.connect

    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(
        registry_module.sqlite3,
        "connect",
        traced_connect,
    )
    store = _store(tmp_path)

    assert any(
        statement.casefold().startswith("pragma quick_check")
        for statement in statements
    )
    statements.clear()

    store.record_once(_target())
    assert store.load(
        owner=_owner(),
        reference=_reference(),
    ) == _target()

    assert not any(
        statement.casefold().startswith("pragma quick_check")
        for statement in statements
    )
    assert any(
        statement.casefold().startswith("pragma application_id")
        for statement in statements
    )
    assert any(
        statement.casefold().startswith("pragma user_version")
        for statement in statements
    )
    assert any(
        "from sqlite_schema" in statement.casefold()
        for statement in statements
    )


@pytest.mark.parametrize(
    "pragma",
    (
        "PRAGMA application_id = 0",
        "PRAGMA user_version = 0",
    ),
)
def test_runtime_metadata_change_still_fails_closed(
    tmp_path: Path,
    pragma: str,
) -> None:
    store = _store(tmp_path)
    store.record_once(_target())
    with sqlite3.connect(store.database_path) as connection:
        connection.execute(pragma)

    with pytest.raises(FeedbackTargetStoreCorrupt):
        store.load(owner=_owner(), reference=_reference())
