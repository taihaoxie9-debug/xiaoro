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
