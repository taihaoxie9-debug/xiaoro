from __future__ import annotations

import pytest

from app.guide.understanding.semantic_equivalence import (
    SemanticActualOutcome,
    SemanticAtomKind,
    SemanticAtomRequirement,
    SemanticEquivalenceMismatchCode,
    SemanticOutcomeContract,
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
    )


def _actual(
    *,
    responsibility: str,
    reference_shape: str,
    operation: str,
    atoms: tuple[SemanticAtomKind, ...] = (),
    question: bool = False,
    revision: bool = False,
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
            ),
        )
        assert decision.passed


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
