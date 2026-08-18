"""Real frozen-model entrypoint for the Guide model vertical gate."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
import hashlib
from pathlib import Path

from app.guide.adapters.llm.contracts import (
    SemanticIntentCallResult,
)
from app.guide.adapters.llm.siliconflow_intent import (
    SiliconFlowIntentAdapter,
)
from app.guide_runtime.llm_config import (
    GuideLlmConfig,
    GuideLlmConfigError,
)
from tools.guide_gates.guide_pipeline_evaluator import (
    ModelVerticalEvaluator,
)
from tools.guide_gates.intent_model_ab import (
    AbInvocation,
    AdapterUsage,
    IntentAbConfigurationError,
    IntentAdapter,
    IntentCase,
    IntentCaseError,
    PipelineEvaluator,
    _case_manifest_sha256,
    load_cases,
    run_ab,
)


FLASH_MODEL = "deepseek-ai/DeepSeek-V4-Flash"
BASELINE_MODEL = "deepseek-ai/DeepSeek-V3.2"
FROZEN_MODELS = (FLASH_MODEL, BASELINE_MODEL)
FROZEN_CASE_COUNT = 128
FROZEN_CASE_FILE_SHA256 = (
    "be3df249f3bfdf9e0482a445cae8144ff461a4cc32fa204d40b93df7e63b615e"
)
FROZEN_CASE_MANIFEST_SHA256 = (
    "7c815ae4b9dcc23d74a5d4b66b011102c8670de9c5639f7938795dc8c07c670a"
)

AdapterFactory = Callable[[GuideLlmConfig], object]
EvaluatorFactory = Callable[[], PipelineEvaluator]


def _load_frozen_cases(path: str | Path) -> tuple[IntentCase, ...]:
    case_path = Path(path)
    try:
        content = case_path.read_bytes()
    except OSError as exc:
        raise IntentCaseError(
            "intent case file is unavailable"
        ) from exc
    if hashlib.sha256(content).hexdigest() != FROZEN_CASE_FILE_SHA256:
        raise IntentAbConfigurationError(
            "real A/B requires the canonical frozen v2 case file"
        )

    cases = load_cases(case_path)
    if (
        len(cases) != FROZEN_CASE_COUNT
        or _case_manifest_sha256(cases)
        != FROZEN_CASE_MANIFEST_SHA256
    ):
        raise IntentAbConfigurationError(
            "real A/B requires the canonical frozen v2 case manifest"
        )
    return cases


def build_real_adapters(
    *,
    base_config: GuideLlmConfig,
    models: Sequence[str],
    adapter_factory: AdapterFactory = (
        SiliconFlowIntentAdapter.from_config
    ),
) -> dict[str, IntentAdapter]:
    requested = tuple(models)
    if (
        len(requested) != len(FROZEN_MODELS)
        or set(requested) != set(FROZEN_MODELS)
    ):
        raise IntentAbConfigurationError(
            "real A/B requires the frozen model pair"
        )
    if base_config.api_key is None:
        raise IntentAbConfigurationError(
            "Guide LLM API key is unavailable"
        )
    if not callable(adapter_factory):
        raise IntentAbConfigurationError(
            "adapter factory must be callable"
        )

    adapters: dict[str, IntentAdapter] = {}
    try:
        for model in requested:
            config = replace(base_config, model=model).require_ready()
            adapters[model] = _UsageReportingIntentAdapter(
                adapter_factory(config)
            )
    except Exception:
        _close_adapters(adapters)
        raise
    return adapters


class _UsageReportingIntentAdapter:
    def __init__(self, adapter: object) -> None:
        self._adapter = adapter
        for name in ("provider", "model", "prompt_version"):
            value = getattr(adapter, name, None)
            if not isinstance(value, str):
                raise IntentAbConfigurationError(
                    "real adapter identity is unavailable"
                )
            setattr(self, name, value)
        if not callable(getattr(adapter, "propose_with_result", None)):
            raise IntentAbConfigurationError(
                "real adapter must expose propose_with_result"
            )

    def propose(self, message, context) -> AbInvocation:
        result = self._adapter.propose_with_result(message, context)
        if not isinstance(result, SemanticIntentCallResult):
            raise TypeError(
                "real adapter must return SemanticIntentCallResult"
            )
        usage = result.usage
        return AbInvocation(
            proposal=result.proposal,
            usage=AdapterUsage(
                prompt_tokens=(
                    usage.prompt_tokens if usage is not None else None
                ),
                completion_tokens=(
                    usage.completion_tokens if usage is not None else None
                ),
                total_tokens=(
                    usage.total_tokens if usage is not None else None
                ),
                cached_tokens=(
                    usage.cached_tokens if usage is not None else None
                ),
            ),
        )

    def close(self) -> None:
        close = getattr(self._adapter, "close", None)
        if callable(close):
            close()


def main(
    argv: Sequence[str] | None = None,
    *,
    adapter_factory: AdapterFactory = (
        SiliconFlowIntentAdapter.from_config
    ),
    evaluator_factory: EvaluatorFactory = ModelVerticalEvaluator,
) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the frozen real-model Guide A/B through the "
            "non-public model vertical gate."
        )
    )
    parser.add_argument("--cases", required=True)
    parser.add_argument(
        "--model",
        action="append",
        required=True,
        dest="models",
    )
    parser.add_argument("--output-dir", required=True)
    arguments = parser.parse_args(argv)

    requested_models = tuple(arguments.models)
    if (
        len(requested_models) != len(FROZEN_MODELS)
        or set(requested_models) != set(FROZEN_MODELS)
    ):
        return 2

    adapters: Mapping[str, IntentAdapter] = {}
    try:
        cases = _load_frozen_cases(arguments.cases)
        base_config = GuideLlmConfig.from_environment()
        if base_config.api_key is None:
            return 2
        adapters = build_real_adapters(
            base_config=base_config,
            models=requested_models,
            adapter_factory=adapter_factory,
        )
        report = run_ab(
            cases=cases,
            adapters=adapters,
            evaluator=evaluator_factory(),
            output_dir=arguments.output_dir,
        )
    except (
        GuideLlmConfigError,
        IntentCaseError,
        IntentAbConfigurationError,
    ):
        return 2
    finally:
        _close_adapters(adapters)
    return report.exit_code


def _close_adapters(adapters: Mapping[str, IntentAdapter]) -> None:
    for adapter in adapters.values():
        close = getattr(adapter, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":
    raise SystemExit(main())
