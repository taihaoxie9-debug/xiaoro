"""Run a bounded real-model probe sheet for transition semantics."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.guide.adapters.llm.contracts import SemanticProviderFailure
from app.guide.adapters.llm.deepseek_intent import (
    DEEPSEEK_V4_PRO_MODEL,
)
from app.guide.adapters.llm.deepseek_turn_meaning import (
    DeepSeekTurnMeaningAdapter,
)
from app.guide_runtime.composition import build_selection_concept_assets
from app.guide.understanding.contracts import TopicCode
from app.guide.understanding.semantic_contracts import SemanticContext
from app.guide.understanding.turn_meaning_contracts import (
    TurnMeaning,
    TurnOperationHint,
)
from tools.guide_gates.run_official_deepseek_smoke import (
    DEFAULT_KEY_PATH,
    KeyPrecheckError,
    read_private_api_key,
)


_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CASES = (
    _ROOT
    / "tests"
    / "fixtures"
    / "guide"
    / "intent"
    / "transition_probes_3x6_v1.jsonl"
)
DEFAULT_PROBE_DAILY_BUDGET_CNY = Decimal("100.00")

ProbeState = Literal[
    "recommendation_batch",
    "single_product_focus",
    "comparison_batch",
    "consultation",
    "general_knowledge",
    "confirmed_image_product",
]
ReferenceExpectation = Literal[
    "none",
    "product_single",
    "product_batch",
    "focused_image",
]


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class TransitionProbeCase(_StrictFrozen):
    case_id: str = Field(min_length=1, max_length=128)
    state: ProbeState
    message: str = Field(min_length=1, max_length=4000)
    context: SemanticContext
    allowed_operations: tuple[TurnOperationHint, ...] = Field(
        min_length=1,
    )
    allowed_topics: tuple[TopicCode | None, ...] = Field(
        min_length=1,
    )
    required_reference: ReferenceExpectation
    forbidden_operations: tuple[TurnOperationHint, ...] = ()

class TransitionProbeRow(_StrictFrozen):
    case_id: str
    status: Literal[
        "ok",
        "invalid_output",
        "provider_failure",
        "adapter_error",
    ]
    failures: tuple[
        Literal[
            "operation",
            "topic",
            "required_reference",
            "forbidden_operation",
        ],
        ...,
    ]
    provider_failure_code: str | None
    latency_ms: float = Field(ge=0.0, allow_inf_nan=False)
    meaning: TurnMeaning | None
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)

class TransitionProbeReport(_StrictFrozen):
    schema_version: Literal[
        "guide-real-transition-probe-summary-v1"
    ] = "guide-real-transition-probe-summary-v1"
    model: str
    case_count: int = Field(ge=0)
    provider_call_count: int = Field(ge=0)
    passed_count: int = Field(ge=0)
    operation_failure_count: int = Field(ge=0)
    topic_failure_count: int = Field(ge=0)
    reference_failure_count: int = Field(ge=0)
    forbidden_operation_count: int = Field(ge=0)
    provider_failure_count: int = Field(ge=0)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    results_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    passed: bool


def load_transition_probes(
    path: str | Path,
) -> tuple[TransitionProbeCase, ...]:
    probe_path = Path(path)
    rows = tuple(
        TransitionProbeCase.model_validate_json(line, strict=True)
        for line in probe_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    case_ids = tuple(item.case_id for item in rows)
    if not rows:
        raise ValueError("transition probe sheet is empty")
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("transition probe case IDs must be unique")
    return rows


def run_transition_probes(
    *,
    adapter,
    cases: Sequence[TransitionProbeCase],
    output_dir: str | Path,
) -> TransitionProbeReport:
    normalized = tuple(cases)
    if not normalized or any(
        type(case) is not TransitionProbeCase
        for case in normalized
    ):
        raise TypeError(
            "cases must contain nonempty exact TransitionProbeCase values"
        )
    if not hasattr(adapter, "propose_with_result"):
        raise TypeError("adapter must expose propose_with_result")
    rows: list[TransitionProbeRow] = []
    for case in normalized:
        started = perf_counter()
        try:
            call = adapter.propose_with_result(case.message, case.context)
            meaning = call.meaning
            usage = call.usage
            failures = _evaluate_probe(case, meaning)
            status = "ok"
            failure_code = None
        except SemanticProviderFailure as error:
            meaning = None
            usage = error.usage
            failures = ()
            failure_code = error.code.value
            status = (
                "invalid_output"
                if error.code.value in {"invalid_output", "forbidden_output"}
                else "provider_failure"
            )
        except Exception:
            meaning = None
            usage = None
            failures = ()
            failure_code = None
            status = "adapter_error"
        rows.append(
            TransitionProbeRow(
                case_id=case.case_id,
                status=status,
                failures=failures,
                provider_failure_code=failure_code,
                latency_ms=(perf_counter() - started) * 1000,
                meaning=meaning,
                prompt_tokens=(
                    usage.prompt_tokens if usage is not None else 0
                ),
                completion_tokens=(
                    usage.completion_tokens
                    if usage is not None
                    else 0
                ),
                total_tokens=(
                    usage.total_tokens if usage is not None else 0
                ),
            )
        )
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    results = b"".join(
        _canonical_json(row.model_dump(mode="json")) + b"\n"
        for row in rows
    )
    results_sha256 = sha256(results).hexdigest()
    (output / "results.jsonl").write_bytes(results)
    report = TransitionProbeReport(
        model=str(getattr(adapter, "model", "unknown")),
        case_count=len(rows),
        provider_call_count=len(rows),
        passed_count=sum(
            row.status == "ok" and not row.failures
            for row in rows
        ),
        operation_failure_count=sum(
            "operation" in row.failures for row in rows
        ),
        topic_failure_count=sum(
            "topic" in row.failures for row in rows
        ),
        reference_failure_count=sum(
            "required_reference" in row.failures for row in rows
        ),
        forbidden_operation_count=sum(
            "forbidden_operation" in row.failures for row in rows
        ),
        provider_failure_count=sum(
            row.status != "ok" for row in rows
        ),
        prompt_tokens=sum(row.prompt_tokens for row in rows),
        completion_tokens=sum(
            row.completion_tokens for row in rows
        ),
        total_tokens=sum(row.total_tokens for row in rows),
        results_sha256=results_sha256,
        passed=all(
            row.status == "ok" and not row.failures
            for row in rows
        ),
    )
    summary = _canonical_json(report.model_dump(mode="json")) + b"\n"
    (output / "summary.json").write_bytes(summary)
    (output / "SHA256SUMS").write_text(
        (
            f"{results_sha256}  results.jsonl\n"
            f"{sha256(summary).hexdigest()}  summary.json\n"
        ),
        encoding="ascii",
    )
    return report


def _evaluate_probe(
    case: TransitionProbeCase,
    meaning: TurnMeaning,
) -> tuple[
    Literal[
        "operation",
        "topic",
        "required_reference",
        "forbidden_operation",
    ],
    ...,
]:
    failures: list[
        Literal[
            "operation",
            "topic",
            "required_reference",
            "forbidden_operation",
        ]
    ] = []
    if meaning.operation_hint not in case.allowed_operations:
        failures.append("operation")
    if meaning.topic_hint not in case.allowed_topics:
        failures.append("topic")
    if meaning.operation_hint in case.forbidden_operations:
        failures.append("forbidden_operation")
    if not _matches_reference(case, meaning):
        failures.append("required_reference")
    return tuple(failures)


def _matches_reference(
    case: TransitionProbeCase,
    meaning: TurnMeaning,
) -> bool:
    if case.required_reference == "none":
        return True
    if case.required_reference == "product_batch":
        return any(
            item.object_family_hint == "product"
            and item.plurality_hint == "batch"
            for item in meaning.reference_mentions
        )
    if case.required_reference == "product_single":
        return any(
            item.object_family_hint == "product"
            and item.plurality_hint == "single"
            for item in meaning.reference_mentions
        )
    focused = case.context.focused_image_ordinal
    return any(
        item.object_family_hint == "image"
        and item.ordinal_hint == focused
        for item in meaning.reference_mentions
    )


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=_DEFAULT_CASES)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--key-path", default=DEFAULT_KEY_PATH)
    parser.add_argument("--model", default=DEEPSEEK_V4_PRO_MODEL)
    args = parser.parse_args(argv)
    try:
        api_key = read_private_api_key(args.key_path)
    except KeyPrecheckError as error:
        print(json.dumps({
            "status": "key_precheck_failed",
            "code": error.code.value,
        }))
        return 5
    assets = build_selection_concept_assets()
    catalog = tuple(sorted({
        item.concept_id for item in assets.projections
    }))
    cases = load_transition_probes(args.cases)
    adapter = DeepSeekTurnMeaningAdapter(
        api_key=api_key,
        model=args.model,
        timeout_seconds=20.0,
        max_tokens=1024,
        concept_catalog=catalog,
        daily_budget_cny=DEFAULT_PROBE_DAILY_BUDGET_CNY,
        daily_call_cap=len(cases),
    )
    try:
        report = run_transition_probes(
            adapter=adapter,
            cases=cases,
            output_dir=args.output_dir,
        )
    finally:
        adapter.close()
    print(report.model_dump_json())
    return 0 if report.passed else 3


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "TransitionProbeCase",
    "TransitionProbeReport",
    "load_transition_probes",
    "main",
    "run_transition_probes",
]
