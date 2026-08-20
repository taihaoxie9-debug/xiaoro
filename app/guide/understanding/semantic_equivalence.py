from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SemanticAtomKind = Literal[
    "budget_candidate",
    "constraint_change",
    "product_reference",
    "image_reference",
    "comparison_cardinality",
    "observation",
    "question_meaning",
    "revision",
    "safety_observation",
]
SemanticReferenceShape = Literal[
    "none",
    "one_product",
    "product_batch",
    "one_image",
    "image_batch",
]
SemanticTaskMode = Literal[
    "recommend",
    "comparison",
    "suitability",
    "knowledge",
    "followup",
    "clarify",
]


class SemanticEquivalenceMismatchCode(str, Enum):
    OPERATION = "operation"
    RESPONSIBILITY = "responsibility"
    REFERENCE_SHAPE = "reference_shape"
    REQUIRED_ATOM = "required_atom"
    QUESTION_MEANING = "question_meaning"
    REVISION = "revision"
    SAFETY = "safety"
    TASK_MODE = "task_mode"


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        protected_namespaces=(),
    )


class SemanticAtomRequirement(_StrictFrozen):
    kind: SemanticAtomKind
    minimum_count: int = Field(default=1, ge=1, le=4)


class SemanticOutcomeContract(_StrictFrozen):
    responsibility: str = Field(min_length=1, max_length=64)
    reference_shape: SemanticReferenceShape
    allowed_operation_hints: tuple[str, ...] = Field(
        min_length=1,
        max_length=8,
    )
    required_atoms: tuple[SemanticAtomRequirement, ...] = Field(
        default_factory=tuple,
        max_length=12,
    )
    question_required: bool = False
    revision_required: bool = False
    safety_required: bool = False
    allowed_task_modes: tuple[SemanticTaskMode, ...] = Field(
        min_length=1,
        max_length=6,
    )

    @model_validator(mode="after")
    def validate_unique_requirements(self) -> SemanticOutcomeContract:
        kinds = tuple(item.kind for item in self.required_atoms)
        if len(kinds) != len(set(kinds)):
            raise ValueError("semantic atom requirements must be unique")
        if len(self.allowed_operation_hints) != len(
            set(self.allowed_operation_hints)
        ):
            raise ValueError("operation hints must be unique")
        if len(self.allowed_task_modes) != len(
            set(self.allowed_task_modes)
        ):
            raise ValueError("task modes must be unique")
        return self


class SemanticActualOutcome(_StrictFrozen):
    responsibility: str = Field(min_length=1, max_length=64)
    reference_shape: SemanticReferenceShape
    operation_hint: str = Field(min_length=1, max_length=64)
    atom_kinds: tuple[SemanticAtomKind, ...] = Field(
        default_factory=tuple,
        max_length=16,
    )
    question_present: bool = False
    revision_present: bool = False
    safety_present: bool = False
    task_mode: SemanticTaskMode

    @model_validator(mode="after")
    def validate_unique_atoms(self) -> SemanticActualOutcome:
        if len(self.atom_kinds) != len(set(self.atom_kinds)):
            raise ValueError("actual semantic atoms must be unique")
        return self


class SemanticEquivalenceDecision(_StrictFrozen):
    passed: bool
    expected_outcome: SemanticOutcomeContract
    actual_outcome: SemanticActualOutcome
    mismatch_code: SemanticEquivalenceMismatchCode | None = None


def evaluate_semantic_equivalence(
    *,
    expected: SemanticOutcomeContract,
    actual: SemanticActualOutcome,
) -> SemanticEquivalenceDecision:
    """Compare typed responsibility outcomes, not natural-language wording."""
    if actual.responsibility != expected.responsibility:
        return _decision(
            expected=expected,
            actual=actual,
            mismatch_code=SemanticEquivalenceMismatchCode.RESPONSIBILITY,
        )
    if actual.operation_hint not in expected.allowed_operation_hints:
        return _decision(
            expected=expected,
            actual=actual,
            mismatch_code=SemanticEquivalenceMismatchCode.OPERATION,
        )
    if actual.reference_shape != expected.reference_shape:
        return _decision(
            expected=expected,
            actual=actual,
            mismatch_code=SemanticEquivalenceMismatchCode.REFERENCE_SHAPE,
        )
    actual_atoms = set(actual.atom_kinds)
    for requirement in expected.required_atoms:
        if (
            requirement.minimum_count > 1
            or requirement.kind not in actual_atoms
        ):
            return _decision(
                expected=expected,
                actual=actual,
                mismatch_code=(
                    SemanticEquivalenceMismatchCode.REQUIRED_ATOM
                ),
            )
    if expected.question_required and not actual.question_present:
        return _decision(
            expected=expected,
            actual=actual,
            mismatch_code=SemanticEquivalenceMismatchCode.QUESTION_MEANING,
        )
    if expected.revision_required and not actual.revision_present:
        return _decision(
            expected=expected,
            actual=actual,
            mismatch_code=SemanticEquivalenceMismatchCode.REVISION,
        )
    if expected.safety_required and not actual.safety_present:
        return _decision(
            expected=expected,
            actual=actual,
            mismatch_code=SemanticEquivalenceMismatchCode.SAFETY,
        )
    if actual.task_mode not in expected.allowed_task_modes:
        return _decision(
            expected=expected,
            actual=actual,
            mismatch_code=SemanticEquivalenceMismatchCode.TASK_MODE,
        )
    return _decision(expected=expected, actual=actual, mismatch_code=None)


def _decision(
    *,
    expected: SemanticOutcomeContract,
    actual: SemanticActualOutcome,
    mismatch_code: SemanticEquivalenceMismatchCode | None,
) -> SemanticEquivalenceDecision:
    return SemanticEquivalenceDecision(
        passed=mismatch_code is None,
        expected_outcome=expected,
        actual_outcome=actual,
        mismatch_code=mismatch_code,
    )


__all__ = [
    "SemanticActualOutcome",
    "SemanticAtomKind",
    "SemanticAtomRequirement",
    "SemanticEquivalenceDecision",
    "SemanticEquivalenceMismatchCode",
    "SemanticOutcomeContract",
    "evaluate_semantic_equivalence",
]
