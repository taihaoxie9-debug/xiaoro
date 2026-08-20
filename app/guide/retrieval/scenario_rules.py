from __future__ import annotations

from app.guide.retrieval.scenario_contracts import (
    ScenarioEfficacyConstraint,
    ScenarioEvidenceField,
    ScenarioEvidenceRequirement,
    ScenarioRuleProjection,
    ScenarioRuleSource,
    ScenarioSkinConstraint,
)
from app.guide.understanding.scenario_parsing import (
    ScenarioCode,
    ScenarioObservation,
)


def compile_scenario_requirements(
    observations: list[ScenarioObservation],
) -> ScenarioRuleProjection:
    constraints = []
    evidence_requirements: list[ScenarioEvidenceRequirement] = []

    for observation in observations:
        scenario = observation.scenario
        if scenario is ScenarioCode.COMMUTE:
            evidence_requirements.extend(
                (
                    _evidence(
                        observation,
                        field=ScenarioEvidenceField.SPF_PA,
                        rationale=(
                            "通勤暴露下只核对有来源的防晒标识，"
                            "缺失时保持未知。"
                        ),
                    ),
                    _evidence(
                        observation,
                        field=ScenarioEvidenceField.TEXTURE,
                        rationale=(
                            "通勤使用感仅由已审核质地事实支持，"
                            "不从场景猜测。"
                        ),
                    ),
                )
            )
        elif scenario is ScenarioCode.TRAVEL:
            evidence_requirements.extend(
                (
                    _evidence(
                        observation,
                        field=ScenarioEvidenceField.USAGE,
                        rationale=(
                            "旅行使用方式需要 Canonical 用法事实，"
                            "不推断便携或适用环境。"
                        ),
                    ),
                    _evidence(
                        observation,
                        field=ScenarioEvidenceField.TEXTURE,
                        rationale=(
                            "旅行中的质地偏好只引用已审核质地事实。"
                        ),
                    ),
                )
            )
        elif scenario is ScenarioCode.OUTDOOR:
            evidence_requirements.extend(
                (
                    _evidence(
                        observation,
                        field=ScenarioEvidenceField.SPF_PA,
                        rationale=(
                            "户外防护判断需要有来源的 SPF/PA 事实。"
                        ),
                    ),
                    _evidence(
                        observation,
                        field=ScenarioEvidenceField.WATER_RESISTANCE,
                        rationale=(
                            "户外耐水信息必须来自 Canonical，"
                            "缺失不视为耐水。"
                        ),
                    ),
                    _evidence(
                        observation,
                        field=ScenarioEvidenceField.USAGE,
                        rationale=(
                            "户外补涂或使用方式"
                            "只引用已审核用法事实。"
                        ),
                    ),
                )
            )
        elif scenario is ScenarioCode.REPAIR:
            constraints.append(
                ScenarioEfficacyConstraint(
                    source=_source(observation, "efficacy"),
                    rationale=(
                        "修护场景补空为既有 repair 功效硬约束，"
                        "不会覆盖本轮明确功效。"
                    ),
                )
            )
            evidence_requirements.append(
                _evidence(
                    observation,
                    field=ScenarioEvidenceField.EFFICACY,
                    source_suffix="efficacy_evidence",
                    rationale=(
                        "修护结论必须有 Canonical 功效证据，"
                        "未知或冲突不能通过。"
                    ),
                )
            )
        elif scenario is ScenarioCode.SENSITIVE_PERIOD:
            constraints.append(
                ScenarioSkinConstraint(
                    source=_source(observation, "skin"),
                    rationale=(
                        "敏感期仅在肤质未明确时补空为 sensitive，"
                        "不覆盖本轮明确肤质。"
                    ),
                )
            )
            evidence_requirements.append(
                _evidence(
                    observation,
                    field=ScenarioEvidenceField.SUITABLE_SKIN,
                    rationale=(
                        "敏感期适配只核对有来源的适用肤质事实，"
                        "不生成安全保证。"
                    ),
                )
            )

    return ScenarioRuleProjection(
        constraints=constraints,
        evidence_requirements=evidence_requirements,
    )


def _evidence(
    observation: ScenarioObservation,
    *,
    field: ScenarioEvidenceField,
    rationale: str,
    source_suffix: str | None = None,
) -> ScenarioEvidenceRequirement:
    return ScenarioEvidenceRequirement(
        field=field,
        source=_source(
            observation,
            source_suffix or field.value,
        ),
        rationale=rationale,
    )


def _source(
    observation: ScenarioObservation,
    suffix: str,
) -> ScenarioRuleSource:
    return ScenarioRuleSource(
        scenario=observation.scenario,
        matched_text=observation.matched_text,
        rule_id=(
            f"scenario-v1:{observation.scenario.value}:{suffix}"
        ),
    )
