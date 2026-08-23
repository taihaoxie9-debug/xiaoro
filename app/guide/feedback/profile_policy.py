from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.guide.feedback.profile_contracts import (
    ConfirmedProfileFact,
)
from app.guide.feedback.contracts import ConversationSnapshot
from app.guide.feedback.ports import ConversationStatePort
from app.guide.feedback.profile_state import (
    ProfileSnapshot,
    ProfileStatePort,
    ProfileWriteDisposition,
)


ProfileField = Literal[
    "skin_type",
    "skin_concern",
    "ingredient_exclusion",
    "preferred_brand",
    "preferred_category",
]
DurableSourceKind = Literal[
    "explicit_user",
    "confirmed_consultation",
]
ResolutionSource = Literal[
    "current_explicit_input",
    "confirmed_session_fact",
    "long_term_profile",
    "default",
]
SkinTargetValue = Literal[
    "oily_sensitive",
    "oily",
    "dry",
    "combination",
    "sensitive",
    "normal",
]
PersistenceRejectionCode = Literal[
    "anonymous_snapshot",
    "unconfirmed_consultation",
    "mismatched_consultation_state",
    "mismatched_snapshot_authority",
]
ProfileValue = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]
SourceTurnId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=16, max_length=160),
]

_PROFILE_FIELD_ORDER: tuple[ProfileField, ...] = (
    "skin_type",
    "skin_concern",
    "ingredient_exclusion",
    "preferred_brand",
    "preferred_category",
)
_SKIN_TARGET_VALUES = frozenset(
    {
        "oily_sensitive",
        "oily",
        "dry",
        "combination",
        "sensitive",
        "normal",
    }
)


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class CurrentExplicitFact(_StrictFrozen):
    field: ProfileField
    value: ProfileValue
    source_turn_id: SourceTurnId


class ConfirmedSessionFact(_StrictFrozen):
    field: ProfileField
    value: ProfileValue
    source_turn_id: SourceTurnId
    source_kind: DurableSourceKind


class DefaultProfileFact(_StrictFrozen):
    field: ProfileField
    value: ProfileValue


class ResolvedValueProvenance(_StrictFrozen):
    source_turn_id: SourceTurnId | None = None
    source_kind: DurableSourceKind | None = None
    profile_version: int | None = Field(default=None, ge=1)


class ResolvedProfileValue(_StrictFrozen):
    field: ProfileField
    value: ProfileValue
    source: ResolutionSource
    provenance: ResolvedValueProvenance

    @model_validator(mode="after")
    def validate_provenance(self) -> Self:
        provenance = self.provenance
        if self.source == "default":
            if provenance != ResolvedValueProvenance():
                raise ValueError("default values cannot claim provenance")
            return self
        if (
            provenance.source_turn_id is None
            or provenance.source_kind is None
        ):
            raise ValueError("resolved source requires turn provenance")
        if self.source == "current_explicit_input":
            if provenance.source_kind != "explicit_user":
                raise ValueError(
                    "current explicit input requires explicit_user source"
                )
            if provenance.profile_version is not None:
                raise ValueError(
                    "current explicit input forbids profile version"
                )
        elif self.source == "confirmed_session_fact":
            if provenance.profile_version is not None:
                raise ValueError(
                    "confirmed session fact forbids profile version"
                )
        elif provenance.profile_version is None:
            raise ValueError(
                "long-term profile requires profile version"
            )
        return self


class ResolvedProfileContext(_StrictFrozen):
    values: tuple[ResolvedProfileValue, ...] = Field(max_length=5)

    @field_validator("values", mode="before")
    @classmethod
    def freeze_values(
        cls,
        value: object,
    ) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_unique_fields(self) -> Self:
        fields = [item.field for item in self.values]
        if len(fields) != len(set(fields)):
            raise ValueError("resolved profile fields must be unique")
        return self


def has_confirmed_profile_provenance(
    value: ResolvedProfileValue,
) -> bool:
    """Return whether a resolved value carries explicit/confirmed authority."""
    if not isinstance(value, ResolvedProfileValue):
        return False
    provenance = value.provenance
    if value.source == "current_explicit_input":
        return (
            provenance.source_turn_id is not None
            and provenance.source_kind == "explicit_user"
            and provenance.profile_version is None
        )
    if value.source == "confirmed_session_fact":
        return (
            provenance.source_turn_id is not None
            and provenance.source_kind is not None
            and provenance.profile_version is None
        )
    if value.source == "long_term_profile":
        return (
            provenance.source_turn_id is not None
            and provenance.source_kind is not None
            and provenance.profile_version is not None
        )
    return False


class ProfilePersistenceRejected(RuntimeError):
    def __init__(self, code: PersistenceRejectionCode) -> None:
        self.code = code
        super().__init__(code)


class ProfilePersistencePlan(_StrictFrozen):
    outcome: Literal["created", "idempotent", "preserved_existing"]
    disposition: Literal["created", "replay", "conflict"]
    field: Literal["skin_type"] = "skin_type"
    value: ProfileValue
    requested_value: SkinTargetValue
    profile_version: int = Field(ge=1)
    existing_value: ProfileValue | None = None
    existing_source_turn_id: SourceTurnId | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        has_existing = (
            self.existing_value is not None
            and self.existing_source_turn_id is not None
        )
        if self.outcome == "created":
            if (
                self.disposition != "created"
                or has_existing
                or self.value != self.requested_value
            ):
                raise ValueError("created plan cannot claim existing state")
        elif self.outcome == "idempotent":
            if (
                self.disposition != "replay"
                or not has_existing
                or self.value != self.requested_value
                or self.existing_value != self.requested_value
            ):
                raise ValueError(
                    "idempotent plan must preserve the same existing value"
                )
        elif (
            self.disposition != "conflict"
            or not has_existing
            or self.value != self.existing_value
            or self.existing_value == self.requested_value
        ):
            raise ValueError(
                "preserved plan must describe a conflicting existing value"
            )
        return self


class ProfilePersistenceRetry(_StrictFrozen):
    outcome: Literal["retry_required"] = "retry_required"
    reason: Literal["cas_conflict", "store_unavailable"]
    field: Literal["skin_type"] = "skin_type"
    requested_value: SkinTargetValue


def resolve_profile_context(
    *,
    current_explicit: Sequence[CurrentExplicitFact] = (),
    confirmed_session: Sequence[ConfirmedSessionFact] = (),
    profile: ProfileSnapshot | None = None,
    defaults: Sequence[DefaultProfileFact] = (),
) -> ResolvedProfileContext:
    resolved: dict[ProfileField, ResolvedProfileValue] = {}

    for fact in _unique_by_field(defaults, source="default"):
        resolved[fact.field] = ResolvedProfileValue(
            field=fact.field,
            value=fact.value,
            source="default",
            provenance=ResolvedValueProvenance(),
        )
    if profile is not None:
        for fact in profile.facts:
            resolved[fact.field] = ResolvedProfileValue(
                field=fact.field,
                value=fact.value,
                source="long_term_profile",
                provenance=ResolvedValueProvenance(
                    source_turn_id=fact.source_turn_id,
                    source_kind=fact.source_kind,
                    profile_version=fact.profile_version,
                ),
            )
    for fact in _unique_by_field(
        confirmed_session,
        source="confirmed_session",
    ):
        resolved[fact.field] = ResolvedProfileValue(
            field=fact.field,
            value=fact.value,
            source="confirmed_session_fact",
            provenance=ResolvedValueProvenance(
                source_turn_id=fact.source_turn_id,
                source_kind=fact.source_kind,
            ),
        )
    for fact in _unique_by_field(
        current_explicit,
        source="current_explicit",
    ):
        resolved[fact.field] = ResolvedProfileValue(
            field=fact.field,
            value=fact.value,
            source="current_explicit_input",
            provenance=ResolvedValueProvenance(
                source_turn_id=fact.source_turn_id,
                source_kind="explicit_user",
            ),
        )

    return ResolvedProfileContext(
        values=[
            resolved[field]
            for field in _PROFILE_FIELD_ORDER
            if field in resolved
        ]
    )


def persist_confirmed_consultation_profile(
    state: ProfileStatePort,
    conversation_state: ConversationStatePort,
    snapshot: ConversationSnapshot,
    *,
    expected_version: int,
    confirmed_at: datetime,
) -> ProfilePersistencePlan:
    if type(snapshot) is not ConversationSnapshot:
        raise TypeError("snapshot must be an exact ConversationSnapshot")
    if (
        not isinstance(expected_version, int)
        or isinstance(expected_version, bool)
        or expected_version < 0
    ):
        raise ValueError("expected_version must be a non-negative integer")
    _require_utc_datetime(confirmed_at)

    authoritative = conversation_state.load(snapshot.session_id)
    if (
        type(authoritative) is not ConversationSnapshot
        or authoritative != snapshot
    ):
        raise ProfilePersistenceRejected("mismatched_snapshot_authority")
    owner = authoritative.profile_owner
    if owner is None:
        raise ProfilePersistenceRejected("anonymous_snapshot")

    consultation = (
        authoritative.consultation_slot.state
        if authoritative.consultation_slot is not None
        else None
    )
    assessment = (
        consultation.confirmable_assessment
        if consultation is not None
        else None
    )
    if (
        consultation is None
        or assessment is None
        or not assessment.conclusion.confirmed_by_user
        or assessment.conclusion.skin_target not in _SKIN_TARGET_VALUES
        or consultation.confirmation_source_turn_id is None
    ):
        raise ProfilePersistenceRejected("unconfirmed_consultation")
    if (
        authoritative.version != assessment.observation_set_version + 2
        or assessment.observations != consultation.observations
        or consultation.medical_escalation is not None
        or assessment.escalation_triggers
        or assessment.stop_skincare_advice
    ):
        raise ProfilePersistenceRejected("mismatched_consultation_state")

    skin_target = assessment.conclusion.skin_target
    assert skin_target is not None
    fact = ConfirmedProfileFact(
        owner=owner,
        field="skin_type",
        value=skin_target,
        source_turn_id=consultation.confirmation_source_turn_id,
        source_kind="confirmed_consultation",
        confirmed_at=confirmed_at,
        profile_version=expected_version + 1,
    )
    write_result = state.write_once(
        fact,
        expected_version=expected_version,
    )
    stored = write_result.stored_fact
    if write_result.disposition is ProfileWriteDisposition.CREATED:
        return ProfilePersistencePlan(
            outcome="created",
            disposition="created",
            value=stored.value,
            requested_value=skin_target,
            profile_version=stored.profile_version,
        )
    is_replay = (
        write_result.disposition is ProfileWriteDisposition.IDEMPOTENT
    )
    return ProfilePersistencePlan(
        outcome="idempotent" if is_replay else "preserved_existing",
        disposition="replay" if is_replay else "conflict",
        value=stored.value,
        requested_value=skin_target,
        profile_version=stored.profile_version,
        existing_value=stored.value,
        existing_source_turn_id=stored.source_turn_id,
    )


def reconcile_confirmed_consultation_profile(
    state: ProfileStatePort,
    conversation_state: ConversationStatePort,
    snapshot: ConversationSnapshot,
    *,
    confirmed_at: datetime,
) -> ProfilePersistencePlan:
    if type(snapshot) is not ConversationSnapshot:
        raise TypeError("snapshot must be an exact ConversationSnapshot")
    authoritative = conversation_state.load(snapshot.session_id)
    if (
        type(authoritative) is not ConversationSnapshot
        or authoritative != snapshot
    ):
        raise ProfilePersistenceRejected("mismatched_snapshot_authority")
    owner = authoritative.profile_owner
    if owner is None:
        raise ProfilePersistenceRejected("anonymous_snapshot")
    latest = state.load(owner)
    return persist_confirmed_consultation_profile(
        state,
        conversation_state,
        authoritative,
        expected_version=latest.version if latest is not None else 0,
        confirmed_at=confirmed_at,
    )


def _require_utc_datetime(value: datetime) -> None:
    if not isinstance(value, datetime):
        raise TypeError("confirmed_at must be a datetime")
    if (
        value.utcoffset() is None
        or value.utcoffset() != UTC.utcoffset(value)
    ):
        raise ValueError("confirmed_at must be UTC")


def _unique_by_field(
    facts: Sequence[CurrentExplicitFact]
    | Sequence[ConfirmedSessionFact]
    | Sequence[DefaultProfileFact],
    *,
    source: str,
):
    fields = [fact.field for fact in facts]
    if len(fields) != len(set(fields)):
        raise ValueError(f"{source} facts must have unique fields")
    return facts
