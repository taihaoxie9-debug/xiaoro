from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from decimal import Decimal
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import textwrap
import threading

import pytest
from pydantic import ValidationError

from app.guide.feedback.consultation_state import ConsultationSubstate
from app.guide.feedback.contracts import (
    ClarificationProgress,
    ConsultationSlotState,
    ConversationSnapshot,
    DisplayedCandidateRef,
    KnowledgeSlotState,
    PendingClarificationSlot,
    ProductSlotState,
    RecommendationQueryContext,
    RecommendationSlotState,
)
from app.guide.feedback.focus_state import ActiveFocus
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
from app.guide.intent.responsibility_matrix import Responsibility
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
        active_owner=Responsibility.RECOMMENDATION,
        active_focus=ActiveFocus(
            slot="recommendation",
            ordinal=focused_candidate_ordinal,
        ),
        recommendation_slot=RecommendationSlotState(
            query_context=RecommendationQueryContext(
                category=category,
                recommendation_mode_basis="broad_exploration",
                budget_minimum=Decimal("100.50"),
                budget_maximum=Decimal("500"),
                skin="sensitive",
                efficacy="repair" if category == "serum" else None,
                exclusions=["酒精", "香精"],
            ),
            candidates=tuple(
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
            ),
            focused_candidate_ordinal=focused_candidate_ordinal,
        ),
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


def test_bool_expected_version_is_rejected(tmp_path: Path) -> None:
    state = _state(tmp_path)

    with pytest.raises(
        ValueError,
        match="expected_version must be a non-negative integer",
    ):
        state.save(
            _recommendation(session_id="bool-version"),
            expected_version=False,
        )


def test_save_reconciles_post_commit_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(tmp_path)
    snapshot = _recommendation(session_id="post-commit-reconcile")
    secure_database_files = state._secure_database_files
    save_in_transaction = state._save_in_transaction
    cleanup_calls = 0
    write_attempts = 0

    def fail_first_cleanup() -> None:
        nonlocal cleanup_calls
        cleanup_calls += 1
        if cleanup_calls == 1:
            raise PermissionError("injected post-commit cleanup failure")
        secure_database_files()

    def record_write_attempt(
        connection,
        *,
        snapshot,
        expected_version,
    ):
        nonlocal write_attempts
        write_attempts += 1
        return save_in_transaction(
            connection,
            snapshot=snapshot,
            expected_version=expected_version,
        )

    monkeypatch.setattr(
        state,
        "_secure_database_files",
        fail_first_cleanup,
    )
    monkeypatch.setattr(
        state,
        "_save_in_transaction",
        record_write_attempt,
    )

    assert state.save(snapshot, expected_version=0) == snapshot
    assert write_attempts == 1
    assert state.load(snapshot.session_id) == snapshot


def test_save_recognizes_commit_that_raises_after_sqlite_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.guide.adapters.state import trusted_sqlite_storage

    state = _state(tmp_path)
    snapshot = _recommendation(session_id="commit-postcheck")
    original_commit = (
        trusted_sqlite_storage._AnchoredSqliteConnection.commit
    )
    commit_calls = 0

    def commit_then_raise(connection) -> None:
        nonlocal commit_calls
        commit_calls += 1
        original_commit(connection)
        if commit_calls == 1:
            raise PermissionError(
                "injected post-commit verification failure"
            )

    monkeypatch.setattr(
        trusted_sqlite_storage._AnchoredSqliteConnection,
        "commit",
        commit_then_raise,
    )

    assert state.save(snapshot, expected_version=0) == snapshot


def test_post_commit_reconciliation_accepts_a_later_valid_cas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(tmp_path)
    concurrent = _state(tmp_path)
    first = _recommendation(session_id="post-commit-race")
    second = _recommendation(
        session_id=first.session_id,
        version=2,
        product_id=38,
    )
    secure_database_files = state._secure_database_files
    reconcile = state._reconcile_post_commit_save
    reconciliation_started = threading.Event()
    writer_finished = threading.Event()
    cleanup_calls = 0
    writer_errors: list[BaseException] = []

    def fail_first_cleanup() -> None:
        nonlocal cleanup_calls
        cleanup_calls += 1
        if cleanup_calls == 1:
            raise PermissionError("injected post-commit cleanup failure")
        secure_database_files()

    def delayed_reconcile(snapshot, *, error):
        reconciliation_started.set()
        assert writer_finished.wait(timeout=5)
        return reconcile(snapshot, error=error)

    def advance_state() -> None:
        assert reconciliation_started.wait(timeout=5)
        try:
            concurrent.save(second, expected_version=1)
        except BaseException as error:
            writer_errors.append(error)
        finally:
            writer_finished.set()

    monkeypatch.setattr(
        state,
        "_secure_database_files",
        fail_first_cleanup,
    )
    monkeypatch.setattr(
        state,
        "_reconcile_post_commit_save",
        delayed_reconcile,
    )
    writer = threading.Thread(target=advance_state, daemon=True)
    writer.start()

    assert state.save(first, expected_version=0) == first
    writer.join(timeout=5)
    assert not writer.is_alive()
    assert writer_errors == []
    assert concurrent.load(first.session_id) == second


def test_connection_close_failure_releases_storage_lock(
    tmp_path: Path,
) -> None:
    script = textwrap.dedent(
        """
        from pathlib import Path
        import sqlite3
        import sys

        from app.guide.adapters.state import trusted_sqlite_storage
        from app.guide.adapters.state.sqlite_conversation_state import (
            SqliteConversationState,
        )
        from tests.guide.adapters.state.test_sqlite_conversation_state import (
            _recommendation,
        )

        root = Path(sys.argv[1])
        state = SqliteConversationState(
            root / "conversations.sqlite3",
            trusted_state_root=root,
        )
        original_close = (
            trusted_sqlite_storage._AnchoredSqliteConnection.close
        )
        close_calls = [0]

        def close_then_raise(connection):
            close_calls[0] += 1
            original_close(connection)
            if close_calls[0] == 1:
                raise PermissionError("injected close failure")

        trusted_sqlite_storage._AnchoredSqliteConnection.close = (
            close_then_raise
        )
        snapshot = _recommendation(session_id="close-postcommit")
        assert state.save(snapshot, expected_version=0) == snapshot
        print("saved", flush=True)
        """
    )

    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "state")],
        cwd=Path.cwd(),
        env={**os.environ, "PYTHONPATH": str(Path.cwd())},
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "saved"


def test_delete_reconciles_post_commit_cleanup_failure_without_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(tmp_path)
    owner = _owner(subject_id="delete-reconcile-owner")
    snapshot = state.save(
        _recommendation(
            session_id="delete-post-commit-reconcile",
            owner=owner,
        ),
        expected_version=0,
    )
    secure_database_files = state._secure_database_files
    transaction = state._transaction
    load = state.load
    cleanup_calls = 0
    write_attempts = 0
    reconciliation_reads = 0

    def fail_first_cleanup() -> None:
        nonlocal cleanup_calls
        cleanup_calls += 1
        if cleanup_calls == 1:
            raise PermissionError("injected post-commit cleanup failure")
        secure_database_files()

    @contextmanager
    def record_write_attempt(session_id):
        nonlocal write_attempts
        write_attempts += 1
        with transaction(session_id) as connection:
            yield connection

    def record_reconciliation_read(session_id):
        nonlocal reconciliation_reads
        reconciliation_reads += 1
        return load(session_id)

    monkeypatch.setattr(
        state,
        "_secure_database_files",
        fail_first_cleanup,
    )
    monkeypatch.setattr(state, "_transaction", record_write_attempt)
    monkeypatch.setattr(state, "load", record_reconciliation_read)

    assert state.delete(
        snapshot.session_id,
        expected_owner=owner,
    )
    assert write_attempts == 1
    assert reconciliation_reads == 1
    assert load(snapshot.session_id) is None


def test_delete_preserves_post_commit_no_op_false_without_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(tmp_path)
    owner = _owner(subject_id="delete-no-op-owner")
    foreign = _owner(subject_id="delete-no-op-foreign")
    snapshot = state.save(
        _recommendation(
            session_id="delete-post-commit-no-op",
            owner=owner,
        ),
        expected_version=0,
    )
    secure_database_files = state._secure_database_files
    transaction = state._transaction
    load = state.load
    cleanup_calls = 0
    write_attempts = 0
    reconciliation_reads = 0

    def fail_first_cleanup() -> None:
        nonlocal cleanup_calls
        cleanup_calls += 1
        if cleanup_calls == 1:
            raise PermissionError("injected post-commit cleanup failure")
        secure_database_files()

    @contextmanager
    def record_write_attempt(session_id):
        nonlocal write_attempts
        write_attempts += 1
        with transaction(session_id) as connection:
            yield connection

    def record_reconciliation_read(session_id):
        nonlocal reconciliation_reads
        reconciliation_reads += 1
        return load(session_id)

    monkeypatch.setattr(
        state,
        "_secure_database_files",
        fail_first_cleanup,
    )
    monkeypatch.setattr(state, "_transaction", record_write_attempt)
    monkeypatch.setattr(state, "load", record_reconciliation_read)

    assert not state.delete(
        snapshot.session_id,
        expected_owner=foreign,
    )
    assert write_attempts == 1
    assert reconciliation_reads == 1
    assert load(snapshot.session_id) == snapshot


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
            },
            deep=True,
        ),
        expected_version=0,
    )

    assert state.load(stored.session_id).session_profile is not None
    assert state.load(stored.session_id).active_focus is not None
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


def test_delete_of_unknown_session_does_not_create_permanent_tombstone(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    owner = _owner(subject_id="unknown-delete-owner")
    session_id = "never-created-session"

    assert not state.delete(session_id, expected_owner=owner)

    with sqlite3.connect(state.database_path) as connection:
        tombstone_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM conversation_tombstones
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()[0]
    assert tombstone_count == 0
    stored = state.save(
        _recommendation(session_id=session_id, owner=owner),
        expected_version=0,
    )
    assert stored.version == 1


def test_deleted_session_rejects_stale_version_zero_recreation(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    owner = _owner(subject_id="deleted-session-owner")
    snapshot = state.save(
        _recommendation(
            session_id="deleted-session-generation",
            owner=owner,
        ),
        expected_version=0,
    )

    assert state.delete(
        snapshot.session_id,
        expected_owner=owner,
    )
    with pytest.raises(ConversationStateConflict):
        state.save(
            _recommendation(
                session_id=snapshot.session_id,
                owner=owner,
            ),
            expected_version=0,
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
            "consultation_slot": ConsultationSlotState(
                state=ConsultationSubstate(
                    started_at_conversation_version=2,
                    observations=[],
                )
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
    assert (
        loaded.recommendation_slot
        is not saved.recommendation_slot
    )
    payload = loaded.model_dump(mode="json")
    query = payload["recommendation_slot"]["query_context"]
    assert query["budget_minimum"] == "100.50"
    assert isinstance(query["exclusions"], list)
    assert isinstance(payload["recommendation_slot"]["candidates"], list)
    assert isinstance(
        payload["consultation_slot"]["state"]["observations"],
        list,
    )


def test_restart_round_trips_active_product_focus(tmp_path: Path) -> None:
    state = _state(tmp_path)
    current = _recommendation(
        session_id="focus-restart",
        product_ids=(51, 55, 101),
        focused_candidate_ordinal=2,
    ).model_copy(
        update={
            "active_owner": Responsibility.PRODUCT_KNOWLEDGE,
            "active_focus": ActiveFocus(
                slot="product",
                object_id=55,
            ),
            "product_slot": ProductSlotState(
                products=(
                    DisplayedCandidateRef(
                        product_id=55,
                        ordinal=1,
                        skin_match="matched",
                        matched_efficacies=("修护",),
                    ),
                ),
                focused_product_id=55,
            ),
            "knowledge_slot": KnowledgeSlotState(
                question="询问第二款补涂方式",
                evidence_ids=(),
            ),
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
    assert loaded.active_focus.object_id == 55
    assert loaded.product_slot.focused_product_id == 55
    assert loaded.knowledge_slot.question == "询问第二款补涂方式"


def test_restart_round_trips_clarification_only_state(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    stored = state.save(
        ConversationSnapshot(
            session_id="clarification-restart",
            version=1,
            active_owner=Responsibility.CLARIFICATION,
            active_focus=ActiveFocus(slot="reply"),
            reply_slot=PendingClarificationSlot(
                value=ClarificationProgress(
                    gap=ClarificationCode.REFERENCE,
                    attempts=1,
                )
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
    assert (
        loaded.reply_slot.value.gap
        is ClarificationCode.REFERENCE
    )


def test_restart_round_trips_general_knowledge_focus(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    stored = state.save(
        ConversationSnapshot(
            session_id="knowledge-restart",
            version=1,
            active_owner=Responsibility.GENERAL_KNOWLEDGE,
            active_focus=ActiveFocus(slot="knowledge"),
            knowledge_slot=KnowledgeSlotState(
                evidence_ids=(
                    "a" * 64,
                    "b" * 64,
                ),
                question="SPF是什么意思",
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
    assert loaded.knowledge_slot.evidence_ids == (
        "a" * 64,
        "b" * 64,
    )
    assert loaded.knowledge_slot.question == "SPF是什么意思"


def test_general_knowledge_focus_ids_must_be_sorted_unique() -> None:
    with pytest.raises(
        ValidationError,
        match="knowledge evidence IDs must be sorted and unique",
    ):
        ConversationSnapshot(
            session_id="invalid-knowledge-focus",
            version=1,
            active_owner=Responsibility.GENERAL_KNOWLEDGE,
            active_focus=ActiveFocus(slot="knowledge"),
            knowledge_slot=KnowledgeSlotState(
                evidence_ids=(
                    "b" * 64,
                    "a" * 64,
                    "b" * 64,
                ),
                question="继续问",
            ),
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
                active_owner=Responsibility.CLARIFICATION,
                active_focus=ActiveFocus(slot="reply"),
                reply_slot=PendingClarificationSlot(
                    value=ClarificationProgress(
                        gap=ClarificationCode.TOPIC,
                        attempts=2,
                    )
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
    candidates = loaded.recommendation_slot.candidates
    assert [item.ordinal for item in candidates] == [1, 2, 3, 4]
    assert [item.product_id for item in candidates] == [
        91,
        38,
        55,
        72,
    ]
    assert loaded.recommendation_slot.focused_candidate_ordinal == 4
    with pytest.raises(ConversationStateConflict):
        restarted.save(
            current.model_copy(update={"version": 2}, deep=True),
            expected_version=0,
        )
    assert restarted.load(current.session_id) == current
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
    assert loaded.recommendation_slot is not None
    assert (
        loaded.recommendation_slot.query_context.category
        == topic.value
    )


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


_LEGACY_V1_SCHEMA = """
CREATE TABLE conversations (
    session_id TEXT NOT NULL PRIMARY KEY,
    snapshot_version INTEGER NOT NULL CHECK (snapshot_version >= 1),
    owner_scope TEXT CHECK (
        owner_scope IS NULL OR owner_scope IN (
            'authenticated_user',
            'local_demo',
            'anonymous_browser'
        )
    ),
    owner_subject_id TEXT,
    snapshot_json TEXT NOT NULL,
    CHECK (
        (owner_scope IS NULL AND owner_subject_id IS NULL)
        OR
        (owner_scope IS NOT NULL AND owner_subject_id IS NOT NULL)
    )
)
"""
_V2_SNAPSHOT_KEYS = {
    "session_id",
    "version",
    "profile_owner",
    "session_profile",
    "active_owner",
    "active_focus",
    "recommendation_slot",
    "product_slot",
    "image_slot",
    "consultation_slot",
    "knowledge_slot",
    "reply_slot",
}


def _legacy_v1_payload(
    session_id: str,
    *,
    include_recommendation_basis: bool,
) -> dict[str, object]:
    query = RecommendationQueryContext(
        category="serum",
        recommendation_mode="explore",
        recommendation_mode_basis="broad_exploration",
        recommendation_count=2,
        budget_minimum=Decimal("100"),
        budget_maximum=Decimal("500"),
    ).model_dump(mode="json")
    if not include_recommendation_basis:
        del query["recommendation_mode_basis"]
    return {
        "session_id": session_id,
        "version": 1,
        "profile_owner": None,
        "session_profile": None,
        "focus_state": {
            "active_processor": (
                "recommendation"
                if include_recommendation_basis
                else "consultation"
            ),
            "current_product_id": None,
            "confirmed_image_products": [
                {
                    "image_ordinal": 1,
                    "product_id": 53,
                    "variant_scope": None,
                }
            ],
            "current_knowledge_topic": "防晒补涂",
            "last_question_meaning": "防晒为什么需要补涂",
        },
        "has_image_delivery": True,
        "query_context": query,
        "empty_result": False,
        "candidates": [
            DisplayedCandidateRef(
                product_id=91,
                ordinal=1,
                skin_match="matched",
                matched_efficacies=("修护",),
            ).model_dump(mode="json"),
            DisplayedCandidateRef(
                product_id=38,
                ordinal=2,
                skin_match="matched",
                matched_efficacies=("保湿",),
            ).model_dump(mode="json"),
        ],
        "focused_candidate_ordinal": 1,
        "focused_evidence_ids": ["a" * 64],
        "focused_general_knowledge_ids": ["b" * 64],
        "last_general_knowledge_question": "防晒为什么需要补涂",
        "consultation": ConsultationSubstate(
            started_at_conversation_version=1,
        ).model_dump(mode="json"),
        "clarification": None,
        "pending_turn": None,
    }


def _create_schema_v1_database(
    database_path: Path,
    payloads: tuple[dict[str, object], ...],
) -> None:
    def owner_columns(
        payload: dict[str, object],
    ) -> tuple[str | None, str | None]:
        owner = payload.get("profile_owner")
        if not isinstance(owner, dict):
            return None, None
        scope = owner.get("scope")
        subject_id = owner.get("subject_id")
        return (
            scope if isinstance(scope, str) else None,
            subject_id if isinstance(subject_id, str) else None,
        )

    database_path.parent.mkdir(mode=0o700, parents=True)
    with sqlite3.connect(database_path) as connection:
        connection.execute(_LEGACY_V1_SCHEMA)
        connection.execute("PRAGMA application_id = 1481786198")
        connection.execute("PRAGMA user_version = 1")
        connection.executemany(
            """
            INSERT INTO conversations (
                session_id,
                snapshot_version,
                owner_scope,
                owner_subject_id,
                snapshot_json
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    payload["session_id"],
                    payload["version"],
                    *owner_columns(payload),
                    json.dumps(
                        payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                )
                for payload in payloads
            ],
        )
        connection.commit()
    os.chmod(database_path, 0o600)


def _current_v2_payload(session_id: str) -> dict[str, object]:
    return {
        "session_id": session_id,
        "version": 1,
        "profile_owner": None,
        "session_profile": None,
        "active_owner": "recommendation",
        "active_focus": {
            "slot": "recommendation",
            "object_id": None,
            "ordinal": None,
        },
        "recommendation_slot": {
            "kind": "recommendation",
            "query_context": RecommendationQueryContext(
                category="serum",
                recommendation_mode="explore",
                recommendation_mode_basis="broad_exploration",
                recommendation_count=2,
            ).model_dump(mode="json"),
            "candidates": [
                DisplayedCandidateRef(
                    product_id=91,
                    ordinal=1,
                    skin_match="unknown",
                    matched_efficacies=(),
                ).model_dump(mode="json"),
                DisplayedCandidateRef(
                    product_id=38,
                    ordinal=2,
                    skin_match="unknown",
                    matched_efficacies=(),
                ).model_dump(mode="json"),
            ],
            "empty_result": False,
            "focused_candidate_ordinal": None,
            "card_display": None,
        },
        "product_slot": None,
        "image_slot": None,
        "consultation_slot": None,
        "knowledge_slot": None,
        "reply_slot": None,
    }


def test_schema_v1_rows_are_atomically_migrated_to_v2(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state" / "conversations.sqlite3"
    payloads = (
        _legacy_v1_payload(
            "legacy-valid-recommendation",
            include_recommendation_basis=True,
        ),
        _legacy_v1_payload(
            "legacy-missing-basis",
            include_recommendation_basis=False,
        ),
    )
    _create_schema_v1_database(database_path, payloads)

    state = _state(tmp_path)

    with state._storage.connect() as connection:
        assert connection.execute(
            "PRAGMA user_version"
        ).fetchone() == (3,)
        migrated_rows = {
            session_id: json.loads(snapshot_json)
            for session_id, snapshot_json in connection.execute(
                """
                SELECT session_id, snapshot_json
                FROM conversations
                ORDER BY session_id
                """
            ).fetchall()
        }

    assert set(migrated_rows) == {
        "legacy-valid-recommendation",
        "legacy-missing-basis",
    }
    assert all(
        set(payload) == _V2_SNAPSHOT_KEYS
        for payload in migrated_rows.values()
    )
    assert (
        migrated_rows["legacy-valid-recommendation"][
            "recommendation_slot"
        ]
        is not None
    )
    assert (
        migrated_rows["legacy-missing-basis"]["recommendation_slot"]
        is None
    )
    assert (
        migrated_rows["legacy-missing-basis"]["consultation_slot"]
        is not None
    )
    assert state.load("legacy-valid-recommendation") is not None
    assert state.load("legacy-missing-basis") is not None


def test_v1_migration_preserves_dormant_product_focus(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state" / "conversations.sqlite3"
    legacy = _legacy_v1_payload(
        "legacy-dormant-product-focus",
        include_recommendation_basis=True,
    )
    legacy["focus_state"]["active_processor"] = "general_knowledge"
    legacy["focus_state"]["current_product_id"] = 38
    _create_schema_v1_database(database_path, (legacy,))

    state = _state(tmp_path)
    loaded = state.load("legacy-dormant-product-focus")

    assert loaded is not None
    assert loaded.active_owner is Responsibility.GENERAL_KNOWLEDGE
    assert loaded.active_focus == ActiveFocus(slot="knowledge")
    assert loaded.product_slot is not None
    assert [
        item.product_id for item in loaded.product_slot.products
    ] == [91, 38]
    assert loaded.product_slot.focused_product_id == 38


def test_schema_v1_migration_preserves_dormant_four_image_slot(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state" / "conversations.sqlite3"
    dormant = _legacy_v1_payload(
        "legacy-dormant-images",
        include_recommendation_basis=False,
    )
    dormant["focus_state"]["active_processor"] = "recommendation"
    dormant["focus_state"]["confirmed_image_products"] = [
        {
            "image_ordinal": ordinal,
            "product_id": 50 + ordinal,
            "variant_scope": None,
        }
        for ordinal in range(1, 5)
    ]
    dormant["last_general_knowledge_question"] = None
    dormant["focused_general_knowledge_ids"] = []
    dormant["consultation"] = None
    _create_schema_v1_database(database_path, (dormant,))

    state = _state(tmp_path)
    loaded = state.load("legacy-dormant-images")

    assert loaded is not None
    assert loaded.active_owner is None
    assert loaded.active_focus is None
    assert loaded.image_slot is not None
    assert [
        item.image_ordinal
        for item in loaded.image_slot.confirmed_products
    ] == [1, 2, 3, 4]


def test_schema_v1_migration_normalizes_sparse_image_focus(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state" / "conversations.sqlite3"
    legacy = _legacy_v1_payload(
        "legacy-sparse-image-focus",
        include_recommendation_basis=False,
    )
    legacy["focus_state"]["active_processor"] = "image_identity"
    legacy["focus_state"]["current_product_id"] = 82
    legacy["focus_state"]["confirmed_image_products"] = [
        {
            "image_ordinal": 2,
            "product_id": 82,
            "variant_scope": None,
        }
    ]
    legacy["last_general_knowledge_question"] = None
    legacy["focused_general_knowledge_ids"] = []
    legacy["consultation"] = None
    _create_schema_v1_database(database_path, (legacy,))

    state = _state(tmp_path)
    loaded = state.load("legacy-sparse-image-focus")

    assert loaded is not None
    assert loaded.image_slot is not None
    assert [
        item.image_ordinal
        for item in loaded.image_slot.confirmed_products
    ] == [1]
    assert loaded.image_slot.focused_image_ordinal == 1
    assert loaded.active_focus == ActiveFocus(
        slot="image",
        object_id=82,
        ordinal=1,
    )


def test_schema_v1_comparison_keeps_image_owned_current_product_focus(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state" / "conversations.sqlite3"
    legacy = _legacy_v1_payload(
        "legacy-comparison-image-focus",
        include_recommendation_basis=True,
    )
    legacy["focus_state"]["active_processor"] = "comparison"
    legacy["focus_state"]["current_product_id"] = 53
    legacy["focus_state"]["confirmed_image_products"] = [
        {
            "image_ordinal": 2,
            "product_id": 53,
            "variant_scope": None,
        }
    ]
    _create_schema_v1_database(database_path, (legacy,))

    state = _state(tmp_path)
    loaded = state.load("legacy-comparison-image-focus")

    assert loaded is not None
    assert loaded.active_owner is Responsibility.COMPARISON
    assert loaded.product_slot is not None
    assert [
        item.product_id for item in loaded.product_slot.products
    ] == [91, 38]
    assert loaded.image_slot is not None
    assert loaded.active_focus == ActiveFocus(
        slot="image",
        object_id=53,
        ordinal=1,
    )


def test_schema_v1_migration_discards_only_irrecoverable_image_state(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state" / "conversations.sqlite3"
    legacy = _legacy_v1_payload(
        "legacy-ambiguous-image-state",
        include_recommendation_basis=True,
    )
    legacy["focus_state"]["active_processor"] = "image_identity"
    legacy["focus_state"]["current_product_id"] = 53
    legacy["focus_state"]["confirmed_image_products"] = [
        {
            "image_ordinal": 1,
            "product_id": 53,
            "variant_scope": None,
        },
        {
            "image_ordinal": 2,
            "product_id": 53,
            "variant_scope": None,
        },
    ]
    legacy["last_general_knowledge_question"] = None
    legacy["focused_general_knowledge_ids"] = []
    legacy["consultation"] = None
    _create_schema_v1_database(database_path, (legacy,))

    state = _state(tmp_path)
    loaded = state.load("legacy-ambiguous-image-state")

    assert loaded is not None
    assert loaded.active_owner is None
    assert loaded.active_focus is None
    assert loaded.recommendation_slot is not None
    assert loaded.image_slot is None


def test_schema_v1_migration_keeps_valid_fourth_comparison_focus(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state" / "conversations.sqlite3"
    legacy = _legacy_v1_payload(
        "legacy-fourth-comparison-focus",
        include_recommendation_basis=True,
    )
    legacy["focus_state"]["active_processor"] = "comparison"
    legacy["focus_state"]["current_product_id"] = 44
    legacy["candidates"] = [
        DisplayedCandidateRef(
            product_id=40 + ordinal,
            ordinal=ordinal,
            skin_match="unknown",
            matched_efficacies=(),
        ).model_dump(mode="json")
        for ordinal in range(1, 5)
    ]
    _create_schema_v1_database(database_path, (legacy,))

    state = _state(tmp_path)
    loaded = state.load("legacy-fourth-comparison-focus")

    assert loaded is not None
    assert loaded.product_slot is not None
    assert [
        item.product_id for item in loaded.product_slot.products
    ] == [41, 42, 43, 44]
    assert loaded.product_slot.focused_product_id == 44


def test_schema_v1_irrecoverable_recommendation_row_is_dropped(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state" / "conversations.sqlite3"
    invalid = _legacy_v1_payload(
        "legacy-invalid-recommendation",
        include_recommendation_basis=False,
    )
    invalid["focus_state"]["active_processor"] = "recommendation"
    invalid["focus_state"]["confirmed_image_products"] = []
    invalid["last_general_knowledge_question"] = None
    invalid["focused_general_knowledge_ids"] = []
    invalid["consultation"] = None
    _create_schema_v1_database(
        database_path,
        (
            _legacy_v1_payload(
                "legacy-valid-recommendation",
                include_recommendation_basis=True,
            ),
            invalid,
        ),
    )

    state = _state(tmp_path)

    with state._storage.connect() as connection:
        assert connection.execute(
            "PRAGMA user_version"
        ).fetchone() == (3,)
        session_ids = {
            row[0]
            for row in connection.execute(
                "SELECT session_id FROM conversations"
            ).fetchall()
        }
    assert session_ids == {"legacy-valid-recommendation"}
    assert state.load("legacy-valid-recommendation") is not None
    assert state.load("legacy-invalid-recommendation") is None


def test_v1_migration_tombstones_discarded_session(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "state" / "conversations.sqlite3"
    owner = _owner(subject_id="legacy-discarded-owner")
    invalid = _legacy_v1_payload(
        "legacy-discarded-session",
        include_recommendation_basis=False,
    )
    invalid["version"] = 7
    invalid["profile_owner"] = owner.model_dump(mode="json")
    invalid["focus_state"]["active_processor"] = "recommendation"
    invalid["focus_state"]["confirmed_image_products"] = []
    invalid["last_general_knowledge_question"] = None
    invalid["focused_general_knowledge_ids"] = []
    invalid["consultation"] = None
    _create_schema_v1_database(database_path, (invalid,))

    state = _state(tmp_path)

    with state._storage.connect() as connection:
        tombstone = connection.execute(
            """
            SELECT deleted_version, owner_scope, owner_subject_id
            FROM conversation_tombstones
            WHERE session_id = ?
            """,
            ("legacy-discarded-session",),
        ).fetchone()
    assert tombstone == (
        7,
        owner.scope,
        owner.subject_id,
    )
    assert state.load("legacy-discarded-session") is None
    with pytest.raises(ConversationStateConflict):
        state.save(
            _recommendation(
                session_id="legacy-discarded-session",
                owner=owner,
            ),
            expected_version=0,
        )


def test_current_schema_load_does_not_invoke_legacy_dual_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.guide.adapters.state import sqlite_conversation_state

    state = _state(tmp_path)
    payload = _current_v2_payload("current-v2-no-dual-read")
    with state._storage.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO conversations (
                session_id,
                snapshot_version,
                owner_scope,
                owner_subject_id,
                snapshot_json
            )
            VALUES (?, ?, NULL, NULL, ?)
            """,
            (
                payload["session_id"],
                payload["version"],
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            ),
        )
        connection.commit()

    def fail_legacy_dual_read(_payload):
        raise AssertionError("runtime load invoked legacy migration")

    monkeypatch.setattr(
        sqlite_conversation_state,
        "migrate_legacy_conversation_snapshot_payload",
        fail_legacy_dual_read,
        raising=False,
    )

    loaded = state.load("current-v2-no-dual-read")

    assert loaded is not None
    assert loaded.model_dump(mode="json") == payload
