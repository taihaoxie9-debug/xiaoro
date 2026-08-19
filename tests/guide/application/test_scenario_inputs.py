from __future__ import annotations

from decimal import Decimal

from app.guide.decision.contracts import (
    DecisionProductFacts,
    FactState,
    WinnerStatus,
)
from app.guide.decision.recommendation import decide_recommendation
from app.guide.intent.contracts import (
    BudgetConstraint,
    CategoryConstraint,
    EfficacyConstraint,
    SkinConstraint,
    TaskPlan,
)
from app.guide.intent.task_planning import plan_task
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.retrieval.contracts import CandidateRef, RetrievalResult
from app.guide.understanding.contracts import (
    SkinTarget,
    TopicCode,
)
from app.guide.understanding.text_understanding import understand_text


class MemoryFacts:
    def __init__(self, products: list[DecisionProductFacts]) -> None:
        self._products = {item.product_id: item for item in products}

    def get_decision_facts(
        self,
        product_id: int,
    ) -> DecisionProductFacts:
        return self._products[product_id].model_copy(deep=True)


def scenario_api():
    from app.guide.application.scenario_inputs import (
        build_scenario_inputs,
    )

    return build_scenario_inputs


def test_explicit_turn_constraints_remain_authoritative_over_scenario() -> None:
    build_scenario_inputs = scenario_api()
    task = plan_task(
        understand_text(
            "300 到 500 元干性修护精华，敏感期出差用"
        )
    )

    inputs = build_scenario_inputs(
        task,
        message="300 到 500 元干性修护精华，敏感期出差用",
    )

    assert inputs.query.query_context.category == "serum"
    assert inputs.query.query_context.budget_minimum == Decimal("300")
    assert inputs.query.query_context.budget_maximum == Decimal("500")
    assert inputs.query.query_context.skin == "dry"
    assert inputs.query.query_context.efficacy == "repair"
    assert [item.scenario.value for item in inputs.query.scenarios] == [
        "travel",
        "repair",
        "sensitive_period",
    ]
    skin_resolution = next(
        item
        for item in inputs.decision.scenario_resolutions
        if item.constraint.kind == "skin"
    )
    assert skin_resolution.status == "shadowed_by_explicit"
    assert sum(
        isinstance(item, SkinConstraint)
        for item in inputs.decision.constraints
    ) == 1
    effective_skin = next(
        item
        for item in inputs.decision.constraints
        if isinstance(item, SkinConstraint)
    )
    assert effective_skin.value is SkinTarget.DRY


def test_repair_scenario_adds_auditable_existing_decision_constraint() -> None:
    build_scenario_inputs = scenario_api()
    task = TaskPlan(
        mode="recommend",
        referenced_image_ids=[],
        constraints=[
            CategoryConstraint(value=TopicCode.SERUM),
            BudgetConstraint(maximum=Decimal("500")),
        ],
        required_evidence=["canonical_product"],
        clarification=None,
    )

    inputs = build_scenario_inputs(task, message="最近处于修护期")
    result = decide_recommendation(
        MemoryFacts(
            [
                _facts(
                    801,
                    efficacy=("修护",),
                    efficacy_state=FactState.KNOWN,
                ),
                _facts(
                    802,
                    efficacy=("美白",),
                    efficacy_state=FactState.KNOWN,
                ),
                _facts(
                    803,
                    efficacy=None,
                    efficacy_state=FactState.UNKNOWN,
                ),
            ]
        ),
        _retrieval([801, 802, 803], category="精华"),
        constraints=inputs.decision.constraints,
    )

    resolution = inputs.decision.scenario_resolutions[0]
    assert resolution.constraint.kind == "efficacy"
    assert resolution.constraint.source.rule_id == (
        "scenario-v1:repair:efficacy"
    )
    assert resolution.status == "applied"
    assert result.ordered_product_ids == [801]
    assert _evaluation(result, 802).disposition == (
        "excluded_efficacy_mismatch"
    )
    assert _evaluation(result, 803).disposition == (
        "excluded_efficacy_unknown"
    )


def test_typed_parent_withdrawal_suppresses_legacy_scenario_constraint() -> None:
    build_scenario_inputs = scenario_api()
    task = TaskPlan(
        mode="recommend",
        referenced_image_ids=[],
        constraints=[
            CategoryConstraint(value=TopicCode.SERUM),
            BudgetConstraint(maximum=Decimal("500")),
        ],
        required_evidence=["canonical_product"],
        clarification=None,
    )

    inputs = build_scenario_inputs(
        task,
        message="当前修护不再作为硬条件",
        suppressed_constraint_parents={"efficacy"},
    )

    assert not any(
        isinstance(item, EfficacyConstraint)
        for item in inputs.decision.constraints
    )
    assert inputs.decision.scenario_resolutions[0].status == (
        "suppressed_by_withdrawal"
    )


def test_sensitive_period_unknown_fact_is_not_pass_or_winner() -> None:
    build_scenario_inputs = scenario_api()
    task = TaskPlan(
        mode="recommend",
        referenced_image_ids=[],
        constraints=[
            CategoryConstraint(value=TopicCode.SERUM),
        ],
        required_evidence=["canonical_product"],
        clarification=None,
    )

    inputs = build_scenario_inputs(task, message="最近处于敏感期")
    result = decide_recommendation(
        MemoryFacts(
            [
                _facts(
                    901,
                    skin=None,
                    skin_state=FactState.UNKNOWN,
                )
            ]
        ),
        _retrieval([901], category="精华"),
        constraints=inputs.decision.constraints,
    )

    assert inputs.query.query_context.skin == "sensitive"
    assert _evaluation(result, 901).skin_match == "unknown"
    assert result.winner_status is WinnerStatus.INSUFFICIENT_FOR_WINNER
    assert result.winner_product_id is None


def test_scenario_inputs_are_strict_and_deterministically_serializable() -> None:
    build_scenario_inputs = scenario_api()
    task = plan_task(understand_text("500 元内干性户外防晒"))

    first = build_scenario_inputs(task, message="500 元内干性户外防晒")
    second = build_scenario_inputs(task, message="500 元内干性户外防晒")

    assert first.model_dump_json() == second.model_dump_json()
    assert {
        item.field.value
        for item in first.decision.evidence_requirements
    } == {"spf_pa", "water_resistance", "usage"}


def _facts(
    product_id: int,
    *,
    efficacy: tuple[str, ...] | None = None,
    efficacy_state: FactState = FactState.UNKNOWN,
    skin: tuple[str, ...] | None = ("敏感肌适用",),
    skin_state: FactState = FactState.KNOWN,
) -> DecisionProductFacts:
    return DecisionProductFacts(
        product_id=product_id,
        category_profile=CategoryProfile.SKINCARE,
        category_fields=(),
        price=Decimal("100"),
        price_state=FactState.KNOWN,
        efficacy=efficacy,
        efficacy_state=efficacy_state,
        suitable_skin=skin,
        suitable_skin_state=skin_state,
        ingredients_present=("水",),
        ingredients_present_state=FactState.KNOWN,
        verified_absences=None,
        verified_absences_state=FactState.UNKNOWN,
    )


def _retrieval(
    product_ids: list[int],
    *,
    category: str,
) -> RetrievalResult:
    return RetrievalResult(
        candidates=[
            CandidateRef(
                product_id=product_id,
                source="canonical",
                canonical_category=category,
                retrieval_reason="scenario-input-test",
            )
            for product_id in product_ids
        ],
        knowledge_evidence=[],
        review_evidence=[],
        memory_evidence=[],
        missing_sources=[],
    )


def _evaluation(result, product_id: int):
    return next(
        item
        for item in result.evaluations
        if item.product_id == product_id
    )
