from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from hashlib import sha256
from itertools import combinations
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from fastapi.testclient import TestClient
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.guide.feedback.contracts import ConversationSnapshot
from app.guide.feedback.profile_contracts import ProfileOwnerRef
from app.guide.intent.unified_turn_router import UnifiedRouteDecision
from app.guide.understanding.contracts import (
    StructuredUnderstanding,
    UnderstandingGoal,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning
from app.guide_runtime.app import create_app
from app.guide_runtime.composition import (
    build_consultation_vertical_runtime,
    build_feedback_service,
    build_image_bundle_service,
)
from app.guide_runtime.feedback_http import FEEDBACK_SESSION_COOKIE
from tools.guide_gates.zero_api_network_guard import ZeroApiNetworkGuard


DEFAULT_CASES_PATH = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "guide"
    / "intent"
    / "task11_production_path_matrix_v1.jsonl"
)
_RUNTIME_LAYER_ORDER = (
    "translation",
    "compiler",
    "router",
    "processor",
    "reducer",
    "sqlite",
    "sse",
)
_BOUNDED_TRAJECTORY_CONTRACT = (
    (
        "bounded-text-fit",
        "bounded-text-fit-t1",
        "给我推荐一款 900 到 1100 元的精华，我是油敏肌，换季容易泛红",
    ),
    (
        "bounded-text-context",
        "bounded-text-context-t1",
        "给我推荐 900 到 1100 元的精华",
    ),
    (
        "bounded-text-context",
        "bounded-text-context-t2",
        "第二款的质地适合什么肤质？",
    ),
    (
        "bounded-text-context",
        "bounded-text-context-t3",
        "我现在有点换季泛红，T 区出油，我可能是什么肤质？",
    ),
    (
        "bounded-text-context",
        "bounded-text-context-t4",
        "确认",
    ),
    (
        "bounded-text-context",
        "bounded-text-context-t5",
        "回到刚才的推荐，第一款和第二款哪个更适合我的肤质？",
    ),
    (
        "bounded-image-context",
        "bounded-image-context-t1",
        "",
    ),
    (
        "bounded-image-context",
        "bounded-image-context-t2",
        "给我找两款相似的，我最近换季泛红，T 区出油。",
    ),
    (
        "bounded-image-context",
        "bounded-image-context-t3",
        "图片里的 B5 和第一款哪个更适合我的肤质？",
    ),
)


class ProductionPathInvariantError(ValueError):
    pass


class StateCoveragePoint(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )

    active_owner: Literal[
        "none",
        "recommendation",
        "product_knowledge",
        "consultation",
        "general_knowledge",
        "image_identity",
        "clarification",
        "safety_escalation",
        "comparison",
    ]
    reply_state: Literal[
        "not_awaiting",
        "collecting_consultation",
        "confirmable_consultation",
        "pending_clarification",
    ]
    preserved_authority: Literal[
        "none",
        "product",
        "candidate_batch",
        "one_confirmed_image",
        "multiple_confirmed_images",
        "product_plus_active_consultation",
    ]
    semantic_act: Literal[
        "recommendation_request",
        "observation_answer",
        "ambiguous_continuation",
        "explicit_product_question",
        "explicit_image_question",
        "explicit_general_knowledge_question",
        "recommendation_revision",
        "explicit_return",
        "safety_escalation",
    ]
    reference_source: Literal[
        "none",
        "explicit_current_item",
        "candidate_ordinal",
        "image_ordinal",
        "current_batch",
        "ambiguous_reference",
    ]

    def edge_ids(self) -> tuple[str, ...]:
        dimensions = (
            ("active_owner", self.active_owner),
            ("reply_state", self.reply_state),
            ("preserved_authority", self.preserved_authority),
            ("semantic_act", self.semantic_act),
            ("reference_source", self.reference_source),
        )
        return tuple(
            f"{left_name}={left_value}|"
            f"{right_name}={right_value}"
            for (
                (left_name, left_value),
                (right_name, right_value),
            ) in combinations(dimensions, 2)
        )


class ProductionPathCase(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )

    schema_version: Literal[
        "guide-task11-production-path-case-v1"
    ] = "guide-task11-production-path-case-v1"
    case_id: str = Field(
        min_length=1,
        max_length=180,
        pattern=r"^[a-z0-9][a-z0-9_-]+$",
    )
    trajectory_id: str = Field(
        min_length=1,
        max_length=180,
        pattern=r"^[a-z0-9][a-z0-9_-]+$",
    )
    partition: Literal[
        "semantic",
        "state",
        "bounded",
        "pre_decision_rejection",
    ]
    message: str = Field(max_length=4000)
    conversation_version_delta: int = Field(default=0, ge=-20, le=20)
    expected_terminal_event: Literal["end", "error"] = "end"
    expected_rejection_stage: Literal[
        "none",
        "pre_decision",
    ] = "none"
    image_action: Literal["identify", "compare"] | None = None
    image_paths: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=4,
    )
    meaning: TurnMeaning
    expected_state_edge: str = Field(min_length=1, max_length=160)
    expected_coverage: StateCoveragePoint | None = None
    required_state_edges: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=10,
    )
    expected_processor: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
    )
    expected_intent: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
    )
    expected_card_ids: tuple[int, ...] | None = Field(
        default=None,
        max_length=4,
    )
    bounded: bool = False

    @model_validator(mode="before")
    @classmethod
    def reject_direct_state_setup(cls, value: object) -> object:
        if isinstance(value, dict) and "starting_snapshot" in value:
            raise ValueError(
                "direct state setup is forbidden in production-path cases"
            )
        return value

    @field_validator(
        "expected_card_ids",
        "image_paths",
        "required_state_edges",
        mode="before",
    )
    @classmethod
    def freeze_card_ids(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_starting_snapshot(self):
        is_stateful = self.partition in {"state", "bounded"}
        is_pre_decision_rejection = (
            self.partition == "pre_decision_rejection"
        )
        if is_pre_decision_rejection:
            if self.bounded:
                raise ValueError(
                    "pre-decision rejection cannot be a bounded turn"
                )
            if self.conversation_version_delta == 0:
                raise ValueError(
                    "pre-decision rejection requires version drift"
                )
            if self.expected_terminal_event != "error":
                raise ValueError(
                    "pre-decision rejection must expect error terminal"
                )
            if self.expected_rejection_stage != "pre_decision":
                raise ValueError(
                    "pre-decision rejection stage must be explicit"
                )
            if self.expected_coverage is not None:
                raise ValueError(
                    "pre-decision rejection has no state coverage point"
                )
            if self.required_state_edges:
                raise ValueError(
                    "pre-decision rejection has no required state edges"
                )
            if self.expected_processor not in {None, "none"}:
                raise ValueError(
                    "pre-decision rejection must not expect a processor"
                )
        elif (
            self.conversation_version_delta != 0
            or self.expected_terminal_event != "end"
            or self.expected_rejection_stage != "none"
        ):
            raise ValueError(
                "only pre-decision rejection cases may alter terminal "
                "or request-version expectations"
            )
        if self.image_action is None:
            if not self.message:
                raise ValueError(
                    "text production path case requires a message"
                )
            if len(self.image_paths) > 4:
                raise ValueError(
                    "text production path case allows at most four images"
                )
        else:
            if self.message:
                raise ValueError(
                    "typed image action forbids a text message"
                )
            expected_count = 1 if self.image_action == "identify" else None
            if expected_count is not None and len(self.image_paths) != 1:
                raise ValueError(
                    "identify action requires exactly one image path"
                )
            if (
                self.image_action == "compare"
                and not 2 <= len(self.image_paths) <= 4
            ):
                raise ValueError(
                    "compare action requires two to four image paths"
                )
            for raw_path in self.image_paths:
                path = Path(raw_path)
                if (
                    not raw_path
                    or path.is_absolute()
                    or ".." in path.parts
                ):
                    raise ValueError(
                        "image paths must be repository-relative"
                    )
        if is_stateful and self.expected_coverage is None:
            raise ValueError(
                "state partition requires expected coverage"
            )
        if (
            self.expected_coverage is not None
            and not set(self.required_state_edges).issubset(
                self.expected_coverage.edge_ids()
            )
        ):
            raise ValueError(
                "required state edges must belong to expected coverage"
            )
        if self.bounded != (self.partition == "bounded"):
            raise ValueError(
                "bounded marker must match bounded partition"
            )
        return self


class ProductionPathTurnTrace(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )

    turn_id: str = Field(
        min_length=1,
        max_length=180,
        pattern=r"^[a-z0-9][a-z0-9_-]+$",
    )
    trajectory_id: str = Field(
        min_length=1,
        max_length=180,
        pattern=r"^[a-z0-9][a-z0-9_-]+$",
    )
    partition: Literal[
        "semantic",
        "state",
        "bounded",
        "pre_decision_rejection",
    ]
    rejection_stage: Literal[
        "none",
        "pre_decision",
    ] = "none"
    translation_injection_count: int = Field(ge=0)
    structured_understanding_injection_count: int = Field(ge=0)
    compiler_call_count: int = Field(ge=0)
    direct_router_bypass_count: int = Field(ge=0)
    legacy_entrypoint_count: int = Field(ge=0)
    router_call_count: int = Field(ge=0)
    route_decision_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_processor_decision_digest: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    result_decision_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    sse_decision_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    validated_sse_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    emitted_sse_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_processor: str = Field(min_length=1, max_length=80)
    processor_invocation_counts: dict[str, int]
    processor_implementation_counts: dict[str, int]
    selected_processor_instance_entry_count: int = Field(ge=0)
    unregistered_processor_invocation_count: int = Field(ge=0)
    decision_identity_violation_count: int = Field(ge=0)
    execution_result_count: int = Field(ge=0)
    reducer_call_count: int = Field(ge=0)
    state_save_count: int = Field(ge=0)
    state_save_completed_count: int = Field(ge=0)
    state_backend: str = Field(min_length=1, max_length=160)
    processor_state_write_count: int = Field(ge=0)
    event_state_projection_count: int = Field(ge=0)
    provider_call_count: int = Field(ge=0)
    outbound_network_attempt_count: int = Field(ge=0)
    loaded_version: int = Field(ge=0)
    committed_version: int = Field(ge=0)
    expected_state_edge: str = Field(min_length=1, max_length=160)
    observed_state_edge: str = Field(min_length=1, max_length=160)
    terminal_event: Literal["end", "error"]
    bounded: bool
    semantic_equivalence_passed: bool
    accepted: bool = True
    coverage_edges: tuple[str, ...] = ()
    actual_processor: str = ""
    actual_intent: str = ""
    card_ids: tuple[int, ...] = ()
    event_names: tuple[str, ...] = ()
    observed_layers: tuple[str, ...] = ()

    @field_validator(
        "coverage_edges",
        "card_ids",
        "event_names",
        "observed_layers",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class ProductionPathSummary(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )

    schema_version: Literal[
        "guide-task11-production-path-summary-v1"
    ] = "guide-task11-production-path-summary-v1"
    candidate_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    protected_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cases_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    passed: bool
    expected_contract_case_count: int = Field(ge=0)
    actual_equivalence_case_count: int = Field(ge=0)
    actual_equivalence_failure_count: int = Field(ge=0)
    trajectory_count: int = Field(ge=0)
    stateful_turn_count: int = Field(ge=0)
    turn_count: int = Field(ge=0)
    state_edge_count: int = Field(ge=0)
    required_state_edge_count: int = Field(ge=0)
    bounded_turn_count: int = Field(ge=0)
    bounded_failure_count: int = Field(ge=0)
    pre_decision_rejection_count: int = Field(ge=0)
    pre_decision_rejection_failure_count: int = Field(ge=0)
    translation_injection_count: int = Field(ge=0)
    compiler_bypass_count: int = Field(ge=0)
    compiler_call_count_violation_count: int = Field(ge=0)
    structured_understanding_injection_count: int = Field(ge=0)
    direct_router_bypass_count: int = Field(ge=0)
    legacy_entrypoint_count: int = Field(ge=0)
    router_call_count_violation_count: int = Field(ge=0)
    decision_identity_violation_count: int = Field(ge=0)
    selected_processor_invocation_count_violation_count: int = Field(
        ge=0
    )
    nonselected_processor_invocation_count: int = Field(ge=0)
    execution_result_count_violation_count: int = Field(ge=0)
    reducer_call_count_violation_count: int = Field(ge=0)
    processor_state_write_count: int = Field(ge=0)
    event_state_projection_count: int = Field(ge=0)
    state_save_count_violation_count: int = Field(ge=0)
    terminal_contract_failure_count: int = Field(ge=0)
    state_transition_failure_count: int = Field(ge=0)
    outbound_network_attempt_count: int = Field(ge=0)
    provider_call_count: int = Field(ge=0)
    observed_layers: tuple[str, ...] = ()
    required_state_edges: tuple[str, ...] = ()
    turn_traces: tuple[ProductionPathTurnTrace, ...] = ()

    @field_validator(
        "required_state_edges",
        "observed_layers",
        "turn_traces",
        mode="before",
    )
    @classmethod
    def freeze_turn_traces(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


def _validate_bounded_trajectory_contract(
    cases: Sequence[ProductionPathCase],
) -> None:
    observed = tuple(
        (case.trajectory_id, case.case_id, case.message)
        for case in cases
        if case.bounded
    )
    if observed != _BOUNDED_TRAJECTORY_CONTRACT:
        raise ProductionPathInvariantError(
            "bounded trajectory contract does not match browser smoke"
        )


def load_production_path_cases(
    path: str | Path,
) -> tuple[ProductionPathCase, ...]:
    cases: list[ProductionPathCase] = []
    for line in Path(path).read_text(
        encoding="utf-8"
    ).splitlines():
        if not line.strip():
            continue
        cases.append(
            ProductionPathCase.model_validate_json(line, strict=True)
        )
    normalized = tuple(cases)
    case_ids = tuple(case.case_id for case in normalized)
    if len(normalized) != 177:
        raise ValueError(
            "Task 11 production matrix requires exactly 177 turns"
        )
    if len(case_ids) != len(set(case_ids)):
        raise ValueError(
            "Task 11 production matrix case IDs must be unique"
        )
    semantic = tuple(
        case for case in normalized if case.partition == "semantic"
    )
    stateful = tuple(
        case
        for case in normalized
        if case.partition in {"state", "bounded"}
    )
    if len(semantic) != 128 or len(stateful) != 48:
        raise ValueError(
            "Task 11 matrix requires 128 semantic and 48 state turns"
        )
    pre_decision_rejections = tuple(
        case
        for case in normalized
        if case.partition == "pre_decision_rejection"
    )
    if len(pre_decision_rejections) != 1:
        raise ValueError(
            "Task 11 matrix requires exactly one pre-decision rejection"
        )
    if len({
        case.trajectory_id for case in stateful
    }) != 12:
        raise ValueError(
            "Task 11 matrix requires exactly 12 state trajectories"
        )
    bounded = tuple(case for case in normalized if case.bounded)
    if (
        len(bounded) != 9
        or any(case.partition != "bounded" for case in bounded)
    ):
        raise ValueError(
            "Task 11 matrix requires exactly nine bounded turns"
        )
    _validate_bounded_trajectory_contract(normalized)
    required_state_edges = {
        edge
        for case in stateful
        for edge in case.required_state_edges
    }
    if len(required_state_edges) != 40:
        raise ValueError(
            "Task 11 matrix requires exactly 40 unique state edges"
        )
    return normalized


def summarize_production_path(
    traces: Sequence[ProductionPathTurnTrace],
    *,
    required_state_edges: Sequence[str],
    candidate_manifest_sha256: str,
    protected_payload_sha256: str,
    cases_sha256: str,
) -> ProductionPathSummary:
    normalized = tuple(traces)
    if not normalized or any(
        type(trace) is not ProductionPathTurnTrace
        for trace in normalized
    ):
        raise TypeError(
            "traces must be a nonempty sequence of exact "
            "ProductionPathTurnTrace values"
        )
    turn_ids = tuple(trace.turn_id for trace in normalized)
    if len(turn_ids) != len(set(turn_ids)):
        raise ValueError("production path turn IDs must be unique")
    required_edges = tuple(required_state_edges)
    if (
        len(required_edges) != 40
        or len(required_edges) != len(set(required_edges))
    ):
        raise ValueError(
            "Task 11 requires exactly 40 unique state edges"
        )

    semantic = tuple(
        trace
        for trace in normalized
        if trace.partition == "semantic"
    )
    accepted = tuple(trace for trace in normalized if trace.accepted)
    pre_decision_rejections = tuple(
        trace
        for trace in normalized
        if trace.partition == "pre_decision_rejection"
    )
    stateful = tuple(
        trace
        for trace in normalized
        if trace.partition in {"state", "bounded"}
    )
    bounded = tuple(trace for trace in normalized if trace.bounded)
    observed_edges = {
        edge
        for trace in stateful
        for edge in trace.coverage_edges
    }
    observed_required_edges = set(required_edges) & observed_edges
    missing_edges = set(required_edges) - observed_required_edges
    compiler_call_violations = sum(
        (
            trace.compiler_call_count != 0
            if trace.partition == "pre_decision_rejection"
            else trace.compiler_call_count != 1
        )
        for trace in normalized
    )
    router_call_violations = sum(
        (
            trace.router_call_count != 0
            if trace.partition == "pre_decision_rejection"
            else trace.router_call_count != 1
        )
        for trace in normalized
    )
    execution_result_violations = sum(
        (
            trace.execution_result_count != 0
            if trace.partition == "pre_decision_rejection"
            else trace.execution_result_count != 1
        )
        for trace in normalized
    )
    reducer_call_violations = sum(
        (
            trace.reducer_call_count != 1
            if trace.accepted
            else trace.reducer_call_count != 0
        )
        for trace in normalized
    )
    state_save_violations = sum(
        (
            (
                trace.state_save_count != 1
                or trace.state_save_completed_count != 1
            )
            if trace.accepted
            else (
                trace.state_save_count != 0
                or trace.state_save_completed_count != 0
            )
        )
        for trace in normalized
    )
    decision_identity_violations = sum(
        trace.decision_identity_violation_count
        + (
            trace.route_decision_digest
            != trace.result_decision_digest
        )
        for trace in normalized
    )
    selected_processor_violations = sum(
        (
            (
                trace.selected_processor != "none"
                or any(trace.processor_invocation_counts.values())
                or trace.processor_implementation_counts != {}
                or trace.selected_processor_instance_entry_count != 0
            )
            if trace.partition == "pre_decision_rejection"
            else (
                trace.processor_invocation_counts.get(
                    trace.selected_processor,
                    0,
                )
                != 1
                or trace.selected_processor_instance_entry_count != 1
            )
        )
        for trace in normalized
    )
    nonselected_processor_invocations = sum(
        count
        for trace in normalized
        for name, count in trace.processor_invocation_counts.items()
        if name != trace.selected_processor
    ) + sum(
        trace.unregistered_processor_invocation_count
        for trace in normalized
    )
    observed_layers = tuple(
        layer
        for layer in _RUNTIME_LAYER_ORDER
        if all(layer in trace.observed_layers for trace in accepted)
    )
    runtime_layer_violations = sum(
        trace.observed_layers != _RUNTIME_LAYER_ORDER
        for trace in normalized
        if trace.accepted
    )
    terminal_failures = sum(
        (
            trace.terminal_event != "end"
            if trace.accepted
            else trace.terminal_event != "error"
        )
        for trace in normalized
    )
    state_transition_failures = sum(
        (
            trace.expected_state_edge
            != trace.observed_state_edge
        )
        or (
            trace.committed_version
            != trace.loaded_version + 1
            if trace.accepted
            else trace.committed_version != trace.loaded_version
        )
        for trace in normalized
    )
    bounded_failures = sum(
        not _trace_passes(trace) for trace in bounded
    )
    pre_decision_rejection_failures = sum(
        not _trace_passes(trace) for trace in pre_decision_rejections
    )
    violation_counts = (
        sum(
            trace.structured_understanding_injection_count
            for trace in normalized
        ),
        sum(
            trace.direct_router_bypass_count for trace in normalized
        ),
        sum(trace.legacy_entrypoint_count for trace in normalized),
        compiler_call_violations,
        router_call_violations,
        decision_identity_violations,
        selected_processor_violations,
        nonselected_processor_invocations,
        execution_result_violations,
        reducer_call_violations,
        sum(
            trace.processor_state_write_count for trace in normalized
        ),
        sum(
            trace.event_state_projection_count for trace in normalized
        ),
        state_save_violations,
        terminal_failures,
        state_transition_failures,
        sum(
            trace.outbound_network_attempt_count
            for trace in normalized
        ),
        sum(trace.provider_call_count for trace in normalized),
        runtime_layer_violations,
        pre_decision_rejection_failures,
    )
    counts_match = (
        len(semantic) == 128
        and len(stateful) == 48
        and len(pre_decision_rejections) == 1
        and len(normalized) == 177
        and len({
            trace.trajectory_id for trace in stateful
        }) == 12
        and len(observed_required_edges) == 40
        and not missing_edges
        and len(bounded) == 9
    )
    equivalence_failures = sum(
        not trace.semantic_equivalence_passed for trace in semantic
    )
    return ProductionPathSummary(
        candidate_manifest_sha256=candidate_manifest_sha256,
        protected_payload_sha256=protected_payload_sha256,
        cases_sha256=cases_sha256,
        passed=(
            counts_match
            and equivalence_failures == 0
            and bounded_failures == 0
            and not any(violation_counts)
        ),
        expected_contract_case_count=128,
        actual_equivalence_case_count=len(semantic),
        actual_equivalence_failure_count=equivalence_failures,
        trajectory_count=len({
            trace.trajectory_id for trace in stateful
        }),
        stateful_turn_count=len(stateful),
        turn_count=len(normalized),
        state_edge_count=len(observed_required_edges),
        required_state_edge_count=len(required_edges),
        bounded_turn_count=len(bounded),
        bounded_failure_count=bounded_failures,
        pre_decision_rejection_count=len(pre_decision_rejections),
        pre_decision_rejection_failure_count=(
            pre_decision_rejection_failures
        ),
        translation_injection_count=sum(
            trace.translation_injection_count
            for trace in normalized
        ),
        compiler_bypass_count=sum(
            trace.compiler_call_count == 0
            and trace.partition != "pre_decision_rejection"
            for trace in normalized
        ),
        compiler_call_count_violation_count=(
            compiler_call_violations
        ),
        structured_understanding_injection_count=(
            violation_counts[0]
        ),
        direct_router_bypass_count=violation_counts[1],
        legacy_entrypoint_count=violation_counts[2],
        router_call_count_violation_count=router_call_violations,
        decision_identity_violation_count=(
            decision_identity_violations
        ),
        selected_processor_invocation_count_violation_count=(
            selected_processor_violations
        ),
        nonselected_processor_invocation_count=(
            nonselected_processor_invocations
        ),
        execution_result_count_violation_count=(
            execution_result_violations
        ),
        reducer_call_count_violation_count=(
            reducer_call_violations
        ),
        processor_state_write_count=violation_counts[10],
        event_state_projection_count=violation_counts[11],
        state_save_count_violation_count=state_save_violations,
        terminal_contract_failure_count=terminal_failures,
        state_transition_failure_count=state_transition_failures,
        outbound_network_attempt_count=violation_counts[15],
        provider_call_count=violation_counts[16],
        observed_layers=observed_layers,
        required_state_edges=required_edges,
        turn_traces=normalized,
    )


def _trace_passes(trace: ProductionPathTurnTrace) -> bool:
    try:
        validate_production_path_trace(trace)
    except ProductionPathInvariantError:
        return False
    return trace.semantic_equivalence_passed


def _digest_model(value: object) -> str:
    model_dump = getattr(value, "model_dump", None)
    if not callable(model_dump):
        return "0" * 64
    payload = model_dump(mode="json")
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _snapshot_version(snapshot: ConversationSnapshot | None) -> int:
    return snapshot.version if snapshot is not None else 0


def _snapshot_owner(snapshot: ConversationSnapshot | None) -> str:
    if snapshot is None or snapshot.active_owner is None:
        return "none"
    owner = snapshot.active_owner.value
    return (
        "product_knowledge"
        if owner == "single_product_suitability"
        else owner
    )


def _parse_sse(payload: bytes) -> tuple[tuple[str, dict], ...]:
    if type(payload) is not bytes:
        raise TypeError("HTTP SSE payload must be bytes")
    text = payload.decode("utf-8")
    events: list[tuple[str, dict]] = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        name = ""
        payload = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line.removeprefix("event: ").strip()
            elif line.startswith("data: "):
                payload += line.removeprefix("data: ")
        if not name or not payload:
            raise ProductionPathInvariantError(
                "HTTP response contains malformed SSE"
            )
        decoded = json.loads(payload)
        if not isinstance(decoded, dict):
            raise ProductionPathInvariantError(
                "HTTP SSE payload must be an object"
            )
        events.append((name, decoded))
    return tuple(events)


class _FrozenTurnMeaningProvider:
    def __init__(self) -> None:
        self._message: str | None = None
        self._meaning: TurnMeaning | None = None
        self.call_count = 0

    def bind(self, *, message: str, meaning: TurnMeaning) -> None:
        self._message = message
        self._meaning = meaning
        self.call_count = 0

    def propose(self, message, context) -> TurnMeaning:
        del context
        if message != self._message or self._meaning is None:
            raise ProductionPathInvariantError(
                "frozen TurnMeaning binding mismatch"
            )
        self.call_count += 1
        return self._meaning.model_copy(deep=True)


class _ProductionPathObserver:
    def __init__(self) -> None:
        self._state = None
        self._session_id = ""
        self._loaded_version = 0
        self.reset()

    def bind(
        self,
        *,
        state,
        session_id: str,
        loaded_version: int,
        registered_processors: Mapping[str, object],
    ) -> None:
        self._state = state
        self._session_id = session_id
        self._loaded_version = loaded_version
        self.reset()
        self._registered_processor_instances = dict(
            registered_processors
        )
        self.processor_invocation_counts = {
            name: 0 for name in registered_processors
        }
        self.state_backend = type(state).__qualname__

    def reset(self) -> None:
        self.turn_meaning_supply_count = 0
        self.compiler_call_count = 0
        self.router_call_count = 0
        self.execution_result_count = 0
        self.reducer_call_count = 0
        self.state_save_count = 0
        self.processor_state_write_count = 0
        self.event_state_projection_count = 0
        self.decision_identity_violation_count = 0
        self.route_decision = None
        self.selected_processor_decision = None
        self.result_decision = None
        self.supplied_meaning = None
        self.compiler_input_meaning = None
        self.compiled_meaning = None
        self.compiled_understanding = None
        self.reduced_snapshot = None
        self._registered_processor_instances: dict[str, object] = {}
        self.processor_invocation_counts: dict[str, int] = {}
        self.processor_implementation_counts: dict[str, int] = {}
        self.selected_processor_instance_entry_count = 0
        self.unregistered_processor_invocation_count = 0
        self.state_save_completed_count = 0
        self.state_backend = ""
        self.sse_decision_digest = "0" * 64
        self.validated_sse_bytes = b""

    def turn_meaning_supplied(self, **values) -> None:
        self.turn_meaning_supply_count += 1
        self.supplied_meaning = values["meaning"]

    def compiler_invoked(self, **values) -> None:
        self.compiler_call_count += 1
        self.compiler_input_meaning = values["meaning"]

    def compiled(self, **values) -> None:
        self.compiled_meaning = values["meaning"]
        self.compiled_understanding = values["understanding"]

    def router_invoked(self, **values) -> None:
        del values
        self.router_call_count += 1

    def routed(self, **values) -> None:
        self.route_decision = values["decision"]

    def processor_entered(self, **values) -> None:
        selected = values["processor"]
        instance = values["instance"]
        implementation = values["implementation"]
        expected_instance = self._registered_processor_instances.get(
            selected
        )
        if (
            expected_instance is None
            or instance is not expected_instance
            or implementation != type(instance).__qualname__
        ):
            self.unregistered_processor_invocation_count += 1
            return
        self.selected_processor_decision = values["decision"]
        if self.selected_processor_decision is not self.route_decision:
            self.decision_identity_violation_count += 1
        self.processor_invocation_counts[selected] = (
            self.processor_invocation_counts.get(selected, 0) + 1
        )
        self.processor_implementation_counts[implementation] = (
            self.processor_implementation_counts.get(
                implementation,
                0,
            )
            + 1
        )
        self.selected_processor_instance_entry_count += 1

    def result_received(self, **values) -> None:
        self.execution_result_count += 1
        self.result_decision = values["result"].decision
        if self.result_decision is not self.route_decision:
            self.decision_identity_violation_count += 1
        if self._current_version() != self._loaded_version:
            self.processor_state_write_count += 1

    def reducer_invoked(self, **values) -> None:
        del values
        self.reducer_call_count += 1

    def state_reduced(self, **values) -> None:
        self.reduced_snapshot = values["snapshot"]
        if self._current_version() != self._loaded_version:
            self.processor_state_write_count += 1

    def envelope_materialized(self, **values) -> None:
        envelope = values["envelope"]
        self.sse_decision_digest = envelope.decision_digest
        self.validated_sse_bytes = b"".join(envelope.frames)
        if self._current_version() != self._loaded_version:
            self.event_state_projection_count += 1

    def state_save_invoked(self, **values) -> None:
        del values
        self.state_save_count += 1

    def state_saved(self, **values) -> None:
        del values
        self.state_save_completed_count += 1

    def _current_version(self) -> int:
        if self._state is None:
            return 0
        return _snapshot_version(
            self._state.load(self._session_id)
        )


def _derive_observed_layers(
    *,
    observer: _ProductionPathObserver,
    emitted_sse: bytes,
) -> tuple[str, ...]:
    layers: list[str] = []
    if (
        observer.turn_meaning_supply_count == 1
        and type(observer.supplied_meaning) is TurnMeaning
    ):
        layers.append("translation")
    if (
        observer.compiler_call_count == 1
        and type(observer.compiled_understanding)
        is StructuredUnderstanding
    ):
        layers.append("compiler")
    if (
        observer.router_call_count == 1
        and type(observer.route_decision) is UnifiedRouteDecision
    ):
        layers.append("router")
    if (
        observer.selected_processor_instance_entry_count == 1
        and observer.unregistered_processor_invocation_count == 0
        and sum(observer.processor_invocation_counts.values()) == 1
        and observer.selected_processor_decision
        is observer.route_decision
    ):
        layers.append("processor")
    if (
        observer.reducer_call_count == 1
        and type(observer.reduced_snapshot) is ConversationSnapshot
    ):
        layers.append("reducer")
    if (
        observer.state_backend == "SqliteConversationState"
        and observer.state_save_count == 1
        and observer.state_save_completed_count == 1
    ):
        layers.append("sqlite")
    if (
        observer.validated_sse_bytes
        and observer.validated_sse_bytes == emitted_sse
        and observer.sse_decision_digest != "0" * 64
    ):
        layers.append("sse")
    return tuple(layers)


class Task11ProductionPathRuntime:
    def __init__(
        self,
        *,
        repo_root: str | Path,
        state_root: str | Path,
        network_guard: ZeroApiNetworkGuard | None = None,
    ) -> None:
        if os.environ.get("GUIDE_COPY_LLM_API_KEY"):
            raise ProductionPathInvariantError(
                "zero-provider matrix forbids copywriter credentials"
            )
        root = Path(repo_root).resolve()
        state_directory = Path(state_root).resolve()
        if not root.is_dir():
            raise ValueError("repo_root must be a directory")
        state_directory.mkdir(parents=True, exist_ok=False)
        self._repo_root = root
        self._network_guard = network_guard
        self._provider = _FrozenTurnMeaningProvider()
        self._observer = _ProductionPathObserver()
        image_bundles = build_image_bundle_service(
            database_path=state_directory / "image_bundles.sqlite3"
        )
        self._vertical = build_consultation_vertical_runtime(
            repo_root=root,
            state_dir=state_directory,
            semantic_intent=self._provider,
            execution_observer=self._observer,
            image_bundle_service=image_bundles,
        )
        self._client = TestClient(
            create_app(
                consultation_runtime=self._vertical,
                image_bundle_service=image_bundles,
                feedback_service=build_feedback_service(
                    state_directory=state_directory,
                ),
                repo_root=root,
            )
        )
        self._profile_owner = self._bind_profile_owner("bootstrap")

    def _bind_profile_owner(
        self,
        trajectory_id: str,
    ) -> ProfileOwnerRef:
        digest = sha256(trajectory_id.encode("utf-8")).hexdigest()
        feedback_cookie = "feedback_session_" + digest[:43]
        self._client.cookies.set(
            FEEDBACK_SESSION_COOKIE,
            feedback_cookie,
        )
        owner = ProfileOwnerRef(
            scope="local_demo",
            subject_id=(
                "feedback-browser-"
                + sha256(feedback_cookie.encode("utf-8")).hexdigest()
            ),
        )
        self._profile_owner = owner
        return owner

    def execute(
        self,
        case: ProductionPathCase,
    ) -> ProductionPathTurnTrace:
        if type(case) is not ProductionPathCase:
            raise TypeError(
                "case must be an exact ProductionPathCase"
            )
        if self._network_guard is None:
            with ZeroApiNetworkGuard() as guard:
                self._network_guard = guard
                try:
                    return self.execute(case)
                finally:
                    self._network_guard = None
        self._bind_profile_owner(case.trajectory_id)
        before = self._vertical.conversation_state.load(case.trajectory_id)
        loaded_version = _snapshot_version(before)
        provider_calls_before = self._network_guard.provider_call_count
        network_attempts_before = (
            self._network_guard.outbound_network_attempt_count
        )
        self._provider.bind(
            message=case.message,
            meaning=case.meaning,
        )
        self._observer.bind(
            state=self._vertical.conversation_state,
            session_id=case.trajectory_id,
            loaded_version=loaded_version,
            registered_processors=(
                self._vertical.unified._processor_registry
            ),
        )
        request_payload = {
            "message": case.message,
            "session_id": case.trajectory_id,
            "conversation_version": (
                loaded_version + case.conversation_version_delta
            ),
            "stream": True,
        }
        if case.image_paths:
            receipt = self._upload_images(case)
            request_payload.update({
                "image_bundle_id": receipt["bundle_id"],
                "image_bundle_version": receipt["version"],
                "image_bundle_token": receipt["owner_token"],
            })
            if case.image_action is not None:
                request_payload["image_action"] = case.image_action
        response = self._client.post(
            "/api/v1/chat/stream",
            json=request_payload,
        )
        if response.status_code != 200:
            raise ProductionPathInvariantError(
                f"HTTP production path returned {response.status_code}"
            )
        events = _parse_sse(response.content)
        event_names = tuple(name for name, _ in events)
        terminal_names = tuple(
            name for name in event_names if name in {"end", "error"}
        )
        terminal_contract_passed = (
            len(terminal_names) == 1
            and bool(event_names)
            and event_names[-1] == terminal_names[0]
        )
        terminal_event = (
            terminal_names[0]
            if terminal_contract_passed
            else "error"
        )
        accepted = terminal_event == "end"
        after = self._vertical.conversation_state.load(
            case.trajectory_id
        )
        if accepted:
            _validate_committed_snapshot(
                reduced=self._observer.reduced_snapshot,
                committed=after,
            )
        elif before is not None and after is not None:
            if before.model_dump(mode="json") != after.model_dump(mode="json"):
                raise ProductionPathInvariantError(
                    "rejected turn must preserve the loaded snapshot"
                )
        elif before is not after:
            raise ProductionPathInvariantError(
                "rejected turn must preserve empty state"
            )
        actual_intent = next(
            (
                str(data.get("intent") or "")
                for name, data in events
                if name == "intent"
            ),
            "",
        )
        card_ids = tuple(
            item["id"]
            for name, data in events
            if name == "products"
            for item in data.get("products", [])
            if isinstance(item, dict)
            and type(item.get("id")) is int
        )
        route_digest = _digest_model(
            self._observer.route_decision
        )
        result_digest = _digest_model(
            self._observer.result_decision
        )
        selected_processor_digest = _digest_model(
            self._observer.selected_processor_decision
        )
        emitted_sse_sha256 = sha256(response.content).hexdigest()
        validated_sse_bytes = self._observer.validated_sse_bytes
        if (
            case.expected_rejection_stage == "pre_decision"
            and not validated_sse_bytes
        ):
            validated_sse_bytes = response.content
        validated_sse_sha256 = sha256(
            validated_sse_bytes
        ).hexdigest()
        actual_processor = (
            self._observer.route_decision.processor
            if self._observer.route_decision is not None
            else "none"
        )
        actual_coverage = (
            _derive_state_coverage(
                current=before,
                understanding=self._observer.compiled_understanding,
                decision=self._observer.route_decision,
                committed=after,
                current_image_action=case.image_action,
            )
            if self._observer.compiled_understanding is not None
            and self._observer.route_decision is not None
            and after is not None
            else None
        )
        compiled_meaning_matches = (
            self._observer.compiled_meaning == case.meaning
        )
        translation_injection_count = (
            self._observer.turn_meaning_supply_count
        )
        structured_understanding_injection_count = int(
            self._observer.compiler_input_meaning
            is not self._observer.supplied_meaning
        )
        processor_invocation_count = sum(
            self._observer.processor_invocation_counts.values()
        )
        direct_router_bypass_count = int(
            processor_invocation_count > self._observer.router_call_count
        )
        request_path = response.request.url.path
        legacy_entrypoint_count = int(
            request_path != "/api/v1/chat/stream"
        )
        provider_call_count = (
            self._network_guard.provider_call_count
            - provider_calls_before
        )
        outbound_network_attempt_count = (
            self._network_guard.outbound_network_attempt_count
            - network_attempts_before
        )
        observed_layers = _derive_observed_layers(
            observer=self._observer,
            emitted_sse=response.content,
        )
        semantic_equivalence_passed = (
            (
                terminal_contract_passed
                and terminal_event == case.expected_terminal_event
                and event_names == ("start", "error")
                and before is not None
                and after is not None
                and before.model_dump(mode="json")
                == after.model_dump(mode="json")
                and translation_injection_count == 0
                and self._observer.compiler_call_count == 0
                and self._observer.router_call_count == 0
                and self._observer.execution_result_count == 0
                and self._observer.reducer_call_count == 0
                and self._observer.state_save_count == 0
                and provider_call_count == 0
                and outbound_network_attempt_count == 0
            )
            if case.expected_rejection_stage == "pre_decision"
            else (
                terminal_contract_passed
                and terminal_event == case.expected_terminal_event
                and compiled_meaning_matches
                and (
                    case.expected_processor is None
                    or actual_processor == case.expected_processor
                )
                and (
                    case.expected_intent is None
                    or actual_intent == case.expected_intent
                )
                and (
                    case.expected_card_ids is None
                    or card_ids == case.expected_card_ids
                )
                and (
                    case.expected_coverage is None
                    or actual_coverage == case.expected_coverage
                )
            )
        )
        trace = ProductionPathTurnTrace(
            turn_id=case.case_id,
            trajectory_id=case.trajectory_id,
            partition=case.partition,
            rejection_stage=case.expected_rejection_stage,
            translation_injection_count=translation_injection_count,
            structured_understanding_injection_count=(
                structured_understanding_injection_count
            ),
            compiler_call_count=self._observer.compiler_call_count,
            direct_router_bypass_count=direct_router_bypass_count,
            legacy_entrypoint_count=legacy_entrypoint_count,
            router_call_count=self._observer.router_call_count,
            route_decision_digest=route_digest,
            selected_processor_decision_digest=(
                selected_processor_digest
            ),
            result_decision_digest=result_digest,
            sse_decision_digest=self._observer.sse_decision_digest,
            validated_sse_sha256=validated_sse_sha256,
            emitted_sse_sha256=emitted_sse_sha256,
            selected_processor=actual_processor,
            processor_invocation_counts=(
                self._observer.processor_invocation_counts
            ),
            processor_implementation_counts=(
                self._observer.processor_implementation_counts
            ),
            selected_processor_instance_entry_count=(
                self._observer.selected_processor_instance_entry_count
            ),
            unregistered_processor_invocation_count=(
                self._observer.unregistered_processor_invocation_count
            ),
            decision_identity_violation_count=(
                self._observer.decision_identity_violation_count
            ),
            execution_result_count=(
                self._observer.execution_result_count
            ),
            reducer_call_count=self._observer.reducer_call_count,
            state_save_count=self._observer.state_save_count,
            state_save_completed_count=(
                self._observer.state_save_completed_count
            ),
            state_backend=self._observer.state_backend,
            processor_state_write_count=(
                self._observer.processor_state_write_count
            ),
            event_state_projection_count=(
                self._observer.event_state_projection_count
            ),
            provider_call_count=provider_call_count,
            outbound_network_attempt_count=(
                outbound_network_attempt_count
            ),
            loaded_version=loaded_version,
            committed_version=_snapshot_version(after),
            expected_state_edge=case.expected_state_edge,
            observed_state_edge=(
                f"{_snapshot_owner(before)}->{_snapshot_owner(after)}"
            ),
            terminal_event=terminal_event,
            bounded=case.bounded,
            semantic_equivalence_passed=semantic_equivalence_passed,
            accepted=accepted,
            coverage_edges=(
                actual_coverage.edge_ids()
                if actual_coverage is not None
                else ()
            ),
            actual_processor=actual_processor,
            actual_intent=actual_intent,
            card_ids=card_ids,
            event_names=event_names,
            observed_layers=observed_layers,
        )
        if not terminal_contract_passed:
            raise ProductionPathInvariantError(
                "HTTP SSE terminal contract failed"
            )
        if not trace.semantic_equivalence_passed:
            raise ProductionPathInvariantError(
                "HTTP output does not match declared case expectation: "
                f"intent={actual_intent!r}, card_ids={card_ids!r}, "
                f"events={events!r}, "
                f"translation={translation_injection_count}, "
                f"compiler={self._observer.compiler_call_count}, "
                f"router={self._observer.router_call_count}, "
                f"result={self._observer.execution_result_count}"
            )
        return trace

    def _upload_images(
        self,
        case: ProductionPathCase,
    ) -> dict[str, object]:
        media_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }
        files = []
        for raw_path in case.image_paths:
            path = (self._repo_root / raw_path).resolve()
            try:
                path.relative_to(self._repo_root)
                media_type = media_types[path.suffix.lower()]
            except (KeyError, ValueError) as exc:
                raise ProductionPathInvariantError(
                    "image fixture must be a supported repository file"
                ) from exc
            if not path.is_file():
                raise ProductionPathInvariantError(
                    f"image fixture does not exist: {raw_path}"
                )
            files.append(
                (
                    "images",
                    (path.name, path.read_bytes(), media_type),
                )
            )
        response = self._client.post(
            "/api/v1/chat/image-bundles",
            data={"session_id": case.trajectory_id},
            files=files,
        )
        if response.status_code != 201:
            raise ProductionPathInvariantError(
                "HTTP image bundle upload failed: "
                f"{response.status_code}"
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise ProductionPathInvariantError(
                "HTTP image bundle receipt must be an object"
            )
        return payload


def _validate_committed_snapshot(
    *,
    reduced: ConversationSnapshot | None,
    committed: ConversationSnapshot | None,
) -> None:
    if reduced is None or committed is None:
        raise ProductionPathInvariantError(
            "accepted turn must expose reducer and committed snapshots"
        )
    reduced_payload = reduced.model_dump(mode="json")
    committed_payload = committed.model_dump(mode="json")
    if committed_payload != reduced_payload:
        raise ProductionPathInvariantError(
            "committed snapshot differs from reducer output"
        )


def _derive_state_coverage(
    *,
    current: ConversationSnapshot | None,
    understanding: StructuredUnderstanding,
    decision: UnifiedRouteDecision,
    committed: ConversationSnapshot,
    current_image_action: str | None = None,
) -> StateCoveragePoint:
    if type(understanding) is not StructuredUnderstanding:
        raise ProductionPathInvariantError(
            "state coverage requires observed compiled understanding"
        )
    if type(decision) is not UnifiedRouteDecision:
        raise ProductionPathInvariantError(
            "state coverage requires observed route decision"
        )
    if type(committed) is not ConversationSnapshot:
        raise ProductionPathInvariantError(
            "state coverage requires the committed snapshot"
        )
    expected_owner = {
        "recommendation": "recommendation",
        "comparison": "comparison",
        "product_knowledge": "product_knowledge",
        "general_knowledge": "general_knowledge",
        "clarification": "clarification",
        "consultation": "consultation",
        "safety_escalation": "safety_escalation",
        "image_identity": "image_identity",
        "image_comparison": "comparison",
    }[decision.processor]
    if _snapshot_owner(committed) != expected_owner:
        raise ProductionPathInvariantError(
            "committed owner does not match the observed processor"
        )
    active_owner = _snapshot_owner(current)
    reply_state = "not_awaiting"
    if current is not None and current.reply_slot is not None:
        reply_state = "pending_clarification"
    elif current is not None and current.consultation_slot is not None:
        assessment = (
            current.consultation_slot.state.confirmable_assessment
        )
        if (
            assessment is not None
            and not assessment.conclusion.confirmed_by_user
            and assessment.assessment_kind == "provisional"
        ):
            reply_state = "confirmable_consultation"
        elif active_owner == "consultation":
            reply_state = "collecting_consultation"

    confirmed_images = (
        current.image_slot.confirmed_products
        if current is not None and current.image_slot is not None
        else ()
    )
    has_product = bool(
        current is not None
        and current.product_slot is not None
        and (
            current.product_slot.focused_product_id is not None
            or len(current.product_slot.products) == 1
        )
    )
    has_candidates = bool(
        current is not None
        and current.recommendation_slot is not None
        and current.recommendation_slot.candidates
    )
    has_active_consultation = bool(
        current is not None
        and current.consultation_slot is not None
        and active_owner == "consultation"
    )
    if has_active_consultation and (has_product or has_candidates):
        authority = "product_plus_active_consultation"
    elif len(confirmed_images) > 1:
        authority = "multiple_confirmed_images"
    elif len(confirmed_images) == 1:
        authority = "one_confirmed_image"
    elif has_product:
        authority = "product"
    elif has_candidates:
        authority = "candidate_batch"
    else:
        authority = "none"

    reference_source = "none"
    reference_kinds = {
        reference.kind for reference in understanding.references
    }
    image_reference_count = sum(
        reference.kind == "image_ordinal"
        for reference in understanding.references
    )
    if current_image_action == "compare":
        reference_source = "current_batch"
    elif current_image_action == "identify":
        reference_source = "image_ordinal"
    elif (
        decision.processor == "clarification"
        and decision.clarification_code is not None
    ):
        reference_source = "ambiguous_reference"
    elif (
        "current_batch" in reference_kinds
        or image_reference_count > 1
    ):
        reference_source = "current_batch"
    elif image_reference_count == 1 or (
        decision.focus_source == "confirmed_image"
        and len(confirmed_images) == 1
    ):
        reference_source = "image_ordinal"
    elif any(
        kind == "candidate_ordinal"
        for kind in reference_kinds
    ):
        reference_source = "candidate_ordinal"
    elif understanding.product_mentions or any(
        kind == "current_item"
        for kind in reference_kinds
    ):
        reference_source = "explicit_current_item"

    if decision.processor == "safety_escalation":
        semantic_act = "safety_escalation"
    elif decision.continuity == "return_to_focus":
        semantic_act = "explicit_return"
    elif understanding.goal is UnderstandingGoal.ASSESSMENT:
        semantic_act = "observation_answer"
    elif reference_source == "image_ordinal":
        semantic_act = "explicit_image_question"
    elif reference_source in {
        "explicit_current_item",
        "candidate_ordinal",
        "current_batch",
    }:
        semantic_act = "explicit_product_question"
    elif decision.processor == "general_knowledge":
        semantic_act = "explicit_general_knowledge_question"
    elif decision.processor == "clarification":
        semantic_act = "ambiguous_continuation"
    elif (
        decision.processor == "recommendation"
        and current is not None
        and current.recommendation_slot is not None
    ):
        semantic_act = "recommendation_revision"
    else:
        semantic_act = "recommendation_request"

    return StateCoveragePoint(
        active_owner=active_owner,
        reply_state=reply_state,
        preserved_authority=authority,
        semantic_act=semantic_act,
        reference_source=reference_source,
    )


def _validate_pre_decision_rejection_trace(
    trace: ProductionPathTurnTrace,
) -> None:
    if trace.rejection_stage != "pre_decision":
        raise ProductionPathInvariantError(
            "pre-decision rejection must declare its rejection stage"
        )
    zero_count_fields = (
        "translation_injection_count",
        "structured_understanding_injection_count",
        "compiler_call_count",
        "router_call_count",
        "execution_result_count",
        "reducer_call_count",
        "state_save_count",
        "state_save_completed_count",
        "selected_processor_instance_entry_count",
        "unregistered_processor_invocation_count",
        "decision_identity_violation_count",
        "processor_state_write_count",
        "event_state_projection_count",
        "provider_call_count",
        "outbound_network_attempt_count",
    )
    for field in zero_count_fields:
        if getattr(trace, field) != 0:
            raise ProductionPathInvariantError(
                "pre-decision rejection must not enter the mainline"
            )
    if trace.direct_router_bypass_count != 0:
        raise ProductionPathInvariantError(
            "pre-decision rejection must not use a router bypass"
        )
    if trace.legacy_entrypoint_count != 0:
        raise ProductionPathInvariantError(
            "pre-decision rejection must use the production entrypoint"
        )
    if len({
        trace.route_decision_digest,
        trace.selected_processor_decision_digest,
        trace.result_decision_digest,
        trace.sse_decision_digest,
    }) != 1 or trace.route_decision_digest != "0" * 64:
        raise ProductionPathInvariantError(
            "pre-decision rejection must not fabricate a decision"
        )
    if trace.validated_sse_sha256 != trace.emitted_sse_sha256:
        raise ProductionPathInvariantError(
            "pre-decision rejection SSE bytes must be stable"
        )
    if (
        trace.selected_processor != "none"
        or trace.actual_processor != "none"
        or any(trace.processor_invocation_counts.values())
        or trace.processor_implementation_counts != {}
    ):
        raise ProductionPathInvariantError(
            "pre-decision rejection must not invoke a processor"
        )
    if (
        trace.accepted
        or trace.terminal_event != "error"
        or trace.semantic_equivalence_passed is not True
        or trace.event_names != ("start", "error")
        or trace.coverage_edges
        or trace.card_ids
    ):
        raise ProductionPathInvariantError(
            "pre-decision rejection terminal contract is invalid"
        )
    if trace.committed_version != trace.loaded_version:
        raise ProductionPathInvariantError(
            "pre-decision rejection must not mutate state version"
        )
    if trace.expected_state_edge != trace.observed_state_edge:
        raise ProductionPathInvariantError(
            "pre-decision rejection must preserve state owner"
        )


def validate_production_path_trace(
    trace: ProductionPathTurnTrace,
) -> None:
    if type(trace) is not ProductionPathTurnTrace:
        raise TypeError(
            "trace must be an exact ProductionPathTurnTrace"
        )
    if trace.partition == "pre_decision_rejection":
        _validate_pre_decision_rejection_trace(trace)
        return
    if trace.translation_injection_count != 1:
        raise ProductionPathInvariantError(
            "turn must use exactly one TurnMeaning injection"
        )
    if trace.structured_understanding_injection_count:
        raise ProductionPathInvariantError(
            "StructuredUnderstanding injection is forbidden"
        )
    if trace.compiler_call_count != 1:
        raise ProductionPathInvariantError(
            "accepted turn requires exactly one compiler call"
        )
    if trace.direct_router_bypass_count:
        raise ProductionPathInvariantError(
            "direct router bypass is forbidden"
        )
    if trace.legacy_entrypoint_count:
        raise ProductionPathInvariantError(
            "legacy production entrypoint is forbidden"
        )
    if trace.router_call_count != 1:
        raise ProductionPathInvariantError(
            "accepted turn requires exactly one router call"
        )
    if trace.route_decision_digest != trace.result_decision_digest:
        raise ProductionPathInvariantError(
            "route and result decision identity must match"
        )
    if len({
        trace.route_decision_digest,
        trace.selected_processor_decision_digest,
        trace.result_decision_digest,
        trace.sse_decision_digest,
    }) != 1:
        raise ProductionPathInvariantError(
            "decision identity must match across all boundaries"
        )
    if trace.validated_sse_sha256 != trace.emitted_sse_sha256:
        raise ProductionPathInvariantError(
            "emitted SSE bytes must equal the validated envelope"
        )
    if trace.processor_invocation_counts.get(
        trace.selected_processor,
        0,
    ) != 1:
        raise ProductionPathInvariantError(
            "selected processor must be invoked exactly once"
        )
    if trace.selected_processor_instance_entry_count != 1:
        raise ProductionPathInvariantError(
            "selected registry processor instance must be entered exactly once"
        )
    if trace.unregistered_processor_invocation_count:
        raise ProductionPathInvariantError(
            "unregistered processor invocation is forbidden"
        )
    if any(
        count
        for name, count in trace.processor_invocation_counts.items()
        if name != trace.selected_processor
    ):
        raise ProductionPathInvariantError(
            "non-selected processor invocation is forbidden"
        )
    if trace.decision_identity_violation_count:
        raise ProductionPathInvariantError(
            "processor must return the exact route decision object"
        )
    if trace.execution_result_count != 1:
        raise ProductionPathInvariantError(
            "accepted turn requires exactly one ExecutionResult"
        )
    if trace.accepted and trace.reducer_call_count != 1:
        raise ProductionPathInvariantError(
            "accepted turn requires exactly one reducer call"
        )
    if trace.accepted and trace.state_save_count != 1:
        raise ProductionPathInvariantError(
            "accepted turn requires exactly one state save"
        )
    if trace.accepted and trace.state_save_completed_count != 1:
        raise ProductionPathInvariantError(
            "accepted turn requires exactly one completed state save"
        )
    if trace.processor_state_write_count:
        raise ProductionPathInvariantError(
            "processor state writes are forbidden"
        )
    if trace.event_state_projection_count:
        raise ProductionPathInvariantError(
            "event-to-state projection is forbidden"
        )
    if trace.provider_call_count:
        raise ProductionPathInvariantError(
            "provider calls are forbidden in the zero-provider matrix"
        )
    if trace.outbound_network_attempt_count:
        raise ProductionPathInvariantError(
            "outbound network attempts are forbidden"
        )
    if trace.accepted:
        if trace.committed_version != trace.loaded_version + 1:
            raise ProductionPathInvariantError(
                "accepted turn must commit exactly one snapshot version"
            )
        if trace.terminal_event != "end":
            raise ProductionPathInvariantError(
                "accepted turn must emit one terminal end event"
            )
    elif trace.state_save_count != 0:
        raise ProductionPathInvariantError(
            "rejected turn must not save conversation state"
        )
    elif trace.state_save_completed_count != 0:
        raise ProductionPathInvariantError(
            "rejected turn must not complete a conversation state save"
        )
    if trace.expected_state_edge != trace.observed_state_edge:
        raise ProductionPathInvariantError(
            "observed state edge does not match expected state edge"
        )
    if trace.accepted and trace.observed_layers != _RUNTIME_LAYER_ORDER:
        raise ProductionPathInvariantError(
            "accepted turn must expose all observed runtime layers"
        )


def validate_case_trace_bindings(
    *,
    cases: Sequence[ProductionPathCase],
    traces: Sequence[ProductionPathTurnTrace],
) -> None:
    if len(cases) != len(traces):
        raise ProductionPathInvariantError(
            "production cases and traces must have equal length"
        )
    for index, (case, trace) in enumerate(
        zip(cases, traces, strict=True)
    ):
        validate_production_path_trace(trace)
        if (
            trace.turn_id != case.case_id
            or trace.trajectory_id != case.trajectory_id
            or trace.partition != case.partition
            or trace.bounded is not case.bounded
            or trace.expected_state_edge != case.expected_state_edge
        ):
            raise ProductionPathInvariantError(
                f"production trace {index} identity disagrees with its case"
            )
        if trace.selected_processor != trace.actual_processor:
            raise ProductionPathInvariantError(
                f"production trace {index} processor identity is inconsistent"
            )
        if (
            case.expected_processor is not None
            and trace.actual_processor != case.expected_processor
        ):
            raise ProductionPathInvariantError(
                f"production trace {index} processor disagrees with its case"
            )
        if (
            case.expected_intent is not None
            and trace.actual_intent != case.expected_intent
        ):
            raise ProductionPathInvariantError(
                f"production trace {index} intent disagrees with its case"
            )
        if (
            case.expected_card_ids is not None
            and trace.card_ids != case.expected_card_ids
        ):
            raise ProductionPathInvariantError(
                f"production trace {index} cards disagree with its case"
            )
        expected_coverage = (
            case.expected_coverage.edge_ids()
            if case.expected_coverage is not None
            else None
        )
        if (
            expected_coverage is not None
            and trace.coverage_edges != expected_coverage
        ):
            raise ProductionPathInvariantError(
                f"production trace {index} coverage disagrees with its case"
            )
        if not set(case.required_state_edges).issubset(
            trace.coverage_edges
        ):
            raise ProductionPathInvariantError(
                f"production trace {index} misses required case coverage"
            )


def validate_state_edge_coverage(
    traces: Sequence[ProductionPathTurnTrace],
    *,
    required_state_edges: Sequence[str],
) -> None:
    required = tuple(required_state_edges)
    if not required or len(required) != len(set(required)):
        raise ValueError(
            "required state edges must be nonempty and unique"
        )
    for trace in traces:
        validate_production_path_trace(trace)
    observed = {
        edge
        for trace in traces
        if trace.partition in {"state", "bounded"}
        for edge in trace.coverage_edges
    }
    missing = tuple(
        edge for edge in required if edge not in observed
    )
    if missing:
        raise ProductionPathInvariantError(
            "missing required state edges: " + ", ".join(missing)
        )


def validate_bounded_turns(
    traces: Sequence[ProductionPathTurnTrace],
) -> None:
    bounded = tuple(trace for trace in traces if trace.bounded)
    if len(bounded) != 9:
        raise ProductionPathInvariantError(
            "bounded partition must contain exactly nine turns"
        )
    turn_ids = tuple(trace.turn_id for trace in bounded)
    if len(turn_ids) != len(set(turn_ids)):
        raise ProductionPathInvariantError(
            "bounded turn IDs must be unique"
        )
    for trace in bounded:
        if trace.partition != "bounded":
            raise ProductionPathInvariantError(
                "bounded turns must use the bounded partition"
            )
        validate_production_path_trace(trace)


def run_production_path_matrix(
    *,
    repo_root: str | Path,
    cases_path: str | Path,
    state_root: str | Path,
    candidate_manifest_sha256: str,
    protected_payload_sha256: str,
    cases_sha256: str,
) -> ProductionPathSummary:
    cases = load_production_path_cases(cases_path)
    with ZeroApiNetworkGuard() as guard:
        runtime = Task11ProductionPathRuntime(
            repo_root=repo_root,
            state_root=state_root,
            network_guard=guard,
        )
        traces = tuple(runtime.execute(case) for case in cases)
    validate_case_trace_bindings(cases=cases, traces=traces)
    required_state_edges = tuple(sorted({
        edge
        for case in cases
        if case.partition in {"state", "bounded"}
        for edge in case.required_state_edges
    }))
    validate_state_edge_coverage(
        traces,
        required_state_edges=required_state_edges,
    )
    validate_bounded_turns(traces)
    summary = summarize_production_path(
        traces,
        required_state_edges=required_state_edges,
        candidate_manifest_sha256=candidate_manifest_sha256,
        protected_payload_sha256=protected_payload_sha256,
        cases_sha256=cases_sha256,
    )
    if not summary.passed:
        raise ProductionPathInvariantError(
            "Task 11 production path summary did not pass"
        )
    return summary


def _verify_candidate_manifest(
    *,
    repo_root: Path,
    manifest_path: Path,
    cases_path: Path,
    expected_manifest_sha256: str,
) -> tuple[str, str, str]:
    from tools.guide_gates.build_task11_readiness import (
        Task11ReadinessError,
        _validated_manifest,
        canonical_payload_sha256,
    )

    if manifest_path.is_symlink():
        raise ProductionPathInvariantError(
            "candidate manifest path is a symlink"
        )
    try:
        manifest, manifest_root = _validated_manifest(
            manifest_path,
            expected_manifest_sha256=expected_manifest_sha256,
        )
    except Task11ReadinessError as exc:
        raise ProductionPathInvariantError(str(exc)) from exc
    if manifest_root != repo_root:
        raise ProductionPathInvariantError(
            "candidate repository root mismatch"
        )
    protected = manifest.get("protected_paths")
    if (
        manifest.get("schema_version")
        != "guide-task11-candidate-manifest-v1"
        or not isinstance(protected, list)
        or not protected
        or len(protected) != len(set(protected))
    ):
        raise ProductionPathInvariantError(
            "candidate manifest is invalid"
        )
    manifest_sha256 = expected_manifest_sha256
    try:
        cases_relative = cases_path.resolve().relative_to(
            repo_root
        ).as_posix()
    except ValueError as exc:
        raise ProductionPathInvariantError(
            "production matrix fixture escapes repository"
        ) from exc
    required = {
        cases_relative,
        "tools/guide_gates/run_task11_production_path_matrix.py",
    }
    if not required.issubset(set(protected)):
        raise ProductionPathInvariantError(
            "candidate manifest does not protect production matrix inputs"
        )
    current = canonical_payload_sha256(repo_root, protected)
    if (
        manifest.get("candidate_payload_sha256") != current
        or manifest.get("protected_payload_sha256") != current
    ):
        raise ProductionPathInvariantError(
            "candidate manifest protected payload drift"
        )
    return (
        manifest_sha256,
        current,
        sha256(cases_path.read_bytes()).hexdigest(),
    )


def _write_summary_exclusive(
    output_path: Path,
    summary: ProductionPathSummary,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        summary.model_dump_json(indent=2)
        + "\n"
    ).encode("utf-8")
    descriptor = os.open(
        output_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    with os.fdopen(descriptor, "wb", closefd=True) as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(output_path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the Task 11 HTTP production-path matrix.",
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument(
        "--expected-manifest-sha256",
        required=True,
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_CASES_PATH,
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
    )
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    output = args.output.resolve()
    if output.exists() or output.is_symlink():
        raise FileExistsError(
            f"production path summary already exists: {output}"
        )
    (
        candidate_manifest_sha256,
        protected_payload_sha256,
        cases_sha256,
    ) = _verify_candidate_manifest(
        repo_root=root,
        manifest_path=args.manifest.absolute(),
        cases_path=args.cases.resolve(),
        expected_manifest_sha256=args.expected_manifest_sha256,
    )
    with TemporaryDirectory(
        prefix="xiaoro-task11-production-path-"
    ) as directory:
        summary = run_production_path_matrix(
            repo_root=root,
            cases_path=args.cases,
            state_root=Path(directory) / "state",
            candidate_manifest_sha256=candidate_manifest_sha256,
            protected_payload_sha256=protected_payload_sha256,
            cases_sha256=cases_sha256,
        )
    _write_summary_exclusive(output, summary)
    print(summary.model_dump_json())
    return 0


__all__ = [
    "DEFAULT_CASES_PATH",
    "ProductionPathCase",
    "ProductionPathInvariantError",
    "ProductionPathSummary",
    "ProductionPathTurnTrace",
    "Task11ProductionPathRuntime",
    "load_production_path_cases",
    "run_production_path_matrix",
    "summarize_production_path",
    "validate_bounded_turns",
    "validate_production_path_trace",
    "validate_state_edge_coverage",
]


if __name__ == "__main__":
    raise SystemExit(main())
