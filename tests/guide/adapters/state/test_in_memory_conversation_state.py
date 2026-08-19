from __future__ import annotations

import pytest

from app.guide.adapters.state import InMemoryConversationState
from app.guide.feedback.contracts import (
    ConversationSnapshot,
    DisplayedCandidateRef,
    RecommendationQueryContext,
)
from app.guide.feedback.consultation_state import ConsultationSubstate
from app.guide.feedback.focus_state import FocusState
from app.guide.feedback.ports import ConversationStateConflict
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.feedback.session_profile import (
    SessionProfile,
    StableTendencyUpdate,
    reduce_session_profile,
)
from app.guide.understanding.consultation_contracts import (
    ConsultationObservation,
)
from app.guide.understanding.contracts import TopicCode


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


def snapshot(
    session_id: str,
    version: int,
    product_id: int,
    *,
    product_ids: tuple[int, ...] | None = None,
    focused_candidate_ordinal: int | None = None,
    category: str = "serum",
) -> ConversationSnapshot:
    visible_product_ids = (
        product_ids if product_ids is not None else (product_id,)
    )
    return ConversationSnapshot(
        session_id=session_id,
        version=version,
        query_context=RecommendationQueryContext(
            category=category,
            budget_minimum=None,
            budget_maximum=None,
            skin=None,
            efficacy="repair" if category == "serum" else None,
            exclusions=[],
        ),
        candidates=[
            DisplayedCandidateRef(
                product_id=visible_product_id,
                ordinal=ordinal,
                skin_match="unknown",
                matched_efficacies=[],
            )
            for ordinal, visible_product_id in enumerate(
                visible_product_ids,
                start=1,
            )
        ],
        focused_candidate_ordinal=focused_candidate_ordinal,
    )


def consultation_observation(
    code: str,
    *,
    answer: str,
    source_turn_id: str,
) -> ConsultationObservation:
    return ConsultationObservation(
        code=code,
        answer=answer,
        source_turn_id=source_turn_id,
    )


def consultation_snapshot(
    session_id: str,
    version: int,
    observations: tuple[ConsultationObservation, ...],
) -> ConversationSnapshot:
    return ConversationSnapshot(
        session_id=session_id,
        version=version,
        consultation=ConsultationSubstate(observations=observations),
    )


def save_two_observations(
    store: InMemoryConversationState,
    *,
    session_id: str = "consultation-state",
) -> ConversationSnapshot:
    active = store.save(
        consultation_snapshot(session_id, 1, ()),
        expected_version=0,
    )
    first_observation = consultation_observation(
        "post_cleanse_tightness",
        answer="yes",
        source_turn_id="turn_collect_00000001",
    )
    first = store.save(
        consultation_snapshot(session_id, 2, (first_observation,)),
        expected_version=active.version,
    )
    second_observation = consultation_observation(
        "t_zone_oiliness",
        answer="no",
        source_turn_id="turn_collect_00000002",
    )
    return store.save(
        consultation_snapshot(
            session_id,
            3,
            (first_observation, second_observation),
        ),
        expected_version=first.version,
    )


def save_provisional_assessment(
    store: InMemoryConversationState,
) -> ConversationSnapshot:
    from app.guide.application.consultation_assessment import (
        assess_consultation,
    )
    from app.guide.application.consultation_confirmation import (
        record_provisional_conclusion,
    )

    collecting = save_two_observations(store)
    assert collecting.consultation is not None
    assessment = assess_consultation(
        collecting.consultation,
        current_conversation_version=collecting.version,
        conclusion_source_turn_id="turn_assessment_000001",
    )
    transition = record_provisional_conclusion(
        collecting.consultation,
        current_conversation_version=collecting.version,
        assessment=assessment.confirmable_assessment,
    )
    return store.save(
        collecting.model_copy(
            update={
                "version": transition.output.conversation_version,
                "consultation": transition.next_consultation,
            },
            deep=True,
        ),
        expected_version=transition.expected_conversation_version,
    )


def save_confirmed_assessment(
    store: InMemoryConversationState,
) -> ConversationSnapshot:
    from app.guide.application.consultation_confirmation import (
        confirm_provisional_conclusion,
    )

    provisional = save_provisional_assessment(store)
    assert provisional.consultation is not None
    assessment = provisional.consultation.confirmable_assessment
    assert assessment is not None
    assert assessment.conclusion.skin_target == "dry"
    transition = confirm_provisional_conclusion(
        provisional.consultation,
        current_conversation_version=provisional.version,
        message="我确认是干性肤质",
        source_turn_id="turn_confirm_00000001",
        expected_skin_target="dry",
        expected_conclusion_source_turn_id=(
            assessment.conclusion_source_turn_id
        ),
    )
    return store.save(
        provisional.model_copy(
            update={
                "version": transition.output.conversation_version,
                "consultation": transition.next_consultation,
            },
            deep=True,
        ),
        expected_version=transition.expected_conversation_version,
    )


def test_delete_requires_matching_owner_and_removes_whole_snapshot() -> None:
    store = InMemoryConversationState()
    owner = ProfileOwnerRef(
        scope="local_demo",
        subject_id="owner-delete-session",
    )
    foreign = ProfileOwnerRef(
        scope="local_demo",
        subject_id="foreign-delete-session",
    )
    stored = snapshot("delete-session", 1, 91).model_copy(
        update={
            "profile_owner": owner,
            "session_profile": reduce_session_profile(
                previous=SessionProfile(),
                updates=(
                    StableTendencyUpdate(
                        value="sensitivity",
                        confirmation="confirmed",
                    ),
                ),
                subject_scope="self",
                source_turn_id="turn_delete_profile_0001",
                conversation_version=1,
            ).profile,
            "focus_state": FocusState(
                active_processor="recommendation",
                current_product_id=91,
            ),
        },
        deep=True,
    )
    store.save(stored, expected_version=0)

    assert store.load("delete-session").session_profile is not None
    assert store.load("delete-session").focus_state is not None
    assert not store.delete(
        "delete-session",
        expected_owner=foreign,
    )
    assert store.load("delete-session") == stored
    assert store.delete(
        "delete-session",
        expected_owner=owner,
    )
    assert store.load("delete-session") is None
    assert not store.delete(
        "delete-session",
        expected_owner=owner,
    )


def medical_escalation_transition(
    snapshot: ConversationSnapshot,
    *,
    source_turn_id: str,
):
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


def test_store_compare_and_set_and_copy_isolation() -> None:
    store = InMemoryConversationState()
    saved = store.save(snapshot("s-1", 1, 91), expected_version=0)
    loaded = store.load("s-1")

    assert saved == loaded
    assert loaded is not saved
    with pytest.raises(ConversationStateConflict):
        store.save(snapshot("s-1", 2, 38), expected_version=0)


def test_four_candidate_round_trip_preserves_order_and_cas() -> None:
    store = InMemoryConversationState()
    current = store.save(
        snapshot(
            "four-candidate-state",
            1,
            91,
            product_ids=(91, 38, 55, 72),
            focused_candidate_ordinal=4,
        ),
        expected_version=0,
    )

    loaded = store.load(current.session_id)

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
        store.save(
            current.model_copy(update={"version": 2}, deep=True),
            expected_version=0,
        )
    assert store.load(current.session_id) == current


def test_focus_state_round_trips_without_aliasing() -> None:
    store = InMemoryConversationState()
    current = snapshot(
        "focus-round-trip",
        1,
        51,
        product_ids=(51, 55, 101),
        focused_candidate_ordinal=2,
    ).model_copy(
        update={
            "focus_state": FocusState(
                active_processor="product_knowledge",
                current_product_id=55,
                last_question_meaning="询问第二款",
            )
        },
        deep=True,
    )

    saved = store.save(current, expected_version=0)
    loaded = store.load(current.session_id)

    assert loaded == saved
    assert loaded is not saved
    assert loaded.focus_state is not saved.focus_state
    assert loaded.focus_state.current_product_id == 55


@pytest.mark.parametrize("topic", list(TopicCode))
def test_store_round_trips_every_topic_code(topic: TopicCode) -> None:
    store = InMemoryConversationState()
    saved = store.save(
        snapshot(
            f"topic-{topic.value}",
            1,
            91,
            category=topic.value,
        ),
        expected_version=0,
    )

    loaded = store.load(saved.session_id)

    assert loaded is not None
    assert loaded.query_context is not None
    assert loaded.query_context.category == topic.value


def test_store_expires_by_injected_clock() -> None:
    clock = FakeClock()
    store = InMemoryConversationState(
        ttl_seconds=30,
        clock=clock,
    )
    store.save(snapshot("s-1", 1, 91), expected_version=0)
    clock.value = 30
    assert store.load("s-1") is None


def test_store_evicts_least_recently_updated_session() -> None:
    clock = FakeClock()
    store = InMemoryConversationState(
        max_sessions=2,
        ttl_seconds=300,
        clock=clock,
    )
    store.save(snapshot("s-1", 1, 1), expected_version=0)
    clock.value = 1
    store.save(snapshot("s-2", 1, 2), expected_version=0)
    clock.value = 2
    store.save(snapshot("s-3", 1, 3), expected_version=0)

    assert store.load("s-1") is None
    assert store.load("s-2") is not None
    assert store.load("s-3") is not None


def test_store_instances_do_not_share_state() -> None:
    first = InMemoryConversationState()
    second = InMemoryConversationState()
    first.save(snapshot("s-1", 1, 91), expected_version=0)
    assert second.load("s-1") is None


@pytest.mark.parametrize(
    "mutation",
    ["answer", "source", "remove", "reorder"],
)
def test_store_rejects_changes_to_prior_consultation_observations(
    mutation: str,
) -> None:
    store = InMemoryConversationState()
    current = save_two_observations(store)
    assert current.consultation is not None
    observations = list(current.consultation.observations)

    if mutation == "answer":
        observations[0] = observations[0].model_copy(
            update={"answer": "no"}
        )
        replacement_consultation = ConsultationSubstate(
            observations=observations
        )
    elif mutation == "source":
        observations[0] = observations[0].model_copy(
            update={"source_turn_id": "turn_rewritten_000001"}
        )
        replacement_consultation = ConsultationSubstate(
            observations=observations
        )
    elif mutation == "remove":
        replacement_consultation = ConsultationSubstate(
            observations=observations[:-1]
        )
    else:
        replacement_consultation = current.consultation.model_copy(
            update={"observations": tuple(reversed(observations))},
            deep=True,
        )

    replacement = current.model_copy(
        update={
            "version": current.version + 1,
            "consultation": replacement_consultation,
        },
        deep=True,
    )

    with pytest.raises(ValueError, match="immutable prefix"):
        store.save(replacement, expected_version=current.version)

    assert store.load(current.session_id) == current


def test_store_rejects_more_than_one_observation_in_one_transition() -> None:
    store = InMemoryConversationState()
    active = store.save(
        consultation_snapshot("consultation-state", 1, ()),
        expected_version=0,
    )
    first_observation = consultation_observation(
        "post_cleanse_tightness",
        answer="yes",
        source_turn_id="turn_collect_00000001",
    )
    current = store.save(
        consultation_snapshot(
            "consultation-state",
            2,
            (first_observation,),
        ),
        expected_version=active.version,
    )
    replacement = consultation_snapshot(
        current.session_id,
        3,
        (
            first_observation,
            consultation_observation(
                "t_zone_oiliness",
                answer="no",
                source_turn_id="turn_collect_00000002",
            ),
            consultation_observation(
                "recurrent_redness",
                answer="sometimes",
                source_turn_id="turn_collect_00000003",
            ),
        ),
    )

    with pytest.raises(ValueError, match="one observation"):
        store.save(replacement, expected_version=current.version)

    assert store.load(current.session_id) == current


def test_store_rejects_multiple_observations_in_initial_transition() -> None:
    store = InMemoryConversationState()
    replacement = consultation_snapshot(
        "consultation-state",
        1,
        (
            consultation_observation(
                "post_cleanse_tightness",
                answer="yes",
                source_turn_id="turn_collect_00000001",
            ),
            consultation_observation(
                "t_zone_oiliness",
                answer="no",
                source_turn_id="turn_collect_00000002",
            ),
        ),
    )

    with pytest.raises(ValueError, match="stored before observations"):
        store.save(replacement, expected_version=0)

    assert store.load(replacement.session_id) is None


@pytest.mark.parametrize("has_existing_observation", [False, True])
def test_store_rejects_confirmation_source_without_assessment(
    has_existing_observation: bool,
) -> None:
    store = InMemoryConversationState()
    active = consultation_snapshot(
        "consultation-state",
        1,
        (),
    )
    base = store.save(active, expected_version=0)
    expected_version = base.version
    observations: tuple[ConsultationObservation, ...] = ()
    if has_existing_observation:
        observations = (
            consultation_observation(
                "post_cleanse_tightness",
                answer="yes",
                source_turn_id="turn_collect_00000001",
            ),
        )
        base = store.save(
            consultation_snapshot(
                "consultation-state",
                2,
                observations,
            ),
            expected_version=expected_version,
        )
        expected_version = base.version
    base = consultation_snapshot(
        "consultation-state",
        expected_version,
        observations,
    )
    assert base.consultation is not None
    invalid_consultation = base.consultation.model_copy(
        update={
            "confirmation_source_turn_id": "turn_confirm_00000001"
        },
        deep=True,
    )
    replacement = base.model_copy(
        update={
            "version": expected_version + 1,
            "consultation": invalid_consultation,
        },
        deep=True,
    )

    with pytest.raises(ValueError, match="provisional assessment"):
        store.save(replacement, expected_version=expected_version)

    assert store.load(replacement.session_id) == (
        base
    )


@pytest.mark.parametrize("mutation", ["change", "clear"])
def test_store_rejects_changing_or_clearing_recorded_assessment(
    mutation: str,
) -> None:
    store = InMemoryConversationState()
    current = save_provisional_assessment(store)
    assert current.consultation is not None
    assessment = current.consultation.confirmable_assessment
    assert assessment is not None

    if mutation == "change":
        changed_conclusion = assessment.conclusion.model_copy(
            update={
                "confidence": (
                    "high"
                    if assessment.conclusion.confidence != "high"
                    else "low"
                )
            }
        )
        changed_assessment = assessment.model_copy(
            update={"conclusion": changed_conclusion},
            deep=True,
        )
        replacement_consultation = ConsultationSubstate(
            observations=current.consultation.observations,
            confirmable_assessment=changed_assessment,
        )
    else:
        replacement_consultation = ConsultationSubstate(
            observations=current.consultation.observations,
        )
    replacement = current.model_copy(
        update={
            "version": current.version + 1,
            "consultation": replacement_consultation,
        },
        deep=True,
    )

    with pytest.raises(ValueError, match="assessment is immutable"):
        store.save(replacement, expected_version=current.version)

    assert store.load(current.session_id) == current


@pytest.mark.parametrize("mutation", ["clear", "change_source"])
def test_store_rejects_changing_or_clearing_recorded_confirmation(
    mutation: str,
) -> None:
    store = InMemoryConversationState()
    current = save_confirmed_assessment(store)
    assert current.consultation is not None
    assessment = current.consultation.confirmable_assessment
    assert assessment is not None

    if mutation == "clear":
        unconfirmed_conclusion = assessment.conclusion.model_copy(
            update={"confirmed_by_user": False}
        )
        unconfirmed_assessment = assessment.model_copy(
            update={"conclusion": unconfirmed_conclusion},
            deep=True,
        )
        replacement_consultation = ConsultationSubstate(
            observations=current.consultation.observations,
            confirmable_assessment=unconfirmed_assessment,
        )
    else:
        replacement_consultation = ConsultationSubstate(
            observations=current.consultation.observations,
            confirmable_assessment=assessment,
            confirmation_source_turn_id="turn_confirm_rewrite_01",
        )
    replacement = current.model_copy(
        update={
            "version": current.version + 1,
            "consultation": replacement_consultation,
        },
        deep=True,
    )

    with pytest.raises(ValueError, match="confirmation is immutable"):
        store.save(replacement, expected_version=current.version)

    assert store.load(current.session_id) == current


def test_store_rejects_escalation_after_confirmation() -> None:
    store = InMemoryConversationState()
    current = save_confirmed_assessment(store)
    transition = medical_escalation_transition(
        current,
        source_turn_id="turn_escalate_after_confirm_0001",
    )
    replacement = current.model_copy(
        update={
            "version": transition.output.conversation_version,
            "consultation": transition.next_consultation,
        },
        deep=True,
    )

    with pytest.raises(ValueError, match="mutually exclusive"):
        store.save(replacement, expected_version=current.version)

    assert store.load(current.session_id) == current


def test_store_rejects_confirmation_after_escalation() -> None:
    store = InMemoryConversationState()
    provisional = save_provisional_assessment(store)
    transition = medical_escalation_transition(
        provisional,
        source_turn_id="turn_escalate_before_confirm_001",
    )
    escalated = store.save(
        provisional.model_copy(
            update={
                "version": transition.output.conversation_version,
                "consultation": transition.next_consultation,
            },
            deep=True,
        ),
        expected_version=provisional.version,
    )
    consultation = escalated.consultation
    assert consultation is not None
    assessment = consultation.confirmable_assessment
    assert assessment is not None
    confirmed_assessment = assessment.model_copy(
        update={
            "conclusion": assessment.conclusion.model_copy(
                update={"confirmed_by_user": True}
            )
        },
        deep=True,
    )
    replacement = escalated.model_copy(
        update={
            "version": escalated.version + 1,
            "consultation": consultation.model_copy(
                update={
                    "confirmable_assessment": confirmed_assessment,
                    "confirmation_source_turn_id": (
                        "turn_confirm_after_escalation_01"
                    ),
                },
                deep=True,
            ),
        },
        deep=True,
    )

    with pytest.raises(ValueError, match="mutually exclusive"):
        store.save(replacement, expected_version=escalated.version)

    assert store.load(escalated.session_id) == escalated


def test_store_allows_append_provisional_and_confirmation_transitions() -> None:
    store = InMemoryConversationState()

    confirmed = save_confirmed_assessment(store)

    assert confirmed.version == 5
    assert confirmed.consultation is not None
    assert len(confirmed.consultation.observations) == 2
    assessment = confirmed.consultation.confirmable_assessment
    assert assessment is not None
    assert assessment.conclusion.confirmed_by_user is True
    assert (
        confirmed.consultation.confirmation_source_turn_id
        == "turn_confirm_00000001"
    )


def test_ownerless_snapshot_cannot_be_claimed_by_later_save() -> None:
    store = InMemoryConversationState()
    initial = store.save(snapshot("s-1", 1, 91), expected_version=0)
    owner = ProfileOwnerRef(
        scope="local_demo",
        subject_id="profile_0123456789abcdef",
    )
    bound = ConversationSnapshot(
        **{
            **initial.model_dump(),
            "version": 2,
            "profile_owner": owner,
        }
    )

    with pytest.raises(ConversationStateConflict):
        store.save(bound, expected_version=1)

    assert store.load("s-1").profile_owner is None


def test_profile_owner_must_be_set_on_first_authoritative_snapshot() -> None:
    owner = ProfileOwnerRef(
        scope="local_demo",
        subject_id="profile_0123456789abcdef",
    )
    store = InMemoryConversationState()
    first = ConversationSnapshot(
        **{
            **snapshot("s-1", 1, 91).model_dump(),
            "profile_owner": owner,
        }
    )
    saved = store.save(first, expected_version=0)
    second = ConversationSnapshot(
        **{
            **saved.model_dump(),
            "version": 2,
        }
    )

    updated = store.save(second, expected_version=1)

    assert updated.profile_owner == owner


@pytest.mark.parametrize("replacement", ["different", "anonymous"])
def test_bound_profile_owner_cannot_change_or_be_removed(
    replacement: str,
) -> None:
    owner = ProfileOwnerRef(
        scope="local_demo",
        subject_id="profile_0123456789abcdef",
    )
    store = InMemoryConversationState()
    bound = ConversationSnapshot(
        **{
            **snapshot("s-1", 1, 91).model_dump(),
            "profile_owner": owner,
        }
    )
    store.save(bound, expected_version=0)
    next_owner = (
        ProfileOwnerRef(
            scope="authenticated_user",
            subject_id="profile_fedcba9876543210",
        )
        if replacement == "different"
        else None
    )
    replacement_snapshot = ConversationSnapshot(
        **{
            **bound.model_dump(),
            "version": 2,
            "profile_owner": next_owner,
        }
    )

    with pytest.raises(ConversationStateConflict):
        store.save(replacement_snapshot, expected_version=1)

    assert store.load("s-1").profile_owner == owner
