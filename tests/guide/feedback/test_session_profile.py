from __future__ import annotations

from app.guide.feedback.session_profile import (
    BaseSkinUpdate,
    CurrentConditionUpdate,
    ExplicitRestrictionUpdate,
    SessionProfile,
    StableTendencyUpdate,
    reduce_session_profile,
)


def _turn(index: int) -> str:
    return f"turn_session_profile_{index:04d}"


def test_explicit_self_sensitive_is_confirmed_session_tendency() -> None:
    result = reduce_session_profile(
        previous=SessionProfile(),
        updates=(
            StableTendencyUpdate(
                value="sensitivity",
                confirmation="confirmed",
            ),
        ),
        subject_scope="self",
        source_turn_id=_turn(1),
        conversation_version=1,
    )

    assert result.changed
    assert result.disposition == "updated"
    assert result.profile.base_skin is None
    assert result.profile.stable_tendencies[0].value == "sensitivity"
    assert (
        result.profile.stable_tendencies[0].confirmation
        == "confirmed"
    )
    assert result.profile.stable_tendencies[0].source_turn_id == _turn(1)


def test_current_redness_and_stinging_do_not_become_base_skin() -> None:
    result = reduce_session_profile(
        previous=SessionProfile(),
        updates=(
            CurrentConditionUpdate(value="redness"),
            CurrentConditionUpdate(value="stinging"),
        ),
        subject_scope="self",
        source_turn_id=_turn(2),
        conversation_version=4,
    )

    assert result.profile.base_skin is None
    assert result.profile.stable_tendencies == ()
    assert [
        (item.value, item.active, item.recorded_at_version)
        for item in result.profile.current_conditions
    ] == [
        ("redness", True, 4),
        ("stinging", True, 4),
    ]


def test_friend_fact_does_not_modify_self_profile() -> None:
    existing = reduce_session_profile(
        previous=SessionProfile(),
        updates=(
            BaseSkinUpdate(
                value="dry",
                confirmation="confirmed",
            ),
        ),
        subject_scope="self",
        source_turn_id=_turn(3),
        conversation_version=1,
    ).profile

    result = reduce_session_profile(
        previous=existing,
        updates=(
            StableTendencyUpdate(
                value="sensitivity",
                confirmation="confirmed",
            ),
        ),
        subject_scope="other",
        source_turn_id=_turn(4),
        conversation_version=2,
    )

    assert not result.changed
    assert result.disposition == "unchanged_other_subject"
    assert result.profile == existing


def test_correction_replaces_base_skin_and_clears_condition() -> None:
    initial = reduce_session_profile(
        previous=SessionProfile(),
        updates=(
            BaseSkinUpdate(
                value="dry",
                confirmation="provisional",
            ),
            CurrentConditionUpdate(value="redness"),
        ),
        subject_scope="self",
        source_turn_id=_turn(5),
        conversation_version=1,
    ).profile

    corrected = reduce_session_profile(
        previous=initial,
        updates=(
            BaseSkinUpdate(
                value="combination",
                confirmation="confirmed",
            ),
            CurrentConditionUpdate(
                value="redness",
                active=False,
            ),
        ),
        subject_scope="self",
        source_turn_id=_turn(6),
        conversation_version=2,
    ).profile

    assert corrected.base_skin is not None
    assert corrected.base_skin.value == "combination"
    assert corrected.base_skin.confirmation == "confirmed"
    assert corrected.base_skin.source_turn_id == _turn(6)
    assert corrected.current_conditions == ()


def test_restriction_can_be_added_and_withdrawn_losslessly() -> None:
    stored = reduce_session_profile(
        previous=SessionProfile(),
        updates=(
            ExplicitRestrictionUpdate(
                value="酒精",
                operation="set",
            ),
        ),
        subject_scope="self",
        source_turn_id=_turn(7),
        conversation_version=1,
    ).profile

    assert stored.explicit_restrictions[0].value == "酒精"
    assert stored.explicit_restrictions[0].source_turn_id == _turn(7)

    withdrawn = reduce_session_profile(
        previous=stored,
        updates=(
            ExplicitRestrictionUpdate(
                value="酒精",
                operation="remove",
            ),
        ),
        subject_scope="self",
        source_turn_id=_turn(8),
        conversation_version=2,
    )

    assert withdrawn.changed
    assert withdrawn.profile.explicit_restrictions == ()
