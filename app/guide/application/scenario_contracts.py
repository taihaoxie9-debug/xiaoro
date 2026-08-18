from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from app.guide.feedback.contracts import RecommendationQueryContext
from app.guide.intent.contracts import TaskConstraint
from app.guide.retrieval.scenario_contracts import (
    ScenarioConstraint,
    ScenarioEvidenceRequirement,
)
from app.guide.understanding.scenario_parsing import ScenarioObservation


class _StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ScenarioConstraintResolution(_StrictContract):
    constraint: ScenarioConstraint
    status: Literal["applied", "shadowed_by_explicit"]


class ScenarioQueryInput(_StrictContract):
    query_context: RecommendationQueryContext
    scenarios: list[ScenarioObservation]
    scenario_resolutions: list[ScenarioConstraintResolution]
    evidence_requirements: list[ScenarioEvidenceRequirement]


class ScenarioDecisionInput(_StrictContract):
    constraints: list[TaskConstraint]
    scenario_resolutions: list[ScenarioConstraintResolution]
    evidence_requirements: list[ScenarioEvidenceRequirement]


class ScenarioInputBundle(_StrictContract):
    query: ScenarioQueryInput
    decision: ScenarioDecisionInput

    @model_validator(mode="after")
    def validate_shared_audit_input(self) -> Self:
        if (
            self.query.scenario_resolutions
            != self.decision.scenario_resolutions
        ):
            raise ValueError(
                "query and decision scenario resolutions differ"
            )
        if (
            self.query.evidence_requirements
            != self.decision.evidence_requirements
        ):
            raise ValueError(
                "query and decision evidence requirements differ"
            )
        return self
