from __future__ import annotations

from app.guide.adapters.state import InMemoryConversationState
from app.guide.application.consultation_coordinator import (
    ConsultationApplicationCoordinator,
)
from app.guide.application.consultation_chat_flow import (
    ConsultationChatFlow,
)
from app.guide.application.dynamic_consultation import (
    advance_dynamic_consultation,
)
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.understanding.turn_meaning_contracts import TurnMeaning


_OWNER = ProfileOwnerRef(
    scope="anonymous_browser",
    subject_id="dynamic_consultation_owner_0123456789",
)


def _meaning(
    *,
    observations: tuple[dict[str, object], ...],
    base_skin: str | None = None,
    tendencies: tuple[str, ...] = (),
    conditions: tuple[str, ...] = (),
    support: tuple[str, ...] = (),
    next_gap: str | None = None,
) -> TurnMeaning:
    return TurnMeaning.model_validate(
        {
            "operation_hint": "assessment",
            "topic_hint": "skincare",
            "continuity_hint": "continue",
            "subject_scope_hint": "self",
            "reference_mentions": [],
            "product_mentions": [],
            "budget_candidates": [],
            "observation_candidates": observations,
            "preference_candidates": [],
            "relative_candidates": [],
            "consultation_hypothesis": (
                {
                    "base_skin_direction": base_skin,
                    "stable_tendencies": list(tendencies),
                    "current_conditions": list(conditions),
                    "supporting_observation_ids": list(support),
                }
                if base_skin is not None or tendencies or conditions
                else None
            ),
            "next_observation_gap": next_gap,
            "question_meaning": "动态轻问诊",
            "safety_language": "ordinary",
        },
        strict=True,
    )


def _observation(
    observation_id: str,
    *,
    code: str,
    raw_text: str,
    location: str | None = None,
    trigger: str | None = None,
    duration: str | None = None,
    severity: str | None = None,
    present: bool = True,
) -> dict[str, object]:
    return {
        "observation_id": observation_id,
        "code": code,
        "present": present,
        "qualifier": None,
        "raw_text": raw_text,
        "location": location,
        "trigger": trigger,
        "duration": duration,
        "severity": severity,
    }


def test_multi_observation_turn_asks_one_largest_gap() -> None:
    message = "一会油一会干，换季还红"
    result = advance_dynamic_consultation(
        previous=None,
        message=message,
        meaning=_meaning(
            observations=(
                _observation(
                    "obs_oil",
                    code="oiliness",
                    raw_text="一会油",
                ),
                _observation(
                    "obs_dry",
                    code="dryness",
                    raw_text="一会干",
                ),
                _observation(
                    "obs_red",
                    code="redness",
                    raw_text="换季还红",
                    trigger="seasonal",
                ),
            ),
            base_skin="combination",
            conditions=("redness",),
            support=("obs_oil", "obs_dry", "obs_red"),
            next_gap="location",
        ),
        source_turn_id="turn_dynamic_consultation_0001",
        conversation_version=1,
    )

    assert len(result.observations) == 3
    assert result.conclusion is not None
    assert result.conclusion.skin_target == "combination"
    assert result.next_gap == "location"
    assert result.next_question is not None
    assert "哪里容易出油" in result.next_question.prompt
    assert result.ready_for_confirmation is False


def test_followup_uses_new_locations_and_moves_to_trigger_gap() -> None:
    first = advance_dynamic_consultation(
        previous=None,
        message="一会油一会干",
        meaning=_meaning(
            observations=(
                _observation(
                    "obs_oil",
                    code="oiliness",
                    raw_text="一会油",
                ),
                _observation(
                    "obs_dry",
                    code="dryness",
                    raw_text="一会干",
                ),
            ),
            base_skin="combination",
            support=("obs_oil", "obs_dry"),
            next_gap="location",
        ),
        source_turn_id="turn_dynamic_consultation_0002",
        conversation_version=1,
    )
    second = advance_dynamic_consultation(
        previous=first.next_consultation,
        message="下午鼻子额头油，两颊洗完紧",
        meaning=_meaning(
            observations=(
                _observation(
                    "obs_oil_location",
                    code="oiliness",
                    raw_text="下午鼻子额头油",
                    location="t_zone",
                    duration="recurrent",
                ),
                _observation(
                    "obs_tight_cheeks",
                    code="tightness",
                    raw_text="两颊洗完紧",
                    location="cheeks",
                    trigger="post_cleanse",
                    duration="recurrent",
                ),
            ),
            base_skin="combination",
            support=(
                "obs_oil_location",
                "obs_tight_cheeks",
            ),
            next_gap="persistence_or_trigger",
        ),
        source_turn_id="turn_dynamic_consultation_0003",
        conversation_version=2,
    )

    assert second.conclusion is not None
    assert second.conclusion.skin_target == "combination"
    assert second.next_gap == "persistence_or_trigger"
    assert second.next_question is not None
    assert "什么时候更容易泛红或刺痛" in (
        second.next_question.prompt
    )


def test_known_oily_and_dry_locations_close_stale_location_gap() -> None:
    first = advance_dynamic_consultation(
        previous=None,
        message="一会油一会干",
        meaning=_meaning(
            observations=(
                _observation(
                    "obs_oil",
                    code="oiliness",
                    raw_text="一会油",
                ),
                _observation(
                    "obs_dry",
                    code="dryness",
                    raw_text="一会干",
                ),
            ),
            base_skin="combination",
            support=("obs_oil", "obs_dry"),
            next_gap="location",
        ),
        source_turn_id="turn_dynamic_consultation_0011",
        conversation_version=1,
    )
    second = advance_dynamic_consultation(
        previous=first.next_consultation,
        message="鼻子额头会油，两颊洗完会紧",
        meaning=_meaning(
            observations=(
                _observation(
                    "obs_oil_location",
                    code="oiliness",
                    raw_text="鼻子额头会油",
                    location="t_zone",
                ),
                _observation(
                    "obs_tight_cheeks",
                    code="tightness",
                    raw_text="两颊洗完会紧",
                    location="cheeks",
                ),
            ),
            base_skin="combination",
            support=(
                "obs_oil_location",
                "obs_tight_cheeks",
            ),
            next_gap="location",
        ),
        source_turn_id="turn_dynamic_consultation_0012",
        conversation_version=2,
    )

    assert second.next_gap == "persistence_or_trigger"


def test_same_turn_prefers_present_location_over_absent_same_dimension() -> None:
    result = advance_dynamic_consultation(
        previous=None,
        message="只有鼻子明显出油，额头并不怎么油",
        meaning=_meaning(
            observations=(
                _observation(
                    "obs_oil_nose",
                    code="oiliness",
                    raw_text="鼻子明显出油",
                    location="nose",
                ),
                _observation(
                    "obs_oil_forehead_absent",
                    code="oiliness",
                    raw_text="额头并不怎么油",
                    location="forehead",
                    present=False,
                ),
            ),
            next_gap="ordinary_product_tolerance",
        ),
        source_turn_id="turn_dynamic_consultation_0013",
        conversation_version=1,
    )

    oiliness = [
        item
        for item in result.observations
        if item.dimension == "oiliness"
    ]
    assert len(oiliness) == 1
    assert oiliness[0].state == "present"
    assert oiliness[0].location == "nose"


def test_confirmation_requires_supported_direction_and_safety_status() -> None:
    result = advance_dynamic_consultation(
        previous=None,
        message="鼻子额头容易油，两颊洗完会紧，平时保湿不痛，也没有红肿破损",
        meaning=_meaning(
            observations=(
                _observation(
                    "obs_oil",
                    code="oiliness",
                    raw_text="鼻子额头容易油",
                    location="t_zone",
                    duration="recurrent",
                ),
                _observation(
                    "obs_tight",
                    code="tightness",
                    raw_text="两颊洗完会紧",
                    location="cheeks",
                    trigger="post_cleanse",
                ),
                _observation(
                    "obs_tolerance",
                    code="product_tolerance",
                    raw_text="平时保湿不痛",
                    present=False,
                ),
                _observation(
                    "obs_damage",
                    code="broken_skin",
                    raw_text="没有红肿破损",
                    present=False,
                ),
            ),
            base_skin="combination",
            support=("obs_oil", "obs_tight"),
            next_gap="confirmation",
        ),
        source_turn_id="turn_dynamic_consultation_0004",
        conversation_version=3,
    )

    assert result.conclusion is not None
    assert result.conclusion.skin_target == "combination"
    assert result.ready_for_confirmation
    assert result.next_question is not None
    assert "更接近混合性肤质" in result.next_question.prompt


def test_correction_replaces_matching_observation_not_contradiction() -> None:
    first = advance_dynamic_consultation(
        previous=None,
        message="额头和鼻子都会油",
        meaning=_meaning(
            observations=(
                _observation(
                    "obs_oil",
                    code="oiliness",
                    raw_text="额头和鼻子都会油",
                    location="t_zone",
                ),
            ),
            next_gap="location",
        ),
        source_turn_id="turn_dynamic_consultation_0005",
        conversation_version=1,
    )
    corrected = advance_dynamic_consultation(
        previous=first.next_consultation,
        message="纠正一下，只有鼻子会油",
        meaning=_meaning(
            observations=(
                _observation(
                    "obs_oil_correction",
                    code="oiliness",
                    raw_text="只有鼻子会油",
                    location="nose",
                ),
            ),
            next_gap="ordinary_product_tolerance",
        ),
        source_turn_id="turn_dynamic_consultation_0006",
        conversation_version=2,
    )

    oiliness = [
        item
        for item in corrected.observations
        if item.dimension == "oiliness"
    ]
    assert len(oiliness) == 1
    assert oiliness[0].location == "nose"
    assert oiliness[0].source_turn_id == (
        "turn_dynamic_consultation_0006"
    )


def test_active_breakage_escalates_from_one_source_bound_observation() -> None:
    result = advance_dynamic_consultation(
        previous=None,
        message="昨天用新精华后一直火辣辣，现在还有破皮渗出",
        meaning=_meaning(
            observations=(
                _observation(
                    "obs_burning",
                    code="burning",
                    raw_text="一直火辣辣",
                    trigger="new_product",
                    duration="persistent",
                    severity="severe",
                ),
                _observation(
                    "obs_broken",
                    code="broken_skin",
                    raw_text="破皮",
                    severity="severe",
                ),
                _observation(
                    "obs_oozing",
                    code="oozing",
                    raw_text="渗出",
                    severity="severe",
                ),
            ),
            conditions=("broken_skin", "oozing"),
            support=("obs_broken", "obs_oozing"),
            next_gap="active_damage_risk",
        ),
        source_turn_id="turn_dynamic_consultation_0007",
        conversation_version=1,
    )

    assert result.stop_skincare_advice
    assert result.next_question is None
    assert {
        item.code for item in result.escalation_triggers
    } == {"oozing"}


def test_broken_skin_alone_escalates_without_becoming_skin_type() -> None:
    result = advance_dynamic_consultation(
        previous=None,
        message="现在有一点破皮",
        meaning=_meaning(
            observations=(
                _observation(
                    "obs_broken",
                    code="broken_skin",
                    raw_text="有一点破皮",
                    severity="moderate",
                ),
            ),
            conditions=("broken_skin",),
            support=("obs_broken",),
            next_gap="active_damage_risk",
        ),
        source_turn_id="turn_dynamic_consultation_0009",
        conversation_version=1,
    )

    assert result.stop_skincare_advice
    assert result.conclusion is not None
    assert result.conclusion.skin_target is None
    assert [item.code for item in result.escalation_triggers] == [
        "broken_skin"
    ]


def test_persistent_new_product_burning_escalates_without_sensitivity() -> None:
    result = advance_dynamic_consultation(
        previous=None,
        message="昨天换新精华后一直火辣辣",
        meaning=_meaning(
            observations=(
                _observation(
                    "obs_burning",
                    code="burning",
                    raw_text="一直火辣辣",
                    trigger="new_product",
                    duration="persistent",
                    severity="severe",
                ),
            ),
            next_gap="active_damage_risk",
        ),
        source_turn_id="turn_dynamic_consultation_0010",
        conversation_version=1,
    )

    assert result.stop_skincare_advice
    assert result.stable_tendencies == ()
    assert [item.code for item in result.escalation_triggers] == [
        "persistent_burning"
    ]


def test_invented_observation_source_is_not_stored() -> None:
    result = advance_dynamic_consultation(
        previous=None,
        message="换季会泛红",
        meaning=_meaning(
            observations=(
                _observation(
                    "obs_red",
                    code="redness",
                    raw_text="换季会泛红",
                    trigger="seasonal",
                ),
                _observation(
                    "obs_invented",
                    code="stinging",
                    raw_text="刷酸会刺痛",
                    trigger="acid",
                ),
            ),
            conditions=("redness",),
            support=("obs_red",),
            next_gap="persistence_or_trigger",
        ),
        source_turn_id="turn_dynamic_consultation_0008",
        conversation_version=1,
    )

    assert [item.source_text for item in result.observations] == [
        "换季会泛红"
    ]


def test_coordinator_confirms_dynamic_profile_with_separate_tendencies(
) -> None:
    state = InMemoryConversationState()
    coordinator = ConsultationApplicationCoordinator(
        conversation_state=state,
    )
    message = (
        "鼻子额头容易油，两颊洗完会紧，平时保湿不痛，"
        "换季会红，也没有破皮"
    )
    provisional = coordinator.handle_dynamic_turn(
        session_id="dynamic-consultation-profile",
        conversation_version=0,
        message=message,
        meaning=_meaning(
            observations=(
                _observation(
                    "obs_oil",
                    code="oiliness",
                    raw_text="鼻子额头容易油",
                    location="t_zone",
                    duration="recurrent",
                ),
                _observation(
                    "obs_tight",
                    code="tightness",
                    raw_text="两颊洗完会紧",
                    location="cheeks",
                    trigger="post_cleanse",
                ),
                _observation(
                    "obs_tolerance",
                    code="product_tolerance",
                    raw_text="平时保湿不痛",
                    present=False,
                ),
                _observation(
                    "obs_red",
                    code="redness",
                    raw_text="换季会红",
                    trigger="seasonal",
                    duration="recurrent",
                ),
                _observation(
                    "obs_damage",
                    code="broken_skin",
                    raw_text="没有破皮",
                    present=False,
                ),
            ),
            base_skin="combination",
            tendencies=("seasonal_redness",),
            conditions=("redness",),
            support=(
                "obs_oil",
                "obs_tight",
                "obs_tolerance",
                "obs_red",
                "obs_damage",
            ),
            next_gap="confirmation",
        ),
        source_turn_id="turn_dynamic_coordinator_0001",
        profile_owner=_OWNER,
    )

    assert provisional.intent == "consultation_provisional"
    assert provisional.conversation_version == 1
    assert provisional.conclusion is not None
    assert provisional.conclusion.skin_target == "combination"
    assert provisional.conclusion.stable_tendencies == (
        "seasonal_redness",
    )
    assert provisional.conclusion.current_conditions == ("redness",)
    provisional_copy = ConsultationChatFlow._message(provisional)
    assert "更接近混合性肤质" in provisional_copy
    assert "换季容易泛红" in provisional_copy
    assert "当前还有泛红" in provisional_copy
    assert "观察依据与不确定项" not in provisional_copy

    confirmed = coordinator.handle_turn(
        session_id="dynamic-consultation-profile",
        conversation_version=provisional.conversation_version,
        message="我确认是混合皮",
        source_turn_id="turn_dynamic_coordinator_0002",
        profile_owner=_OWNER,
    )

    assert confirmed is not None
    assert confirmed.intent == "consultation_confirmation"
    assert confirmed.session_profile is not None
    assert confirmed.session_profile.base_skin is not None
    assert confirmed.session_profile.base_skin.value == "combination"
    assert [
        item.value
        for item in confirmed.session_profile.stable_tendencies
    ] == ["seasonal_redness"]
    assert [
        item.value
        for item in confirmed.session_profile.current_conditions
    ] == ["redness"]


def test_coordinator_records_dynamic_breakage_as_terminal_safety() -> None:
    state = InMemoryConversationState()
    coordinator = ConsultationApplicationCoordinator(
        conversation_state=state,
    )
    result = coordinator.handle_dynamic_turn(
        session_id="dynamic-consultation-safety",
        conversation_version=0,
        message="现在有一点破皮",
        meaning=_meaning(
            observations=(
                _observation(
                    "obs_broken",
                    code="broken_skin",
                    raw_text="有一点破皮",
                    severity="moderate",
                ),
            ),
            conditions=("broken_skin",),
            support=("obs_broken",),
            next_gap="active_damage_risk",
        ),
        source_turn_id="turn_dynamic_coordinator_0003",
        profile_owner=_OWNER,
    )

    assert result.intent == "consultation_medical_escalation"
    assert result.conversation_version == 1
    assert result.stop_skincare_advice
    assert [item.code for item in result.escalation_triggers] == [
        "broken_skin"
    ]
    stored = state.load("dynamic-consultation-safety")
    assert stored is not None
    assert stored.version == 1
    assert stored.consultation is not None
    assert stored.consultation.medical_escalation is not None


def test_dynamic_read_only_return_advances_conversation_version() -> None:
    state = InMemoryConversationState()
    coordinator = ConsultationApplicationCoordinator(
        conversation_state=state,
    )
    first = coordinator.handle_dynamic_turn(
        session_id="dynamic-consultation-read-only",
        conversation_version=0,
        message="洗脸后两颊会紧",
        meaning=_meaning(
            observations=(
                _observation(
                    "obs_tight",
                    code="tightness",
                    raw_text="洗脸后两颊会紧",
                    location="cheeks",
                    trigger="post_cleanse",
                ),
            ),
            support=("obs_tight",),
            next_gap="persistence_or_trigger",
        ),
        source_turn_id="turn_dynamic_coordinator_0004",
        profile_owner=_OWNER,
    )
    before = state.load("dynamic-consultation-read-only")
    assert before is not None

    returned = coordinator.handle_dynamic_turn(
        session_id="dynamic-consultation-read-only",
        conversation_version=first.conversation_version,
        message="回到刚才的判断，继续问缺的信息",
        meaning=_meaning(
            observations=(),
            next_gap="persistence_or_trigger",
        ),
        source_turn_id="turn_dynamic_coordinator_0005",
        profile_owner=_OWNER,
    )
    stored = state.load("dynamic-consultation-read-only")

    assert returned.intent == "consultation_clarification"
    assert returned.conversation_version == first.conversation_version + 1
    assert stored is not None
    assert stored.version == first.conversation_version + 1
    assert stored.consultation == before.consultation
