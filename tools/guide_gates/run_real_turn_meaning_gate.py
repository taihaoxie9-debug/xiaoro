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

from app.guide.adapters.llm.contracts import (
    SemanticProviderFailure,
)
from app.guide.adapters.llm.deepseek_intent import (
    DEEPSEEK_V4_PRO_MODEL,
)
from app.guide.adapters.llm.deepseek_turn_meaning import (
    DeepSeekTurnMeaningAdapter,
)
from app.guide.intent.concept_preferences import (
    ConceptPreferenceCatalog,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning
from app.guide_runtime.composition import build_selection_concept_assets
from tools.guide_gates.run_official_deepseek_smoke import (
    DEFAULT_KEY_PATH,
    KeyPrecheckError,
    read_private_api_key,
)
from tools.guide_gates.turn_meaning_gate import (
    TurnMeaningGateCase,
    TurnMeaningGateRow,
    evaluate_gate_case,
    load_gate_cases,
    summarize_gate,
)


_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CASES = (
    _ROOT
    / "tests"
    / "fixtures"
    / "guide"
    / "intent"
    / "turn_meaning_gate_v1.jsonl"
)


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class RealTurnMeaningResult(_StrictFrozenModel):
    case_id: str
    status: Literal[
        "ok",
        "invalid_output",
        "provider_failure",
        "adapter_error",
    ]
    provider_failure_code: str | None
    latency_ms: float = Field(ge=0.0, allow_inf_nan=False)
    meaning: TurnMeaning | None
    evaluation: TurnMeaningGateRow | None
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class RealTurnMeaningReport(_StrictFrozenModel):
    schema_version: Literal[
        "guide-real-turn-meaning-gate-summary-v1"
    ] = "guide-real-turn-meaning-gate-summary-v1"
    model: str
    case_count: int = Field(ge=0)
    provider_call_count: int = Field(ge=0)
    schema_valid_count: int = Field(ge=0)
    translation_passed_count: int = Field(ge=0)
    source_grounded_count: int = Field(ge=0)
    binding_passed_count: int = Field(ge=0)
    task_plan_passed_count: int = Field(ge=0)
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
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    p95_latency_ms: float = Field(ge=0.0, allow_inf_nan=False)
    results_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    passed: bool


def run_real_gate(
    *,
    adapter,
    cases: Sequence[TurnMeaningGateCase],
    concept_catalog: ConceptPreferenceCatalog,
    output_dir: str | Path,
) -> RealTurnMeaningReport:
    normalized = tuple(cases)
    if any(
        not isinstance(case, TurnMeaningGateCase)
        for case in normalized
    ):
        raise TypeError(
            "cases must contain TurnMeaningGateCase values"
        )
    case_ids = tuple(case.case_id for case in normalized)
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("real gate case IDs must be unique")
    if not isinstance(concept_catalog, ConceptPreferenceCatalog):
        raise TypeError(
            "concept_catalog must be ConceptPreferenceCatalog"
        )
    if not hasattr(adapter, "propose_with_result"):
        raise TypeError("adapter must expose propose_with_result")

    rows: list[RealTurnMeaningResult] = []
    evaluations: list[TurnMeaningGateRow] = []
    provider_call_count = 0
    for case in normalized:
        started = perf_counter()
        provider_call_count += 1
        try:
            call = adapter.propose_with_result(
                case.message,
                case.context,
            )
            meaning = call.meaning
            usage = call.usage
            evaluation = evaluate_gate_case(
                case=case,
                meaning=meaning,
                concept_catalog=concept_catalog,
                provider_call_count=1,
            )
            evaluations.append(evaluation)
            status = "ok"
            failure_code = None
        except SemanticProviderFailure as error:
            meaning = None
            usage = None
            evaluation = None
            failure_code = error.code.value
            status = (
                "invalid_output"
                if error.code.value
                in {"invalid_output", "forbidden_output"}
                else "provider_failure"
            )
        except Exception:
            meaning = None
            usage = None
            evaluation = None
            failure_code = None
            status = "adapter_error"
        latency_ms = (perf_counter() - started) * 1000
        rows.append(
            RealTurnMeaningResult(
                case_id=case.case_id,
                status=status,
                provider_failure_code=failure_code,
                latency_ms=latency_ms,
                meaning=meaning,
                evaluation=evaluation,
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
    results_bytes = b"".join(
        _canonical_json(row.model_dump(mode="json")) + b"\n"
        for row in rows
    )
    results_hash = sha256(results_bytes).hexdigest()
    (output / "results.jsonl").write_bytes(results_bytes)
    gate_summary = summarize_gate(evaluations)
    report = RealTurnMeaningReport(
        model=str(getattr(adapter, "model", "unknown")),
        case_count=len(normalized),
        provider_call_count=provider_call_count,
        schema_valid_count=sum(row.status == "ok" for row in rows),
        translation_passed_count=sum(
            row.translation_passed for row in evaluations
        ),
        source_grounded_count=sum(
            row.source_grounded for row in evaluations
        ),
        binding_passed_count=sum(
            row.binding_passed for row in evaluations
        ),
        task_plan_passed_count=sum(
            row.task_plan_passed for row in evaluations
        ),
        passed_count=gate_summary.passed_count,
        end_to_end_rate=(
            gate_summary.passed_count / len(normalized)
            if normalized
            else 0.0
        ),
        provider_call_violation_count=(
            gate_summary.provider_call_violation_count
            + max(0, provider_call_count - len(normalized))
        ),
        invented_source_atom_count=(
            gate_summary.invented_source_atom_count
        ),
        ambiguous_source_atom_count=(
            gate_summary.ambiguous_source_atom_count
        ),
        unmentioned_state_change_count=(
            gate_summary.unmentioned_state_change_count
        ),
        unauthorized_state_transition_count=(
            gate_summary.unauthorized_state_transition_count
        ),
        hard_safety_override_count=(
            gate_summary.hard_safety_override_count
        ),
        wrong_product_selection_count=(
            gate_summary.wrong_product_selection_count
        ),
        ranking_answer_source_mismatch_count=(
            gate_summary.ranking_answer_source_mismatch_count
        ),
        prompt_tokens=sum(row.prompt_tokens for row in rows),
        completion_tokens=sum(
            row.completion_tokens for row in rows
        ),
        total_tokens=sum(row.total_tokens for row in rows),
        p95_latency_ms=_p95(
            tuple(row.latency_ms for row in rows)
        ),
        results_sha256=results_hash,
        passed=(
            len(normalized) == 128
            and provider_call_count == len(normalized)
            and gate_summary.provider_call_violation_count == 0
            and (
                gate_summary.passed_count / len(normalized)
            ) >= 0.90
            and gate_summary.invented_source_atom_count == 0
            and gate_summary.unmentioned_state_change_count == 0
            and gate_summary.unauthorized_state_transition_count == 0
            and gate_summary.hard_safety_override_count == 0
            and gate_summary.wrong_product_selection_count == 0
            and (
                gate_summary.ranking_answer_source_mismatch_count
                == 0
            )
        ),
    )
    summary_bytes = (
        _canonical_json(report.model_dump(mode="json")) + b"\n"
    )
    summary_hash = sha256(summary_bytes).hexdigest()
    (output / "summary.json").write_bytes(summary_bytes)
    (output / "SHA256SUMS").write_text(
        (
            f"{results_hash}  results.jsonl\n"
            f"{summary_hash}  summary.json\n"
        ),
        encoding="ascii",
    )
    return report


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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default=str(_DEFAULT_CASES))
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--key-path", default=DEFAULT_KEY_PATH)
    parser.add_argument("--model", default=DEEPSEEK_V4_PRO_MODEL)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        api_key = read_private_api_key(args.key_path)
    except KeyPrecheckError as error:
        print(json.dumps({
            "status": "key_precheck_failed",
            "code": error.code.value,
        }))
        return 5
    assets = build_selection_concept_assets()
    prompt_catalog = tuple(sorted({
        item.concept_id for item in assets.projections
    }))
    concept_catalog = ConceptPreferenceCatalog.from_projections(
        assets.projections
    )
    cases = load_gate_cases(args.cases)
    adapter = DeepSeekTurnMeaningAdapter(
        api_key=api_key,
        model=args.model,
        timeout_seconds=12.0,
        max_tokens=1024,
        concept_catalog=prompt_catalog,
        daily_budget_cny=Decimal("100.00"),
        daily_call_cap=len(cases),
    )
    try:
        report = run_real_gate(
            adapter=adapter,
            cases=cases,
            concept_catalog=concept_catalog,
            output_dir=args.output_dir,
        )
    finally:
        adapter.close()
    print(report.model_dump_json())
    return 0 if report.passed else 3


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "RealTurnMeaningReport",
    "RealTurnMeaningResult",
    "main",
    "run_real_gate",
]
