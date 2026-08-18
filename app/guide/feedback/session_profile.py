from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


SessionBaseSkinValue = Literal[
    "oily",
    "dry",
    "combination",
    "normal",
    "unknown",
]
StableTendency = Literal[
    "sensitivity",
    "seasonal_redness",
    "acid_triggered_irritation",
    "dehydration",
    "other",
]
CurrentCondition = Literal[
    "redness",
    "stinging",
    "flaking",
    "tightness",
    "swelling",
    "broken_skin",
    "oozing",
    "persistent_pain",
]
ConfirmationState = Literal["provisional", "confirmed"]
SubjectScope = Literal["self", "other"]
UpdateOperation = Literal["set", "remove"]
SourceTurnId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=16,
        max_length=160,
    ),
]
RestrictionValue = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
    ),
]


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class SessionBaseSkin(_StrictFrozen):
    value: SessionBaseSkinValue
    confirmation: ConfirmationState
    source_turn_id: SourceTurnId


class SessionProfileFact(_StrictFrozen):
    value: StableTendency
    confirmation: ConfirmationState
    source_turn_id: SourceTurnId


class SessionConditionFact(_StrictFrozen):
    value: CurrentCondition
    active: Literal[True] = True
    source_turn_id: SourceTurnId
    recorded_at_version: int = Field(ge=1)


class SessionRestriction(_StrictFrozen):
    value: RestrictionValue
    confirmation: Literal["confirmed"] = "confirmed"
    source_turn_id: SourceTurnId


class SessionProfile(_StrictFrozen):
    base_skin: SessionBaseSkin | None = None
    stable_tendencies: tuple[SessionProfileFact, ...] = ()
    current_conditions: tuple[SessionConditionFact, ...] = ()
    explicit_restrictions: tuple[SessionRestriction, ...] = ()

    @field_validator(
        "stable_tendencies",
        "current_conditions",
        "explicit_restrictions",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_unique_facts(self) -> Self:
        tendency_values = [
            item.value for item in self.stable_tendencies
        ]
        if len(tendency_values) != len(set(tendency_values)):
            raise ValueError("stable tendencies must be unique")
        condition_values = [
            item.value for item in self.current_conditions
        ]
        if len(condition_values) != len(set(condition_values)):
            raise ValueError("current conditions must be unique")
        restrictions = [
            item.value.casefold()
            for item in self.explicit_restrictions
        ]
        if len(restrictions) != len(set(restrictions)):
            raise ValueError("explicit restrictions must be unique")
        return self


class BaseSkinUpdate(_StrictFrozen):
    value: SessionBaseSkinValue
    confirmation: ConfirmationState
    operation: UpdateOperation = "set"


class StableTendencyUpdate(_StrictFrozen):
    value: StableTendency
    confirmation: ConfirmationState
    operation: UpdateOperation = "set"


class CurrentConditionUpdate(_StrictFrozen):
    value: CurrentCondition
    active: bool = True


class ExplicitRestrictionUpdate(_StrictFrozen):
    value: RestrictionValue
    operation: UpdateOperation = "set"


SessionProfileUpdate = (
    BaseSkinUpdate
    | StableTendencyUpdate
    | CurrentConditionUpdate
    | ExplicitRestrictionUpdate
)


class SessionProfileReduction(_StrictFrozen):
    profile: SessionProfile
    changed: bool
    disposition: Literal[
        "updated",
        "unchanged",
        "unchanged_other_subject",
    ]


def reduce_session_profile(
    *,
    previous: SessionProfile,
    updates: Sequence[SessionProfileUpdate],
    subject_scope: SubjectScope,
    source_turn_id: str,
    conversation_version: int,
) -> SessionProfileReduction:
    if type(previous) is not SessionProfile:
        raise TypeError("previous must be an exact SessionProfile")
    if subject_scope not in {"self", "other"}:
        raise ValueError("subject_scope must be self or other")
    if (
        not isinstance(conversation_version, int)
        or isinstance(conversation_version, bool)
        or conversation_version < 1
    ):
        raise ValueError("conversation_version must be a positive integer")
    typed_updates = tuple(updates)
    if any(
        not isinstance(
            item,
            (
                BaseSkinUpdate,
                StableTendencyUpdate,
                CurrentConditionUpdate,
                ExplicitRestrictionUpdate,
            ),
        )
        for item in typed_updates
    ):
        raise TypeError("updates must contain session profile updates")
    _validate_unique_updates(typed_updates)
    if subject_scope == "other":
        return SessionProfileReduction(
            profile=previous,
            changed=False,
            disposition="unchanged_other_subject",
        )

    base_skin = previous.base_skin
    tendencies = {
        item.value: item
        for item in previous.stable_tendencies
    }
    conditions = {
        item.value: item
        for item in previous.current_conditions
    }
    restrictions = {
        item.value.casefold(): item
        for item in previous.explicit_restrictions
    }

    for update in typed_updates:
        if isinstance(update, BaseSkinUpdate):
            base_skin = (
                None
                if update.operation == "remove"
                else SessionBaseSkin(
                    value=update.value,
                    confirmation=update.confirmation,
                    source_turn_id=source_turn_id,
                )
            )
        elif isinstance(update, StableTendencyUpdate):
            if update.operation == "remove":
                tendencies.pop(update.value, None)
            else:
                tendencies[update.value] = SessionProfileFact(
                    value=update.value,
                    confirmation=update.confirmation,
                    source_turn_id=source_turn_id,
                )
        elif isinstance(update, CurrentConditionUpdate):
            if not update.active:
                conditions.pop(update.value, None)
            else:
                conditions[update.value] = SessionConditionFact(
                    value=update.value,
                    source_turn_id=source_turn_id,
                    recorded_at_version=conversation_version,
                )
        else:
            assert isinstance(update, ExplicitRestrictionUpdate)
            key = update.value.casefold()
            if update.operation == "remove":
                restrictions.pop(key, None)
            else:
                restrictions[key] = SessionRestriction(
                    value=update.value,
                    source_turn_id=source_turn_id,
                )

    profile = SessionProfile(
        base_skin=base_skin,
        stable_tendencies=tuple(
            tendencies[key] for key in sorted(tendencies)
        ),
        current_conditions=tuple(
            conditions[key] for key in sorted(conditions)
        ),
        explicit_restrictions=tuple(
            restrictions[key] for key in sorted(restrictions)
        ),
    )
    changed = profile != previous
    return SessionProfileReduction(
        profile=profile,
        changed=changed,
        disposition="updated" if changed else "unchanged",
    )


def _validate_unique_updates(
    updates: tuple[SessionProfileUpdate, ...],
) -> None:
    keys: list[tuple[str, str]] = []
    for update in updates:
        if isinstance(update, BaseSkinUpdate):
            key = ("base_skin", "base_skin")
        elif isinstance(update, StableTendencyUpdate):
            key = ("stable_tendency", update.value)
        elif isinstance(update, CurrentConditionUpdate):
            key = ("current_condition", update.value)
        else:
            assert isinstance(update, ExplicitRestrictionUpdate)
            key = ("explicit_restriction", update.value.casefold())
        keys.append(key)
    if len(keys) != len(set(keys)):
        raise ValueError("session profile updates must be unique")


__all__ = [
    "BaseSkinUpdate",
    "CurrentConditionUpdate",
    "ExplicitRestrictionUpdate",
    "SessionBaseSkin",
    "SessionBaseSkinValue",
    "SessionConditionFact",
    "SessionProfile",
    "SessionProfileFact",
    "SessionProfileReduction",
    "SessionProfileUpdate",
    "SessionRestriction",
    "StableTendencyUpdate",
    "reduce_session_profile",
]
