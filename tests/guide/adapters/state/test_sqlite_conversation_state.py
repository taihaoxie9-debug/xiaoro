from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import stat

import pytest
from pydantic import ValidationError

from app.guide.feedback.consultation_state import ConsultationSubstate
from app.guide.feedback.contracts import (
    ClarificationProgress,
    ConversationSnapshot,
    DisplayedCandidateRef,
    RecommendationQueryContext,
)
from app.guide.feedback.focus_state import FocusState
from app.guide.feedback.ports import (
    ConversationStateConflict,
    ConversationStateCorrupt,
)
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.feedback.session_profile import (
    SessionProfile,
    StableTendencyUpdate,
    reduce_session_profile,
)
from app.guide.understanding.contracts import TopicCode
from app.guide.understanding.semantic_contracts import ClarificationCode


def _owner(
    *,
    scope: str = "anonymous_browser",
    subject_id: str = "browser_owner_0123456789",
) -> ProfileOwnerRef:
    return ProfileOwnerRef(scope=scope, subject_id=subject_id)


def _recommendation(
    *,
    session_id: str = "conversation-session",
    version: int = 1,
    owner: ProfileOwnerRef | None = None,
    product_id: int = 91,
    focused_candidate_ordinal: int | None = None,
    product_ids: tuple[int, ...] | None = None,
    category: str = "serum",
) -> ConversationSnapshot:
    visible_product_ids = (
        product_ids if product_ids is not None else (product_id,)
    )
    return ConversationSnapshot(
        session_id=session_id,
        version=version,
        profile_owner=owner,
        query_context=RecommendationQueryContext(
            category=category,
            budget_minimum=Decimal("100.50"),
            budget_maximum=Decimal("500"),
            skin="sensitive",
            efficacy="repair" if category == "serum" else None,
            exclusions=["酒精", "香精"],
        ),
        candidates=[
            DisplayedCandidateRef(
                product_id=visible_product_id,
                ordinal=ordinal,
                skin_match="matched",
                matched_efficacies=["修护", "保湿"],
            )
            for ordinal, visible_product_id in enumerate(
                visible_product_ids,
                start=1,
            )
        ],
        focused_candidate_ordinal=focused_candidate_ordinal,
    )


def _state(
    tmp_path: Path,
):
    from app.guide.adapters.state.sqlite_conversation_state import (
        SqliteConversationState,
    )

    state_root = tmp_path / "state"
    return SqliteConversationState(
        state_root / "conversations.sqlite3",
        trusted_state_root=state_root,
    )


def _multiprocess_create(
    database_path: str,
    state_root: str,
    ready,
    start,
    results,
) -> None:
    from app.guide.adapters.state.sqlite_conversation_state import (
        SqliteConversationState,
    )

    try:
        state = SqliteConversationState(
            database_path,
            trusted_state_root=state_root,
        )
        ready.put("ready")
        start.wait(timeout=10)
        state.save(
            _recommendation(
                session_id="multiprocess-session",
                owner=_owner(),
            ),
            expected_version=0,
        )
    except ConversationStateConflict:
        results.put("conflict")
    except BaseException as error:
        results.put(f"error:{type(error).__name__}:{error}")
    else:
        results.put("saved")


def test_delete_is_atomic_owner_scoped_and_idempotent(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    owner = _owner(subject_id="delete-owner-0001")
    foreign = _owner(subject_id="foreign-owner-001")
    stored = state.save(
        _recommendation(
            session_id="delete-session",
            owner=owner,
        ).model_copy(
            update={
                "session_profile": reduce_session_profile(
                    previous=SessionProfile(),
                    updates=(
                        StableTendencyUpdate(
                            value="sensitivity",
                            confirmation="confirmed",
                        ),
                    ),
                    subject_scope="self",
                    source_turn_id="turn_delete_profile_0002",
                    conversation_version=1,
                ).profile,
                "focus_state": FocusState(
                    active_processor="recommendation",
                    current_product_id=91,
                ),
            },
            deep=True,
        ),
        expected_version=0,
    )

    assert state.load(stored.session_id).session_profile is not None
    assert state.load(stored.session_id).focus_state is not None
    assert not state.delete(
        stored.session_id,
        expected_owner=foreign,
    )
    assert state.load(stored.session_id) == stored
    assert state.delete(
        stored.session_id,
        expected_owner=owner,
    )
    assert state.load(stored.session_id) is None
    assert not state.delete(
        stored.session_id,
        expected_owner=owner,
    )


def test_deep_json_round_trip_and_restart(tmp_path: Path) -> None:
    state = _state(tmp_path)
    owner = _owner()
    first = state.save(
        _recommendation(owner=owner),
        expected_version=0,
    )
    active = first.model_copy(
        update={
            "version": 2,
            "consultation": ConsultationSubstate(
                started_at_conversation_version=2,
                observations=[],
            ),
        },
        deep=True,
    )
    saved = state.save(active, expected_version=1)

    restarted = type(state)(
        state.database_path,
        trusted_state_root=state.database_path.parent,
    )
    loaded = restarted.load(saved.session_id)

    assert loaded == saved
    assert loaded is not saved
    assert loaded.query_context is not saved.query_context
    payload = loaded.model_dump(mode="json")
    assert payload["query_context"]["budget_minimum"] == "100.50"
    assert isinstance(payload["query_context"]["exclusions"], list)
    assert isinstance(payload["candidates"], list)
    assert isinstance(payload["consultation"]["observations"], list)


def test_restart_round_trips_focus_state(tmp_path: Path) -> None:
    state = _state(tmp_path)
    current = _recommendation(
        session_id="focus-restart",
        product_ids=(51, 55, 101),
        focused_candidate_ordinal=2,
    ).model_copy(
        update={
            "focus_state": FocusState(
                active_processor="product_knowledge",
                current_product_id=55,
                current_knowledge_topic="防晒补涂",
                last_question_meaning="询问第二款补涂方式",
            )
        },
        deep=True,
    )
    stored = state.save(current, expected_version=0)

    restarted = type(state)(
        state.database_path,
        trusted_state_root=state.database_path.parent,
    )
    loaded = restarted.load(stored.session_id)

    assert loaded == stored
    assert loaded.focus_state is not None
    assert loaded.focus_state.current_product_id == 55
    assert loaded.focus_state.current_knowledge_topic == "防晒补涂"


def test_restart_round_trips_clarification_only_state(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    stored = state.save(
        ConversationSnapshot(
            session_id="clarification-restart",
            version=1,
            clarification=ClarificationProgress(
                gap=ClarificationCode.REFERENCE,
                attempts=1,
            ),
        ),
        expected_version=0,
    )

    restarted = type(state)(
        state.database_path,
        trusted_state_root=state.database_path.parent,
    )

    loaded = restarted.load(stored.session_id)

    assert loaded == stored
    assert loaded.clarification.gap is ClarificationCode.REFERENCE


def test_restart_round_trips_general_knowledge_focus(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    stored = state.save(
        ConversationSnapshot(
            session_id="knowledge-restart",
            version=1,
            focused_general_knowledge_ids=(
                "a" * 64,
                "b" * 64,
            ),
            last_general_knowledge_question="SPF是什么意思",
        ),
        expected_version=0,
    )

    restarted = type(state)(
        state.database_path,
        trusted_state_root=state.database_path.parent,
    )
    loaded = restarted.load(stored.session_id)

    assert loaded == stored
    assert loaded.focused_general_knowledge_ids == (
        "a" * 64,
        "b" * 64,
    )
    assert loaded.last_general_knowledge_question == "SPF是什么意思"


def test_general_knowledge_focus_ids_must_be_sorted_unique() -> None:
    with pytest.raises(
        ValidationError,
        match="general knowledge IDs must be sorted and unique",
    ):
        ConversationSnapshot(
            session_id="invalid-knowledge-focus",
            version=1,
            focused_general_knowledge_ids=(
                "b" * 64,
                "a" * 64,
                "b" * 64,
            ),
            last_general_knowledge_question="继续问",
        )


def test_clarification_state_must_start_at_first_attempt(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)

    with pytest.raises(ValueError, match="attempt one"):
        state.save(
            ConversationSnapshot(
                session_id="invalid-clarification-start",
                version=1,
                clarification=ClarificationProgress(
                    gap=ClarificationCode.TOPIC,
                    attempts=2,
                ),
            ),
            expected_version=0,
        )


def test_four_candidate_round_trip_preserves_order_and_cas(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    current = state.save(
        _recommendation(
            product_ids=(91, 38, 55, 72),
            focused_candidate_ordinal=4,
        ),
        expected_version=0,
    )
    restarted = type(state)(
        state.database_path,
        trusted_state_root=state.database_path.parent,
    )

    loaded = restarted.load(current.session_id)

    assert loaded == current
    assert loaded is not current
    assert [item.ordinal for item in loaded.candidates] == [1, 2, 3, 4]
    assert [item.product_id for item in loaded.candidates] == [
        91,
        38,
        55,
        72,
    ]
    assert loaded.focused_candidate_ordinal == 4
    with pytest.raises(ConversationStateConflict):
        restarted.save(
            current.model_copy(update={"version": 2}, deep=True),
            expected_version=0,
        )
    assert restarted.load(current.session_id) == current


def test_restart_loads_legacy_row_without_candidate_focus(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    current = state.save(_recommendation(), expected_version=0)
    with state._storage.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        payload = json.loads(
            connection.execute(
                """
                SELECT snapshot_json
                FROM conversations
                WHERE session_id = ?
                """,
                (current.session_id,),
            ).fetchone()[0]
        )
        del payload["focused_candidate_ordinal"]
        connection.execute(
            """
            UPDATE conversations
            SET snapshot_json = ?
            WHERE session_id = ?
            """,
            (
                json.dumps(payload, ensure_ascii=False),
                current.session_id,
            ),
        )
        connection.commit()

    restarted = type(state)(
        state.database_path,
        trusted_state_root=state.database_path.parent,
    )
    loaded = restarted.load(current.session_id)

    assert loaded is not None
    assert loaded.focused_candidate_ordinal is None
    saved = restarted.save(
        loaded.model_copy(update={"version": 2}, deep=True),
        expected_version=1,
    )
    assert saved.focused_candidate_ordinal is None

    with restarted._storage.connect() as connection:
        stored_payload = json.loads(
            connection.execute(
                """
                SELECT snapshot_json
                FROM conversations
                WHERE session_id = ?
                """,
                (current.session_id,),
            ).fetchone()[0]
        )
    assert stored_payload["focused_candidate_ordinal"] is None


@pytest.mark.parametrize("topic", list(TopicCode))
def test_restart_round_trips_every_topic_code(
    tmp_path: Path,
    topic: TopicCode,
) -> None:
    state = _state(tmp_path)
    saved = state.save(
        _recommendation(
            session_id=f"topic-{topic.value}",
            category=topic.value,
        ),
        expected_version=0,
    )

    restarted = type(state)(
        state.database_path,
        trusted_state_root=state.database_path.parent,
    )
    loaded = restarted.load(saved.session_id)

    assert loaded is not None
    assert loaded.query_context is not None
    assert loaded.query_context.category == topic.value


def test_optimistic_cas_rejects_stale_writer_after_restart(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    current = state.save(_recommendation(), expected_version=0)
    restarted = type(state)(
        state.database_path,
        trusted_state_root=state.database_path.parent,
    )

    with pytest.raises(ConversationStateConflict):
        restarted.save(
            current.model_copy(update={"version": 2}, deep=True),
            expected_version=0,
        )

    assert restarted.load(current.session_id) == current


def test_threaded_same_version_race_has_one_winner(tmp_path: Path) -> None:
    state = _state(tmp_path)
    snapshots = (
        _recommendation(product_id=91),
        _recommendation(product_id=38),
    )

    def save(snapshot: ConversationSnapshot) -> str:
        try:
            state.save(snapshot, expected_version=0)
        except ConversationStateConflict:
            return "conflict"
        return "saved"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(save, snapshots))

    assert sorted(outcomes) == ["conflict", "saved"]
    assert state.load("conversation-session") in snapshots


def test_multiprocess_cold_start_and_cas_are_atomic(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    database_path = state_root / "conversations.sqlite3"
    context = multiprocessing.get_context("spawn")
    ready = context.Queue()
    results = context.Queue()
    start = context.Event()
    processes = [
        context.Process(
            target=_multiprocess_create,
            args=(
                str(database_path),
                str(state_root),
                ready,
                start,
                results,
            ),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    assert [ready.get(timeout=15) for _ in processes] == [
        "ready",
        "ready",
    ]
    start.set()
    observed = [results.get(timeout=15) for _ in processes]
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0

    assert sorted(observed) == ["conflict", "saved"]
    state = _state(tmp_path)
    assert state.load("multiprocess-session") is not None


@pytest.mark.parametrize("replacement", ["different", "ownerless"])
def test_bound_owner_cannot_change_or_be_removed(
    tmp_path: Path,
    replacement: str,
) -> None:
    state = _state(tmp_path)
    owner = _owner()
    current = state.save(
        _recommendation(owner=owner),
        expected_version=0,
    )
    next_owner = (
        _owner(
            scope="authenticated_user",
            subject_id="different_owner_0123456789",
        )
        if replacement == "different"
        else None
    )

    with pytest.raises(ConversationStateConflict):
        state.save(
            current.model_copy(
                update={
                    "version": 2,
                    "profile_owner": next_owner,
                },
                deep=True,
            ),
            expected_version=1,
        )

    assert state.load(current.session_id).profile_owner == owner


def test_ownerless_row_cannot_be_claimed(tmp_path: Path) -> None:
    state = _state(tmp_path)
    current = state.save(_recommendation(), expected_version=0)

    with pytest.raises(ConversationStateConflict):
        state.save(
            current.model_copy(
                update={
                    "version": 2,
                    "profile_owner": _owner(),
                },
                deep=True,
            ),
            expected_version=1,
        )

    assert state.load(current.session_id).profile_owner is None


def test_owner_columns_tampering_fails_closed(tmp_path: Path) -> None:
    state = _state(tmp_path)
    current = state.save(
        _recommendation(owner=_owner()),
        expected_version=0,
    )
    with sqlite3.connect(state.database_path) as connection:
        connection.execute(
            """
            UPDATE conversations
            SET owner_scope = 'authenticated_user'
            WHERE session_id = ?
            """,
            (current.session_id,),
        )

    with pytest.raises(ConversationStateCorrupt):
        state.load(current.session_id)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("snapshot_json", "{}"),
        ("snapshot_version", 99),
        ("owner_subject_id", "other_owner_0123456789"),
    ],
)
def test_malformed_or_mismatched_row_fails_closed(
    tmp_path: Path,
    column: str,
    value: object,
) -> None:
    state = _state(tmp_path)
    current = state.save(
        _recommendation(owner=_owner()),
        expected_version=0,
    )
    with sqlite3.connect(state.database_path) as connection:
        connection.execute(
            f"UPDATE conversations SET {column} = ? WHERE session_id = ?",
            (value, current.session_id),
        )

    with pytest.raises(ConversationStateCorrupt):
        state.load(current.session_id)


def test_schema_tampering_is_rejected_on_restart(tmp_path: Path) -> None:
    state = _state(tmp_path)
    state.save(_recommendation(), expected_version=0)
    with sqlite3.connect(state.database_path) as connection:
        connection.execute(
            "ALTER TABLE conversations ADD COLUMN injected TEXT"
        )

    with pytest.raises(ConversationStateCorrupt):
        type(state)(
            state.database_path,
            trusted_state_root=state.database_path.parent,
        )


def test_invalid_sqlite_file_is_not_rewritten(tmp_path: Path) -> None:
    from app.guide.adapters.state.sqlite_conversation_state import (
        SqliteConversationState,
    )

    state_root = tmp_path / "state"
    state_root.mkdir(mode=0o700)
    database_path = state_root / "conversations.sqlite3"
    payload = b"not a sqlite database"
    database_path.write_bytes(payload)
    database_path.chmod(0o600)

    with pytest.raises(ConversationStateCorrupt):
        SqliteConversationState(
            database_path,
            trusted_state_root=state_root,
        )

    assert database_path.read_bytes() == payload


def test_private_storage_and_sidecars(tmp_path: Path) -> None:
    state = _state(tmp_path)
    state.save(_recommendation(), expected_version=0)

    assert stat.S_IMODE(state.database_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(state.database_path.stat().st_mode) == 0o600
    anchor = (
        state.database_path.parent
        / f".{state.database_path.name}.inode"
    )
    assert stat.S_IMODE(anchor.stat().st_mode) == 0o600
    for suffix in ("-wal", "-shm"):
        sidecar = state.database_path.with_name(
            f"{state.database_path.name}{suffix}"
        )
        if sidecar.exists():
            assert stat.S_IMODE(sidecar.stat().st_mode) == 0o600


def test_symlink_database_and_parent_are_rejected(tmp_path: Path) -> None:
    from app.guide.adapters.state.sqlite_conversation_state import (
        SqliteConversationState,
    )

    real_root = tmp_path / "real"
    real_root.mkdir(mode=0o700)
    linked_root = tmp_path / "linked"
    linked_root.symlink_to(real_root, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        SqliteConversationState(
            linked_root / "conversations.sqlite3",
            trusted_state_root=linked_root,
        )

    target = tmp_path / "target.sqlite3"
    target.write_bytes(b"unchanged")
    linked_database = real_root / "conversations.sqlite3"
    linked_database.symlink_to(target)
    with pytest.raises(ValueError, match="database.*symlink"):
        SqliteConversationState(
            linked_database,
            trusted_state_root=real_root,
        )
    assert target.read_bytes() == b"unchanged"


def test_replaced_database_inode_is_rejected(tmp_path: Path) -> None:
    state = _state(tmp_path)
    state.save(_recommendation(), expected_version=0)
    replacement = tmp_path / "replacement.sqlite3"
    replacement.write_bytes(state.database_path.read_bytes())
    replacement.chmod(0o600)
    state.database_path.unlink()
    os.link(replacement, state.database_path)

    with pytest.raises(ValueError, match="inode anchor changed"):
        state.load("conversation-session")


def test_secure_files_rejects_sidecar_symlink_replacement_after_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.guide.adapters.state import trusted_sqlite_storage

    state = _state(tmp_path)
    sidecar = state.database_path.parent / (
        f".{state.database_path.name}.inode-wal"
    )
    sidecar.write_bytes(b"opened-sidecar")
    sidecar.chmod(0o600)
    protected = tmp_path / "protected"
    protected.write_bytes(b"must-not-change")
    protected.chmod(0o640)
    original_open = trusted_sqlite_storage.os.open
    replaced = False

    def replace_after_open(
        path,
        flags,
        mode=0o777,
        *,
        dir_fd=None,
    ):
        nonlocal replaced
        descriptor = original_open(
            path,
            flags,
            mode,
            dir_fd=dir_fd,
        )
        if path == sidecar.name and dir_fd is not None and not replaced:
            replaced = True
            sidecar.unlink()
            sidecar.symlink_to(protected)
        return descriptor

    monkeypatch.setattr(
        trusted_sqlite_storage.os,
        "open",
        replace_after_open,
    )

    with pytest.raises(ValueError, match="database file.*changed"):
        state._secure_database_files()

    assert replaced is True
    assert sidecar.is_symlink()
    assert protected.read_bytes() == b"must-not-change"
    assert stat.S_IMODE(protected.stat().st_mode) == 0o640


def test_secure_files_rejects_sidecar_inode_replacement_after_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.guide.adapters.state import trusted_sqlite_storage

    state = _state(tmp_path)
    sidecar = state.database_path.parent / (
        f".{state.database_path.name}.inode-shm"
    )
    sidecar.write_bytes(b"opened-sidecar")
    sidecar.chmod(0o600)
    replacement = tmp_path / "replacement-sidecar"
    replacement.write_bytes(b"replacement-must-not-change")
    replacement.chmod(0o640)
    original_open = trusted_sqlite_storage.os.open
    replaced = False

    def replace_after_open(
        path,
        flags,
        mode=0o777,
        *,
        dir_fd=None,
    ):
        nonlocal replaced
        descriptor = original_open(
            path,
            flags,
            mode,
            dir_fd=dir_fd,
        )
        if path == sidecar.name and dir_fd is not None and not replaced:
            replaced = True
            os.replace(replacement, sidecar)
        return descriptor

    monkeypatch.setattr(
        trusted_sqlite_storage.os,
        "open",
        replace_after_open,
    )

    with pytest.raises(ValueError, match="database file.*changed"):
        state._secure_database_files()

    assert replaced is True
    assert sidecar.read_bytes() == b"replacement-must-not-change"
    assert stat.S_IMODE(sidecar.stat().st_mode) == 0o640


def test_secure_files_rejects_parent_drift_after_sidecar_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.guide.adapters.state import trusted_sqlite_storage
    from app.guide.adapters.state.sqlite_conversation_state import (
        SqliteConversationState,
    )

    state_root = tmp_path / "state"
    database_parent = state_root / "nested"
    state = SqliteConversationState(
        database_parent / "conversations.sqlite3",
        trusted_state_root=state_root,
    )
    sidecar = database_parent / (
        f".{state.database_path.name}.inode-wal"
    )
    sidecar.write_bytes(b"opened-sidecar")
    sidecar.chmod(0o600)
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    protected = outside / sidecar.name
    protected.write_bytes(b"must-not-change")
    protected.chmod(0o640)
    moved_parent = state_root / "moved"
    original_open = trusted_sqlite_storage.os.open
    drifted = False

    def drift_after_open(
        path,
        flags,
        mode=0o777,
        *,
        dir_fd=None,
    ):
        nonlocal drifted
        descriptor = original_open(
            path,
            flags,
            mode,
            dir_fd=dir_fd,
        )
        if path == sidecar.name and dir_fd is not None and not drifted:
            drifted = True
            database_parent.rename(moved_parent)
            database_parent.symlink_to(
                outside,
                target_is_directory=True,
            )
        return descriptor

    monkeypatch.setattr(
        trusted_sqlite_storage.os,
        "open",
        drift_after_open,
    )

    with pytest.raises(ValueError, match="database parent.*changed"):
        state._secure_database_files()

    assert drifted is True
    assert database_parent.is_symlink()
    assert protected.read_bytes() == b"must-not-change"
    assert stat.S_IMODE(protected.stat().st_mode) == 0o640


def test_connect_rechecks_sidecar_anchor_after_sqlite_path_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.guide.adapters.state import trusted_sqlite_storage

    state = _state(tmp_path)
    anchor = state.database_path.parent / (
        f".{state.database_path.name}.inode"
    )
    sidecar = anchor.with_name(f"{anchor.name}-wal")
    protected = tmp_path / "protected-connect"
    protected.write_bytes(b"must-not-change")
    protected.chmod(0o640)
    keeper = sqlite3.connect(anchor)
    keeper.execute("SELECT * FROM conversations").fetchall()
    assert sidecar.is_file()
    original_connect = trusted_sqlite_storage.sqlite3.connect
    replaced = False

    def replace_after_connect(*args, **kwargs):
        nonlocal replaced
        connection = original_connect(*args, **kwargs)
        if not replaced:
            replaced = True
            sidecar.unlink()
            sidecar.symlink_to(protected)
        return connection

    monkeypatch.setattr(
        trusted_sqlite_storage.sqlite3,
        "connect",
        replace_after_connect,
    )
    try:
        with pytest.raises(ValueError, match="database file.*changed"):
            with state._storage.connect():
                pass
        assert replaced is True
        assert protected.read_bytes() == b"must-not-change"
        assert stat.S_IMODE(protected.stat().st_mode) == 0o640
    finally:
        keeper.close()


def test_transaction_rechecks_sidecar_anchor_after_begin(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    anchor = state.database_path.parent / (
        f".{state.database_path.name}.inode"
    )
    sidecar = anchor.with_name(f"{anchor.name}-wal")
    protected = tmp_path / "protected-transaction"
    protected.write_bytes(b"must-not-change")
    protected.chmod(0o640)
    keeper = sqlite3.connect(anchor)
    keeper.execute("SELECT * FROM conversations").fetchall()
    assert sidecar.is_file()
    replaced = False

    def replace_during_begin(statement: str) -> None:
        nonlocal replaced
        if statement == "BEGIN IMMEDIATE" and not replaced:
            replaced = True
            sidecar.unlink()
            os.link(protected, sidecar)

    try:
        with pytest.raises(ValueError, match="database file.*changed"):
            with state._storage.connect() as connection:
                connection.set_trace_callback(replace_during_begin)
                connection.execute("BEGIN IMMEDIATE")
        assert replaced is True
        assert protected.read_bytes() == b"must-not-change"
        assert stat.S_IMODE(protected.stat().st_mode) == 0o640
    finally:
        keeper.close()


def test_adapter_has_no_second_consultation_authority() -> None:
    from app.guide.adapters.state import sqlite_conversation_state

    source = Path(sqlite_conversation_state.__file__).read_text(
        encoding="utf-8"
    )
    assert "ConversationStatePort" not in source
    assert "ConsultationStatePort" not in source
    assert "ConsultationSnapshot" not in source
