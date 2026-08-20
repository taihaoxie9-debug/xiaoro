from __future__ import annotations

from typing import Any

import pytest

from app.guide.retrieval.contracts import CanonicalField, CanonicalProduct


def scenario_api():
    from app.guide.retrieval.scenario_contracts import (
        ScenarioEvidenceField,
        ScenarioEvidenceState,
    )
    from app.guide.retrieval.scenario_evidence import (
        project_scenario_evidence,
    )
    from app.guide.retrieval.scenario_rules import (
        compile_scenario_requirements,
    )
    from app.guide.understanding.scenario_parsing import parse_scenarios

    return (
        ScenarioEvidenceField,
        ScenarioEvidenceState,
        compile_scenario_requirements,
        parse_scenarios,
        project_scenario_evidence,
    )


@pytest.mark.parametrize(
    ("message", "constraint_kinds", "evidence_fields"),
    [
        ("通勤防晒", [], {"spf_pa", "texture"}),
        ("旅行带什么", [], {"usage", "texture"}),
        (
            "长时间户外",
            [],
            {"spf_pa", "water_resistance", "usage"},
        ),
        ("处于修护期", [("efficacy", "repair")], {"efficacy"}),
        (
            "处于敏感期",
            [("skin", "sensitive")],
            {"suitable_skin"},
        ),
    ],
)
def test_each_scenario_compiles_only_sourced_explainable_requirements(
    message: str,
    constraint_kinds: list[tuple[str, str]],
    evidence_fields: set[str],
) -> None:
    (
        _,
        _,
        compile_requirements,
        parse_scenarios,
        _,
    ) = scenario_api()

    projection = compile_requirements(parse_scenarios(message))

    assert [
        (item.kind, item.value.value)
        for item in projection.constraints
    ] == constraint_kinds
    assert {
        item.field.value for item in projection.evidence_requirements
    } == evidence_fields
    for item in [
        *projection.constraints,
        *projection.evidence_requirements,
    ]:
        assert item.source.rule_id.startswith("scenario-v1:")
        assert item.source.matched_text in message
        assert item.rationale.strip()
    assert all(
        item.unknown_policy == "preserve_unknown"
        and item.claim_policy == "evidence_only"
        for item in projection.evidence_requirements
    )


def test_scenario_rules_have_no_product_winner_or_score_authority() -> None:
    (
        _,
        _,
        compile_requirements,
        parse_scenarios,
        _,
    ) = scenario_api()

    projection = compile_requirements(
        parse_scenarios("通勤旅行、户外修护期和敏感期")
    )
    dumped = projection.model_dump(mode="json")

    forbidden_keys = {
        "product_id",
        "winner",
        "winner_product_id",
        "score",
        "passed",
        "is_safe",
    }
    assert forbidden_keys.isdisjoint(_all_keys(dumped))


def test_canonical_unknown_and_missing_scenario_facts_stay_unknown() -> None:
    (
        ScenarioEvidenceField,
        ScenarioEvidenceState,
        compile_requirements,
        parse_scenarios,
        project_evidence,
    ) = scenario_api()
    requirements = compile_requirements(
        parse_scenarios("长时间户外徒步")
    ).evidence_requirements
    product = CanonicalProduct(
        product_id=701,
        schema_version="canonical-decision-product-v1",
        fields={
            "spf_pa": _field(
                "spf_pa",
                value="SPF50+ / PA++++",
                state="known",
                source_refs=["canonical#701:spf_pa"],
            ),
            "water_resistance": _field(
                "water_resistance",
                value=None,
                state="unknown",
                source_refs=[],
            ),
        },
    )

    evidence = project_evidence(product, requirements)
    by_field = {item.field: item for item in evidence}

    assert by_field[ScenarioEvidenceField.SPF_PA].state is (
        ScenarioEvidenceState.KNOWN
    )
    assert by_field[ScenarioEvidenceField.SPF_PA].value == (
        "SPF50+ / PA++++"
    )
    assert by_field[ScenarioEvidenceField.WATER_RESISTANCE].state is (
        ScenarioEvidenceState.UNKNOWN
    )
    assert by_field[ScenarioEvidenceField.WATER_RESISTANCE].value is None
    assert by_field[ScenarioEvidenceField.WATER_RESISTANCE].reason == (
        "canonical_unknown"
    )
    assert by_field[ScenarioEvidenceField.USAGE].state is (
        ScenarioEvidenceState.UNKNOWN
    )
    assert by_field[ScenarioEvidenceField.USAGE].value is None
    assert by_field[ScenarioEvidenceField.USAGE].reason == (
        "canonical_field_missing"
    )
    assert all(not hasattr(item, "passed") for item in evidence)


def test_known_value_without_source_ref_fails_closed_to_unknown() -> None:
    (
        _,
        ScenarioEvidenceState,
        compile_requirements,
        parse_scenarios,
        project_evidence,
    ) = scenario_api()
    requirement = compile_requirements(
        parse_scenarios("通勤")
    ).evidence_requirements[0]
    product = CanonicalProduct(
        product_id=702,
        schema_version="canonical-decision-product-v1",
        fields={
            requirement.field.value: _field(
                requirement.field.value,
                value="unattributed claim",
                state="known",
                source_refs=[],
            )
        },
    )

    evidence = project_evidence(product, [requirement])

    assert evidence[0].state is ScenarioEvidenceState.UNKNOWN
    assert evidence[0].value is None
    assert evidence[0].reason == "canonical_source_missing"


def _field(
    key: str,
    *,
    value: Any,
    state: str,
    source_refs: list[str],
) -> CanonicalField:
    return CanonicalField(
        key=key,
        value=value,
        field_origin="reviewed_decision",
        resolved_state=state,
        source_classes=["approved_fact"] if source_refs else [],
        source_refs=source_refs,
        evidence_status=(
            "approved_fact" if source_refs else "needs_evidence"
        ),
    )


def _all_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            key
            for item in value.values()
            for key in _all_keys(item)
        }
    if isinstance(value, list):
        return {
            key
            for item in value
            for key in _all_keys(item)
        }
    return set()
