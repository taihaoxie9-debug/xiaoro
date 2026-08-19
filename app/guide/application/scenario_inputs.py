from __future__ import annotations

from collections.abc import Collection
from typing import Literal, assert_never

from app.guide.application.query_context import (
    task_plan_to_query_context,
)
from app.guide.application.scenario_contracts import (
    ScenarioConstraintResolution,
    ScenarioDecisionInput,
    ScenarioInputBundle,
    ScenarioQueryInput,
)
from app.guide.intent.contracts import (
    EfficacyConstraint,
    SkinConstraint,
    TaskConstraint,
    TaskPlan,
)
from app.guide.retrieval.scenario_contracts import (
    ScenarioConstraint,
    ScenarioEfficacyConstraint,
    ScenarioSkinConstraint,
)
from app.guide.retrieval.scenario_rules import (
    compile_scenario_requirements,
)
from app.guide.understanding.scenario_parsing import (
    ScenarioCode,
    parse_scenarios,
)

_SCENARIO_PARENT_BY_CODE = {
    ScenarioCode.REPAIR: "efficacy",
    ScenarioCode.SENSITIVE_PERIOD: "skin",
}


def build_scenario_inputs(
    task: TaskPlan,
    *,
    message: str,
    suppressed_constraint_parents: Collection[
        Literal["efficacy", "skin"]
    ] = (),
) -> ScenarioInputBundle:
    if task.mode != "recommend":
        raise ValueError("scenario inputs require recommend task")
    suppressed = frozenset(suppressed_constraint_parents)
    if not suppressed <= {"efficacy", "skin"}:
        raise ValueError("unsupported scenario constraint parent")

    scenarios = parse_scenarios(message)
    projection = compile_scenario_requirements(scenarios)
    effective_constraints = [
        item.model_copy(deep=True)
        for item in task.constraints
    ]
    explicit_kinds = {
        item.kind for item in effective_constraints
    }
    resolutions: list[ScenarioConstraintResolution] = []

    for constraint in projection.constraints:
        if constraint.kind in explicit_kinds:
            status = "shadowed_by_explicit"
        elif constraint.kind in suppressed:
            status = "suppressed_by_withdrawal"
        else:
            effective_constraints.append(
                _to_task_constraint(constraint)
            )
            explicit_kinds.add(constraint.kind)
            status = "applied"
        resolutions.append(
            ScenarioConstraintResolution(
                constraint=constraint,
                status=status,
            )
        )

    effective_task = task.model_copy(
        update={"constraints": effective_constraints},
        deep=True,
    )
    query_context = task_plan_to_query_context(effective_task)
    return ScenarioInputBundle(
        query=ScenarioQueryInput(
            query_context=query_context,
            scenarios=scenarios,
            scenario_resolutions=resolutions,
            evidence_requirements=[
                item
                for item in projection.evidence_requirements
                if (
                    _SCENARIO_PARENT_BY_CODE.get(
                        item.source.scenario
                    )
                    not in suppressed
                )
            ],
        ),
        decision=ScenarioDecisionInput(
            constraints=effective_constraints,
            scenario_resolutions=resolutions,
            evidence_requirements=[
                item
                for item in projection.evidence_requirements
                if (
                    _SCENARIO_PARENT_BY_CODE.get(
                        item.source.scenario
                    )
                    not in suppressed
                )
            ],
        ),
    )


def _to_task_constraint(
    constraint: ScenarioConstraint,
) -> TaskConstraint:
    if isinstance(constraint, ScenarioEfficacyConstraint):
        return EfficacyConstraint(value=constraint.value)
    if isinstance(constraint, ScenarioSkinConstraint):
        return SkinConstraint(value=constraint.value)
    assert_never(constraint)
