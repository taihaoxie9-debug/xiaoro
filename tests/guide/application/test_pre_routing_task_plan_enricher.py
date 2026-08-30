from __future__ import annotations

from types import SimpleNamespace

from app.guide.application.task_plan_enrichment import (
    PreRoutingTaskPlanEnricher,
)
from app.guide.intent.contracts import (
    CategoryConstraint,
    ConceptConstraint,
    EfficacyConstraint,
    TaskPlan,
)
from app.guide.retrieval.ports import CategoryRecord
from app.guide.understanding.contracts import TopicCode
from app.guide.understanding.semantic_contracts import ClarificationCode
from app.guide.understanding.scenario_parsing import (
    ScenarioCode,
    ScenarioObservation,
)


class _Catalog:
    @staticmethod
    def iter_category_records():
        return (
            CategoryRecord(
                product_id=38,
                value="精华",
                state="known",
            ),
        )


class _MixedCatalog:
    @staticmethod
    def iter_category_records():
        return (
            CategoryRecord(
                product_id=26,
                value="防晒",
                state="known",
            ),
            CategoryRecord(
                product_id=38,
                value="精华",
                state="known",
            ),
        )


class _DecisionFacts:
    @staticmethod
    def get_decision_facts(product_id: int):
        assert product_id == 38
        return SimpleNamespace(
            product_id=38,
            selection_facts=(
                SimpleNamespace(safety_role="ordinary"),
            ),
        )


class _ConceptReader:
    @staticmethod
    def project(facts):
        assert len(tuple(facts)) == 1
        return (
            SimpleNamespace(
                rank_strength=2,
                field_key="texture",
                concept_id="texture.lightweight",
                stance="supports",
            ),
        )


def _recommendation_task(
    *,
    product_ids: list[int] | None = None,
    similarity_anchor_product_id: int | None = None,
) -> TaskPlan:
    return TaskPlan(
        mode="recommend",
        recommendation_mode="explore",
        recommendation_mode_basis="similar_alternatives",
        recommendation_count=2,
        referenced_image_ids=[],
        constraints=[],
        product_ids=product_ids or [],
        similarity_anchor_product_id=similarity_anchor_product_id,
        required_evidence=["canonical_product"],
        question_meaning="查找相似精华",
    )


def test_enricher_finalizes_category_and_similarity_before_router() -> None:
    task = _recommendation_task()
    enricher = PreRoutingTaskPlanEnricher(
        category_catalog=_Catalog(),
        decision_facts=_DecisionFacts(),
        concept_reader=_ConceptReader(),
    )

    enriched = enricher.enrich(
        task,
        scenarios=(),
        context_product_ids=(38,),
        similarity_anchor_product_id=38,
    )

    assert task.constraints == []
    assert any(
        isinstance(item, CategoryConstraint)
        and item.value is TopicCode.SERUM
        for item in enriched.task_plan.constraints
    )
    assert any(
        isinstance(item, ConceptConstraint)
        and item.concept_id == "texture.lightweight"
        for item in enriched.task_plan.constraints
    )
    assert enriched.scenario_inputs is not None
    assert (
        enriched.scenario_inputs.decision.constraints
        == enriched.task_plan.constraints
    )


def test_enricher_applies_scenario_constraints_to_router_task() -> None:
    task = _recommendation_task(product_ids=[38])
    enricher = PreRoutingTaskPlanEnricher(
        category_catalog=_Catalog(),
        decision_facts=_DecisionFacts(),
        concept_reader=None,
    )

    enriched = enricher.enrich(
        task,
        scenarios=(
            ScenarioObservation(
                scenario=ScenarioCode.REPAIR,
                matched_text="修护",
            ),
        ),
    )

    assert any(
        isinstance(item, EfficacyConstraint)
        and item.value == "repair"
        for item in enriched.task_plan.constraints
    )
    assert (
        enriched.scenario_inputs is not None
        and enriched.scenario_inputs.query.query_context.category
        == "serum"
    )


def test_enricher_promotes_single_image_comparison_before_router() -> None:
    task = TaskPlan(
        mode="clarify",
        referenced_image_ids=[],
        constraints=[],
        product_ids=[],
        required_evidence=[],
        question_meaning="比较这一张图里的商品",
        clarification="商品对比需要至少两款商品。",
        clarification_code=ClarificationCode.REFERENCE,
    )
    enricher = PreRoutingTaskPlanEnricher(
        category_catalog=_Catalog(),
        decision_facts=_DecisionFacts(),
        concept_reader=None,
    )

    enriched = enricher.enrich(
        task,
        scenarios=(),
        context_product_ids=(38,),
        similarity_anchor_product_id=38,
    )

    assert enriched.task_plan.mode == "recommend"
    assert enriched.task_plan.recommendation_mode == "explore"
    assert (
        enriched.task_plan.recommendation_mode_basis
        == "similar_alternatives"
    )
    assert enriched.task_plan.recommendation_count == 3
    assert enriched.task_plan.similarity_anchor_product_id == 38
    assert enriched.scenario_inputs is not None


def test_enricher_leaves_non_recommendation_task_unchanged() -> None:
    task = TaskPlan(
        mode="knowledge",
        referenced_image_ids=[],
        constraints=[],
        product_ids=[38],
        required_evidence=["canonical_product"],
        question_meaning="这款是什么质地",
    )
    enricher = PreRoutingTaskPlanEnricher(
        category_catalog=_Catalog(),
        decision_facts=_DecisionFacts(),
        concept_reader=None,
    )

    enriched = enricher.enrich(task, scenarios=())

    assert enriched.task_plan is not task
    assert any(
        isinstance(item, CategoryConstraint)
        and item.value is TopicCode.SERUM
        for item in enriched.task_plan.constraints
    )
    assert enriched.scenario_inputs is None


def test_clarification_skips_unneeded_mixed_image_category_inference() -> None:
    task = TaskPlan(
        mode="clarify",
        referenced_image_ids=[],
        constraints=[],
        product_ids=[26, 38],
        required_evidence=[],
        clarification="请明确要看哪张图片。",
        clarification_code=ClarificationCode.REFERENCE,
    )
    enricher = PreRoutingTaskPlanEnricher(
        category_catalog=_MixedCatalog(),
        decision_facts=_DecisionFacts(),
        concept_reader=None,
    )

    enriched = enricher.enrich(
        task,
        scenarios=(),
        context_product_ids=(26, 38),
    )

    assert enriched.task_plan == task
    assert enriched.scenario_inputs is None


def test_comparison_defers_mixed_category_decision_to_processor() -> None:
    task = TaskPlan(
        mode="comparison",
        referenced_image_ids=[],
        constraints=[],
        product_ids=[26, 38],
        required_evidence=["canonical_product"],
        question_meaning="比较两张图里的商品",
    )
    enricher = PreRoutingTaskPlanEnricher(
        category_catalog=_MixedCatalog(),
        decision_facts=_DecisionFacts(),
        concept_reader=None,
    )

    enriched = enricher.enrich(
        task,
        scenarios=(),
        context_product_ids=(26, 38),
    )

    assert enriched.task_plan == task
    assert enriched.scenario_inputs is None
