from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, field_validator

from app.guide.understanding.consultation_escalation import (
    EscalationCode,
)
from app.guide.understanding.source_grounding import (
    SourceGroundingError,
    ground_unique_text,
)
from app.guide.understanding.turn_meaning_contracts import (
    TurnObservationCandidate,
    TurnObservationCode,
    TurnObservationDuration,
    TurnObservationSeverity,
    TurnObservationTrigger,
)


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class SafetyObservation(_StrictFrozen):
    code: TurnObservationCode
    present: bool
    trigger: TurnObservationTrigger | None
    duration: TurnObservationDuration | None
    severity: TurnObservationSeverity | None


class AdmittedSafetySignal(_StrictFrozen):
    trigger_codes: tuple[EscalationCode, ...] = ()

    @field_validator("trigger_codes", mode="before")
    @classmethod
    def freeze_trigger_codes(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @property
    def requires_escalation(self) -> bool:
        return bool(self.trigger_codes)


def admit_safety_signal(
    *,
    message: str,
    candidates: Sequence[TurnObservationCandidate],
) -> AdmittedSafetySignal:
    if not isinstance(message, str) or not message.strip():
        raise ValueError("message must be nonempty")
    observations: list[SafetyObservation] = []
    for candidate in candidates:
        if type(candidate) is not TurnObservationCandidate:
            raise TypeError(
                "candidates must contain exact TurnObservationCandidate values"
            )
        try:
            ground_unique_text(message.strip(), candidate.raw_text)
        except SourceGroundingError:
            continue
        observations.append(
            SafetyObservation(
                code=candidate.code,
                present=candidate.present,
                trigger=candidate.trigger,
                duration=candidate.duration,
                severity=candidate.severity,
            )
        )
    return classify_safety_observations(observations)


def classify_safety_observations(
    observations: Sequence[SafetyObservation],
) -> AdmittedSafetySignal:
    normalized = tuple(observations)
    if any(type(item) is not SafetyObservation for item in normalized):
        raise TypeError(
            "observations must contain exact SafetyObservation values"
        )
    present = {
        item.code: item
        for item in normalized
        if item.present
    }
    code: EscalationCode | None = None
    if "oozing" in present:
        code = "oozing"
    elif "broken_skin" in present:
        code = "broken_skin"
    elif (
        "swelling" in present
        and present["swelling"].duration == "persistent"
    ):
        code = "persistent_swelling"
    elif (
        "burning" in present
        and (
            present["burning"].duration == "persistent"
            or present["burning"].severity == "severe"
            or present["burning"].trigger == "new_product"
        )
    ):
        code = "persistent_burning"
    elif "pain" in present:
        code = "pain"
    return AdmittedSafetySignal(
        trigger_codes=((code,) if code is not None else ()),
    )


__all__ = [
    "AdmittedSafetySignal",
    "SafetyObservation",
    "admit_safety_signal",
    "classify_safety_observations",
]
