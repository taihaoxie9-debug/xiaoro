from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.guide.feedback.contracts import (
    ClarificationProgress,
    ConversationSnapshot,
    DisplayedCandidateRef,
    PendingBudgetRange,
    PendingRecommendationContext,
    PendingTurn,
    RecommendationQueryContext,
)
from app.guide.feedback.consultation_state import ConsultationSubstate
from app.guide.feedback.ports import (
    validate_conversation_state_transition,
)
from app.guide.feedback.session_profile import (
    BaseSkinUpdate,
    SessionProfile,
    StableTendencyUpdate,
    reduce_session_profile,
)
from app.guide.understanding.consultation_contracts import (
    ConsultationObservation,
)
from app.guide.understanding.contracts import TopicCode
from app.guide.understanding.semantic_contracts import ClarificationCode


def candidate(product_id: int, ordinal: int) -> DisplayedCandidateRef:
    return DisplayedCandidateRef(
        product_id=product_id,
        ordinal=ordinal,
        skin_match="unknown",
        matched_efficacies=["修护"],
    )


def query_context() -> RecommendationQueryContext:
    return RecommendationQueryContext(
        category="serum",
        budget_minimum=None,
        budget_maximum=Decimal("500"),
        skin="sensitive",
        efficacy="repair",
        exclusions=[],
    )


def consultation() -> ConsultationSubstate:
    return ConsultationSubstate(
        observations=(
            ConsultationObservation(
                code="post_cleanse_tightness",
                answer="yes",
                source_turn_id="turn_0000000000000001",
            ),
        ),
    )


def test_snapshot_requires_contiguous_unique_displayed_candidates() -> None:
    snapshot = ConversationSnapshot(
        session_id="session-1",
        version=1,
        query_context=query_context(),
        candidates=[candidate(91, 1), candidate(38, 2)],
    )
    assert [item.product_id for item in snapshot.candidates] == [91, 38]

    with pytest.raises(ValidationError, match="ordinal"):
        ConversationSnapshot(
            session_id="session-1",
            version=1,
            query_context=query_context(),
            candidates=[candidate(91, 1), candidate(38, 3)],
        )
    with pytest.raises(ValidationError, match="product_id"):
        ConversationSnapshot(
            session_id="session-1",
            version=1,
            query_context=query_context(),
            candidates=[candidate(91, 1), candidate(91, 2)],
        )


def test_candidate_focus_is_explicit_and_bounded_by_visible_candidates() -> None:
    unfocused = ConversationSnapshot(
        session_id="candidate-focus-default",
        version=1,
        query_context=query_context(),
        candidates=[candidate(91, 1), candidate(38, 2)],
    )
    focused = ConversationSnapshot(
        session_id="candidate-focus-explicit",
        version=1,
        query_context=query_context(),
        candidates=[candidate(91, 1), candidate(38, 2)],
        focused_candidate_ordinal=2,
    )

    assert unfocused.focused_candidate_ordinal is None
    assert focused.focused_candidate_ordinal == 2
    assert ConversationSnapshot.model_validate_json(
        focused.model_dump_json()
    ) == focused


def test_candidate_focus_schema_and_serialization_keep_nullable_default() -> None:
    snapshot = ConversationSnapshot(
        session_id="single-candidate-no-inferred-focus",
        version=1,
        query_context=query_context(),
        candidates=[candidate(91, 1)],
    )
    field_schema = ConversationSnapshot.model_json_schema()[
        "properties"
    ]["focused_candidate_ordinal"]

    assert snapshot.focused_candidate_ordinal is None
    assert snapshot.model_dump(mode="json")[
        "focused_candidate_ordinal"
    ] is None
    assert field_schema["default"] is None
    assert field_schema["anyOf"] == [
        {
            "maximum": 4,
            "minimum": 1,
            "type": "integer",
        },
        {"type": "null"},
    ]


@pytest.mark.parametrize(
    ("candidates", "focus"),
    [
        ([candidate(91, 1)], 2),
        ([candidate(91, 1)], 0),
        ([candidate(91, 1)], True),
        ([candidate(91, 1)], "1"),
        ([], 1),
    ],
)
def test_candidate_focus_rejects_invalid_or_absent_candidate_authority(
    candidates: list[DisplayedCandidateRef],
    focus: object,
) -> None:
    with pytest.raises(ValidationError):
        ConversationSnapshot(
            session_id="invalid-candidate-focus",
            version=1,
            has_image_delivery=not candidates,
            query_context=query_context() if candidates else None,
            candidates=candidates,
            focused_candidate_ordinal=focus,
        )


def test_consultation_snapshot_needs_no_fake_recommendation_state() -> None:
    snapshot = ConversationSnapshot(
        session_id="consultation-only",
        version=1,
        query_context=None,
        candidates=[],
        consultation=consultation(),
    )

    assert snapshot.query_context is None
    assert snapshot.candidates == ()
    assert snapshot.consultation == consultation()


def _dynamic_observation(
    observation_id: str,
    *,
    dimension: str,
    source_text: str,
    source_turn_id: str,
    location: str | None = None,
) -> ConsultationObservation:
    return ConsultationObservation.model_validate(
        {
            "code": None,
            "answer": None,
            "observation_id": observation_id,
            "dimension": dimension,
            "state": "present",
            "location": location,
            "trigger": None,
            "duration": None,
            "severity": None,
            "source_text": source_text,
            "source_turn_id": source_turn_id,
        },
        strict=True,
    )


def test_dynamic_consultation_can_start_with_multiple_observations() -> None:
    replacement = ConversationSnapshot(
        session_id="dynamic-consultation-start",
        version=1,
        consultation=ConsultationSubstate(
            started_at_conversation_version=1,
            observations=(
                _dynamic_observation(
                    "obs_oil",
                    dimension="oiliness",
                    source_text="一会油",
                    source_turn_id="turn_dynamic_state_0001",
                ),
                _dynamic_observation(
                    "obs_dry",
                    dimension="dryness",
                    source_text="一会干",
                    source_turn_id="turn_dynamic_state_0001",
                ),
            ),
        ),
    )

    validate_conversation_state_transition(None, replacement)


def test_dynamic_consultation_replaces_dimension_and_keeps_other_facts(
) -> None:
    first = ConversationSnapshot(
        session_id="dynamic-consultation-correction",
        version=1,
        consultation=ConsultationSubstate(
            started_at_conversation_version=1,
            observations=(
                _dynamic_observation(
                    "obs_oil",
                    dimension="oiliness",
                    location="t_zone",
                    source_text="额头和鼻子都会油",
                    source_turn_id="turn_dynamic_state_0002",
                ),
                _dynamic_observation(
                    "obs_dry",
                    dimension="dryness",
                    source_text="脸颊会干",
                    source_turn_id="turn_dynamic_state_0002",
                ),
            ),
        ),
    )
    corrected_oil = _dynamic_observation(
        "obs_oil_correction",
        dimension="oiliness",
        location="nose",
        source_text="只有鼻子会油",
        source_turn_id="turn_dynamic_state_0003",
    )
    corrected = first.model_copy(
        update={
            "version": 2,
            "consultation": ConsultationSubstate(
                started_at_conversation_version=1,
                observations=(
                    first.consultation.observations[1],
                    corrected_oil,
                    _dynamic_observation(
                        "obs_red",
                        dimension="redness",
                        source_text="换季会红",
                        source_turn_id="turn_dynamic_state_0003",
                    ),
                ),
            ),
        },
        deep=True,
    )

    validate_conversation_state_transition(first, corrected)

    dropped = corrected.model_copy(
        update={
            "version": 3,
            "consultation": ConsultationSubstate(
                started_at_conversation_version=1,
                observations=(corrected_oil,),
            ),
        },
        deep=True,
    )
    with pytest.raises(ValueError, match="without replacement"):
        validate_conversation_state_transition(corrected, dropped)


def test_dynamic_correction_may_keep_observation_id_with_new_source() -> None:
    first = ConversationSnapshot(
        session_id="dynamic-consultation-stable-id",
        version=1,
        consultation=ConsultationSubstate(
            started_at_conversation_version=1,
            observations=(
                _dynamic_observation(
                    "obs_oiliness",
                    dimension="oiliness",
                    location="t_zone",
                    source_text="鼻子额头都会油",
                    source_turn_id="turn_dynamic_state_0004",
                ),
            ),
        ),
    )
    corrected = first.model_copy(
        update={
            "version": 2,
            "consultation": ConsultationSubstate(
                started_at_conversation_version=1,
                observations=(
                    _dynamic_observation(
                        "obs_oiliness",
                        dimension="oiliness",
                        location="nose",
                        source_text="鼻子比额头更油",
                        source_turn_id="turn_dynamic_state_0005",
                    ),
                ),
            ),
        },
        deep=True,
    )

    validate_conversation_state_transition(first, corrected)


def test_snapshot_persists_session_profile_without_fake_task_state() -> None:
    profile = reduce_session_profile(
        previous=SessionProfile(),
        updates=(
            BaseSkinUpdate(
                value="combination",
                confirmation="confirmed",
            ),
            StableTendencyUpdate(
                value="sensitivity",
                confirmation="confirmed",
            ),
        ),
        subject_scope="self",
        source_turn_id="turn_session_profile_snapshot_0001",
        conversation_version=1,
    ).profile
    snapshot = ConversationSnapshot(
        session_id="session-profile-only",
        version=1,
        session_profile=profile,
    )

    assert snapshot.session_profile == profile
    assert ConversationSnapshot.model_validate_json(
        snapshot.model_dump_json()
    ) == snapshot


def test_snapshot_accepts_typed_clarification_only_state() -> None:
    snapshot = ConversationSnapshot(
        session_id="clarification-only",
        version=1,
        clarification=ClarificationProgress(
            gap=ClarificationCode.TOPIC,
            attempts=1,
        ),
    )

    assert snapshot.query_context is None
    assert snapshot.candidates == ()
    assert snapshot.clarification.gap is ClarificationCode.TOPIC
    assert snapshot.clarification.attempts == 1


def test_snapshot_persists_complete_pending_budget_turn() -> None:
    pending = PendingTurn(
        kind="clarification",
        gap=ClarificationCode.BUDGET,
        attempts=1,
        source_conversation_version=0,
        source_message="干敏肌想要抗初老精华，预算1000左右",
        expected_response="confirm_or_correct",
        resume_mode="recommendation",
        resume_context=PendingRecommendationContext(
            category="serum",
            skin="dry",
            efficacy="anti_aging",
            exclusions=("酒精",),
        ),
        proposed_budget=PendingBudgetRange(
            minimum=Decimal("900"),
            maximum=Decimal("1100"),
        ),
    )
    snapshot = ConversationSnapshot(
        session_id="pending-budget",
        version=1,
        pending_turn=pending,
    )

    assert snapshot.pending_turn == pending
    assert snapshot.pending_turn.source_message.startswith("干敏肌")
    assert snapshot.pending_turn.proposed_budget.maximum == Decimal(
        "1100"
    )


def test_pending_budget_turn_rejects_mismatched_or_invalid_payloads() -> None:
    context = PendingRecommendationContext(category="serum")

    with pytest.raises(ValidationError, match="budget gap"):
        PendingTurn(
            gap=ClarificationCode.GOAL,
            attempts=1,
            source_conversation_version=0,
            source_message="帮我选",
            expected_response="confirm_or_correct",
            resume_mode="recommendation",
            resume_context=context,
            proposed_budget=PendingBudgetRange(
                minimum=Decimal("900"),
                maximum=Decimal("1100"),
            ),
        )
    with pytest.raises(ValidationError, match="minimum"):
        PendingBudgetRange(
            minimum=Decimal("1100"),
            maximum=Decimal("900"),
        )
    with pytest.raises(ValidationError):
        PendingTurn(
            gap=ClarificationCode.BUDGET,
            attempts=3,
            source_conversation_version=0,
            source_message="预算1000左右",
            expected_response="confirm_or_correct",
            resume_mode="recommendation",
            resume_context=context,
            proposed_budget=PendingBudgetRange(
                minimum=Decimal("900"),
                maximum=Decimal("1100"),
            ),
        )


def test_pending_budget_range_accepts_one_sided_bound() -> None:
    maximum_only = PendingBudgetRange(
        minimum=None,
        maximum=Decimal("500"),
    )
    minimum_only = PendingBudgetRange(
        minimum=Decimal("500"),
        maximum=None,
    )

    assert maximum_only.maximum == Decimal("500")
    assert maximum_only.minimum is None
    assert minimum_only.minimum == Decimal("500")
    assert minimum_only.maximum is None


def test_pending_turn_transition_preserves_original_task_and_advances_attempt(
) -> None:
    pending = PendingTurn(
        gap=ClarificationCode.BUDGET,
        attempts=1,
        source_conversation_version=0,
        source_message="干敏肌想要抗初老精华，预算1000左右",
        expected_response="confirm_or_correct",
        resume_mode="recommendation",
        resume_context=PendingRecommendationContext(
            category="serum",
            skin="dry",
            efficacy="anti_aging",
        ),
        proposed_budget=PendingBudgetRange(
            minimum=Decimal("900"),
            maximum=Decimal("1100"),
        ),
    )
    first = ConversationSnapshot(
        session_id="pending-transition",
        version=1,
        pending_turn=pending,
    )
    second = first.model_copy(
        update={
            "version": 2,
            "pending_turn": pending.model_copy(
                update={"attempts": 2}
            ),
        },
        deep=True,
    )

    validate_conversation_state_transition(first, second)

    mutated = second.model_copy(
        update={
            "version": 3,
            "pending_turn": second.pending_turn.model_copy(
                update={"source_message": "覆盖原任务"}
            ),
        },
        deep=True,
    )
    with pytest.raises(ValueError, match="source data"):
        validate_conversation_state_transition(second, mutated)


@pytest.mark.parametrize("attempts", [0, 3, True, "1"])
def test_clarification_progress_is_strict_and_bounded(
    attempts: object,
) -> None:
    with pytest.raises(ValidationError):
        ClarificationProgress(
            gap=ClarificationCode.TOPIC,
            attempts=attempts,
        )


@pytest.mark.parametrize("gap", [None, "unresolved", "topic"])
def test_clarification_progress_requires_closed_typed_gap(
    gap: object,
) -> None:
    with pytest.raises(ValidationError):
        ClarificationProgress(gap=gap, attempts=1)


def test_clarification_transition_advances_same_gap_and_resets_new_gap(
) -> None:
    first = ConversationSnapshot(
        session_id="clarification-transition",
        version=1,
        clarification=ClarificationProgress(
            gap=ClarificationCode.TOPIC,
            attempts=1,
        ),
    )
    second = first.model_copy(
        update={
            "version": 2,
            "clarification": ClarificationProgress(
                gap=ClarificationCode.TOPIC,
                attempts=2,
            ),
        },
        deep=True,
    )
    changed = second.model_copy(
        update={
            "version": 3,
            "clarification": ClarificationProgress(
                gap=ClarificationCode.BUDGET,
                attempts=1,
            ),
        },
        deep=True,
    )

    validate_conversation_state_transition(first, second)
    validate_conversation_state_transition(second, changed)

    invalid_reset = second.model_copy(
        update={
            "version": 3,
            "clarification": ClarificationProgress(
                gap=ClarificationCode.BUDGET,
                attempts=2,
            ),
        },
        deep=True,
    )
    with pytest.raises(ValueError, match="new clarification gap"):
        validate_conversation_state_transition(second, invalid_reset)


def test_snapshot_represents_collection_provisional_and_confirmation(
) -> None:
    from app.guide.application.consultation_assessment import (
        assess_consultation,
    )
    from app.guide.application.consultation_confirmation import (
        confirm_provisional_conclusion,
        record_provisional_conclusion,
    )

    collecting = consultation()
    assessment = assess_consultation(
        collecting,
        current_conversation_version=1,
        conclusion_source_turn_id="turn_assessment_000001",
    )
    provisional = record_provisional_conclusion(
        collecting,
        current_conversation_version=1,
        assessment=assessment.confirmable_assessment,
    )
    confirmed = confirm_provisional_conclusion(
        provisional.next_consultation,
        current_conversation_version=2,
        message="我确认是干性肤质",
        source_turn_id="turn_confirm_00000001",
        expected_skin_target="dry",
        expected_conclusion_source_turn_id="turn_assessment_000001",
    )

    snapshots = (
        ConversationSnapshot(
            session_id="consultation-phases",
            version=1,
            query_context=None,
            candidates=[],
            consultation=collecting,
        ),
        ConversationSnapshot(
            session_id="consultation-phases",
            version=2,
            query_context=None,
            candidates=[],
            consultation=provisional.next_consultation,
        ),
        ConversationSnapshot(
            session_id="consultation-phases",
            version=3,
            query_context=None,
            candidates=[],
            consultation=confirmed.next_consultation,
        ),
    )

    assert snapshots[0].consultation.confirmable_assessment is None
    assert (
        snapshots[1].consultation.confirmable_assessment is not None
    )
    assert (
        snapshots[1]
        .consultation.confirmable_assessment.conclusion.confirmed_by_user
        is False
    )
    assert (
        snapshots[2]
        .consultation.confirmable_assessment.conclusion.confirmed_by_user
        is True
    )
    assert all(snapshot.candidates == () for snapshot in snapshots)


def test_consultation_substate_is_deeply_immutable() -> None:
    state = consultation()

    with pytest.raises(AttributeError):
        state.observations.append(
            ConsultationObservation(
                code="t_zone_oiliness",
                answer="no",
                source_turn_id="turn_0000000000000002",
            )
        )
    with pytest.raises(ValidationError):
        state.observations[0].answer = "no"


def test_recommendation_snapshot_is_deeply_immutable_and_breaks_list_aliases(
) -> None:
    exclusion_input = ["酒精"]
    efficacy_input = ["修护"]
    context = RecommendationQueryContext(
        category="serum",
        budget_minimum=None,
        budget_maximum=Decimal("500"),
        skin="sensitive",
        efficacy="repair",
        exclusions=exclusion_input,
    )
    reference = DisplayedCandidateRef(
        product_id=91,
        ordinal=1,
        skin_match="matched",
        matched_efficacies=efficacy_input,
    )
    candidate_input = [reference]
    snapshot = ConversationSnapshot(
        session_id="immutable-recommendation",
        version=1,
        query_context=context,
        candidates=candidate_input,
        consultation=consultation(),
    )

    exclusion_input.append("香精")
    efficacy_input.append("保湿")
    candidate_input.append(candidate(38, 2))

    assert context.exclusions == ("酒精",)
    assert reference.matched_efficacies == ("修护",)
    assert snapshot.candidates == (reference,)
    with pytest.raises(ValidationError):
        snapshot.version = 2
    with pytest.raises(AttributeError):
        snapshot.candidates.append(candidate(38, 2))
    with pytest.raises(ValidationError):
        context.category = "sunscreen"
    with pytest.raises(AttributeError):
        context.exclusions.append("香精")
    with pytest.raises(ValidationError):
        reference.product_id = 38
    with pytest.raises(AttributeError):
        reference.matched_efficacies.append("保湿")


def test_recommendation_snapshot_json_keeps_sequences_list_shaped() -> None:
    snapshot = ConversationSnapshot(
        session_id="json-recommendation",
        version=1,
        query_context=query_context(),
        candidates=[candidate(91, 1)],
    )

    payload = snapshot.model_dump(mode="json")

    assert isinstance(payload["query_context"]["exclusions"], list)
    assert isinstance(payload["candidates"], list)
    assert isinstance(
        payload["candidates"][0]["matched_efficacies"],
        list,
    )


def test_snapshot_requires_positive_version() -> None:
    with pytest.raises(ValidationError):
        ConversationSnapshot(
            session_id="session-1",
            version=0,
            query_context=query_context(),
            candidates=[candidate(91, 1)],
        )


def test_snapshot_accepts_four_visible_candidates_and_rejects_five(
) -> None:
    snapshot = ConversationSnapshot(
        session_id="session-1",
        version=1,
        query_context=query_context(),
        candidates=[
            candidate(1, 1),
            candidate(2, 2),
            candidate(3, 3),
            candidate(4, 4),
        ],
    )

    assert [item.ordinal for item in snapshot.candidates] == [1, 2, 3, 4]

    with pytest.raises(ValidationError) as caught:
        ConversationSnapshot(
            session_id="session-1",
            version=1,
            query_context=query_context(),
            candidates=[
                candidate(1, 1),
                candidate(2, 2),
                candidate(3, 3),
                candidate(4, 4),
                candidate(5, 4),
            ],
        )

    assert caught.value.errors()[0]["type"] == "too_long"


def test_displayed_candidate_rejects_ordinal_five() -> None:
    with pytest.raises(ValidationError):
        candidate(5, 5)


def test_query_context_keeps_only_normalized_decision_constraints() -> None:
    context = RecommendationQueryContext(
        category="serum",
        budget_minimum=None,
        budget_maximum=Decimal("500"),
        skin="sensitive",
        efficacy="repair",
        exclusions=["酒精"],
    )

    assert context.category == "serum"
    assert context.budget_maximum == Decimal("500")
    assert context.skin == "sensitive"
    assert context.efficacy == "repair"
    assert context.exclusions == ("酒精",)


@pytest.mark.parametrize("topic", list(TopicCode))
def test_query_context_accepts_every_topic_in_strict_json_round_trip(
    topic: TopicCode,
) -> None:
    context = RecommendationQueryContext(
        category=topic.value,
        budget_minimum=None,
        budget_maximum=None,
        skin=None,
        efficacy=None,
        exclusions=[],
    )

    restored = RecommendationQueryContext.model_validate_json(
        context.model_dump_json()
    )

    assert restored.category == topic.value
    assert restored == context


@pytest.mark.parametrize("category", ["foundation", 1, True])
def test_query_context_rejects_unknown_or_non_string_category(
    category: object,
) -> None:
    with pytest.raises(ValidationError):
        RecommendationQueryContext(
            category=category,
            budget_minimum=None,
            budget_maximum=None,
            skin=None,
            efficacy=None,
            exclusions=[],
        )


def test_query_context_allows_no_budget_but_rejects_invalid_bounds() -> None:
    no_budget = RecommendationQueryContext(
        category="sunscreen",
        budget_minimum=None,
        budget_maximum=None,
        skin=None,
        efficacy=None,
        exclusions=[],
    )
    assert no_budget.budget_maximum is None

    with pytest.raises(ValidationError, match="budget"):
        RecommendationQueryContext(
            category="serum",
            budget_minimum=None,
            budget_maximum=Decimal("0"),
            skin="sensitive",
            efficacy="repair",
            exclusions=[],
        )
    with pytest.raises(ValidationError, match="budget"):
        RecommendationQueryContext(
            category="serum",
            budget_minimum=Decimal("500"),
            budget_maximum=Decimal("100"),
            skin="sensitive",
            efficacy="repair",
            exclusions=[],
        )


def test_query_context_rejects_duplicate_or_empty_exclusions() -> None:
    with pytest.raises(ValidationError, match="exclusions"):
        RecommendationQueryContext(
            category="sunscreen",
            budget_minimum=None,
            budget_maximum=None,
            skin=None,
            efficacy=None,
            exclusions=["酒精", "酒精"],
        )
    with pytest.raises(ValidationError):
        RecommendationQueryContext(
            category="sunscreen",
            budget_minimum=None,
            budget_maximum=None,
            skin=None,
            efficacy=None,
            exclusions=[""],
        )


@pytest.mark.parametrize(
    "forbidden_field",
    ["raw_message", "candidate_ids", "product_facts", "score"],
)
def test_query_context_rejects_raw_or_privileged_fields(
    forbidden_field: str,
) -> None:
    payload = {
        "category": "serum",
        "budget_minimum": None,
        "budget_maximum": Decimal("500"),
        "skin": "sensitive",
        "efficacy": "repair",
        "exclusions": [],
        forbidden_field: "not allowed",
    }

    with pytest.raises(
        ValidationError,
        match="Extra inputs are not permitted",
    ):
        RecommendationQueryContext.model_validate(payload)


def test_snapshot_requires_query_context() -> None:
    with pytest.raises(ValidationError, match="query_context"):
        ConversationSnapshot(
            session_id="session-1",
            version=1,
            candidates=[candidate(91, 1)],
        )
