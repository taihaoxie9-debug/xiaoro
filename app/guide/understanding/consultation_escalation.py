from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)


EscalationCode = Literal[
    "persistent_swelling",
    "persistent_burning",
    "pain",
    "broken_skin",
    "oozing",
]


class ConsultationEscalationTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    code: EscalationCode
    source_turn_id: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=16,
            max_length=160,
        ),
    ]


class ConsultationEscalationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    triggers: list[ConsultationEscalationTrigger] = Field(
        default_factory=list,
        max_length=3,
    )

    @model_validator(mode="after")
    def require_unique_trigger_codes(self) -> Self:
        codes = [trigger.code for trigger in self.triggers]
        if len(codes) != len(set(codes)):
            raise ValueError(
                "consultation escalation trigger codes must be unique"
            )
        return self
