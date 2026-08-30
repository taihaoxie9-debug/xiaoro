from __future__ import annotations

from enum import Enum
from hashlib import sha256
from pathlib import Path
from collections.abc import Callable, Sequence
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_serializer,
    model_validator,
)

from app.guide.feedback.contracts import ConversationSnapshot
from app.guide.intent.responsibility_matrix import ProcessorKind
from app.guide.intent.unified_turn_router import (
    ContinuityKind,
    FocusSource,
)
from app.guide.presentation.copywriter_contracts import PresentationMode
from app.guide.retrieval.product_name_resolver import (
    ResolvedProductBinding,
)
from app.guide.understanding.turn_meaning_contracts import (
    TurnContinuityHint,
    TurnMeaning,
    TurnOperationHint,
    TurnSubjectScopeHint,
    TurnTopicHint,
)


class FailureLayer(str, Enum):
    MODEL_TRANSLATION = "model_translation"
    SEMANTIC_ADMISSION = "semantic_admission"
    IDENTITY_BINDING = "identity_binding"
    ROUTE_SELECTION = "route_selection"
    STATE_TRANSITION = "state_transition"
    DECISION_EXECUTION = "decision_execution"
    PRESENTATION = "presentation"


class LayerEvidence(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )

    model_translation: bool
    semantic_admission: bool
    identity_binding: bool
    route_selection: bool
    state_transition: bool
    decision_execution: bool
    presentation: bool


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )


class SemanticExpectation(_StrictFrozen):
    operation_hints: tuple[TurnOperationHint, ...] = Field(
        min_length=1
    )
    topic_hints: tuple[TurnTopicHint | None, ...] = Field(
        min_length=1
    )
    continuity_hints: tuple[TurnContinuityHint, ...] = Field(
        min_length=1
    )
    subject_scope_hints: tuple[TurnSubjectScopeHint, ...] = Field(
        min_length=1
    )

    @field_validator(
        "operation_hints",
        "topic_hints",
        "continuity_hints",
        "subject_scope_hints",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_unique_values(self):
        for values in (
            self.operation_hints,
            self.topic_hints,
            self.continuity_hints,
            self.subject_scope_hints,
        ):
            if len(values) != len(set(values)):
                raise ValueError(
                    "semantic expectation values must be unique"
                )
        return self


class RouteExpectation(_StrictFrozen):
    processor: ProcessorKind
    continuity: ContinuityKind
    focus_source: FocusSource


def legacy_replay_payload(payload: object) -> object:
    if isinstance(payload, dict):
        normalized = {
            key: legacy_replay_payload(value)
            for key, value in payload.items()
        }
        if normalized.get("similarity_anchor_product_id") is None:
            normalized.pop("similarity_anchor_product_id", None)
        return normalized
    if isinstance(payload, list):
        return [legacy_replay_payload(item) for item in payload]
    return payload


class ReplayCase(_StrictFrozen):
    schema_version: Literal[
        "guide-unified-router-replay-case-v1"
    ] = "guide-unified-router-replay-case-v1"
    case_id: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[a-z0-9][a-z0-9_-]+$",
    )
    message: str = Field(min_length=1, max_length=4000)
    starting_snapshot: ConversationSnapshot | None
    raw_turn_meaning: TurnMeaning
    acceptable_semantic: SemanticExpectation
    expected_bindings: tuple[ResolvedProductBinding, ...] = ()
    expected_route: RouteExpectation
    expected_final_snapshot: dict[str, JsonValue]
    expected_task_plan: dict[str, JsonValue]
    expected_card_ids: tuple[int, ...] = Field(
        default_factory=tuple,
        max_length=3,
    )
    expected_safety: bool
    expected_clarification: bool
    expected_presentation_mode: PresentationMode | None

    @field_validator(
        "expected_bindings",
        "expected_card_ids",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_serializer(mode="wrap")
    def serialize_legacy_replay_payload(self, handler):
        return legacy_replay_payload(handler(self))

    @model_validator(mode="after")
    def validate_expected_output(self):
        if (
            self.expected_safety
            and self.expected_clarification
        ):
            raise ValueError(
                "safety and clarification expectations are exclusive"
            )
        if len(self.expected_card_ids) != len(
            set(self.expected_card_ids)
        ):
            raise ValueError("expected card IDs must be unique")
        return self


class ReplayManifest(_StrictFrozen):
    schema_version: Literal[
        "guide-unified-router-replay-manifest-v1"
    ] = "guide-unified-router-replay-manifest-v1"
    case_count: int = Field(ge=1)
    cases_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReplayTrace(_StrictFrozen):
    semantic_admission_passed: bool
    bindings: tuple[ResolvedProductBinding, ...] = ()
    route: RouteExpectation
    final_snapshot: dict[str, JsonValue]
    task_plan: dict[str, JsonValue]
    card_ids: tuple[int, ...] = Field(
        default_factory=tuple,
        max_length=3,
    )
    safety: bool
    clarification: bool
    presentation_mode: PresentationMode | None
    event_names: tuple[str, ...] = Field(min_length=1)
    error_code: str | None
    hard_condition_override: bool
    cross_session_leak: bool

    @field_validator(
        "bindings",
        "card_ids",
        "event_names",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class ReplayResult(_StrictFrozen):
    case_id: str
    layer_evidence: LayerEvidence
    failure_layer: FailureLayer | None
    wrong_product_selection_count: int = Field(ge=0)
    unauthorized_state_transition_count: int = Field(ge=0)
    hard_condition_override_count: int = Field(ge=0)
    unsafe_downgrade_count: int = Field(ge=0)
    cross_session_leak_count: int = Field(ge=0)
    passed: bool


class ReplaySummary(_StrictFrozen):
    schema_version: Literal[
        "guide-unified-router-replay-summary-v1"
    ] = "guide-unified-router-replay-summary-v1"
    case_count: int = Field(ge=0)
    passed_count: int = Field(ge=0)
    end_to_end_rate: float = Field(ge=0.0, le=1.0)
    wrong_product_selection_count: int = Field(ge=0)
    unauthorized_state_transition_count: int = Field(ge=0)
    hard_condition_override_count: int = Field(ge=0)
    unsafe_downgrade_count: int = Field(ge=0)
    cross_session_leak_count: int = Field(ge=0)
    failure_counts: dict[FailureLayer, int]
    passed: bool


def build_replay_manifest(
    cases_bytes: bytes,
    *,
    cases: tuple[ReplayCase, ...],
) -> ReplayManifest:
    if not isinstance(cases_bytes, bytes):
        raise TypeError("cases_bytes must be bytes")
    if not cases or any(type(item) is not ReplayCase for item in cases):
        raise TypeError(
            "cases must be a nonempty tuple of exact ReplayCase values"
        )
    case_ids = tuple(item.case_id for item in cases)
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("replay case IDs must be unique")
    return ReplayManifest(
        case_count=len(cases),
        cases_sha256=sha256(cases_bytes).hexdigest(),
        case_ids_sha256=sha256(
            ("\n".join(case_ids) + "\n").encode("utf-8")
        ).hexdigest(),
    )


def load_replay_cases(
    cases_path: str | Path,
    *,
    manifest_path: str | Path,
) -> tuple[ReplayCase, ...]:
    raw = Path(cases_path).read_bytes()
    manifest = ReplayManifest.model_validate_json(
        Path(manifest_path).read_text(encoding="utf-8"),
        strict=True,
    )
    if sha256(raw).hexdigest() != manifest.cases_sha256:
        raise ValueError("replay cases SHA-256 does not match manifest")
    cases = tuple(
        ReplayCase.model_validate_json(line, strict=True)
        for line in raw.splitlines()
        if line.strip()
    )
    actual = build_replay_manifest(raw, cases=cases)
    if actual.case_count != manifest.case_count:
        raise ValueError("replay case count does not match manifest")
    if actual.case_ids_sha256 != manifest.case_ids_sha256:
        raise ValueError(
            "replay case ID SHA-256 does not match manifest"
        )
    return cases


_SINGLE_PRODUCT_PRESENTATION_FAMILY = frozenset({
    "followup",
    "product_knowledge",
    "single_product",
})


def _presentation_matches(
    *,
    case: ReplayCase,
    trace: ReplayTrace,
) -> bool:
    if trace.presentation_mode == case.expected_presentation_mode:
        return True
    return (
        case.expected_route.processor == "product_knowledge"
        and case.expected_presentation_mode
        in _SINGLE_PRODUCT_PRESENTATION_FAMILY
        and trace.presentation_mode
        in _SINGLE_PRODUCT_PRESENTATION_FAMILY
    )


def evaluate_replay_trace(
    *,
    case: ReplayCase,
    trace: ReplayTrace,
) -> ReplayResult:
    if type(case) is not ReplayCase:
        raise TypeError("case must be an exact ReplayCase")
    if type(trace) is not ReplayTrace:
        raise TypeError("trace must be an exact ReplayTrace")
    meaning = case.raw_turn_meaning
    semantic = case.acceptable_semantic
    translation_passed = (
        meaning.operation_hint in semantic.operation_hints
        and meaning.topic_hint in semantic.topic_hints
        and meaning.continuity_hint in semantic.continuity_hints
        and meaning.subject_scope_hint
        in semantic.subject_scope_hints
    )
    identity_passed = _binding_keys(
        trace.bindings
    ) == _binding_keys(case.expected_bindings)
    route_passed = trace.route == case.expected_route
    state_passed = (
        _contains_expected(
            trace.final_snapshot,
            case.expected_final_snapshot,
        )
        and not trace.cross_session_leak
    )
    task_passed = _contains_expected(
        trace.task_plan,
        case.expected_task_plan,
    )
    cards_passed = trace.card_ids == case.expected_card_ids
    safety_passed = trace.safety == case.expected_safety
    clarification_passed = (
        trace.clarification == case.expected_clarification
    )
    decision_passed = (
        task_passed
        and cards_passed
        and safety_passed
        and clarification_passed
        and not trace.hard_condition_override
    )
    presentation_passed = (
        _presentation_matches(case=case, trace=trace)
        and trace.error_code is None
        and trace.event_names[-1] == "end"
    )
    evidence = LayerEvidence(
        model_translation=translation_passed,
        semantic_admission=trace.semantic_admission_passed,
        identity_binding=identity_passed,
        route_selection=route_passed,
        state_transition=state_passed,
        decision_execution=decision_passed,
        presentation=presentation_passed,
    )
    failure_layer = classify_earliest_failure(evidence)
    wrong_product_count = int(bool(
        set(trace.card_ids) - set(case.expected_card_ids)
    ))
    unauthorized_state_count = int(
        not _is_nonmutating_fail_closed_clarification(
            case=case,
            trace=trace,
        )
        and _contradicts_expected(
            trace.final_snapshot,
            case.expected_final_snapshot,
        )
    )
    hard_override_count = int(trace.hard_condition_override)
    unsafe_count = int(
        case.expected_safety and not trace.safety
    )
    cross_leak_count = int(trace.cross_session_leak)
    zero_tolerance_passed = not any(
        (
            wrong_product_count,
            unauthorized_state_count,
            hard_override_count,
            unsafe_count,
            cross_leak_count,
        )
    )
    return ReplayResult(
        case_id=case.case_id,
        layer_evidence=evidence,
        failure_layer=failure_layer,
        wrong_product_selection_count=wrong_product_count,
        unauthorized_state_transition_count=(
            unauthorized_state_count
        ),
        hard_condition_override_count=hard_override_count,
        unsafe_downgrade_count=unsafe_count,
        cross_session_leak_count=cross_leak_count,
        passed=failure_layer is None and zero_tolerance_passed,
    )


def summarize_replay(
    results: tuple[ReplayResult, ...],
) -> ReplaySummary:
    if any(type(item) is not ReplayResult for item in results):
        raise TypeError("results must contain exact ReplayResult values")
    case_ids = tuple(item.case_id for item in results)
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("replay result case IDs must be unique")
    passed_count = sum(item.passed for item in results)
    wrong_products = sum(
        item.wrong_product_selection_count for item in results
    )
    unauthorized = sum(
        item.unauthorized_state_transition_count
        for item in results
    )
    hard_overrides = sum(
        item.hard_condition_override_count for item in results
    )
    unsafe = sum(item.unsafe_downgrade_count for item in results)
    cross_leaks = sum(
        item.cross_session_leak_count for item in results
    )
    failure_counts = {
        layer: sum(item.failure_layer is layer for item in results)
        for layer in _LAYER_ORDER
    }
    return ReplaySummary(
        case_count=len(results),
        passed_count=passed_count,
        end_to_end_rate=(
            passed_count / len(results) if results else 0.0
        ),
        wrong_product_selection_count=wrong_products,
        unauthorized_state_transition_count=unauthorized,
        hard_condition_override_count=hard_overrides,
        unsafe_downgrade_count=unsafe,
        cross_session_leak_count=cross_leaks,
        failure_counts=failure_counts,
        passed=(
            bool(results)
            and passed_count == len(results)
            and wrong_products == 0
            and unauthorized == 0
            and hard_overrides == 0
            and unsafe == 0
            and cross_leaks == 0
        ),
    )


def detect_hard_condition_override(
    *,
    events: Sequence[tuple[str, dict[str, JsonValue]]],
    card_ids: tuple[int, ...],
) -> bool:
    if not card_ids:
        return False
    has_selection_decision = any(
        event == "decision_process" for event, _ in events
    )
    if not has_selection_decision:
        return False
    decision_product_ids = {
        product_id
        for event, data in events
        if event == "decision_process"
        for product_id in data.get("ordered_product_ids", [])
        if isinstance(product_id, int)
        and not isinstance(product_id, bool)
    }
    return not set(card_ids).issubset(decision_product_ids)


def detect_cross_session_leak(
    *,
    expected: ConversationSnapshot,
    actual: ConversationSnapshot | None,
) -> bool:
    if type(expected) is not ConversationSnapshot:
        raise TypeError(
            "expected must be an exact ConversationSnapshot"
        )
    if actual is not None and type(actual) is not ConversationSnapshot:
        raise TypeError(
            "actual must be an exact ConversationSnapshot or None"
        )
    return actual != expected


def run_replay(
    cases: tuple[ReplayCase, ...],
    *,
    executor: Callable[[ReplayCase], ReplayTrace],
) -> tuple[ReplaySummary, tuple[ReplayResult, ...]]:
    if not cases or any(type(item) is not ReplayCase for item in cases):
        raise TypeError(
            "cases must be a nonempty tuple of exact ReplayCase values"
        )
    case_ids = tuple(item.case_id for item in cases)
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("replay case IDs must be unique")
    results: list[ReplayResult] = []
    for case in cases:
        trace = executor(case)
        if type(trace) is not ReplayTrace:
            raise TypeError("executor must return an exact ReplayTrace")
        results.append(evaluate_replay_trace(case=case, trace=trace))
    frozen = tuple(results)
    return summarize_replay(frozen), frozen


def _binding_keys(
    bindings: tuple[ResolvedProductBinding, ...],
) -> tuple[tuple[int, str | None], ...]:
    return tuple(
        (item.product_id, item.variant_scope)
        for item in bindings
    )


def _contains_expected(
    actual: JsonValue,
    expected: JsonValue,
) -> bool:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(
            key in actual
            and _contains_expected(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return False
        return len(actual) == len(expected) and all(
            _contains_expected(actual_item, expected_item)
            for actual_item, expected_item in zip(
                actual,
                expected,
                strict=True,
            )
        )
    return actual == expected


def _contradicts_expected(
    actual: JsonValue,
    expected: JsonValue,
) -> bool:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return True
        return any(
            key in actual
            and _contradicts_expected(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return actual != expected
    return actual != expected


_NONMUTATING_CLARIFICATION_FIELDS = (
    "session_profile",
    "focus_state",
    "has_image_delivery",
    "query_context",
    "empty_result",
    "candidates",
    "focused_candidate_ordinal",
    "focused_evidence_ids",
    "focused_general_knowledge_ids",
    "last_general_knowledge_question",
    "consultation",
)


def _is_nonmutating_fail_closed_clarification(
    *,
    case: ReplayCase,
    trace: ReplayTrace,
) -> bool:
    if (
        trace.route.processor != "clarification"
        or not trace.clarification
        or trace.card_ids
        or not isinstance(trace.final_snapshot.get("clarification"), dict)
    ):
        return False
    baseline = (
        case.starting_snapshot.model_dump(mode="json")
        if case.starting_snapshot is not None
        else {
            "session_profile": None,
            "focus_state": None,
            "has_image_delivery": False,
            "query_context": None,
            "empty_result": False,
            "candidates": [],
            "focused_candidate_ordinal": None,
            "focused_evidence_ids": [],
            "focused_general_knowledge_ids": [],
            "last_general_knowledge_question": None,
            "consultation": None,
        }
    )
    return all(
        trace.final_snapshot.get(field) == baseline.get(field)
        for field in _NONMUTATING_CLARIFICATION_FIELDS
    )


_LAYER_ORDER = (
    FailureLayer.MODEL_TRANSLATION,
    FailureLayer.SEMANTIC_ADMISSION,
    FailureLayer.IDENTITY_BINDING,
    FailureLayer.ROUTE_SELECTION,
    FailureLayer.STATE_TRANSITION,
    FailureLayer.DECISION_EXECUTION,
    FailureLayer.PRESENTATION,
)


def classify_earliest_failure(
    evidence: LayerEvidence,
) -> FailureLayer | None:
    if type(evidence) is not LayerEvidence:
        raise TypeError("evidence must be an exact LayerEvidence")
    for layer in _LAYER_ORDER:
        if not getattr(evidence, layer.value):
            return layer
    return None


__all__ = [
    "FailureLayer",
    "LayerEvidence",
    "ReplayCase",
    "ReplayManifest",
    "ReplayResult",
    "ReplaySummary",
    "ReplayTrace",
    "RouteExpectation",
    "SemanticExpectation",
    "build_replay_manifest",
    "classify_earliest_failure",
    "detect_cross_session_leak",
    "detect_hard_condition_override",
    "evaluate_replay_trace",
    "legacy_replay_payload",
    "load_replay_cases",
    "run_replay",
    "summarize_replay",
]
