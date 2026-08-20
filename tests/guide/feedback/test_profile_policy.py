from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.guide.feedback.profile_contracts import (
    ConfirmedProfileFact,
    ProfileOwnerRef,
)
from app.guide.feedback.profile_state import ProfileSnapshot


_OWNER = ProfileOwnerRef(
    scope="local_demo",
    subject_id="profile_0123456789abcdef",
)
_CONFIRMED_AT = datetime(2026, 8, 9, 3, 0, tzinfo=UTC)


def _profile_fact(
    *,
    field: str = "skin_type",
    value: str = "sensitive",
    source_turn_id: str = "turn_profile_00000001",
    source_kind: str = "confirmed_consultation",
    profile_version: int = 1,
) -> ConfirmedProfileFact:
    return ConfirmedProfileFact(
        owner=_OWNER,
        field=field,
        value=value,
        source_turn_id=source_turn_id,
        source_kind=source_kind,
        confirmed_at=_CONFIRMED_AT,
        profile_version=profile_version,
    )


def _source_inputs(
    source: str,
    *,
    field: str = "skin_type",
    value: str,
) -> dict[str, object]:
    from app.guide.feedback.profile_policy import (
        ConfirmedSessionFact,
        CurrentExplicitFact,
        DefaultProfileFact,
    )

    if source == "current_explicit_input":
        return {
            "current_explicit": [
                CurrentExplicitFact(
                    field=field,
                    value=value,
                    source_turn_id="turn_current_00000001",
                )
            ]
        }
    if source == "confirmed_session_fact":
        return {
            "confirmed_session": [
                ConfirmedSessionFact(
                    field=field,
                    value=value,
                    source_turn_id="turn_session_00000001",
                    source_kind="confirmed_consultation",
                )
            ]
        }
    if source == "long_term_profile":
        return {
            "profile": ProfileSnapshot(
                owner=_OWNER,
                version=1,
                facts=[_profile_fact(value=value)],
            )
        }
    if source == "default":
        return {
            "defaults": [
                DefaultProfileFact(field=field, value=value)
            ]
        }
    raise AssertionError(f"unsupported source: {source}")


def _resolve(**overrides: object):
    from app.guide.feedback.profile_policy import resolve_profile_context

    inputs: dict[str, object] = {
        "current_explicit": [],
        "confirmed_session": [],
        "profile": None,
        "defaults": [],
    }
    inputs.update(overrides)
    return resolve_profile_context(**inputs)


@pytest.mark.parametrize(
    ("higher", "lower"),
    [
        ("current_explicit_input", "confirmed_session_fact"),
        ("current_explicit_input", "long_term_profile"),
        ("current_explicit_input", "default"),
        ("confirmed_session_fact", "long_term_profile"),
        ("confirmed_session_fact", "default"),
        ("long_term_profile", "default"),
    ],
)
def test_resolution_precedence_prefers_higher_conflicting_source(
    higher: str,
    lower: str,
) -> None:
    result = _resolve(
        **{
            **_source_inputs(lower, value=f"{lower}-value"),
            **_source_inputs(higher, value=f"{higher}-value"),
        }
    )

    assert [
        (item.field, item.value, item.source)
        for item in result.values
    ] == [("skin_type", f"{higher}-value", higher)]


@pytest.mark.parametrize(
    ("source", "turn_id", "kind", "version"),
    [
        (
            "current_explicit_input",
            "turn_current_00000001",
            "explicit_user",
            None,
        ),
        (
            "confirmed_session_fact",
            "turn_session_00000001",
            "confirmed_consultation",
            None,
        ),
        (
            "long_term_profile",
            "turn_profile_00000001",
            "confirmed_consultation",
            1,
        ),
        ("default", None, None, None),
    ],
)
def test_resolution_preserves_source_provenance(
    source: str,
    turn_id: str | None,
    kind: str | None,
    version: int | None,
) -> None:
    resolved = _resolve(
        **_source_inputs(source, value=f"{source}-value")
    ).values[0]

    assert resolved.source == source
    assert resolved.provenance.source_turn_id == turn_id
    assert resolved.provenance.source_kind == kind
    assert resolved.provenance.profile_version == version


def test_profile_and_defaults_fill_only_missing_fields() -> None:
    from app.guide.feedback.profile_policy import (
        ConfirmedSessionFact,
        CurrentExplicitFact,
        DefaultProfileFact,
    )

    profile = ProfileSnapshot(
        owner=_OWNER,
        version=2,
        facts=[
            _profile_fact(),
            _profile_fact(
                field="preferred_brand",
                value="CeraVe",
                source_turn_id="turn_profile_brand_001",
                source_kind="explicit_user",
                profile_version=2,
            ),
        ],
    )
    before = profile.model_dump(mode="json")

    result = _resolve(
        current_explicit=[
            CurrentExplicitFact(
                field="skin_type",
                value="dry",
                source_turn_id="turn_current_00000001",
            )
        ],
        confirmed_session=[
            ConfirmedSessionFact(
                field="skin_concern",
                value="redness",
                source_turn_id="turn_session_00000001",
                source_kind="confirmed_consultation",
            )
        ],
        profile=profile,
        defaults=[
            DefaultProfileFact(field="skin_type", value="normal"),
            DefaultProfileFact(field="skin_concern", value="none"),
            DefaultProfileFact(field="preferred_brand", value="none"),
            DefaultProfileFact(
                field="preferred_category",
                value="sunscreen",
            ),
        ],
    )

    assert [
        (item.field, item.value, item.source)
        for item in result.values
    ] == [
        ("skin_type", "dry", "current_explicit_input"),
        ("skin_concern", "redness", "confirmed_session_fact"),
        ("preferred_brand", "CeraVe", "long_term_profile"),
        ("preferred_category", "sunscreen", "default"),
    ]
    assert profile.model_dump(mode="json") == before


def test_missing_sources_leave_context_empty_and_immutable() -> None:
    assert _resolve().values == ()
    result = _resolve(
        **_source_inputs("current_explicit_input", value="sensitive")
    )

    assert isinstance(result.values, tuple)
    with pytest.raises(AttributeError):
        result.values.append(result.values[0])
    with pytest.raises(ValidationError, match="frozen"):
        result.values[0].value = "dry"


def test_resolved_context_preserves_unique_and_max_invariants() -> None:
    from app.guide.feedback.profile_policy import (
        ResolvedProfileContext,
        ResolvedProfileValue,
        ResolvedValueProvenance,
    )

    value = ResolvedProfileValue(
        field="skin_type",
        value="sensitive",
        source="default",
        provenance=ResolvedValueProvenance(),
    )
    with pytest.raises(ValidationError, match="unique"):
        ResolvedProfileContext(values=(value, value))
    with pytest.raises(ValidationError):
        ResolvedProfileContext(values=(value,) * 6)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("budget", "500"),
        ("price", "299"),
        ("recurrent_redness", "yes"),
        ("post_cleanse_tightness", "sometimes"),
    ],
)
def test_non_profile_labels_are_not_representable(
    field: str,
    value: str,
) -> None:
    from app.guide.feedback.profile_policy import CurrentExplicitFact

    with pytest.raises(ValidationError):
        CurrentExplicitFact(
            field=field,
            value=value,
            source_turn_id="turn_pollution_000001",
        )
