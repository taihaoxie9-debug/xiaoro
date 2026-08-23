#!/usr/bin/env python3
"""Replay captured final translations through the real Guide HTTP backend."""

from __future__ import annotations

import argparse
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.presentation.public_contracts import (
    PublicPresentationContract,
)
from app.guide.presentation.public_language import (
    PublicLanguageError,
    validate_public_text,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning
from app.guide_runtime.app import create_app
from app.guide_runtime.composition import (
    build_consultation_vertical_runtime,
    build_image_bundle_service,
)
from tools.guide_gates.attempt_ledger import (
    AttemptLedgerError,
    read_attempt_context,
    read_ledger,
)
from tools.guide_gates.run_final_real_translation import (
    FINAL_TRANSLATION_CASE_COUNT,
    FINAL_TRANSLATION_TURN_COUNT,
    FinalTranslationTrajectory,
    FinalTranslationTurn,
    load_final_translation_trajectories,
)
from tools.guide_gates.zero_api_network_guard import ZeroApiNetworkGuard


REPORT_SCHEMA = "guide-final-real-backend-summary-v1"
_TRANSLATION_DIRECTORY = "real-translation"
_BACKEND_DIRECTORY = "real-backend"
_FORBIDDEN_SEMANTIC_KEYS = frozenset(
    {
        "budget_candidates",
        "constraint_changes",
        "consultation_hypothesis",
        "continuity_hint",
        "next_observation_gap",
        "observation_candidates",
        "operation_hint",
        "pending_response_hint",
        "preference_candidates",
        "product_mentions",
        "question_meaning",
        "recommendation_mode_basis",
        "reference_mentions",
        "relative_candidates",
        "safety_language",
        "source_span",
        "subject_scope_hint",
        "topic_hint",
    }
)
_BOUND_PRODUCT_RESPONSIBILITIES = frozenset(
    {
        Responsibility.COMPARISON.value,
        Responsibility.SINGLE_PRODUCT_SUITABILITY.value,
        Responsibility.PRODUCT_KNOWLEDGE.value,
        Responsibility.IMAGE_IDENTITY.value,
    }
)
_PROVIDER_KEY_NAMES = (
    "GUIDE_LLM_API_KEY",
    "GUIDE_COPY_LLM_API_KEY",
)
_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CASES = (
    _ROOT
    / "tests"
    / "fixtures"
    / "guide"
    / "final_release"
    / "real_translation_12x4_v5.jsonl"
)


class BackendReplayError(ValueError):
    pass


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )


class CapturedMeaning(_StrictFrozen):
    trajectory_id: str = Field(min_length=1, max_length=160)
    turn_id: str = Field(min_length=1, max_length=180)
    case_id: str = Field(min_length=1, max_length=180)
    meaning: TurnMeaning
    expected_responsibility: str = Field(min_length=1, max_length=80)


class BackendReplayTurnTrace(_StrictFrozen):
    trajectory_id: str
    turn_id: str
    completed: bool
    clarification: bool
    translation_injection_count: int = Field(ge=0)
    provider_call_count: int = Field(ge=0)
    copywriter_call_count: int = Field(ge=0)
    presentation_contract_count: int = Field(ge=0)
    message_event_count: int = Field(ge=0)
    wrong_responsibility_count: int = Field(ge=0)
    wrong_binding_count: int = Field(ge=0)
    wrong_product_count: int = Field(ge=0)
    price_specification_mismatch_count: int = Field(ge=0)
    section_order_violation_count: int = Field(ge=0)
    raw_ad_leak_count: int = Field(ge=0)
    internal_language_count: int = Field(ge=0)
    unsafe_downgrade_count: int = Field(ge=0)
    frontend_contract_violation_count: int = Field(ge=0)
    expected_responsibility: str
    actual_responsibility: str | None
    visible_product_ids: tuple[int, ...] = ()
    event_names: tuple[str, ...] = ()
    passed: bool


class BackendReplayReport(_StrictFrozen):
    schema_version: Literal[
        "guide-final-real-backend-summary-v1"
    ] = REPORT_SCHEMA
    passed: bool
    trajectory_count: int = Field(ge=0)
    critical_trajectory_count: int = Field(ge=0)
    critical_trajectory_passed: int = Field(ge=0)
    expected_turn_count: int = Field(ge=0)
    turn_count: int = Field(ge=0)
    completed_turn_count: int = Field(ge=0)
    passed_turn_count: int = Field(ge=0)
    non_clarification_turn_count: int = Field(ge=0)
    clarification_turn_count: int = Field(ge=0)
    translation_injection_count: int = Field(ge=0)
    provider_call_count: int = Field(ge=0)
    copywriter_call_count: int = Field(ge=0)
    presentation_contract_count: int = Field(ge=0)
    message_event_count: int = Field(ge=0)
    wrong_responsibility_count: int = Field(ge=0)
    wrong_binding_count: int = Field(ge=0)
    wrong_product_count: int = Field(ge=0)
    wrong_presentation_count: int = Field(ge=0)
    price_specification_mismatch_count: int = Field(ge=0)
    section_order_violation_count: int = Field(ge=0)
    raw_ad_leak_count: int = Field(ge=0)
    internal_language_count: int = Field(ge=0)
    internal_public_language_count: int = Field(ge=0)
    unsafe_downgrade_count: int = Field(ge=0)
    frontend_contract_violation_count: int = Field(ge=0)
    outbound_network_attempt_count: int = Field(ge=0)
    serious_failure_count: int = Field(ge=0)
    results_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    turn_traces: tuple[BackendReplayTurnTrace, ...] = ()


class _CapturedMeaningPort:
    def __init__(self) -> None:
        self._message: str | None = None
        self._meaning: TurnMeaning | None = None
        self.injection_count = 0

    def bind(self, *, message: str, meaning: TurnMeaning) -> None:
        self._message = message
        self._meaning = meaning

    def propose(self, message, context) -> TurnMeaning:
        del context
        if message != self._message or self._meaning is None:
            raise BackendReplayError(
                "captured TurnMeaning binding mismatch"
            )
        self.injection_count += 1
        return self._meaning.model_copy(deep=True)


class _ReplayObserver:
    def reset(self) -> None:
        self.meaning: TurnMeaning | None = None
        self.decision = None
        self.result = None

    def __init__(self) -> None:
        self.reset()

    def compiled(self, **values: object) -> None:
        meaning = values.get("meaning")
        self.meaning = (
            meaning if type(meaning) is TurnMeaning else None
        )

    def routed(self, **values: object) -> None:
        self.decision = values.get("decision")

    def result_received(self, **values: object) -> None:
        self.result = values.get("result")


def replay_final_real_backend(
    *,
    cases_path: str | Path,
    attempt_context_path: str | Path,
    phase: str = "backend",
    repo_root: str | Path = _ROOT,
) -> BackendReplayReport:
    if phase != "backend":
        raise BackendReplayError("backend replay requires phase=backend")
    root = Path(repo_root).resolve()
    if not root.is_dir():
        raise BackendReplayError("repo_root must be a directory")
    trajectories = load_final_translation_trajectories(cases_path)
    context, translation_dir, output_dir = _resolve_attempt_paths(
        attempt_context_path
    )
    captures = _load_captured_meanings(
        trajectories=trajectories,
        translation_dir=translation_dir,
    )
    context_before = Path(attempt_context_path).read_bytes()
    if output_dir.exists() or output_dir.is_symlink():
        raise BackendReplayError(
            "real backend output directory already exists"
        )

    with TemporaryDirectory(
        prefix="xiaoro-final-backend-replay-"
    ) as temporary:
        with _provider_keys_disabled():
            traces, network_attempts = _run_http_replay(
                repo_root=root,
                state_root=Path(temporary),
                trajectories=trajectories,
                captures=captures,
            )
    if Path(attempt_context_path).read_bytes() != context_before:
        raise BackendReplayError("immutable attempt context changed")
    report = _summarize(
        trajectories=trajectories,
        traces=traces,
        outbound_network_attempt_count=network_attempts,
    )
    _write_report(output_dir=output_dir, report=report)
    del context
    return report


def _resolve_attempt_paths(
    attempt_context_path: str | Path,
) -> tuple[dict[str, Any], Path, Path]:
    context_path = Path(attempt_context_path).resolve()
    try:
        raw_context = _read_json_object(
            context_path,
            label="attempt context",
        )
        ledger_path = Path(str(raw_context["ledger_path"])).resolve()
        readiness_path = Path(
            str(raw_context["readiness_path"])
        ).resolve()
        context = read_attempt_context(
            context_path,
            ledger_path=ledger_path,
            readiness_path=readiness_path,
        )
        if (
            not readiness_path.is_file()
            or sha256(readiness_path.read_bytes()).hexdigest()
            != context.get("readiness_sha256")
        ):
            raise BackendReplayError(
                "attempt context readiness hash mismatch"
            )
        phase_attempt_ids = context.get("phase_attempt_ids")
        if (
            not isinstance(phase_attempt_ids, dict)
            or next(reversed(phase_attempt_ids), None) != "translation"
        ):
            raise BackendReplayError(
                "attempt context must end at translation phase"
            )
        translation_attempt_id = phase_attempt_ids["translation"]
        ledger = read_ledger(ledger_path)
        attempts = [
            item
            for item in ledger["attempts"]
            if isinstance(item, dict)
            and item.get("attempt_id") == translation_attempt_id
        ]
        if (
            len(attempts) != 1
            or attempts[0].get("trajectory_set") != "translation"
            or attempts[0].get("result") != "passed"
        ):
            raise BackendReplayError(
                "attempt context translation result is not passed"
            )
        attempt_root = Path(
            str(context["output_directory"])
        ).resolve()
        if (
            attempt_root != context_path.parent
            or Path(
                str(attempts[0].get("evidence_directory"))
            ).resolve()
            != attempt_root
        ):
            raise BackendReplayError(
                "attempt context output directory mismatch"
            )
    except (
        AttemptLedgerError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
    ) as error:
        if isinstance(error, BackendReplayError):
            raise
        raise BackendReplayError(
            f"attempt context is invalid: {error}"
        ) from error
    return (
        context,
        attempt_root / _TRANSLATION_DIRECTORY,
        attempt_root / _BACKEND_DIRECTORY,
    )


def _load_captured_meanings(
    *,
    trajectories: Sequence[FinalTranslationTrajectory],
    translation_dir: Path,
) -> tuple[CapturedMeaning, ...]:
    results_path = translation_dir / "results.jsonl"
    summary_path = translation_dir / "summary.json"
    checksums_path = translation_dir / "SHA256SUMS"
    try:
        results_bytes = results_path.read_bytes()
        summary_bytes = summary_path.read_bytes()
        summary = json.loads(summary_bytes)
        checksums = _read_checksums(checksums_path)
    except (OSError, json.JSONDecodeError) as error:
        raise BackendReplayError(
            "translation capture is invalid"
        ) from error
    results_hash = sha256(results_bytes).hexdigest()
    summary_hash = sha256(summary_bytes).hexdigest()
    if (
        checksums.get("results.jsonl") != results_hash
        or checksums.get("summary.json") != summary_hash
        or summary.get("results_sha256") != results_hash
    ):
        raise BackendReplayError("translation capture hash mismatch")
    try:
        raw_rows = [
            json.loads(line)
            for line in results_bytes.decode("utf-8").splitlines()
            if line.strip()
        ]
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BackendReplayError(
            "translation results are invalid"
        ) from error
    if len(raw_rows) != FINAL_TRANSLATION_TURN_COUNT:
        raise BackendReplayError(
            "backend replay requires exactly 48 captured meanings"
        )

    required_summary_counts = (
        "turn_count",
        "passed_turn_count",
        "schema_valid_count",
        "translation_passed_count",
        "source_grounded_count",
        "binding_passed_count",
        "task_plan_passed_count",
        "recommendation_mode_passed_count",
    )
    if (
        summary.get("schema_version")
        != "guide-final-real-translation-summary-v1"
        or summary.get("passed") is not True
        or summary.get("expected_turn_count")
        != FINAL_TRANSLATION_TURN_COUNT
        or any(
            summary.get(field) != FINAL_TRANSLATION_TURN_COUNT
            for field in required_summary_counts
        )
        or summary.get("provider_call_count")
        != FINAL_TRANSLATION_TURN_COUNT
        or summary.get("stopped_early") is not False
        or any(
            int(summary.get(field, 0)) != 0
            for field in (
                "wrong_binding_count",
                "wrong_product_or_image_binding_count",
                "unsafe_downgrade_count",
                "internal_language_count",
                "internal_public_language_count",
                "serious_failure_count",
            )
        )
    ):
        raise BackendReplayError(
            "translation summary must prove all 48 captured meanings"
        )

    expected_turns = tuple(
        turn
        for trajectory in trajectories
        for turn in trajectory.turns
    )
    captures: list[CapturedMeaning] = []
    for source, turn in zip(raw_rows, expected_turns, strict=True):
        if not isinstance(source, dict):
            raise BackendReplayError(
                "translation result row must be an object"
            )
        identity = (
            source.get("trajectory_id"),
            source.get("turn_id"),
            source.get("case_id"),
        )
        if identity != (
            turn.trajectory_id,
            turn.turn_id,
            turn.case.case_id,
        ):
            raise BackendReplayError(
                "translation capture does not match sealed cases"
            )
        if any(
            source.get(field) is not True
            for field in (
                "schema_valid",
                "translation_passed",
                "source_grounded",
                "binding_passed",
                "task_plan_passed",
                "recommendation_mode_passed",
                "passed",
            )
        ) or source.get("status") != "ok":
            raise BackendReplayError(
                "translation capture contains a failed row"
            )
        payload = source.get("provider_output")
        if (
            not isinstance(payload, dict)
            or source.get("provider_output_sha256")
            != _hash_json(payload)
        ):
            raise BackendReplayError(
                "captured TurnMeaning hash mismatch"
            )
        try:
            meaning = TurnMeaning.model_validate(payload, strict=True)
        except ValidationError as error:
            raise BackendReplayError(
                "captured TurnMeaning is invalid"
            ) from error
        captures.append(
            CapturedMeaning(
                trajectory_id=turn.trajectory_id,
                turn_id=turn.turn_id,
                case_id=turn.case.case_id,
                meaning=meaning,
                expected_responsibility=(
                    _expected_responsibility(source, turn)
                ),
            )
        )
    identities = tuple(
        (item.trajectory_id, item.turn_id) for item in captures
    )
    if len(set(identities)) != FINAL_TRANSLATION_TURN_COUNT:
        raise BackendReplayError(
            "captured TurnMeaning identities must be unique"
        )
    return tuple(captures)


def _expected_responsibility(
    source: Mapping[str, object],
    turn: FinalTranslationTurn,
) -> str:
    captured = source.get("responsibility")
    if captured in {item.value for item in Responsibility}:
        return str(captured)
    task_mode = (
        captured
        if isinstance(captured, str) and captured
        else turn.case.execution.expected_task_mode
    )
    if task_mode == "recommend":
        return Responsibility.RECOMMENDATION.value
    if task_mode == "comparison":
        return Responsibility.COMPARISON.value
    if task_mode == "suitability":
        return Responsibility.SINGLE_PRODUCT_SUITABILITY.value
    if task_mode == "followup":
        return Responsibility.PRODUCT_KNOWLEDGE.value
    if task_mode == "knowledge":
        return (
            Responsibility.PRODUCT_KNOWLEDGE.value
            if turn.case.binding.expected_objects
            else Responsibility.GENERAL_KNOWLEDGE.value
        )
    if task_mode == "clarify":
        return Responsibility.CLARIFICATION.value
    if turn.required_safety_language == "safety":
        return Responsibility.SAFETY_ESCALATION.value
    if turn.case.family == "consultation":
        return Responsibility.CONSULTATION.value
    if turn.case.family == "image":
        return Responsibility.IMAGE_IDENTITY.value
    raise BackendReplayError(
        f"captured responsibility is unavailable for {turn.turn_id}"
    )


def _run_http_replay(
    *,
    repo_root: Path,
    state_root: Path,
    trajectories: Sequence[FinalTranslationTrajectory],
    captures: Sequence[CapturedMeaning],
) -> tuple[tuple[BackendReplayTurnTrace, ...], int]:
    provider = _CapturedMeaningPort()
    observer = _ReplayObserver()
    image_bundles = build_image_bundle_service(
        database_path=state_root / "image_bundles.sqlite3"
    )
    runtime = build_consultation_vertical_runtime(
        repo_root=repo_root,
        state_dir=state_root,
        semantic_intent=provider,
        execution_observer=observer,
        image_bundle_service=image_bundles,
    )
    if getattr(runtime.presentation_compiler, "_copywriter", object()) is not None:
        raise BackendReplayError("backend replay requires copywriter off")
    client = TestClient(
        create_app(
            consultation_runtime=runtime,
            image_bundle_service=image_bundles,
            repo_root=repo_root,
        )
    )
    turns = tuple(
        turn
        for trajectory in trajectories
        for turn in trajectory.turns
    )
    traces: list[BackendReplayTurnTrace] = []
    with ZeroApiNetworkGuard() as network_guard:
        for turn, capture in zip(turns, captures, strict=True):
            provider.bind(
                message=turn.case.message,
                meaning=capture.meaning,
            )
            observer.reset()
            before_injections = provider.injection_count
            response = client.post(
                "/api/v1/chat/stream",
                json={
                    "message": turn.case.message,
                    "session_id": turn.trajectory_id,
                    "conversation_version": _conversation_version(
                        runtime,
                        turn.trajectory_id,
                    ),
                    "stream": True,
                },
            )
            trace = _evaluate_http_turn(
                turn=turn,
                capture=capture,
                status_code=response.status_code,
                payload=response.content,
                injected_meaning=observer.meaning,
                decision=observer.decision,
                result=observer.result,
                translation_injection_count=(
                    provider.injection_count - before_injections
                ),
            )
            traces.append(trace)
    return (
        tuple(traces),
        network_guard.outbound_network_attempt_count,
    )


def _evaluate_http_turn(
    *,
    turn: FinalTranslationTurn,
    capture: CapturedMeaning,
    status_code: int,
    payload: bytes,
    injected_meaning: TurnMeaning | None,
    decision: object,
    result: object,
    translation_injection_count: int,
) -> BackendReplayTurnTrace:
    events, malformed = _parse_sse(payload)
    names = tuple(name for name, _ in events)
    clarification = names.count("clarify") == 1
    presentations = tuple(
        data for name, data in events if name == "presentation_contract"
    )
    messages = names.count("message")
    terminal_valid = (
        status_code == 200
        and bool(names)
        and names[0] == "start"
        and names[-1] == "end"
        and names.count("end") == 1
        and names.count("error") == 0
        and (clarification != bool(presentations))
        and (
            len(presentations) == 0
            if clarification
            else len(presentations) == 1
        )
    )
    actual_responsibility = _responsibility_value(decision)
    wrong_responsibility = int(
        not clarification
        and actual_responsibility != capture.expected_responsibility
    )
    presentation: PublicPresentationContract | None = None
    section_violation = 0
    internal_language = 0
    if len(presentations) == 1:
        try:
            presentation = PublicPresentationContract.model_validate(
                presentations[0],
                strict=True,
            )
        except ValidationError:
            section_violation = 1
    if presentation is not None:
        wrong_responsibility += int(
            presentation.responsibility.value
            != capture.expected_responsibility
        )
        internal_language += _internal_language_count(presentation)
    else:
        for name, data in events:
            if name == "clarify":
                question = data.get("question")
                if not isinstance(question, str):
                    internal_language += 1
                else:
                    try:
                        validate_public_text(question)
                    except PublicLanguageError:
                        internal_language += 1

    route_product_ids = tuple(
        binding.product_id
        for binding in getattr(decision, "product_bindings", ())
    )
    visible_product_ids = (
        presentation.visible_product_ids
        if presentation is not None
        else ()
    )
    product_event_ids = _product_event_ids(events)
    wrong_binding = int(
        not clarification
        and
        actual_responsibility in _BOUND_PRODUCT_RESPONSIBILITIES
        and route_product_ids != visible_product_ids
    )
    wrong_product = int(
        (
            bool(product_event_ids) or bool(visible_product_ids)
        )
        and product_event_ids != visible_product_ids
    )
    price_mismatches = _price_specification_mismatches(events)
    raw_leaks = _raw_semantic_leak_count(
        tuple(
            (name, data)
            for name, data in events
            if name in {"presentation_contract", "clarify", "message"}
        )
    )
    unsafe_downgrade = int(
        turn.required_safety_language == "safety"
        and actual_responsibility
        != Responsibility.SAFETY_ESCALATION.value
    )
    execution_decision = getattr(result, "decision", None)
    decision_identity_valid = (
        decision is not None
        and execution_decision is decision
    )
    injection_valid = (
        translation_injection_count == 1
        and injected_meaning == capture.meaning
    )
    frontend_violations = int(
        malformed
        or not terminal_valid
        or not decision_identity_valid
    )
    wrong_presentation = int(
        (
            capture.expected_responsibility
            == Responsibility.CLARIFICATION.value
            and not clarification
        )
        or (
            capture.expected_responsibility
            != Responsibility.CLARIFICATION.value
            and len(presentations) != 1
        )
    )
    counters = (
        messages,
        wrong_responsibility,
        wrong_binding,
        wrong_product,
        price_mismatches,
        section_violation,
        raw_leaks,
        internal_language,
        unsafe_downgrade,
        frontend_violations,
        wrong_presentation,
        int(not injection_valid),
    )
    return BackendReplayTurnTrace(
        trajectory_id=turn.trajectory_id,
        turn_id=turn.turn_id,
        completed=terminal_valid,
        clarification=clarification,
        translation_injection_count=translation_injection_count,
        provider_call_count=0,
        copywriter_call_count=0,
        presentation_contract_count=len(presentations),
        message_event_count=messages,
        wrong_responsibility_count=wrong_responsibility,
        wrong_binding_count=wrong_binding,
        wrong_product_count=wrong_product,
        price_specification_mismatch_count=price_mismatches,
        section_order_violation_count=section_violation,
        raw_ad_leak_count=raw_leaks,
        internal_language_count=internal_language,
        unsafe_downgrade_count=unsafe_downgrade,
        frontend_contract_violation_count=(
            frontend_violations + wrong_presentation
        ),
        expected_responsibility=capture.expected_responsibility,
        actual_responsibility=actual_responsibility,
        visible_product_ids=visible_product_ids,
        event_names=names,
        passed=terminal_valid and not any(counters),
    )


def _summarize(
    *,
    trajectories: Sequence[FinalTranslationTrajectory],
    traces: Sequence[BackendReplayTurnTrace],
    outbound_network_attempt_count: int,
) -> BackendReplayReport:
    normalized = tuple(traces)
    if len(normalized) != FINAL_TRANSLATION_TURN_COUNT:
        raise BackendReplayError(
            "backend replay requires exactly 48 turn traces"
        )
    identities = tuple(
        (trace.trajectory_id, trace.turn_id) for trace in normalized
    )
    if len(set(identities)) != FINAL_TRANSLATION_TURN_COUNT:
        raise BackendReplayError("backend replay turn IDs must be unique")
    presentation_count = sum(
        trace.presentation_contract_count for trace in normalized
    )
    clarification_count = sum(
        trace.clarification for trace in normalized
    )
    non_clarification_count = (
        FINAL_TRANSLATION_TURN_COUNT - clarification_count
    )
    totals = {
        field: sum(getattr(trace, field) for trace in normalized)
        for field in (
            "translation_injection_count",
            "provider_call_count",
            "copywriter_call_count",
            "message_event_count",
            "wrong_responsibility_count",
            "wrong_binding_count",
            "wrong_product_count",
            "price_specification_mismatch_count",
            "section_order_violation_count",
            "raw_ad_leak_count",
            "internal_language_count",
            "unsafe_downgrade_count",
            "frontend_contract_violation_count",
        )
    }
    wrong_presentation_count = abs(
        presentation_count - non_clarification_count
    )
    passed_by_trajectory = {
        trajectory.trajectory_id: (
            len([
                trace
                for trace in normalized
                if trace.trajectory_id == trajectory.trajectory_id
            ])
            == len(trajectory.turns)
            and all(
                trace.passed
                for trace in normalized
                if trace.trajectory_id == trajectory.trajectory_id
            )
        )
        for trajectory in trajectories
    }
    critical_count = sum(
        trajectory.critical for trajectory in trajectories
    )
    critical_passed = sum(
        passed_by_trajectory[trajectory.trajectory_id]
        for trajectory in trajectories
        if trajectory.critical
    )
    passed_turn_count = sum(trace.passed for trace in normalized)
    completed_turn_count = sum(
        trace.completed for trace in normalized
    )
    zero_tolerance = (
        totals["provider_call_count"],
        totals["copywriter_call_count"],
        totals["message_event_count"],
        totals["wrong_responsibility_count"],
        totals["wrong_binding_count"],
        totals["wrong_product_count"],
        totals["price_specification_mismatch_count"],
        totals["section_order_violation_count"],
        totals["raw_ad_leak_count"],
        totals["internal_language_count"],
        totals["unsafe_downgrade_count"],
        totals["frontend_contract_violation_count"],
        outbound_network_attempt_count,
        wrong_presentation_count,
    )
    passed = (
        len(trajectories) == FINAL_TRANSLATION_CASE_COUNT
        and completed_turn_count == FINAL_TRANSLATION_TURN_COUNT
        and passed_turn_count == FINAL_TRANSLATION_TURN_COUNT
        and totals["translation_injection_count"]
        == FINAL_TRANSLATION_TURN_COUNT
        and presentation_count == non_clarification_count
        and critical_passed == critical_count
        and not any(zero_tolerance)
    )
    trace_payload = [
        trace.model_dump(mode="json") for trace in normalized
    ]
    results_sha256 = sha256(
        b"".join(_canonical_line(item) for item in trace_payload)
    ).hexdigest()
    serious_failures = sum(not trace.passed for trace in normalized)
    serious_failures += int(not passed and serious_failures == 0)
    return BackendReplayReport(
        passed=passed,
        trajectory_count=len(trajectories),
        critical_trajectory_count=critical_count,
        critical_trajectory_passed=critical_passed,
        expected_turn_count=FINAL_TRANSLATION_TURN_COUNT,
        turn_count=len(normalized),
        completed_turn_count=completed_turn_count,
        passed_turn_count=passed_turn_count,
        non_clarification_turn_count=non_clarification_count,
        clarification_turn_count=clarification_count,
        translation_injection_count=totals[
            "translation_injection_count"
        ],
        provider_call_count=totals["provider_call_count"],
        copywriter_call_count=totals["copywriter_call_count"],
        presentation_contract_count=presentation_count,
        message_event_count=totals["message_event_count"],
        wrong_responsibility_count=totals[
            "wrong_responsibility_count"
        ],
        wrong_binding_count=totals["wrong_binding_count"],
        wrong_product_count=totals["wrong_product_count"],
        wrong_presentation_count=wrong_presentation_count,
        price_specification_mismatch_count=totals[
            "price_specification_mismatch_count"
        ],
        section_order_violation_count=totals[
            "section_order_violation_count"
        ],
        raw_ad_leak_count=totals["raw_ad_leak_count"],
        internal_language_count=totals["internal_language_count"],
        internal_public_language_count=totals[
            "internal_language_count"
        ],
        unsafe_downgrade_count=totals["unsafe_downgrade_count"],
        frontend_contract_violation_count=totals[
            "frontend_contract_violation_count"
        ],
        outbound_network_attempt_count=(
            outbound_network_attempt_count
        ),
        serious_failure_count=serious_failures,
        results_sha256=results_sha256,
        turn_traces=normalized,
    )


def _parse_sse(
    payload: bytes,
) -> tuple[tuple[tuple[str, dict[str, Any]], ...], bool]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return (), True
    events: list[tuple[str, dict[str, Any]]] = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        name = ""
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line.removeprefix("event: ").strip()
            elif line.startswith("data: "):
                data_lines.append(line.removeprefix("data: "))
        if not name or not data_lines:
            return tuple(events), True
        try:
            data = json.loads("".join(data_lines))
        except json.JSONDecodeError:
            return tuple(events), True
        if not isinstance(data, dict):
            return tuple(events), True
        events.append((name, data))
    return tuple(events), False


def _product_event_ids(
    events: Sequence[tuple[str, Mapping[str, object]]],
) -> tuple[int, ...]:
    product_events = [
        data for name, data in events if name == "products"
    ]
    if not product_events:
        return ()
    if len(product_events) != 1:
        return (-1,)
    cards = product_events[0].get("cards")
    if not isinstance(cards, list):
        return (-1,)
    values = tuple(
        card.get("product_id")
        for card in cards
        if isinstance(card, dict)
    )
    if (
        len(values) != len(cards)
        or any(type(value) is not int or value <= 0 for value in values)
        or len(values) != len(set(values))
    ):
        return (-1,)
    return values


def _price_specification_mismatches(
    events: Sequence[tuple[str, Mapping[str, object]]],
) -> int:
    mismatches = 0
    for name, data in events:
        if name != "products":
            continue
        cards = data.get("cards")
        if not isinstance(cards, list):
            return 1
        for card in cards:
            if not isinstance(card, dict):
                mismatches += 1
                continue
            price = card.get("price")
            specification = card.get("specification")
            alignment = card.get("price_specification_alignment")
            if alignment == "aligned" and (
                price is None
                or not isinstance(specification, str)
                or not specification.strip()
            ):
                mismatches += 1
            if alignment != "aligned" and specification is not None:
                mismatches += 1
            if price is not None and not isinstance(price, str):
                mismatches += 1
            if specification is not None and (
                not isinstance(specification, str)
                or not specification.strip()
            ):
                mismatches += 1
    return mismatches


def _internal_language_count(
    presentation: PublicPresentationContract,
) -> int:
    values = [
        *(
            value
            for section in presentation.sections
            for value in (
                section.copy_text,
                section.advisor_reason,
                *(fact.display_value for fact in section.direct_facts),
            )
            if value is not None
        ),
        *(
            value
            for value in (
                presentation.winner.reason
                if presentation.winner is not None
                else None,
                presentation.winner.tie_reason
                if presentation.winner is not None
                else None,
            )
            if value is not None
        ),
        *(
            cell.value
            for row in presentation.comparison_rows
            for cell in row.cells
        ),
        *(tag.label for tag in presentation.compact_tags),
    ]
    count = 0
    for value in values:
        try:
            validate_public_text(value)
        except PublicLanguageError:
            count += 1
    return count


def _raw_semantic_leak_count(
    events: Sequence[tuple[str, Mapping[str, object]]],
) -> int:
    return sum(
        key in _FORBIDDEN_SEMANTIC_KEYS
        for _, data in events
        for key in _walk_keys(data)
    )


def _walk_keys(value: object) -> Iterator[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str):
                yield key
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _responsibility_value(decision: object) -> str | None:
    responsibility = getattr(decision, "responsibility", None)
    if isinstance(responsibility, Responsibility):
        return responsibility.value
    return responsibility if isinstance(responsibility, str) else None


def _conversation_version(runtime: object, session_id: str) -> int:
    state = runtime.conversation_state.load(session_id)
    return state.version if state is not None else 0


@contextmanager
def _provider_keys_disabled() -> Iterator[None]:
    previous = {
        name: os.environ.get(name) for name in _PROVIDER_KEY_NAMES
    }
    try:
        for name in _PROVIDER_KEY_NAMES:
            os.environ.pop(name, None)
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BackendReplayError(f"{label} is invalid") from error
    if not isinstance(payload, dict):
        raise BackendReplayError(f"{label} is invalid")
    return payload


def _read_checksums(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="ascii").splitlines():
        parts = line.split()
        if len(parts) != 2 or len(parts[0]) != 64:
            raise BackendReplayError(
                "translation checksums are invalid"
            )
        values[parts[1]] = parts[0]
    if set(values) != {"results.jsonl", "summary.json"}:
        raise BackendReplayError("translation checksums are invalid")
    return values


def _hash_json(value: object) -> str:
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _canonical_line(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _write_report(
    *,
    output_dir: Path,
    report: BackendReplayReport,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=False)
    rows_bytes = b"".join(
        _canonical_line(trace.model_dump(mode="json"))
        for trace in report.turn_traces
    )
    if sha256(rows_bytes).hexdigest() != report.results_sha256:
        raise BackendReplayError("backend result hash mismatch")
    summary_payload = report.model_dump(
        mode="json",
        exclude={"turn_traces"},
    )
    summary_bytes = _canonical_line(summary_payload)
    (output_dir / "results.jsonl").write_bytes(rows_bytes)
    (output_dir / "summary.json").write_bytes(summary_bytes)
    (output_dir / "SHA256SUMS").write_text(
        (
            f"{report.results_sha256}  results.jsonl\n"
            f"{sha256(summary_bytes).hexdigest()}  summary.json\n"
        ),
        encoding="ascii",
    )


def _parse_args(
    argv: Sequence[str] | None = None,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Replay one immutable 48-row translation capture through "
            "the real Guide HTTP backend."
        )
    )
    parser.add_argument("--cases", type=Path, default=_DEFAULT_CASES)
    parser.add_argument(
        "--attempt-context",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--phase",
        choices=("backend",),
        required=True,
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=_ROOT,
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = replay_final_real_backend(
        cases_path=args.cases,
        attempt_context_path=args.attempt_context,
        phase=args.phase,
        repo_root=args.repo_root,
    )
    print(
        report.model_dump_json(
            exclude={"turn_traces"},
        )
    )
    return 0 if report.passed else 3


__all__ = [
    "BackendReplayError",
    "BackendReplayReport",
    "BackendReplayTurnTrace",
    "CapturedMeaning",
    "main",
    "replay_final_real_backend",
]


if __name__ == "__main__":
    raise SystemExit(main())
