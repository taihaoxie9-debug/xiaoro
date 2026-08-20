from __future__ import annotations

import argparse
from collections.abc import Sequence
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.guide.adapters.llm.contracts import (
    SemanticProviderFailure,
)
from app.guide.adapters.llm.deepseek_intent import (
    DEEPSEEK_V4_PRO_MODEL,
)
from app.guide.adapters.llm.deepseek_presentation_copywriter import (
    DeepSeekPresentationCopywriterAdapter,
)
from app.guide.presentation.copywriter_contracts import CopywriterDraft
from app.guide.presentation.copywriter_prompt import (
    PRESENTATION_COPY_PROMPT_VERSION,
)
from tools.guide_gates.presentation_copy_gate import (
    PresentationCopyGateCase,
    PresentationCopyGateRow,
    evaluate_copy_gate_output,
    load_copy_gate_cases,
    summarize_copy_gate,
)
from tools.guide_gates.run_official_deepseek_smoke import (
    DEFAULT_KEY_PATH,
    KeyPrecheckError,
    read_private_api_key,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES = (
    ROOT
    / "tests"
    / "fixtures"
    / "guide"
    / "presentation"
    / "copy_gate_v3_production.jsonl"
)
COPY_GATE_MAX_TOKENS = 1536


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )


class RealPresentationCopyResult(_StrictFrozenModel):
    case_id: str
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal[
        "ok",
        "invalid_output",
        "provider_failure",
        "adapter_error",
    ]
    provider_failure_code: str | None
    raw_provider_output: str | None = Field(
        default=None,
        max_length=65536,
    )
    trace_id: str | None = Field(default=None, max_length=80)
    earliest_failure_layer: Literal["public_presentation"] | None
    latency_ms: float = Field(ge=0.0, allow_inf_nan=False)
    draft: CopywriterDraft | None
    evaluation: PresentationCopyGateRow
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class RealPresentationCopyReport(_StrictFrozenModel):
    schema_version: Literal[
        "guide-real-presentation-copy-gate-summary-v1"
    ] = "guide-real-presentation-copy-gate-summary-v1"
    run_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")
    provider: str = Field(min_length=1, max_length=96)
    model: str = Field(min_length=1, max_length=256)
    prompt_version: str = Field(min_length=1, max_length=160)
    cases_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_count: int = Field(ge=0)
    completed_case_count: int = Field(ge=0)
    provider_call_count: int = Field(ge=0)
    stopped_early: bool
    stop_reason: Literal[
        "hard_violation",
        "invalid_output",
        "provider_failure",
        "adapter_error",
    ] | None = None
    schema_valid_count: int = Field(ge=0)
    readability_passed_count: int = Field(ge=0)
    fact_coverage_passed_count: int = Field(ge=0)
    internal_language_passed_count: int = Field(ge=0)
    passed_count: int = Field(ge=0)
    schema_valid_rate: float = Field(ge=0.0, le=1.0)
    readability_rate: float = Field(ge=0.0, le=1.0)
    fact_coverage_rate: float = Field(ge=0.0, le=1.0)
    minimum_fact_coverage: float = Field(ge=0.0, le=1.0)
    internal_language_rate: float = Field(ge=0.0, le=1.0)
    provider_call_violation_count: int = Field(ge=0)
    slot_binding_violation_count: int = Field(ge=0)
    fact_grounding_violation_count: int = Field(ge=0)
    hard_atom_violation_count: int = Field(ge=0)
    winner_language_violation_count: int = Field(ge=0)
    attribution_violation_count: int = Field(ge=0)
    fact_coverage_violation_count: int = Field(ge=0)
    internal_language_violation_count: int = Field(ge=0)
    hard_violation_count: int = Field(ge=0)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    p95_latency_ms: float = Field(ge=0.0, allow_inf_nan=False)
    results_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    passed: bool


class RealPresentationCopyReplayReport(_StrictFrozenModel):
    schema_version: Literal[
        "guide-real-presentation-copy-replay-v1"
    ] = "guide-real-presentation-copy-replay-v1"
    source_results_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cases_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_count: int = Field(ge=0)
    replayed_case_count: int = Field(ge=0)
    provider_call_count: Literal[0] = 0
    passed_count: int = Field(ge=0)
    hard_violation_count: int = Field(ge=0)
    rows: tuple[PresentationCopyGateRow, ...]
    passed: bool


def run_real_copy_gate(
    *,
    adapter,
    cases: Sequence[PresentationCopyGateCase],
    output_dir: str | Path,
    run_id: str,
) -> RealPresentationCopyReport:
    normalized = tuple(cases)
    if any(
        not isinstance(case, PresentationCopyGateCase)
        for case in normalized
    ):
        raise TypeError(
            "cases must contain PresentationCopyGateCase values"
        )
    case_ids = tuple(case.case_id for case in normalized)
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("real copy gate case IDs must be unique")
    if not hasattr(adapter, "write"):
        raise TypeError("adapter must expose write")

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    rows: list[RealPresentationCopyResult] = []
    evaluations: list[PresentationCopyGateRow] = []
    provider_call_count = 0
    stop_reason: Literal[
        "hard_violation",
        "invalid_output",
        "provider_failure",
        "adapter_error",
    ] | None = None
    for case in normalized:
        started = perf_counter()
        provider_call_count += 1
        try:
            call = adapter.write(case.packet)
            evaluation = evaluate_copy_gate_output(
                case=case,
                output=call.draft,
                provider_call_count=1,
            )
            draft = call.draft
            usage = call.usage
            status = "ok"
            failure_code = None
            raw_provider_output = call.raw_content
            trace_id = call.trace_id
        except SemanticProviderFailure as error:
            evaluation = evaluate_copy_gate_output(
                case=case,
                output={},
                provider_call_count=1,
            )
            draft = None
            usage = error.usage
            failure_code = error.code.value
            raw_provider_output = error.raw_content
            trace_id = error.trace_id
            status = (
                "invalid_output"
                if error.code.value
                in {"invalid_output", "forbidden_output"}
                else "provider_failure"
            )
        except Exception:
            evaluation = evaluate_copy_gate_output(
                case=case,
                output={},
                provider_call_count=1,
            )
            draft = None
            usage = None
            failure_code = None
            raw_provider_output = None
            trace_id = None
            status = "adapter_error"
        latency_ms = (perf_counter() - started) * 1000
        evaluations.append(evaluation)
        rows.append(
            RealPresentationCopyResult(
                case_id=case.case_id,
                input_sha256=_packet_sha256(case),
                status=status,
                provider_failure_code=failure_code,
                raw_provider_output=raw_provider_output,
                trace_id=trace_id,
                earliest_failure_layer=(
                    None
                    if status == "ok" and evaluation.passed
                    else "public_presentation"
                ),
                latency_ms=latency_ms,
                draft=draft,
                evaluation=evaluation,
                prompt_tokens=_usage_count(usage, "prompt_tokens"),
                completion_tokens=_usage_count(
                    usage,
                    "completion_tokens",
                ),
                total_tokens=_usage_count(usage, "total_tokens"),
            )
        )
        partial_result_bytes = _result_bytes(rows)
        _atomic_write(
            output / "results.jsonl",
            partial_result_bytes,
        )
        _atomic_write(
            output / "partial-summary.json",
            _canonical_json({
                "schema_version": (
                    "guide-real-presentation-copy-partial-v1"
                ),
                "expected_case_count": len(normalized),
                "provider_call_count": provider_call_count,
                "completed_case_count": len(rows),
                "last_case_id": case.case_id,
                "total_tokens": sum(
                    row.total_tokens for row in rows
                ),
                "results_sha256": sha256(
                    partial_result_bytes
                ).hexdigest(),
            })
            + b"\n",
        )
        print(
            "progress "
            f"case_id={case.case_id} "
            f"attempted_calls={provider_call_count} "
            f"total_tokens={sum(row.total_tokens for row in rows)}",
            flush=True,
        )
        if status != "ok":
            stop_reason = status
            break
        if evaluation.hard_violation_count:
            stop_reason = "hard_violation"
            break

    result_bytes = _result_bytes(rows)
    result_hash = sha256(result_bytes).hexdigest()
    _atomic_write(output / "results.jsonl", result_bytes)
    summary = summarize_copy_gate(evaluations)
    report = RealPresentationCopyReport(
        run_id=run_id,
        provider=str(getattr(adapter, "provider", "unknown")),
        model=str(getattr(adapter, "model", "unknown")),
        prompt_version=str(
            getattr(
                adapter,
                "prompt_version",
                PRESENTATION_COPY_PROMPT_VERSION,
            )
        ),
        cases_sha256=_cases_sha256(normalized),
        case_count=len(normalized),
        completed_case_count=len(rows),
        provider_call_count=provider_call_count,
        stopped_early=stop_reason is not None,
        stop_reason=stop_reason,
        schema_valid_count=summary.schema_valid_count,
        readability_passed_count=summary.readability_passed_count,
        fact_coverage_passed_count=(
            summary.fact_coverage_passed_count
        ),
        internal_language_passed_count=(
            summary.internal_language_passed_count
        ),
        passed_count=summary.passed_count,
        schema_valid_rate=summary.schema_valid_rate,
        readability_rate=summary.readability_rate,
        fact_coverage_rate=summary.fact_coverage_rate,
        minimum_fact_coverage=summary.minimum_fact_coverage,
        internal_language_rate=summary.internal_language_rate,
        provider_call_violation_count=(
            summary.provider_call_violation_count
            + max(0, provider_call_count - len(normalized))
        ),
        slot_binding_violation_count=(
            summary.slot_binding_violation_count
        ),
        fact_grounding_violation_count=(
            summary.fact_grounding_violation_count
        ),
        hard_atom_violation_count=(
            summary.hard_atom_violation_count
        ),
        winner_language_violation_count=(
            summary.winner_language_violation_count
        ),
        attribution_violation_count=(
            summary.attribution_violation_count
        ),
        fact_coverage_violation_count=(
            summary.fact_coverage_violation_count
        ),
        internal_language_violation_count=(
            summary.internal_language_violation_count
        ),
        hard_violation_count=summary.hard_violation_count,
        prompt_tokens=sum(row.prompt_tokens for row in rows),
        completion_tokens=sum(row.completion_tokens for row in rows),
        total_tokens=sum(row.total_tokens for row in rows),
        p95_latency_ms=_p95(
            tuple(row.latency_ms for row in rows)
        ),
        results_sha256=result_hash,
        passed=(
            provider_call_count == len(normalized)
            and stop_reason is None
            and summary.passed
        ),
    )
    summary_bytes = (
        _canonical_json(report.model_dump(mode="json")) + b"\n"
    )
    summary_hash = sha256(summary_bytes).hexdigest()
    _atomic_write(output / "summary.json", summary_bytes)
    _atomic_write(
        output / "SHA256SUMS",
        (
            f"{result_hash}  results.jsonl\n"
            f"{summary_hash}  summary.json\n"
        ).encode("ascii"),
    )
    return report


def replay_real_copy_gate_results(
    *,
    cases: Sequence[PresentationCopyGateCase],
    results_path: str | Path,
    output_path: str | Path,
) -> RealPresentationCopyReplayReport:
    normalized = tuple(cases)
    if any(
        not isinstance(case, PresentationCopyGateCase)
        for case in normalized
    ):
        raise TypeError(
            "cases must contain PresentationCopyGateCase values"
        )
    source = Path(results_path)
    source_bytes = source.read_bytes()
    raw_rows = tuple(
        json.loads(line)
        for line in source_bytes.decode("utf-8").splitlines()
        if line.strip()
    )
    expected_ids = tuple(case.case_id for case in normalized)
    actual_ids = tuple(
        row.get("case_id") if isinstance(row, dict) else None
        for row in raw_rows
    )
    if actual_ids != expected_ids:
        raise ValueError(
            "copywriter replay result identities must exactly match cases"
        )

    evaluations = tuple(
        evaluate_copy_gate_output(
            case=case,
            output=raw_row.get("draft") or {},
            provider_call_count=1,
        )
        for case, raw_row in zip(
            normalized,
            raw_rows,
            strict=True,
        )
    )
    summary = summarize_copy_gate(evaluations)
    report = RealPresentationCopyReplayReport(
        source_results_sha256=sha256(source_bytes).hexdigest(),
        cases_sha256=_cases_sha256(normalized),
        case_count=len(normalized),
        replayed_case_count=len(evaluations),
        passed_count=summary.passed_count,
        hard_violation_count=summary.hard_violation_count,
        rows=evaluations,
        passed=(
            bool(normalized)
            and len(evaluations) == len(normalized)
            and summary.passed
        ),
    )
    destination = Path(output_path)
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(
        destination,
        _canonical_json(report.model_dump(mode="json")) + b"\n",
    )
    return report


def validate_copywriter_call_budget(
    *,
    prior_calls: int,
    requested_calls: int,
    reserved_future_calls: int,
    call_cap: int,
) -> int:
    values = {
        "prior_calls": prior_calls,
        "requested_calls": requested_calls,
        "reserved_future_calls": reserved_future_calls,
        "call_cap": call_cap,
    }
    if any(
        not isinstance(value, int) or isinstance(value, bool)
        for value in values.values()
    ):
        raise TypeError("copywriter call budget values must be integers")
    if (
        prior_calls < 0
        or requested_calls < 0
        or reserved_future_calls < 0
        or call_cap <= 0
    ):
        raise ValueError("copywriter call budget values are invalid")
    projected = prior_calls + requested_calls + reserved_future_calls
    if projected > call_cap:
        raise ValueError(
            "copywriter call cap would be exceeded "
            f"(projected={projected}, cap={call_cap})"
        )
    return projected


def _p95(values: tuple[float, ...]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, (95 * len(ordered) + 99) // 100)
    return ordered[rank - 1]


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _packet_sha256(case: PresentationCopyGateCase) -> str:
    return sha256(
        _canonical_json(case.packet.model_dump(mode="json"))
    ).hexdigest()


def _cases_sha256(
    cases: Sequence[PresentationCopyGateCase],
) -> str:
    payload = b"".join(
        _canonical_json(case.model_dump(mode="json")) + b"\n"
        for case in cases
    )
    return sha256(payload).hexdigest()


def _usage_count(usage: object, field_name: str) -> int:
    if usage is None:
        return 0
    value = getattr(usage, field_name, None)
    return value if isinstance(value, int) else 0


def _result_bytes(
    rows: Sequence[RealPresentationCopyResult],
) -> bytes:
    return b"".join(
        _canonical_json(row.model_dump(mode="json")) + b"\n"
        for row in rows
    )


def _atomic_write(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default=str(DEFAULT_CASES))
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--key-path", default=DEFAULT_KEY_PATH)
    parser.add_argument("--model", default=DEEPSEEK_V4_PRO_MODEL)
    parser.add_argument(
        "--prior-call-count",
        type=int,
        required=True,
    )
    parser.add_argument(
        "--copywriter-call-cap",
        type=int,
        required=True,
    )
    parser.add_argument(
        "--reserved-future-calls",
        type=int,
        required=True,
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    cases = load_copy_gate_cases(args.cases)
    try:
        validate_copywriter_call_budget(
            prior_calls=args.prior_call_count,
            requested_calls=len(cases),
            reserved_future_calls=args.reserved_future_calls,
            call_cap=args.copywriter_call_cap,
        )
    except (TypeError, ValueError) as error:
        print(json.dumps({
            "status": "copywriter_call_cap_rejected",
            "detail": str(error),
        }))
        return 6
    try:
        api_key = read_private_api_key(args.key_path)
    except KeyPrecheckError as error:
        print(json.dumps({
            "status": "key_precheck_failed",
            "code": error.code.value,
        }))
        return 5
    adapter = DeepSeekPresentationCopywriterAdapter(
        api_key=api_key,
        model=args.model,
        timeout_seconds=30.0,
        max_tokens=COPY_GATE_MAX_TOKENS,
        temperature=0.3,
        daily_budget_cny=Decimal("100.00"),
        daily_call_cap=len(cases),
    )
    try:
        report = run_real_copy_gate(
            adapter=adapter,
            cases=cases,
            output_dir=args.output_dir,
            run_id=args.run_id,
        )
    finally:
        adapter.close()
    print(report.model_dump_json())
    return 0 if report.passed else 3


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "RealPresentationCopyReport",
    "RealPresentationCopyReplayReport",
    "RealPresentationCopyResult",
    "main",
    "replay_real_copy_gate_results",
    "run_real_copy_gate",
    "validate_copywriter_call_budget",
]
