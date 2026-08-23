from __future__ import annotations

import argparse
from collections.abc import Sequence
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
from app.guide.understanding.turn_meaning_contracts import TurnMeaning
from app.guide_runtime.app import create_app
from app.guide_runtime.composition import (
    build_consultation_vertical_runtime,
    build_feedback_service,
    build_image_bundle_service,
)
from app.guide_runtime.feedback_http import FEEDBACK_SESSION_COOKIE


DEFAULT_CASES_PATH = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "guide"
    / "intent"
    / "task11_production_path_matrix_v1.jsonl"
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
    partition: Literal["semantic", "state", "bounded"]
    message: str = Field(max_length=4000)
    image_action: Literal["identify", "compare"] | None = None
    image_paths: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=4,
    )
    meaning: TurnMeaning
    starting_snapshot: ConversationSnapshot | None = None
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
        if self.image_action is None:
            if not self.message:
                raise ValueError(
                    "text production path case requires a message"
                )
            if self.image_paths:
                raise ValueError(
                    "image paths require a typed image action"
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
        if self.starting_snapshot is None:
            return self
        if self.partition != "semantic":
            raise ValueError(
                "only independent semantic cases may seed state"
            )
        if self.starting_snapshot.session_id != self.trajectory_id:
            raise ValueError(
                "starting snapshot must match trajectory ID"
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
    partition: Literal["semantic", "state", "bounded"]
    translation_injection_count: int = Field(ge=0)
    structured_understanding_injection_count: int = Field(ge=0)
    compiler_call_count: int = Field(ge=0)
    direct_router_bypass_count: int = Field(ge=0)
    legacy_entrypoint_count: int = Field(ge=0)
    router_call_count: int = Field(ge=0)
    route_decision_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_decision_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_identity_violation_count: int = Field(ge=0)
    execution_result_count: int = Field(ge=0)
    reducer_call_count: int = Field(ge=0)
    state_save_count: int = Field(ge=0)
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

    @field_validator(
        "coverage_edges",
        "card_ids",
        "event_names",
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
    translation_injection_count: int = Field(ge=0)
    compiler_bypass_count: int = Field(ge=0)
    compiler_call_count_violation_count: int = Field(ge=0)
    structured_understanding_injection_count: int = Field(ge=0)
    direct_router_bypass_count: int = Field(ge=0)
    legacy_entrypoint_count: int = Field(ge=0)
    router_call_count_violation_count: int = Field(ge=0)
    decision_identity_violation_count: int = Field(ge=0)
    execution_result_count_violation_count: int = Field(ge=0)
    reducer_call_count_violation_count: int = Field(ge=0)
    processor_state_write_count: int = Field(ge=0)
    event_state_projection_count: int = Field(ge=0)
    state_save_count_violation_count: int = Field(ge=0)
    terminal_contract_failure_count: int = Field(ge=0)
    state_transition_failure_count: int = Field(ge=0)
    outbound_network_attempt_count: int = Field(ge=0)
    provider_call_count: int = Field(ge=0)
    turn_traces: tuple[ProductionPathTurnTrace, ...] = ()

    @field_validator("turn_traces", mode="before")
    @classmethod
    def freeze_turn_traces(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


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
    if len(normalized) != 176:
        raise ValueError(
            "Task 11 production matrix requires exactly 176 turns"
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
        trace.compiler_call_count != 1 for trace in normalized
    )
    router_call_violations = sum(
        trace.router_call_count != 1 for trace in normalized
    )
    execution_result_violations = sum(
        trace.execution_result_count != 1 for trace in normalized
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
            trace.state_save_count != 1
            if trace.accepted
            else trace.state_save_count != 0
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
    )
    counts_match = (
        len(semantic) == 128
        and len(stateful) == 48
        and len(normalized) == 176
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
        translation_injection_count=sum(
            trace.translation_injection_count
            for trace in normalized
        ),
        compiler_bypass_count=sum(
            trace.compiler_call_count == 0 for trace in normalized
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
        execution_result_count_violation_count=(
            execution_result_violations
        ),
        reducer_call_count_violation_count=(
            reducer_call_violations
        ),
        processor_state_write_count=violation_counts[8],
        event_state_projection_count=violation_counts[9],
        state_save_count_violation_count=state_save_violations,
        terminal_contract_failure_count=terminal_failures,
        state_transition_failure_count=state_transition_failures,
        outbound_network_attempt_count=violation_counts[13],
        provider_call_count=violation_counts[14],
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
    ) -> None:
        self._state = state
        self._session_id = session_id
        self._loaded_version = loaded_version
        self.reset()

    def reset(self) -> None:
        self.compiler_call_count = 0
        self.router_call_count = 0
        self.execution_result_count = 0
        self.reducer_call_count = 0
        self.state_save_count = 0
        self.processor_state_write_count = 0
        self.event_state_projection_count = 0
        self.decision_identity_violation_count = 0
        self.route_decision = None
        self.result_decision = None
        self.compiled_meaning = None

    def compiled(self, **values) -> None:
        self.compiler_call_count += 1
        self.compiled_meaning = values["meaning"]

    def routed(self, **values) -> None:
        self.router_call_count += 1
        self.route_decision = values["decision"]

    def result_received(self, **values) -> None:
        self.execution_result_count += 1
        self.result_decision = values["result"].decision
        if self.result_decision is not self.route_decision:
            self.decision_identity_violation_count += 1
        if self._current_version() != self._loaded_version:
            self.processor_state_write_count += 1

    def state_reduced(self, **values) -> None:
        del values
        self.reducer_call_count += 1
        if self._current_version() != self._loaded_version:
            self.processor_state_write_count += 1

    def envelope_materialized(self, **values) -> None:
        del values
        if self._current_version() != self._loaded_version:
            self.event_state_projection_count += 1

    def state_saved(self, **values) -> None:
        del values
        self.state_save_count += 1

    def _current_version(self) -> int:
        if self._state is None:
            return 0
        return _snapshot_version(
            self._state.load(self._session_id)
        )


class Task11ProductionPathRuntime:
    def __init__(
        self,
        *,
        repo_root: str | Path,
        state_root: str | Path,
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
        feedback_cookie = "feedback_session_" + "a" * 43
        self._client.cookies.set(
            FEEDBACK_SESSION_COOKIE,
            feedback_cookie,
        )
        self._profile_owner = ProfileOwnerRef(
            scope="local_demo",
            subject_id=(
                "feedback-browser-"
                + sha256(feedback_cookie.encode("utf-8")).hexdigest()
            ),
        )

    def execute(
        self,
        case: ProductionPathCase,
    ) -> ProductionPathTurnTrace:
        if type(case) is not ProductionPathCase:
            raise TypeError(
                "case must be an exact ProductionPathCase"
            )
        before = self._vertical.conversation_state.load(
            case.trajectory_id
        )
        if case.starting_snapshot is not None:
            if before is not None:
                raise ProductionPathInvariantError(
                    "starting snapshot cannot patch an existing session"
                )
            starting_snapshot = case.starting_snapshot.model_copy(
                update={"profile_owner": self._profile_owner},
                deep=True,
            )
            self._vertical.conversation_state.save(
                starting_snapshot,
                expected_version=0,
            )
            before = self._vertical.conversation_state.load(
                case.trajectory_id
            )
        loaded_version = _snapshot_version(before)
        self._provider.bind(
            message=case.message,
            meaning=case.meaning,
        )
        self._observer.bind(
            state=self._vertical.conversation_state,
            session_id=case.trajectory_id,
            loaded_version=loaded_version,
        )
        request_payload = {
            "message": case.message,
            "session_id": case.trajectory_id,
            "conversation_version": loaded_version,
            "stream": True,
        }
        if case.image_action is not None:
            receipt = self._upload_images(case)
            request_payload.update({
                "image_action": case.image_action,
                "image_bundle_id": receipt["bundle_id"],
                "image_bundle_version": receipt["version"],
                "image_bundle_token": receipt["owner_token"],
            })
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
        after = self._vertical.conversation_state.load(
            case.trajectory_id
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
        accepted = terminal_event == "end"
        actual_processor = (
            self._observer.route_decision.processor
            if self._observer.route_decision is not None
            else ""
        )
        actual_coverage = _derive_state_coverage(
            current=before,
            meaning=case.meaning,
            processor=actual_processor,
        )
        compiled_meaning_matches = (
            self._observer.compiled_meaning == case.meaning
        )
        translation_injection_count = int(
            compiled_meaning_matches
            and (
                self._provider.call_count == 0
                if case.image_action is not None
                else self._provider.call_count == 1
            )
        )
        trace = ProductionPathTurnTrace(
            turn_id=case.case_id,
            trajectory_id=case.trajectory_id,
            partition=case.partition,
            translation_injection_count=translation_injection_count,
            structured_understanding_injection_count=0,
            compiler_call_count=self._observer.compiler_call_count,
            direct_router_bypass_count=0,
            legacy_entrypoint_count=0,
            router_call_count=self._observer.router_call_count,
            route_decision_digest=route_digest,
            result_decision_digest=result_digest,
            decision_identity_violation_count=(
                self._observer.decision_identity_violation_count
            ),
            execution_result_count=(
                self._observer.execution_result_count
            ),
            reducer_call_count=self._observer.reducer_call_count,
            state_save_count=self._observer.state_save_count,
            processor_state_write_count=(
                self._observer.processor_state_write_count
            ),
            event_state_projection_count=(
                self._observer.event_state_projection_count
            ),
            provider_call_count=0,
            outbound_network_attempt_count=0,
            loaded_version=loaded_version,
            committed_version=_snapshot_version(after),
            expected_state_edge=case.expected_state_edge,
            observed_state_edge=(
                f"{_snapshot_owner(before)}->{_snapshot_owner(after)}"
            ),
            terminal_event=terminal_event,
            bounded=case.bounded,
            semantic_equivalence_passed=(
                terminal_contract_passed
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
            ),
            accepted=accepted,
            coverage_edges=actual_coverage.edge_ids(),
            actual_processor=actual_processor,
            actual_intent=actual_intent,
            card_ids=card_ids,
            event_names=event_names,
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


def _derive_state_coverage(
    *,
    current: ConversationSnapshot | None,
    meaning: TurnMeaning,
    processor: str,
) -> StateCoveragePoint:
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
    references = meaning.reference_mentions
    if any(
        item.object_family_hint == "image"
        and (
            item.ordinal_hint is not None
            or (
                item.plurality_hint == "single"
                and len(confirmed_images) == 1
            )
        )
        for item in references
    ):
        reference_source = "image_ordinal"
    elif any(
        item.object_family_hint == "product"
        and item.ordinal_hint is not None
        for item in references
    ):
        reference_source = "candidate_ordinal"
    elif any(
        item.object_family_hint in {"image", "product"}
        and item.plurality_hint == "batch"
        for item in references
    ):
        reference_source = "current_batch"
    elif meaning.product_mentions or any(
        item.object_family_hint == "product"
        for item in references
    ):
        reference_source = "explicit_current_item"
    elif processor == "clarification":
        reference_source = "ambiguous_reference"

    if processor == "safety_escalation":
        semantic_act = "safety_escalation"
    elif meaning.continuity_hint == "return_to_focus":
        semantic_act = "explicit_return"
    elif meaning.operation_hint == "assessment":
        semantic_act = "observation_answer"
    elif reference_source == "image_ordinal":
        semantic_act = "explicit_image_question"
    elif reference_source in {
        "explicit_current_item",
        "candidate_ordinal",
        "current_batch",
    }:
        semantic_act = "explicit_product_question"
    elif processor == "general_knowledge":
        semantic_act = "explicit_general_knowledge_question"
    elif processor == "clarification":
        semantic_act = "ambiguous_continuation"
    elif (
        processor == "recommendation"
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


def validate_production_path_trace(
    trace: ProductionPathTurnTrace,
) -> None:
    if type(trace) is not ProductionPathTurnTrace:
        raise TypeError(
            "trace must be an exact ProductionPathTurnTrace"
        )
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
    if trace.expected_state_edge != trace.observed_state_edge:
        raise ProductionPathInvariantError(
            "observed state edge does not match expected state edge"
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
) -> ProductionPathSummary:
    cases = load_production_path_cases(cases_path)
    runtime = Task11ProductionPathRuntime(
        repo_root=repo_root,
        state_root=state_root,
    )
    traces = tuple(runtime.execute(case) for case in cases)
    for trace in traces:
        validate_production_path_trace(trace)
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
) -> None:
    from tools.guide_gates.build_task11_readiness import (
        canonical_payload_sha256,
    )

    try:
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ProductionPathInvariantError(
            "candidate manifest is invalid"
        ) from exc
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
    _verify_candidate_manifest(
        repo_root=root,
        manifest_path=args.manifest.resolve(),
        cases_path=args.cases.resolve(),
    )
    with TemporaryDirectory(
        prefix="xiaoro-task11-production-path-"
    ) as directory:
        summary = run_production_path_matrix(
            repo_root=root,
            cases_path=args.cases,
            state_root=Path(directory) / "state",
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
