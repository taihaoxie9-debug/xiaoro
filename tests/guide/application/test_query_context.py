from decimal import Decimal

import pytest

from app.guide.application.query_context import (
    apply_session_profile_to_task,
    query_context_to_constraints,
    task_plan_to_query_context,
)
from app.guide.feedback.session_profile import (
    CurrentConditionUpdate,
    ExplicitRestrictionUpdate,
    SessionProfile,
    StableTendencyUpdate,
    reduce_session_profile,
)
from app.guide.intent.contracts import (
    BudgetConstraint,
    CategoryConstraint,
    EfficacyConstraint,
    ExclusionConstraint,
    FacetConstraint,
    InclusionConstraint,
    SkinConstraint,
    TaskPlan,
)
from app.guide.intent.task_planning import plan_task
from app.guide.understanding.contracts import (
    EfficacyTarget,
    SkinTarget,
    TopicCode,
)
from app.guide.understanding.text_understanding import understand_text


def test_task_plan_round_trips_through_query_context() -> None:
    task = plan_task(
        understand_text(
            "300 到 500 元敏感肌不要酒精的修护精华"
        )
    )

    context = task_plan_to_query_context(task)
    restored = query_context_to_constraints(context)

    assert context.category == "serum"
    assert context.budget_minimum == Decimal("300")
    assert context.budget_maximum == Decimal("500")
    assert context.skin == "sensitive"
    assert context.efficacy == "repair"
    assert context.exclusions == ("酒精",)
    assert any(
        isinstance(item, CategoryConstraint)
        and item.value is TopicCode.SERUM
        for item in restored
    )
    assert any(
        isinstance(item, SkinConstraint)
        and item.value is SkinTarget.SENSITIVE
        for item in restored
    )
    assert any(
        isinstance(item, EfficacyConstraint)
        and item.value is EfficacyTarget.REPAIR
        for item in restored
    )
    assert any(
        isinstance(item, ExclusionConstraint)
        and item.value == "酒精"
        for item in restored
    )
    budget = next(
        item for item in restored
        if isinstance(item, BudgetConstraint)
    )
    assert budget.minimum == Decimal("300")
    assert budget.maximum == Decimal("500")


def test_similarity_anchor_is_preserved_in_server_query_context() -> None:
    task = TaskPlan(
        mode="recommend",
        referenced_image_ids=[],
        constraints=[
            CategoryConstraint(value=TopicCode.SUNSCREEN),
            BudgetConstraint(maximum=Decimal("130")),
        ],
        similarity_anchor_product_id=53,
        required_evidence=["canonical_product"],
    )

    context = task_plan_to_query_context(task)

    assert context.similarity_anchor_product_id == 53


@pytest.mark.parametrize("efficacy", list(EfficacyTarget))
def test_every_efficacy_round_trips_through_query_context(
    efficacy: EfficacyTarget,
) -> None:
    task = TaskPlan(
        mode="recommend",
        referenced_image_ids=[],
        constraints=[
            CategoryConstraint(value=TopicCode.SERUM),
            EfficacyConstraint(value=efficacy),
        ],
        required_evidence=["canonical_product"],
    )

    context = task_plan_to_query_context(task)
    restored = query_context_to_constraints(context)

    assert context.efficacy == efficacy.value
    assert any(
        isinstance(item, EfficacyConstraint)
        and item.value is efficacy
        for item in restored
    )


@pytest.mark.parametrize("topic", list(TopicCode))
def test_every_topic_round_trips_through_query_context(
    topic: TopicCode,
) -> None:
    task = TaskPlan(
        mode="recommend",
        referenced_image_ids=[],
        constraints=[CategoryConstraint(value=topic)],
        required_evidence=[],
        clarification=None,
    )

    context = task_plan_to_query_context(task)
    restored = query_context_to_constraints(context)

    assert context.category == topic.value
    assert restored == [CategoryConstraint(value=topic)]


def test_query_context_conversion_returns_fresh_constraints() -> None:
    task = plan_task(understand_text("500 元内敏感肌修护精华"))
    context = task_plan_to_query_context(task)

    first = query_context_to_constraints(context)
    second = query_context_to_constraints(context)

    assert first == second
    assert first is not second
    assert all(left is not right for left, right in zip(first, second))


def test_selection_constraints_and_safety_round_trip() -> None:
    task = TaskPlan(
        mode="recommend",
        referenced_image_ids=[],
        constraints=[
            CategoryConstraint(value=TopicCode.SKINCARE),
            FacetConstraint(field_key="efficacy", value="保湿"),
            FacetConstraint(field_key="efficacy", value="舒缓"),
            InclusionConstraint(value="烟酰胺"),
        ],
        required_evidence=["canonical_product"],
        safety_sensitive=True,
    )

    context = task_plan_to_query_context(task)
    restored = query_context_to_constraints(context)

    assert [
        (item.field_key, item.value)
        for item in context.facets
    ] == [
        ("efficacy", "保湿"),
        ("efficacy", "舒缓"),
    ]
    assert context.inclusions == ("烟酰胺",)
    assert context.safety_sensitive
    assert restored == task.constraints


def test_clarify_task_cannot_be_saved_as_query_context() -> None:
    task = plan_task(understand_text("500 元以内"))

    with pytest.raises(ValueError, match="recommend"):
        task_plan_to_query_context(task)


def test_confirmed_session_profile_projects_into_existing_task_inputs() -> None:
    profile = reduce_session_profile(
        previous=SessionProfile(),
        updates=(
            StableTendencyUpdate(
                value="sensitivity",
                confirmation="confirmed",
            ),
            CurrentConditionUpdate(value="redness"),
            ExplicitRestrictionUpdate(value="酒精"),
        ),
        subject_scope="self",
        source_turn_id="turn_profile_projection_0001",
        conversation_version=3,
    ).profile
    task = TaskPlan(
        mode="recommend",
        referenced_image_ids=[],
        constraints=[CategoryConstraint(value=TopicCode.SERUM)],
        required_evidence=["canonical_product"],
    )

    projected = apply_session_profile_to_task(task, profile)

    assert any(
        isinstance(item, SkinConstraint)
        and item.value is SkinTarget.SENSITIVE
        for item in projected.constraints
    )
    assert any(
        isinstance(item, ExclusionConstraint)
        and item.value == "酒精"
        for item in projected.constraints
    )
    assert projected.safety_sensitive


def test_current_turn_overrides_profile_and_provisional_is_not_ranked() -> None:
    profile = reduce_session_profile(
        previous=SessionProfile(),
        updates=(
            StableTendencyUpdate(
                value="sensitivity",
                confirmation="provisional",
            ),
            ExplicitRestrictionUpdate(value="酒精"),
        ),
        subject_scope="self",
        source_turn_id="turn_profile_projection_0002",
        conversation_version=2,
    ).profile
    task = TaskPlan(
        mode="recommend",
        referenced_image_ids=[],
        constraints=[
            CategoryConstraint(value=TopicCode.SERUM),
            SkinConstraint(value=SkinTarget.OILY),
            InclusionConstraint(value="酒精"),
        ],
        required_evidence=["canonical_product"],
    )

    projected = apply_session_profile_to_task(task, profile)

    skins = [
        item for item in projected.constraints
        if isinstance(item, SkinConstraint)
    ]
    assert skins == [SkinConstraint(value=SkinTarget.OILY)]
    assert not any(
        isinstance(item, ExclusionConstraint)
        and item.value == "酒精"
        for item in projected.constraints
    )
