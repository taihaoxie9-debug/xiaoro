from __future__ import annotations

from app.guide.application.session_profile_resolution import (
    resolve_session_profile_context,
)
from app.guide.feedback.contracts import ConversationSnapshot
from app.guide.feedback.session_profile import (
    BaseSkinUpdate,
    ExplicitRestrictionUpdate,
    SessionProfile,
    StableTendencyUpdate,
    reduce_session_profile,
)
from app.guide.understanding.contracts import SkinTarget


def _snapshot(*updates) -> ConversationSnapshot:
    profile = reduce_session_profile(
        previous=SessionProfile(),
        updates=updates,
        subject_scope="self",
        source_turn_id="turn_profile_resolution_0001",
        conversation_version=1,
    ).profile
    return ConversationSnapshot(
        session_id="session-profile-resolution",
        version=1,
        session_profile=profile,
    )


def test_resolves_confirmed_session_skin_without_state_store() -> None:
    context = resolve_session_profile_context(
        _snapshot(
            BaseSkinUpdate(
                value="dry",
                confirmation="confirmed",
            )
        )
    )

    assert context.model_dump(mode="python") == {
        "values": (
            {
                "field": "skin_type",
                "value": "dry",
                "source": "confirmed_session_fact",
                "provenance": {
                    "source_turn_id": "turn_profile_resolution_0001",
                    "source_kind": "confirmed_consultation",
                    "profile_version": None,
                },
            },
        )
    }


def test_combines_confirmed_oily_skin_and_sensitivity() -> None:
    context = resolve_session_profile_context(
        _snapshot(
            BaseSkinUpdate(
                value="oily",
                confirmation="confirmed",
            ),
            StableTendencyUpdate(
                value="sensitivity",
                confirmation="confirmed",
            ),
        )
    )

    assert [(item.field, item.value) for item in context.values] == [
        ("skin_type", "oily_sensitive")
    ]


def test_resolves_session_restriction_and_current_explicit_override() -> None:
    context = resolve_session_profile_context(
        _snapshot(
            BaseSkinUpdate(
                value="dry",
                confirmation="confirmed",
            ),
            ExplicitRestrictionUpdate(value="alcohol"),
        ),
        current_explicit_skin=SkinTarget.NORMAL,
        source_turn_id="turn_profile_resolution_0002",
    )

    assert [
        (item.field, item.value, item.source)
        for item in context.values
    ] == [
        ("skin_type", "normal", "current_explicit_input"),
        (
            "ingredient_exclusion",
            "alcohol",
            "confirmed_session_fact",
        ),
    ]


def test_resolves_all_confirmed_session_restrictions() -> None:
    context = resolve_session_profile_context(
        _snapshot(
            ExplicitRestrictionUpdate(value="alcohol"),
            ExplicitRestrictionUpdate(value="fragrance"),
        )
    )

    assert [
        (item.field, item.value)
        for item in context.values
    ] == [
        ("ingredient_exclusion", "alcohol"),
        ("ingredient_exclusion", "fragrance"),
    ]


def test_current_explicit_skin_requires_source_provenance() -> None:
    try:
        resolve_session_profile_context(
            None,
            current_explicit_skin=SkinTarget.DRY,
        )
    except ValueError as error:
        assert str(error) == (
            "current explicit skin requires source turn provenance"
        )
    else:
        raise AssertionError("missing provenance must be rejected")
