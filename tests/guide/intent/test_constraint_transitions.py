from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from app.guide.feedback.contracts import (
    RecommendationQueryContext,
    StoredFacet,
)
from app.guide.intent.constraint_transitions import (
    BoundConstraint,
    reduce_constraint_state,
)
from app.guide.intent.contracts import (
    BudgetConstraint,
    CategoryConstraint,
    EfficacyConstraint,
    ExclusionConstraint,
    FacetConstraint,
    InclusionConstraint,
    SkinConstraint,
    TaskConstraint,
)
from app.guide.understanding.contracts import (
    ConstraintChangeDraft,
    EfficacyTarget,
    ExactRevisionConfirmation,
    ExactRevisionOperation,
    ExactRevisionTarget,
    SkinTarget,
    SourceSpan,
    TopicCode,
    UnderstandingGoal,
)
from app.guide.understanding.exact_parsing import (
    parse_exact_constraints,
    parse_exact_revision_confirmations,
)


TRANSITION_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "guide"
    / "intent"
    / "transition_metamorphic_v1.jsonl"
)
TASK_CONSTRAINT_ADAPTER = TypeAdapter(TaskConstraint)


def _bound(
    constraint: TaskConstraint,
    *,
    start: int = 0,
    end: int = 2,
    authority: str = "exact",
) -> BoundConstraint:
    return BoundConstraint(
        constraint=constraint,
        source_span=SourceSpan(start=start, end=end),
        authority=authority,
    )


def _proof(
    *,
    target: ExactRevisionTarget,
    operation: ExactRevisionOperation = (
        ExactRevisionOperation.REVISE_CONSTRAINT
    ),
    affected_value: str | None = None,
    affected_field_key: str | None = None,
) -> ExactRevisionConfirmation:
    return ExactRevisionConfirmation(
        operation=operation,
        target=target,
        source_span=SourceSpan(start=0, end=4),
        affected_value=affected_value,
        affected_field_key=affected_field_key,
    )


def _previous() -> RecommendationQueryContext:
    return RecommendationQueryContext(
        category="sunscreen",
        recommendation_mode_basis="broad_exploration",
        budget_maximum=Decimal("500"),
        skin="sensitive",
        efficacy="repair",
        exclusions=("酒精", "香精"),
        inclusions=("烟酰胺",),
        facets=(
            StoredFacet(field_key="texture", value="清爽"),
        ),
        safety_sensitive=True,
    )


@pytest.mark.parametrize(
    ("current", "target", "proof_target"),
    (
        (
            CategoryConstraint(value=TopicCode.SERUM),
            "category",
            ExactRevisionTarget.CATEGORY,
        ),
        (
            BudgetConstraint(maximum=Decimal("300")),
            "budget",
            ExactRevisionTarget.BUDGET,
        ),
        (
            SkinConstraint(value=SkinTarget.OILY),
            "skin",
            ExactRevisionTarget.SKIN,
        ),
        (
            EfficacyConstraint(value=EfficacyTarget.HYDRATION),
            "efficacy",
            ExactRevisionTarget.EFFICACY,
        ),
    ),
)
def test_single_value_slot_requires_exact_proof_to_replace(
    current: TaskConstraint,
    target: str,
    proof_target: ExactRevisionTarget,
) -> None:
    without_proof = reduce_constraint_state(
        previous=_previous(),
        current_constraints=(_bound(current),),
        revision_confirmations=(),
        goal=UnderstandingGoal.FOLLOWUP,
    )

    assert without_proof.constraints != (current,)
    assert without_proof.transitions == ()
    assert [
        issue.code for issue in without_proof.issues
    ] == ["confirm_hard_constraint_revision"]

    with_proof = reduce_constraint_state(
        previous=_previous(),
        current_constraints=(_bound(current),),
        revision_confirmations=(
            _proof(target=proof_target),
        ),
        goal=UnderstandingGoal.FOLLOWUP,
    )

    transition = next(
        item for item in with_proof.transitions
        if item.target == target
    )
    assert transition.operation == "replace"
    assert transition.after == current
    assert transition.authority == "exact"


def test_restated_value_is_retain_and_unmentioned_values_survive() -> None:
    result = reduce_constraint_state(
        previous=_previous(),
        current_constraints=(
            _bound(
                BudgetConstraint(maximum=Decimal("500")),
            ),
            _bound(ExclusionConstraint(value="酒精"), start=3, end=5),
        ),
        revision_confirmations=(),
        goal=UnderstandingGoal.FOLLOWUP,
    )

    assert [
        (item.target, item.operation)
        for item in result.transitions
    ] == [
        ("budget", "retain"),
        ("exclusion:酒精", "retain"),
    ]
    assert result.constraints == (
        CategoryConstraint(value=TopicCode.SUNSCREEN),
        BudgetConstraint(maximum=Decimal("500")),
        SkinConstraint(value=SkinTarget.SENSITIVE),
        EfficacyConstraint(value=EfficacyTarget.REPAIR),
        ExclusionConstraint(value="酒精"),
        ExclusionConstraint(value="香精"),
        FacetConstraint(field_key="texture", value="清爽"),
        InclusionConstraint(value="烟酰胺"),
    )


def test_multi_value_add_and_duplicate_are_deterministic() -> None:
    result = reduce_constraint_state(
        previous=_previous(),
        current_constraints=(
            _bound(ExclusionConstraint(value="防腐剂")),
            _bound(ExclusionConstraint(value="防腐剂")),
            _bound(
                FacetConstraint(
                    field_key="texture",
                    value="轻薄",
                ),
                start=3,
                end=5,
                authority="validated_semantic",
            ),
        ),
        revision_confirmations=(),
        goal=UnderstandingGoal.FOLLOWUP,
    )

    assert [
        (item.target, item.operation)
        for item in result.transitions
    ] == [
        ("exclusion:防腐剂", "add"),
        ("facet:texture:轻薄", "add"),
    ]
    assert sum(
        isinstance(item, ExclusionConstraint)
        and item.value == "防腐剂"
        for item in result.constraints
    ) == 1


def test_named_multi_value_withdrawal_removes_only_that_value() -> None:
    result = reduce_constraint_state(
        previous=_previous(),
        current_constraints=(),
        revision_confirmations=(
            _proof(
                target=ExactRevisionTarget.INGREDIENT_EXCLUSION,
                operation=ExactRevisionOperation.WITHDRAW_CONSTRAINT,
                affected_value="酒精",
            ),
        ),
        goal=UnderstandingGoal.FOLLOWUP,
    )

    assert ExclusionConstraint(value="酒精") not in result.constraints
    assert ExclusionConstraint(value="香精") in result.constraints
    assert [
        (item.target, item.operation)
        for item in result.transitions
    ] == [("exclusion:酒精", "remove")]
    assert result.issues == ()


def test_withdrawal_proof_does_not_readd_same_surface_constraint() -> None:
    result = reduce_constraint_state(
        previous=_previous(),
        current_constraints=(
            _bound(ExclusionConstraint(value="酒精")),
        ),
        revision_confirmations=(
            _proof(
                target=ExactRevisionTarget.INGREDIENT_EXCLUSION,
                operation=ExactRevisionOperation.WITHDRAW_CONSTRAINT,
                affected_value="酒精",
            ),
        ),
        goal=UnderstandingGoal.FOLLOWUP,
        transition_requested=True,
    )

    assert ExclusionConstraint(value="酒精") not in result.constraints
    assert ExclusionConstraint(value="香精") in result.constraints
    assert [
        (item.target, item.operation)
        for item in result.transitions
    ] == [("exclusion:酒精", "remove")]
    assert result.issues == ()


def test_target_only_multi_value_withdrawal_fails_closed() -> None:
    result = reduce_constraint_state(
        previous=_previous(),
        current_constraints=(),
        revision_confirmations=(
            _proof(
                target=ExactRevisionTarget.INGREDIENT_EXCLUSION,
                operation=ExactRevisionOperation.WITHDRAW_CONSTRAINT,
            ),
        ),
        goal=UnderstandingGoal.FOLLOWUP,
    )

    assert ExclusionConstraint(value="酒精") in result.constraints
    assert ExclusionConstraint(value="香精") in result.constraints
    assert result.transitions == ()
    assert [
        issue.code for issue in result.issues
    ] == ["confirm_hard_constraint_revision"]


def test_conflicting_current_single_values_fail_closed() -> None:
    result = reduce_constraint_state(
        previous=_previous(),
        current_constraints=(
            _bound(BudgetConstraint(maximum=Decimal("300"))),
            _bound(BudgetConstraint(maximum=Decimal("400"))),
        ),
        revision_confirmations=(
            _proof(target=ExactRevisionTarget.BUDGET),
        ),
        goal=UnderstandingGoal.FOLLOWUP,
    )

    assert BudgetConstraint(maximum=Decimal("500")) in result.constraints
    assert result.transitions == ()
    assert [
        issue.code for issue in result.issues
    ] == ["ambiguous_revision_target"]


def test_fresh_recommendation_does_not_inherit_snapshot() -> None:
    result = reduce_constraint_state(
        previous=_previous(),
        current_constraints=(
            _bound(CategoryConstraint(value=TopicCode.SKINCARE)),
        ),
        revision_confirmations=(),
        goal=UnderstandingGoal.RECOMMENDATION,
    )

    assert result.constraints == (
        CategoryConstraint(value=TopicCode.SKINCARE),
    )
    assert [
        (item.target, item.operation)
        for item in result.transitions
    ] == [("category", "add")]
    assert result.issues == ()


def test_category_replace_drops_old_category_facets_only() -> None:
    result = reduce_constraint_state(
        previous=_previous(),
        current_constraints=(
            _bound(CategoryConstraint(value=TopicCode.SERUM)),
        ),
        revision_confirmations=(
            _proof(target=ExactRevisionTarget.CATEGORY),
        ),
        goal=UnderstandingGoal.RECOMMENDATION,
    )

    assert CategoryConstraint(value=TopicCode.SERUM) in result.constraints
    assert not any(
        isinstance(item, (SkinConstraint, EfficacyConstraint, FacetConstraint))
        for item in result.constraints
    )
    assert BudgetConstraint(maximum=Decimal("500")) in result.constraints
    assert ExclusionConstraint(value="酒精") in result.constraints


def test_semantic_candidate_cannot_weaken_safety_state() -> None:
    result = reduce_constraint_state(
        previous=_previous(),
        current_constraints=(
            _bound(
                FacetConstraint(
                    field_key="suitable_skin",
                    value="敏感肌",
                ),
                authority="validated_semantic",
            ),
        ),
        revision_confirmations=(),
        goal=UnderstandingGoal.FOLLOWUP,
        safety_sensitive=False,
    )

    assert result.safety_sensitive
    assert result.issues == ()


def test_transition_reference_without_value_or_proof_clarifies() -> None:
    result = reduce_constraint_state(
        previous=_previous(),
        current_constraints=(),
        revision_confirmations=(),
        goal=UnderstandingGoal.FOLLOWUP,
        transition_requested=True,
    )

    assert result.constraints == tuple(
        item
        for item in result.constraints
    )
    assert result.transitions == ()
    assert [
        issue.code for issue in result.issues
    ] == ["confirm_hard_constraint_revision"]


def test_transition_reference_with_only_unchanged_category_clarifies() -> None:
    result = reduce_constraint_state(
        previous=_previous(),
        current_constraints=(
            _bound(CategoryConstraint(value=TopicCode.SUNSCREEN)),
        ),
        revision_confirmations=(),
        goal=UnderstandingGoal.FOLLOWUP,
        transition_requested=True,
    )

    assert [
        issue.code for issue in result.issues
    ] == ["confirm_hard_constraint_revision"]


def test_remove_old_efficacy_plus_new_value_collapses_to_replace() -> None:
    result = reduce_constraint_state(
        previous=_previous().model_copy(
            update={"efficacy": "anti_aging"},
            deep=True,
        ),
        current_constraints=(
            _bound(
                CategoryConstraint(value=TopicCode.SUNSCREEN),
                authority="validated_semantic",
            ),
            _bound(
                EfficacyConstraint(value=EfficacyTarget.REPAIR),
                authority="validated_semantic",
            ),
        ),
        revision_confirmations=(),
        semantic_changes=(
            ConstraintChangeDraft(
                parent_concept="efficacy",
                requested_change="remove",
                value="anti_aging",
                source_span=SourceSpan(start=0, end=2),
            ),
        ),
        goal=UnderstandingGoal.RECOMMENDATION,
        transition_requested=True,
    )

    efficacy = [
        item
        for item in result.transitions
        if item.target == "efficacy"
    ]
    assert [(item.operation, item.authority) for item in efficacy] == [
        ("replace", "validated_semantic"),
    ]
    assert EfficacyConstraint(
        value=EfficacyTarget.REPAIR
    ) in result.constraints


def test_proof_value_must_match_replacement_value() -> None:
    result = reduce_constraint_state(
        previous=_previous(),
        current_constraints=(
            _bound(SkinConstraint(value=SkinTarget.OILY)),
        ),
        revision_confirmations=(
            _proof(
                target=ExactRevisionTarget.SKIN,
                affected_value=SkinTarget.DRY.value,
            ),
        ),
        goal=UnderstandingGoal.FOLLOWUP,
    )

    assert SkinConstraint(value=SkinTarget.SENSITIVE) in result.constraints
    assert SkinConstraint(value=SkinTarget.OILY) not in result.constraints
    assert result.transitions == ()
    assert [
        issue.code for issue in result.issues
    ] == ["confirm_hard_constraint_revision"]


def test_frozen_transition_metamorphic_cases_match_code_owned_state(
) -> None:
    rows = [
        json.loads(line)
        for line in TRANSITION_FIXTURE.read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]

    assert [row["case_id"] for row in rows] == [
        "retain-alcohol-change-budget",
        "unmentioned-exclusion-survives",
        "repeat-is-idempotent",
        "fresh-does-not-inherit",
    ]
    for row in rows:
        message = row["message"]
        previous = RecommendationQueryContext.model_validate_json(
            json.dumps(row["before"], ensure_ascii=False),
            strict=True,
        )
        parsed, issues = parse_exact_constraints(message)
        assert issues == []
        result = reduce_constraint_state(
            previous=previous,
            current_constraints=tuple(
                _bound(
                    TASK_CONSTRAINT_ADAPTER.validate_python(
                        constraint.model_dump(),
                        strict=True,
                    ),
                    start=0,
                    end=len(message),
                )
                for constraint in parsed
            ),
            revision_confirmations=tuple(
                parse_exact_revision_confirmations(message)
            ),
            goal=UnderstandingGoal(row["goal"]),
        )

        assert result.issues == ()
        expected = row["expected"]
        actual = RecommendationQueryContext(
            category=next(
                constraint.value.value
                for constraint in result.constraints
                if isinstance(constraint, CategoryConstraint)
            ),
            recommendation_mode_basis="broad_exploration",
            budget_maximum=next(
                (
                    constraint.maximum
                    for constraint in result.constraints
                    if isinstance(constraint, BudgetConstraint)
                ),
                None,
            ),
            exclusions=tuple(
                constraint.value
                for constraint in result.constraints
                if isinstance(constraint, ExclusionConstraint)
            ),
        )
        assert actual.model_dump(mode="json") == expected["state"]
        assert [
            [transition.target, transition.operation]
            for transition in result.transitions
        ] == expected["operations"]
