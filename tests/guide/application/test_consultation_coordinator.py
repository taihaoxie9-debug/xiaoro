from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

import pytest
from pydantic import ValidationError

from app.guide.adapters.state import InMemoryConversationState
from app.guide.adapters.state.sqlite_profile_state import (
    SqliteProfileState,
)
from app.guide.feedback.ports import ConversationStateConflict
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.feedback.profile_state import ProfileStateCorrupt
from app.guide.understanding.contracts import SkinTarget


_OWNER = ProfileOwnerRef(
    scope="anonymous_browser",
    subject_id="browser_consultation_0123456789",
)
_CONFIRMED_AT = datetime(2026, 8, 9, 8, 0, tzinfo=UTC)


def _build(tmp_path: Path):
    from app.guide.application.consultation_coordinator import (
        ConsultationApplicationCoordinator,
    )

    conversation_state = InMemoryConversationState()
    state_root = tmp_path / "state"
    profile_state = SqliteProfileState(
        state_root / "profiles.sqlite3",
        trusted_state_root=state_root,
    )
    coordinator = ConsultationApplicationCoordinator(
        conversation_state=conversation_state,
        profile_state=profile_state,
        long_term_profile_opt_in=True,
    )
    return coordinator, conversation_state, profile_state


def _turn_id(index: int) -> str:
    return f"turn_consultation_{index:04d}"


def _enter(coordinator):
    return coordinator.handle_turn(
        session_id="consultation-coordinator",
        conversation_version=0,
        message="我不知道自己是什么肤质",
        source_turn_id=_turn_id(0),
        profile_owner=_OWNER,
    )


def _advance_to_provisional(coordinator):
    output = _enter(coordinator)
    assert output is not None
    for index, answer in enumerate(
        ("会", "不会", "不会", "不会", "不会"),
        start=1,
    ):
        output = coordinator.handle_turn(
            session_id="consultation-coordinator",
            conversation_version=output.conversation_version,
            message=answer,
            source_turn_id=_turn_id(index),
            profile_owner=_OWNER,
        )
        assert output is not None
        if index < 5:
            assert output.intent == "consultation_answer"
        else:
            assert output.intent == "consultation_provisional"
    return output


def _zero_card_payload(output) -> dict[str, object]:
    return output.card_display_contract.model_dump(mode="json")


def _medical_transition(snapshot, *, source_turn_id: str):
    from app.guide.application.consultation_assessment import (
        assess_consultation,
    )
    from app.guide.application.consultation_confirmation import (
        record_medical_escalation,
    )
    from app.guide.understanding.consultation_escalation import (
        ConsultationEscalationInput,
        ConsultationEscalationTrigger,
    )

    consultation = snapshot.consultation
    assert consultation is not None
    assessment = assess_consultation(
        consultation,
        current_conversation_version=snapshot.version,
        conclusion_source_turn_id=source_turn_id,
        escalation=ConsultationEscalationInput(
            triggers=[
                ConsultationEscalationTrigger(
                    code="pain",
                    source_turn_id=source_turn_id,
                )
            ]
        ),
    )
    return record_medical_escalation(
        consultation,
        current_conversation_version=snapshot.version,
        assessment=assessment.confirmable_assessment,
    )


def test_entry_persists_before_question_and_is_exactly_zero_card(
    tmp_path: Path,
) -> None:
    coordinator, conversation_state, _ = _build(tmp_path)

    output = _enter(coordinator)

    assert output is not None
    assert output.intent == "consultation_entry"
    assert output.conversation_version == 1
    assert output.next_question is not None
    assert output.next_question.code == "post_cleanse_tightness"
    assert output.observations == ()
    assert output.conclusion is None
    assert output.profile_persistence is None
    assert _zero_card_payload(output) == {
        "mode": "none",
        "visible_product_ids": [],
        "max_cards": 0,
        "reason": None,
    }
    stored = conversation_state.load("consultation-coordinator")
    assert stored is not None
    assert stored.profile_owner == _OWNER
    assert stored.consultation is not None
    assert stored.consultation.started_at_conversation_version == 1
    assert stored.consultation.observations == ()


def test_five_answers_persist_provisional_evidence_and_uncertainty(
    tmp_path: Path,
) -> None:
    coordinator, conversation_state, profile_state = _build(tmp_path)

    output = _advance_to_provisional(coordinator)

    assert output.conversation_version == 7
    assert output.next_question is None
    assert len(output.observations) == 5
    assert output.conclusion is not None
    assert output.conclusion.skin_target == "dry"
    assert output.conclusion.evidence == ("post_cleanse_tightness",)
    assert output.conclusion.uncertainties == ()
    assert output.conclusion.confidence == "medium"
    assert output.conclusion.confirmed_by_user is False
    assert output.stop_skincare_advice is False
    assert output.profile_persistence is None
    assert _zero_card_payload(output)["visible_product_ids"] == []
    stored = conversation_state.load("consultation-coordinator")
    assert stored is not None
    assert stored.version == 7
    assert stored.consultation is not None
    assessment = stored.consultation.confirmable_assessment
    assert assessment is not None
    assert assessment.assessment_kind == "provisional"
    assert assessment.observation_set_version == 6
    assert profile_state.load(_OWNER) is None


def test_ambiguous_active_answer_is_read_only_clarification(
    tmp_path: Path,
) -> None:
    coordinator, conversation_state, profile_state = _build(tmp_path)
    entered = _enter(coordinator)
    assert entered is not None
    before = conversation_state.load("consultation-coordinator")

    output = coordinator.handle_turn(
        session_id="consultation-coordinator",
        conversation_version=entered.conversation_version,
        message="好像会，但不确定",
        source_turn_id=_turn_id(1),
        profile_owner=_OWNER,
    )

    assert output is not None
    assert output.intent == "consultation_clarification"
    assert output.reason == "answer_required"
    assert output.conversation_version == 1
    assert conversation_state.load("consultation-coordinator") == before
    assert profile_state.load(_OWNER) is None
    assert _zero_card_payload(output)["max_cards"] == 0


@pytest.mark.parametrize(
    "message",
    ["是还是不是", "会还是不会"],
)
def test_alternative_active_answer_appends_nothing(
    tmp_path: Path,
    message: str,
) -> None:
    coordinator, conversation_state, profile_state = _build(tmp_path)
    entered = _enter(coordinator)
    assert entered is not None
    before = conversation_state.load("consultation-coordinator")

    output = coordinator.handle_turn(
        session_id="consultation-coordinator",
        conversation_version=entered.conversation_version,
        message=message,
        source_turn_id=_turn_id(1),
        profile_owner=_OWNER,
    )

    assert output is not None
    assert output.intent == "consultation_clarification"
    assert output.reason == "answer_required"
    assert output.conversation_version == 1
    assert conversation_state.load("consultation-coordinator") == before
    assert profile_state.load(_OWNER) is None
    assert _zero_card_payload(output)["max_cards"] == 0


@pytest.mark.parametrize(
    ("message", "intent", "reason"),
    [
        ("不确认", "consultation_rejection", "rejected_by_user"),
        (
            "可能吧",
            "consultation_clarification",
            "confirmation_required",
        ),
    ],
)
def test_reject_or_ambiguous_confirmation_never_writes_profile(
    tmp_path: Path,
    message: str,
    intent: str,
    reason: str,
) -> None:
    coordinator, conversation_state, profile_state = _build(tmp_path)
    provisional = _advance_to_provisional(coordinator)
    before = conversation_state.load("consultation-coordinator")

    output = coordinator.handle_turn(
        session_id="consultation-coordinator",
        conversation_version=provisional.conversation_version,
        message=message,
        source_turn_id=_turn_id(6),
        profile_owner=_OWNER,
    )

    assert output is not None
    assert output.intent == intent
    assert output.reason == reason
    assert output.profile_persistence is None
    assert conversation_state.load("consultation-coordinator") == before
    assert profile_state.load(_OWNER) is None
    assert _zero_card_payload(output)["mode"] == "none"


def test_confirmation_saves_conversation_before_fill_only_profile(
    tmp_path: Path,
) -> None:
    from app.guide.application.consultation_coordinator import (
        ConsultationApplicationCoordinator,
    )

    conversation_state = InMemoryConversationState()
    state_root = tmp_path / "state"
    durable_profile = SqliteProfileState(
        state_root / "profiles.sqlite3",
        trusted_state_root=state_root,
    )
    observed_confirmed_state: list[bool] = []

    class OrderCheckingProfileState:
        def load(self, owner):
            return durable_profile.load(owner)

        def write_once(self, fact, *, expected_version):
            snapshot = conversation_state.load(
                "consultation-coordinator"
            )
            observed_confirmed_state.append(
                bool(
                    snapshot
                    and snapshot.consultation
                    and snapshot.consultation.confirmable_assessment
                    and snapshot.consultation.confirmable_assessment
                    .conclusion.confirmed_by_user
                )
            )
            return durable_profile.write_once(
                fact,
                expected_version=expected_version,
            )

        def save(self, fact, *, expected_version):
            return durable_profile.save(
                fact,
                expected_version=expected_version,
            )

    coordinator = ConsultationApplicationCoordinator(
        conversation_state=conversation_state,
        profile_state=OrderCheckingProfileState(),
        long_term_profile_opt_in=True,
    )
    provisional = _advance_to_provisional(coordinator)

    output = coordinator.handle_turn(
        session_id="consultation-coordinator",
        conversation_version=provisional.conversation_version,
        message="我确认是干皮",
        source_turn_id=_turn_id(6),
        profile_owner=_OWNER,
        confirmed_at=_CONFIRMED_AT,
    )

    assert output is not None
    assert output.intent == "consultation_confirmation"
    assert output.conversation_version == 8
    assert output.conclusion is not None
    assert output.conclusion.confirmed_by_user is True
    assert output.profile_persistence is not None
    assert output.profile_persistence.outcome == "created"
    assert observed_confirmed_state == [True]
    stored = conversation_state.load("consultation-coordinator")
    assert stored is not None
    assert stored.version == 8
    assert stored.consultation is not None
    assert stored.consultation.confirmation_source_turn_id == _turn_id(6)
    profile = durable_profile.load(_OWNER)
    assert profile is not None
    assert profile.version == 1
    assert profile.facts[0].field == "skin_type"
    assert profile.facts[0].value == "dry"
    assert profile.facts[0].source_turn_id == _turn_id(6)
    assert profile.facts[0].confirmed_at == _CONFIRMED_AT


def test_default_confirmation_updates_session_profile_only(
    tmp_path: Path,
) -> None:
    from app.guide.application.consultation_coordinator import (
        ConsultationApplicationCoordinator,
    )

    conversation_state = InMemoryConversationState()
    state_root = tmp_path / "session-only"
    durable_profile = SqliteProfileState(
        state_root / "profiles.sqlite3",
        trusted_state_root=state_root,
    )
    coordinator = ConsultationApplicationCoordinator(
        conversation_state=conversation_state,
        profile_state=durable_profile,
    )
    provisional = _advance_to_provisional(coordinator)

    output = coordinator.handle_turn(
        session_id="consultation-coordinator",
        conversation_version=provisional.conversation_version,
        message="我确认是干皮",
        source_turn_id=_turn_id(6),
        profile_owner=_OWNER,
        confirmed_at=_CONFIRMED_AT,
    )

    assert output is not None
    assert output.intent == "consultation_confirmation"
    assert output.profile_persistence is None
    assert output.session_profile is not None
    assert output.session_profile.base_skin is not None
    assert output.session_profile.base_skin.value == "dry"
    assert output.session_profile.base_skin.confirmation == "confirmed"
    stored = conversation_state.load("consultation-coordinator")
    assert stored is not None
    assert stored.session_profile == output.session_profile
    assert durable_profile.load(_OWNER) is None


def test_default_profile_resolution_does_not_inherit_another_session(
    tmp_path: Path,
) -> None:
    from app.guide.application.consultation_coordinator import (
        ConsultationApplicationCoordinator,
    )
    from app.guide.feedback.profile_contracts import ConfirmedProfileFact

    conversation_state = InMemoryConversationState()
    state_root = tmp_path / "no-inheritance"
    durable_profile = SqliteProfileState(
        state_root / "profiles.sqlite3",
        trusted_state_root=state_root,
    )
    durable_profile.save(
        ConfirmedProfileFact(
            owner=_OWNER,
            field="skin_type",
            value="sensitive",
            source_turn_id="turn_other_session_profile_0001",
            source_kind="explicit_user",
            confirmed_at=_CONFIRMED_AT,
            profile_version=1,
        ),
        expected_version=0,
    )
    coordinator = ConsultationApplicationCoordinator(
        conversation_state=conversation_state,
        profile_state=durable_profile,
    )

    resolved = coordinator.resolve_turn_profile(
        session_id="brand-new-session",
        profile_owner=_OWNER,
    )

    assert resolved.values == ()


def test_transient_profile_failure_returns_retry_required_and_reconciles(
    tmp_path: Path,
) -> None:
    from app.guide.application.consultation_coordinator import (
        ConsultationApplicationCoordinator,
    )

    conversation_state = InMemoryConversationState()
    state_root = tmp_path / "state"
    durable_profile = SqliteProfileState(
        state_root / "profiles.sqlite3",
        trusted_state_root=state_root,
    )

    class TransientOnceProfileState:
        unavailable = True

        def load(self, owner):
            return durable_profile.load(owner)

        def write_once(self, fact, *, expected_version):
            if self.unavailable:
                self.unavailable = False
                raise OSError("profile store temporarily unavailable")
            return durable_profile.write_once(
                fact,
                expected_version=expected_version,
            )

        def save(self, fact, *, expected_version):
            return durable_profile.save(
                fact,
                expected_version=expected_version,
            )

    coordinator = ConsultationApplicationCoordinator(
        conversation_state=conversation_state,
        profile_state=TransientOnceProfileState(),
        long_term_profile_opt_in=True,
    )
    provisional = _advance_to_provisional(coordinator)

    failed = coordinator.handle_turn(
        session_id="consultation-coordinator",
        conversation_version=provisional.conversation_version,
        message="我确认是干皮",
        source_turn_id=_turn_id(6),
        profile_owner=_OWNER,
        confirmed_at=_CONFIRMED_AT,
    )

    assert failed is not None
    assert failed.intent == "consultation_confirmation"
    assert failed.conversation_version == 8
    assert failed.conclusion is not None
    assert failed.conclusion.confirmed_by_user is True
    assert failed.profile_persistence is not None
    assert failed.profile_persistence.outcome == "retry_required"
    assert failed.profile_persistence.reason == "store_unavailable"
    assert _zero_card_payload(failed)["max_cards"] == 0
    confirmed = conversation_state.load("consultation-coordinator")
    assert confirmed is not None
    assert confirmed.version == 8
    assert confirmed.consultation is not None
    assert (
        confirmed.consultation.confirmation_source_turn_id
        == _turn_id(6)
    )
    assert durable_profile.load(_OWNER) is None

    persisted = coordinator.handle_turn(
        session_id="consultation-coordinator",
        conversation_version=failed.conversation_version,
        message="我确认是干皮",
        source_turn_id=_turn_id(7),
        profile_owner=_OWNER,
        confirmed_at=_CONFIRMED_AT,
    )
    replay = coordinator.handle_turn(
        session_id="consultation-coordinator",
        conversation_version=failed.conversation_version,
        message="我确认是干皮",
        source_turn_id=_turn_id(8),
        profile_owner=_OWNER,
        confirmed_at=_CONFIRMED_AT,
    )

    assert persisted is not None
    assert persisted.conversation_version == 8
    assert persisted.profile_persistence is not None
    assert persisted.profile_persistence.outcome == "created"
    assert replay is not None
    assert replay.conversation_version == 8
    assert replay.profile_persistence is not None
    assert replay.profile_persistence.outcome == "idempotent"
    assert conversation_state.load("consultation-coordinator") == confirmed
    profile = durable_profile.load(_OWNER)
    assert profile is not None
    assert profile.version == 1
    assert profile.facts[0].source_turn_id == _turn_id(6)


def test_corrupt_profile_store_preserves_confirmed_conversation_version() -> None:
    from app.guide.application.consultation_coordinator import (
        ConsultationApplicationCoordinator,
    )

    class CorruptProfileState:
        def load(self, owner):
            raise ProfileStateCorrupt(owner.subject_id)

        def write_once(self, fact, *, expected_version):
            raise AssertionError("corrupt profile must fail before writing")

        def save(self, fact, *, expected_version):
            raise AssertionError("corrupt profile must fail before saving")

    conversation_state = InMemoryConversationState()
    coordinator = ConsultationApplicationCoordinator(
        conversation_state=conversation_state,
        profile_state=CorruptProfileState(),
        long_term_profile_opt_in=True,
    )
    provisional = _advance_to_provisional(coordinator)

    result = coordinator.handle_turn(
        session_id="consultation-coordinator",
        conversation_version=provisional.conversation_version,
        message="我确认是干皮",
        source_turn_id=_turn_id(6),
        profile_owner=_OWNER,
        confirmed_at=_CONFIRMED_AT,
    )

    assert result is not None
    assert result.intent == "consultation_confirmation"
    assert result.conversation_version == 8
    assert result.profile_persistence is not None
    assert result.profile_persistence.outcome == "retry_required"
    assert result.profile_persistence.reason == "store_unavailable"
    stored = conversation_state.load("consultation-coordinator")
    assert stored is not None
    assert stored.version == 8
    assert stored.consultation is not None
    assert stored.consultation.confirmation_source_turn_id == _turn_id(6)


def test_profile_cas_failure_after_confirmation_reloads_latest_on_retry(
    tmp_path: Path,
) -> None:
    from app.guide.application.consultation_coordinator import (
        ConsultationApplicationCoordinator,
    )
    from app.guide.feedback.profile_contracts import ConfirmedProfileFact
    from app.guide.feedback.profile_state import ProfileStateConflict

    conversation_state = InMemoryConversationState()
    state_root = tmp_path / "state"
    durable_profile = SqliteProfileState(
        state_root / "profiles.sqlite3",
        trusted_state_root=state_root,
    )

    class RacingProfileState:
        race_pending = True

        def load(self, owner):
            return durable_profile.load(owner)

        def write_once(self, fact, *, expected_version):
            if self.race_pending:
                self.race_pending = False
                durable_profile.save(
                    ConfirmedProfileFact(
                        owner=_OWNER,
                        field="preferred_brand",
                        value="CeraVe",
                        source_turn_id="turn_profile_race_0001",
                        source_kind="explicit_user",
                        confirmed_at=_CONFIRMED_AT,
                        profile_version=1,
                    ),
                    expected_version=0,
                )
                raise ProfileStateConflict(_OWNER.subject_id)
            return durable_profile.write_once(
                fact,
                expected_version=expected_version,
            )

        def save(self, fact, *, expected_version):
            return durable_profile.save(
                fact,
                expected_version=expected_version,
            )

    coordinator = ConsultationApplicationCoordinator(
        conversation_state=conversation_state,
        profile_state=RacingProfileState(),
        long_term_profile_opt_in=True,
    )
    provisional = _advance_to_provisional(coordinator)

    conflicted = coordinator.handle_turn(
        session_id="consultation-coordinator",
        conversation_version=provisional.conversation_version,
        message="确认",
        source_turn_id=_turn_id(6),
        profile_owner=_OWNER,
        confirmed_at=_CONFIRMED_AT,
    )

    assert conflicted is not None
    assert conflicted.conversation_version == 8
    assert conflicted.profile_persistence is not None
    assert conflicted.profile_persistence.outcome == "retry_required"
    assert conflicted.profile_persistence.reason == "cas_conflict"
    assert _zero_card_payload(conflicted)["visible_product_ids"] == []

    reconciled = coordinator.handle_turn(
        session_id="consultation-coordinator",
        conversation_version=conflicted.conversation_version,
        message="确认",
        source_turn_id=_turn_id(7),
        profile_owner=_OWNER,
        confirmed_at=_CONFIRMED_AT,
    )

    assert reconciled is not None
    assert reconciled.conversation_version == 8
    assert reconciled.profile_persistence is not None
    assert reconciled.profile_persistence.outcome == "created"
    assert reconciled.profile_persistence.profile_version == 2
    profile = durable_profile.load(_OWNER)
    assert profile is not None
    assert profile.version == 2
    assert {(fact.field, fact.value) for fact in profile.facts} == {
        ("preferred_brand", "CeraVe"),
        ("skin_type", "dry"),
    }


def test_existing_skin_conflict_returns_typed_fill_only_outcome(
    tmp_path: Path,
) -> None:
    from app.guide.feedback.profile_contracts import ConfirmedProfileFact

    coordinator, conversation_state, profile_state = _build(tmp_path)
    before = profile_state.save(
        ConfirmedProfileFact(
            owner=_OWNER,
            field="skin_type",
            value="sensitive",
            source_turn_id="turn_existing_skin_001",
            source_kind="explicit_user",
            confirmed_at=_CONFIRMED_AT,
            profile_version=1,
        ),
        expected_version=0,
    )
    provisional = _advance_to_provisional(coordinator)

    output = coordinator.handle_turn(
        session_id="consultation-coordinator",
        conversation_version=provisional.conversation_version,
        message="确认",
        source_turn_id=_turn_id(6),
        profile_owner=_OWNER,
        confirmed_at=_CONFIRMED_AT,
    )

    assert output is not None
    assert output.intent == "consultation_confirmation"
    assert output.conclusion is not None
    assert output.conclusion.confirmed_by_user is True
    assert output.profile_persistence is not None
    assert output.profile_persistence.outcome == "preserved_existing"
    assert output.profile_persistence.disposition == "conflict"
    assert output.profile_persistence.value == "sensitive"
    assert output.profile_persistence.requested_value == "dry"
    assert profile_state.load(_OWNER) == before
    stored = conversation_state.load("consultation-coordinator")
    assert stored is not None
    assert stored.version == 8


def test_user_supplied_confirmation_target_cannot_override_assessment(
    tmp_path: Path,
) -> None:
    coordinator, conversation_state, profile_state = _build(tmp_path)
    provisional = _advance_to_provisional(coordinator)
    before = conversation_state.load("consultation-coordinator")

    output = coordinator.handle_turn(
        session_id="consultation-coordinator",
        conversation_version=provisional.conversation_version,
        message="我确认是油皮",
        source_turn_id=_turn_id(6),
        profile_owner=_OWNER,
        confirmed_at=_CONFIRMED_AT,
    )

    assert output is not None
    assert output.intent == "consultation_clarification"
    assert output.reason == "confirmation_required"
    assert output.profile_persistence is None
    assert conversation_state.load("consultation-coordinator") == before
    assert profile_state.load(_OWNER) is None


def test_medical_red_flag_without_skin_target_is_authoritative_terminal(
    tmp_path: Path,
) -> None:
    coordinator, conversation_state, profile_state = _build(tmp_path)
    entered = _enter(coordinator)
    assert entered is not None

    output = coordinator.handle_turn(
        session_id="consultation-coordinator",
        conversation_version=entered.conversation_version,
        message="好像会，而且持续红肿",
        source_turn_id=_turn_id(1),
        profile_owner=_OWNER,
    )

    assert output is not None
    assert output.intent == "consultation_medical_escalation"
    assert output.conversation_version == 2
    assert output.conclusion is not None
    assert output.conclusion.skin_target is None
    assert output.stop_skincare_advice is True
    assert tuple(item.code for item in output.escalation_triggers) == (
        "persistent_swelling",
    )
    assert output.profile_persistence is None
    assert profile_state.load(_OWNER) is None
    stored = conversation_state.load("consultation-coordinator")
    assert stored is not None
    assert stored.consultation is not None
    assessment = stored.consultation.confirmable_assessment
    assert assessment is not None
    assert assessment.assessment_kind == "medical_escalation"
    assert assessment.conclusion.skin_target is None
    assert assessment.conclusion.confirmed_by_user is False
    assert stored.consultation.confirmation_source_turn_id is None

    replay = coordinator.handle_turn(
        session_id="consultation-coordinator",
        conversation_version=output.conversation_version,
        message="确认",
        source_turn_id=_turn_id(2),
        profile_owner=_OWNER,
        confirmed_at=_CONFIRMED_AT,
    )
    assert replay is not None
    assert replay.intent == "consultation_medical_escalation"
    assert replay.conversation_version == 2
    assert conversation_state.load("consultation-coordinator") == stored
    assert profile_state.load(_OWNER) is None


@pytest.mark.parametrize(
    ("message", "code"),
    [
        ("我现在明显疼痛", "pain"),
        ("我现在持续肿胀", "persistent_swelling"),
        ("我现在有液体渗出", "oozing"),
    ],
)
def test_red_flag_while_awaiting_confirmation_records_separate_terminal_state(
    tmp_path: Path,
    message: str,
    code: str,
) -> None:
    coordinator, conversation_state, profile_state = _build(tmp_path)
    provisional = _advance_to_provisional(coordinator)
    before = conversation_state.load("consultation-coordinator")
    assert before is not None
    assert before.consultation is not None
    provisional_assessment = before.consultation.confirmable_assessment
    assert provisional_assessment is not None

    output = coordinator.handle_turn(
        session_id="consultation-coordinator",
        conversation_version=provisional.conversation_version,
        message=message,
        source_turn_id=_turn_id(6),
        profile_owner=_OWNER,
    )

    assert output is not None
    assert output.intent == "consultation_medical_escalation"
    assert output.conversation_version == 8
    assert output.stop_skincare_advice is True
    assert tuple(item.code for item in output.escalation_triggers) == (
        code,
    )
    assert output.profile_persistence is None
    assert _zero_card_payload(output) == {
        "mode": "none",
        "visible_product_ids": [],
        "max_cards": 0,
        "reason": None,
    }
    stored = conversation_state.load("consultation-coordinator")
    assert stored is not None
    assert stored.consultation is not None
    assert (
        stored.consultation.confirmable_assessment
        == provisional_assessment
    )
    escalation = stored.consultation.medical_escalation
    assert escalation is not None
    assert escalation.recorded_at_conversation_version == 8
    assert escalation.assessment.assessment_kind == "medical_escalation"
    assert tuple(
        item.code for item in escalation.assessment.escalation_triggers
    ) == (code,)
    assert profile_state.load(_OWNER) is None

    replay = coordinator.handle_turn(
        session_id="consultation-coordinator",
        conversation_version=output.conversation_version,
        message="确认",
        source_turn_id=_turn_id(7),
        profile_owner=_OWNER,
        confirmed_at=_CONFIRMED_AT,
    )

    assert replay is not None
    assert replay.intent == "consultation_medical_escalation"
    assert replay.conversation_version == 8
    assert replay.stop_skincare_advice is True
    assert conversation_state.load("consultation-coordinator") == stored
    assert profile_state.load(_OWNER) is None


@pytest.mark.parametrize("mutation", ["remove", "rewrite"])
def test_recorded_medical_escalation_cannot_be_removed_or_rewritten(
    tmp_path: Path,
    mutation: str,
) -> None:
    coordinator, conversation_state, _ = _build(tmp_path)
    provisional = _advance_to_provisional(coordinator)
    escalated = coordinator.handle_turn(
        session_id="consultation-coordinator",
        conversation_version=provisional.conversation_version,
        message="我现在明显疼痛",
        source_turn_id=_turn_id(6),
        profile_owner=_OWNER,
    )
    assert escalated is not None
    current = conversation_state.load("consultation-coordinator")
    assert current is not None
    assert current.consultation is not None
    medical = current.consultation.medical_escalation
    assert medical is not None

    if mutation == "remove":
        replacement_medical = None
    else:
        replacement_medical = medical.model_copy(
            update={
                "recorded_at_conversation_version": (
                    medical.recorded_at_conversation_version + 1
                )
            },
            deep=True,
        )
    replacement_consultation = current.consultation.model_copy(
        update={"medical_escalation": replacement_medical},
        deep=True,
    )
    replacement = current.model_copy(
        update={
            "version": current.version + 1,
            "consultation": replacement_consultation,
        },
        deep=True,
    )

    with pytest.raises(ValueError, match="medical escalation is immutable"):
        conversation_state.save(
            replacement,
            expected_version=current.version,
        )

    assert conversation_state.load("consultation-coordinator") == current
    with pytest.raises(ValidationError, match="frozen"):
        medical.assessment.escalation_triggers[0].code = "oozing"


def test_escalation_first_race_blocks_confirmation_and_profile_write(
    tmp_path: Path,
) -> None:
    coordinator, conversation_state, profile_state = _build(tmp_path)
    provisional = _advance_to_provisional(coordinator)
    escalated = coordinator.handle_turn(
        session_id="consultation-coordinator",
        conversation_version=provisional.conversation_version,
        message="我现在明显疼痛",
        source_turn_id=_turn_id(6),
        profile_owner=_OWNER,
    )
    assert escalated is not None

    with pytest.raises(ConversationStateConflict):
        coordinator.handle_turn(
            session_id="consultation-coordinator",
            conversation_version=provisional.conversation_version,
            message="确认",
            source_turn_id=_turn_id(7),
            profile_owner=_OWNER,
            confirmed_at=_CONFIRMED_AT,
        )

    stored = conversation_state.load("consultation-coordinator")
    assert stored is not None
    assert stored.version == 8
    assert stored.consultation is not None
    assert stored.consultation.medical_escalation is not None
    assert profile_state.load(_OWNER) is None


def test_confirmation_first_race_rejects_escalation_after_final_authority_load(
    tmp_path: Path,
) -> None:
    from app.guide.application.consultation_coordinator import (
        ConsultationApplicationCoordinator,
    )

    backing_state = InMemoryConversationState()
    state_root = tmp_path / "state"
    durable_profile = SqliteProfileState(
        state_root / "profiles.sqlite3",
        trusted_state_root=state_root,
    )
    final_authority_loaded = Event()
    allow_final_authority_return = Event()
    profile_write_authorities = []

    class PausingFinalAuthorityState:
        confirmed_loads = 0

        def load(self, session_id):
            snapshot = backing_state.load(session_id)
            consultation = snapshot.consultation if snapshot else None
            assessment = (
                consultation.confirmable_assessment
                if consultation is not None
                else None
            )
            if (
                assessment is not None
                and assessment.conclusion.confirmed_by_user
            ):
                self.confirmed_loads += 1
                if self.confirmed_loads == 2:
                    final_authority_loaded.set()
                    assert allow_final_authority_return.wait(timeout=5)
            return snapshot

        def save(self, snapshot, *, expected_version):
            return backing_state.save(
                snapshot,
                expected_version=expected_version,
            )

    class AuthorityRecordingProfileState:
        def load(self, owner):
            return durable_profile.load(owner)

        def write_once(self, fact, *, expected_version):
            profile_write_authorities.append(
                backing_state.load("consultation-coordinator")
            )
            return durable_profile.write_once(
                fact,
                expected_version=expected_version,
            )

        def save(self, fact, *, expected_version):
            return durable_profile.save(
                fact,
                expected_version=expected_version,
            )

    coordinator = ConsultationApplicationCoordinator(
        conversation_state=PausingFinalAuthorityState(),
        profile_state=AuthorityRecordingProfileState(),
        long_term_profile_opt_in=True,
    )
    provisional = _advance_to_provisional(coordinator)

    with ThreadPoolExecutor(max_workers=1) as executor:
        confirming = executor.submit(
            coordinator.handle_turn,
            session_id="consultation-coordinator",
            conversation_version=provisional.conversation_version,
            message="确认",
            source_turn_id=_turn_id(6),
            profile_owner=_OWNER,
            confirmed_at=_CONFIRMED_AT,
        )
        assert final_authority_loaded.wait(timeout=5)
        confirmed = backing_state.load("consultation-coordinator")
        assert confirmed is not None
        assert confirmed.version == 8
        assert confirmed.consultation is not None
        confirmed_assessment = (
            confirmed.consultation.confirmable_assessment
        )
        assert confirmed_assessment is not None
        assert confirmed_assessment.conclusion.confirmed_by_user is True
        escalation = _medical_transition(
            confirmed,
            source_turn_id=_turn_id(7),
        )
        replacement = confirmed.model_copy(
            update={
                "version": escalation.output.conversation_version,
                "consultation": escalation.next_consultation,
            },
            deep=True,
        )
        try:
            with pytest.raises(ValueError, match="mutually exclusive"):
                backing_state.save(
                    replacement,
                    expected_version=confirmed.version,
                )
        finally:
            allow_final_authority_return.set()
        confirmation_result = confirming.result(timeout=5)

    assert confirmation_result is not None
    assert confirmation_result.intent == "consultation_confirmation"
    assert confirmation_result.conversation_version == 8
    assert confirmation_result.profile_persistence is not None
    assert confirmation_result.profile_persistence.outcome == "created"
    stored = backing_state.load("consultation-coordinator")
    assert stored is not None
    assert stored == confirmed
    assert stored.consultation is not None
    assert stored.consultation.medical_escalation is None
    assert profile_write_authorities == [confirmed]
    profile = durable_profile.load(_OWNER)
    assert profile is not None
    assert profile.version == 1
    assert profile.facts[0].value == "dry"
    assert profile.facts[0].source_turn_id == _turn_id(6)


def test_red_flag_after_confirmation_is_typed_read_only_safety_stop(
    tmp_path: Path,
) -> None:
    coordinator, conversation_state, profile_state = _build(tmp_path)
    provisional = _advance_to_provisional(coordinator)
    confirmed = coordinator.handle_turn(
        session_id="consultation-coordinator",
        conversation_version=provisional.conversation_version,
        message="确认",
        source_turn_id=_turn_id(6),
        profile_owner=_OWNER,
        confirmed_at=_CONFIRMED_AT,
    )
    assert confirmed is not None
    conversation_before = conversation_state.load(
        "consultation-coordinator"
    )
    profile_before = profile_state.load(_OWNER)

    output = coordinator.handle_turn(
        session_id="consultation-coordinator",
        conversation_version=confirmed.conversation_version,
        message="我现在明显疼痛",
        source_turn_id=_turn_id(7),
        profile_owner=_OWNER,
    )

    assert output is not None
    assert output.intent == "consultation_medical_escalation"
    assert output.conversation_version == confirmed.conversation_version
    assert output.conclusion is not None
    assert output.conclusion.confirmed_by_user is False
    assert output.stop_skincare_advice is True
    assert tuple(item.code for item in output.escalation_triggers) == ("pain",)
    assert output.profile_persistence is None
    assert _zero_card_payload(output) == {
        "mode": "none",
        "visible_product_ids": [],
        "max_cards": 0,
        "reason": None,
    }
    assert conversation_state.load(
        "consultation-coordinator"
    ) == conversation_before
    assert profile_state.load(_OWNER) == profile_before
    assert profile_before is not None
    assert profile_before.facts[0].value == "dry"


def test_current_explicit_skin_overrides_for_turn_without_mutation(
    tmp_path: Path,
) -> None:
    coordinator, conversation_state, profile_state = _build(tmp_path)
    provisional = _advance_to_provisional(coordinator)
    confirmed = coordinator.handle_turn(
        session_id="consultation-coordinator",
        conversation_version=provisional.conversation_version,
        message="确认",
        source_turn_id=_turn_id(6),
        profile_owner=_OWNER,
        confirmed_at=_CONFIRMED_AT,
    )
    assert confirmed is not None
    conversation_before = conversation_state.load(
        "consultation-coordinator"
    )
    profile_before = profile_state.load(_OWNER)

    resolved = coordinator.resolve_turn_profile(
        session_id="consultation-coordinator",
        profile_owner=_OWNER,
        current_explicit_skin=SkinTarget.OILY,
        source_turn_id=_turn_id(7),
    )

    skin = next(item for item in resolved.values if item.field == "skin_type")
    assert skin.value == "oily"
    assert skin.source == "current_explicit_input"
    assert conversation_state.load(
        "consultation-coordinator"
    ) == conversation_before
    assert profile_state.load(_OWNER) == profile_before
    assert profile_before is not None
    assert profile_before.facts[0].value == "dry"


def test_owner_mismatch_fails_before_state_or_profile_disclosure(
    tmp_path: Path,
) -> None:
    coordinator, conversation_state, profile_state = _build(tmp_path)
    entered = _enter(coordinator)
    assert entered is not None
    before = conversation_state.load("consultation-coordinator")
    other = ProfileOwnerRef(
        scope="authenticated_user",
        subject_id="other_consultation_0123456789",
    )

    with pytest.raises(ConversationStateConflict) as captured:
        coordinator.handle_turn(
            session_id="consultation-coordinator",
            conversation_version=entered.conversation_version,
            message="会",
            source_turn_id=_turn_id(1),
            profile_owner=other,
        )

    assert conversation_state.load("consultation-coordinator") == before
    assert profile_state.load(_OWNER) is None
    assert _OWNER.subject_id not in str(captured.value)
    assert other.subject_id not in str(captured.value)


def test_coordinator_resumes_from_durable_state_after_restart(
    tmp_path: Path,
) -> None:
    from app.guide.adapters.state.sqlite_conversation_state import (
        SqliteConversationState,
    )
    from app.guide.application.consultation_coordinator import (
        ConsultationApplicationCoordinator,
    )

    state_root = tmp_path / "state"
    conversation_path = state_root / "conversations.sqlite3"
    profile_path = state_root / "profiles.sqlite3"
    first = ConsultationApplicationCoordinator(
        conversation_state=SqliteConversationState(
            conversation_path,
            trusted_state_root=state_root,
        ),
        profile_state=SqliteProfileState(
            profile_path,
            trusted_state_root=state_root,
        ),
    )
    entered = _enter(first)
    assert entered is not None

    conversation_state = SqliteConversationState(
        conversation_path,
        trusted_state_root=state_root,
    )
    restarted = ConsultationApplicationCoordinator(
        conversation_state=conversation_state,
        profile_state=SqliteProfileState(
            profile_path,
            trusted_state_root=state_root,
        ),
    )
    answered = restarted.handle_turn(
        session_id="consultation-coordinator",
        conversation_version=entered.conversation_version,
        message="会",
        source_turn_id=_turn_id(1),
        profile_owner=_OWNER,
    )

    assert answered is not None
    assert answered.intent == "consultation_answer"
    assert answered.conversation_version == 2
    stored = conversation_state.load("consultation-coordinator")
    assert stored is not None
    assert stored.consultation is not None
    assert tuple(
        observation.answer
        for observation in stored.consultation.observations
    ) == ("yes",)
