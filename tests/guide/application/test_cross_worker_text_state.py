from __future__ import annotations

import asyncio
from decimal import Decimal
from hashlib import sha256
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
from threading import get_ident

import numpy as np
import pytest

from app.guide_runtime import composition
from app.guide.adapters.image.safe_image_input import UntrustedImageInput
from app.guide.adapters.state import (
    InMemoryImageBundleState,
    SqliteConversationState,
)
from app.guide.application.contracts import TurnIdentity, UserTurn
from app.guide.application.image_bundle_service import ImageBundleService
from app.guide.feedback.ports import ConversationStateConflict
from app.guide.feedback.contracts import (
    KnowledgeSlotState,
    PendingClarificationSlot,
    ProductSlotState,
    RecommendationSlotState,
    ConversationSnapshot,
    DisplayedCandidateRef,
    RecommendationQueryContext,
)
from app.guide.feedback.focus_state import ActiveFocus
from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.retrieval.image_contracts import ApprovedImageModelLock
from app.guide.understanding.semantic_contracts import ClarificationCode
from app.guide.understanding.turn_meaning_contracts import TurnMeaning
from app.guide_runtime.composition import (
    REPO_ROOT,
    build_consultation_vertical_runtime as _build_consultation_vertical_runtime,
    conversation_database_path,
    guide_state_directory,
    guide_image_runtime_lock,
)
from app.guide_runtime.sse import (
    iterate_http_events_in_threadpool,
)


class CrossWorkerTurnMeaningPort:
    def propose(self, message, context) -> TurnMeaning:
        del context
        if message == "第二款呢":
            return TurnMeaning(
                operation_hint="followup",
                topic_hint=None,
                continuity_hint="continue",
                subject_scope_hint="self",
                reference_mentions=(
                    {
                        "raw_text": "第二款",
                        "object_family_hint": "product",
                        "ordinal_hint": 2,
                        "plurality_hint": "single",
                    },
                ),
                question_meaning="继续查看第二款",
                safety_language="ordinary",
            )
        if message.startswith("预算降到"):
            amount = message.removeprefix("预算降到").removesuffix("元呢")
            return TurnMeaning(
                operation_hint="followup",
                topic_hint=None,
                continuity_hint="continue",
                subject_scope_hint="self",
                reference_mentions=(
                    {
                        "raw_text": "预算",
                        "object_family_hint": "constraint",
                        "ordinal_hint": None,
                        "plurality_hint": "single",
                    },
                ),
                budget_candidates=(
                    {
                        "raw_text": f"{amount}元",
                        "relation": "maximum",
                        "minimum": None,
                        "maximum": amount,
                    },
                ),
                question_meaning=f"把原推荐预算上限改为{amount}元",
                safety_language="ordinary",
            )
        if message == "150元以内找相似款":
            return TurnMeaning(
                operation_hint="image_similarity",
                recommendation_mode="explore",
                recommendation_count=None,
                recommendation_mode_basis={
                    "basis": "similar_alternatives",
                    "source_text": "相似款",
                },
                topic_hint="sunscreen",
                continuity_hint="new_task",
                subject_scope_hint="self",
                reference_mentions=(
                    {
                        "raw_text": "相似款",
                        "object_family_hint": "image",
                        "ordinal_hint": 1,
                        "plurality_hint": "single",
                    },
                ),
                budget_candidates=(
                    {
                        "raw_text": "150元以内",
                        "relation": "maximum",
                        "minimum": None,
                        "maximum": "150",
                    },
                ),
                question_meaning="查找预算内的相似防晒",
                safety_language="ordinary",
            )
        if message == "帮我看看":
            return TurnMeaning(
                operation_hint="clarification",
                topic_hint=None,
                continuity_hint="unknown",
                subject_scope_hint="self",
                question_meaning="需求不完整",
                safety_language="ordinary",
            )
        budget_text = next(
            (
                value
                for value in ("500 元内", "100元内", "0 元以内")
                if value in message
            ),
            None,
        )
        return TurnMeaning(
            operation_hint="recommendation",
            recommendation_mode="explore",
            recommendation_count=None,
            recommendation_mode_basis={
                "basis": (
                    "bounded_exploration"
                    if budget_text is not None
                    else "broad_exploration"
                ),
                "source_text": budget_text or "防晒",
            },
            topic_hint="serum" if "精华" in message else "sunscreen",
            continuity_hint="new_task",
            subject_scope_hint="self",
            budget_candidates=(
                (
                    {
                        "raw_text": budget_text,
                        "relation": "maximum",
                        "minimum": None,
                        "maximum": (
                            "500"
                            if budget_text == "500 元内"
                            else "100"
                            if budget_text == "100元内"
                            else "0"
                        ),
                    },
                )
                if budget_text is not None
                else ()
            ),
            question_meaning=message,
            safety_language="ordinary",
        )


def build_consultation_vertical_runtime(*args, **kwargs):
    kwargs.setdefault(
        "semantic_intent",
        CrossWorkerTurnMeaningPort(),
    )
    return _build_consultation_vertical_runtime(*args, **kwargs)


def build_unified_runtime(*args, **kwargs):
    return build_consultation_vertical_runtime(
        *args,
        **kwargs,
    ).unified


def _turn_identity(
    *,
    session_id: str,
    version: int,
    channel: str,
    discriminator: str,
) -> TurnIdentity:
    digest = sha256(
        f"{session_id}\0{version}\0{channel}\0{discriminator}".encode()
    ).hexdigest()
    return TurnIdentity(
        session_id=session_id,
        request_id=f"request_{digest}",
        turn_id=f"turn_{digest}",
    )


def _turn(
    message: str,
    *,
    session_id: str = "cross-worker-session",
    version: int,
    profile_owner=None,
) -> UserTurn:
    return UserTurn(
        identity=_turn_identity(
            session_id=session_id,
            version=version,
            channel="text",
            discriminator=message,
        ),
        session_id=session_id,
        message=message,
        image_bundle_id=None,
        conversation_version=version,
        profile_owner=profile_owner,
    )


def _public_events(
    orchestrator,
    turn: UserTurn,
) -> list[tuple[str, dict]]:
    return _decode_frames(orchestrator.stream(turn))


def _decode_frames(frames) -> list[tuple[str, dict]]:
    events = []
    for frame in frames:
        event_line, data_line, _ = frame.split(b"\n", maxsplit=2)
        events.append(
            (
                event_line.removeprefix(b"event: ").decode("ascii"),
                json.loads(
                    data_line.removeprefix(b"data: ").decode("utf-8")
                ),
            )
        )
    return events


def _deliver(
    orchestrator,
    turn: UserTurn,
) -> list[tuple[str, dict]]:
    events = _public_events(orchestrator, turn)
    assert events[-1][0] in {"end", "error"}
    return events


def _deliver_image(
    unified,
    turn: UserTurn,
) -> list[tuple[str, dict]]:
    events = _decode_frames(unified.stream(turn))
    assert events[-1][0] in {"end", "error"}
    return events


def _terminal_version(events: list[tuple[str, dict]]) -> int:
    assert events[-1][0] == "end"
    return int(events[-1][1]["conversation_version"])


def _clarification(snapshot: ConversationSnapshot):
    return (
        snapshot.reply_slot.value
        if isinstance(snapshot.reply_slot, PendingClarificationSlot)
        else None
    )


def _sqlite_delegate(orchestrator) -> SqliteConversationState:
    state = orchestrator._conversation_state
    assert isinstance(state, SqliteConversationState)
    return state


def _process_text_turn(
    state_dir: str,
    message: str,
    version: int,
    results,
) -> None:
    try:
        orchestrator = build_unified_runtime(
            state_dir=state_dir,
        )
        events = _deliver(
            orchestrator,
            _turn(message, version=version),
        )
        products = next(
            (
                [
                    int(product["product_id"])
                    for product in data["products"]
                ]
                for event, data in events
                if event == "products"
            ),
            [],
        )
        results.put(
            (
                "ok",
                _terminal_version(events),
                products,
            )
        )
    except BaseException as error:
        results.put(
            (
                "error",
                type(error).__name__,
                str(error),
            )
        )


def _process_text_turn_from_environment(
    state_dir: str,
    cwd: str,
    message: str,
    version: int,
    results,
) -> None:
    try:
        os.chdir(cwd)
        os.environ["XIAORO_GUIDE_STATE_DIR"] = state_dir
        orchestrator = build_unified_runtime()
        events = _deliver(
            orchestrator,
            _turn(message, version=version),
        )
        products = next(
            (
                [
                    int(product["product_id"])
                    for product in data["products"]
                ]
                for event, data in events
                if event == "products"
            ),
            [],
        )
        results.put(
            (
                "ok",
                _terminal_version(events),
                products,
                str(_sqlite_delegate(orchestrator).database_path),
            )
        )
    except BaseException as error:
        results.put(
            (
                "error",
                type(error).__name__,
                str(error),
            )
        )


class _StoredVectorEncoder:
    def __init__(self, product_id: int) -> None:
        lock = guide_image_runtime_lock()
        self.model_lock = ApprovedImageModelLock(
            approval_id="guide-task7-cross-worker-image",
            model_name=lock.model_name,
            weights_sha256=lock.weights_sha256,
            preprocessing_version=lock.preprocessing_version,
            vector_dimension=lock.vector_dimension,
        )
        artifact_root = (
            REPO_ROOT
            / "data"
            / "guide_image_index"
            / "openclip_vit_b32_laion2b_s34b_b79k_v1"
        )
        manifest = json.loads(
            (artifact_root / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        product_ids = [
            int(entry["product_id"])
            for entry in manifest["entries"]
        ]
        matrix = np.load(
            artifact_root / "index.npy",
            allow_pickle=False,
        )
        self._vector = matrix[product_ids.index(product_id)]

    def encode_bytes(self, content: bytes) -> np.ndarray:
        assert content
        return self._vector.copy()


def _image_turn(
    service: ImageBundleService,
    *,
    session_id: str,
    version: int,
    profile_owner,
) -> UserTurn:
    source = (
        REPO_ROOT
        / "app"
        / "static"
        / "images"
        / "products"
        / "taobao_v3_572910260362.png"
    )
    receipt = service.create(
        session_id=session_id,
        images=[
            UntrustedImageInput(
                file_name=source.name,
                declared_media_type="image/png",
                content=source.read_bytes(),
            )
        ],
    )
    return UserTurn(
        identity=_turn_identity(
            session_id=session_id,
            version=version,
            channel="image",
            discriminator=receipt.bundle_id,
        ),
        session_id=session_id,
        message="150元以内找相似款",
        image_bundle_id=receipt.bundle_id,
        image_bundle_version=receipt.version,
        image_bundle_token=receipt.owner_token,
        conversation_version=version,
        profile_owner=profile_owner,
    )


def test_runtime_uses_trusted_conversation_database(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "trusted-state"

    orchestrator = build_unified_runtime(
        state_dir=state_root,
    )

    delegate = _sqlite_delegate(orchestrator)
    assert delegate.database_path == (
        state_root / "conversations.sqlite3"
    )
    assert delegate.database_path.parent.stat().st_mode & 0o777 == 0o700
    assert delegate.database_path.stat().st_mode & 0o777 == 0o600


def test_explicit_state_directory_precedes_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment_root = tmp_path / "environment-state"
    explicit_root = tmp_path / "explicit-state"
    monkeypatch.setenv(
        "XIAORO_GUIDE_STATE_DIR",
        str(environment_root),
    )
    assert conversation_database_path() == (
        environment_root / "conversations.sqlite3"
    )

    orchestrator = build_unified_runtime(
        state_dir=explicit_root,
    )

    assert _sqlite_delegate(orchestrator).database_path == (
        explicit_root / "conversations.sqlite3"
    )
    assert not environment_root.exists()


@pytest.mark.parametrize("configured", ["", "relative-state"])
def test_environment_state_directory_rejects_empty_or_relative_paths(
    configured: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XIAORO_GUIDE_STATE_DIR", configured)

    with pytest.raises(
        ValueError,
        match="XIAORO_GUIDE_STATE_DIR.*absolute",
    ):
        guide_state_directory()


@pytest.mark.parametrize(
    "factory",
    [
        build_consultation_vertical_runtime,
    ],
    ids=["consultation"],
)
@pytest.mark.parametrize(
    "invalid_state_dir",
    ["", Path(), Path("relative-state")],
    ids=["empty-string", "empty-path", "relative-path"],
)
def test_explicit_state_directory_rejects_invalid_paths_without_env_fallback(
    factory,
    invalid_state_dir: str | Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    working_directory = tmp_path / "worker-cwd"
    working_directory.mkdir()
    environment_root = tmp_path / "environment-state"
    monkeypatch.chdir(working_directory)
    monkeypatch.setenv(
        "XIAORO_GUIDE_STATE_DIR",
        str(environment_root),
    )

    with pytest.raises(ValueError, match="state_dir.*absolute"):
        factory(state_dir=invalid_state_dir)

    assert not environment_root.exists()


def test_worker_b_follows_worker_a_with_separate_orchestrators(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "shared-state"
    worker_a = build_unified_runtime(state_dir=state_root)
    worker_b = build_unified_runtime(state_dir=state_root)

    initial = _deliver(
        worker_a,
        _turn("500 元内敏感肌修护精华", version=0),
    )
    followup = _deliver(
        worker_b,
        _turn("第二款呢", version=1),
    )

    assert _terminal_version(initial) == 1
    assert _terminal_version(followup) == 2
    products = next(
        data["products"]
        for event, data in followup
        if event == "products"
    )
    assert [product["product_id"] for product in products] == [91]
    assert _sqlite_delegate(worker_b).load(
        "cross-worker-session"
    ).version == 2


def test_focus_state_survives_two_sqlite_workers_and_stale_cas(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "focus-worker-state"
    database = state_root / "conversations.sqlite3"
    worker_a = SqliteConversationState(
        database,
        trusted_state_root=state_root,
    )
    worker_b = SqliteConversationState(
        database,
        trusted_state_root=state_root,
    )
    initial = ConversationSnapshot(
        session_id="cross-worker-focus",
        version=1,
        active_owner=Responsibility.PRODUCT_KNOWLEDGE,
        active_focus=ActiveFocus(
            slot="product",
            object_id=55,
        ),
        recommendation_slot=RecommendationSlotState(
            query_context=RecommendationQueryContext(
                category="sunscreen",
                recommendation_mode_basis="broad_exploration",
                budget_minimum=None,
                budget_maximum=Decimal("500"),
                skin=None,
                efficacy=None,
                exclusions=(),
            ),
            candidates=(
                DisplayedCandidateRef(
                    product_id=51,
                    ordinal=1,
                    skin_match="unknown",
                    matched_efficacies=(),
                ),
                DisplayedCandidateRef(
                    product_id=55,
                    ordinal=2,
                    skin_match="unknown",
                    matched_efficacies=(),
                ),
            ),
            focused_candidate_ordinal=2,
        ),
        product_slot=ProductSlotState(
            products=(
                DisplayedCandidateRef(
                    product_id=55,
                    ordinal=1,
                    skin_match="unknown",
                    matched_efficacies=(),
                ),
            ),
            focused_product_id=55,
        ),
    )
    worker_a.save(initial, expected_version=0)
    loaded = worker_b.load(initial.session_id)
    assert loaded == initial
    switched = loaded.model_copy(
        update={
            "version": 2,
            "active_owner": Responsibility.GENERAL_KNOWLEDGE,
            "active_focus": ActiveFocus(slot="knowledge"),
            "knowledge_slot": KnowledgeSlotState(
                question="视黄醇是什么",
                evidence_ids=(),
            ),
        },
        deep=True,
    )

    worker_b.save(switched, expected_version=1)

    assert worker_a.load(initial.session_id) == switched
    with pytest.raises(ConversationStateConflict):
        worker_a.save(
            initial.model_copy(update={"version": 2}, deep=True),
            expected_version=1,
        )


def test_workers_with_different_cwds_share_environment_sqlite(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "environment-process-state"
    worker_a_cwd = tmp_path / "worker-a"
    worker_b_cwd = tmp_path / "worker-b"
    worker_a_cwd.mkdir()
    worker_b_cwd.mkdir()
    expected_database = str(state_root / "conversations.sqlite3")
    context = multiprocessing.get_context("spawn")
    results = context.Queue()

    worker_a = context.Process(
        target=_process_text_turn_from_environment,
        args=(
            str(state_root),
            str(worker_a_cwd),
            "500 元内敏感肌修护精华",
            0,
            results,
        ),
    )
    worker_a.start()
    first = results.get(timeout=30)
    worker_a.join(timeout=30)
    assert worker_a.exitcode == 0

    worker_b = context.Process(
        target=_process_text_turn_from_environment,
        args=(
            str(state_root),
            str(worker_b_cwd),
            "第二款呢",
            1,
            results,
        ),
    )
    worker_b.start()
    second = results.get(timeout=30)
    worker_b.join(timeout=30)
    assert worker_b.exitcode == 0

    assert first == ("ok", 1, [38, 91], expected_database)
    assert second == ("ok", 2, [91], expected_database)


def test_text_state_survives_two_real_worker_processes(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "process-state"
    context = multiprocessing.get_context("spawn")
    results = context.Queue()

    worker_a = context.Process(
        target=_process_text_turn,
        args=(
            str(state_root),
            "500 元内敏感肌修护精华",
            0,
            results,
        ),
    )
    worker_a.start()
    first = results.get(timeout=30)
    worker_a.join(timeout=30)
    assert worker_a.exitcode == 0

    worker_b = context.Process(
        target=_process_text_turn,
        args=(
            str(state_root),
            "第二款呢",
            1,
            results,
        ),
    )
    worker_b.start()
    second = results.get(timeout=30)
    worker_b.join(timeout=30)
    assert worker_b.exitcode == 0

    assert first == ("ok", 1, [38, 91])
    assert second == ("ok", 2, [91])
    restarted = build_unified_runtime(state_dir=state_root)
    assert _sqlite_delegate(restarted).load(
        "cross-worker-session"
    ).version == 2


def test_stale_worker_is_rejected_before_second_cas_save(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = tmp_path / "cas-state"
    initial_worker = build_unified_runtime(state_dir=state_root)
    _deliver(
        initial_worker,
        _turn("500 元内敏感肌修护精华", version=0),
    )
    worker_a = build_unified_runtime(state_dir=state_root)
    worker_b = build_unified_runtime(state_dir=state_root)
    save_calls: list[tuple[str, int]] = []
    real_save = SqliteConversationState.save

    def recording_save(self, snapshot, *, expected_version):
        save_calls.append((snapshot.session_id, expected_version))
        return real_save(
            self,
            snapshot,
            expected_version=expected_version,
        )

    monkeypatch.setattr(
        SqliteConversationState,
        "save",
        recording_save,
    )
    staged_a = _public_events(
        worker_a,
        _turn("预算降到100元呢", version=1),
    )
    stale = _public_events(
        worker_b,
        _turn("预算降到200元呢", version=1),
    )

    assert staged_a[-1][0] == "end"
    assert stale[-1] == (
        "error",
        {
            "error": "GUIDE_INTERNAL_ERROR",
            "message": "推荐暂时不可用，请稍后重试。",
        },
    )
    stored = _sqlite_delegate(worker_a).load(
        "cross-worker-session"
    )
    assert stored is not None
    assert stored.version == 2
    assert str(
        stored.recommendation_slot.query_context.budget_maximum
    ) == "100"
    assert save_calls == [("cross-worker-session", 1)]


def test_stale_and_error_keep_state_while_zero_result_commits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = tmp_path / "non-mutating-state"
    first = build_unified_runtime(state_dir=state_root)
    _deliver(
        first,
        _turn("500 元内敏感肌修护精华", version=0),
    )
    state = _sqlite_delegate(first)
    before = state.load("cross-worker-session")
    assert before is not None

    stale = _deliver(
        build_unified_runtime(state_dir=state_root),
        _turn("预算降到100元呢", version=0),
    )
    assert stale[-1][0] == "error"
    assert state.load("cross-worker-session") == before

    zero = _deliver(
        build_unified_runtime(state_dir=state_root),
        _turn("预算降到50元呢", version=1),
    )
    zero_products = next(
        data["products"]
        for event, data in zero
        if event == "products"
    )
    assert zero_products == []
    after_zero = state.load("cross-worker-session")
    assert after_zero is not None
    assert after_zero.version == 2
    assert after_zero.recommendation_slot.empty_result is True

    def broken_retrieval(*args, **kwargs):
        raise RuntimeError("task7 injected retrieval failure")

    monkeypatch.setattr(
        (
            "app.guide.application.text_recommendation_flow."
            "retrieve_candidates"
        ),
        broken_retrieval,
    )
    failed = _deliver(
        build_unified_runtime(state_dir=state_root),
        _turn("预算降到100元呢", version=2),
    )
    assert failed[-1][0] == "error"
    assert state.load("cross-worker-session") == after_zero


def test_cross_worker_clarification_progress_is_bounded_and_success_clears_it(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "clarification-state"
    worker_a = build_consultation_vertical_runtime(
        state_dir=state_root
    ).unified
    worker_b = build_consultation_vertical_runtime(
        state_dir=state_root
    ).unified

    first = _deliver(worker_a, _turn("帮我看看", version=0))
    first_state = _sqlite_delegate(worker_b).load("cross-worker-session")
    second = _deliver(worker_b, _turn("帮我看看", version=1))
    second_state = _sqlite_delegate(worker_a).load("cross-worker-session")
    third = _deliver(worker_a, _turn("帮我看看", version=2))
    third_state = _sqlite_delegate(worker_b).load("cross-worker-session")

    clarifications = [
        next(
            data
            for event, data in events
            if event == "clarify"
        )
        for events in (first, second, third)
    ]
    assert len({
        item["question"]
        for item in clarifications
    }) == 1
    assert {
        item["clarification_code"]
        for item in clarifications
    } == {ClarificationCode.GOAL.value}
    assert [_terminal_version(events) for events in (first, second, third)] == [
        1,
        2,
        3,
    ]
    assert first_state is not None
    assert _clarification(first_state).attempts == 1
    assert second_state is not None
    assert _clarification(second_state).attempts == 2
    assert third_state is not None
    assert _clarification(third_state).gap is ClarificationCode.GOAL
    assert _clarification(third_state).attempts == 2
    assert third_state.recommendation_slot is None

    changed_gap = _deliver(
        worker_b,
        _turn("0 元以内的防晒", version=3),
    )
    changed = _sqlite_delegate(worker_a).load("cross-worker-session")

    changed_clarification = next(
        data
        for event, data in changed_gap
        if event == "clarify"
    )
    assert changed_clarification["question"]
    assert (
        changed_clarification["clarification_code"]
        == ClarificationCode.BUDGET.value
    )
    assert _terminal_version(changed_gap) == 4
    assert changed is not None
    assert _clarification(changed).gap is ClarificationCode.BUDGET
    assert _clarification(changed).attempts == 1

    successful = _deliver(
        worker_b,
        _turn("500 元内敏感肌修护精华", version=4),
    )
    saved = _sqlite_delegate(worker_a).load("cross-worker-session")

    assert _terminal_version(successful) == 5
    assert saved is not None
    assert _clarification(saved) is None
    assert saved.recommendation_slot.candidates


def test_clarification_state_commits_before_transport_disconnect(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "discard-state"
    orchestrator = build_consultation_vertical_runtime(
        state_dir=state_root
    ).unified
    state = _sqlite_delegate(orchestrator)

    clarify = _deliver(
        orchestrator,
        _turn("帮我看看", version=0),
    )
    assert any(
        event == "clarify"
        for event, data in clarify
    )
    before = state.load("cross-worker-session")
    assert before is not None
    assert _clarification(before).gap is ClarificationCode.GOAL
    assert _clarification(before).attempts == 1

    interrupted_turn = _turn("帮我看看", version=1)
    interrupted = orchestrator.stream(interrupted_turn)
    assert next(interrupted).startswith(b"event: start\n")
    assert not next(interrupted).startswith(b"event: end\n")
    interrupted.close()

    committed = state.load("cross-worker-session")
    assert committed is not None
    assert committed.version == before.version + 1
    assert _clarification(committed) is not None


@pytest.mark.parametrize("first_owner", ["text", "image"])
def test_text_and_image_share_one_authoritative_sqlite_version_chain(
    tmp_path: Path,
    first_owner: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = tmp_path / f"{first_owner}-image-state"
    session_id = f"cross-{first_owner}-image-session"
    image_bundles = ImageBundleService(
        state=InMemoryImageBundleState(max_bundles=2)
    )
    monkeypatch.setattr(
        composition,
        "_build_runtime_image_encoder",
        lambda **_: _StoredVectorEncoder(53),
    )
    consultation = build_consultation_vertical_runtime(
        state_dir=state_root,
        image_bundle_service=image_bundles,
    )
    profile_owner = consultation.profile_owner(session_id)
    text = consultation.unified
    image_turn = _image_turn(
        image_bundles,
        session_id=session_id,
        version=0 if first_owner == "image" else 1,
        profile_owner=profile_owner,
    )
    text_turn = _turn(
        "100元内防晒",
        session_id=session_id,
        version=0 if first_owner == "text" else 1,
        profile_owner=profile_owner,
    )

    first, second = (
        (
            _deliver(text, text_turn),
            _deliver_image(
                consultation.unified,
                image_turn,
            ),
        )
        if first_owner == "text"
        else (
            _deliver_image(
                consultation.unified,
                image_turn,
            ),
            _deliver(text, text_turn),
        )
    )

    assert [
        _terminal_version(first),
        _terminal_version(second),
    ] == [1, 2]
    assert _sqlite_delegate(text).database_path == (
        consultation.conversation_state.database_path
    )
    stored = consultation.conversation_state.load(session_id)
    assert stored is not None
    assert stored.version == 2
    assert stored.recommendation_slot is not None
    assert stored.image_slot is not None


def test_runtime_sqlite_io_stays_in_threadpool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_root = tmp_path / "threadpool-state"
    io_threads: list[int] = []
    real_load = SqliteConversationState.load
    real_save = SqliteConversationState.save

    def recording_load(self, session_id):
        io_threads.append(get_ident())
        return real_load(self, session_id)

    def recording_save(self, snapshot, *, expected_version):
        io_threads.append(get_ident())
        return real_save(
            self,
            snapshot,
            expected_version=expected_version,
        )

    monkeypatch.setattr(
        SqliteConversationState,
        "load",
        recording_load,
    )
    monkeypatch.setattr(
        SqliteConversationState,
        "save",
        recording_save,
    )
    orchestrator = build_unified_runtime(state_dir=state_root)

    async def exercise() -> int:
        event_loop_thread = get_ident()
        events = [
            event
            async for event in iterate_http_events_in_threadpool(
                orchestrator.stream(
                    _turn(
                        "500 元内敏感肌修护精华",
                        session_id="threadpool-session",
                        version=0,
                    )
                )
            )
        ]
        return event_loop_thread

    loop_thread = asyncio.run(exercise())

    assert len(io_threads) >= 2
    assert loop_thread not in io_threads


def test_no_second_conversation_authority_is_created(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "single-authority-state"
    text = build_unified_runtime(state_dir=state_root)
    consultation = build_consultation_vertical_runtime(
        state_dir=state_root,
    )

    assert _sqlite_delegate(text).database_path == (
        consultation.conversation_state.database_path
    )
    with sqlite3.connect(
        consultation.conversation_state.database_path
    ) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type = 'table'"
            )
        }
    assert tables == {
        "conversations",
        "conversation_tombstones",
    }
