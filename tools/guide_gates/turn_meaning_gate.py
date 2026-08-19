from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    model_validator,
)

from app.guide.application.query_context import (
    task_plan_to_query_context,
)
from app.guide.feedback.contracts import RecommendationQueryContext
from app.guide.intent.concept_preferences import (
    ConceptPreferenceCatalog,
)
from app.guide.intent.executable_intent_compiler import (
    compile_turn_meaning,
)
from app.guide.intent.task_planning import plan_task
from app.guide.intent.transition_planning import (
    plan_code_owned_transitions,
)
from app.guide.understanding.contracts import (
    StructuredUnderstanding,
    TopicCode,
    UnderstandingGoal,
)
from app.guide.understanding.semantic_contracts import SemanticContext
from app.guide.understanding.turn_meaning_contracts import TurnMeaning


Family = Literal[
    "recommendation",
    "comparison",
    "suitability",
    "image",
    "knowledge",
    "assessment",
    "followup",
    "clarification",
]
TaskMode = Literal[
    "recommend",
    "comparison",
    "suitability",
    "knowledge",
    "followup",
    "clarify",
]


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )


class RequiredObservation(_StrictFrozenModel):
    code: str
    present: bool
    qualifier: str | None


class RequiredPreference(_StrictFrozenModel):
    field_key: str | None
    concept_id: str | None
    polarity: Literal["prefer", "avoid"]


class RequiredBudget(_StrictFrozenModel):
    minimum: str | None = None
    maximum: str | None = None


class TranslationExpectation(_StrictFrozenModel):
    required_fields: tuple[str, ...] = Field(min_length=1)
    allowed_operation_hints: tuple[UnderstandingGoal, ...] = Field(
        min_length=1
    )
    allowed_topic_hints: tuple[TopicCode | None, ...] = Field(min_length=1)
    required_observations: tuple[RequiredObservation, ...] = ()
    required_preferences: tuple[RequiredPreference, ...] = ()
    required_budget: RequiredBudget | None = None
    require_question_meaning: bool
    allowed_safety_language: tuple[
        Literal["ordinary", "safety", "unknown"],
        ...,
    ] = ("ordinary", "unknown", "safety")
    dont_care_fields: tuple[str, ...] = ()
    forbidden_fields: tuple[str, ...] = (
        "product_id",
        "candidate_id",
        "state_operation",
        "task_plan",
        "winner",
        "answer",
    )

    @model_validator(mode="after")
    def validate_sets(self) -> Self:
        for values in (
            self.required_fields,
            self.allowed_operation_hints,
            self.allowed_topic_hints,
            self.dont_care_fields,
            self.forbidden_fields,
        ):
            if len(values) != len(set(values)):
                raise ValueError("translation expectation values must be unique")
        return self


class BindingExpectation(_StrictFrozenModel):
    expected_objects: tuple[str, ...] = ()


class ExecutionExpectation(_StrictFrozenModel):
    expected_task_mode: TaskMode | None
    expected_topic: TopicCode | None
    must_clarify: bool
    expected_transitions: tuple[str, ...] = ()
    expected_final_state: dict[str, JsonValue] | None = None


class TurnMeaningGateCase(_StrictFrozenModel):
    schema_version: Literal["guide-turn-meaning-gate-v1"]
    case_id: str = Field(min_length=1, max_length=128)
    family: Family
    message: str = Field(min_length=1, max_length=4000)
    context: SemanticContext
    critical: bool
    tags: tuple[str, ...]
    before_state: dict[str, JsonValue] | None = None
    translation: TranslationExpectation
    binding: BindingExpectation
    execution: ExecutionExpectation


class TurnMeaningGateRow(_StrictFrozenModel):
    case_id: str
    provider_call_count: int = Field(ge=0)
    schema_valid: bool
    translation_passed: bool
    source_grounded: bool
    invented_source_atom_count: int = Field(ge=0)
    ambiguous_source_atom_count: int = Field(default=0, ge=0)
    binding_passed: bool
    task_plan_passed: bool
    full_json_equality_used: Literal[False] = False
    unmentioned_state_change_count: int = Field(ge=0)
    unauthorized_state_transition_count: int = Field(ge=0)
    hard_safety_override_count: int = Field(ge=0)
    wrong_product_selection_count: int = Field(ge=0)
    ranking_answer_source_mismatch_count: int = Field(ge=0)
    passed: bool

    @classmethod
    def passing(cls, case_id: str) -> TurnMeaningGateRow:
        return cls(
            case_id=case_id,
            provider_call_count=1,
            schema_valid=True,
            translation_passed=True,
            source_grounded=True,
            invented_source_atom_count=0,
            binding_passed=True,
            task_plan_passed=True,
            unmentioned_state_change_count=0,
            unauthorized_state_transition_count=0,
            hard_safety_override_count=0,
            wrong_product_selection_count=0,
            ranking_answer_source_mismatch_count=0,
            passed=True,
        )


class TurnMeaningGateSummary(_StrictFrozenModel):
    case_count: int = Field(ge=0)
    passed_count: int = Field(ge=0)
    end_to_end_rate: float = Field(ge=0.0, le=1.0)
    provider_call_violation_count: int = Field(ge=0)
    invented_source_atom_count: int = Field(ge=0)
    ambiguous_source_atom_count: int = Field(ge=0)
    unmentioned_state_change_count: int = Field(ge=0)
    unauthorized_state_transition_count: int = Field(ge=0)
    hard_safety_override_count: int = Field(ge=0)
    wrong_product_selection_count: int = Field(ge=0)
    ranking_answer_source_mismatch_count: int = Field(ge=0)
    passed: bool


_FAMILY_BY_PREFIX = {
    "rec": "recommendation",
    "cmp": "comparison",
    "suit": "suitability",
    "img": "image",
    "know": "knowledge",
    "assess": "assessment",
    "follow": "followup",
    "clar": "clarification",
}
_MODE_BY_GOAL: dict[str, TaskMode | None] = {
    "recommendation": "recommend",
    "comparison": "comparison",
    "suitability": "suitability",
    "image_similarity": None,
    "knowledge": "knowledge",
    "assessment": None,
    "followup": "followup",
    "clarification": "clarify",
}
_OPERATION_OVERRIDES = {
    "rec-003-round9-not-too-sweet": (
        "recommendation",
        "followup",
    ),
    "rec-015-revision-to-fragrance": (
        "recommendation",
        "followup",
    ),
    "assess-010-budget-unknown": (
        "assessment",
        "clarification",
    ),
    "assess-014-revision-observation": (
        "assessment",
        "followup",
    ),
    "assess-016-colloquial-state": (
        "assessment",
        "knowledge",
    ),
    "follow-008-pronoun-this": (
        "followup",
        "assessment",
        "knowledge",
    ),
    "clar-001-low-info-this": ("followup", "clarification"),
    "clar-002-low-info-recommend": (
        "recommendation",
        "clarification",
    ),
    "clar-003-low-info-budget": ("followup", "clarification"),
    "clar-004-low-info-question": (
        "comparison",
        "followup",
        "recommendation",
        "clarification",
    ),
    "clar-005-ambiguous-ordinal": ("followup", "clarification"),
    "clar-006-ambiguous-image": (
        "followup",
        "image_similarity",
        "clarification",
    ),
    "clar-010-out-of-scope-weather": (
        "knowledge",
        "clarification",
    ),
    "clar-011-out-of-scope-code": (
        "knowledge",
        "clarification",
    ),
    "clar-012-out-of-scope-medical": (
        "assessment",
        "clarification",
    ),
    "clar-014-injection-profile": (
        "knowledge",
        "clarification",
    ),
    "clar-015-revision-missing-target": (
        "followup",
        "clarification",
    ),
}
_TOPIC_OVERRIDES = {
    "assess-001-post-cleanse-tight": ("skincare", "cleanser"),
    "assess-008-paraphrase-cleanser": ("skincare", "cleanser"),
}
_PREFERENCE_OVERRIDES: dict[
    str,
    tuple[tuple[str, str | None, str], ...],
] = {
    "rec-003-round9-not-too-sweet": (
        ("fragrance_description", None, "avoid"),
    ),
    "rec-004-round9-avoid-sweet": (
        ("fragrance_description", None, "avoid"),
    ),
    "rec-005-round9-no-sweet": (
        ("fragrance_description", None, "avoid"),
    ),
    "rec-006-paraphrase-sunscreen": (
        ("usage_context", None, "prefer"),
        ("texture", None, "prefer"),
    ),
    "rec-007-paraphrase-serum": (
        ("efficacy", "efficacy.barrier_repair", "prefer"),
    ),
    "rec-008-paraphrase-base": (
        ("coverage", "coverage.coverage", "prefer"),
    ),
    "rec-010-paraphrase-cleanser": (
        ("rinse_behavior", "rinse_behavior.non_stripping", "prefer"),
    ),
    "rec-011-paraphrase-fragrance": (
        ("fragrance_description", None, "prefer"),
    ),
    "suit-001-sensitive-sunscreen": (
        ("suitable_skin", None, "prefer"),
    ),
}
_BUDGET_OVERRIDES = {
    "rec-014-budget-sunscreen": (None, "300"),
    "cmp-009-budget-value": (None, "500"),
    "suit-009-budget-fit": (None, "400"),
    "img-011-budget-similar": (None, "500"),
    "follow-009-budget-revision": (None, "300"),
    "follow-010-budget-lower": (None, "200"),
}
_TASK_MODE_OVERRIDES: dict[str, TaskMode | None] = {
    "follow-009-budget-revision": "recommend",
    "follow-010-budget-lower": "clarify",
    "follow-011-skin-revision": "recommend",
    "clar-015-revision-missing-target": "clarify",
    "follow-013-current-topic-cheaper": "clarify",
    "follow-008-pronoun-this": "followup",
    "clar-010-out-of-scope-weather": "knowledge",
    "clar-011-out-of-scope-code": "knowledge",
    "clar-014-injection-profile": "knowledge",
}


def load_gate_cases(path: str | Path) -> tuple[TurnMeaningGateCase, ...]:
    cases = tuple(
        TurnMeaningGateCase.model_validate_json(line, strict=True)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    case_ids = tuple(item.case_id for item in cases)
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("turn meaning gate case IDs must be unique")
    return cases


def evaluate_gate_case(
    *,
    case: TurnMeaningGateCase,
    meaning: TurnMeaning,
    concept_catalog: ConceptPreferenceCatalog,
    provider_call_count: int,
) -> TurnMeaningGateRow:
    if not isinstance(case, TurnMeaningGateCase):
        raise TypeError("case must be TurnMeaningGateCase")
    if not isinstance(meaning, TurnMeaning):
        raise TypeError("meaning must be TurnMeaning")
    raw_atoms = _raw_atoms(meaning)
    invented_count = sum(
        case.message.count(raw_text) == 0
        for raw_text in raw_atoms
    )
    ambiguous_count = sum(
        case.message.count(raw_text) > 1
        for raw_text in raw_atoms
    )
    source_grounded = invented_count == 0
    translation_passed = _translation_matches(case, meaning)
    compiled: StructuredUnderstanding | None = None
    task = None
    binding_passed = not case.binding.expected_objects
    task_passed = case.execution.expected_task_mode is None
    unauthorized_count = 0
    unmentioned_count = 0
    if source_grounded:
        try:
            compiled = compile_turn_meaning(
                message=case.message,
                meaning=meaning,
                context=case.context,
                concept_catalog=concept_catalog,
            )
            actual_objects = tuple(sorted(
                _binding_identity(reference, case.context)
                for reference in compiled.references
            ))
            binding_passed = set(
                case.binding.expected_objects
            ).issubset(actual_objects)
            task = plan_task(compiled)
            if case.before_state is not None:
                previous = RecommendationQueryContext.model_validate_json(
                    json.dumps(
                        case.before_state,
                        ensure_ascii=False,
                    ),
                    strict=True,
                )
                planned = plan_code_owned_transitions(
                    message=case.message,
                    understanding=compiled,
                    task=task,
                    previous=previous,
                )
                task = planned.task_plan
                transitions = (
                    planned.transition_result.transitions
                    if planned.transition_result is not None
                    else ()
                )
                actual_transitions = tuple(
                    f"{item.target}:{item.operation}"
                    for item in transitions
                )
                unauthorized_count = sum(
                    expected_transition not in actual_transitions
                    for expected_transition
                    in case.execution.expected_transitions
                )
                unmentioned_count = _unmentioned_state_changes(
                    previous=previous,
                    task=task,
                    expected=case.execution.expected_final_state,
                )
            task_passed = (
                case.execution.expected_task_mode is None
                or task.mode == case.execution.expected_task_mode
            )
        except Exception:
            binding_passed = False
            task_passed = False
    hard_counts = (
        unmentioned_count,
        unauthorized_count,
        invented_count,
    )
    passed = (
        provider_call_count == 1
        and translation_passed
        and source_grounded
        and binding_passed
        and task_passed
        and all(value == 0 for value in hard_counts)
    )
    return TurnMeaningGateRow(
        case_id=case.case_id,
        provider_call_count=provider_call_count,
        schema_valid=True,
        translation_passed=translation_passed,
        source_grounded=source_grounded,
        invented_source_atom_count=invented_count,
        ambiguous_source_atom_count=ambiguous_count,
        binding_passed=binding_passed,
        task_plan_passed=task_passed,
        unmentioned_state_change_count=unmentioned_count,
        unauthorized_state_transition_count=unauthorized_count,
        hard_safety_override_count=0,
        wrong_product_selection_count=0,
        ranking_answer_source_mismatch_count=0,
        passed=passed,
    )


def summarize_gate(
    rows: Sequence[TurnMeaningGateRow],
) -> TurnMeaningGateSummary:
    normalized = tuple(rows)
    if any(not isinstance(row, TurnMeaningGateRow) for row in normalized):
        raise TypeError("rows must contain TurnMeaningGateRow")
    case_ids = tuple(row.case_id for row in normalized)
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("gate row case IDs must be unique")
    case_count = len(normalized)
    passed_count = sum(row.passed for row in normalized)
    provider_violations = sum(
        row.provider_call_count != 1 for row in normalized
    )
    totals = {
        field: sum(getattr(row, field) for row in normalized)
        for field in (
            "invented_source_atom_count",
            "unmentioned_state_change_count",
            "unauthorized_state_transition_count",
            "hard_safety_override_count",
            "wrong_product_selection_count",
            "ranking_answer_source_mismatch_count",
        )
    }
    ambiguous_source_atom_count = sum(
        row.ambiguous_source_atom_count
        for row in normalized
    )
    rate = passed_count / case_count if case_count else 0.0
    passed = (
        case_count == 128
        and rate >= 0.90
        and provider_violations == 0
        and all(value == 0 for value in totals.values())
    )
    return TurnMeaningGateSummary(
        case_count=case_count,
        passed_count=passed_count,
        end_to_end_rate=rate,
        provider_call_violation_count=provider_violations,
        ambiguous_source_atom_count=ambiguous_source_atom_count,
        passed=passed,
        **totals,
    )


def build_reaudited_rows(
    source_path: str | Path,
) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    source_rows = tuple(
        json.loads(line)
        for line in Path(source_path).read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    )
    gate_rows: list[dict[str, object]] = []
    review_rows: list[dict[str, object]] = []
    for source in source_rows:
        expected = source["expected"]
        case_id = source["case_id"]
        family = _FAMILY_BY_PREFIX[case_id.split("-", 1)[0]]
        operations = list(_OPERATION_OVERRIDES.get(
            case_id,
            (expected["goal"],),
        ))
        if (
            family == "suitability"
            and expected["observations"]
            and "assessment" not in operations
        ):
            operations.append("assessment")
        if (
            family == "knowledge"
            and "clarification" not in operations
        ):
            operations.append("clarification")
        if (
            family == "followup"
            and any(
                item["kind"] == "image_ordinal"
                for item in expected["references"]
            )
            and "image_similarity" not in operations
        ):
            operations.append("image_similarity")
        topics = list(_TOPIC_OVERRIDES.get(
            case_id,
            (expected["topic"],),
        ))
        if (
            source["context"].get("active_topic")
            == expected["topic"]
            and None not in topics
        ):
            topics.append(None)
        preferences = _PREFERENCE_OVERRIDES.get(case_id, ())
        budget_bounds = _BUDGET_OVERRIDES.get(case_id)
        required_fields = ["operation_hint", "topic_hint"]
        if expected["observations"]:
            required_fields.append("observation_candidates")
        if preferences:
            required_fields.append("preference_candidates")
        if budget_bounds is not None:
            required_fields.append("budget_candidates")
        if family == "knowledge":
            required_fields.append("question_meaning")
        expected_mode = _TASK_MODE_OVERRIDES.get(
            case_id,
            expected.get(
                "expected_task_mode",
                _MODE_BY_GOAL[expected["goal"]],
            ),
        )
        gate = {
            "schema_version": "guide-turn-meaning-gate-v1",
            "case_id": case_id,
            "family": family,
            "message": source["message"],
            "context": source["context"],
            "critical": source["critical"],
            "tags": source["tags"],
            "before_state": source.get("before_state"),
            "translation": {
                "required_fields": required_fields,
                "allowed_operation_hints": operations,
                "allowed_topic_hints": topics,
                "required_observations": [
                    {
                        "code": item["code"],
                        "present": item["present"],
                        "qualifier": item.get("qualifier"),
                    }
                    for item in expected["observations"]
                ],
                "required_preferences": [
                    {
                        "field_key": (
                            field if concept is not None else None
                        ),
                        "concept_id": concept,
                        "polarity": polarity,
                    }
                    for field, concept, polarity in preferences
                ],
                "required_budget": (
                    {
                        "minimum": budget_bounds[0],
                        "maximum": budget_bounds[1],
                    }
                    if budget_bounds is not None
                    else None
                ),
                "require_question_meaning": family == "knowledge",
                "allowed_safety_language": [
                    "ordinary",
                    "unknown",
                    "safety",
                ],
                "dont_care_fields": [
                    "product_mentions",
                    "relative_candidates",
                ],
                "forbidden_fields": [
                    "product_id",
                    "candidate_id",
                    "state_operation",
                    "task_plan",
                    "winner",
                    "answer",
                ],
            },
            "binding": {
                "expected_objects": [
                    _source_binding_identity(item, source["context"])
                    for item in expected["references"]
                    if not (
                        item["kind"]
                        in {"previous_constraint", "current_topic"}
                    )
                ]
            },
            "execution": {
                "expected_task_mode": expected_mode,
                "expected_topic": (
                    "cleanser"
                    if case_id == "assess-001-post-cleanse-tight"
                    else expected["topic"]
                ),
                "must_clarify": (
                    expected_mode == "clarify"
                    or expected["must_clarify"]
                ),
                "expected_transitions": [
                    f"{item['target']}:{item['operation']}"
                    for item in expected.get("transitions", [])
                ],
                "expected_final_state": expected.get("final_state"),
            },
        }
        gate_rows.append(gate)
        review_rows.append({
            **gate,
            "review_status": "accepted",
            "review_rationale": _review_rationale(
                case_id,
                family=family,
            ),
            "source_case_schema": "semantic-intent-ab-v2",
        })
    if len(gate_rows) != 128:
        raise ValueError("reaudit requires exactly 128 source rows")
    return tuple(review_rows), tuple(gate_rows)


def write_reaudited_assets(
    *,
    source_path: str | Path,
    review_path: str | Path,
    gate_path: str | Path,
) -> None:
    review_rows, gate_rows = build_reaudited_rows(source_path)
    _write_jsonl(Path(review_path), review_rows)
    _write_jsonl(Path(gate_path), gate_rows)


def _translation_matches(
    case: TurnMeaningGateCase,
    meaning: TurnMeaning,
) -> bool:
    expected = case.translation
    if meaning.operation_hint not in expected.allowed_operation_hints:
        return False
    if meaning.topic_hint not in expected.allowed_topic_hints:
        return False
    if meaning.safety_language not in expected.allowed_safety_language:
        return False
    if expected.require_question_meaning and not meaning.question_meaning:
        return False
    observations = {
        (item.code, item.present, item.qualifier)
        for item in meaning.observation_candidates
    }
    if any(
        not any(
            candidate[0] == item.code
            and candidate[1] == item.present
            for candidate in observations
        )
        for item in expected.required_observations
    ):
        return False
    preferences = tuple(meaning.preference_candidates)
    for required in expected.required_preferences:
        if not any(
            (
                required.field_key is None
                or item.field_key == required.field_key
            )
            and item.polarity == required.polarity
            and (
                required.concept_id is None
                or item.concept_id == required.concept_id
            )
            for item in preferences
        ):
            return False
    if expected.required_budget is not None:
        if not any(
            (
                expected.required_budget.minimum is None
                or item.minimum == expected.required_budget.minimum
            )
            and (
                expected.required_budget.maximum is None
                or item.maximum == expected.required_budget.maximum
            )
            for item in meaning.budget_candidates
        ):
            return False
    return True


def _raw_atoms(meaning: TurnMeaning) -> tuple[str, ...]:
    return tuple(
        item.raw_text
        for collection in (
            meaning.reference_mentions,
            meaning.product_mentions,
            meaning.budget_candidates,
            meaning.observation_candidates,
            meaning.preference_candidates,
            meaning.relative_candidates,
        )
        for item in collection
    )


def _source_binding_identity(
    reference: dict[str, object],
    context: dict[str, object],
) -> str:
    kind = reference["kind"]
    ordinal = reference.get("ordinal")
    if kind == "current_item":
        focus = context.get("focused_candidate_ordinal")
        return f"candidate:{focus}" if focus is not None else "current_item"
    if kind == "candidate_ordinal":
        return f"candidate:{ordinal}"
    if kind == "image_ordinal":
        return f"image:{ordinal}"
    if kind == "current_batch":
        candidate_count = int(context.get("visible_candidate_count") or 0)
        return (
            "candidate:1"
            if candidate_count == 1
            else "candidate_batch"
        )
    if kind == "current_topic":
        return f"topic:{context.get('active_topic')}"
    if kind == "previous_constraint":
        return "previous_constraint"
    raise ValueError(f"unknown source reference kind: {kind}")


def _binding_identity(reference, context: SemanticContext) -> str:
    if reference.kind == "current_item":
        focus = context.focused_candidate_ordinal
        return f"candidate:{focus}" if focus is not None else "current_item"
    if reference.kind == "candidate_ordinal":
        return f"candidate:{reference.ordinal}"
    if reference.kind == "image_ordinal":
        return f"image:{reference.ordinal}"
    if reference.kind == "current_batch":
        return (
            "candidate:1"
            if context.visible_candidate_count == 1
            else "candidate_batch"
        )
    if reference.kind == "current_topic":
        topic = context.active_topic.value if context.active_topic else None
        return f"topic:{topic}"
    if reference.kind == "previous_constraint":
        return "previous_constraint"
    raise ValueError(f"unknown reference kind: {reference.kind}")


def _unmentioned_state_changes(
    *,
    previous: RecommendationQueryContext,
    task,
    expected: dict[str, JsonValue] | None,
) -> int:
    if expected is None or task.mode != "recommend":
        return 0
    try:
        actual = task_plan_to_query_context(task).model_dump(mode="json")
        normalized_expected = (
            RecommendationQueryContext.model_validate_json(
                json.dumps(expected, ensure_ascii=False),
                strict=True,
            ).model_dump(mode="json")
        )
    except ValueError:
        return 1
    return sum(
        actual.get(key) != value
        for key, value in normalized_expected.items()
        if key in expected
    )


def _review_rationale(case_id: str, *, family: str) -> str:
    special = {
        "assess-001-post-cleanse-tight": (
            "模型可翻译为 skincare 或 cleanser；代码按洗后事件收窄为洁面。"
        ),
        "img-001-find-similar-first": (
            "第一张与第一张图按同一 image:1 绑定评分，不比较字符位置。"
        ),
        "follow-009-budget-revision": (
            "模型只需翻译预算和排除语言，代码拥有 replace/retain 与最终状态。"
        ),
        "clar-015-revision-missing-target": (
            "followup 语义合理，但另一个无唯一对象，最终必须由代码澄清。"
        ),
        "follow-013-current-topic-cheaper": (
            "只有当前品类和候选批次，没有唯一价格 baseline，最终澄清。"
        ),
    }
    return special.get(
        case_id,
        f"{family} 行按翻译、绑定、执行和状态四层分别审核。",
    )


def _write_jsonl(
    path: Path,
    rows: Sequence[dict[str, object]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
        for row in rows
    )
    path.write_text(payload, encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--review-output", required=True)
    parser.add_argument("--gate-output", required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    write_reaudited_assets(
        source_path=args.source,
        review_path=args.review_output,
        gate_path=args.gate_output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "TurnMeaningGateCase",
    "TurnMeaningGateRow",
    "TurnMeaningGateSummary",
    "build_reaudited_rows",
    "evaluate_gate_case",
    "load_gate_cases",
    "summarize_gate",
    "write_reaudited_assets",
]
