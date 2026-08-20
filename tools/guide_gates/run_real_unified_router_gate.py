from __future__ import annotations

import argparse
from collections.abc import Sequence
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_serializer,
    model_validator,
)

from app.guide.adapters.llm.contracts import SemanticProviderFailure
from app.guide.adapters.llm.deepseek_intent import (
    DEEPSEEK_V4_PRO_MODEL,
)
from app.guide.adapters.llm.deepseek_turn_meaning import (
    DeepSeekTurnMeaningAdapter,
)
from app.guide.feedback.contracts import ConversationSnapshot
from app.guide.intent.concept_preferences import ConceptPreferenceCatalog
from app.guide.presentation.copywriter_contracts import PresentationMode
from app.guide.retrieval.product_name_resolver import (
    ResolvedProductBinding,
)
from app.guide.understanding.context_resolver import (
    resolve_semantic_context,
)
from app.guide.understanding.semantic_contracts import SemanticContext
from app.guide.understanding.turn_meaning_contracts import TurnMeaning
from app.guide_runtime.composition import build_selection_concept_assets
from tools.guide_gates.run_official_deepseek_smoke import (
    DEFAULT_KEY_PATH,
    KeyPrecheckError,
    read_private_api_key,
)
from tools.guide_gates.unified_router_gate import (
    ReplayCase,
    ReplayResult,
    ReplayTrace,
    RouteExpectation,
    SemanticExpectation,
    evaluate_replay_trace,
    execute_replay_case,
    legacy_replay_payload,
)


GateCategory = Literal[
    "recommendation",
    "comparison",
    "product_knowledge",
    "general_knowledge",
    "image",
    "consultation",
    "clarification",
    "safety",
    "state_transition",
]
RealTaskMode = Literal[
    "recommend",
    "comparison",
    "suitability",
    "knowledge",
    "followup",
    "clarify",
]


class _StrictFrozen(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )


class RealUnifiedRouterCase(_StrictFrozen):
    schema_version: Literal[
        "guide-real-unified-router-case-v1"
    ] = "guide-real-unified-router-case-v1"
    case_id: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[a-z0-9][a-z0-9_-]+$",
    )
    category: GateCategory
    message: str = Field(min_length=1, max_length=4000)
    starting_snapshot: ConversationSnapshot | None
    acceptable_semantic: SemanticExpectation
    expected_bindings: tuple[ResolvedProductBinding, ...] = ()
    expected_route: RouteExpectation
    expected_final_snapshot: dict[str, JsonValue]
    expected_task_plan: dict[str, JsonValue]
    acceptable_task_modes: tuple[RealTaskMode, ...] = ()
    expected_card_ids: tuple[int, ...] = Field(
        default_factory=tuple,
        max_length=3,
    )
    expected_safety: bool
    expected_clarification: bool
    expected_presentation_mode: PresentationMode | None
    acceptable_presentation_modes: tuple[
        PresentationMode | None,
        ...,
    ] = Field(min_length=1)

    @field_validator(
        "expected_bindings",
        "expected_card_ids",
        "acceptable_task_modes",
        "acceptable_presentation_modes",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_serializer(mode="wrap")
    def serialize_legacy_replay_payload(self, handler):
        return legacy_replay_payload(handler(self))

    @model_validator(mode="after")
    def validate_acceptable_execution_ranges(self) -> Self:
        if len(self.acceptable_task_modes) != len(
            set(self.acceptable_task_modes)
        ):
            raise ValueError(
                "acceptable task modes must be unique"
            )
        if len(self.acceptable_presentation_modes) != len(
            set(self.acceptable_presentation_modes)
        ):
            raise ValueError(
                "acceptable presentation modes must be unique"
            )
        expected_task_mode = self.expected_task_plan.get("mode")
        if (
            isinstance(expected_task_mode, str)
            and expected_task_mode not in self.acceptable_task_modes
        ):
            raise ValueError(
                "expected task mode must be acceptable"
            )
        if (
            self.expected_presentation_mode
            not in self.acceptable_presentation_modes
        ):
            raise ValueError(
                "expected presentation mode must be acceptable"
            )
        return self

    @classmethod
    def from_replay_case(
        cls,
        replay: ReplayCase,
        *,
        category: GateCategory,
    ) -> Self:
        if type(replay) is not ReplayCase:
            raise TypeError("replay must be an exact ReplayCase")
        return cls(
            case_id=replay.case_id,
            category=category,
            message=replay.message,
            starting_snapshot=replay.starting_snapshot,
            acceptable_semantic=replay.acceptable_semantic,
            expected_bindings=replay.expected_bindings,
            expected_route=replay.expected_route,
            expected_final_snapshot=replay.expected_final_snapshot,
            expected_task_plan=replay.expected_task_plan,
            acceptable_task_modes=(
                (replay.expected_task_plan["mode"],)
                if isinstance(
                    replay.expected_task_plan.get("mode"),
                    str,
                )
                else ()
            ),
            expected_card_ids=replay.expected_card_ids,
            expected_safety=replay.expected_safety,
            expected_clarification=replay.expected_clarification,
            expected_presentation_mode=(
                replay.expected_presentation_mode
            ),
            acceptable_presentation_modes=(
                replay.expected_presentation_mode,
            ),
        )

    def to_replay_case(self, meaning: TurnMeaning) -> ReplayCase:
        if type(meaning) is not TurnMeaning:
            raise TypeError("meaning must be an exact TurnMeaning")
        return ReplayCase(
            case_id=self.case_id,
            message=self.message,
            starting_snapshot=self.starting_snapshot,
            raw_turn_meaning=meaning,
            acceptable_semantic=self.acceptable_semantic,
            expected_bindings=self.expected_bindings,
            expected_route=self.expected_route,
            expected_final_snapshot=self.expected_final_snapshot,
            expected_task_plan=self.expected_task_plan,
            expected_card_ids=self.expected_card_ids,
            expected_safety=self.expected_safety,
            expected_clarification=self.expected_clarification,
            expected_presentation_mode=self.expected_presentation_mode,
        )

    def to_evaluation_replay_case(
        self,
        meaning: TurnMeaning,
        *,
        task_mode: str | None,
        presentation_mode: PresentationMode | None,
    ) -> ReplayCase:
        replay = self.to_replay_case(meaning)
        expected_task_plan = dict(self.expected_task_plan)
        if task_mode in self.acceptable_task_modes:
            expected_task_plan["mode"] = task_mode
        expected_presentation_mode = self.expected_presentation_mode
        if presentation_mode in self.acceptable_presentation_modes:
            expected_presentation_mode = presentation_mode
        return replay.model_copy(
            update={
                "expected_task_plan": expected_task_plan,
                "expected_presentation_mode": (
                    expected_presentation_mode
                ),
            },
            deep=True,
        )


class RealUnifiedRouterManifest(_StrictFrozen):
    schema_version: Literal[
        "guide-real-unified-router-manifest-v1"
    ] = "guide-real-unified-router-manifest-v1"
    case_count: int = Field(ge=1)
    cases_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RealUnifiedRouterResult(_StrictFrozen):
    case_id: str
    category: GateCategory
    status: Literal[
        "ok",
        "invalid_output",
        "provider_failure",
        "adapter_error",
        "local_execution_error",
    ]
    provider_failure_code: str | None
    input: dict[str, JsonValue]
    semantic_context: SemanticContext
    provider_raw_output: str | None
    provider_trace_id: str | None
    provider_output: TurnMeaning | None
    trace: ReplayTrace | None
    evaluation: ReplayResult | None
    latency_ms: float = Field(ge=0.0, allow_inf_nan=False)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_raw_output_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )
    provider_output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RealUnifiedRouterReport(_StrictFrozen):
    schema_version: Literal[
        "guide-real-unified-router-summary-v1"
    ] = "guide-real-unified-router-summary-v1"
    model: str
    prompt_version: str
    case_count: int = Field(ge=0)
    provider_call_count: int = Field(ge=0)
    copywriter_call_count: Literal[0] = 0
    passed_count: int = Field(ge=0)
    end_to_end_rate: float = Field(ge=0.0, le=1.0)
    category_rates: dict[str, float]
    wrong_product_selection_count: int = Field(ge=0)
    unauthorized_state_transition_count: int = Field(ge=0)
    hard_condition_override_count: int = Field(ge=0)
    unsafe_downgrade_count: int = Field(ge=0)
    cross_session_leak_count: int = Field(ge=0)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    p95_latency_ms: float = Field(ge=0.0, allow_inf_nan=False)
    results_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    passed: bool


class CapturedUnifiedRouterReplayReport(_StrictFrozen):
    schema_version: Literal[
        "guide-captured-unified-router-replay-summary-v2"
    ] = "guide-captured-unified-router-replay-summary-v2"
    case_count: int = Field(ge=0)
    captured_output_count: int = Field(ge=0)
    replayed_count: int = Field(ge=0)
    provider_call_count: Literal[0] = 0
    copywriter_call_count: Literal[0] = 0
    passed_count: int = Field(ge=0)
    end_to_end_rate: float = Field(ge=0.0, le=1.0)
    category_rates: dict[str, float]
    wrong_product_selection_count: int = Field(ge=0)
    unauthorized_state_transition_count: int = Field(ge=0)
    hard_condition_override_count: int = Field(ge=0)
    unsafe_downgrade_count: int = Field(ge=0)
    cross_session_leak_count: int = Field(ge=0)
    results_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    passed: bool


def build_real_case_manifest(
    cases_bytes: bytes,
    *,
    cases: tuple[RealUnifiedRouterCase, ...],
) -> RealUnifiedRouterManifest:
    if not isinstance(cases_bytes, bytes):
        raise TypeError("cases_bytes must be bytes")
    if not cases or any(
        type(case) is not RealUnifiedRouterCase
        for case in cases
    ):
        raise TypeError(
            "cases must be a nonempty tuple of exact "
            "RealUnifiedRouterCase values"
        )
    case_ids = tuple(case.case_id for case in cases)
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("real unified router case IDs must be unique")
    return RealUnifiedRouterManifest(
        case_count=len(cases),
        cases_sha256=sha256(cases_bytes).hexdigest(),
        case_ids_sha256=sha256(
            ("\n".join(case_ids) + "\n").encode("utf-8")
        ).hexdigest(),
    )


def load_real_unified_router_cases(
    cases_path: str | Path,
    *,
    manifest_path: str | Path,
) -> tuple[RealUnifiedRouterCase, ...]:
    raw = Path(cases_path).read_bytes()
    manifest = RealUnifiedRouterManifest.model_validate_json(
        Path(manifest_path).read_text(encoding="utf-8"),
        strict=True,
    )
    if sha256(raw).hexdigest() != manifest.cases_sha256:
        raise ValueError(
            "real unified router cases SHA-256 does not match manifest"
        )
    cases = tuple(
        RealUnifiedRouterCase.model_validate_json(
            line,
            strict=True,
        )
        for line in raw.splitlines()
        if line.strip()
    )
    actual = build_real_case_manifest(raw, cases=cases)
    if actual.case_count != manifest.case_count:
        raise ValueError(
            "real unified router case count does not match manifest"
        )
    if actual.case_ids_sha256 != manifest.case_ids_sha256:
        raise ValueError(
            "real unified router case ID SHA-256 does not match manifest"
        )
    return cases


def run_real_unified_router_gate(
    *,
    adapter,
    cases: Sequence[RealUnifiedRouterCase],
    concept_catalog: ConceptPreferenceCatalog,
    repo_root: str | Path,
    state_root: str | Path,
    output_path: str | Path,
) -> RealUnifiedRouterReport:
    normalized = tuple(cases)
    if not normalized or any(
        type(case) is not RealUnifiedRouterCase
        for case in normalized
    ):
        raise TypeError(
            "cases must be a nonempty sequence of exact "
            "RealUnifiedRouterCase values"
        )
    case_ids = tuple(case.case_id for case in normalized)
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("real unified router case IDs must be unique")
    if not isinstance(concept_catalog, ConceptPreferenceCatalog):
        raise TypeError(
            "concept_catalog must be ConceptPreferenceCatalog"
        )
    if not callable(getattr(adapter, "propose_with_result", None)):
        raise TypeError("adapter must expose propose_with_result")
    root = Path(repo_root).resolve()
    if not root.is_dir():
        raise ValueError("repo_root must be a directory")
    state_directory = Path(state_root).resolve()
    state_directory.mkdir(parents=True, exist_ok=False)

    rows: list[RealUnifiedRouterResult] = []
    provider_call_count = 0
    for case in normalized:
        context = resolve_semantic_context(
            conversation_version=(
                case.starting_snapshot.version
                if case.starting_snapshot is not None
                else 0
            ),
            snapshot=case.starting_snapshot,
        )
        input_payload: dict[str, JsonValue] = {
            "message": case.message,
            "starting_snapshot": (
                case.starting_snapshot.model_dump(mode="json")
                if case.starting_snapshot is not None
                else None
            ),
        }
        started = perf_counter()
        provider_call_count += 1
        meaning = None
        trace = None
        evaluation = None
        usage = None
        provider_raw_output = None
        provider_trace_id = None
        failure_code = None
        try:
            call = adapter.propose_with_result(case.message, context)
            meaning = call.meaning
            usage = call.usage
            provider_raw_output = call.raw_content
            provider_trace_id = call.trace_id
            replay = case.to_replay_case(meaning)
            trace = execute_replay_case(
                replay,
                repo_root=root,
                state_root=state_directory / case.case_id,
            )
            evaluation_replay = case.to_evaluation_replay_case(
                meaning,
                task_mode=(
                    trace.task_plan.get("mode")
                    if isinstance(
                        trace.task_plan.get("mode"),
                        str,
                    )
                    else None
                ),
                presentation_mode=trace.presentation_mode,
            )
            evaluation = evaluate_replay_trace(
                case=evaluation_replay,
                trace=trace,
            )
            status = "ok"
        except SemanticProviderFailure as error:
            failure_code = error.code.value
            provider_raw_output = error.raw_content
            provider_trace_id = error.trace_id
            usage = error.usage
            status = (
                "invalid_output"
                if error.code.value
                in {"invalid_output", "forbidden_output"}
                else "provider_failure"
            )
        except (TypeError, ValueError):
            status = "adapter_error" if meaning is None else (
                "local_execution_error"
            )
        except Exception:
            status = "local_execution_error"
        latency_ms = (perf_counter() - started) * 1000
        prompt_tokens = _usage_value(usage, "prompt_tokens")
        completion_tokens = _usage_value(
            usage,
            "completion_tokens",
        )
        total_tokens = _usage_value(usage, "total_tokens")
        provider_payload = (
            meaning.model_dump(mode="json")
            if meaning is not None
            else None
        )
        row_hash_payload = {
            "case_id": case.case_id,
            "category": case.category,
            "status": status,
            "provider_failure_code": failure_code,
            "input": input_payload,
            "semantic_context": context.model_dump(mode="json"),
            "provider_raw_output": provider_raw_output,
            "provider_trace_id": provider_trace_id,
            "provider_output": provider_payload,
            "trace": (
                trace.model_dump(mode="json")
                if trace is not None
                else None
            ),
            "evaluation": (
                evaluation.model_dump(mode="json")
                if evaluation is not None
                else None
            ),
            "latency_ms": latency_ms,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "input_sha256": _hash_json(input_payload),
            "context_sha256": _hash_json(
                context.model_dump(mode="json")
            ),
            "provider_raw_output_sha256": _hash_raw_output(
                provider_raw_output
            ),
            "provider_output_sha256": _hash_json(provider_payload),
        }
        rows.append(
            RealUnifiedRouterResult(
                case_id=case.case_id,
                category=case.category,
                status=status,
                provider_failure_code=failure_code,
                input=input_payload,
                semantic_context=context,
                provider_raw_output=provider_raw_output,
                provider_trace_id=provider_trace_id,
                provider_output=meaning,
                trace=trace,
                evaluation=evaluation,
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                input_sha256=row_hash_payload["input_sha256"],
                context_sha256=row_hash_payload["context_sha256"],
                provider_raw_output_sha256=(
                    row_hash_payload["provider_raw_output_sha256"]
                ),
                provider_output_sha256=(
                    row_hash_payload["provider_output_sha256"]
                ),
                result_sha256=_hash_json(row_hash_payload),
            )
        )

    report = _summarize(
        rows=tuple(rows),
        provider_call_count=provider_call_count,
        model=str(getattr(adapter, "model", "unknown")),
        prompt_version=str(
            getattr(adapter, "prompt_version", "unknown")
        ),
    )
    artifact = {
        "summary": report.model_dump(mode="json"),
        "results": [
            row.model_dump(mode="json")
            for row in rows
        ],
    }
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(_canonical_json(artifact) + b"\n")
    return report


def replay_captured_unified_router_results(
    *,
    cases: Sequence[RealUnifiedRouterCase],
    evidence_path: str | Path,
    repo_root: str | Path,
    state_root: str | Path,
    output_path: str | Path,
) -> CapturedUnifiedRouterReplayReport:
    normalized = tuple(cases)
    if not normalized or any(
        type(case) is not RealUnifiedRouterCase
        for case in normalized
    ):
        raise TypeError(
            "cases must be a nonempty sequence of exact "
            "RealUnifiedRouterCase values"
        )
    case_ids = tuple(case.case_id for case in normalized)
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("captured replay case IDs must be unique")
    by_id = {case.case_id: case for case in normalized}
    artifact = json.loads(
        Path(evidence_path).read_text(encoding="utf-8")
    )
    source_rows = artifact.get("results")
    if not isinstance(source_rows, list):
        raise ValueError("captured evidence must contain results")
    source_by_id = {
        row.get("case_id"): row
        for row in source_rows
        if isinstance(row, dict)
        and isinstance(row.get("case_id"), str)
    }
    if set(source_by_id) != set(by_id):
        raise ValueError(
            "captured evidence case IDs do not match frozen cases"
        )
    root = Path(repo_root).resolve()
    if not root.is_dir():
        raise ValueError("repo_root must be a directory")
    state_directory = Path(state_root).resolve()
    state_directory.mkdir(parents=True, exist_ok=False)

    replay_rows: list[dict[str, JsonValue]] = []
    evaluations: list[ReplayResult] = []
    captured_count = 0
    for case in normalized:
        source = source_by_id[case.case_id]
        provider_output = source.get("provider_output")
        if provider_output is None:
            continue
        captured_count += 1
        meaning = TurnMeaning.model_validate(
            provider_output,
            strict=True,
        )
        replay = case.to_replay_case(meaning)
        trace = execute_replay_case(
            replay,
            repo_root=root,
            state_root=state_directory / case.case_id,
        )
        evaluation_replay = case.to_evaluation_replay_case(
            meaning,
            task_mode=(
                trace.task_plan.get("mode")
                if isinstance(
                    trace.task_plan.get("mode"),
                    str,
                )
                else None
            ),
            presentation_mode=trace.presentation_mode,
        )
        evaluation = evaluate_replay_trace(
            case=evaluation_replay,
            trace=trace,
        )
        evaluations.append(evaluation)
        replay_rows.append({
            "case_id": case.case_id,
            "category": case.category,
            "provider_output_sha256": str(
                source.get("provider_output_sha256") or ""
            ),
            "trace": trace.model_dump(mode="json"),
            "evaluation": evaluation.model_dump(mode="json"),
        })
    wrong_products = sum(
        row.wrong_product_selection_count
        for row in evaluations
    )
    unauthorized = sum(
        row.unauthorized_state_transition_count
        for row in evaluations
    )
    hard_overrides = sum(
        row.hard_condition_override_count
        for row in evaluations
    )
    unsafe = sum(
        row.unsafe_downgrade_count
        for row in evaluations
    )
    cross_leaks = sum(
        row.cross_session_leak_count
        for row in evaluations
    )
    passed_count = sum(row.passed for row in evaluations)
    evaluation_by_id = {
        evaluation.case_id: evaluation
        for evaluation in evaluations
    }
    categories = tuple(sorted({case.category for case in normalized}))
    category_rates = {
        category: (
            sum(
                evaluation_by_id.get(case.case_id) is not None
                and evaluation_by_id[case.case_id].passed
                for case in normalized
                if case.category == category
            )
            / sum(case.category == category for case in normalized)
        )
        for category in categories
    }
    end_to_end_rate = passed_count / len(normalized)
    results_hash = _hash_json(replay_rows)
    report = CapturedUnifiedRouterReplayReport(
        case_count=len(normalized),
        captured_output_count=captured_count,
        replayed_count=len(evaluations),
        passed_count=passed_count,
        end_to_end_rate=end_to_end_rate,
        category_rates=category_rates,
        wrong_product_selection_count=wrong_products,
        unauthorized_state_transition_count=unauthorized,
        hard_condition_override_count=hard_overrides,
        unsafe_downgrade_count=unsafe,
        cross_session_leak_count=cross_leaks,
        results_sha256=results_hash,
        passed=captured_replay_meets_blind_thresholds(
            case_count=len(normalized),
            captured_output_count=captured_count,
            end_to_end_rate=end_to_end_rate,
            category_rates=category_rates,
            wrong_product_selection_count=wrong_products,
            unauthorized_state_transition_count=unauthorized,
            hard_condition_override_count=hard_overrides,
            unsafe_downgrade_count=unsafe,
            cross_session_leak_count=cross_leaks,
        ),
    )
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(
        _canonical_json({
            "summary": report.model_dump(mode="json"),
            "results": replay_rows,
        })
        + b"\n"
    )
    return report


def captured_replay_meets_blind_thresholds(
    *,
    case_count: int,
    captured_output_count: int,
    end_to_end_rate: float,
    category_rates: dict[str, float],
    wrong_product_selection_count: int,
    unauthorized_state_transition_count: int,
    hard_condition_override_count: int,
    unsafe_downgrade_count: int,
    cross_session_leak_count: int,
) -> bool:
    return (
        case_count > 0
        and captured_output_count == case_count
        and end_to_end_rate >= 0.90
        and bool(category_rates)
        and all(rate >= 0.80 for rate in category_rates.values())
        and wrong_product_selection_count == 0
        and unauthorized_state_transition_count == 0
        and hard_condition_override_count == 0
        and unsafe_downgrade_count == 0
        and cross_session_leak_count == 0
    )


def _build_adapter(
    *,
    api_key: str,
    model: str,
    concept_ids: tuple[str, ...],
    case_count: int,
):
    return DeepSeekTurnMeaningAdapter(
        api_key=api_key,
        model=model,
        timeout_seconds=20.0,
        max_tokens=1024,
        concept_catalog=concept_ids,
        daily_budget_cny=Decimal("100.00"),
        daily_call_cap=case_count,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run one-call real-model Unified Guide Router cases "
            "with the copywriter disabled."
        ),
    )
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
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
        required=True,
    )
    args = parser.parse_args(argv)
    if args.output.exists():
        print(json.dumps({
            "status": "output_exists",
            "path": str(args.output),
        }))
        return 4
    cases = load_real_unified_router_cases(
        args.cases,
        manifest_path=args.manifest,
    )
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
    concept_catalog = ConceptPreferenceCatalog.from_projections(
        assets.projections
    )
    adapter = _build_adapter(
        api_key=api_key,
        model=args.model,
        concept_ids=concept_ids,
        case_count=len(cases),
    )
    try:
        with TemporaryDirectory(
            prefix="xiaoro-real-unified-router-"
        ) as temporary:
            report = run_real_unified_router_gate(
                adapter=adapter,
                cases=cases,
                concept_catalog=concept_catalog,
                repo_root=args.repo_root,
                state_root=Path(temporary) / "state",
                output_path=args.output,
            )
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            close()
    print(report.model_dump_json())
    return 0 if report.passed else 3


def _summarize(
    *,
    rows: tuple[RealUnifiedRouterResult, ...],
    provider_call_count: int,
    model: str,
    prompt_version: str,
) -> RealUnifiedRouterReport:
    passed_count = sum(
        row.evaluation is not None and row.evaluation.passed
        for row in rows
    )
    categories = tuple(sorted({row.category for row in rows}))
    category_rates = {
        category: (
            sum(
                row.evaluation is not None
                and row.evaluation.passed
                for row in rows
                if row.category == category
            )
            / sum(row.category == category for row in rows)
        )
        for category in categories
    }
    wrong_products = sum(
        row.evaluation.wrong_product_selection_count
        for row in rows
        if row.evaluation is not None
    )
    unauthorized = sum(
        row.evaluation.unauthorized_state_transition_count
        for row in rows
        if row.evaluation is not None
    )
    hard_overrides = sum(
        row.evaluation.hard_condition_override_count
        for row in rows
        if row.evaluation is not None
    )
    unsafe = sum(
        row.evaluation.unsafe_downgrade_count
        for row in rows
        if row.evaluation is not None
    )
    cross_leaks = sum(
        row.evaluation.cross_session_leak_count
        for row in rows
        if row.evaluation is not None
    )
    rate = passed_count / len(rows) if rows else 0.0
    results_payload = [
        row.model_dump(mode="json")
        for row in rows
    ]
    return RealUnifiedRouterReport(
        model=model,
        prompt_version=prompt_version,
        case_count=len(rows),
        provider_call_count=provider_call_count,
        passed_count=passed_count,
        end_to_end_rate=rate,
        category_rates=category_rates,
        wrong_product_selection_count=wrong_products,
        unauthorized_state_transition_count=unauthorized,
        hard_condition_override_count=hard_overrides,
        unsafe_downgrade_count=unsafe,
        cross_session_leak_count=cross_leaks,
        prompt_tokens=sum(row.prompt_tokens for row in rows),
        completion_tokens=sum(
            row.completion_tokens for row in rows
        ),
        total_tokens=sum(row.total_tokens for row in rows),
        p95_latency_ms=_p95(
            tuple(row.latency_ms for row in rows)
        ),
        results_sha256=_hash_json(results_payload),
        passed=(
            bool(rows)
            and provider_call_count == len(rows)
            and rate >= 0.90
            and all(value >= 0.80 for value in category_rates.values())
            and wrong_products == 0
            and unauthorized == 0
            and hard_overrides == 0
            and unsafe == 0
            and cross_leaks == 0
        ),
    )


def _usage_value(usage, field_name: str) -> int:
    if usage is None:
        return 0
    value = getattr(usage, field_name, None)
    return value if isinstance(value, int) else 0


def _p95(values: tuple[float, ...]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, (95 * len(ordered) + 99) // 100)
    return ordered[rank - 1]


def _hash_json(value: object) -> str:
    return sha256(_canonical_json(value)).hexdigest()


def _hash_raw_output(value: str | None) -> str:
    return sha256(
        value.encode("utf-8")
        if value is not None
        else b"null"
    ).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


__all__ = [
    "CapturedUnifiedRouterReplayReport",
    "GateCategory",
    "RealUnifiedRouterCase",
    "RealUnifiedRouterManifest",
    "RealUnifiedRouterReport",
    "RealUnifiedRouterResult",
    "build_real_case_manifest",
    "captured_replay_meets_blind_thresholds",
    "load_real_unified_router_cases",
    "main",
    "replay_captured_unified_router_results",
    "run_real_unified_router_gate",
]


if __name__ == "__main__":
    raise SystemExit(main())
