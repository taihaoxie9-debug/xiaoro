from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier, Event
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.guide.adapters.state import InMemoryConversationState
from app.guide.adapters.state.sqlite_profile_state import SqliteProfileState
from app.guide.application.consultation_assessment import assess_consultation
from app.guide.application.consultation_confirmation import (
    confirm_provisional_conclusion,
    record_provisional_conclusion,
)
from app.guide.feedback.consultation_state import ConsultationSubstate
from app.guide.feedback.contracts import ConversationSnapshot
from app.guide.feedback.profile_contracts import (
    ConfirmedProfileFact,
    ProfileOwnerRef,
)
from app.guide.understanding.consultation_contracts import (
    ConsultationObservation,
)
from app.guide.understanding.consultation_questions import (
    observable_questions,
)


_OWNER = ProfileOwnerRef(
    scope="local_demo",
    subject_id="profile_0123456789abcdef",
)
_OTHER_OWNER = ProfileOwnerRef(
    scope="authenticated_user",
    subject_id="profile_fedcba9876543210",
)
_SESSION_ID = "consultation-authority-session"
_CONFIRMED_AT = datetime(2026, 8, 9, 4, 0, tzinfo=UTC)


def _consultation_sequence(
    *,
    owner: ProfileOwnerRef | None = _OWNER,
    session_id: str = _SESSION_ID,
) -> tuple[ConversationSnapshot, ...]:
    observations: list[ConsultationObservation] = []
    snapshots: list[ConversationSnapshot] = [
        ConversationSnapshot(
            session_id=session_id,
            version=1,
            profile_owner=owner,
            consultation=ConsultationSubstate(
                started_at_conversation_version=1,
                observations=[],
            ),
        )
    ]
    for index, (question, answer) in enumerate(
        zip(
            observable_questions(),
            ("yes", "no", "no", "no", "no"),
            strict=True,
        ),
        start=2,
    ):
        observations.append(
            ConsultationObservation(
                code=question.code,
                answer=answer,
                source_turn_id=f"turn_observation_{index:04d}",
            )
        )
        snapshots.append(
            ConversationSnapshot(
                session_id=session_id,
                version=index,
                profile_owner=owner,
                consultation=ConsultationSubstate(
                    started_at_conversation_version=1,
                    observations=tuple(observations),
                ),
            )
        )
    collecting = snapshots[-1].consultation
    assert collecting is not None
    collection_version = snapshots[-1].version
    assessment = assess_consultation(
        collecting,
        current_conversation_version=collection_version,
        conclusion_source_turn_id="turn_assessment_000001",
    )
    provisional = record_provisional_conclusion(
        collecting,
        current_conversation_version=collection_version,
        assessment=assessment.confirmable_assessment,
    )
    confirmed = confirm_provisional_conclusion(
        provisional.next_consultation,
        current_conversation_version=provisional.output.conversation_version,
        message="我确认是干性肤质",
        source_turn_id="turn_confirm_00000001",
        expected_skin_target="dry",
        expected_conclusion_source_turn_id="turn_assessment_000001",
    )
    snapshots.extend(
        (
        ConversationSnapshot(
            session_id=session_id,
            version=provisional.output.conversation_version,
            profile_owner=owner,
            consultation=provisional.next_consultation,
        ),
        ConversationSnapshot(
            session_id=session_id,
            version=confirmed.output.conversation_version,
            profile_owner=owner,
            consultation=confirmed.next_consultation,
        ),
        )
    )
    return tuple(snapshots)


def _conversation_state(
    *,
    owner: ProfileOwnerRef | None = _OWNER,
) -> tuple[InMemoryConversationState, ConversationSnapshot]:
    state = InMemoryConversationState()
    snapshots = _consultation_sequence(owner=owner)
    for expected_version, snapshot in enumerate(snapshots):
        state.save(snapshot, expected_version=expected_version)
    authoritative = state.load(_SESSION_ID)
    assert authoritative == snapshots[-1]
    return state, authoritative


def _profile_state(tmp_path: Path) -> SqliteProfileState:
    state_root = tmp_path / "state"
    return SqliteProfileState(
        state_root / "profiles.sqlite3",
        trusted_state_root=state_root,
    )


def _persist(
    tmp_path: Path,
    conversation_state: InMemoryConversationState,
    snapshot: object,
):
    from app.guide.feedback.profile_policy import (
        persist_confirmed_consultation_profile,
    )

    return persist_confirmed_consultation_profile(
        _profile_state(tmp_path),
        conversation_state,
        snapshot,
        expected_version=0,
        confirmed_at=_CONFIRMED_AT,
    )


def test_exact_stored_confirmed_snapshot_creates_durable_skin_fact(
    tmp_path: Path,
) -> None:
    conversation_state, snapshot = _conversation_state()
    profile_state = _profile_state(tmp_path)
    from app.guide.feedback.profile_policy import (
        persist_confirmed_consultation_profile,
    )

    result = persist_confirmed_consultation_profile(
        profile_state,
        conversation_state,
        snapshot,
        expected_version=0,
        confirmed_at=_CONFIRMED_AT,
    )

    assert result.outcome == "created"
    assert result.value == "dry"
    stored = profile_state.load(_OWNER)
    assert stored is not None
    assert stored.facts[0].source_kind == "confirmed_consultation"
    assert stored.facts[0].source_turn_id == "turn_confirm_00000001"
    assert stored.facts[0].confirmed_at == _CONFIRMED_AT


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("profile_owner", _OTHER_OWNER),
        ("session_id", "different-consultation-session"),
        ("version", 2),
    ],
)
def test_snapshot_owner_session_and_version_must_match_stored_authority(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    conversation_state, snapshot = _conversation_state()
    mismatched = snapshot.model_copy(update={field: value}, deep=True)

    with pytest.raises(
        RuntimeError,
        match="mismatched_snapshot_authority",
    ):
        _persist(tmp_path, conversation_state, mismatched)


def test_mutated_consultation_copy_cannot_replace_stored_authority(
    tmp_path: Path,
) -> None:
    conversation_state, snapshot = _conversation_state()
    assert snapshot.consultation is not None
    forged_consultation = snapshot.consultation.model_copy(
        update={"confirmation_source_turn_id": "turn_forged_00000001"},
        deep=True,
    )
    forged = snapshot.model_copy(
        update={"consultation": forged_consultation},
        deep=True,
    )

    with pytest.raises(
        RuntimeError,
        match="mismatched_snapshot_authority",
    ):
        _persist(tmp_path, conversation_state, forged)


@pytest.mark.parametrize(
    "forged",
    [
        {"session_id": _SESSION_ID, "version": 3},
        SimpleNamespace(
            session_id=_SESSION_ID,
            version=3,
            profile_owner=_OWNER,
        ),
    ],
)
def test_request_dictionaries_and_snapshot_lookalikes_are_rejected(
    tmp_path: Path,
    forged: object,
) -> None:
    conversation_state, _ = _conversation_state()

    with pytest.raises(TypeError, match="ConversationSnapshot"):
        _persist(tmp_path, conversation_state, forged)


def test_anonymous_confirmed_snapshot_cannot_persist_profile(
    tmp_path: Path,
) -> None:
    conversation_state, snapshot = _conversation_state(owner=None)

    with pytest.raises(RuntimeError, match="anonymous_snapshot"):
        _persist(tmp_path, conversation_state, snapshot)


def test_authoritative_state_rejects_wrong_confirmation_version(
) -> None:
    sequence = _consultation_sequence()
    conversation_state = InMemoryConversationState()
    for expected_version, snapshot in enumerate(sequence[:-1]):
        conversation_state.save(
            snapshot,
            expected_version=expected_version,
        )
    provisional = sequence[-2]
    invalid = sequence[-1].model_copy(
        update={"version": provisional.version + 2},
        deep=True,
    )

    with pytest.raises(ValueError, match="increment by one"):
        conversation_state.save(
            invalid,
            expected_version=provisional.version,
        )

    assert conversation_state.load(_SESSION_ID) == provisional


def test_snapshot_authority_components_are_deeply_immutable() -> None:
    _, snapshot = _conversation_state()
    assert snapshot.consultation is not None
    assert snapshot.profile_owner is not None

    with pytest.raises(ValidationError, match="frozen"):
        snapshot.profile_owner.subject_id = "profile_changed_0123456789"
    with pytest.raises(ValidationError, match="frozen"):
        snapshot.consultation.observations[0].answer = "no"


def test_concurrent_same_snapshot_reports_one_create_and_one_idempotent(
    tmp_path: Path,
) -> None:
    from app.guide.feedback.profile_policy import (
        persist_confirmed_consultation_profile,
    )

    conversation_state, snapshot = _conversation_state()
    profile_state = _profile_state(tmp_path)
    barrier = Barrier(2)

    def persist() -> str:
        barrier.wait()
        return persist_confirmed_consultation_profile(
            profile_state,
            conversation_state,
            snapshot,
            expected_version=0,
            confirmed_at=_CONFIRMED_AT,
        ).outcome

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: persist(), range(2)))

    assert sorted(outcomes) == ["created", "idempotent"]


def test_conflicting_existing_skin_value_is_preserved(
    tmp_path: Path,
) -> None:
    from app.guide.feedback.profile_policy import (
        persist_confirmed_consultation_profile,
    )

    conversation_state, snapshot = _conversation_state()
    profile_state = _profile_state(tmp_path)
    original = ConfirmedProfileFact(
        owner=_OWNER,
        field="skin_type",
        value="sensitive",
        source_turn_id="turn_original_00000001",
        source_kind="explicit_user",
        confirmed_at=datetime(2026, 8, 9, 3, 0, tzinfo=UTC),
        profile_version=1,
    )
    before = profile_state.save(original, expected_version=0)

    result = persist_confirmed_consultation_profile(
        profile_state,
        conversation_state,
        snapshot,
        expected_version=1,
        confirmed_at=_CONFIRMED_AT,
    )

    assert result.outcome == "preserved_existing"
    assert result.disposition == "conflict"
    assert result.value == "sensitive"
    assert result.requested_value == "dry"
    assert profile_state.load(_OWNER) == before


@pytest.mark.parametrize("mutation", ["downgrade", "rewrite"])
def test_concurrent_confirmation_rewrite_is_rejected_without_invalidating_write(
    tmp_path: Path,
    mutation: str,
) -> None:
    from app.guide.feedback.profile_policy import (
        persist_confirmed_consultation_profile,
    )

    conversation_state, snapshot = _conversation_state()
    profile_state = _profile_state(tmp_path)
    write_entered = Event()
    allow_write = Event()

    class PausingProfileState:
        def write_once(
            self,
            fact: ConfirmedProfileFact,
            *,
            expected_version: int,
        ):
            write_entered.set()
            assert allow_write.wait(timeout=5)
            return profile_state.write_once(
                fact,
                expected_version=expected_version,
            )

    assert snapshot.consultation is not None
    assessment = snapshot.consultation.confirmable_assessment
    assert assessment is not None
    if mutation == "downgrade":
        conclusion = assessment.conclusion.model_copy(
            update={"confirmed_by_user": False},
            deep=True,
        )
        rewritten_assessment = assessment.model_copy(
            update={"conclusion": conclusion},
            deep=True,
        )
        rewritten_consultation = ConsultationSubstate(
            observations=snapshot.consultation.observations,
            confirmable_assessment=rewritten_assessment,
        )
    else:
        rewritten_consultation = snapshot.consultation.model_copy(
            update={
                "confirmation_source_turn_id": "turn_rewrite_00000001",
            },
            deep=True,
        )
    attempted_rewrite = snapshot.model_copy(
        update={
            "version": snapshot.version + 1,
            "consultation": rewritten_consultation,
        },
        deep=True,
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(
            persist_confirmed_consultation_profile,
            PausingProfileState(),
            conversation_state,
            snapshot,
            expected_version=0,
            confirmed_at=_CONFIRMED_AT,
        )
        assert write_entered.wait(timeout=5)
        with pytest.raises(ValueError, match="confirmation is immutable"):
            conversation_state.save(
                attempted_rewrite,
                expected_version=snapshot.version,
            )
        allow_write.set()
        result = pending.result(timeout=5)

    assert result.outcome == "created"
    assert conversation_state.load(snapshot.session_id) == snapshot
    stored = profile_state.load(_OWNER)
    assert stored is not None
    assert stored.version == 1
    assert stored.facts == (
        ConfirmedProfileFact(
            owner=_OWNER,
            field="skin_type",
            value="dry",
            source_turn_id="turn_confirm_00000001",
            source_kind="confirmed_consultation",
            confirmed_at=_CONFIRMED_AT,
            profile_version=1,
        ),
    )


def test_policy_exposes_no_sealed_or_explicit_user_persistence_path() -> None:
    import app.guide.feedback.profile_policy as policy

    forbidden_names = {
        "ConfirmedConsultationConclusionProof",
        "ExplicitSkinTargetProof",
        "derive_confirmed_consultation_proof",
        "derive_explicit_skin_target_proof",
        "persist_profile_proof",
    }

    assert forbidden_names.isdisjoint(vars(policy))
    source = Path(policy.__file__).read_text(encoding="utf-8")
    assert "_PROOF_SEAL" not in source
    assert "object.__setattr__" not in source
