from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    model_validator,
)

from app.guide.understanding.contracts import (
    EfficacyTarget,
    SkinTarget,
)
from app.guide.understanding.scenario_parsing import ScenarioCode


class _StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


RuleId = Annotated[
    str,
    StringConstraints(
        pattern=(
            r"^scenario-v1:"
            r"(commute|travel|outdoor|repair|sensitive_period):"
            r"[a-z_]+$"
        )
    ),
]
Explanation = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=240),
]


class ScenarioRuleSource(_StrictContract):
    scenario: ScenarioCode
    matched_text: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=32),
    ]
    rule_id: RuleId

    @model_validator(mode="after")
    def validate_rule_owner(self) -> Self:
        expected_prefix = f"scenario-v1:{self.scenario.value}:"
        if not self.rule_id.startswith(expected_prefix):
            raise ValueError("scenario rule_id owner mismatch")
        return self


class ScenarioEfficacyConstraint(_StrictContract):
    kind: Literal["efficacy"] = "efficacy"
    value: Literal[EfficacyTarget.REPAIR] = EfficacyTarget.REPAIR
    source: ScenarioRuleSource
    rationale: Explanation


class ScenarioSkinConstraint(_StrictContract):
    kind: Literal["skin"] = "skin"
    value: Literal[SkinTarget.SENSITIVE] = SkinTarget.SENSITIVE
    source: ScenarioRuleSource
    rationale: Explanation


ScenarioConstraint = Annotated[
    ScenarioEfficacyConstraint | ScenarioSkinConstraint,
    Field(discriminator="kind"),
]


class ScenarioEvidenceField(str, Enum):
    EFFICACY = "efficacy"
    SPF_PA = "spf_pa"
    SUITABLE_SKIN = "suitable_skin"
    TEXTURE = "texture"
    USAGE = "usage"
    WATER_RESISTANCE = "water_resistance"


class ScenarioEvidenceRequirement(_StrictContract):
    field: ScenarioEvidenceField
    source: ScenarioRuleSource
    rationale: Explanation
    unknown_policy: Literal["preserve_unknown"] = "preserve_unknown"
    claim_policy: Literal["evidence_only"] = "evidence_only"


class ScenarioRuleProjection(_StrictContract):
    constraints: list[ScenarioConstraint]
    evidence_requirements: list[ScenarioEvidenceRequirement]

    @model_validator(mode="after")
    def validate_unique_rules(self) -> Self:
        rule_ids = [
            item.source.rule_id
            for item in [
                *self.constraints,
                *self.evidence_requirements,
            ]
        ]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("scenario rule_id must be unique")
        return self


class ScenarioEvidenceState(str, Enum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"
    NOT_APPLICABLE = "not_applicable"


class ScenarioEvidenceRecord(_StrictContract):
    product_id: int = Field(gt=0)
    requirement_id: RuleId
    field: ScenarioEvidenceField
    state: ScenarioEvidenceState
    value: JsonValue = None
    source_refs: list[str]
    reason: Literal[
        "canonical_known",
        "canonical_unknown",
        "canonical_conflict",
        "canonical_not_applicable",
        "canonical_field_missing",
        "canonical_source_missing",
        "canonical_value_missing",
        "canonical_state_invalid",
    ]

    @model_validator(mode="after")
    def validate_state_value(self) -> Self:
        if self.state is ScenarioEvidenceState.KNOWN:
            if self.value is None:
                raise ValueError("known scenario evidence requires value")
            if not self.source_refs:
                raise ValueError(
                    "known scenario evidence requires source refs"
                )
        elif self.value is not None:
            raise ValueError(
                "non-known scenario evidence forbids value"
            )
        return self
