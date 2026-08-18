"""Supervised DeepSeek official intent gate runner."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
import json
from pathlib import Path

from app.guide.adapters.llm import intent_detail_prompt
from app.guide.adapters.llm import intent_prompt
from app.guide.adapters.llm import intent_route_prompt
from app.guide.understanding import semantic_contracts
from app.guide.understanding import semantic_detail_contracts
from app.guide.understanding import semantic_route_contracts
from app.guide_runtime.llm_config import GuideLlmConfig
from tools.guide_gates import intent_model_ab
from tools.guide_gates import real_ab_evidence as evidence
from tools.guide_gates import run_real_two_stage_intent_ab as two_stage


FLASH_MODEL = "deepseek-v4-flash"
PRO_MODEL = "deepseek-v4-pro"
TWO_STAGE_FLASH = "two_stage_flash"
TWO_STAGE_PRO = "two_stage_pro"
SINGLE_STAGE_PRO_CONTROL = "single_stage_pro_control"
FROZEN_LANES = (TWO_STAGE_FLASH, TWO_STAGE_PRO, SINGLE_STAGE_PRO_CONTROL)
_TWO_STAGE_LANES = (TWO_STAGE_FLASH, TWO_STAGE_PRO)

_SMOKE_CASE_COUNT = 32
_P95_LIMIT_MS = 12_000.0
_PROVIDER = "deepseek_official"
_TWO_STAGE_PROMPT_VERSION = (
    f"{intent_route_prompt.ROUTE_PROMPT_VERSION}+"
    f"{intent_detail_prompt.DETAIL_PROMPT_VERSION}")
_RUNNER_SCHEMA_VERSION = "guide-real-deepseek-intent-ab-v1"
_RUNTIME_SCHEMA_VERSION = "guide-real-deepseek-runtime-v1"
_SUMMARY_SCHEMA_VERSION = "guide-real-deepseek-summary-v1"
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CASES = _REPOSITORY_ROOT / "tests/fixtures/guide/intent/semantic_intent_ab_v2.jsonl"
_DEFAULT_SMOKE_CASES = _REPOSITORY_ROOT / "tests/fixtures/guide/intent/two_stage_smoke_v1.jsonl"
_DEFAULT_SMOKE_MANIFEST = _REPOSITORY_ROOT / "tests/fixtures/guide/intent/two_stage_smoke_v1_manifest.json"

AdapterFactory = Callable[[GuideLlmConfig], object]
EvaluatorFactory = Callable[[], intent_model_ab.PipelineEvaluator]


@dataclass(frozen=True, slots=True)
class DeepSeekRunnerConfig:
    base_url: str = "https://api.deepseek.com"
    timeout_seconds: float = 12.0
    max_tokens: int = 256
    temperature: int = 0
    enable_thinking: bool = False
    format_repair_attempts: int = 1
    transport_retry_count: int = 0
    daily_budget_cny: Decimal = Decimal("1.00")
    daily_call_cap: int = 480


def _emit_blocked() -> int:
    blocked = {"code": "task_6_15_required", "status": "BLOCKED"}
    print(json.dumps(blocked, sort_keys=True, separators=(",", ":")))
    return 4


def _execution_is_injected(
    *,
    config: DeepSeekRunnerConfig | None,
    api_key: str | None,
    two_stage_adapter_factory: AdapterFactory | None,
    single_stage_adapter_factory: AdapterFactory | None,
    evaluator_factory: EvaluatorFactory | None,
) -> bool:
    dependencies = (
        config, api_key, two_stage_adapter_factory,
        single_stage_adapter_factory, evaluator_factory)
    return all(dependency is not None for dependency in dependencies)


def _validate_execution_inputs(
    *,
    config: DeepSeekRunnerConfig,
    api_key: str,
    two_stage_adapter_factory: AdapterFactory,
    single_stage_adapter_factory: AdapterFactory,
    evaluator_factory: EvaluatorFactory,
) -> None:
    evidence.validate_canonical_sensitive_value(api_key)
    if config != DeepSeekRunnerConfig() or (
        not callable(two_stage_adapter_factory)
        or not callable(single_stage_adapter_factory)
        or not callable(evaluator_factory)
    ):
        raise intent_model_ab.IntentAbConfigurationError(
            "official DeepSeek runner configuration is invalid")


def _guide_config(
    *,
    config: DeepSeekRunnerConfig,
    api_key: str,
    model: str,
) -> GuideLlmConfig:
    return GuideLlmConfig(
        api_key=api_key,
        base_url=config.base_url,
        model=model,
        timeout_seconds=config.timeout_seconds,
        max_tokens=config.max_tokens,
        daily_budget_cny=config.daily_budget_cny,
        daily_call_cap=config.daily_call_cap,
        format_repair_attempts=config.format_repair_attempts,
        enable_thinking=config.enable_thinking,
    ).require_ready()


def _build_adapters(
    *,
    config: DeepSeekRunnerConfig,
    api_key: str,
    two_stage_adapter_factory: AdapterFactory,
    single_stage_adapter_factory: AdapterFactory,
) -> dict[str, object]:
    specs = (
        evidence.AdapterBuildSpec(
            TWO_STAGE_FLASH, FLASH_MODEL, _TWO_STAGE_PROMPT_VERSION,
            two_stage_adapter_factory),
        evidence.AdapterBuildSpec(
            TWO_STAGE_PRO, PRO_MODEL, _TWO_STAGE_PROMPT_VERSION,
            two_stage_adapter_factory),
        evidence.AdapterBuildSpec(
            SINGLE_STAGE_PRO_CONTROL, PRO_MODEL,
            intent_prompt.INTENT_PROMPT_VERSION,
            single_stage_adapter_factory))
    return evidence.build_adapter_set(
        specs=specs,
        config_builder=lambda model: _guide_config(
            config=config, api_key=api_key, model=model),
        provider=_PROVIDER,
        base_url=config.base_url)


def _select_lane(lanes: Mapping[str, Mapping[str, object]]) -> str | None:
    for lane in (TWO_STAGE_PRO, TWO_STAGE_FLASH):
        if lanes[lane]["passed"] is True:
            return lane
    return None


def _build_evidence(
    *,
    config: DeepSeekRunnerConfig,
    adapters: Mapping[str, object],
    reports: Mapping[str, Mapping[str, object | None]],
    control: evidence.SingleStageControlReport,
) -> tuple[evidence.EvidenceBundle, int]:
    collected = evidence.collect_supervised_lane_evidence(
        two_stage_lanes=_TWO_STAGE_LANES,
        reports=reports,
        adapters=adapters,
        control_lane=SINGLE_STAGE_PRO_CONTROL,
        control_model=PRO_MODEL,
        control=control,
        provider=_PROVIDER,
        p95_limit_ms=_P95_LIMIT_MS)
    selected_lane = _select_lane(collected.lane_summaries)
    identity = {
        "runner_schema_version": _RUNNER_SCHEMA_VERSION,
        "provider": _PROVIDER,
        "base_url": config.base_url,
        "lanes": list(FROZEN_LANES),
        "models": {
            TWO_STAGE_FLASH: FLASH_MODEL,
            TWO_STAGE_PRO: PRO_MODEL,
            SINGLE_STAGE_PRO_CONTROL: PRO_MODEL,
        },
        "prompt_versions": {
            lane: adapters[lane].prompt_version
            for lane in FROZEN_LANES
        },
        "route_schema_version": (
            semantic_route_contracts.SemanticRouteProposal.schema_version),
        "detail_schema_versions": sorted(
            model.schema_version
            for model in (
                semantic_detail_contracts.RecommendationDetails,
                semantic_detail_contracts.AssessmentDetails,
                semantic_detail_contracts.ComparisonDetails,
                semantic_detail_contracts.FollowupDetails,
                semantic_detail_contracts.KnowledgeDetails,
                semantic_detail_contracts.ImageDetails)),
        "semantic_schema_version": (
            semantic_contracts.SemanticIntentProposal.schema_version),
        "case_file_sha256": (
            evidence.CANONICAL_INTENT_INPUTS.case_file_sha256),
        "case_manifest_sha256": (
            evidence.CANONICAL_INTENT_INPUTS.case_manifest_sha256),
        "smoke_file_sha256": (
            evidence.CANONICAL_INTENT_INPUTS.smoke_file_sha256),
        "smoke_manifest_sha256": (
            evidence.CANONICAL_INTENT_INPUTS.smoke_manifest_sha256),
        "temperature": config.temperature,
        "enable_thinking": config.enable_thinking,
        "max_tokens": config.max_tokens,
        "timeout_seconds": config.timeout_seconds,
        "format_repair_attempts": config.format_repair_attempts,
        "transport_retry_count": config.transport_retry_count,
    }
    return evidence.build_supervised_evidence(
        collected=collected,
        selected_lane=selected_lane,
        runtime_schema_version=_RUNTIME_SCHEMA_VERSION,
        summary_schema_version=_SUMMARY_SCHEMA_VERSION,
        identity=identity)


def main(
    argv: Sequence[str] | None = None,
    *,
    config: DeepSeekRunnerConfig | None = None,
    api_key: str | None = None,
    two_stage_adapter_factory: AdapterFactory | None = None,
    single_stage_adapter_factory: AdapterFactory | None = None,
    evaluator_factory: EvaluatorFactory | None = None,
) -> int:
    if not _execution_is_injected(
        config=config,
        api_key=api_key,
        two_stage_adapter_factory=two_stage_adapter_factory,
        single_stage_adapter_factory=single_stage_adapter_factory,
        evaluator_factory=evaluator_factory,
    ):
        return _emit_blocked()
    assert config is not None
    assert api_key is not None
    assert two_stage_adapter_factory is not None
    assert single_stage_adapter_factory is not None
    assert evaluator_factory is not None
    try:
        _validate_execution_inputs(
            config=config,
            api_key=api_key,
            two_stage_adapter_factory=two_stage_adapter_factory,
            single_stage_adapter_factory=single_stage_adapter_factory,
            evaluator_factory=evaluator_factory,
        )
        paths = evidence.parse_supervised_runner_paths(
            argv,
            description="Run the supervised DeepSeek official intent gate.",
            default_cases=_DEFAULT_CASES,
            default_smoke_cases=_DEFAULT_SMOKE_CASES,
            default_smoke_manifest=_DEFAULT_SMOKE_MANIFEST,
        )
    except (intent_model_ab.IntentAbConfigurationError, TypeError, ValueError):
        return 2
    return evidence.execute_supervised_runner(
        cases_path=paths.cases,
        smoke_cases_path=paths.smoke_cases,
        smoke_manifest_path=paths.smoke_manifest,
        output_dir=paths.output_dir,
        sensitive_value=api_key,
        adapter_builder=lambda: _build_adapters(
            config=config,
            api_key=api_key,
            two_stage_adapter_factory=two_stage_adapter_factory,
            single_stage_adapter_factory=single_stage_adapter_factory),
        lane_runner=lambda frozen, adapters: (
            evidence.run_two_stage_lane_phases(
                lanes=_TWO_STAGE_LANES,
                frozen=frozen,
                adapters=adapters,
                evaluator_factory=evaluator_factory,
                gate_runner=two_stage.run_real_gate)),
        control_runner=lambda frozen, adapters: (
            evidence.run_single_stage_control(
                adapter=adapters[SINGLE_STAGE_PRO_CONTROL],
                cases=frozen.smoke_cases,
                evaluator=evaluator_factory(),
                lane=SINGLE_STAGE_PRO_CONTROL,
                model=PRO_MODEL,
                expected_case_count=_SMOKE_CASE_COUNT)),
        evidence_builder=lambda adapters, reports, control: (
            _build_evidence(
                config=config,
                adapters=adapters,
                reports=reports,
                control=control)))


if __name__ == "__main__":
    raise SystemExit(main())
