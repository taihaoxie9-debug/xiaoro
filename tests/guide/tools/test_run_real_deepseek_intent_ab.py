from __future__ import annotations

from importlib.util import find_spec
import json
from pathlib import Path
import stat

import pytest

from app.guide.adapters.llm.contracts import (
    SemanticIntentCallResult,
    SemanticProviderFailure,
    SemanticProviderFailureCode,
    SemanticStageUsage,
    SemanticTokenUsage,
    TwoStageSemanticCallResult,
)
from app.guide.adapters.llm.intent_detail_prompt import (
    DETAIL_PROMPT_VERSION,
)
from app.guide.adapters.llm.intent_prompt import INTENT_PROMPT_VERSION
from app.guide.adapters.llm.intent_route_prompt import (
    ROUTE_PROMPT_VERSION,
)
from app.guide.understanding.semantic_contracts import (
    SemanticIntentProposal,
)
from tools.guide_gates.intent_model_ab import (
    MinimalTaskPlanEvaluator,
    PipelineEvaluation,
    load_cases,
)
from tools.guide_gates import run_real_deepseek_intent_ab as runner
from tools.guide_gates import real_ab_evidence as evidence


_CASES_PATH = Path(
    "tests/fixtures/guide/intent/semantic_intent_ab_v2.jsonl"
)
_SECRET = "official-runner-secret-must-not-leak"
_TWO_STAGE_PROMPT_VERSION = (
    f"{ROUTE_PROMPT_VERSION}+{DETAIL_PROMPT_VERSION}"
)


def _proposal_for_expected(case) -> SemanticIntentProposal:
    return SemanticIntentProposal.model_validate_json(
        json.dumps(
            {
                "goal": case.expected.goal.value,
                "topic": (
                    case.expected.topic.value
                    if case.expected.topic is not None
                    else None
                ),
                "concerns": [
                    item.value for item in case.expected.concerns
                ],
                "observations": [
                    item.model_dump(mode="json")
                    for item in case.expected.observations
                ],
                "references": [
                    item.model_dump(mode="json")
                    for item in case.expected.references
                ],
                "confidence": 0.99,
                "clarification_hint": (
                    "goal" if case.expected.must_clarify else None
                ),
            },
            ensure_ascii=False,
        ),
        strict=True,
    )


def _usage(
    *,
    cached_tokens: int | None = 0,
) -> SemanticTokenUsage:
    return SemanticTokenUsage(
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        cached_tokens=cached_tokens,
    )


class _ExpectedTwoStageAdapter:
    provider = "deepseek_official"
    prompt_version = _TWO_STAGE_PROMPT_VERSION

    def __init__(
        self,
        config,
        cases,
        calls,
        *,
        cached_tokens: int | None = 0,
    ) -> None:
        self.base_url = config.base_url
        self.model = config.model
        self._cases = {case.message: case for case in cases}
        self._calls = calls
        self._cached_tokens = cached_tokens

    def propose_with_result(self, message, context):
        del context
        self._calls[self.model].append(message)
        case = self._cases[message]
        proposal = _proposal_for_expected(case)
        stages = [
            SemanticStageUsage(
                stage="route",
                usage=_usage(cached_tokens=self._cached_tokens),
                repair_used=False,
            )
        ]
        if not case.expected.must_clarify:
            stages.append(
                SemanticStageUsage(
                    stage="detail",
                    usage=_usage(cached_tokens=self._cached_tokens),
                    repair_used=False,
                )
            )
        return TwoStageSemanticCallResult(
            proposal=proposal,
            stage_usage=tuple(stages),
        )

    def close(self) -> None:
        pass


class _ExpectedSingleStageAdapter:
    provider = "deepseek_official"
    prompt_version = INTENT_PROMPT_VERSION

    def __init__(
        self,
        config,
        cases,
        calls,
        *,
        cached_tokens: int | None = 0,
    ) -> None:
        self.base_url = config.base_url
        self.model = config.model
        self._cases = {case.message: case for case in cases}
        self._calls = calls
        self._cached_tokens = cached_tokens

    def propose_with_result(self, message, context):
        del context
        self._calls.append(message)
        return SemanticIntentCallResult(
            proposal=_proposal_for_expected(self._cases[message]),
            usage=_usage(cached_tokens=self._cached_tokens),
        )

    def close(self) -> None:
        pass


class _UnavailableTwoStageAdapter:
    provider = "deepseek_official"
    prompt_version = _TWO_STAGE_PROMPT_VERSION

    def __init__(self, config, calls) -> None:
        self.base_url = config.base_url
        self.model = config.model
        self._calls = calls

    def propose_with_result(self, message, context):
        del message, context
        self._calls.append(self.model)
        raise SemanticProviderFailure(
            SemanticProviderFailureCode.PROVIDER_UNAVAILABLE
        )

    def close(self) -> None:
        pass


class _PassingEvaluator:
    def evaluate(self, request):
        planned = MinimalTaskPlanEvaluator().evaluate(request)
        return PipelineEvaluation(
            task_plan_mismatch_count=(
                planned.task_plan_mismatch_count
            ),
            hard_constraint_override_count=(
                planned.hard_constraint_override_count
            ),
            product_selection_invocation_count=0,
            wrong_product_selection_count=0,
            legacy_fallback_count=0,
        )


def test_official_deepseek_runner_module_exists() -> None:
    assert find_spec(
        "tools.guide_gates.run_real_deepseek_intent_ab"
    ) is not None


def test_default_cli_is_typed_task_6_15_block_without_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "default-cli-secret-must-not-leak"
    monkeypatch.setenv("GUIDE_LLM_API_KEY", secret)
    output_dir = tmp_path / "must-not-exist"

    assert callable(getattr(runner, "main", None))
    result = runner.main(["--output-dir", str(output_dir)])

    assert result == 4
    assert not output_dir.exists()
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "code": "task_6_15_required",
        "status": "BLOCKED",
    }
    assert captured.err == ""
    assert secret not in captured.out


def test_execution_config_freezes_official_non_thinking_parameters() -> None:
    assert callable(getattr(runner, "DeepSeekRunnerConfig", None))

    config = runner.DeepSeekRunnerConfig()

    assert config.base_url == "https://api.deepseek.com"
    assert config.timeout_seconds == 12.0
    assert config.max_tokens == 256
    assert config.temperature == 0
    assert config.enable_thinking is False
    assert config.format_repair_attempts == 1
    assert config.transport_retry_count == 0


@pytest.mark.parametrize(
    "missing",
    (
        "config",
        "api_key",
        "two_stage_adapter_factory",
        "single_stage_adapter_factory",
        "evaluator_factory",
    ),
)
def test_execution_stays_blocked_until_every_dependency_is_injected(
    missing: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []

    def two_stage_factory(config):
        calls.append(f"two:{config.model}")
        return object()

    def single_stage_factory(config):
        calls.append(f"single:{config.model}")
        return object()

    def evaluator_factory():
        calls.append("evaluator")
        return object()

    dependencies = {
        "config": runner.DeepSeekRunnerConfig(),
        "api_key": "injected-test-key",
        "two_stage_adapter_factory": two_stage_factory,
        "single_stage_adapter_factory": single_stage_factory,
        "evaluator_factory": evaluator_factory,
    }
    dependencies[missing] = None
    output_dir = tmp_path / missing

    result = runner.main(
        ["--output-dir", str(output_dir)],
        **dependencies,
    )

    assert result == 4
    assert calls == []
    assert not output_dir.exists()
    assert json.loads(capsys.readouterr().out)["code"] == (
        "task_6_15_required"
    )


def test_injected_execution_runs_fixed_lanes_and_writes_safe_evidence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cases = load_cases(_CASES_PATH)
    two_stage_calls = {
        "deepseek-v4-flash": [],
        "deepseek-v4-pro": [],
    }
    control_calls: list[str] = []
    configs = []

    def two_stage_factory(config):
        configs.append(config)
        return _ExpectedTwoStageAdapter(
            config,
            cases,
            two_stage_calls,
        )

    def single_stage_factory(config):
        configs.append(config)
        return _ExpectedSingleStageAdapter(
            config,
            cases,
            control_calls,
        )

    output_dir = tmp_path / "evidence"
    result = runner.main(
        ["--output-dir", str(output_dir)],
        config=runner.DeepSeekRunnerConfig(),
        api_key=_SECRET,
        two_stage_adapter_factory=two_stage_factory,
        single_stage_adapter_factory=single_stage_factory,
        evaluator_factory=_PassingEvaluator,
    )

    assert result == 0
    assert capsys.readouterr().out == ""
    assert [config.model for config in configs] == [
        "deepseek-v4-flash",
        "deepseek-v4-pro",
        "deepseek-v4-pro",
    ]
    assert len(two_stage_calls["deepseek-v4-flash"]) == 160
    assert len(two_stage_calls["deepseek-v4-pro"]) == 160
    assert len(control_calls) == 32
    assert set(path.name for path in output_dir.iterdir()) == {
        "normalized_results.jsonl",
        "runtime_metrics.json",
        "summary.json",
        "SHA256SUMS",
    }
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o600
        for path in output_dir.iterdir()
    )

    evidence = b"".join(
        path.read_bytes() for path in output_dir.iterdir()
    )
    assert _SECRET.encode() not in evidence
    assert cases[0].message.encode() not in evidence
    summary = json.loads(
        (output_dir / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["selected_lane"] == "two_stage_pro"
    assert set(summary["lanes"]) == {
        "two_stage_flash",
        "two_stage_pro",
        "single_stage_pro_control",
    }
    control = summary["lanes"]["single_stage_pro_control"]
    assert control["case_count"] == 32
    assert control["eligible_for_selection"] is False
    assert control["full"] is None
    assert summary["identity"]["provider"] == "deepseek_official"
    assert summary["identity"]["base_url"] == "https://api.deepseek.com"
    assert summary["identity"]["temperature"] == 0
    assert summary["identity"]["enable_thinking"] is False
    assert summary["cost"]["status"] == "UNAVAILABLE"
    assert summary["cost"]["actual_cost_cny"] == "UNAVAILABLE"
    assert len(summary["stable_evidence_sha256"]) == 64
    assert len(summary["runtime_metrics_sha256"]) == 64

    runtime = json.loads(
        (output_dir / "runtime_metrics.json").read_text(
            encoding="utf-8"
        )
    )
    assert all(
        lane["usage_complete"] is True
        for lane in runtime["lanes"].values()
    )
    assert all(
        lane["cost_status"] == "UNAVAILABLE"
        for lane in runtime["lanes"].values()
    )


def test_full_p95_over_twelve_seconds_rejects_pro_and_selects_flash(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cases = load_cases(_CASES_PATH)
    calls = {
        "deepseek-v4-flash": [],
        "deepseek-v4-pro": [],
    }
    control_calls: list[str] = []
    original_phase_runtime = evidence.two_stage_phase_runtime

    def phase_runtime(report):
        payload = original_phase_runtime(report)
        if (
            payload is not None
            and report.phase == "full"
            and report.model == "deepseek-v4-pro"
        ):
            payload["latency_p95_ms"] = 12_000.001
        return payload

    monkeypatch.setattr(evidence, "two_stage_phase_runtime", phase_runtime)
    output_dir = tmp_path / "slow-pro"
    result = runner.main(
        ["--output-dir", str(output_dir)],
        config=runner.DeepSeekRunnerConfig(),
        api_key=_SECRET,
        two_stage_adapter_factory=lambda config: (
            _ExpectedTwoStageAdapter(config, cases, calls)
        ),
        single_stage_adapter_factory=lambda config: (
            _ExpectedSingleStageAdapter(
                config,
                cases,
                control_calls,
            )
        ),
        evaluator_factory=_PassingEvaluator,
    )

    assert result == 0
    summary = json.loads(
        (output_dir / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["selected_lane"] == "two_stage_flash"
    assert summary["lanes"]["two_stage_pro"]["passed"] is False
    assert summary["lanes"]["two_stage_pro"]["stop_reason"] == (
        "latency_p95"
    )


def test_provider_failure_smoke_stops_at_twenty_without_full(
    tmp_path: Path,
) -> None:
    cases = load_cases(_CASES_PATH)
    passing_calls = {
        "deepseek-v4-flash": [],
        "deepseek-v4-pro": [],
    }
    unavailable_calls: list[str] = []
    control_calls: list[str] = []

    def two_stage_factory(config):
        if config.model == "deepseek-v4-flash":
            return _UnavailableTwoStageAdapter(
                config,
                unavailable_calls,
            )
        return _ExpectedTwoStageAdapter(
            config,
            cases,
            passing_calls,
        )

    output_dir = tmp_path / "unavailable-flash"
    result = runner.main(
        ["--output-dir", str(output_dir)],
        config=runner.DeepSeekRunnerConfig(),
        api_key=_SECRET,
        two_stage_adapter_factory=two_stage_factory,
        single_stage_adapter_factory=lambda config: (
            _ExpectedSingleStageAdapter(
                config,
                cases,
                control_calls,
            )
        ),
        evaluator_factory=_PassingEvaluator,
    )

    assert result == 0
    assert len(unavailable_calls) == 20
    summary = json.loads(
        (output_dir / "summary.json").read_text(encoding="utf-8")
    )
    flash = summary["lanes"]["two_stage_flash"]
    assert flash["full"] is None
    assert flash["stop_reason"] == "provider_failure_rate"
    assert summary["selected_lane"] == "two_stage_pro"


def test_optional_cached_token_metric_does_not_block_complete_usage(
    tmp_path: Path,
) -> None:
    cases = load_cases(_CASES_PATH)
    calls = {
        "deepseek-v4-flash": [],
        "deepseek-v4-pro": [],
    }
    control_calls: list[str] = []
    output_dir = tmp_path / "optional-cached-usage"

    result = runner.main(
        ["--output-dir", str(output_dir)],
        config=runner.DeepSeekRunnerConfig(),
        api_key=_SECRET,
        two_stage_adapter_factory=lambda config: (
            _ExpectedTwoStageAdapter(
                config,
                cases,
                calls,
                cached_tokens=None,
            )
        ),
        single_stage_adapter_factory=lambda config: (
            _ExpectedSingleStageAdapter(
                config,
                cases,
                control_calls,
                cached_tokens=None,
            )
        ),
        evaluator_factory=_PassingEvaluator,
    )

    assert result == 0
    summary = json.loads(
        (output_dir / "summary.json").read_text(encoding="utf-8")
    )
    assert summary["selected_lane"] == "two_stage_pro"
    runtime = json.loads(
        (output_dir / "runtime_metrics.json").read_text(
            encoding="utf-8"
        )
    )
    assert all(
        lane["usage_complete"] is True
        for lane in runtime["lanes"].values()
    )


def test_adapter_identity_cannot_reflect_key_into_evidence(
    tmp_path: Path,
) -> None:
    cases = load_cases(_CASES_PATH)
    calls = {
        "deepseek-v4-flash": [],
        "deepseek-v4-pro": [],
    }
    output_dir = tmp_path / "identity-key-leak"

    def unsafe_two_stage_factory(config):
        adapter = _ExpectedTwoStageAdapter(
            config,
            cases,
            calls,
        )
        adapter.prompt_version = _SECRET
        return adapter

    result = runner.main(
        ["--output-dir", str(output_dir)],
        config=runner.DeepSeekRunnerConfig(),
        api_key=_SECRET,
        two_stage_adapter_factory=unsafe_two_stage_factory,
        single_stage_adapter_factory=lambda config: pytest.fail(
            "unsafe two-stage identity must fail first"
        ),
        evaluator_factory=_PassingEvaluator,
    )

    assert result == 2
    assert calls == {
        "deepseek-v4-flash": [],
        "deepseek-v4-pro": [],
    }
    assert not output_dir.exists()


@pytest.mark.parametrize(
    "output_kind",
    ("symlink", "regular_file", "existing_directory"),
)
def test_invalid_output_fails_before_adapter_construction_or_lane_calls(
    output_kind: str,
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "invalid-output"
    if output_kind == "symlink":
        target = tmp_path / "symlink-target"
        target.mkdir()
        output_dir.symlink_to(target, target_is_directory=True)
    elif output_kind == "regular_file":
        output_dir.write_text("occupied", encoding="utf-8")
    else:
        output_dir.mkdir()
    calls: list[str] = []

    def adapter_factory(config):
        calls.append(config.model)
        return object()

    result = runner.main(
        ["--output-dir", str(output_dir)],
        config=runner.DeepSeekRunnerConfig(),
        api_key=_SECRET,
        two_stage_adapter_factory=adapter_factory,
        single_stage_adapter_factory=adapter_factory,
        evaluator_factory=lambda: calls.append("evaluator"),
    )

    assert result == 2
    assert calls == []
    if output_kind == "symlink":
        assert list(target.iterdir()) == []


def test_key_with_outer_whitespace_is_typed_rejected_before_output_or_adapter(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "whitespace-key"
    calls: list[str] = []

    def adapter_factory(config):
        calls.append(config.model)
        return object()

    result = runner.main(
        ["--output-dir", str(output_dir)],
        config=runner.DeepSeekRunnerConfig(),
        api_key=f" {_SECRET} ",
        two_stage_adapter_factory=adapter_factory,
        single_stage_adapter_factory=adapter_factory,
        evaluator_factory=lambda: calls.append("evaluator"),
    )

    assert result == 2
    assert calls == []
    assert not output_dir.exists()


def test_final_sensitive_scan_prevents_every_payload_write(
    tmp_path: Path,
) -> None:
    cases = load_cases(_CASES_PATH)
    calls = {
        "deepseek-v4-flash": [],
        "deepseek-v4-pro": [],
    }
    control_calls: list[str] = []

    class LeakingAfterValidationAdapter(_ExpectedTwoStageAdapter):
        def __init__(self, config, cases, calls) -> None:
            super().__init__(config, cases, calls)
            self._prompt_version_reads = 0

        @property
        def prompt_version(self) -> str:
            self._prompt_version_reads += 1
            if self._prompt_version_reads == 1:
                return _TWO_STAGE_PROMPT_VERSION
            return _SECRET

    output_dir = tmp_path / "late-sensitive-payload"
    result = runner.main(
        ["--output-dir", str(output_dir)],
        config=runner.DeepSeekRunnerConfig(),
        api_key=_SECRET,
        two_stage_adapter_factory=lambda config: (
            LeakingAfterValidationAdapter(config, cases, calls)
        ),
        single_stage_adapter_factory=lambda config: (
            _ExpectedSingleStageAdapter(
                config,
                cases,
                control_calls,
            )
        ),
        evaluator_factory=_PassingEvaluator,
    )

    assert result == 2
    assert all(calls.values())
    assert not output_dir.exists() or list(output_dir.iterdir()) == []
