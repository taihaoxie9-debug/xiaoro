from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.guide.understanding.semantic_equivalence import (
    SemanticActualOutcome,
    SemanticAtomKind,
    SemanticAtomRequirement,
    SemanticEquivalenceMismatchCode,
    SemanticOutcomeContract,
    build_actual_semantic_outcome,
    derive_semantic_outcome,
    evaluate_semantic_equivalence,
)


def _expected(
    *,
    responsibility: str,
    reference_shape: str,
    allowed_operations: tuple[str, ...],
    required_atoms: tuple[SemanticAtomKind, ...] = (),
    question_required: bool = False,
    revision_required: bool = False,
    recommendation_mode: str | None = None,
    recommendation_mode_basis: str | None = None,
) -> SemanticOutcomeContract:
    return SemanticOutcomeContract(
        responsibility=responsibility,
        reference_shape=reference_shape,
        allowed_operation_hints=allowed_operations,
        required_atoms=tuple(
            SemanticAtomRequirement(kind=kind)
            for kind in required_atoms
        ),
        question_required=question_required,
        revision_required=revision_required,
        safety_required=False,
        allowed_task_modes=("knowledge", "followup", "recommend"),
        recommendation_mode=recommendation_mode,
        recommendation_mode_basis=recommendation_mode_basis,
    )


def _actual(
    *,
    responsibility: str,
    reference_shape: str,
    operation: str,
    atoms: tuple[SemanticAtomKind, ...] = (),
    question: bool = False,
    revision: bool = False,
    recommendation_mode: str | None = None,
    recommendation_mode_basis: str | None = None,
) -> SemanticActualOutcome:
    return SemanticActualOutcome(
        responsibility=responsibility,
        reference_shape=reference_shape,
        operation_hint=operation,
        atom_kinds=atoms,
        question_present=question,
        revision_present=revision,
        safety_present=False,
        task_mode="knowledge",
        recommendation_mode=recommendation_mode,
        recommendation_mode_basis=recommendation_mode_basis,
    )


def test_product_knowledge_accepts_knowledge_or_referenced_followup() -> None:
    expected = _expected(
        responsibility="product_knowledge",
        reference_shape="one_product",
        allowed_operations=("knowledge", "followup"),
        required_atoms=("product_reference", "question_meaning"),
        question_required=True,
    )

    for operation in ("knowledge", "followup"):
        decision = evaluate_semantic_equivalence(
            expected=expected,
            actual=_actual(
                responsibility="product_knowledge",
                reference_shape="one_product",
                operation=operation,
                atoms=("product_reference", "question_meaning"),
                question=True,
            ),
        )
        assert decision.passed
        assert decision.mismatch_code is None


def test_product_knowledge_rejects_recommendation_with_same_reference() -> None:
    expected = _expected(
        responsibility="product_knowledge",
        reference_shape="one_product",
        allowed_operations=("knowledge", "followup"),
        required_atoms=("product_reference", "question_meaning"),
        question_required=True,
    )

    decision = evaluate_semantic_equivalence(
        expected=expected,
        actual=_actual(
            responsibility="recommendation",
            reference_shape="one_product",
            operation="recommendation",
            atoms=(
                "product_reference",
                "constraint_change",
            ),
            question=True,
        ),
    )

    assert not decision.passed
    assert decision.mismatch_code is (
        SemanticEquivalenceMismatchCode.RESPONSIBILITY
    )


def test_recommendation_revision_accepts_two_operation_encodings() -> None:
    expected = _expected(
        responsibility="recommendation",
        reference_shape="none",
        allowed_operations=("followup", "recommendation"),
        required_atoms=("revision",),
        revision_required=True,
        recommendation_mode="explore",
        recommendation_mode_basis="bounded_exploration",
    )

    for operation in ("followup", "recommendation"):
        decision = evaluate_semantic_equivalence(
            expected=expected,
            actual=_actual(
                responsibility="recommendation",
                reference_shape="none",
                operation=operation,
                atoms=("revision",),
                revision=True,
                recommendation_mode="explore",
                recommendation_mode_basis="bounded_exploration",
            ),
        )
        assert decision.passed


def test_recommendation_mode_basis_is_part_of_equivalence() -> None:
    expected = _expected(
        responsibility="recommendation",
        reference_shape="none",
        allowed_operations=("recommendation",),
        recommendation_mode="fit",
        recommendation_mode_basis="personal_suitability",
    )

    wrong_mode = evaluate_semantic_equivalence(
        expected=expected,
        actual=_actual(
            responsibility="recommendation",
            reference_shape="none",
            operation="recommendation",
            recommendation_mode="explore",
            recommendation_mode_basis="broad_exploration",
        ),
    )
    wrong_basis = evaluate_semantic_equivalence(
        expected=expected,
        actual=_actual(
            responsibility="recommendation",
            reference_shape="none",
            operation="recommendation",
            recommendation_mode="fit",
            recommendation_mode_basis="single_best_request",
        ),
    )

    assert wrong_mode.mismatch_code is (
        SemanticEquivalenceMismatchCode.RECOMMENDATION_MODE
    )
    assert wrong_basis.mismatch_code is (
        SemanticEquivalenceMismatchCode.RECOMMENDATION_MODE_BASIS
    )


def test_image_actual_outcome_does_not_fabricate_missing_mode() -> None:
    actual = build_actual_semantic_outcome(
        meaning=SimpleNamespace(
            operation_hint="image_similarity",
            budget_candidates=(),
            constraint_changes=(),
            preference_candidates=(),
            question_meaning=None,
            observation_candidates=(),
            safety_language="ordinary",
        ),
        compiled=SimpleNamespace(
            references=(
                SimpleNamespace(kind="image_ordinal"),
            ),
            product_mentions=(),
            recommendation_mode=None,
            recommendation_mode_basis=None,
        ),
        task=SimpleNamespace(
            mode="clarify",
            product_ids=(),
            recommendation_mode=None,
            recommendation_mode_basis=None,
        ),
    )

    assert actual.responsibility == "image_recommendation"
    assert actual.recommendation_mode is None
    assert actual.recommendation_mode_basis is None


def test_missing_required_typed_atom_is_not_equivalent() -> None:
    expected = _expected(
        responsibility="recommendation",
        reference_shape="none",
        allowed_operations=("recommendation",),
        required_atoms=("budget_candidate", "revision"),
        revision_required=True,
    )

    decision = evaluate_semantic_equivalence(
        expected=expected,
        actual=_actual(
            responsibility="recommendation",
            reference_shape="none",
            operation="recommendation",
            atoms=("revision",),
            revision=True,
        ),
    )

    assert not decision.passed
    assert decision.mismatch_code is (
        SemanticEquivalenceMismatchCode.REQUIRED_ATOM
    )


@pytest.mark.parametrize(
    ("responsibility", "reference_shape", "operation", "atoms"),
    (
        (
            "comparison",
            "product_batch",
            "comparison",
            ("product_reference",),
        ),
        (
            "image_identity",
            "one_image",
            "image_identity",
            ("image_reference",),
        ),
        (
            "image_recommendation",
            "one_image",
            "image_similarity",
            ("image_reference",),
        ),
        (
            "general_knowledge",
            "none",
            "knowledge",
            ("question_meaning",),
        ),
        (
            "clarification",
            "none",
            "clarification",
            (),
        ),
        (
            "consultation",
            "none",
            "assessment",
            ("observation",),
        ),
        (
            "safety_escalation",
            "none",
            "assessment",
            ("safety_observation",),
        ),
    ),
)
def test_matrix_covers_other_responsibility_families(
    responsibility: str,
    reference_shape: str,
    operation: str,
    atoms: tuple[SemanticAtomKind, ...],
) -> None:
    expected = _expected(
        responsibility=responsibility,
        reference_shape=reference_shape,
        allowed_operations=(operation,),
        required_atoms=atoms,
    )
    decision = evaluate_semantic_equivalence(
        expected=expected,
        actual=_actual(
            responsibility=responsibility,
            reference_shape=reference_shape,
            operation=operation,
            atoms=atoms,
        ),
    )
    assert decision.passed


def _synthetic_case(
    *,
    family: str,
    expected_mode: str | None,
    expected_objects: tuple[str, ...] = (),
    tags: tuple[str, ...] = (),
    expected_transitions: tuple[str, ...] = (),
) -> SimpleNamespace:
    return SimpleNamespace(
        family=family,
        tags=tags,
        translation=SimpleNamespace(
            allowed_operation_hints=("followup",),
            require_question_meaning=False,
            required_budget=None,
            required_observations=(),
            required_preferences=(),
        ),
        binding=SimpleNamespace(expected_objects=expected_objects),
        execution=SimpleNamespace(
            expected_task_mode=expected_mode,
            expected_transitions=expected_transitions,
            expected_recommendation_mode=None,
            expected_recommendation_mode_basis=None,
        ),
    )


def test_bound_product_followup_uses_product_knowledge_responsibility() -> None:
    outcome = derive_semantic_outcome(
        expected_case=_synthetic_case(
            family="followup",
            expected_mode="followup",
            expected_objects=("candidate:1",),
        )
    )

    assert outcome.responsibility == "product_knowledge"
    assert outcome.allowed_task_modes == ("followup",)


def test_safety_escalation_can_strengthen_consultation() -> None:
    expected = SemanticOutcomeContract(
        responsibility="consultation",
        reference_shape="none",
        allowed_operation_hints=("assessment",),
        required_atoms=(
            SemanticAtomRequirement(kind="observation"),
        ),
        allowed_task_modes=("clarify",),
    )
    actual = SemanticActualOutcome(
        responsibility="safety_escalation",
        reference_shape="none",
        operation_hint="assessment",
        atom_kinds=("observation", "safety_observation"),
        question_present=True,
        revision_present=False,
        safety_present=True,
        task_mode="clarify",
    )

    decision = evaluate_semantic_equivalence(
        expected=expected,
        actual=actual,
    )

    assert decision.passed
    assert decision.mismatch_code is None


def test_revision_atom_is_required_only_for_typed_state_transition() -> None:
    topic_replacement = derive_semantic_outcome(
        expected_case=_synthetic_case(
            family="followup",
            expected_mode="followup",
            tags=("revision",),
        )
    )
    state_revision = derive_semantic_outcome(
        expected_case=_synthetic_case(
            family="followup",
            expected_mode="recommend",
            tags=("revision",),
            expected_transitions=("budget:replace",),
        )
    )

    assert not topic_replacement.revision_required
    assert all(
        item.kind != "revision"
        for item in topic_replacement.required_atoms
    )
    assert state_revision.revision_required
    assert any(
        item.kind == "revision"
        for item in state_revision.required_atoms
    )
