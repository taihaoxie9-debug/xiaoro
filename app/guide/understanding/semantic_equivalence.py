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
SemanticResponsibility = Literal[
    "recommendation",
    "comparison",
    "single_product_suitability",
    "product_knowledge",
    "general_knowledge",
    "followup",
    "consultation",
    "image_identity",
    "image_recommendation",
    "clarification",
    "safety_escalation",
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
    responsibility: SemanticResponsibility
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


def derive_semantic_outcome(
    *,
    expected_case: object,
) -> SemanticOutcomeContract:
    """Derive the expected route contract from a typed gate case."""
    family = getattr(expected_case, "family", None)
    translation = getattr(expected_case, "translation", None)
    binding = getattr(expected_case, "binding", None)
    execution = getattr(expected_case, "execution", None)
    tags = frozenset(getattr(expected_case, "tags", ()))
    if (
        not isinstance(family, str)
        or translation is None
        or binding is None
        or execution is None
    ):
        raise TypeError("expected_case is not a typed gate case")

    expected_mode = execution.expected_task_mode
    responsibility = _expected_responsibility(
        family=family,
        expected_mode=expected_mode,
        expected_objects=tuple(binding.expected_objects),
        allowed_operations=tuple(
            str(item)
            for item in translation.allowed_operation_hints
        ),
    )
    reference_shape = _reference_shape(
        tuple(binding.expected_objects)
    )
    required_atoms: list[SemanticAtomRequirement] = []
    if reference_shape == "one_product":
        required_atoms.append(
            SemanticAtomRequirement(kind="product_reference")
        )
    elif reference_shape == "product_batch":
        required_atoms.extend(
            (
                SemanticAtomRequirement(kind="product_reference"),
                SemanticAtomRequirement(kind="comparison_cardinality"),
            )
        )
    elif reference_shape == "one_image":
        required_atoms.append(
            SemanticAtomRequirement(kind="image_reference")
        )
    elif reference_shape == "image_batch":
        required_atoms.extend(
            (
                SemanticAtomRequirement(kind="image_reference"),
                SemanticAtomRequirement(kind="comparison_cardinality"),
            )
        )
    if translation.require_question_meaning:
        required_atoms.append(
            SemanticAtomRequirement(kind="question_meaning")
        )
    if translation.required_budget is not None:
        required_atoms.append(
            SemanticAtomRequirement(kind="budget_candidate")
        )
    if translation.required_observations:
        required_atoms.append(
            SemanticAtomRequirement(kind="observation")
        )
    if "revision" in tags:
        required_atoms.append(
            SemanticAtomRequirement(kind="revision")
        )
        if translation.required_budget is None:
            required_atoms.append(
                SemanticAtomRequirement(kind="constraint_change")
            )
    operations = list(
        dict.fromkeys(
            str(getattr(item, "value", item))
            for item in translation.allowed_operation_hints
        )
    )
    if (
        responsibility == "product_knowledge"
        and reference_shape in {"one_product", "one_image"}
        and translation.require_question_meaning
    ):
        operations.append("followup")
    if (
        responsibility == "recommendation"
        and "revision" in tags
    ):
        operations.append("recommendation")
    operations = list(dict.fromkeys(operations))
    task_modes = _expected_task_modes(
        responsibility=responsibility,
        expected_mode=expected_mode,
    )
    if (
        responsibility == "product_knowledge"
        and reference_shape in {"one_product", "one_image"}
        and translation.require_question_meaning
        and "followup" not in task_modes
    ):
        task_modes = (*task_modes, "followup")
    return SemanticOutcomeContract(
        responsibility=responsibility,
        reference_shape=reference_shape,
        allowed_operation_hints=tuple(operations),
        required_atoms=tuple(required_atoms),
        question_required=translation.require_question_meaning,
        revision_required="revision" in tags,
        safety_required=responsibility == "safety_escalation",
        allowed_task_modes=task_modes,
    )


def build_actual_semantic_outcome(
    *,
    meaning: object,
    compiled: object,
    task: object,
) -> SemanticActualOutcome:
    """Project production compiler output into the shared outcome shape."""
    references = tuple(getattr(compiled, "references", ()))
    product_mentions = tuple(
        getattr(compiled, "product_mentions", ())
    )
    product_reference_kinds = {
        "candidate_ordinal",
        "current_item",
        "current_batch",
    }
    image_reference_kinds = {"image_ordinal"}
    product_references = tuple(
        item
        for item in references
        if getattr(item, "kind", None) in product_reference_kinds
    )
    image_references = tuple(
        item
        for item in references
        if getattr(item, "kind", None) in image_reference_kinds
    )
    task_product_ids = tuple(
        getattr(task, "product_ids", ())
    )
    reference_shape = _actual_reference_shape(
        product_references=product_references,
        image_references=image_references,
        product_mentions=product_mentions,
        task_product_count=len(task_product_ids),
    )
    atom_kinds: list[SemanticAtomKind] = []
    if product_references or product_mentions:
        atom_kinds.append("product_reference")
    if image_references:
        atom_kinds.append("image_reference")
    if reference_shape in {"product_batch", "image_batch"}:
        atom_kinds.append("comparison_cardinality")
    budget_candidates = tuple(
        getattr(meaning, "budget_candidates", ())
    )
    constraint_changes = tuple(
        getattr(meaning, "constraint_changes", ())
    )
    preferences = tuple(
        getattr(meaning, "preference_candidates", ())
    )
    if budget_candidates:
        atom_kinds.append("budget_candidate")
    if constraint_changes or any(
        getattr(item, "field_key", None) == "ingredient_exclusion"
        for item in preferences
    ):
        atom_kinds.append("constraint_change")
    question_present = bool(
        getattr(meaning, "question_meaning", None)
    )
    if question_present:
        atom_kinds.append("question_meaning")
    observation_candidates = tuple(
        getattr(meaning, "observation_candidates", ())
    )
    if observation_candidates:
        atom_kinds.append("observation")
    safety_present = (
        getattr(meaning, "safety_language", None) == "safety"
        and bool(observation_candidates)
    )
    if safety_present:
        atom_kinds.append("safety_observation")
    revision_present = bool(
        budget_candidates or constraint_changes
    )
    if revision_present:
        atom_kinds.append("revision")
    operation_hint = str(getattr(meaning, "operation_hint"))
    task_mode = str(getattr(task, "mode"))
    responsibility = _actual_responsibility(
        operation_hint=operation_hint,
        task_mode=task_mode,
        reference_shape=reference_shape,
        question_present=question_present,
        safety_present=safety_present,
    )
    return SemanticActualOutcome(
        responsibility=responsibility,
        reference_shape=reference_shape,
        operation_hint=operation_hint,
        atom_kinds=tuple(dict.fromkeys(atom_kinds)),
        question_present=question_present,
        revision_present=revision_present,
        safety_present=safety_present,
        task_mode=task_mode,
    )


def _expected_responsibility(
    *,
    family: str,
    expected_mode: str | None,
    expected_objects: tuple[str, ...],
    allowed_operations: tuple[str, ...],
) -> SemanticResponsibility:
    if family == "recommendation":
        return "recommendation"
    if family == "comparison":
        return "comparison"
    if family == "suitability":
        return "single_product_suitability"
    if family == "knowledge":
        return (
            "product_knowledge"
            if expected_objects
            else "general_knowledge"
        )
    if family == "image":
        return (
            "image_identity"
            if "image_identity" in allowed_operations
            else "image_recommendation"
        )
    if family == "assessment":
        return "consultation"
    if family == "clarification":
        return "clarification"
    if family == "followup":
        if expected_mode == "recommend":
            return "recommendation"
        if expected_mode == "clarify":
            return "clarification"
        return "followup"
    raise ValueError(f"unsupported gate family: {family}")


def _expected_task_modes(
    *,
    responsibility: SemanticResponsibility,
    expected_mode: str | None,
) -> tuple[SemanticTaskMode, ...]:
    if expected_mode is not None:
        return (expected_mode,)  # type: ignore[return-value]
    defaults: dict[SemanticResponsibility, tuple[SemanticTaskMode, ...]] = {
        "recommendation": ("recommend",),
        "comparison": ("comparison",),
        "single_product_suitability": ("suitability",),
        "product_knowledge": ("knowledge", "followup"),
        "general_knowledge": ("knowledge",),
        "followup": ("followup",),
        "consultation": ("clarify",),
        "image_identity": ("knowledge",),
        # The translation gate has no resolved product ID for the image
        # anchor; the production route gate owns that binding decision.
        "image_recommendation": ("recommend", "clarify"),
        "clarification": ("clarify",),
        "safety_escalation": ("clarify",),
    }
    return defaults[responsibility]


def _reference_shape(
    expected_objects: tuple[str, ...],
) -> SemanticReferenceShape:
    if not expected_objects:
        return "none"
    if any(item.startswith("image:") for item in expected_objects):
        return (
            "image_batch"
            if len(expected_objects) >= 2
            else "one_image"
        )
    if any(item == "candidate_batch" for item in expected_objects):
        return "product_batch"
    return (
        "product_batch"
        if len(expected_objects) >= 2
        else "one_product"
    )


def _actual_reference_shape(
    *,
    product_references: tuple[object, ...],
    image_references: tuple[object, ...],
    product_mentions: tuple[object, ...],
    task_product_count: int,
) -> SemanticReferenceShape:
    if image_references:
        return (
            "image_batch"
            if len(image_references) >= 2 or task_product_count >= 2
            else "one_image"
        )
    if product_references or product_mentions:
        return (
            "product_batch"
            if any(
                getattr(item, "kind", None) == "current_batch"
                for item in product_references
            )
            or len(product_references) >= 2
            or len(product_mentions) >= 2
            or task_product_count >= 2
            else "one_product"
        )
    return "none"


def _actual_responsibility(
    *,
    operation_hint: str,
    task_mode: str,
    reference_shape: SemanticReferenceShape,
    question_present: bool,
    safety_present: bool,
) -> SemanticResponsibility:
    if safety_present:
        return "safety_escalation"
    if (
        operation_hint == "image_similarity"
        and reference_shape in {"one_image", "image_batch"}
    ):
        return "image_recommendation"
    if task_mode == "comparison":
        return "comparison"
    if task_mode == "suitability":
        return "single_product_suitability"
    if task_mode == "recommend":
        return "recommendation"
    if task_mode == "knowledge":
        return (
            "product_knowledge"
            if reference_shape in {"one_product", "one_image"}
            else "general_knowledge"
        )
    if task_mode == "followup":
        if (
            question_present
            and reference_shape in {"one_product", "one_image"}
        ):
            return "product_knowledge"
        return "followup"  # type: ignore[return-value]
    if task_mode == "clarify":
        return (
            "consultation"
            if operation_hint == "assessment"
            else "clarification"
        )
    raise ValueError(f"unsupported task mode: {task_mode}")


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
    "build_actual_semantic_outcome",
    "derive_semantic_outcome",
    "evaluate_semantic_equivalence",
]
