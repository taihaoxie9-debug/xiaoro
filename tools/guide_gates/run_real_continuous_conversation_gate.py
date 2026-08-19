from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.guide.adapters.llm.deepseek_intent import (
    DEEPSEEK_V4_PRO_MODEL,
)
from app.guide.adapters.llm.deepseek_turn_meaning import (
    DeepSeekTurnMeaningAdapter,
)
from app.guide.adapters.catalog import CanonicalProductReader
from app.guide.adapters.llm.contracts import (
    SemanticProviderFailure,
    SemanticProviderFailureCode,
)
from app.guide.intent.concept_preferences import (
    ConceptPreferenceCatalog,
)
from app.guide.presentation.public_language import (
    PublicLanguageError,
    validate_public_text,
)
from app.guide.understanding.context_resolver import (
    resolve_semantic_context,
)
from app.guide.understanding.semantic_contracts import SemanticContext
from app.guide.understanding.turn_meaning_contracts import TurnMeaning
from app.guide_runtime.composition import (
    build_selection_concept_assets,
)
from tools.guide_gates.continuous_conversation_fixture import (
    load_frozen_trajectories,
)
from tools.guide_gates.continuous_conversation_mechanical_truth import (
    MechanicalTruthSpec,
    TruthCorrectionOverlay,
    TurnTruthRequirement,
    apply_truth_correction_overlay,
    audit_mechanical_truth,
)
from tools.guide_gates.continuous_conversation_gate import (
    ContinuousFailureLayer,
    ContinuousRuntime,
    ContinuousRuntimeTurnResult,
    ContinuousTrajectory,
    ContinuousTurnExpectation,
    ContinuousTurnTrace,
)
from tools.guide_gates.continuous_conversation_runtime import (
    build_local_continuous_runtime,
    runtime_image_fixtures,
)
from tools.guide_gates.run_official_deepseek_smoke import (
    DEFAULT_KEY_PATH,
    KeyPrecheckError,
    read_private_api_key,
)


RuntimeFactory = Callable[
    [ContinuousTrajectory, Path],
    ContinuousRuntime,
]

_LAYER_ORDER = (
    ContinuousFailureLayer.MODEL_TRANSLATION,
    ContinuousFailureLayer.SEMANTIC_ADMISSION,
    ContinuousFailureLayer.IDENTITY_BINDING,
    ContinuousFailureLayer.ROUTE_SELECTION,
    ContinuousFailureLayer.STATE_TRANSITION,
    ContinuousFailureLayer.DECISION_EXECUTION,
    ContinuousFailureLayer.DATA_COVERAGE,
    ContinuousFailureLayer.PUBLIC_PRESENTATION,
)
_SCORABLE_TRANSLATION_FAILURES = frozenset({
    SemanticProviderFailureCode.INVALID_OUTPUT,
    SemanticProviderFailureCode.FORBIDDEN_OUTPUT,
})


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )


class ContinuousLayerEvidence(_StrictFrozen):
    model_translation: bool
    semantic_admission: bool
    identity_binding: bool
    route_selection: bool
    state_transition: bool
    decision_execution: bool
    data_coverage: bool
    public_presentation: bool


class ContinuousTurnEvaluation(_StrictFrozen):
    trajectory_id: str
    turn_id: str
    layer_evidence: ContinuousLayerEvidence
    failure_layer: ContinuousFailureLayer | None
    wrong_product_or_image_binding_count: int = Field(ge=0)
    unauthorized_state_transition_count: int = Field(ge=0)
    hard_condition_override_count: int = Field(ge=0)
    unsafe_downgrade_count: int = Field(ge=0)
    cross_session_or_subject_leak_count: int = Field(ge=0)
    internal_public_language_count: int = Field(ge=0)
    stale_focus_hijack_count: int = Field(ge=0)
    passed: bool


class ContinuousCaptureRow(_StrictFrozen):
    trajectory_id: str
    turn_id: str
    turn_ordinal: int = Field(ge=1, le=5)
    message: str
    starting_version: int = Field(ge=0)
    semantic_context: SemanticContext
    provider_call_attempted: bool = True
    provider_raw_output: str | None
    provider_trace_id: str | None
    provider_output: TurnMeaning | None
    trace: ContinuousTurnTrace | None
    evaluation: ContinuousTurnEvaluation
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_raw_output_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    provider_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    trace_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ContinuousGateReport(_StrictFrozen):
    schema_version: Literal[
        "guide-continuous-gate-summary-v1"
    ] = "guide-continuous-gate-summary-v1"
    model: str
    prompt_version: str
    trajectory_count: int = Field(ge=0)
    turn_count: int = Field(ge=0)
    provider_call_count: int = Field(ge=0)
    reused_provider_call_count: int = Field(ge=0)
    new_provider_call_count: int = Field(ge=0)
    skipped_dependency_turn_count: int = Field(ge=0)
    copywriter_call_count: Literal[0] = 0
    retry_count: Literal[0] = 0
    passed_turn_count: int = Field(ge=0)
    passed_trajectory_count: int = Field(ge=0)
    complete_trajectory_rate: float = Field(ge=0.0, le=1.0)
    failure_counts: dict[ContinuousFailureLayer, int]
    wrong_product_or_image_binding_count: int = Field(ge=0)
    unauthorized_state_transition_count: int = Field(ge=0)
    hard_condition_override_count: int = Field(ge=0)
    unsafe_downgrade_count: int = Field(ge=0)
    cross_session_or_subject_leak_count: int = Field(ge=0)
    internal_public_language_count: int = Field(ge=0)
    stale_focus_hijack_count: int = Field(ge=0)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    results_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    passed: bool


class ContinuousReplayReport(_StrictFrozen):
    schema_version: Literal[
        "guide-continuous-replay-summary-v1"
    ] = "guide-continuous-replay-summary-v1"
    trajectory_count: int = Field(ge=0)
    expected_turn_count: int = Field(ge=1)
    captured_turn_count: int = Field(ge=0)
    replayed_turn_count: int = Field(ge=0)
    capture_complete: bool
    replay_passed: bool
    provider_call_count: Literal[0] = 0
    copywriter_call_count: Literal[0] = 0
    retry_count: Literal[0] = 0
    passed_turn_count: int = Field(ge=0)
    passed_trajectory_count: int = Field(ge=0)
    failure_counts: dict[ContinuousFailureLayer, int]
    wrong_product_or_image_binding_count: int = Field(ge=0)
    unauthorized_state_transition_count: int = Field(ge=0)
    hard_condition_override_count: int = Field(ge=0)
    unsafe_downgrade_count: int = Field(ge=0)
    cross_session_or_subject_leak_count: int = Field(ge=0)
    internal_public_language_count: int = Field(ge=0)
    stale_focus_hijack_count: int = Field(ge=0)
    results_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    passed: bool


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _hash_json(value: object) -> str:
    return sha256(_canonical_json(value)).hexdigest()


def _hash_text(value: str | None) -> str:
    return sha256((value or "").encode("utf-8")).hexdigest()


def _meaning_from_captured_output(
    source_row: dict[str, object],
) -> TurnMeaning | None:
    output = source_row.get("provider_output")
    if output is not None:
        if source_row.get("provider_output_sha256") != _hash_json(
            output
        ):
            raise ValueError("capture provider output hash drifted")
        return TurnMeaning.model_validate(output, strict=True)
    raw_output = source_row.get("provider_raw_output")
    if not isinstance(raw_output, str):
        return None
    if source_row.get("provider_raw_output_sha256") != _hash_text(
        raw_output
    ):
        raise ValueError("capture raw provider output hash drifted")
    try:
        return TurnMeaning.model_validate_json(
            raw_output,
            strict=True,
        )
    except ValidationError:
        return None


def _contains_expected(actual: object, expected: object) -> bool:
    if isinstance(expected, dict):
        return (
            isinstance(actual, dict)
            and all(
                key in actual
                and _contains_expected(actual[key], value)
                for key, value in expected.items()
            )
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(
                _contains_expected(left, right)
                for left, right in zip(
                    actual,
                    expected,
                    strict=True,
                )
            )
        )
    return actual == expected


def _binding_keys(bindings) -> tuple[tuple[int, str | None], ...]:
    return tuple(
        (binding.product_id, binding.variant_scope)
        for binding in bindings
    )


def _translation_matches(
    turn: ContinuousTurnExpectation,
    meaning: TurnMeaning,
) -> bool:
    expected = turn.acceptable_semantic
    topic_matches = (
        meaning.topic_hint in expected.topic_hints
        or (
            meaning.topic_hint is None
            and turn.expected_route.continuity != "replace_task"
        )
    )
    return (
        meaning.operation_hint in expected.operation_hints
        and topic_matches
        and meaning.continuity_hint in expected.continuity_hints
        and meaning.subject_scope_hint in expected.subject_scope_hints
    )


def _public_presentation_matches(
    turn: ContinuousTurnExpectation,
    trace: ContinuousTurnTrace,
) -> tuple[bool, bool]:
    internal_language = False
    try:
        for message in trace.public_messages:
            validate_public_text(message)
    except PublicLanguageError:
        internal_language = True
    if turn.expected_clarification:
        return (
            (
                trace.clarification
                and trace.presentation_mode is None
                and not internal_language
            ),
            internal_language,
        )
    return (
        (
            trace.presentation_mode
            == turn.expected_presentation_mode
            and (
                bool(trace.public_messages)
            )
            and not internal_language
        ),
        internal_language,
    )


def evaluate_continuous_turn(
    *,
    trajectory_id: str,
    turn: ContinuousTurnExpectation,
    meaning: TurnMeaning,
    trace: ContinuousTurnTrace,
    truth: TurnTruthRequirement | None = None,
    outcome_scoring: bool = False,
) -> ContinuousTurnEvaluation:
    if type(turn) is not ContinuousTurnExpectation:
        raise TypeError(
            "turn must be an exact ContinuousTurnExpectation"
        )
    if type(meaning) is not TurnMeaning:
        raise TypeError("meaning must be an exact TurnMeaning")
    if type(trace) is not ContinuousTurnTrace:
        raise TypeError("trace must be an exact ContinuousTurnTrace")
    if truth is not None and (
        type(truth) is not TurnTruthRequirement
        or truth.turn_id != turn.turn_id
    ):
        raise TypeError(
            "truth must match the evaluated turn"
        )
    identity_binding = (
        _binding_keys(trace.bindings)
        == _binding_keys(turn.expected_bindings)
    )
    route_selection = (
        trace.route.processor == turn.expected_route.processor
        if outcome_scoring
        else trace.route
        in (
            turn.expected_route,
            *turn.acceptable_routes,
        )
    )
    state_transition = (
        _contains_expected(
            trace.final_snapshot.model_dump(mode="json"),
            turn.expected_snapshot_subset,
        )
        and not trace.cross_session_leak
    )
    decision_execution = (
        _contains_expected(
            trace.task_plan,
            turn.expected_task_plan_subset,
        )
        and trace.safety == turn.expected_safety
        and trace.clarification == turn.expected_clarification
        and not trace.hard_condition_override
    )
    data_coverage = _data_coverage_matches(
        turn=turn,
        trace=trace,
        truth=truth,
    )
    public_presentation, internal_language = (
        _public_presentation_matches(turn, trace)
    )
    evidence = ContinuousLayerEvidence(
        model_translation=(
            True
            if outcome_scoring
            else _translation_matches(turn, meaning)
        ),
        semantic_admission=trace.semantic_admission_passed,
        identity_binding=identity_binding,
        route_selection=route_selection,
        state_transition=state_transition,
        decision_execution=decision_execution,
        data_coverage=data_coverage,
        public_presentation=public_presentation,
    )
    evidence_payload = evidence.model_dump(mode="json")
    failure_layer = next(
        (
            layer
            for layer in _LAYER_ORDER
            if not evidence_payload[layer.value]
        ),
        None,
    )
    unexpected_bindings = set(_binding_keys(trace.bindings)).difference(
        _binding_keys(turn.expected_bindings)
    )
    unexpected_cards = (
        set(trace.card_ids).difference(
            truth.eligible_product_ids
        )
        if truth is not None
        else set()
    )
    stale_focus = (
        turn.expected_route.continuity == "return_to_focus"
        and (
            bool(unexpected_bindings or unexpected_cards)
            or (
                trace.route.processor
                != turn.expected_route.processor
                and trace.route.focus_source != "none"
            )
        )
    )
    return ContinuousTurnEvaluation(
        trajectory_id=trajectory_id,
        turn_id=turn.turn_id,
        layer_evidence=evidence,
        failure_layer=failure_layer,
        wrong_product_or_image_binding_count=(
            len(unexpected_bindings) + len(unexpected_cards)
        ),
        unauthorized_state_transition_count=(
            int(
                failure_layer
                is ContinuousFailureLayer.STATE_TRANSITION
            )
        ),
        hard_condition_override_count=int(
            trace.hard_condition_override
        ),
        unsafe_downgrade_count=int(
            turn.expected_safety and not trace.safety
        ),
        cross_session_or_subject_leak_count=int(
            trace.cross_session_leak
        ),
        internal_public_language_count=int(internal_language),
        stale_focus_hijack_count=int(stale_focus),
        passed=failure_layer is None,
    )


def _data_coverage_matches(
    *,
    turn: ContinuousTurnExpectation,
    trace: ContinuousTurnTrace,
    truth: TurnTruthRequirement | None,
) -> bool:
    if truth is None:
        return (
            len(trace.card_ids) == len(turn.expected_card_ids)
            and set(trace.card_ids) == set(turn.expected_card_ids)
        )
    if truth.card_policy == "none":
        return not trace.card_ids
    eligible = set(truth.eligible_product_ids)
    if truth.card_policy == "eligible_subset":
        return (
            truth.minimum_card_count
            <= len(trace.card_ids)
            <= truth.maximum_card_count
            and len(trace.card_ids) == len(set(trace.card_ids))
            and set(trace.card_ids).issubset(eligible)
        )
    return (
        truth.minimum_card_count
        <= len(trace.card_ids)
        <= truth.maximum_card_count
        and set(trace.card_ids) == eligible
    )


def _runtime_failure_layer(runtime: object) -> ContinuousFailureLayer:
    provider = getattr(runtime, "failure_layer_for_last_error", None)
    layer = provider() if callable(provider) else None
    if not isinstance(layer, ContinuousFailureLayer):
        return ContinuousFailureLayer.DECISION_EXECUTION
    return layer


def _failed_translation_evaluation(
    *,
    trajectory_id: str,
    turn: ContinuousTurnExpectation,
) -> ContinuousTurnEvaluation:
    return ContinuousTurnEvaluation(
        trajectory_id=trajectory_id,
        turn_id=turn.turn_id,
        layer_evidence=ContinuousLayerEvidence(
            model_translation=False,
            semantic_admission=False,
            identity_binding=False,
            route_selection=False,
            state_transition=False,
            decision_execution=False,
            data_coverage=False,
            public_presentation=False,
        ),
        failure_layer=ContinuousFailureLayer.MODEL_TRANSLATION,
        wrong_product_or_image_binding_count=0,
        unauthorized_state_transition_count=0,
        hard_condition_override_count=0,
        unsafe_downgrade_count=0,
        cross_session_or_subject_leak_count=0,
        internal_public_language_count=0,
        stale_focus_hijack_count=0,
        passed=False,
    )


def _failed_runtime_evaluation(
    *,
    trajectory_id: str,
    turn: ContinuousTurnExpectation,
    meaning: TurnMeaning,
    failure_layer: ContinuousFailureLayer,
) -> ContinuousTurnEvaluation:
    if failure_layer is ContinuousFailureLayer.MODEL_TRANSLATION:
        return _failed_translation_evaluation(
            trajectory_id=trajectory_id,
            turn=turn,
        )
    failure_index = _LAYER_ORDER.index(failure_layer)
    checks = {
        layer.value: index < failure_index
        for index, layer in enumerate(_LAYER_ORDER)
    }
    checks["model_translation"] = _translation_matches(
        turn,
        meaning,
    )
    evidence = ContinuousLayerEvidence.model_validate(
        checks,
        strict=True,
    )
    return ContinuousTurnEvaluation(
        trajectory_id=trajectory_id,
        turn_id=turn.turn_id,
        layer_evidence=evidence,
        failure_layer=failure_layer,
        wrong_product_or_image_binding_count=int(
            failure_layer
            is ContinuousFailureLayer.IDENTITY_BINDING
        ),
        unauthorized_state_transition_count=int(
            failure_layer
            is ContinuousFailureLayer.STATE_TRANSITION
        ),
        hard_condition_override_count=0,
        unsafe_downgrade_count=int(
            turn.expected_safety
            and _LAYER_ORDER.index(failure_layer)
            <= _LAYER_ORDER.index(
                ContinuousFailureLayer.DECISION_EXECUTION
            )
        ),
        cross_session_or_subject_leak_count=0,
        internal_public_language_count=0,
        stale_focus_hijack_count=int(
            turn.expected_route.continuity == "return_to_focus"
            and failure_layer in {
                ContinuousFailureLayer.ROUTE_SELECTION,
                ContinuousFailureLayer.STATE_TRANSITION,
            }
        ),
        passed=False,
    )


def _public_card_ids(
    events: Sequence[tuple[str, dict[str, Any]]],
) -> tuple[int, ...]:
    ids: list[int] = []
    for event, data in events:
        if event != "products":
            continue
        rows = data.get("products", data.get("cards", ()))
        if not isinstance(rows, (list, tuple)):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            product_id = row.get("id", row.get("product_id"))
            if (
                type(product_id) is int
                and product_id not in ids
            ):
                ids.append(product_id)
    return tuple(ids)


def _execute_turn(
    *,
    trajectory: ContinuousTrajectory,
    turn: ContinuousTurnExpectation,
    meaning: TurnMeaning,
    runtime: ContinuousRuntime,
    starting_version: int,
) -> ContinuousTurnTrace:
    runtime_result = runtime.execute(
        session_id=trajectory.trajectory_id,
        conversation_version=starting_version,
        message=turn.message,
        meaning=meaning,
        image_fixture_ids=turn.image_fixture_ids,
    )
    if type(runtime_result) is not ContinuousRuntimeTurnResult:
        raise TypeError(
            "runtime must return ContinuousRuntimeTurnResult"
        )
    events = runtime_result.events
    delivery_event = (
        runtime_result.delivery_event
        if runtime_result.delivery_event is not None
        else events[-1]
    )
    if not events or events[-1][0] != "end":
        runtime.discard(delivery_event)
        raise ValueError(f"{turn.turn_id} did not emit terminal end")
    terminal_version = events[-1][1].get("conversation_version")
    if (
        type(terminal_version) is not int
        or terminal_version != starting_version + 1
    ):
        runtime.discard(delivery_event)
        raise ValueError(
            f"{turn.turn_id} did not advance exactly once"
        )
    runtime.commit(delivery_event)
    snapshot = runtime.load_snapshot(trajectory.trajectory_id)
    if snapshot.version != terminal_version:
        raise ValueError(
            f"{turn.turn_id} committed snapshot version drifted"
        )
    return ContinuousTurnTrace(
        turn_id=turn.turn_id,
        starting_version=starting_version,
        terminal_version=terminal_version,
        image_fixture_ids=turn.image_fixture_ids,
        meaning=meaning,
        semantic_admission_passed=(
            runtime_result.semantic_admission_passed
        ),
        bindings=runtime_result.bindings,
        route=runtime_result.route,
        task_plan=runtime_result.task_plan,
        card_ids=_public_card_ids(events),
        public_messages=tuple(
            str(data["content"])
            for event, data in events
            if (
                event == "message"
                and isinstance(data.get("content"), str)
            )
        ),
        event_names=tuple(event for event, _ in events),
        safety=runtime_result.safety,
        clarification=runtime_result.clarification,
        presentation_mode=runtime_result.presentation_mode,
        hard_condition_override=(
            runtime_result.hard_condition_override
        ),
        cross_session_leak=runtime_result.cross_session_leak,
        final_snapshot=snapshot,
    )


def _usage_value(usage: object, field: str) -> int:
    value = (
        usage.get(field, 0)
        if isinstance(usage, dict)
        else getattr(usage, field, 0)
    )
    return value if type(value) is int and value >= 0 else 0


def _capture_row(
    *,
    trajectory: ContinuousTrajectory,
    turn: ContinuousTurnExpectation,
    turn_ordinal: int,
    starting_version: int,
    context: SemanticContext,
    provider_raw_output: str | None,
    provider_trace_id: str | None,
    meaning: TurnMeaning | None,
    trace: ContinuousTurnTrace | None,
    evaluation: ContinuousTurnEvaluation,
    usage: object,
    provider_call_attempted: bool = True,
) -> ContinuousCaptureRow:
    input_payload = {
        "trajectory_id": trajectory.trajectory_id,
        "turn_id": turn.turn_id,
        "message": turn.message,
        "starting_version": starting_version,
        "image_fixture_ids": list(turn.image_fixture_ids),
    }
    context_payload = context.model_dump(mode="json")
    output_payload = (
        meaning.model_dump(mode="json")
        if meaning is not None
        else None
    )
    trace_payload = (
        trace.model_dump(mode="json")
        if trace is not None
        else None
    )
    row_payload = {
        "input": input_payload,
        "context": context_payload,
        "provider_raw_output": provider_raw_output,
        "provider_trace_id": provider_trace_id,
        "provider_output": output_payload,
        "provider_call_attempted": provider_call_attempted,
        "trace": trace_payload,
        "evaluation": evaluation.model_dump(mode="json"),
    }
    return ContinuousCaptureRow(
        trajectory_id=trajectory.trajectory_id,
        turn_id=turn.turn_id,
        turn_ordinal=turn_ordinal,
        message=turn.message,
        starting_version=starting_version,
        semantic_context=context,
        provider_call_attempted=provider_call_attempted,
        provider_raw_output=provider_raw_output,
        provider_trace_id=provider_trace_id,
        provider_output=meaning,
        trace=trace,
        evaluation=evaluation,
        prompt_tokens=_usage_value(usage, "prompt_tokens"),
        completion_tokens=_usage_value(
            usage,
            "completion_tokens",
        ),
        total_tokens=_usage_value(usage, "total_tokens"),
        input_sha256=_hash_json(input_payload),
        context_sha256=_hash_json(context_payload),
        provider_raw_output_sha256=_hash_text(
            provider_raw_output
        ),
        provider_output_sha256=_hash_json(output_payload),
        trace_sha256=_hash_json(trace_payload),
        result_sha256=_hash_json(row_payload),
    )


def _validate_trajectories(
    trajectories: Sequence[ContinuousTrajectory],
) -> tuple[ContinuousTrajectory, ...]:
    normalized = tuple(trajectories)
    if not normalized or any(
        type(item) is not ContinuousTrajectory
        for item in normalized
    ):
        raise TypeError(
            "trajectories must be nonempty exact "
            "ContinuousTrajectory values"
        )
    ids = tuple(item.trajectory_id for item in normalized)
    if len(ids) != len(set(ids)):
        raise ValueError("trajectory IDs must be unique")
    return normalized


def _validate_truth_by_turn(
    *,
    trajectories: Sequence[ContinuousTrajectory],
    truth_by_turn: Mapping[str, TurnTruthRequirement] | None,
) -> dict[str, TurnTruthRequirement]:
    if truth_by_turn is None:
        return {}
    expected_ids = {
        turn.turn_id
        for trajectory in trajectories
        for turn in trajectory.turns
    }
    normalized = dict(truth_by_turn)
    if set(normalized) != expected_ids or any(
        type(value) is not TurnTruthRequirement
        or value.turn_id != turn_id
        for turn_id, value in normalized.items()
    ):
        raise ValueError(
            "mechanical truth must cover every turn exactly once"
        )
    return normalized


def _validate_truth_spec_binding(
    *,
    manifest_path: str | Path,
    truth_spec_path: str | Path,
) -> None:
    manifest_file = Path(manifest_path)
    truth_file = Path(truth_spec_path)
    try:
        manifest = json.loads(
            manifest_file.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise ValueError(
            "truth spec must be manifest-bound"
        ) from exc
    declared_name = manifest.get("mechanical_truth_file")
    declared_sha256 = manifest.get("mechanical_truth_sha256")
    declared_path = (
        manifest_file.parent / declared_name
        if isinstance(declared_name, str)
        else None
    )
    try:
        actual_sha256 = sha256(
            truth_file.read_bytes()
        ).hexdigest()
    except OSError as exc:
        raise ValueError(
            "truth spec must be manifest-bound"
        ) from exc
    if (
        declared_path is None
        or declared_path.resolve() != truth_file.resolve()
        or declared_sha256 != actual_sha256
    ):
        raise ValueError("truth spec must be manifest-bound")


def _summarize_capture(
    *,
    trajectories: tuple[ContinuousTrajectory, ...],
    rows: tuple[ContinuousCaptureRow, ...],
    provider_call_count: int,
    reused_provider_call_count: int = 0,
    model: str,
    prompt_version: str,
) -> ContinuousGateReport:
    if not 0 <= reused_provider_call_count <= provider_call_count:
        raise ValueError("invalid reused provider call count")
    evaluations = tuple(row.evaluation for row in rows)
    passing_turns = {
        (row.trajectory_id, row.turn_id)
        for row in evaluations
        if row.passed
    }
    passed_trajectories = sum(
        all(
            (trajectory.trajectory_id, turn.turn_id)
            in passing_turns
            for turn in trajectory.turns
        )
        for trajectory in trajectories
    )
    failure_counts = Counter(
        row.failure_layer
        for row in evaluations
        if row.failure_layer is not None
    )
    counters = _zero_tolerance_counters(evaluations)
    rows_payload = [
        row.model_dump(mode="json") for row in rows
    ]
    passed_turn_count = sum(row.passed for row in evaluations)
    return ContinuousGateReport(
        model=model,
        prompt_version=prompt_version,
        trajectory_count=len(trajectories),
        turn_count=len(rows),
        provider_call_count=provider_call_count,
        reused_provider_call_count=reused_provider_call_count,
        new_provider_call_count=(
            provider_call_count - reused_provider_call_count
        ),
        skipped_dependency_turn_count=sum(
            not row.provider_call_attempted for row in rows
        ),
        passed_turn_count=passed_turn_count,
        passed_trajectory_count=passed_trajectories,
        complete_trajectory_rate=(
            passed_trajectories / len(trajectories)
        ),
        failure_counts={
            layer: failure_counts.get(layer, 0)
            for layer in _LAYER_ORDER
        },
        prompt_tokens=sum(row.prompt_tokens for row in rows),
        completion_tokens=sum(
            row.completion_tokens for row in rows
        ),
        total_tokens=sum(row.total_tokens for row in rows),
        results_sha256=_hash_json(rows_payload),
        passed=blind_qualification_passed(
            turn_count=len(rows),
            passed_turn_count=passed_turn_count,
            trajectory_count=len(trajectories),
            passed_trajectory_count=passed_trajectories,
            zero_tolerance_counters=counters,
        ),
        **counters,
    )


def blind_qualification_passed(
    *,
    turn_count: int,
    passed_turn_count: int,
    trajectory_count: int,
    passed_trajectory_count: int,
    zero_tolerance_counters: Mapping[str, int],
) -> bool:
    return (
        turn_count == 100
        and trajectory_count == 20
        and passed_turn_count >= 90
        and passed_trajectory_count >= 18
        and not any(zero_tolerance_counters.values())
    )


def _zero_tolerance_counters(
    evaluations: Sequence[ContinuousTurnEvaluation],
) -> dict[str, int]:
    return {
        field: sum(getattr(row, field) for row in evaluations)
        for field in (
            "wrong_product_or_image_binding_count",
            "unauthorized_state_transition_count",
            "hard_condition_override_count",
            "unsafe_downgrade_count",
            "cross_session_or_subject_leak_count",
            "internal_public_language_count",
            "stale_focus_hijack_count",
        )
    }


def _write_artifact(
    *,
    output_path: str | Path,
    summary: BaseModel,
    rows: Sequence[ContinuousCaptureRow],
) -> None:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.tmp"
    )
    temporary.write_bytes(
        _canonical_json({
            "summary": summary.model_dump(mode="json"),
            "results": [
                row.model_dump(mode="json") for row in rows
            ],
        })
        + b"\n"
    )
    temporary.replace(destination)


def _load_resume_prefix(
    *,
    trajectories: tuple[ContinuousTrajectory, ...],
    capture_path: str | Path,
    model: str,
    prompt_version: str,
) -> tuple[dict[str, object], ...]:
    source = json.loads(
        Path(capture_path).read_text(encoding="utf-8")
    )
    summary = source.get("summary")
    source_rows = source.get("results")
    if (
        not isinstance(summary, dict)
        or not isinstance(source_rows, list)
        or not source_rows
        or any(not isinstance(row, dict) for row in source_rows)
    ):
        raise ValueError("resume capture must contain summary and results")
    if (
        summary.get("model") != model
        or summary.get("prompt_version") != prompt_version
    ):
        raise ValueError("resume capture model or prompt version drifted")
    expected_order = [
        (trajectory.trajectory_id, turn.turn_id)
        for trajectory in trajectories
        for turn in trajectory.turns
    ]
    captured_order = [
        (row.get("trajectory_id"), row.get("turn_id"))
        for row in source_rows
    ]
    if captured_order != expected_order[:len(captured_order)]:
        raise ValueError(
            "resume capture must be one global contiguous prefix"
        )
    return tuple(source_rows)


def _validate_resume_row(
    *,
    source_row: dict[str, object],
    trajectory: ContinuousTrajectory,
    turn: ContinuousTurnExpectation,
    version: int,
    context: SemanticContext,
) -> None:
    input_payload = {
        "trajectory_id": trajectory.trajectory_id,
        "turn_id": turn.turn_id,
        "message": turn.message,
        "starting_version": version,
        "image_fixture_ids": list(turn.image_fixture_ids),
    }
    if (
        source_row.get("message") != turn.message
        or source_row.get("starting_version") != version
        or source_row.get("input_sha256") != _hash_json(input_payload)
        or source_row.get("context_sha256")
        != _hash_json(context.model_dump(mode="json"))
    ):
        raise ValueError("resume capture input or context drifted")


def run_real_continuous_gate(
    *,
    trajectories: Sequence[ContinuousTrajectory],
    adapter,
    copywriter,
    runtime_factory: RuntimeFactory,
    state_root: str | Path,
    output_path: str | Path,
    stop_on_first_failure: bool = False,
    resume_capture_path: str | Path | None = None,
    truth_by_turn: Mapping[
        str,
        TurnTruthRequirement,
    ] | None = None,
    outcome_scoring: bool = False,
) -> ContinuousGateReport:
    normalized = _validate_trajectories(trajectories)
    normalized_truth = _validate_truth_by_turn(
        trajectories=normalized,
        truth_by_turn=truth_by_turn,
    )
    if type(stop_on_first_failure) is not bool:
        raise TypeError("stop_on_first_failure must be a bool")
    if type(outcome_scoring) is not bool:
        raise TypeError("outcome_scoring must be a bool")
    if not callable(getattr(adapter, "propose_with_result", None)):
        raise TypeError("adapter must expose propose_with_result")
    del copywriter
    state_directory = Path(state_root)
    if state_directory.exists():
        raise ValueError("state_root must not already exist")
    model = str(getattr(adapter, "model", "unknown"))
    prompt_version = str(
        getattr(adapter, "prompt_version", "unknown")
    )
    resume_rows = (
        _load_resume_prefix(
            trajectories=normalized,
            capture_path=resume_capture_path,
            model=model,
            prompt_version=prompt_version,
        )
        if resume_capture_path is not None
        else ()
    )
    rows: list[ContinuousCaptureRow] = []
    provider_call_count = 0
    reused_provider_call_count = 0
    resume_row_index = 0
    for trajectory in normalized:
        runtime = runtime_factory(
            trajectory,
            state_directory / trajectory.trajectory_id,
        )
        snapshot = None
        version = 0
        translation_dependency_broken = False
        for ordinal, turn in enumerate(
            trajectory.turns,
            start=1,
        ):
            context = resolve_semantic_context(
                conversation_version=version,
                snapshot=snapshot,
            )
            source_row = (
                resume_rows[resume_row_index]
                if resume_row_index < len(resume_rows)
                else None
            )
            if source_row is not None:
                resume_row_index += 1
                _validate_resume_row(
                    source_row=source_row,
                    trajectory=trajectory,
                    turn=turn,
                    version=version,
                    context=context,
                )
            source_call_attempted = (
                source_row.get("provider_call_attempted", True)
                if source_row is not None
                else True
            )
            if type(source_call_attempted) is not bool:
                raise ValueError(
                    "resume capture provider call flag is invalid"
                )
            meaning = None
            trace = None
            usage = None
            raw_output = None
            trace_id = None
            provider_call_attempted = True
            fatal_error: BaseException | None = None
            trajectory_broken = False
            translation_broken = False
            if translation_dependency_broken:
                if source_row is not None and source_call_attempted:
                    raise ValueError(
                        "resume capture attempted a dependency-skipped turn"
                    )
                provider_call_attempted = False
                evaluation = _failed_translation_evaluation(
                    trajectory_id=trajectory.trajectory_id,
                    turn=turn,
                )
            elif source_row is not None:
                if not source_call_attempted:
                    raise ValueError(
                        "resume capture skipped an independent turn"
                    )
                provider_call_count += 1
                meaning = _meaning_from_captured_output(source_row)
                if meaning is None:
                    evaluation = _failed_translation_evaluation(
                        trajectory_id=trajectory.trajectory_id,
                        turn=turn,
                    )
                    trajectory_broken = True
                    translation_broken = True
                raw_output = source_row.get("provider_raw_output")
                trace_id = source_row.get("provider_trace_id")
                usage = source_row
                reused_provider_call_count += 1
            else:
                provider_call_count += 1
                try:
                    call = adapter.propose_with_result(
                        turn.message,
                        context,
                    )
                    meaning = call.meaning
                    usage = call.usage
                    raw_output = call.raw_content
                    trace_id = call.trace_id
                except BaseException as error:
                    raw_output = (
                        getattr(error, "raw_content", None)
                        or raw_output
                    )
                    trace_id = (
                        getattr(error, "trace_id", None)
                        or trace_id
                    )
                    usage = getattr(error, "usage", None) or usage
                    evaluation = _failed_translation_evaluation(
                        trajectory_id=trajectory.trajectory_id,
                        turn=turn,
                    )
                    if (
                        isinstance(error, SemanticProviderFailure)
                        and error.code
                        in _SCORABLE_TRANSLATION_FAILURES
                    ):
                        trajectory_broken = True
                        translation_broken = True
                    else:
                        fatal_error = error
            if meaning is not None:
                try:
                    trace = _execute_turn(
                        trajectory=trajectory,
                        turn=turn,
                        meaning=meaning,
                        runtime=runtime,
                        starting_version=version,
                    )
                    evaluation = evaluate_continuous_turn(
                        trajectory_id=trajectory.trajectory_id,
                        turn=turn,
                        meaning=meaning,
                        trace=trace,
                        truth=normalized_truth.get(turn.turn_id),
                        outcome_scoring=outcome_scoring,
                    )
                    snapshot = trace.final_snapshot
                    version = trace.terminal_version
                except KeyboardInterrupt as error:
                    evaluation = _failed_runtime_evaluation(
                        trajectory_id=trajectory.trajectory_id,
                        turn=turn,
                        meaning=meaning,
                        failure_layer=(
                            _runtime_failure_layer(runtime)
                        ),
                    )
                    fatal_error = error
                except Exception:
                    evaluation = _failed_runtime_evaluation(
                        trajectory_id=trajectory.trajectory_id,
                        turn=turn,
                        meaning=meaning,
                        failure_layer=(
                            _runtime_failure_layer(runtime)
                        ),
                    )
                    trajectory_broken = True
            if (
                source_row is not None
                and any(
                    _zero_tolerance_counters((evaluation,)).values()
                )
            ):
                raise ValueError(
                    "resume capture prefix contains a serious failure"
                )
            rows.append(_capture_row(
                trajectory=trajectory,
                turn=turn,
                turn_ordinal=ordinal,
                starting_version=version if trace is None else (
                    trace.starting_version
                ),
                context=context,
                provider_raw_output=raw_output,
                provider_trace_id=trace_id,
                meaning=meaning,
                trace=trace,
                evaluation=evaluation,
                usage=usage,
                provider_call_attempted=provider_call_attempted,
            ))
            partial_rows = tuple(rows)
            partial_report = _summarize_capture(
                trajectories=normalized,
                rows=partial_rows,
                provider_call_count=provider_call_count,
                reused_provider_call_count=(
                    reused_provider_call_count
                ),
                model=model,
                prompt_version=prompt_version,
            )
            _write_artifact(
                output_path=output_path,
                summary=partial_report,
                rows=partial_rows,
            )
            print(
                "progress "
                f"trajectory_id={trajectory.trajectory_id} "
                f"turn_id={turn.turn_id} "
                f"attempted_calls={provider_call_count} "
                "new_calls="
                f"{provider_call_count - reused_provider_call_count} "
                f"{'skipped_dependency=true ' if not provider_call_attempted else ''}"
                f"total_tokens={sum(row.total_tokens for row in partial_rows)}",
                flush=True,
            )
            if fatal_error is not None:
                raise fatal_error
            if any(
                _zero_tolerance_counters((evaluation,)).values()
            ):
                return partial_report
            if stop_on_first_failure and not evaluation.passed:
                return partial_report
            if trajectory_broken:
                if translation_broken:
                    translation_dependency_broken = True
                else:
                    break
    frozen_rows = tuple(rows)
    report = _summarize_capture(
        trajectories=normalized,
        rows=frozen_rows,
        provider_call_count=provider_call_count,
        reused_provider_call_count=reused_provider_call_count,
        model=model,
        prompt_version=prompt_version,
    )
    _write_artifact(
        output_path=output_path,
        summary=report,
        rows=frozen_rows,
    )
    return report


def replay_captured_continuous_gate(
    *,
    trajectories: Sequence[ContinuousTrajectory],
    capture_path: str | Path,
    runtime_factory: RuntimeFactory,
    state_root: str | Path,
    output_path: str | Path,
    allow_partial: bool = False,
    truth_by_turn: Mapping[
        str,
        TurnTruthRequirement,
    ] | None = None,
    outcome_scoring: bool = False,
) -> ContinuousReplayReport:
    normalized = _validate_trajectories(trajectories)
    normalized_truth = _validate_truth_by_turn(
        trajectories=normalized,
        truth_by_turn=truth_by_turn,
    )
    if type(outcome_scoring) is not bool:
        raise TypeError("outcome_scoring must be a bool")
    source = json.loads(
        Path(capture_path).read_text(encoding="utf-8")
    )
    source_rows = source.get("results")
    if not isinstance(source_rows, list):
        raise ValueError("capture must contain results")
    if any(not isinstance(row, dict) for row in source_rows):
        raise ValueError("capture results must contain objects")
    by_key = {
        (row.get("trajectory_id"), row.get("turn_id")): row
        for row in source_rows
    }
    if len(by_key) != len(source_rows):
        raise ValueError("duplicate capture turn identities")
    expected_keys = {
        (trajectory.trajectory_id, turn.turn_id)
        for trajectory in normalized
        for turn in trajectory.turns
    }
    captured_keys = set(by_key)
    if captured_keys.difference(expected_keys):
        raise ValueError(
            "capture turn identities do not match trajectories"
        )
    if not allow_partial and captured_keys != expected_keys:
        raise ValueError(
            "capture turn identities do not match trajectories"
        )
    captured_turns: dict[
        str,
        tuple[ContinuousTurnExpectation, ...],
    ] = {}
    for trajectory in normalized:
        prefix: list[ContinuousTurnExpectation] = []
        missing_seen = False
        for turn in trajectory.turns:
            present = (
                trajectory.trajectory_id,
                turn.turn_id,
            ) in captured_keys
            if present and missing_seen:
                raise ValueError(
                    "capture turns must form a contiguous prefix"
                )
            if present:
                prefix.append(turn)
            else:
                missing_seen = True
        captured_turns[trajectory.trajectory_id] = tuple(prefix)
    state_directory = Path(state_root)
    if state_directory.exists():
        raise ValueError("state_root must not already exist")
    rows: list[ContinuousCaptureRow] = []
    for trajectory in normalized:
        replay_turns = captured_turns[trajectory.trajectory_id]
        if not replay_turns:
            continue
        runtime = runtime_factory(
            trajectory,
            state_directory / trajectory.trajectory_id,
        )
        snapshot = None
        version = 0
        translation_dependency_broken = False
        for ordinal, turn in enumerate(
            replay_turns,
            start=1,
        ):
            source_row = by_key[
                (trajectory.trajectory_id, turn.turn_id)
            ]
            provider_call_attempted = source_row.get(
                "provider_call_attempted",
                True,
            )
            if type(provider_call_attempted) is not bool:
                raise ValueError(
                    "capture provider call flag is invalid"
                )
            meaning = _meaning_from_captured_output(source_row)
            source_starting_version = source_row.get(
                "starting_version"
            )
            if (
                type(source_starting_version) is not int
                or source_starting_version < 0
                or source_row.get("message") != turn.message
                or source_row.get("input_sha256")
                != _hash_json({
                    "trajectory_id": trajectory.trajectory_id,
                    "turn_id": turn.turn_id,
                    "message": turn.message,
                    "starting_version": source_starting_version,
                    "image_fixture_ids": list(
                        turn.image_fixture_ids
                    ),
                })
            ):
                raise ValueError("capture input identity drifted")
            context = resolve_semantic_context(
                conversation_version=version,
                snapshot=snapshot,
            )
            if translation_dependency_broken:
                if provider_call_attempted or meaning is not None:
                    raise ValueError(
                        "capture attempted a dependency-skipped turn"
                    )
                evaluation = _failed_translation_evaluation(
                    trajectory_id=trajectory.trajectory_id,
                    turn=turn,
                )
                trace = None
            elif meaning is None:
                if not provider_call_attempted:
                    raise ValueError(
                        "capture skipped an independent turn"
                    )
                evaluation = _failed_translation_evaluation(
                    trajectory_id=trajectory.trajectory_id,
                    turn=turn,
                )
                trace = None
                translation_dependency_broken = True
            else:
                if not provider_call_attempted:
                    raise ValueError(
                        "capture skipped a turn with provider output"
                    )
                try:
                    trace = _execute_turn(
                        trajectory=trajectory,
                        turn=turn,
                        meaning=meaning,
                        runtime=runtime,
                        starting_version=version,
                    )
                except Exception:
                    evaluation = _failed_runtime_evaluation(
                        trajectory_id=trajectory.trajectory_id,
                        turn=turn,
                        meaning=meaning,
                        failure_layer=_runtime_failure_layer(
                            runtime
                        ),
                    )
                    trace = None
                else:
                    evaluation = evaluate_continuous_turn(
                        trajectory_id=trajectory.trajectory_id,
                        turn=turn,
                        meaning=meaning,
                        trace=trace,
                        truth=normalized_truth.get(turn.turn_id),
                        outcome_scoring=outcome_scoring,
                    )
                    snapshot = trace.final_snapshot
                    version = trace.terminal_version
            rows.append(_capture_row(
                trajectory=trajectory,
                turn=turn,
                turn_ordinal=ordinal,
                starting_version=(
                    version if trace is None else trace.starting_version
                ),
                context=context,
                provider_raw_output=source_row.get(
                    "provider_raw_output"
                ),
                provider_trace_id=source_row.get(
                    "provider_trace_id"
                ),
                meaning=meaning,
                trace=trace,
                evaluation=evaluation,
                usage=None,
                provider_call_attempted=provider_call_attempted,
            ))
            if trace is None and not translation_dependency_broken:
                break
    frozen_rows = tuple(rows)
    evaluations = tuple(row.evaluation for row in frozen_rows)
    passing_turns = {
        (row.trajectory_id, row.turn_id)
        for row in evaluations
        if row.passed
    }
    passed_trajectory_count = sum(
        all(
            (trajectory.trajectory_id, turn.turn_id)
            in passing_turns
            for turn in trajectory.turns
        )
        for trajectory in normalized
    )
    counters = _zero_tolerance_counters(evaluations)
    failure_counts = Counter(
        row.failure_layer
        for row in evaluations
        if row.failure_layer is not None
    )
    replay_passed = (
        all(row.passed for row in evaluations)
        and not any(counters.values())
    )
    capture_complete = captured_keys == expected_keys
    report = ContinuousReplayReport(
        trajectory_count=len(normalized),
        expected_turn_count=len(expected_keys),
        captured_turn_count=len(captured_keys),
        replayed_turn_count=len(frozen_rows),
        capture_complete=capture_complete,
        replay_passed=replay_passed,
        passed_turn_count=sum(row.passed for row in evaluations),
        passed_trajectory_count=passed_trajectory_count,
        failure_counts={
            layer: failure_counts.get(layer, 0)
            for layer in _LAYER_ORDER
        },
        results_sha256=_hash_json([
            row.model_dump(mode="json") for row in frozen_rows
        ]),
        passed=(
            capture_complete
            and len(frozen_rows) == len(expected_keys)
            and replay_passed
            and passed_trajectory_count == len(normalized)
        ),
        **counters,
    )
    _write_artifact(
        output_path=output_path,
        summary=report,
        rows=frozen_rows,
    )
    return report


def _build_adapter(
    *,
    api_key: str,
    model: str,
    concept_ids: tuple[str, ...],
    turn_count: int,
):
    return DeepSeekTurnMeaningAdapter(
        api_key=api_key,
        model=model,
        timeout_seconds=20.0,
        max_tokens=1024,
        concept_catalog=concept_ids,
        daily_budget_cny=Decimal("3.00"),
        daily_call_cap=turn_count,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run or replay the five-turn continuous conversation gate."
        )
    )
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--truth-spec", type=Path)
    parser.add_argument("--truth-correction", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    run_mode = parser.add_mutually_exclusive_group()
    run_mode.add_argument("--replay", type=Path)
    run_mode.add_argument("--resume", type=Path)
    parser.add_argument(
        "--allow-partial-replay",
        action="store_true",
    )
    parser.add_argument(
        "--outcome-scoring",
        action="store_true",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
    )
    parser.add_argument("--key-path", default=DEFAULT_KEY_PATH)
    parser.add_argument("--model", default=DEEPSEEK_V4_PRO_MODEL)
    parser.add_argument(
        "--disable-copywriter",
        action="store_true",
    )
    args = parser.parse_args(argv)
    if args.output.exists():
        print(json.dumps({
            "status": "output_exists",
            "path": str(args.output),
        }))
        return 4
    trajectories = load_frozen_trajectories(
        args.cases,
        manifest_path=args.manifest,
    )
    turn_count = sum(
        len(trajectory.turns)
        for trajectory in trajectories
    )
    if len(trajectories) != 20 or turn_count != 100:
        print(json.dumps({
            "status": "invalid_gate_shape",
            "trajectory_count": len(trajectories),
            "turn_count": turn_count,
        }))
        return 6
    truth_by_turn: dict[str, TurnTruthRequirement] = {}
    if (
        args.truth_correction is not None
        and args.truth_spec is None
    ):
        print(json.dumps({
            "status": "truth_correction_requires_truth_spec",
        }))
        return 8
    if args.truth_spec is not None:
        try:
            _validate_truth_spec_binding(
                manifest_path=args.manifest,
                truth_spec_path=args.truth_spec,
            )
            truth_spec = MechanicalTruthSpec.model_validate_json(
                args.truth_spec.read_text(encoding="utf-8"),
                strict=True,
            )
            if args.truth_correction is not None:
                truth_correction = (
                    TruthCorrectionOverlay.model_validate_json(
                        args.truth_correction.read_text(
                            encoding="utf-8"
                        ),
                        strict=True,
                    )
                )
                trajectories = apply_truth_correction_overlay(
                    trajectories=trajectories,
                    overlay=truth_correction,
                    fixture_path=args.cases,
                    manifest_path=args.manifest,
                    mechanical_truth_path=args.truth_spec,
                )
            canonical_root = (
                args.repo_root / "data" / "canonical"
            )
            truth_report = audit_mechanical_truth(
                trajectories=trajectories,
                canonical_reader=CanonicalProductReader.from_files(
                    manifest_path=(
                        canonical_root
                        / "core_products_v1_manifest.json"
                    ),
                    products_path=(
                        canonical_root / "core_products_v1.jsonl"
                    ),
                ),
                spec=truth_spec,
                runtime_image_fixtures=runtime_image_fixtures(),
                repo_root=args.repo_root,
            )
        except (OSError, ValueError) as error:
            print(json.dumps({
                "status": "mechanical_truth_failed",
                "error": str(error),
            }))
            return 8
        truth_by_turn = {
            item.turn_id: item for item in truth_spec.turns
        }
        print(json.dumps({
            "status": "mechanical_truth_passed",
            "truth_correction_count": (
                len(truth_correction.corrections)
                if args.truth_correction is not None
                else 0
            ),
            **truth_report.model_dump(mode="json"),
        }))
    runtime_factory = lambda trajectory, state_root: (
        build_local_continuous_runtime(
            trajectory,
            state_root,
            repo_root=args.repo_root,
        )
    )
    with TemporaryDirectory(
        prefix="xiaoro-continuous-conversation-"
    ) as temporary:
        state_root = Path(temporary) / "state"
        if args.replay is not None:
            report = replay_captured_continuous_gate(
                trajectories=trajectories,
                capture_path=args.replay,
                runtime_factory=runtime_factory,
                state_root=state_root,
                output_path=args.output,
                allow_partial=args.allow_partial_replay,
                truth_by_turn=truth_by_turn or None,
                outcome_scoring=args.outcome_scoring,
            )
            print(report.model_dump_json())
            return 0 if report.passed else 3
        if not args.disable_copywriter:
            print(json.dumps({
                "status": "copywriter_must_be_disabled",
            }))
            return 7
        try:
            api_key = read_private_api_key(args.key_path)
        except KeyPrecheckError as error:
            print(json.dumps({
                "status": "key_precheck_failed",
                "code": error.code.value,
            }))
            return 5
        assets = build_selection_concept_assets(args.repo_root)
        concept_ids = tuple(sorted({
            item.concept_id for item in assets.projections
        }))
        ConceptPreferenceCatalog.from_projections(
            assets.projections
        )
        adapter = _build_adapter(
            api_key=api_key,
            model=args.model,
            concept_ids=concept_ids,
            turn_count=turn_count,
        )
        try:
            report = run_real_continuous_gate(
                trajectories=trajectories,
                adapter=adapter,
                copywriter=None,
                runtime_factory=runtime_factory,
                state_root=state_root,
                output_path=args.output,
                resume_capture_path=args.resume,
                truth_by_turn=truth_by_turn or None,
                outcome_scoring=args.outcome_scoring,
            )
        finally:
            close = getattr(adapter, "close", None)
            if callable(close):
                close()
    print(report.model_dump_json())
    return 0 if report.passed else 3


__all__ = [
    "ContinuousCaptureRow",
    "ContinuousGateReport",
    "ContinuousLayerEvidence",
    "ContinuousReplayReport",
    "ContinuousTurnEvaluation",
    "blind_qualification_passed",
    "evaluate_continuous_turn",
    "replay_captured_continuous_gate",
    "run_real_continuous_gate",
]


if __name__ == "__main__":
    raise SystemExit(main())
