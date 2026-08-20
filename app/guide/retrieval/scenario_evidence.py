from __future__ import annotations

from app.guide.retrieval.contracts import CanonicalProduct
from app.guide.retrieval.scenario_contracts import (
    ScenarioEvidenceRecord,
    ScenarioEvidenceRequirement,
    ScenarioEvidenceState,
)


def project_scenario_evidence(
    product: CanonicalProduct,
    requirements: list[ScenarioEvidenceRequirement],
) -> list[ScenarioEvidenceRecord]:
    return [
        _project_requirement(product, requirement)
        for requirement in requirements
    ]


def _project_requirement(
    product: CanonicalProduct,
    requirement: ScenarioEvidenceRequirement,
) -> ScenarioEvidenceRecord:
    field = product.fields.get(requirement.field.value)
    if field is None:
        return _record(
            product,
            requirement,
            state=ScenarioEvidenceState.UNKNOWN,
            source_refs=[],
            reason="canonical_field_missing",
        )

    try:
        state = ScenarioEvidenceState(field.resolved_state)
    except ValueError:
        return _record(
            product,
            requirement,
            state=ScenarioEvidenceState.UNKNOWN,
            source_refs=list(field.source_refs),
            reason="canonical_state_invalid",
        )

    if state is ScenarioEvidenceState.KNOWN:
        if field.value is None:
            return _record(
                product,
                requirement,
                state=ScenarioEvidenceState.UNKNOWN,
                source_refs=list(field.source_refs),
                reason="canonical_value_missing",
            )
        if not field.source_refs:
            return _record(
                product,
                requirement,
                state=ScenarioEvidenceState.UNKNOWN,
                source_refs=[],
                reason="canonical_source_missing",
            )
        return _record(
            product,
            requirement,
            state=ScenarioEvidenceState.KNOWN,
            value=field.value,
            source_refs=list(field.source_refs),
            reason="canonical_known",
        )

    reason = {
        ScenarioEvidenceState.UNKNOWN: "canonical_unknown",
        ScenarioEvidenceState.CONFLICT: "canonical_conflict",
        ScenarioEvidenceState.NOT_APPLICABLE: (
            "canonical_not_applicable"
        ),
    }[state]
    return _record(
        product,
        requirement,
        state=state,
        source_refs=list(field.source_refs),
        reason=reason,
    )


def _record(
    product: CanonicalProduct,
    requirement: ScenarioEvidenceRequirement,
    *,
    state: ScenarioEvidenceState,
    source_refs: list[str],
    reason: str,
    value=None,
) -> ScenarioEvidenceRecord:
    return ScenarioEvidenceRecord(
        product_id=product.product_id,
        requirement_id=requirement.source.rule_id,
        field=requirement.field,
        state=state,
        value=value,
        source_refs=source_refs,
        reason=reason,
    )
