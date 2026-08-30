from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.guide.application.scenario_contracts import ScenarioInputBundle
from app.guide.application.scenario_inputs import build_scenario_inputs
from app.guide.decision.ports import DecisionFactPort
from app.guide.intent.contracts import (
    CategoryConstraint,
    ConceptConstraint,
    TaskPlan,
    revalidate_task_plan,
)
from app.guide.retrieval.category_taxonomy import canonical_categories_for
from app.guide.retrieval.ports import CategoryCatalogPort
from app.guide.retrieval.selection_parent_concept_reader import (
    SelectionParentConceptReader,
)
from app.guide.understanding.contracts import TopicCode
from app.guide.understanding.scenario_parsing import ScenarioObservation


@dataclass(frozen=True, slots=True)
class PreRoutingTaskPlan:
    task_plan: TaskPlan
    scenario_inputs: ScenarioInputBundle | None


def promote_single_image_similarity_task(
    task: TaskPlan,
    *,
    similarity_anchor_product_id: int | None,
    topic: TopicCode | None = None,
) -> TaskPlan:
    if (
        similarity_anchor_product_id is None
        or task.mode != "clarify"
    ):
        return task
    constraints = list(task.constraints)
    if (
        topic is not None
        and not any(
            isinstance(item, CategoryConstraint)
            for item in constraints
        )
    ):
        constraints.append(CategoryConstraint(value=topic))
    return revalidate_task_plan(
        task,
        update={
            "mode": "recommend",
            "recommendation_mode": "explore",
            "recommendation_mode_basis": "similar_alternatives",
            "recommendation_count": 3,
            "product_ids": [],
            "required_evidence": [],
            "constraints": constraints,
            "similarity_anchor_product_id": (
                similarity_anchor_product_id
            ),
            "clarification": None,
            "clarification_code": None,
        },
    )


class PreRoutingTaskPlanEnricher:
    def __init__(
        self,
        *,
        category_catalog: CategoryCatalogPort,
        decision_facts: DecisionFactPort,
        concept_reader: SelectionParentConceptReader | None,
    ) -> None:
        self._category_catalog = category_catalog
        self._decision_facts = decision_facts
        self._concept_reader = concept_reader

    def enrich(
        self,
        task: TaskPlan,
        *,
        scenarios: Sequence[ScenarioObservation],
        context_product_ids: Sequence[int] = (),
        similarity_anchor_product_id: int | None = None,
    ) -> PreRoutingTaskPlan:
        if type(task) is not TaskPlan:
            raise TypeError("task must be an exact TaskPlan")
        if (
            isinstance(scenarios, (str, bytes))
            or not isinstance(scenarios, Sequence)
            or any(
                not isinstance(item, ScenarioObservation)
                for item in scenarios
            )
        ):
            raise TypeError(
                "scenarios must contain ScenarioObservation values"
            )
        if (
            isinstance(context_product_ids, (str, bytes))
            or not isinstance(context_product_ids, Sequence)
            or any(
                type(product_id) is not int or product_id <= 0
                for product_id in context_product_ids
            )
        ):
            raise TypeError(
                "context product IDs must be positive integers"
            )
        if (
            similarity_anchor_product_id is not None
            and (
                type(similarity_anchor_product_id) is not int
                or similarity_anchor_product_id <= 0
            )
        ):
            raise TypeError(
                "similarity anchor product ID must be positive"
            )
        enriched = promote_single_image_similarity_task(
            task,
            similarity_anchor_product_id=similarity_anchor_product_id,
        )
        if enriched.mode == "clarify":
            return PreRoutingTaskPlan(
                task_plan=enriched,
                scenario_inputs=None,
            )
        enriched = self._with_inferred_product_category(
            enriched,
            context_product_ids=tuple(context_product_ids),
        )
        enriched = self._with_similarity_concepts(
            enriched,
            anchor_product_id=similarity_anchor_product_id,
        )
        if enriched.mode != "recommend":
            return PreRoutingTaskPlan(
                task_plan=enriched,
                scenario_inputs=None,
            )
        scenario_inputs = build_scenario_inputs(
            enriched,
            scenarios=tuple(scenarios),
        )
        final_task = revalidate_task_plan(
            enriched,
            update={
                "constraints": scenario_inputs.decision.constraints,
            },
        )
        return PreRoutingTaskPlan(
            task_plan=final_task,
            scenario_inputs=scenario_inputs,
        )

    def _with_inferred_product_category(
        self,
        task: TaskPlan,
        *,
        context_product_ids: tuple[int, ...],
    ) -> TaskPlan:
        if any(
            isinstance(item, CategoryConstraint)
            for item in task.constraints
        ):
            return task
        product_ids = (
            tuple(task.product_ids)
            if task.product_ids
            else (
                (task.similarity_anchor_product_id,)
                if task.similarity_anchor_product_id is not None
                else tuple(dict.fromkeys(context_product_ids))
            )
        )
        if not product_ids:
            return task
        records = {
            record.product_id: record
            for record in self._category_catalog.iter_category_records()
        }
        canonical_categories = {
            records[product_id].value
            for product_id in product_ids
            if (
                product_id in records
                and records[product_id].state == "known"
                and records[product_id].value
            )
        }
        matching_topics = tuple(
            topic
            for topic in TopicCode
            if (
                canonical_categories
                and canonical_categories
                <= canonical_categories_for(topic)
            )
        )
        if not matching_topics and task.mode == "comparison":
            return task
        if not matching_topics:
            raise ValueError(
                "bound product category cannot be resolved"
            )
        inferred_topic = min(
            matching_topics,
            key=lambda topic: (
                len(canonical_categories_for(topic)),
                topic.value,
            ),
        )
        return revalidate_task_plan(
            task,
            update={
                "constraints": [
                    *task.constraints,
                    CategoryConstraint(value=inferred_topic),
                ],
            },
        )

    def _with_similarity_concepts(
        self,
        task: TaskPlan,
        *,
        anchor_product_id: int | None,
    ) -> TaskPlan:
        anchor_product_id = (
            task.similarity_anchor_product_id
            if task.similarity_anchor_product_id is not None
            else anchor_product_id
        )
        if anchor_product_id is None or self._concept_reader is None:
            return task
        anchor = self._decision_facts.get_decision_facts(
            anchor_product_id
        )
        if anchor.product_id != anchor_product_id:
            raise ValueError(
                "similarity anchor decision facts product mismatch"
            )
        source_facts = tuple(
            fact
            for fact in anchor.selection_facts
            if not (
                task.safety_sensitive
                and fact.safety_role == "merchant_positive_safety"
            )
        )
        projected = sorted(
            self._concept_reader.project(source_facts),
            key=lambda item: (
                -item.rank_strength,
                item.field_key,
                item.concept_id,
            ),
        )
        existing_concepts = {
            (constraint.field_key, constraint.concept_id)
            for constraint in task.constraints
            if isinstance(constraint, ConceptConstraint)
        }
        concept_count = len(existing_concepts)
        additions: list[ConceptConstraint] = []
        for fact in projected:
            key = (fact.field_key, fact.concept_id)
            if key in existing_concepts or concept_count >= 16:
                continue
            additions.append(
                ConceptConstraint(
                    field_key=fact.field_key,
                    concept_id=fact.concept_id,
                    polarity=(
                        "prefer"
                        if fact.stance == "supports"
                        else "avoid"
                    ),
                )
            )
            existing_concepts.add(key)
            concept_count += 1
        if not additions:
            return task
        return revalidate_task_plan(
            task,
            update={
                "constraints": [
                    *task.constraints,
                    *additions,
                ],
            },
        )
