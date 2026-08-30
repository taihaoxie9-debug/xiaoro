"""Run the production-model translation gate for twelve four-turn sheets."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError,
    field_validator,
    model_validator,
)

from app.guide.adapters.llm.contracts import (
    SemanticProviderFailure,
    SemanticProviderFailureCode,
    SemanticTokenUsage,
)
from app.guide.adapters.llm.deepseek_intent import DEEPSEEK_V4_PRO_MODEL
from app.guide.adapters.llm.deepseek_turn_meaning import (
    DeepSeekTurnMeaningAdapter,
)
from app.guide.intent.concept_preferences import ConceptPreferenceCatalog
from app.guide.intent.executable_intent_compiler import compile_turn_meaning
from app.guide.intent.task_planning import plan_task
from app.guide.understanding.turn_meaning_contracts import (
    EXPLORE_RECOMMENDATION_BASES,
    FIT_RECOMMENDATION_BASES,
    RecommendationMode,
    RecommendationModeBasis,
    TurnMeaning,
)
from app.guide_runtime.composition import (
    build_provider_usage_limiter,
    build_selection_concept_assets,
)
from tools.guide_gates.private_api_key import (
    DEFAULT_KEY_PATH,
    KeyPrecheckError,
    read_private_api_key,
)
from tools.guide_gates.attempt_ledger import (
    attempt_context_phase,
    complete_attempt,
    consume_attempt_context,
    read_attempt_context,
)
from tools.guide_gates.build_task11_readiness import (
    verify_task11_readiness,
)
from tools.guide_gates.turn_meaning_gate import (
    TurnMeaningGateCase,
    TurnMeaningGateRow,
    evaluate_gate_case,
)


FINAL_TRANSLATION_CASE_COUNT = 12
FINAL_TRANSLATION_TURNS_PER_TRAJECTORY = 4
FINAL_TRANSLATION_TURN_COUNT = (
    FINAL_TRANSLATION_CASE_COUNT
    * FINAL_TRANSLATION_TURNS_PER_TRAJECTORY
)
_ROOT = Path(__file__).resolve().parents[2]
FINAL_TRANSLATION_FIXTURE_PATH = (
    "tests/fixtures/guide/final_release/"
    "real_translation_12x4_v5.jsonl"
)
_DEFAULT_CASES = (
    _ROOT / FINAL_TRANSLATION_FIXTURE_PATH
)

FinalContinuityHint = Literal[
    "continue",
    "return_to_focus",
    "new_task",
    "unknown",
]


@dataclass(frozen=True, slots=True)
class FinalTurnExpectations:
    recommendation_mode: RecommendationMode | None
    recommendation_mode_basis: RecommendationModeBasis | None
    allowed_continuity_hints: tuple[FinalContinuityHint, ...]


def derive_final_turn_expectations(
    *,
    operation_hints: Sequence[str],
    embedded_recommendation_mode: RecommendationMode | None,
    embedded_recommendation_mode_basis: RecommendationModeBasis | None,
    expected_objects: Sequence[str],
    conversation_version: int,
    allowed_continuity_hints: Sequence[FinalContinuityHint],
    must_clarify: bool = False,
) -> FinalTurnExpectations:
    operations = tuple(operation_hints)
    if (
        not operations
        or any(not isinstance(item, str) or not item for item in operations)
    ):
        raise ValueError("operation hints must be nonempty strings")
    if (embedded_recommendation_mode is None) != (
        embedded_recommendation_mode_basis is None
    ):
        raise ValueError("embedded recommendation outcome must be complete")
    if (
        not isinstance(conversation_version, int)
        or isinstance(conversation_version, bool)
        or conversation_version < 0
    ):
        raise ValueError("conversation version must be nonnegative")

    if "image_identity" in operations:
        mode = None
        basis = None
    elif (
        "image_similarity" in operations
        and not must_clarify
        and embedded_recommendation_mode != "fit"
    ):
        mode = "explore"
        basis = "similar_alternatives"
    else:
        mode = embedded_recommendation_mode
        basis = embedded_recommendation_mode_basis

    continuity = tuple(dict.fromkeys(allowed_continuity_hints))
    if (
        conversation_version > 0
        and tuple(expected_objects)
        and "continue" not in continuity
    ):
        continuity = ("continue", *continuity)
    return FinalTurnExpectations(
        recommendation_mode=mode,
        recommendation_mode_basis=basis,
        allowed_continuity_hints=continuity,
    )


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )


class FinalTranslationTurn(_StrictFrozen):
    trajectory_id: str = Field(min_length=1, max_length=160)
    turn_id: str = Field(
        min_length=1,
        max_length=180,
        pattern=r"^[a-z0-9][a-z0-9_-]+$",
    )
    case: TurnMeaningGateCase
    allowed_continuity_hints: tuple[
        Literal["continue", "return_to_focus", "new_task", "unknown"],
        ...,
    ] = ("unknown",)
    allowed_subject_scope_hints: tuple[
        Literal["self", "other", "unknown"],
        ...,
    ] = ("unknown",)
    required_safety_language: Literal[
        "ordinary",
        "safety",
        "unknown",
    ] | None = None
    expected_recommendation_mode: RecommendationMode | None
    expected_recommendation_mode_basis: RecommendationModeBasis | None
    image_product_ids: tuple[int, ...]

    @field_validator(
        "case",
        mode="before",
    )
    @classmethod
    def parse_case(cls, value: object) -> object:
        if isinstance(value, TurnMeaningGateCase):
            return value
        return TurnMeaningGateCase.model_validate_json(
            json.dumps(value, ensure_ascii=False),
            strict=True,
        )

    @field_validator(
        "allowed_continuity_hints",
        "allowed_subject_scope_hints",
        "image_product_ids",
        mode="before",
    )
    @classmethod
    def freeze_allowed_hints(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_recommendation_outcome(self):
        if (self.expected_recommendation_mode is None) != (
            self.expected_recommendation_mode_basis is None
        ):
            raise ValueError(
                "expected recommendation outcome must be complete"
            )
        if (
            self.expected_recommendation_mode == "explore"
            and self.expected_recommendation_mode_basis
            not in EXPLORE_RECOMMENDATION_BASES
        ):
            raise ValueError(
                "expected recommendation basis must be parent-scoped"
            )
        if (
            self.expected_recommendation_mode == "fit"
            and self.expected_recommendation_mode_basis
            not in FIT_RECOMMENDATION_BASES
        ):
            raise ValueError(
                "expected recommendation basis must be parent-scoped"
            )
        if (
            len(self.image_product_ids) != self.case.context.image_count
            or len(set(self.image_product_ids))
            != len(self.image_product_ids)
            or any(product_id <= 0 for product_id in self.image_product_ids)
        ):
            raise ValueError(
                "image product IDs must bind the sealed image count"
            )
        return self

    @classmethod
    def from_payload(cls, payload: object) -> FinalTranslationTurn:
        value = cls.model_validate_json(
            json.dumps(payload, ensure_ascii=False),
            strict=True,
        )
        if value.case.case_id != value.turn_id:
            raise ValueError("turn_id must equal the sealed case_id")
        return value


class FinalTranslationTrajectory(_StrictFrozen):
    trajectory_id: str = Field(min_length=1, max_length=160)
    family: str = Field(min_length=1, max_length=160)
    turns: tuple[
        FinalTranslationTurn,
        FinalTranslationTurn,
        FinalTranslationTurn,
        FinalTranslationTurn,
    ]
    critical: bool = True

    @field_validator("turns", mode="before")
    @classmethod
    def freeze_turns(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @classmethod
    def from_payload(cls, payload: object) -> FinalTranslationTrajectory:
        value = cls.model_validate_json(
            json.dumps(payload, ensure_ascii=False),
            strict=True,
        )
        if any(
            turn.trajectory_id != value.trajectory_id
            for turn in value.turns
        ):
            raise ValueError("turn trajectory IDs are inconsistent")
        return value


class FinalTranslationRow(_StrictFrozen):
    trajectory_id: str
    turn_id: str
    case_id: str
    status: Literal[
        "ok",
        "invalid_output",
        "provider_failure",
        "adapter_error",
    ]
    provider_failure_code: str | None
    schema_valid: bool
    translation_passed: bool
    source_grounded: bool
    binding_passed: bool
    task_plan_passed: bool
    continuity_passed: bool
    subject_scope_passed: bool
    recommendation_mode_passed: bool
    passed: bool
    failure_layer: Literal[
        "model_translation",
        "source_grounding",
        "identity_binding",
        "route_selection",
        None,
    ]
    wrong_product_or_image_binding_count: int = Field(ge=0)
    unsafe_downgrade_count: int = Field(ge=0)
    internal_public_language_count: int = Field(ge=0)
    provider_raw_output: str | None
    provider_output: dict[str, JsonValue] | None
    compiled_references: tuple[dict[str, JsonValue], ...] = ()
    responsibility: str | None
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    latency_ms: float = Field(ge=0.0, allow_inf_nan=False)
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_raw_output_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    provider_output_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )


class FinalTranslationReport(_StrictFrozen):
    schema_version: Literal[
        "guide-final-real-translation-summary-v1"
    ] = "guide-final-real-translation-summary-v1"
    model: str
    prompt_version: str
    trajectory_count: int = Field(ge=0)
    critical_trajectory_count: int = Field(ge=0)
    critical_trajectory_passed: int = Field(ge=0)
    expected_turn_count: int = Field(ge=0)
    turn_count: int = Field(ge=0)
    provider_call_count: int = Field(ge=0)
    stopped_early: bool
    stop_reason: str | None
    passed_turn_count: int = Field(ge=0)
    schema_valid_count: int = Field(ge=0)
    translation_passed_count: int = Field(ge=0)
    source_grounded_count: int = Field(ge=0)
    binding_passed_count: int = Field(ge=0)
    task_plan_passed_count: int = Field(ge=0)
    recommendation_mode_passed_count: int = Field(ge=0)
    wrong_product_or_image_binding_count: int = Field(ge=0)
    wrong_binding_count: int = Field(ge=0)
    unsafe_downgrade_count: int = Field(ge=0)
    internal_public_language_count: int = Field(ge=0)
    internal_language_count: int = Field(ge=0)
    serious_failure_count: int = Field(ge=0)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    p95_latency_ms: float = Field(ge=0.0, allow_inf_nan=False)
    focused_summary_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    fixture_path: str | None = None
    fixture_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    results_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    passed: bool


def load_final_translation_trajectories(
    path: str | Path = _DEFAULT_CASES,
) -> tuple[FinalTranslationTrajectory, ...]:
    rows = tuple(
        FinalTranslationTrajectory.from_payload(json.loads(line))
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    if len(rows) != FINAL_TRANSLATION_CASE_COUNT:
        raise ValueError("final translation fixture must contain 12 trajectories")
    trajectory_ids = tuple(row.trajectory_id for row in rows)
    if len(set(trajectory_ids)) != len(trajectory_ids):
        raise ValueError("final translation trajectory IDs must be unique")
    turn_ids = tuple(
        turn.turn_id
        for trajectory in rows
        for turn in trajectory.turns
    )
    if len(set(turn_ids)) != len(turn_ids):
        raise ValueError("final translation turn IDs must be unique")
    return rows


def run_final_translation_gate(
    *,
    trajectories: Sequence[FinalTranslationTrajectory],
    adapter,
    output_dir: str | Path,
    focused_summary_sha256: str | None = None,
    fixture_path: str | None = None,
    fixture_sha256: str | None = None,
) -> FinalTranslationReport:
    normalized = tuple(trajectories)
    _validate_trajectories(normalized)
    concept_catalog = _build_concept_catalog()
    rows: list[FinalTranslationRow] = []
    stop_reason: str | None = None

    for trajectory in normalized:
        for turn in trajectory.turns:
            row = _run_turn(
                trajectory=trajectory,
                turn=turn,
                adapter=adapter,
                concept_catalog=concept_catalog,
            )
            rows.append(row)
            if not row.passed:
                stop_reason = row.status if row.status != "ok" else (
                    row.failure_layer or "translation_mismatch"
                )
                break
        if stop_reason is not None:
            break

    report = _write_report(
        rows=tuple(rows),
        trajectories=normalized,
        model=str(getattr(adapter, "model", "unknown")),
        prompt_version=str(
            getattr(adapter, "prompt_version", "unknown")
        ),
        provider_call_count=len(rows),
        output_dir=output_dir,
        stop_reason=stop_reason,
        focused_summary_sha256=focused_summary_sha256,
        fixture_path=fixture_path,
        fixture_sha256=fixture_sha256,
    )
    return report


def replay_final_translation_gate(
    *,
    trajectories: Sequence[FinalTranslationTrajectory],
    capture_path: str | Path,
    output_dir: str | Path,
) -> FinalTranslationReport:
    normalized = tuple(trajectories)
    _validate_trajectories(normalized)
    by_turn = {
        (trajectory.trajectory_id, turn.turn_id): (trajectory, turn)
        for trajectory in normalized
        for turn in trajectory.turns
    }
    expected_order = tuple(by_turn)
    sources = tuple(
        json.loads(line)
        for line in Path(capture_path).read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    )
    captured_order = tuple(
        (source.get("trajectory_id"), source.get("turn_id"))
        for source in sources
        if isinstance(source, dict)
    )
    if (
        len(captured_order) != len(sources)
        or captured_order != expected_order[:len(captured_order)]
    ):
        raise ValueError(
            "translation replay must be one contiguous prefix "
            "of the sealed fixture"
        )
    rows: list[FinalTranslationRow] = []
    for source in sources:
        trajectory_id = source["trajectory_id"]
        turn_id = source["turn_id"]
        trajectory, turn = by_turn[(trajectory_id, turn_id)]
        rows.append(
            _replay_turn(
                source=source,
                trajectory=trajectory,
                turn=turn,
            )
        )
    first_failure = next(
        (row for row in rows if not row.passed),
        None,
    )
    stop_reason = (
        first_failure.status
        if first_failure is not None
        and first_failure.status != "ok"
        else (
            first_failure.failure_layer
            if first_failure is not None
            else None
        )
    )
    return _write_report(
        rows=tuple(rows),
        trajectories=normalized,
        model="replay",
        prompt_version="replay",
        provider_call_count=0,
        output_dir=output_dir,
        stop_reason=stop_reason,
    )


def validate_final_translation_rows(
    *,
    trajectories: Sequence[FinalTranslationTrajectory],
    rows: Sequence[Mapping[str, object]],
) -> tuple[FinalTranslationRow, ...]:
    normalized_trajectories = tuple(trajectories)
    _validate_trajectories(normalized_trajectories)
    expected_turns = tuple(
        (trajectory, turn)
        for trajectory in normalized_trajectories
        for turn in trajectory.turns
    )
    if len(rows) != len(expected_turns):
        raise ValueError(
            "translation capture must contain the sealed 48 rows"
        )
    validated: list[FinalTranslationRow] = []
    for source, (trajectory, turn) in zip(
        rows,
        expected_turns,
        strict=True,
    ):
        if not isinstance(source, Mapping):
            raise ValueError("translation result row must be an object")
        try:
            actual = FinalTranslationRow.model_validate_json(
                _canonical_json(dict(source)),
                strict=True,
            )
        except ValidationError as error:
            raise ValueError(
                "translation result row schema is invalid"
            ) from error
        recomputed = _replay_turn(
            source=source,
            trajectory=trajectory,
            turn=turn,
        )
        if actual != recomputed:
            raise ValueError(
                f"translation row provenance mismatch: {turn.turn_id}"
            )
        validated.append(actual)
    return tuple(validated)


def _run_turn(
    *,
    trajectory: FinalTranslationTrajectory,
    turn: FinalTranslationTurn,
    adapter,
    concept_catalog: ConceptPreferenceCatalog,
) -> FinalTranslationRow:
    started = perf_counter()
    usage: SemanticTokenUsage | None = None
    raw_output: str | None = None
    meaning: TurnMeaning | None = None
    status = "ok"
    failure_code: str | None = None
    try:
        call = adapter.propose_with_result(
            turn.case.message,
            turn.case.context,
        )
        meaning = call.meaning
        raw_output = call.raw_content
        usage = call.usage
    except SemanticProviderFailure as error:
        status = (
            "invalid_output"
            if error.code in {
                SemanticProviderFailureCode.INVALID_OUTPUT,
                SemanticProviderFailureCode.FORBIDDEN_OUTPUT,
            }
            else "provider_failure"
        )
        failure_code = error.code.value
        raw_output = error.raw_content
        usage = error.usage
    except Exception:
        status = "adapter_error"

    if meaning is None:
        return _make_row(
            trajectory=trajectory,
            turn=turn,
            status=status,
            provider_failure_code=failure_code,
            meaning=None,
            raw_output=raw_output,
            compiled_references=(),
            responsibility=None,
            gate_row=None,
            continuity_passed=False,
            subject_scope_passed=False,
            usage=usage,
            latency_ms=(perf_counter() - started) * 1000,
        )

    gate_row = evaluate_gate_case(
        case=turn.case,
        meaning=meaning,
        concept_catalog=concept_catalog,
        provider_call_count=1,
    )
    continuity_passed = (
        meaning.continuity_hint in turn.allowed_continuity_hints
    )
    subject_scope_passed = (
        meaning.subject_scope_hint in turn.allowed_subject_scope_hints
    )
    compiled_references: tuple[dict[str, JsonValue], ...] = ()
    responsibility: str | None = None
    try:
        compiled = compile_turn_meaning(
            message=turn.case.message,
            meaning=meaning,
            context=turn.case.context,
            concept_catalog=concept_catalog,
        )
        compiled_references = tuple(
            item.model_dump(mode="json")
            for item in compiled.references
        )
        responsibility = plan_task(compiled).mode
    except Exception:
        pass
    return _make_row(
        trajectory=trajectory,
        turn=turn,
        status=status,
        provider_failure_code=failure_code,
        meaning=meaning,
        raw_output=raw_output,
        compiled_references=compiled_references,
        responsibility=responsibility,
        gate_row=gate_row,
        continuity_passed=continuity_passed,
        subject_scope_passed=subject_scope_passed,
        usage=usage,
        latency_ms=(perf_counter() - started) * 1000,
    )


def _replay_turn(
    *,
    source: Mapping[str, object],
    trajectory: FinalTranslationTrajectory,
    turn: FinalTranslationTurn,
) -> FinalTranslationRow:
    raw = source.get("provider_raw_output")
    usage = SemanticTokenUsage(
        prompt_tokens=int(source.get("prompt_tokens", 0)),
        completion_tokens=int(source.get("completion_tokens", 0)),
        total_tokens=int(source.get("total_tokens", 0)),
    )
    try:
        meaning = TurnMeaning.model_validate_json(raw, strict=True)
    except (TypeError, ValidationError):
        meaning = None
    if meaning is None:
        return _make_row(
            trajectory=trajectory,
            turn=turn,
            status="invalid_output",
            provider_failure_code="invalid_output",
            meaning=None,
            raw_output=raw if isinstance(raw, str) else None,
            compiled_references=(),
            responsibility=None,
            gate_row=None,
            continuity_passed=False,
            subject_scope_passed=False,
            usage=usage,
            latency_ms=float(source.get("latency_ms", 0.0)),
        )
    return _run_replayed_meaning(
        trajectory=trajectory,
        turn=turn,
        meaning=meaning,
        raw_output=raw if isinstance(raw, str) else None,
        usage=usage,
        latency_ms=float(source.get("latency_ms", 0.0)),
    )


def _run_replayed_meaning(
    *,
    trajectory: FinalTranslationTrajectory,
    turn: FinalTranslationTurn,
    meaning: TurnMeaning,
    raw_output: str | None,
    usage: SemanticTokenUsage,
    latency_ms: float,
) -> FinalTranslationRow:
    catalog = _build_concept_catalog()
    gate_row = evaluate_gate_case(
        case=turn.case,
        meaning=meaning,
        concept_catalog=catalog,
        provider_call_count=1,
    )
    continuity_passed = (
        meaning.continuity_hint in turn.allowed_continuity_hints
    )
    subject_scope_passed = (
        meaning.subject_scope_hint in turn.allowed_subject_scope_hints
    )
    compiled_references: tuple[dict[str, JsonValue], ...] = ()
    responsibility = None
    try:
        compiled = compile_turn_meaning(
            message=turn.case.message,
            meaning=meaning,
            context=turn.case.context,
            concept_catalog=catalog,
        )
        compiled_references = tuple(
            item.model_dump(mode="json")
            for item in compiled.references
        )
        responsibility = plan_task(compiled).mode
    except Exception:
        pass
    return _make_row(
        trajectory=trajectory,
        turn=turn,
        status="ok",
        provider_failure_code=None,
        meaning=meaning,
        raw_output=raw_output,
        compiled_references=compiled_references,
        responsibility=responsibility,
        gate_row=gate_row,
        continuity_passed=continuity_passed,
        subject_scope_passed=subject_scope_passed,
        usage=usage,
        latency_ms=latency_ms,
    )


def _make_row(
    *,
    trajectory: FinalTranslationTrajectory,
    turn: FinalTranslationTurn,
    status: str,
    provider_failure_code: str | None,
    meaning: TurnMeaning | None,
    raw_output: str | None,
    compiled_references: tuple[dict[str, JsonValue], ...],
    responsibility: str | None,
    gate_row: TurnMeaningGateRow | None,
    continuity_passed: bool,
    subject_scope_passed: bool,
    usage: SemanticTokenUsage | None,
    latency_ms: float,
) -> FinalTranslationRow:
    translation_passed = bool(gate_row and gate_row.translation_passed)
    source_grounded = bool(gate_row and gate_row.source_grounded)
    binding_passed = bool(gate_row and gate_row.binding_passed)
    task_plan_passed = bool(gate_row and gate_row.task_plan_passed)
    recommendation_mode_passed = bool(
        meaning is not None
        and meaning.recommendation_mode
        == turn.expected_recommendation_mode
        and (
            meaning.recommendation_mode_basis.basis
            if meaning.recommendation_mode_basis is not None
            else None
        )
        == turn.expected_recommendation_mode_basis
    )
    schema_valid = meaning is not None
    failure_layer = None
    if meaning is None:
        failure_layer = "model_translation"
    elif (
        not translation_passed
        or not source_grounded
        or not recommendation_mode_passed
    ):
        failure_layer = "model_translation"
    elif not continuity_passed or not subject_scope_passed:
        failure_layer = "model_translation"
    elif not binding_passed:
        failure_layer = "identity_binding"
    elif not task_plan_passed:
        failure_layer = "route_selection"
    passed = (
        status == "ok"
        and schema_valid
        and translation_passed
        and source_grounded
        and binding_passed
        and task_plan_passed
        and continuity_passed
        and subject_scope_passed
        and recommendation_mode_passed
    )
    unsafe_downgrade_count = int(
        turn.required_safety_language == "safety"
        and (
            meaning is None
            or meaning.safety_language != "safety"
        )
    )
    output = (
        meaning.model_dump(mode="json")
        if meaning is not None
        else None
    )
    prompt_tokens = usage.prompt_tokens if usage is not None else 0
    completion_tokens = (
        usage.completion_tokens if usage is not None else 0
    )
    total_tokens = usage.total_tokens if usage is not None else 0
    return FinalTranslationRow(
        trajectory_id=trajectory.trajectory_id,
        turn_id=turn.turn_id,
        case_id=turn.case.case_id,
        status=status,
        provider_failure_code=provider_failure_code,
        schema_valid=schema_valid,
        translation_passed=translation_passed,
        source_grounded=source_grounded,
        binding_passed=binding_passed,
        task_plan_passed=task_plan_passed,
        continuity_passed=continuity_passed,
        subject_scope_passed=subject_scope_passed,
        recommendation_mode_passed=recommendation_mode_passed,
        passed=passed,
        failure_layer=failure_layer,
        wrong_product_or_image_binding_count=(
            0 if binding_passed else 1
        ),
        unsafe_downgrade_count=unsafe_downgrade_count,
        internal_public_language_count=0,
        provider_raw_output=raw_output,
        provider_output=output,
        compiled_references=compiled_references,
        responsibility=responsibility,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        latency_ms=latency_ms,
        input_sha256=_hash_json({
            "message": turn.case.message,
            "context": turn.case.context.model_dump(mode="json"),
        }),
        context_sha256=_hash_json(
            turn.case.context.model_dump(mode="json")
        ),
        provider_raw_output_sha256=_hash_text(raw_output),
        provider_output_sha256=_hash_json(output),
    )


def _write_report(
    *,
    rows: tuple[FinalTranslationRow, ...],
    trajectories: tuple[FinalTranslationTrajectory, ...],
    model: str,
    prompt_version: str,
    provider_call_count: int,
    output_dir: str | Path,
    stop_reason: str | None,
    focused_summary_sha256: str | None = None,
    fixture_path: str | None = None,
    fixture_sha256: str | None = None,
) -> FinalTranslationReport:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    results_bytes = b"".join(
        _canonical_json(row.model_dump(mode="json")) + b"\n"
        for row in rows
    )
    results_hash = sha256(results_bytes).hexdigest()
    (output / "results.jsonl").write_bytes(results_bytes)
    trajectory_passed = {
        trajectory.trajectory_id: all(
            row.passed
            for row in rows
            if row.trajectory_id == trajectory.trajectory_id
        )
        and sum(
            row.trajectory_id == trajectory.trajectory_id
            for row in rows
        ) == FINAL_TRANSLATION_TURNS_PER_TRAJECTORY
        for trajectory in trajectories
    }
    critical_count = sum(item.critical for item in trajectories)
    critical_passed = sum(
        trajectory_passed[item.trajectory_id]
        for item in trajectories
        if item.critical
    )
    report = FinalTranslationReport(
        model=model,
        prompt_version=prompt_version,
        trajectory_count=len(trajectories),
        critical_trajectory_count=critical_count,
        critical_trajectory_passed=critical_passed,
        expected_turn_count=FINAL_TRANSLATION_TURN_COUNT,
        turn_count=len(rows),
        provider_call_count=provider_call_count,
        stopped_early=stop_reason is not None,
        stop_reason=stop_reason,
        passed_turn_count=sum(row.passed for row in rows),
        schema_valid_count=sum(row.schema_valid for row in rows),
        translation_passed_count=sum(
            row.translation_passed for row in rows
        ),
        source_grounded_count=sum(row.source_grounded for row in rows),
        binding_passed_count=sum(row.binding_passed for row in rows),
        task_plan_passed_count=sum(
            row.task_plan_passed for row in rows
        ),
        recommendation_mode_passed_count=sum(
            row.recommendation_mode_passed for row in rows
        ),
        wrong_product_or_image_binding_count=sum(
            row.wrong_product_or_image_binding_count for row in rows
        ),
        wrong_binding_count=sum(
            row.wrong_product_or_image_binding_count for row in rows
        ),
        unsafe_downgrade_count=sum(
            row.unsafe_downgrade_count for row in rows
        ),
        internal_public_language_count=sum(
            row.internal_public_language_count for row in rows
        ),
        internal_language_count=sum(
            row.internal_public_language_count for row in rows
        ),
        serious_failure_count=sum(
            not row.passed for row in rows
        ),
        prompt_tokens=sum(row.prompt_tokens for row in rows),
        completion_tokens=sum(row.completion_tokens for row in rows),
        total_tokens=sum(row.total_tokens for row in rows),
        p95_latency_ms=_p95(tuple(row.latency_ms for row in rows)),
        focused_summary_sha256=focused_summary_sha256,
        fixture_path=fixture_path,
        fixture_sha256=fixture_sha256,
        results_sha256=results_hash,
        passed=(
            stop_reason is None
            and len(rows) == FINAL_TRANSLATION_TURN_COUNT
            and critical_passed == critical_count
            and sum(row.passed for row in rows) >= 46
            and sum(
                row.recommendation_mode_passed for row in rows
            ) == len(rows)
            and sum(
                row.wrong_product_or_image_binding_count
                for row in rows
            ) == 0
            and sum(row.unsafe_downgrade_count for row in rows) == 0
            and sum(
                row.internal_public_language_count for row in rows
            ) == 0
        ),
    )
    summary_bytes = _canonical_json(report.model_dump(mode="json")) + b"\n"
    (output / "summary.json").write_bytes(summary_bytes)
    (output / "SHA256SUMS").write_text(
        (
            f"{results_hash}  results.jsonl\n"
            f"{sha256(summary_bytes).hexdigest()}  summary.json\n"
        ),
        encoding="ascii",
    )
    return report


def _validate_trajectories(
    trajectories: Sequence[FinalTranslationTrajectory],
) -> None:
    if len(trajectories) != FINAL_TRANSLATION_CASE_COUNT:
        raise ValueError("final translation requires 12 trajectories")
    if any(
        type(trajectory) is not FinalTranslationTrajectory
        for trajectory in trajectories
    ):
        raise TypeError("trajectories must contain exact final trajectories")
    turn_count = sum(len(item.turns) for item in trajectories)
    if turn_count != FINAL_TRANSLATION_TURN_COUNT:
        raise ValueError("final translation requires 48 turns")


def _build_concept_catalog() -> ConceptPreferenceCatalog:
    assets = build_selection_concept_assets()
    return ConceptPreferenceCatalog.from_projections(
        assets.projections
    )


def _hash_json(value: object) -> str:
    return sha256(_canonical_json(value)).hexdigest()


def _hash_text(value: str | None) -> str:
    return sha256((value or "").encode("utf-8")).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _p95(values: tuple[float, ...]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, (95 * len(ordered) + 99) // 100)
    return ordered[rank - 1]


def _read_context_paths(
    path: Path,
) -> tuple[Path, Path]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("attempt context is invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("attempt context is invalid")
    readiness_path = Path(str(payload.get("readiness_path")))
    ledger_path = Path(str(payload.get("ledger_path")))
    return readiness_path, ledger_path


def _failure_owner(layer: object) -> str:
    return {
        "model_translation": "translation",
        "source_grounding": "admission",
        "identity_binding": "retrieval_identity",
        "route_selection": "planning_state",
    }.get(str(layer), "translation")


def _first_failed_row(output_dir: Path) -> dict[str, Any]:
    path = output_dir / "results.jsonl"
    if not path.is_file():
        return {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if isinstance(row, dict) and row.get("passed") is not True:
            return row
    return {}


def _focused_summary_sha256(output_root: Path) -> str:
    path = output_root / "focused.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("focused release summary is invalid") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version")
        != "guide-final-focused-gate-v1"
        or payload.get("passed") is not True
    ):
        raise ValueError("focused release summary is invalid")
    return sha256(path.read_bytes()).hexdigest()


def validate_completed_final_translation_evidence(
    attempt_output: str | Path,
) -> FinalTranslationReport:
    attempt_root = Path(attempt_output).resolve()
    output = attempt_root / "real-translation"
    if (
        not attempt_root.is_dir()
        or attempt_root.is_symlink()
        or not output.is_dir()
        or output.is_symlink()
    ):
        raise ValueError("translation terminal evidence is invalid")
    expected_names = {"results.jsonl", "summary.json", "SHA256SUMS"}
    actual_names = {
        item.name
        for item in output.iterdir()
        if item.is_file() and not item.is_symlink()
    }
    if (
        actual_names != expected_names
        or any(item.is_symlink() for item in output.iterdir())
    ):
        raise ValueError("translation terminal evidence is invalid")
    results_path = output / "results.jsonl"
    summary_path = output / "summary.json"
    checksums_path = output / "SHA256SUMS"
    results_bytes = results_path.read_bytes()
    summary_bytes = summary_path.read_bytes()
    expected_checksums = (
        f"{sha256(results_bytes).hexdigest()}  results.jsonl\n"
        f"{sha256(summary_bytes).hexdigest()}  summary.json\n"
    ).encode("ascii")
    if checksums_path.read_bytes() != expected_checksums:
        raise ValueError("translation terminal evidence is invalid")
    try:
        raw_rows = [
            json.loads(line)
            for line in results_bytes.splitlines()
            if line.strip()
        ]
        report = FinalTranslationReport.model_validate_json(
            summary_bytes,
            strict=True,
        )
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(
            "translation terminal evidence is invalid"
        ) from exc
    trajectories = load_final_translation_trajectories(_DEFAULT_CASES)
    rows = validate_final_translation_rows(
        trajectories=trajectories,
        rows=raw_rows,
    )
    canonical_results = b"".join(
        _canonical_json(row.model_dump(mode="json")) + b"\n"
        for row in rows
    )
    focused_path = attempt_root / "focused.json"
    if (
        canonical_results != results_bytes
        or summary_bytes
        != _canonical_json(report.model_dump(mode="json")) + b"\n"
        or report.model != DEEPSEEK_V4_PRO_MODEL
        or report.prompt_version == "unknown"
        or report.trajectory_count != FINAL_TRANSLATION_CASE_COUNT
        or report.critical_trajectory_count
        != FINAL_TRANSLATION_CASE_COUNT
        or report.critical_trajectory_passed
        != FINAL_TRANSLATION_CASE_COUNT
        or report.expected_turn_count != FINAL_TRANSLATION_TURN_COUNT
        or report.turn_count != FINAL_TRANSLATION_TURN_COUNT
        or report.provider_call_count != FINAL_TRANSLATION_TURN_COUNT
        or report.stopped_early
        or report.stop_reason is not None
        or report.passed_turn_count != FINAL_TRANSLATION_TURN_COUNT
        or report.schema_valid_count != FINAL_TRANSLATION_TURN_COUNT
        or report.translation_passed_count
        != FINAL_TRANSLATION_TURN_COUNT
        or report.source_grounded_count != FINAL_TRANSLATION_TURN_COUNT
        or report.binding_passed_count != FINAL_TRANSLATION_TURN_COUNT
        or report.task_plan_passed_count
        != FINAL_TRANSLATION_TURN_COUNT
        or report.recommendation_mode_passed_count
        != FINAL_TRANSLATION_TURN_COUNT
        or report.wrong_product_or_image_binding_count != 0
        or report.wrong_binding_count != 0
        or report.unsafe_downgrade_count != 0
        or report.internal_public_language_count != 0
        or report.internal_language_count != 0
        or report.serious_failure_count != 0
        or report.results_sha256 != sha256(results_bytes).hexdigest()
        or report.fixture_path != FINAL_TRANSLATION_FIXTURE_PATH
        or report.fixture_sha256 != sha256(_DEFAULT_CASES.read_bytes()).hexdigest()
        or not focused_path.is_file()
        or focused_path.is_symlink()
        or report.focused_summary_sha256
        != sha256(focused_path.read_bytes()).hexdigest()
        or report.passed is not True
        or any(row.passed is not True for row in rows)
    ):
        raise ValueError("translation terminal evidence is invalid")
    return report


def validate_final_translation_fixture(
    path: str | Path,
) -> tuple[str, str]:
    supplied = Path(path)
    lexical = (
        supplied.absolute()
        if supplied.is_absolute()
        else (Path.cwd() / supplied).absolute()
    )
    expected = _DEFAULT_CASES.absolute()
    if (
        lexical != expected
        or supplied.is_symlink()
        or not expected.is_file()
        or expected.is_symlink()
    ):
        raise ValueError(
            "final translation requires the canonical v5 fixture"
        )
    return FINAL_TRANSLATION_FIXTURE_PATH, sha256(
        expected.read_bytes()
    ).hexdigest()


def run_authorized_final_translation(
    *,
    cases_path: str | Path,
    attempt_context_path: str | Path,
    phase: str,
    key_path: str | Path = DEFAULT_KEY_PATH,
    model: str = DEEPSEEK_V4_PRO_MODEL,
    state_dir: str | Path,
) -> FinalTranslationReport:
    if phase != "translation":
        raise ValueError("final translation phase must be translation")
    if model != DEEPSEEK_V4_PRO_MODEL:
        raise ValueError("model must be deepseek-v4-pro")
    context_path = Path(attempt_context_path).resolve()
    readiness_path, ledger_path = _read_context_paths(context_path)
    context = read_attempt_context(
        context_path,
        ledger_path=ledger_path,
        readiness_path=readiness_path,
    )
    phase_ids = context.get("phase_attempt_ids")
    if (
        not isinstance(phase_ids, dict)
        or not phase_ids
        or attempt_context_phase(context) != "translation"
    ):
        raise ValueError(
            "attempt context does not own the translation phase"
        )
    verify_task11_readiness(
        readiness_path=readiness_path,
        ledger_path=ledger_path,
        expected_manifest_sha256=str(
            context.get("expected_manifest_sha256")
        ),
    )
    output_root = Path(str(context.get("output_directory"))).resolve()
    if context_path.parent != output_root:
        raise ValueError("attempt output directory is not context-owned")
    output_dir = output_root / "real-translation"
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError("real translation output already exists")
    fixture_path, fixture_sha256 = validate_final_translation_fixture(
        cases_path
    )
    focused_summary_sha256 = _focused_summary_sha256(output_root)
    trajectories = load_final_translation_trajectories(cases_path)
    api_key = read_private_api_key(key_path)
    usage_limiter = build_provider_usage_limiter(
        provider="deepseek_official",
        daily_budget_cny=Decimal("100.00"),
        daily_call_cap=FINAL_TRANSLATION_TURN_COUNT,
        state_dir=state_dir,
    )
    consume_attempt_context(
        context_path,
        phase="translation",
        ledger_path=ledger_path,
        readiness_path=readiness_path,
    )
    consumed = True
    adapter = None
    try:
        assets = build_selection_concept_assets()
        concept_ids = tuple(sorted({
            item.concept_id for item in assets.projections
        }))
        adapter = DeepSeekTurnMeaningAdapter(
            api_key=api_key,
            model=model,
            concept_catalog=concept_ids,
            timeout_seconds=12.0,
            max_tokens=1024,
            daily_budget_cny=Decimal("100.00"),
            daily_call_cap=FINAL_TRANSLATION_TURN_COUNT,
            usage_limiter=usage_limiter,
        )
        try:
            report = run_final_translation_gate(
                trajectories=trajectories,
                adapter=adapter,
                output_dir=output_dir,
                focused_summary_sha256=focused_summary_sha256,
                fixture_path=fixture_path,
                fixture_sha256=fixture_sha256,
            )
        finally:
            adapter.close()
            adapter = None
        if report.passed:
            complete_attempt(context_path, result="passed")
        else:
            failed = _first_failed_row(output_dir)
            complete_attempt(
                context_path,
                result="failed",
                first_failure_turn_id=str(
                    failed.get("turn_id") or "translation-unknown"
                ),
                first_failure_owner=_failure_owner(
                    failed.get("failure_layer")
                ),
                failure_code=str(
                    failed.get("provider_failure_code")
                    or failed.get("status")
                    or report.stop_reason
                    or "translation_gate_failed"
                ),
                evidence_directory=str(output_dir),
            )
        consumed = False
        return report
    except BaseException as exc:
        if consumed:
            output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            failure_path = output_dir / "failure.json"
            if not failure_path.exists() and not failure_path.is_symlink():
                failure_path.write_text(
                    json.dumps(
                        {
                            "schema_version": (
                                "guide-final-real-translation-failure-v1"
                            ),
                            "error_type": type(exc).__name__,
                        },
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
            complete_attempt(
                context_path,
                result="failed",
                first_failure_turn_id="translation-runtime",
                first_failure_owner="translation",
                failure_code=type(exc).__name__,
                evidence_directory=str(output_dir),
            )
        raise
    finally:
        if adapter is not None:
            adapter.close()


def _parse_args(
    argv: Sequence[str] | None = None,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default=str(_DEFAULT_CASES))
    parser.add_argument("--attempt-context", required=True)
    parser.add_argument(
        "--phase",
        choices=("translation",),
        required=True,
    )
    parser.add_argument("--key-path", default=DEFAULT_KEY_PATH)
    parser.add_argument("--model", default=DEEPSEEK_V4_PRO_MODEL)
    parser.add_argument("--state-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        report = run_authorized_final_translation(
            cases_path=args.cases,
            attempt_context_path=args.attempt_context,
            phase=args.phase,
            key_path=args.key_path,
            model=args.model,
            state_dir=args.state_dir,
        )
    except KeyPrecheckError as error:
        print(json.dumps({
            "status": "key_precheck_failed",
            "code": error.code.value,
        }))
        return 5
    print(report.model_dump_json())
    return 0 if report.passed else 3


__all__ = [
    "FINAL_TRANSLATION_CASE_COUNT",
    "FINAL_TRANSLATION_FIXTURE_PATH",
    "FINAL_TRANSLATION_TURN_COUNT",
    "FINAL_TRANSLATION_TURNS_PER_TRAJECTORY",
    "FinalTranslationReport",
    "FinalTranslationTrajectory",
    "FinalTranslationTurn",
    "FinalTurnExpectations",
    "derive_final_turn_expectations",
    "load_final_translation_trajectories",
    "main",
    "replay_final_translation_gate",
    "run_authorized_final_translation",
    "run_final_translation_gate",
    "validate_completed_final_translation_evidence",
    "validate_final_translation_rows",
    "validate_final_translation_fixture",
]


if __name__ == "__main__":
    raise SystemExit(main())
