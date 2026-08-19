from __future__ import annotations

from app.guide.feedback.contracts import (
    RecommendationQueryContext,
    StoredConcept,
    StoredFacet,
)
from app.guide.feedback.session_profile import SessionProfile
from app.guide.intent.contracts import (
    BudgetConstraint,
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
from app.guide.understanding.contracts import (
    EfficacyTarget,
    SkinTarget,
    TopicCode,
)


def task_plan_to_query_context(
    task: TaskPlan,
) -> RecommendationQueryContext:
    if task.mode != "recommend":
        raise ValueError("query context requires recommend task")
    category = _one_or_none(task.constraints, CategoryConstraint)
    if category is None:
        raise ValueError("query context requires category")
    budget = _one_or_none(task.constraints, BudgetConstraint)
    skin = _one_or_none(task.constraints, SkinConstraint)
    efficacy = _one_or_none(task.constraints, EfficacyConstraint)
    exclusions = [
        item.value
        for item in task.constraints
        if isinstance(item, ExclusionConstraint)
    ]
    facets = [
        StoredFacet(
            field_key=item.field_key,
            value=item.value,
        )
        for item in task.constraints
        if isinstance(item, FacetConstraint)
    ]
    concepts = [
        StoredConcept(
            field_key=item.field_key,
            concept_id=item.concept_id,
            polarity=item.polarity,
        )
        for item in task.constraints
        if isinstance(item, ConceptConstraint)
    ]
    inclusions = [
        item.value
        for item in task.constraints
        if isinstance(item, InclusionConstraint)
    ]
    return RecommendationQueryContext(
        category=category.value.value,
        budget_minimum=budget.minimum if budget else None,
        budget_maximum=budget.maximum if budget else None,
        skin=skin.value.value if skin else None,
        efficacy=efficacy.value.value if efficacy else None,
        exclusions=exclusions,
        facets=facets,
        concepts=concepts,
        similarity_anchor_product_id=(
            task.similarity_anchor_product_id
        ),
        inclusions=inclusions,
        safety_sensitive=task.safety_sensitive,
    )


def query_context_to_constraints(
    context: RecommendationQueryContext,
) -> list[TaskConstraint]:
    constraints: list[TaskConstraint] = [
        CategoryConstraint(value=TopicCode(context.category))
    ]
    if (
        context.budget_minimum is not None
        or context.budget_maximum is not None
    ):
        constraints.append(
            BudgetConstraint(
                minimum=context.budget_minimum,
                maximum=context.budget_maximum,
            )
        )
    if context.skin is not None:
        constraints.append(
            SkinConstraint(value=SkinTarget(context.skin))
        )
    if context.efficacy is not None:
        constraints.append(
            EfficacyConstraint(
                value=EfficacyTarget(context.efficacy)
            )
        )
    constraints.extend(
        ExclusionConstraint(value=value)
        for value in context.exclusions
    )
    constraints.extend(
        FacetConstraint(
            field_key=item.field_key,
            value=item.value,
        )
        for item in context.facets
    )
    constraints.extend(
        ConceptConstraint(
            field_key=item.field_key,
            concept_id=item.concept_id,
            polarity=item.polarity,
        )
        for item in context.concepts
    )
    constraints.extend(
        InclusionConstraint(value=value)
        for value in context.inclusions
    )
    return constraints


def apply_session_profile_to_task(
    task: TaskPlan,
    profile: SessionProfile,
) -> TaskPlan:
    if type(task) is not TaskPlan:
        raise TypeError("task must be an exact TaskPlan")
    if type(profile) is not SessionProfile:
        raise TypeError("profile must be an exact SessionProfile")

    constraints = list(task.constraints)
    if not any(
        isinstance(item, SkinConstraint)
        for item in constraints
    ):
        skin_target = _profile_skin_target(profile)
        if skin_target is not None:
            constraints.append(SkinConstraint(value=skin_target))

    current_inclusions = {
        item.value.casefold()
        for item in constraints
        if isinstance(item, InclusionConstraint)
    }
    current_exclusions = {
        item.value.casefold()
        for item in constraints
        if isinstance(item, ExclusionConstraint)
    }
    for restriction in profile.explicit_restrictions:
        key = restriction.value.casefold()
        if key in current_inclusions or key in current_exclusions:
            continue
        constraints.append(
            ExclusionConstraint(value=restriction.value)
        )
        current_exclusions.add(key)

    return task.model_copy(
        update={
            "constraints": constraints,
            "safety_sensitive": (
                task.safety_sensitive
                or bool(profile.current_conditions)
            ),
        },
        deep=True,
    )


def _profile_skin_target(
    profile: SessionProfile,
) -> SkinTarget | None:
    base_skin = profile.base_skin
    confirmed_base = (
        base_skin
        if (
            base_skin is not None
            and base_skin.confirmation == "confirmed"
        )
        else None
    )
    sensitive = any(
        item.value == "sensitivity"
        and item.confirmation == "confirmed"
        for item in profile.stable_tendencies
    )
    if sensitive:
        if (
            confirmed_base is not None
            and confirmed_base.value == "oily"
        ):
            return SkinTarget.OILY_SENSITIVE
        return SkinTarget.SENSITIVE
    if confirmed_base is None or confirmed_base.value == "unknown":
        return None
    return {
        "oily": SkinTarget.OILY,
        "dry": SkinTarget.DRY,
        "combination": SkinTarget.COMBINATION,
        "normal": SkinTarget.NORMAL,
    }[confirmed_base.value]


def _one_or_none(
    constraints: list[TaskConstraint],
    constraint_type: type,
):
    matches = [
        item for item in constraints
        if isinstance(item, constraint_type)
    ]
    if len(matches) > 1:
        raise ValueError(
            f"duplicate {constraint_type.__name__} constraints"
        )
    return matches[0] if matches else None
