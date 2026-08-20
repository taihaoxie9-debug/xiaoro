"""Shared frozen-input and evidence primitives for real Guide A/B gates."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, TypeVar

from app.guide.adapters.llm.contracts import (
    SemanticIntentCallResult,
    SemanticTokenUsage,
)
from tools.guide_gates.intent_model_ab import (
    AbInvocation,
    AdapterUsage,
    IntentAbConfigurationError,
    IntentCase,
    IntentCaseError,
    PipelineEvaluator,
    _run_case as _run_single_stage_case,
    _summarize_model,
    load_cases,
)
from tools.guide_gates.private_output_io import (
    OutputBindingError,
    PrivateRunDirectory,
    open_private_at,
    verify_output_binding,
)


NORMALIZED_RESULTS_NAME = "normalized_results.jsonl"
RUNTIME_METRICS_NAME = "runtime_metrics.json"
SUMMARY_NAME = "summary.json"
SUMS_NAME = "SHA256SUMS"
EVIDENCE_FILENAMES = (
    NORMALIZED_RESULTS_NAME,
    RUNTIME_METRICS_NAME,
    SUMMARY_NAME,
    SUMS_NAME,
)
_TOKEN_FIELDS = (
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cached_tokens",
)
_ControlT = TypeVar("_ControlT")


@dataclass(frozen=True, slots=True)
class FrozenInputSpec:
    case_count: int
    case_file_sha256: str
    case_manifest_sha256: str
    smoke_count: int
    smoke_file_sha256: str
    smoke_manifest_sha256: str
    smoke_schema_version: str
    smoke_fixture: str
    source_fixture: str


CANONICAL_INTENT_INPUTS = FrozenInputSpec(
    case_count=128,
    case_file_sha256=(
        "be3df249f3bfdf9e0482a445cae8144ff461a4cc32fa204d40b93df7e63b615e"
    ),
    case_manifest_sha256=(
        "11f3b49d0eb00e201d76f321446127bb0ba1c9f5e398828df8d5e006d51ce0d5"
    ),
    smoke_count=32,
    smoke_file_sha256=(
        "19f4fc5fcbd6aada4158f31cbac20afa3c37f0f36e7b48390afa95f43d662b81"
    ),
    smoke_manifest_sha256=(
        "842f702868244ee0ab6253126eacb51638c80fd694d12a0a421bb24a25b7ac86"
    ),
    smoke_schema_version="guide-two-stage-smoke-manifest-v1",
    smoke_fixture="two_stage_smoke_v1.jsonl",
    source_fixture="semantic_intent_ab_v2.jsonl",
)


@dataclass(frozen=True, slots=True)
class FrozenInputs:
    cases: tuple[IntentCase, ...]
    smoke_cases: tuple[IntentCase, ...]


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    payloads: Mapping[str, bytes]
    normalized_sha256: str
    runtime_sha256: str
    summary_sha256: str


@dataclass(frozen=True, slots=True)
class SingleStageControlReport:
    summary: dict[str, object]
    normalized_rows: tuple[dict[str, object], ...]
    runtime_rows: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class CollectedLaneEvidence:
    lane_summaries: Mapping[str, Mapping[str, object]]
    normalized_rows: tuple[Mapping[str, object], ...]
    runtime_rows: tuple[Mapping[str, object], ...]


@dataclass(frozen=True, slots=True)
class SupervisedRunnerPaths:
    cases: str
    smoke_cases: str
    smoke_manifest: str
    output_dir: str


@dataclass(frozen=True, slots=True)
class AdapterBuildSpec:
    lane: str
    model: str
    prompt_version: str
    factory: Callable[[object], object]


class SensitiveEvidenceError(ValueError):
    """Raised before writing evidence that contains a sensitive value."""


class PrivateEvidenceWriter:
    def __init__(self, run_directory: PrivateRunDirectory) -> None:
        self._run_directory = run_directory
        self._closed = False

    @classmethod
    def create(cls, path: str | Path) -> PrivateEvidenceWriter:
        absolute = Path(os.path.abspath(os.fspath(path)))
        return cls(PrivateRunDirectory.create(absolute))

    def write(
        self,
        bundle: EvidenceBundle,
        *,
        sensitive_values: Sequence[str] = (),
    ) -> None:
        if self._closed:
            raise ValueError("private evidence writer is closed")
        payloads = dict(bundle.payloads)
        if set(payloads) != set(EVIDENCE_FILENAMES) or any(
            not isinstance(payloads[name], bytes)
            for name in EVIDENCE_FILENAMES
        ):
            raise ValueError("real A/B evidence payload set is invalid")

        self._run_directory.verify_binding()
        _reject_sensitive_payloads(payloads, sensitive_values)
        scratch_names: list[str] = []
        try:
            for filename in EVIDENCE_FILENAMES:
                scratch = f".{filename}.{os.getpid()}.tmp"
                self._run_directory.verify_binding()
                descriptor = open_private_at(
                    self._run_directory.directory_descriptor,
                    scratch,
                )
                scratch_names.append(scratch)
                try:
                    _write_all(descriptor, payloads[filename])
                    os.fsync(descriptor)
                    verify_output_binding(
                        self._run_directory.directory_descriptor,
                        scratch,
                        descriptor,
                    )
                finally:
                    os.close(descriptor)
            for filename, scratch in zip(EVIDENCE_FILENAMES, scratch_names):
                self._run_directory.verify_binding()
                os.rename(
                    scratch,
                    filename,
                    src_dir_fd=self._run_directory.directory_descriptor,
                    dst_dir_fd=self._run_directory.directory_descriptor,
                )
            scratch_names.clear()
        finally:
            self._remove_scratch(scratch_names)
        self._run_directory.verify_binding()

    def _remove_scratch(self, scratch_names: Sequence[str]) -> None:
        for scratch in scratch_names:
            try:
                os.unlink(
                    scratch,
                    dir_fd=self._run_directory.directory_descriptor,
                )
            except OSError:
                continue

    def close(self, *, remove_if_empty: bool = False) -> None:
        if self._closed:
            return
        try:
            if remove_if_empty:
                self._remove_if_empty()
        finally:
            self._closed = True
            self._run_directory.close()

    def _remove_if_empty(self) -> None:
        try:
            self._run_directory.verify_binding()
            if os.listdir(self._run_directory.directory_descriptor):
                return
            os.rmdir(
                self._run_directory.path.name,
                dir_fd=self._run_directory.parent_descriptor,
            )
        except OSError:
            return


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def load_frozen_inputs(
    *,
    cases_path: str | Path,
    smoke_cases_path: str | Path,
    smoke_manifest_path: str | Path,
    spec: FrozenInputSpec = CANONICAL_INTENT_INPUTS,
) -> FrozenInputs:
    case_path = Path(cases_path)
    case_bytes = _read_bytes(case_path, label="intent case file")
    if hashlib.sha256(case_bytes).hexdigest() != spec.case_file_sha256:
        raise IntentAbConfigurationError(
            "real A/B requires the canonical frozen v2 case file"
        )
    cases = load_cases(case_path)
    if (
        len(cases) != spec.case_count
        or _case_manifest_sha256(cases) != spec.case_manifest_sha256
    ):
        raise IntentAbConfigurationError(
            "real A/B requires the canonical frozen v2 case manifest"
        )

    smoke_path = Path(smoke_cases_path)
    smoke_bytes = _read_bytes(smoke_path, label="smoke case file")
    if hashlib.sha256(smoke_bytes).hexdigest() != spec.smoke_file_sha256:
        raise IntentAbConfigurationError(
            "real A/B requires the canonical frozen smoke file"
        )
    manifest_bytes = _read_bytes(
        Path(smoke_manifest_path),
        label="smoke manifest",
    )
    if (
        hashlib.sha256(manifest_bytes).hexdigest()
        != spec.smoke_manifest_sha256
    ):
        raise IntentAbConfigurationError(
            "real A/B requires the canonical frozen smoke manifest"
        )
    manifest = _decode_json_object(
        manifest_bytes,
        label="smoke manifest",
    )
    smoke_raw_rows = _decode_jsonl(
        smoke_bytes,
        label="smoke case file",
    )
    smoke_cases = tuple(
        IntentCase.model_validate_json(
            canonical_json_bytes(row),
            strict=True,
        )
        for row in smoke_raw_rows
    )
    case_ids = [case.case_id for case in smoke_cases]
    expected_manifest = {
        "case_ids": case_ids,
        "schema_version": spec.smoke_schema_version,
        "smoke_fixture": spec.smoke_fixture,
        "smoke_sha256": spec.smoke_file_sha256,
        "source_fixture": spec.source_fixture,
        "source_sha256": spec.case_file_sha256,
    }
    if (
        manifest != expected_manifest
        or len(smoke_cases) != spec.smoke_count
        or len(case_ids) != len(set(case_ids))
    ):
        raise IntentAbConfigurationError(
            "real A/B requires the canonical frozen smoke manifest"
        )
    full_raw_rows = _decode_jsonl(case_bytes, label="intent case file")
    full_by_id = {
        row.get("case_id"): row
        for row in full_raw_rows
    }
    if smoke_raw_rows != [
        full_by_id.get(case_id)
        for case_id in case_ids
    ]:
        raise IntentAbConfigurationError(
            "smoke cases must be an exact canonical subset"
        )
    return FrozenInputs(cases=cases, smoke_cases=smoke_cases)


def mapping_usage_complete(usage: Mapping[str, object]) -> bool:
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    total = usage.get("total_tokens")
    return bool(
        _is_token_count(prompt)
        and _is_token_count(completion)
        and _is_token_count(total)
        and total == prompt + completion
    )


def nearest_rank(values: Sequence[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * quantile) - 1)
    return ordered[index]


def sum_token_fields(
    usages: Sequence[object | None],
) -> dict[str, int | None]:
    totals: dict[str, int | None] = {}
    for field_name in _TOKEN_FIELDS:
        values = [
            (
                getattr(usage, field_name)
                if usage is not None
                else None
            )
            for usage in usages
        ]
        totals[field_name] = (
            sum(int(value) for value in values)
            if values and all(_is_token_count(value) for value in values)
            else None
        )
    return totals


def two_stage_usage_complete(report: object) -> bool:
    runtime_rows = getattr(report, "runtime_rows", ())
    return bool(runtime_rows) and all(
        row.stage_usage
        and all(
            _token_usage_complete(stage.usage)
            for stage in row.stage_usage
        )
        for row in runtime_rows
    )


def two_stage_phase_runtime(
    report: object | None,
) -> dict[str, object] | None:
    if report is None:
        return None
    runtime_rows = tuple(getattr(report, "runtime_rows"))
    usages = [
        stage.usage
        for row in runtime_rows
        for stage in row.stage_usage
    ]
    return {
        "case_count": len(runtime_rows),
        "latency_p95_ms": nearest_rank(
            [row.latency_ms for row in runtime_rows],
            0.95,
        ),
        "usage_complete": two_stage_usage_complete(report),
        "usage": sum_token_fields(usages),
    }


def run_single_stage_control(
    *,
    adapter: object,
    cases: Sequence[object],
    evaluator: object,
    lane: str,
    model: str,
    expected_case_count: int,
) -> SingleStageControlReport:
    if len(cases) != expected_case_count:
        raise IntentAbConfigurationError(
            "single-stage control requires the canonical smoke cases"
        )
    control_adapter = _SingleStageControlAdapter(adapter)
    executions = tuple(
        _run_single_stage_case(
            case=case,
            model=model,
            adapter=control_adapter,
            evaluator=evaluator,
        )
        for case in cases
    )
    rows = tuple(item[0] for item in executions)
    runtime = tuple(item[1] for item in executions)
    model_summary = _summarize_model(rows)
    route_matches = sum(
        row.goal_correct and row.topic_correct
        for row in rows
    )
    detail_matches = sum(
        row.concern_correct
        and row.observation_correct
        and row.reference_correct
        for row in rows
    )
    hard = model_summary.hard_gates
    pipeline_complete = hard.pipeline_status == "AVAILABLE"
    usage_complete = bool(runtime) and all(
        mapping_usage_complete(row.usage)
        for row in runtime
    )
    summary = {
        "case_count": len(rows),
        "route_critical_match_count": route_matches,
        "route_critical_rate": route_matches / len(rows),
        "detail_key_match_count": detail_matches,
        "detail_key_rate": detail_matches / len(rows),
        "safe_clarification_mismatch_count": 0,
        "unsafe_task_plan_mismatch_count": (
            hard.task_plan_mismatch_count or 0
        ),
        "hard_constraint_override_count": (
            hard.hard_constraint_override_count or 0
        ),
        "unauthorized_constraint_transition_count": (
            hard.unauthorized_constraint_transition_count or 0
        ),
        "forbidden_field_acceptance_count": (
            hard.forbidden_field_acceptance_count
        ),
        "invalid_output_task_plan_invocation_count": (
            hard.invalid_output_task_plan_invocation_count
        ),
        "wrong_product_selection_count": (
            hard.wrong_product_selection_count or 0
        ),
        "legacy_fallback_count": hard.legacy_fallback_count or 0,
        "pipeline_evidence_complete": pipeline_complete,
        "hard_gates_passed": hard.passed,
        "usage_complete": usage_complete,
        "latency_p95_ms": nearest_rank(
            [row.latency_ms for row in runtime],
            0.95,
        ),
        "passed": bool(
            route_matches / len(rows) >= 0.85
            and hard.passed
            and usage_complete
        ),
    }
    return SingleStageControlReport(
        summary=summary,
        normalized_rows=tuple(
            {
                "lane": lane,
                "phase": "smoke",
                **row.model_dump(mode="json"),
            }
            for row in rows
        ),
        runtime_rows=tuple(
            {
                "lane": lane,
                "phase": "smoke",
                **row.model_dump(mode="json"),
            }
            for row in runtime
        ),
    )


def build_evidence_bundle(
    *,
    normalized_rows: Sequence[Mapping[str, object]],
    normalized_sort_key: Callable[[Mapping[str, object]], object],
    runtime_payload: Mapping[str, object],
    summary_builder: Callable[[str, str], Mapping[str, object]],
) -> EvidenceBundle:
    normalized_bytes = b"".join(
        canonical_json_bytes(row) + b"\n"
        for row in sorted(normalized_rows, key=normalized_sort_key)
    )
    normalized_sha256 = hashlib.sha256(normalized_bytes).hexdigest()
    runtime_bytes = canonical_json_bytes(runtime_payload) + b"\n"
    runtime_sha256 = hashlib.sha256(runtime_bytes).hexdigest()
    summary_payload = summary_builder(
        normalized_sha256,
        runtime_sha256,
    )
    summary_bytes = canonical_json_bytes(summary_payload) + b"\n"
    summary_sha256 = hashlib.sha256(summary_bytes).hexdigest()
    sums_bytes = (
        f"{normalized_sha256}  {NORMALIZED_RESULTS_NAME}\n"
        f"{runtime_sha256}  {RUNTIME_METRICS_NAME}\n"
        f"{summary_sha256}  {SUMMARY_NAME}\n"
    ).encode("ascii")
    return EvidenceBundle(
        payloads={
            NORMALIZED_RESULTS_NAME: normalized_bytes,
            RUNTIME_METRICS_NAME: runtime_bytes,
            SUMMARY_NAME: summary_bytes,
            SUMS_NAME: sums_bytes,
        },
        normalized_sha256=normalized_sha256,
        runtime_sha256=runtime_sha256,
        summary_sha256=summary_sha256,
    )


def collect_supervised_lane_evidence(
    *,
    two_stage_lanes: Sequence[str],
    reports: Mapping[str, Mapping[str, object | None]],
    adapters: Mapping[str, object],
    control_lane: str,
    control_model: str,
    control: SingleStageControlReport,
    provider: str,
    p95_limit_ms: float,
) -> CollectedLaneEvidence:
    lane_summaries: dict[str, dict[str, object]] = {}
    normalized_rows: list[Mapping[str, object]] = []
    runtime_rows: list[Mapping[str, object]] = []
    for lane in two_stage_lanes:
        smoke = reports[lane]["smoke"]
        full = reports[lane]["full"]
        if smoke is None:
            raise TypeError("two-stage smoke report is required")
        lane_summaries[lane] = _two_stage_lane_summary(
            lane=lane,
            adapter=adapters[lane],
            smoke=smoke,
            full=full,
            provider=provider,
            p95_limit_ms=p95_limit_ms,
        )
        for report in (smoke, full):
            if report is None:
                continue
            normalized_rows.extend(
                {
                    "lane": lane,
                    **row.model_dump(mode="json"),
                }
                for row in report.normalized_rows
            )
            runtime_rows.extend(
                {
                    "lane": lane,
                    **row.model_dump(mode="json"),
                }
                for row in report.runtime_rows
            )
    lane_summaries[control_lane] = {
        "lane": control_lane,
        "eligible_for_selection": False,
        "provider": provider,
        "model": control_model,
        "model_fingerprint": "UNAVAILABLE",
        "prompt_version": adapters[control_lane].prompt_version,
        "case_count": len(control.normalized_rows),
        "smoke": control.summary,
        "full": None,
        "usage_complete": control.summary["usage_complete"],
        "passed": control.summary["passed"],
    }
    normalized_rows.extend(control.normalized_rows)
    runtime_rows.extend(control.runtime_rows)
    return CollectedLaneEvidence(
        lane_summaries=lane_summaries,
        normalized_rows=tuple(normalized_rows),
        runtime_rows=tuple(runtime_rows),
    )


def build_supervised_evidence(
    *,
    collected: CollectedLaneEvidence,
    selected_lane: str | None,
    runtime_schema_version: str,
    summary_schema_version: str,
    identity: Mapping[str, object],
) -> tuple[EvidenceBundle, int]:
    runtime_lanes = {
        lane: _lane_runtime_payload(summary)
        for lane, summary in collected.lane_summaries.items()
    }
    runtime_payload = {
        "schema_version": runtime_schema_version,
        "lanes": runtime_lanes,
        "rows": sorted(
            collected.runtime_rows,
            key=_lane_case_sort_key,
        ),
    }
    exit_code = 0 if selected_lane is not None else 3

    def build_summary(
        normalized_sha: str,
        runtime_sha: str,
    ) -> Mapping[str, object]:
        selected = (
            collected.lane_summaries[selected_lane]
            if selected_lane is not None
            else None
        )
        return {
            "schema_version": summary_schema_version,
            "identity": dict(identity),
            "selected_lane": selected_lane,
            "selected_model": (
                selected["model"] if selected is not None else None
            ),
            "exit_code": exit_code,
            "lanes": dict(collected.lane_summaries),
            "cost": {
                "pricing_snapshot_status": "UNAVAILABLE",
                "status": "UNAVAILABLE",
                "actual_cost_cny": "UNAVAILABLE",
            },
            "stable_evidence_sha256": normalized_sha,
            "runtime_metrics_sha256": runtime_sha,
        }

    bundle = build_evidence_bundle(
        normalized_rows=collected.normalized_rows,
        normalized_sort_key=_lane_case_sort_key,
        runtime_payload=runtime_payload,
        summary_builder=build_summary,
    )
    return bundle, exit_code


def execute_supervised_runner(
    *,
    cases_path: str | Path,
    smoke_cases_path: str | Path,
    smoke_manifest_path: str | Path,
    output_dir: str | Path,
    sensitive_value: str,
    adapter_builder: Callable[[], Mapping[str, object]],
    lane_runner: Callable[
        [FrozenInputs, Mapping[str, object]],
        Mapping[str, Mapping[str, object | None]],
    ],
    control_runner: Callable[
        [FrozenInputs, Mapping[str, object]],
        _ControlT,
    ],
    evidence_builder: Callable[
        [
            Mapping[str, object],
            Mapping[str, Mapping[str, object | None]],
            _ControlT,
        ],
        tuple[EvidenceBundle, int],
    ],
) -> int:
    adapters: Mapping[str, object] = {}
    writer: PrivateEvidenceWriter | None = None
    evidence_written = False
    try:
        frozen = load_frozen_inputs(
            cases_path=cases_path,
            smoke_cases_path=smoke_cases_path,
            smoke_manifest_path=smoke_manifest_path,
        )
        writer = PrivateEvidenceWriter.create(output_dir)
        adapters = adapter_builder()
        reports = lane_runner(frozen, adapters)
        control = control_runner(frozen, adapters)
        bundle, exit_code = evidence_builder(adapters, reports, control)
        writer.write(bundle, sensitive_values=(sensitive_value,))
        evidence_written = True
        return exit_code
    except (
        IntentAbConfigurationError,
        IntentCaseError,
        OSError,
        OutputBindingError,
        TypeError,
        ValueError,
    ):
        return 2
    finally:
        try:
            close_adapters(adapters)
        finally:
            if writer is not None:
                writer.close(remove_if_empty=not evidence_written)


def close_adapters(adapters: Mapping[str, object]) -> None:
    for adapter in adapters.values():
        close = getattr(adapter, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                continue


def build_adapter_set(
    *,
    specs: Sequence[AdapterBuildSpec],
    config_builder: Callable[[str], object],
    provider: str,
    base_url: str,
) -> dict[str, object]:
    adapters: dict[str, object] = {}
    try:
        for spec in specs:
            adapter = spec.factory(config_builder(spec.model))
            identity = (
                getattr(adapter, "provider", None),
                getattr(adapter, "model", None),
                getattr(adapter, "base_url", None),
                getattr(adapter, "prompt_version", None),
            )
            if (
                identity
                != (
                    provider,
                    spec.model,
                    base_url,
                    spec.prompt_version,
                )
                or not callable(
                    getattr(adapter, "propose_with_result", None)
                )
            ):
                raise IntentAbConfigurationError(
                    "real A/B adapter identity is invalid"
                )
            adapters[spec.lane] = adapter
    except Exception:
        close_adapters(adapters)
        raise
    return adapters


def run_two_stage_lane_phases(
    *,
    lanes: Sequence[str],
    frozen: FrozenInputs,
    adapters: Mapping[str, object],
    evaluator_factory: Callable[[], PipelineEvaluator],
    gate_runner: Callable[..., object],
) -> dict[str, dict[str, object | None]]:
    reports: dict[str, dict[str, object | None]] = {}
    for lane in lanes:
        smoke = gate_runner(
            adapter=adapters[lane],
            cases=frozen.smoke_cases,
            evaluator=evaluator_factory(),
            phase="smoke",
        )
        reports[lane] = {"smoke": smoke, "full": None}
    for lane in lanes:
        smoke = reports[lane]["smoke"]
        if (
            smoke is not None
            and smoke.passed
            and two_stage_usage_complete(smoke)
        ):
            reports[lane]["full"] = gate_runner(
                adapter=adapters[lane],
                cases=frozen.cases,
                evaluator=evaluator_factory(),
                phase="full",
            )
    return reports


def validate_canonical_sensitive_value(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 1024
        or any(
            ord(character) < 32 or ord(character) == 127
            for character in value
        )
    ):
        raise IntentAbConfigurationError(
            "real A/B sensitive value is invalid"
        )
    return value


def parse_supervised_runner_paths(
    argv: Sequence[str] | None,
    *,
    description: str,
    default_cases: str | Path,
    default_smoke_cases: str | Path,
    default_smoke_manifest: str | Path,
) -> SupervisedRunnerPaths:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--cases", default=str(default_cases))
    parser.add_argument("--smoke-cases", default=str(default_smoke_cases))
    parser.add_argument(
        "--smoke-manifest",
        default=str(default_smoke_manifest),
    )
    parser.add_argument("--output-dir", required=True)
    values = parser.parse_args(argv)
    return SupervisedRunnerPaths(
        cases=values.cases,
        smoke_cases=values.smoke_cases,
        smoke_manifest=values.smoke_manifest,
        output_dir=values.output_dir,
    )


def _two_stage_lane_summary(
    *,
    lane: str,
    adapter: object,
    smoke: object,
    full: object | None,
    provider: str,
    p95_limit_ms: float,
) -> dict[str, object]:
    smoke_runtime = two_stage_phase_runtime(smoke)
    full_runtime = two_stage_phase_runtime(full)
    p95_gate_passed = bool(
        full_runtime is not None
        and full_runtime["latency_p95_ms"] <= p95_limit_ms
    )
    usage_complete = bool(
        smoke_runtime is not None
        and smoke_runtime["usage_complete"]
        and full_runtime is not None
        and full_runtime["usage_complete"]
    )
    passed = bool(
        full is not None
        and full.passed
        and p95_gate_passed
        and usage_complete
    )
    if not smoke.passed:
        stop_reason = (
            "provider_failure_rate"
            if smoke.stop_reason == "provider_failure_rate"
            else "smoke_gate"
        )
    elif full is None:
        stop_reason = "usage_incomplete"
    elif not full.passed:
        stop_reason = (
            "provider_failure_rate"
            if full.stop_reason == "provider_failure_rate"
            else "full_gate"
        )
    elif not p95_gate_passed:
        stop_reason = "latency_p95"
    elif not usage_complete:
        stop_reason = "usage_incomplete"
    else:
        stop_reason = None
    return {
        "lane": lane,
        "eligible_for_selection": True,
        "provider": provider,
        "model": adapter.model,
        "model_fingerprint": "UNAVAILABLE",
        "prompt_version": adapter.prompt_version,
        "smoke": {
            **smoke.summary_payload(),
            "runtime": smoke_runtime,
        },
        "full": (
            {
                **full.summary_payload(),
                "runtime": full_runtime,
            }
            if full is not None
            else None
        ),
        "p95_limit_ms": p95_limit_ms,
        "p95_gate_passed": p95_gate_passed,
        "usage_complete": usage_complete,
        "stop_reason": stop_reason,
        "passed": passed,
    }


def _lane_runtime_payload(
    summary: Mapping[str, object],
) -> dict[str, object]:
    smoke = summary["smoke"]
    full = summary["full"]
    if not isinstance(smoke, Mapping):
        raise TypeError("lane smoke summary must be a mapping")
    smoke_runtime = smoke.get("runtime")
    if smoke_runtime is None:
        smoke_runtime = {
            "case_count": smoke["case_count"],
            "latency_p95_ms": smoke["latency_p95_ms"],
        }
    full_runtime = (
        full.get("runtime")
        if isinstance(full, Mapping)
        else None
    )
    return {
        "usage_complete": summary["usage_complete"],
        "cost_status": "UNAVAILABLE",
        "actual_cost_cny": "UNAVAILABLE",
        "smoke": smoke_runtime,
        "full": full_runtime,
    }


def _lane_case_sort_key(row: Mapping[str, object]) -> tuple[str, str, str]:
    return (
        str(row["lane"]),
        str(row["phase"]),
        str(row["case_id"]),
    )


class _SingleStageControlAdapter:
    def __init__(self, adapter: object) -> None:
        self._adapter = adapter
        self.provider = adapter.provider
        self.model = adapter.model
        self.prompt_version = adapter.prompt_version

    def propose(self, message, context) -> AbInvocation:
        result = self._adapter.propose_with_result(message, context)
        if not isinstance(result, SemanticIntentCallResult):
            raise TypeError(
                "single-stage adapter must return SemanticIntentCallResult"
            )
        usage = result.usage
        return AbInvocation(
            proposal=result.proposal,
            usage=AdapterUsage(
                prompt_tokens=(
                    usage.prompt_tokens if usage is not None else None
                ),
                completion_tokens=(
                    usage.completion_tokens
                    if usage is not None
                    else None
                ),
                total_tokens=(
                    usage.total_tokens if usage is not None else None
                ),
                cached_tokens=(
                    usage.cached_tokens if usage is not None else None
                ),
            ),
        )


def _token_usage_complete(usage: SemanticTokenUsage | None) -> bool:
    return bool(
        usage is not None
        and _is_token_count(usage.prompt_tokens)
        and _is_token_count(usage.completion_tokens)
        and _is_token_count(usage.total_tokens)
        and usage.total_tokens
        == usage.prompt_tokens + usage.completion_tokens
    )


def _is_token_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _write_all(descriptor: int, content: bytes) -> None:
    written = 0
    while written < len(content):
        count = os.write(descriptor, content[written:])
        if count <= 0:
            raise OSError("private evidence write made no progress")
        written += count


def _read_bytes(path: Path, *, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise IntentCaseError(f"{label} is unavailable") from exc


def _decode_json_object(
    content: bytes,
    *,
    label: str,
) -> dict[str, object]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise IntentCaseError(f"{label} is invalid") from None
    if not isinstance(value, dict):
        raise IntentCaseError(f"{label} must be an object")
    return value


def _decode_jsonl(
    content: bytes,
    *,
    label: str,
) -> list[dict[str, object]]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise IntentCaseError(f"{label} must be UTF-8") from None
    rows: list[dict[str, object]] = []
    for line in text.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            raise IntentCaseError(f"{label} is invalid") from None
        if not isinstance(value, dict):
            raise IntentCaseError(f"{label} rows must be objects")
        rows.append(value)
    return rows


def _case_manifest_sha256(cases: Sequence[IntentCase]) -> str:
    content = b"".join(
        canonical_json_bytes(_legacy_v2_case_payload(case)) + b"\n"
        for case in cases
    )
    return hashlib.sha256(content).hexdigest()


def _legacy_v2_case_payload(case: IntentCase) -> dict[str, object]:
    payload = case.model_dump(mode="json")
    before = payload.get("before_state")
    if isinstance(before, dict):
        before.pop("concepts", None)
        before.pop("similarity_anchor_product_id", None)
    expected = payload.get("expected")
    if isinstance(expected, dict):
        final_state = expected.get("final_state")
        if isinstance(final_state, dict):
            final_state.pop("concepts", None)
            final_state.pop("similarity_anchor_product_id", None)
    return payload


def _reject_sensitive_payloads(
    payloads: Mapping[str, bytes],
    sensitive_values: Sequence[str],
) -> None:
    for sensitive in sensitive_values:
        if not isinstance(sensitive, str) or not sensitive:
            raise ValueError("sensitive evidence value must be non-empty")
        raw = sensitive.encode("utf-8")
        canonical = canonical_json_bytes(sensitive)[1:-1]
        fragments = {raw, canonical}
        if any(
            fragment and fragment in payload
            for payload in payloads.values()
            for fragment in fragments
        ):
            raise SensitiveEvidenceError(
                "real A/B evidence contains a sensitive value"
            )


__all__ = [
    "CANONICAL_INTENT_INPUTS",
    "CollectedLaneEvidence",
    "AdapterBuildSpec",
    "EVIDENCE_FILENAMES",
    "EvidenceBundle",
    "FrozenInputSpec",
    "FrozenInputs",
    "NORMALIZED_RESULTS_NAME",
    "PrivateEvidenceWriter",
    "RUNTIME_METRICS_NAME",
    "SensitiveEvidenceError",
    "SingleStageControlReport",
    "SupervisedRunnerPaths",
    "SUMMARY_NAME",
    "SUMS_NAME",
    "build_evidence_bundle",
    "build_adapter_set",
    "build_supervised_evidence",
    "canonical_json_bytes",
    "close_adapters",
    "collect_supervised_lane_evidence",
    "execute_supervised_runner",
    "load_frozen_inputs",
    "mapping_usage_complete",
    "nearest_rank",
    "parse_supervised_runner_paths",
    "run_single_stage_control",
    "run_two_stage_lane_phases",
    "sum_token_fields",
    "two_stage_phase_runtime",
    "two_stage_usage_complete",
    "validate_canonical_sensitive_value",
]
