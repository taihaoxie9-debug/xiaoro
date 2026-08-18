from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.guide.understanding.consultation_contracts import (
    ConsultationObservation,
    ProvisionalConsultationConclusion,
)
from app.guide.understanding.consultation_escalation import (
    ConsultationEscalationTrigger,
)

ConsultationSourceTurnId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=16,
        max_length=160,
    ),
]


def _validate_observations(
    observations: tuple[ConsultationObservation, ...],
) -> None:
    legacy_codes = [
        item.code for item in observations if item.code is not None
    ]
    if len(legacy_codes) != len(set(legacy_codes)):
        raise ValueError("legacy observation codes must be unique")
    dynamic_ids = [
        item.observation_id
        for item in observations
        if item.observation_id is not None
    ]
    if len(dynamic_ids) != len(set(dynamic_ids)):
        raise ValueError("dynamic observation IDs must be unique")
    dynamic_dimensions = [
        item.dimension
        for item in observations
        if item.dimension is not None
    ]
    if len(dynamic_dimensions) != len(set(dynamic_dimensions)):
        raise ValueError(
            "dynamic observation dimensions must be unique"
        )


class ConfirmableConsultationAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    assessment_kind: Literal[
        "provisional",
        "medical_escalation",
    ] = "provisional"
    observation_set_version: int = Field(ge=1)
    observations: tuple[ConsultationObservation, ...] = Field(
        default_factory=tuple,
        max_length=32,
    )
    conclusion: ProvisionalConsultationConclusion
    conclusion_source_turn_id: ConsultationSourceTurnId
    escalation_triggers: tuple[
        ConsultationEscalationTrigger,
        ...,
    ] = Field(
        max_length=3,
    )
    stop_skincare_advice: bool

    @field_validator(
        "observations",
        "escalation_triggers",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_assessment_binding(self) -> Self:
        _validate_observations(self.observations)
        trigger_codes = [
            trigger.code for trigger in self.escalation_triggers
        ]
        if len(trigger_codes) != len(set(trigger_codes)):
            raise ValueError(
                "consultation escalation trigger codes must be unique"
            )
        if self.stop_skincare_advice != bool(
            self.escalation_triggers
        ):
            raise ValueError(
                "stop_skincare_advice must match escalation triggers"
            )
        if self.assessment_kind == "medical_escalation":
            if (
                not self.escalation_triggers
                or not self.stop_skincare_advice
                or self.conclusion.confirmed_by_user
            ):
                raise ValueError(
                    "medical escalation must be terminal and unconfirmed"
                )
        elif not self.observations:
            raise ValueError(
                "provisional assessment requires observations"
            )
        return self


class RecordedMedicalEscalation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    recorded_at_conversation_version: int = Field(ge=1)
    assessment: ConfirmableConsultationAssessment

    @model_validator(mode="after")
    def validate_record(self) -> Self:
        assessment = self.assessment
        if (
            assessment.assessment_kind != "medical_escalation"
            or not assessment.escalation_triggers
            or not assessment.stop_skincare_advice
            or assessment.conclusion.confirmed_by_user
        ):
            raise ValueError(
                "recorded medical escalation requires terminal assessment"
            )
        recorded_version = self.recorded_at_conversation_version
        observation_version = assessment.observation_set_version
        same_turn_dynamic_assessment = (
            recorded_version == observation_version
            and any(
                item.observation_id is not None
                for item in assessment.observations
            )
        )
        if (
            recorded_version != observation_version + 1
            and not same_turn_dynamic_assessment
        ):
            raise ValueError(
                "medical escalation version must follow its observation "
                "set or atomically bind dynamic observations"
            )
        return self


class ConsultationSubstate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    started_at_conversation_version: int = Field(default=1, ge=1)
    observations: tuple[ConsultationObservation, ...] = Field(
        default_factory=tuple,
        max_length=32,
    )
    confirmable_assessment: ConfirmableConsultationAssessment | None = (
        None
    )
    medical_escalation: RecordedMedicalEscalation | None = None
    confirmation_source_turn_id: ConsultationSourceTurnId | None = None

    @field_validator("observations", mode="before")
    @classmethod
    def freeze_observations(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_consultation_substate(self) -> Self:
        _validate_observations(self.observations)
        assessment = self.confirmable_assessment
        medical = self.medical_escalation
        if (
            medical is not None
            and medical.assessment.observations != self.observations
        ):
            raise ValueError(
                "medical escalation must bind exact observations"
            )
        if assessment is None:
            if self.confirmation_source_turn_id is not None:
                raise ValueError(
                    "consultation confirmation requires an assessment"
                )
            return self
        if (
            assessment.observation_set_version
            < self.started_at_conversation_version
        ):
            raise ValueError(
                "consultation assessment cannot predate consultation start"
            )
        if assessment.observations != self.observations:
            raise ValueError(
                "consultation assessment must bind exact observations"
            )
        if (
            assessment.assessment_kind == "medical_escalation"
            and (
                medical is None
                or medical.assessment != assessment
            )
        ):
            raise ValueError(
                "terminal assessment requires its medical escalation record"
            )
        is_confirmed = assessment.conclusion.confirmed_by_user
        if is_confirmed and self.confirmation_source_turn_id is None:
            raise ValueError(
                "confirmed consultation requires confirmation source turn"
            )
        if not is_confirmed and self.confirmation_source_turn_id is not None:
            raise ValueError(
                "unconfirmed consultation forbids confirmation source turn"
            )
        return self
