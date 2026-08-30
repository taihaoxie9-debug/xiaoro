from __future__ import annotations

from app.guide.feedback.contracts import ConversationSnapshot
from app.guide.feedback.profile_policy import (
    ConfirmedSessionFact,
    CurrentExplicitFact,
    ResolvedProfileContext,
    resolve_profile_context,
)
from app.guide.understanding.contracts import SkinTarget


def resolve_session_profile_context(
    snapshot: ConversationSnapshot | None,
    *,
    current_explicit_skin: SkinTarget | None = None,
    source_turn_id: str | None = None,
) -> ResolvedProfileContext:
    if snapshot is not None and type(snapshot) is not ConversationSnapshot:
        raise TypeError(
            "snapshot must be a ConversationSnapshot or None"
        )
    if current_explicit_skin is not None and not isinstance(
        current_explicit_skin,
        SkinTarget,
    ):
        raise TypeError("current_explicit_skin must be a SkinTarget")
    if (current_explicit_skin is None) != (source_turn_id is None):
        raise ValueError(
            "current explicit skin requires source turn provenance"
        )

    current_explicit = (
        (
            CurrentExplicitFact(
                field="skin_type",
                value=current_explicit_skin.value,
                source_turn_id=source_turn_id,
            ),
        )
        if current_explicit_skin is not None
        and source_turn_id is not None
        else ()
    )
    return resolve_profile_context(
        current_explicit=current_explicit,
        confirmed_session=_confirmed_session_facts(snapshot),
    )


def _confirmed_session_facts(
    snapshot: ConversationSnapshot | None,
) -> tuple[ConfirmedSessionFact, ...]:
    if snapshot is None or snapshot.session_profile is None:
        return ()
    profile = snapshot.session_profile
    facts: list[ConfirmedSessionFact] = []
    base_skin = profile.base_skin
    sensitivity = next(
        (
            item
            for item in profile.stable_tendencies
            if (
                item.value == "sensitivity"
                and item.confirmation == "confirmed"
            )
        ),
        None,
    )
    if (
        base_skin is not None
        and base_skin.confirmation == "confirmed"
        and base_skin.value != "unknown"
    ):
        facts.append(
            ConfirmedSessionFact(
                field="skin_type",
                value=(
                    "oily_sensitive"
                    if base_skin.value == "oily"
                    and sensitivity is not None
                    else base_skin.value
                ),
                source_turn_id=base_skin.source_turn_id,
                source_kind="confirmed_consultation",
            )
        )
    elif sensitivity is not None:
        facts.append(
            ConfirmedSessionFact(
                field="skin_type",
                value="sensitive",
                source_turn_id=sensitivity.source_turn_id,
                source_kind="confirmed_consultation",
            )
        )
    facts.extend(
        ConfirmedSessionFact(
            field="ingredient_exclusion",
            value=item.value,
            source_turn_id=item.source_turn_id,
            source_kind="explicit_user",
        )
        for item in profile.explicit_restrictions
    )
    return tuple(facts)


__all__ = ["resolve_session_profile_context"]
