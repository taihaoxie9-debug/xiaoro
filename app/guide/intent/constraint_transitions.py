from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.guide.feedback.contracts import RecommendationQueryContext
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
    UnderstandingIssue,
)


class _StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class BoundConstraint(_StrictContract):
    constraint: TaskConstraint
    source_span: SourceSpan
    authority: Literal["exact", "validated_semantic"]


class ConstraintTransition(_StrictContract):
    target: str
    operation: Literal["add", "retain", "replace", "remove"]
    before: TaskConstraint | None
    after: TaskConstraint | None
    source_span: SourceSpan
    authority: Literal["exact", "validated_semantic"]


class ConstraintTransitionResult(_StrictContract):
    constraints: tuple[TaskConstraint, ...]
    transitions: tuple[ConstraintTransition, ...]
    issues: tuple[UnderstandingIssue, ...]
    safety_sensitive: bool


_SINGLE_TARGET_BY_IDENTITY = {
    "category": ExactRevisionTarget.CATEGORY,
    "budget": ExactRevisionTarget.BUDGET,
    "skin": ExactRevisionTarget.SKIN,
    "efficacy": ExactRevisionTarget.EFFICACY,
}
_CATEGORY_SCOPED_TYPES = (
    SkinConstraint,
    EfficacyConstraint,
    FacetConstraint,
    ConceptConstraint,
)


def reduce_constraint_state(
    *,
    previous: RecommendationQueryContext | None,
    current_constraints: Sequence[BoundConstraint],
    revision_confirmations: Sequence[ExactRevisionConfirmation],
    semantic_changes: Sequence[ConstraintChangeDraft] = (),
    goal: UnderstandingGoal,
    safety_sensitive: bool = False,
    transition_requested: bool = False,
) -> ConstraintTransitionResult:
    if previous is not None and not isinstance(
        previous,
        RecommendationQueryContext,
    ):
        raise TypeError(
            "previous must be a RecommendationQueryContext or None"
        )
    if (
        isinstance(current_constraints, (str, bytes))
        or not isinstance(current_constraints, Sequence)
        or any(
            not isinstance(item, BoundConstraint)
            for item in current_constraints
        )
    ):
        raise TypeError(
            "current_constraints must contain BoundConstraint values"
        )
    if (
        isinstance(revision_confirmations, (str, bytes))
        or not isinstance(revision_confirmations, Sequence)
        or any(
            not isinstance(item, ExactRevisionConfirmation)
            for item in revision_confirmations
        )
    ):
        raise TypeError(
            "revision_confirmations must contain exact proofs"
        )
    if (
        isinstance(semantic_changes, (str, bytes))
        or not isinstance(semantic_changes, Sequence)
        or any(
            not isinstance(item, ConstraintChangeDraft)
            for item in semantic_changes
        )
    ):
        raise TypeError(
            "semantic_changes must contain ConstraintChangeDraft values"
        )
    if not isinstance(goal, UnderstandingGoal):
        raise TypeError("goal must be an UnderstandingGoal")
    if not isinstance(safety_sensitive, bool):
        raise TypeError("safety_sensitive must be bool")
    if not isinstance(transition_requested, bool):
        raise TypeError("transition_requested must be bool")

    current, issues = _normalize_current(current_constraints)
    has_current_transition_value = _has_current_transition_value(
        current,
        previous=previous,
    )
    if (
        transition_requested
        and not has_current_transition_value
        and not revision_confirmations
        and not semantic_changes
    ):
        _append_issue(
            issues,
            code="confirm_hard_constraint_revision",
            detail=(
                "已识别到修改既有条件的意图，但本轮没有给出"
                "可验证的新值，请明确要改成什么。"
            ),
        )
    inherit_previous = (
        previous is not None
        and (
            goal is UnderstandingGoal.FOLLOWUP
            or bool(revision_confirmations)
            or bool(semantic_changes)
            or transition_requested
        )
    )
    state = {
        _constraint_identity(item): item
        for item in (
            _context_constraints(previous)
            if inherit_previous and previous is not None
            else ()
        )
    }
    transitions: list[ConstraintTransition] = []

    if inherit_previous:
        _apply_withdrawals(
            state=state,
            proofs=revision_confirmations,
            transitions=transitions,
            issues=issues,
        )
        _apply_semantic_changes(
            state=state,
            changes=semantic_changes,
            current=current,
            transitions=transitions,
        )

    for bound in sorted(
        current,
        key=lambda item: _constraint_sort_key(item.constraint),
    ):
        constraint = bound.constraint
        identity = _constraint_identity(constraint)
        if any(
            proof.operation
            is ExactRevisionOperation.WITHDRAW_CONSTRAINT
            and _withdrawal_identity(proof) == identity
            for proof in revision_confirmations
        ):
            continue
        before = state.get(identity)
        if before is None:
            state[identity] = constraint
            transitions.append(
                ConstraintTransition(
                    target=identity,
                    operation="add",
                    before=None,
                    after=constraint,
                    source_span=bound.source_span,
                    authority=bound.authority,
                )
            )
            continue
        if before == constraint:
            transitions.append(
                ConstraintTransition(
                    target=identity,
                    operation="retain",
                    before=before,
                    after=before,
                    source_span=bound.source_span,
                    authority=bound.authority,
                )
            )
            continue

        proof_target = _SINGLE_TARGET_BY_IDENTITY.get(identity)
        if proof_target is None:
            raise AssertionError(
                "multi-value identities must include their value"
            )
        proof = _matching_proof(
            revision_confirmations,
            operation=ExactRevisionOperation.REVISE_CONSTRAINT,
            target=proof_target,
        )
        if (
            proof is not None
            and not _proof_matches_constraint_value(
                proof,
                constraint=constraint,
            )
        ):
            proof = None
        validated_continuing_budget = (
            transition_requested
            and isinstance(constraint, BudgetConstraint)
        )
        semantic_change = _matching_semantic_change(
            semantic_changes,
            constraint=constraint,
            before=before,
        )
        if (
            proof is None
            and semantic_change is None
            and not validated_continuing_budget
        ):
            _append_issue(
                issues,
                code="confirm_hard_constraint_revision",
                detail=(
                    f"{identity} 的新值缺少精确修改证明，"
                    "已保留原条件。"
                ),
            )
            continue

        state[identity] = constraint
        transitions.append(
            ConstraintTransition(
                target=identity,
                operation="replace",
                before=before,
                after=constraint,
                source_span=(
                    semantic_change.source_span
                    if semantic_change is not None
                    else bound.source_span
                ),
                authority=(
                    "validated_semantic"
                    if semantic_change is not None
                    else bound.authority
                ),
            )
        )
        if identity == "category":
            _drop_old_category_scope(state)
        elif (
            identity == "efficacy"
            and isinstance(before, EfficacyConstraint)
        ):
            _drop_efficacy_concept(state, before.value)

    return ConstraintTransitionResult(
        constraints=tuple(
            sorted(state.values(), key=_constraint_sort_key)
        ),
        transitions=tuple(
            sorted(transitions, key=_transition_sort_key)
        ),
        issues=tuple(issues),
        safety_sensitive=(
            previous.safety_sensitive or safety_sensitive
            if inherit_previous and previous is not None
            else safety_sensitive
        ),
    )


def _normalize_current(
    current: Sequence[BoundConstraint],
) -> tuple[list[BoundConstraint], list[UnderstandingIssue]]:
    by_identity: dict[str, BoundConstraint] = {}
    issues: list[UnderstandingIssue] = []
    invalid_identities: set[str] = set()
    for bound in current:
        identity = _constraint_identity(bound.constraint)
        existing = by_identity.get(identity)
        if existing is None:
            by_identity[identity] = bound
            continue
        if existing.constraint == bound.constraint:
            continue
        invalid_identities.add(identity)
        _append_issue(
            issues,
            code="ambiguous_revision_target",
            detail=(
                f"本轮对 {identity} 给出多个不同值，"
                "已保持旧状态并请求确认。"
            ),
        )
    return (
        [
            bound
            for identity, bound in by_identity.items()
            if identity not in invalid_identities
        ],
        issues,
    )


def _has_current_transition_value(
    current: Sequence[BoundConstraint],
    *,
    previous: RecommendationQueryContext | None,
) -> bool:
    for bound in current:
        constraint = bound.constraint
        if (
            isinstance(constraint, CategoryConstraint)
            and previous is not None
            and constraint.value.value == previous.category
        ):
            continue
        return True
    return False


def _apply_withdrawals(
    *,
    state: dict[str, TaskConstraint],
    proofs: Sequence[ExactRevisionConfirmation],
    transitions: list[ConstraintTransition],
    issues: list[UnderstandingIssue],
) -> None:
    for proof in proofs:
        if (
            proof.operation
            is not ExactRevisionOperation.WITHDRAW_CONSTRAINT
        ):
            continue
        identity = _withdrawal_identity(proof)
        if identity is None:
            _append_issue(
                issues,
                code="confirm_hard_constraint_revision",
                detail=(
                    "多值条件的删除证明没有绑定具体值，"
                    "已保持原条件。"
                ),
            )
            continue
        before = state.pop(identity, None)
        if before is None:
            continue
        if (
            proof.target is ExactRevisionTarget.EFFICACY
            and isinstance(before, EfficacyConstraint)
        ):
            _drop_efficacy_concept(state, before.value)
        transitions.append(
            ConstraintTransition(
                target=identity,
                operation="remove",
                before=before,
                after=None,
                source_span=proof.source_span,
                authority="exact",
            )
        )


def _withdrawal_identity(
    proof: ExactRevisionConfirmation,
) -> str | None:
    single = {
        ExactRevisionTarget.CATEGORY: "category",
        ExactRevisionTarget.BUDGET: "budget",
        ExactRevisionTarget.SKIN: "skin",
        ExactRevisionTarget.EFFICACY: "efficacy",
    }.get(proof.target)
    if single is not None:
        return single
    if proof.affected_value is None:
        return None
    normalized = proof.affected_value.casefold()
    if proof.target is ExactRevisionTarget.INGREDIENT_EXCLUSION:
        return f"exclusion:{normalized}"
    if proof.target is ExactRevisionTarget.INGREDIENT_INCLUSION:
        return f"inclusion:{normalized}"
    if (
        proof.target is ExactRevisionTarget.FACET
        and proof.affected_field_key is not None
    ):
        return (
            f"facet:{proof.affected_field_key}:"
            f"{normalized}"
        )
    return None


def _apply_semantic_changes(
    *,
    state: dict[str, TaskConstraint],
    changes: Sequence[ConstraintChangeDraft],
    current: Sequence[BoundConstraint],
    transitions: list[ConstraintTransition],
) -> None:
    replaced_parents = {
        change.parent_concept
        for change in changes
        if change.requested_change == "replace"
    }
    current_efficacies = {
        bound.constraint.value.value
        for bound in current
        if isinstance(bound.constraint, EfficacyConstraint)
    }
    for change in changes:
        if change.requested_change != "remove":
            continue
        if change.parent_concept == "ingredient_exclusion":
            identity = f"exclusion:{change.value.casefold()}"
        elif (
            change.parent_concept == "efficacy"
            and "efficacy" not in replaced_parents
            and not (
                current_efficacies
                and change.value not in current_efficacies
            )
        ):
            identity = "efficacy"
        else:
            continue
        before = state.pop(identity, None)
        if before is None:
            continue
        if (
            isinstance(before, EfficacyConstraint)
            and before.value.value != change.value
        ):
            state[identity] = before
            continue
        if isinstance(before, EfficacyConstraint):
            _drop_efficacy_concept(state, before.value)
        transitions.append(
            ConstraintTransition(
                target=identity,
                operation="remove",
                before=before,
                after=None,
                source_span=change.source_span,
                authority="validated_semantic",
            )
        )


def _matching_proof(
    proofs: Sequence[ExactRevisionConfirmation],
    *,
    operation: ExactRevisionOperation,
    target: ExactRevisionTarget,
) -> ExactRevisionConfirmation | None:
    return next(
        (
            proof
            for proof in proofs
            if proof.operation is operation and proof.target is target
        ),
        None,
    )


def _matching_semantic_change(
    changes: Sequence[ConstraintChangeDraft],
    *,
    constraint: TaskConstraint,
    before: TaskConstraint,
) -> ConstraintChangeDraft | None:
    if isinstance(constraint, EfficacyConstraint):
        parent = "efficacy"
        value = constraint.value.value
    elif isinstance(constraint, SkinConstraint):
        parent = "skin"
        value = constraint.value.value
    else:
        return None
    explicit = next(
        (
            change
            for change in changes
            if (
                change.parent_concept == parent
                and change.requested_change == "replace"
                and change.value == value
            )
        ),
        None,
    )
    if explicit is not None:
        return explicit
    if (
        parent == "efficacy"
        and isinstance(before, EfficacyConstraint)
        and before.value.value != value
    ):
        return next(
            (
                change
                for change in changes
                if (
                    change.parent_concept == "efficacy"
                    and change.requested_change == "remove"
                    and change.value == before.value.value
                )
            ),
            None,
        )
    return None


def _proof_matches_constraint_value(
    proof: ExactRevisionConfirmation,
    *,
    constraint: TaskConstraint,
) -> bool:
    if proof.affected_value is None:
        return True
    if isinstance(
        constraint,
        (
            CategoryConstraint,
            SkinConstraint,
            EfficacyConstraint,
        ),
    ):
        return (
            constraint.value.value.casefold()
            == proof.affected_value.casefold()
        )
    return True


def _drop_old_category_scope(
    state: dict[str, TaskConstraint],
) -> None:
    for identity, constraint in tuple(state.items()):
        if isinstance(constraint, _CATEGORY_SCOPED_TYPES):
            state.pop(identity)


def _drop_efficacy_concept(
    state: dict[str, TaskConstraint],
    target: EfficacyTarget,
) -> None:
    concept_id = f"efficacy.{target.value}"
    for identity, constraint in tuple(state.items()):
        if (
            isinstance(constraint, ConceptConstraint)
            and constraint.field_key == "efficacy"
            and constraint.concept_id == concept_id
        ):
            state.pop(identity)


def _context_constraints(
    context: RecommendationQueryContext,
) -> tuple[TaskConstraint, ...]:
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
            EfficacyConstraint(value=EfficacyTarget(context.efficacy))
        )
    constraints.extend(
        ExclusionConstraint(value=value)
        for value in context.exclusions
    )
    constraints.extend(
        FacetConstraint(
            field_key=facet.field_key,
            value=facet.value,
        )
        for facet in context.facets
    )
    constraints.extend(
        ConceptConstraint(
            field_key=concept.field_key,
            concept_id=concept.concept_id,
            polarity=concept.polarity,
        )
        for concept in context.concepts
    )
    constraints.extend(
        InclusionConstraint(value=value)
        for value in context.inclusions
    )
    return tuple(constraints)


def _constraint_identity(constraint: TaskConstraint) -> str:
    if isinstance(constraint, CategoryConstraint):
        return "category"
    if isinstance(constraint, BudgetConstraint):
        return "budget"
    if isinstance(constraint, SkinConstraint):
        return "skin"
    if isinstance(constraint, EfficacyConstraint):
        return "efficacy"
    if isinstance(constraint, ExclusionConstraint):
        return f"exclusion:{constraint.value.casefold()}"
    if isinstance(constraint, InclusionConstraint):
        return f"inclusion:{constraint.value.casefold()}"
    if isinstance(constraint, FacetConstraint):
        return (
            f"facet:{constraint.field_key}:"
            f"{constraint.value.casefold()}"
        )
    if isinstance(constraint, ConceptConstraint):
        return (
            f"concept:{constraint.field_key}:"
            f"{constraint.concept_id}:{constraint.polarity}"
        )
    raise TypeError("unsupported TaskConstraint")


def _constraint_sort_key(
    constraint: TaskConstraint,
) -> tuple[int, str, str]:
    if isinstance(constraint, CategoryConstraint):
        return (0, "", "")
    if isinstance(constraint, BudgetConstraint):
        return (1, "", "")
    if isinstance(constraint, SkinConstraint):
        return (2, "", "")
    if isinstance(constraint, EfficacyConstraint):
        return (3, "", "")
    if isinstance(constraint, ExclusionConstraint):
        return (4, "", constraint.value.casefold())
    if isinstance(constraint, FacetConstraint):
        return (
            5,
            constraint.field_key,
            constraint.value.casefold(),
        )
    if isinstance(constraint, ConceptConstraint):
        return (
            5,
            constraint.field_key,
            f"{constraint.concept_id}:{constraint.polarity}",
        )
    if isinstance(constraint, InclusionConstraint):
        return (6, "", constraint.value.casefold())
    raise TypeError("unsupported TaskConstraint")


def _transition_sort_key(
    transition: ConstraintTransition,
) -> tuple[int, str]:
    target = transition.target
    if target == "category":
        return (0, target)
    if target == "budget":
        return (1, target)
    if target == "skin":
        return (2, target)
    if target == "efficacy":
        return (3, target)
    if target.startswith("exclusion:"):
        return (4, target)
    if target.startswith("facet:"):
        return (5, target)
    if target.startswith("concept:"):
        return (5, target)
    if target.startswith("inclusion:"):
        return (6, target)
    return (7, target)


def _append_issue(
    issues: list[UnderstandingIssue],
    *,
    code: str,
    detail: str,
) -> None:
    issue = UnderstandingIssue(code=code, detail=detail)
    if issue not in issues:
        issues.append(issue)


__all__ = [
    "BoundConstraint",
    "ConstraintTransition",
    "ConstraintTransitionResult",
    "reduce_constraint_state",
]
