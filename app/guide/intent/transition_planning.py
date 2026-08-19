from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.guide.feedback.contracts import RecommendationQueryContext
from app.guide.intent.constraint_transitions import (
    BoundConstraint,
    ConstraintTransitionResult,
    reduce_constraint_state,
)
from app.guide.intent.contracts import (
    CategoryConstraint,
    ConceptConstraint,
    EfficacyConstraint,
    ExclusionConstraint,
    FacetConstraint,
    InclusionConstraint,
    SkinConstraint,
    TaskConstraint,
    TaskPlan,
)
from app.guide.intent.task_planning import (
    compile_task_constraints,
    plan_task,
)
from app.guide.retrieval.ingredient_entities import (
    normalize_ingredient_entity,
)
from app.guide.understanding.contracts import (
    BudgetDraft,
    ExactRevisionConfirmation,
    ExactRevisionTarget,
    ExclusionDraft,
    SourceSpan,
    StructuredUnderstanding,
)
from app.guide.understanding.exact_parsing import (
    parse_exact_constraints,
    parse_exact_efficacy_withdrawals,
    parse_exact_revision_confirmations,
)
from app.guide.understanding.semantic_contracts import ClarificationCode


class _StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class TransitionPlanningResult(_StrictContract):
    task_plan: TaskPlan
    transition_result: ConstraintTransitionResult | None


def plan_code_owned_transitions(
    *,
    message: str,
    understanding: StructuredUnderstanding,
    task: TaskPlan,
    previous: RecommendationQueryContext | None,
    continuation_requested: bool = False,
) -> TransitionPlanningResult:
    if not isinstance(message, str) or not message:
        raise ValueError("message must be nonempty")
    if not isinstance(understanding, StructuredUnderstanding):
        raise TypeError("understanding must be StructuredUnderstanding")
    if not isinstance(task, TaskPlan):
        raise TypeError("task must be TaskPlan")
    if previous is not None and not isinstance(
        previous,
        RecommendationQueryContext,
    ):
        raise TypeError(
            "previous must be RecommendationQueryContext or None"
        )
    if not isinstance(continuation_requested, bool):
        raise TypeError("continuation_requested must be bool")
    if task.mode == "clarify":
        return TransitionPlanningResult(
            task_plan=task,
            transition_result=None,
        )

    semantic_changes = tuple(understanding.constraint_changes)
    if (
        task.mode == "followup"
        and task.product_ids
        and not task.relative_requirements
        and not semantic_changes
        and not any(
            reference.kind == "previous_constraint"
            for reference in understanding.references
        )
    ):
        return TransitionPlanningResult(
            task_plan=task,
            transition_result=None,
        )
    transition_requested = any(
        reference.kind == "previous_constraint"
        for reference in understanding.references
    ) or (
        continuation_requested
        and previous is not None
    ) or bool(semantic_changes)
    semantic_withdrawals = {
        (
            item.parent_concept,
            item.value.casefold(),
        )
        for item in semantic_changes
        if item.requested_change == "remove"
    }
    proofs = (
        ()
        if understanding.semantic_authoritative
        else tuple(
            proof
            for proof in parse_exact_revision_confirmations(message)
            if not (
                proof.target is ExactRevisionTarget.INGREDIENT_EXCLUSION
                and proof.affected_value is not None
                and (
                    "ingredient_exclusion",
                    normalize_ingredient_entity(
                        proof.affected_value
                    ).casefold(),
                )
                in semantic_withdrawals
            )
        )
    )
    withdrawn_efficacy_concepts = (
        {
            f"efficacy.{item.value}"
            for item in semantic_changes
            if (
                item.parent_concept == "efficacy"
                and item.requested_change == "remove"
            )
        }
        if understanding.semantic_authoritative
        else {
            f"efficacy.{target.value}"
            for target in parse_exact_efficacy_withdrawals(message)
        }
    )
    if not (
        task.mode == "recommend"
        or (
            task.mode == "followup"
            and (transition_requested or proofs)
        )
    ):
        return TransitionPlanningResult(
            task_plan=task,
            transition_result=None,
        )

    exact_drafts = (
        list(understanding.exact_constraints)
        if understanding.semantic_authoritative
        else parse_exact_constraints(message)[0]
    )
    if semantic_withdrawals:
        exact_drafts = [
            item
            for item in exact_drafts
            if not (
                isinstance(item, ExclusionDraft)
                and (
                    "ingredient_exclusion",
                    normalize_ingredient_entity(
                        item.value
                    ).casefold(),
                )
                in semantic_withdrawals
            )
        ]
    if not any(
        isinstance(item, BudgetDraft)
        for item in exact_drafts
    ):
        exact_drafts.extend(
            item
            for item in understanding.exact_constraints
            if isinstance(item, BudgetDraft)
        )
    exact_understanding = understanding.model_copy(
        update={
            "exact_constraints": exact_drafts,
            "preference_drafts": [],
        },
        deep=True,
    )
    exact_constraints = compile_task_constraints(exact_understanding)
    if transition_requested or proofs:
        current_understanding = understanding.model_copy(
            update={
                "preference_drafts": [
                    preference
                    for preference in understanding.preference_drafts
                    if not (
                        preference.field_key == "efficacy"
                        and preference.polarity == "avoid"
                        and preference.concept_id
                        in withdrawn_efficacy_concepts
                    )
                ],
            },
            deep=True,
        )
        current_constraints = compile_task_constraints(
            current_understanding
        )
        current_constraints = [
            constraint
            for constraint in current_constraints
            if not _matches_inherited_category(
                constraint,
                previous=previous,
            )
        ]
    else:
        current_constraints = list(task.constraints)

    result = reduce_constraint_state(
        previous=previous,
        current_constraints=tuple(
            _bind_transition_constraint(
                message=message,
                constraint=constraint,
                exact_constraints=exact_constraints,
                proofs=proofs,
            )
            for constraint in current_constraints
        ),
        revision_confirmations=proofs,
        semantic_changes=semantic_changes,
        goal=understanding.goal,
        safety_sensitive=task.safety_sensitive,
        transition_requested=transition_requested,
    )
    if result.issues:
        has_budget_transition = any(
            proof.target is ExactRevisionTarget.BUDGET
            for proof in proofs
        ) or any(
            constraint.kind == "budget"
            for constraint in current_constraints
        )
        planned = TaskPlan(
            mode="clarify",
            referenced_image_ids=[],
            constraints=list(result.constraints),
            references=list(task.references),
            product_mentions=list(task.product_mentions),
            product_ids=[],
            required_evidence=[],
            question_meaning=task.question_meaning,
            safety_sensitive=result.safety_sensitive,
            clarification=result.issues[0].detail,
            clarification_code=(
                ClarificationCode.BUDGET
                if has_budget_transition
                else ClarificationCode.CONCERN
            ),
        )
        return TransitionPlanningResult(
            task_plan=planned,
            transition_result=result,
        )
    if not any(
        isinstance(item, CategoryConstraint)
        for item in result.constraints
    ):
        planned = TaskPlan(
            mode="clarify",
            referenced_image_ids=[],
            constraints=list(result.constraints),
            references=list(task.references),
            product_mentions=list(task.product_mentions),
            product_ids=[],
            required_evidence=[],
            question_meaning=task.question_meaning,
            safety_sensitive=result.safety_sensitive,
            clarification="请明确本轮要找的商品品类。",
            clarification_code=ClarificationCode.TOPIC,
        )
        return TransitionPlanningResult(
            task_plan=planned,
            transition_result=result,
        )
    planned = task.model_copy(
        update={
            "mode": "recommend",
            "constraints": list(result.constraints),
            "product_ids": [],
            "similarity_anchor_product_id": (
                task.similarity_anchor_product_id
                or (
                    previous.similarity_anchor_product_id
                    if (
                        transition_requested
                        and previous is not None
                    )
                    else None
                )
            ),
            "required_evidence": ["canonical_product"],
            "safety_sensitive": result.safety_sensitive,
            "clarification": None,
            "clarification_code": None,
        },
        deep=True,
    )
    return TransitionPlanningResult(
        task_plan=planned,
        transition_result=result,
    )


def plan_route_transition_operations(
    *,
    message: str,
    understanding: StructuredUnderstanding,
    previous: RecommendationQueryContext | None,
    continuity_hint: Literal[
        "continue",
        "return_to_focus",
        "new_task",
        "unknown",
    ] = "unknown",
    resolved_product_ids: Sequence[int] = (),
    product_resolution_issue: Literal[
        "missing_reference",
        "ambiguous_reference",
        "invalid_source_span",
    ] | None = None,
) -> tuple[Literal["add", "retain", "replace", "remove"], ...]:
    task = plan_task(
        understanding,
        resolved_product_ids=resolved_product_ids,
        product_resolution_issue=product_resolution_issue,
        message=message,
    )
    planned = plan_code_owned_transitions(
        message=message,
        understanding=understanding,
        task=task,
        previous=previous,
        continuation_requested=continuity_hint == "continue",
    )
    if planned.transition_result is None:
        return ()
    return tuple(
        item.operation
        for item in planned.transition_result.transitions
    )


def _bind_transition_constraint(
    *,
    message: str,
    constraint: TaskConstraint,
    exact_constraints: Sequence[TaskConstraint],
    proofs: Sequence[ExactRevisionConfirmation],
) -> BoundConstraint:
    proof_target = _revision_target_for_constraint(constraint)
    proof = next(
        (
            item
            for item in proofs
            if item.target is proof_target
        ),
        None,
    )
    span = proof.source_span if proof is not None else None
    if span is None:
        raw_value = _source_value_for_constraint(constraint)
        if raw_value is not None:
            starts = _exact_substring_starts(message, raw_value)
            if len(starts) == 1:
                span = SourceSpan(
                    start=starts[0],
                    end=starts[0] + len(raw_value),
                )
    if span is None:
        span = SourceSpan(start=0, end=len(message))
    return BoundConstraint(
        constraint=constraint,
        source_span=span,
        authority=(
            "exact"
            if constraint in exact_constraints
            else "validated_semantic"
        ),
    )


def _matches_inherited_category(
    constraint: TaskConstraint,
    *,
    previous: RecommendationQueryContext | None,
) -> bool:
    return (
        previous is not None
        and isinstance(constraint, CategoryConstraint)
        and constraint.value.value == previous.category
    )


def _revision_target_for_constraint(
    constraint: TaskConstraint,
) -> ExactRevisionTarget | None:
    if isinstance(constraint, CategoryConstraint):
        return ExactRevisionTarget.CATEGORY
    if constraint.kind == "budget":
        return ExactRevisionTarget.BUDGET
    if isinstance(constraint, SkinConstraint):
        return ExactRevisionTarget.SKIN
    if isinstance(constraint, EfficacyConstraint):
        return ExactRevisionTarget.EFFICACY
    if isinstance(constraint, ExclusionConstraint):
        return ExactRevisionTarget.INGREDIENT_EXCLUSION
    if isinstance(constraint, InclusionConstraint):
        return ExactRevisionTarget.INGREDIENT_INCLUSION
    if isinstance(constraint, FacetConstraint):
        return ExactRevisionTarget.FACET
    if isinstance(constraint, ConceptConstraint):
        return ExactRevisionTarget.FACET
    return None


def _source_value_for_constraint(
    constraint: TaskConstraint,
) -> str | None:
    if isinstance(
        constraint,
        (
            ExclusionConstraint,
            InclusionConstraint,
            FacetConstraint,
        ),
    ):
        return constraint.value
    return None


def _exact_substring_starts(message: str, value: str) -> list[int]:
    starts: list[int] = []
    start = 0
    while True:
        index = message.find(value, start)
        if index < 0:
            return starts
        starts.append(index)
        start = index + 1


__all__ = [
    "TransitionPlanningResult",
    "plan_code_owned_transitions",
    "plan_route_transition_operations",
]
