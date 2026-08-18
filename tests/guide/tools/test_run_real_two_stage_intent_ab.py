from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
import json
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from app.guide.adapters.llm.contracts import (
    SemanticProviderFailure,
    SemanticProviderFailureCode,
    SemanticStageUsage,
    SemanticTokenUsage,
    TwoStageSemanticCallResult,
)
from app.guide.understanding.semantic_contracts import (
    ConcernCode,
    SemanticIntentProposal,
    SemanticPreferenceCandidate,
    SemanticPreferenceField,
    SemanticPreferenceStrength,
)
from tools.guide_gates.intent_model_ab import (
    IntentAbConfigurationError,
    MinimalTaskPlanEvaluator,
    PipelineEvaluation,
    load_cases,
)
from tools.guide_gates import run_real_two_stage_intent_ab as runner
from tools.guide_gates.run_real_two_stage_intent_ab import (
    BASELINE_MODEL,
    FLASH_MODEL,
    build_real_adapters,
    main,
    run_real_gate,
)


_FIXTURE_ROOT = Path("tests/fixtures/guide/intent")
_CASES_PATH = _FIXTURE_ROOT / "semantic_intent_ab_v2.jsonl"
_SMOKE_PATH = _FIXTURE_ROOT / "two_stage_smoke_v1.jsonl"
_SMOKE_MANIFEST_PATH = (
    _FIXTURE_ROOT / "two_stage_smoke_v1_manifest.json"
)
_SECRET = "two-stage-entrypoint-secret-must-not-leak"


def _args(
    output_dir: Path,
    *,
    cases_path: Path = _CASES_PATH,
    smoke_path: Path = _SMOKE_PATH,
    smoke_manifest_path: Path = _SMOKE_MANIFEST_PATH,
) -> list[str]:
    return [
        "--cases",
        str(cases_path),
        "--smoke-cases",
        str(smoke_path),
        "--smoke-manifest",
        str(smoke_manifest_path),
        "--model",
        FLASH_MODEL,
        "--model",
        BASELINE_MODEL,
        "--output-dir",
        str(output_dir),
    ]


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
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
) -> SemanticTokenUsage:
    return SemanticTokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        cached_tokens=0,
    )


class _RecordingAdapter:
    provider = "siliconflow"
    prompt_version = "two-stage-recording-prompt-v1"

    def __init__(
        self,
        config,
        cases,
        calls: dict[str, list[str]],
        *,
        prompt_tokens: int = 10,
        events: list[str] | None = None,
    ) -> None:
        self.model = config.model
        self._cases = {case.message: case for case in cases}
        self._calls = calls
        self._prompt_tokens = prompt_tokens
        self._events = events

    def propose_with_result(self, message, context):
        del context
        self._calls[self.model].append(message)
        if self._events is not None:
            self._events.append(self.model)
        proposal = _proposal_for_expected(self._cases[message])
        stages = [
            SemanticStageUsage(
                stage="route",
                usage=_usage(prompt_tokens=self._prompt_tokens),
                repair_used=False,
            )
        ]
        if not self._cases[message].expected.must_clarify:
            stages.append(
                SemanticStageUsage(
                    stage="detail",
                    usage=_usage(
                        prompt_tokens=self._prompt_tokens + 1
                    ),
                    repair_used=False,
                )
            )
        return TwoStageSemanticCallResult(
            proposal=proposal,
            stage_usage=tuple(stages),
        )

    def close(self) -> None:
        pass


class _ClarifyingAdapter(_RecordingAdapter):
    def propose_with_result(self, message, context):
        del context
        self._calls[self.model].append(message)
        return TwoStageSemanticCallResult(
            proposal=SemanticIntentProposal.model_validate_json(
                json.dumps(
                    {
                        "goal": "clarification",
                        "topic": None,
                        "concerns": [],
                        "observations": [],
                        "references": [],
                        "confidence": 0.2,
                        "clarification_hint": "goal",
                    }
                ),
                strict=True,
            ),
            stage_usage=(
                SemanticStageUsage(
                    stage="route",
                    usage=_usage(),
                    repair_used=False,
                ),
            ),
        )


class _AlwaysUnavailableAdapter:
    provider = "siliconflow"
    model = FLASH_MODEL
    prompt_version = "always-unavailable-v1"

    def __init__(self) -> None:
        self.calls = 0

    def propose_with_result(self, message, context):
        del message, context
        self.calls += 1
        raise SemanticProviderFailure(
            SemanticProviderFailureCode.PROVIDER_UNAVAILABLE
        )


class _AlwaysInvalidOutputAdapter:
    provider = "siliconflow"
    model = FLASH_MODEL
    prompt_version = "always-invalid-output-v1"

    def __init__(self) -> None:
        self.calls = 0

    def propose_with_result(self, message, context):
        del message, context
        self.calls += 1
        raise SemanticProviderFailure(
            SemanticProviderFailureCode.INVALID_OUTPUT
        )


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


def _read_summary(output_dir: Path) -> dict[str, object]:
    return json.loads(
        (output_dir / "summary.json").read_text(encoding="utf-8")
    )


def test_frozen_detail_fixture_ignores_new_unasserted_query_fields() -> None:
    case = next(
        item
        for item in load_cases(_CASES_PATH)
        if item.case_id == "know-001-sunscreen-spf"
    )
    proposal = _proposal_for_expected(case).model_copy(
        update={
            "question_meaning": "询问SPF和PA的含义",
            "safety_sensitive": False,
        },
        deep=True,
    )

    assert runner._detail_matches(case, proposal)


def test_frozen_detail_fixture_does_not_treat_unlabelled_preference_as_empty(
) -> None:
    case = next(
        item
        for item in load_cases(_CASES_PATH)
        if item.case_id == "rec-006-paraphrase-sunscreen"
    )
    proposal = _proposal_for_expected(case).model_copy(
        update={
            "preference_candidates": (
                SemanticPreferenceCandidate(
                    field=SemanticPreferenceField.USAGE_CONTEXT,
                    raw_text="通勤",
                    start=4,
                    end=6,
                    strength=SemanticPreferenceStrength.PREFERENCE,
                ),
            ),
        },
        deep=True,
    )

    assert runner._detail_matches(case, proposal)


def test_detail_quality_miss_without_task_impact_is_not_unsafe() -> None:
    frozen = runner.load_frozen_inputs(
        cases_path=_CASES_PATH,
        smoke_cases_path=_SMOKE_PATH,
        smoke_manifest_path=_SMOKE_MANIFEST_PATH,
    )
    calls = {FLASH_MODEL: []}

    class DetailOnlyMismatchAdapter(_RecordingAdapter):
        def propose_with_result(self, message, context):
            result = super().propose_with_result(message, context)
            if message != "想找一支通勤时挡紫外线又不搓泥的":
                return result
            return result.model_copy(
                update={
                    "proposal": result.proposal.model_copy(
                        update={
                            "concerns": (ConcernCode.TEXTURE,),
                        },
                        deep=True,
                    )
                },
                deep=True,
            )

    adapter = DetailOnlyMismatchAdapter(
        SimpleNamespace(model=FLASH_MODEL),
        frozen.smoke_cases,
        calls,
    )
    report = run_real_gate(
        adapter=adapter,
        cases=frozen.smoke_cases,
        evaluator=_PassingEvaluator(),
        phase="smoke",
    )

    row = next(
        item
        for item in report.normalized_rows
        if item.case_id == "rec-006-paraphrase-sunscreen"
    )
    assert row.detail_key_match is False
    assert row.unsafe_task_plan_mismatch_count == 0
    assert row.unauthorized_constraint_transition_count == 0
    assert report.hard_gates_passed is True
    assert report.passed is True


def test_critical_route_miss_corrected_by_code_is_not_execution_error(
) -> None:
    frozen = runner.load_frozen_inputs(
        cases_path=_CASES_PATH,
        smoke_cases_path=_SMOKE_PATH,
        smoke_manifest_path=_SMOKE_MANIFEST_PATH,
    )
    calls = {FLASH_MODEL: []}

    class SafelyCorrectedRouteAdapter(_RecordingAdapter):
        def propose_with_result(self, message, context):
            result = super().propose_with_result(message, context)
            if message != "推荐一下":
                return result
            proposal = SemanticIntentProposal.model_validate_json(
                (
                    '{"goal":"recommendation","topic":null,'
                    '"concerns":[],"observations":[],"references":[],'
                    '"confidence":0.9,"clarification_hint":null}'
                ),
                strict=True,
            )
            return TwoStageSemanticCallResult(
                proposal=proposal,
                stage_usage=(
                    SemanticStageUsage(
                        stage="route",
                        usage=_usage(),
                        repair_used=False,
                    ),
                    SemanticStageUsage(
                        stage="detail",
                        usage=_usage(),
                        repair_used=False,
                    ),
                ),
            )

    adapter = SafelyCorrectedRouteAdapter(
        SimpleNamespace(model=FLASH_MODEL),
        frozen.smoke_cases,
        calls,
    )
    report = run_real_gate(
        adapter=adapter,
        cases=frozen.smoke_cases,
        evaluator=_PassingEvaluator(),
        phase="smoke",
    )

    row = next(
        item
        for item in report.normalized_rows
        if item.case_id == "clar-002-low-info-recommend"
    )
    assert row.route_critical_match is False
    assert row.fail_closed_clarification is True
    assert row.safe_clarification_mismatch_count == 1
    assert row.unsafe_task_plan_mismatch_count == 0
    assert row.critical_route_error_count == 0
    assert report.route_critical_rate > 0.85
    assert report.passed is True


@pytest.mark.parametrize(
    "input_name",
    ("cases", "smoke-cases", "smoke-manifest"),
)
def test_noncanonical_inputs_fail_before_config_or_network(
    input_name: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    paths = {
        "cases": _CASES_PATH,
        "smoke-cases": _SMOKE_PATH,
        "smoke-manifest": _SMOKE_MANIFEST_PATH,
    }
    modified = tmp_path / paths[input_name].name
    modified.write_bytes(paths[input_name].read_bytes() + b" ")
    kwargs = {
        "cases_path": paths["cases"],
        "smoke_path": paths["smoke-cases"],
        "smoke_manifest_path": paths["smoke-manifest"],
    }
    kwargs[
        {
            "cases": "cases_path",
            "smoke-cases": "smoke_path",
            "smoke-manifest": "smoke_manifest_path",
        }[input_name]
    ] = modified
    configuration_calls: list[bool] = []

    def fail_if_configured(cls):
        configuration_calls.append(True)
        pytest.fail("frozen inputs must fail before configuration")

    monkeypatch.setattr(
        "tools.guide_gates.run_real_two_stage_intent_ab."
        "GuideLlmConfig.from_environment",
        classmethod(fail_if_configured),
    )

    result = main(
        _args(tmp_path / "output", **kwargs),
        adapter_factory=lambda config: pytest.fail(
            "frozen inputs must fail before adapter creation"
        ),
    )

    assert result == 2
    assert configuration_calls == []
    assert not (tmp_path / "output").exists()


def test_missing_key_is_silent_and_creates_no_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("GUIDE_LLM_API_KEY", raising=False)
    destination = tmp_path / "missing-key"

    assert main(_args(destination)) == 2
    assert not destination.exists()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_canonical_smoke_inputs_are_internal_cli_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("GUIDE_LLM_API_KEY", raising=False)
    destination = tmp_path / "default-smoke"
    arguments = [
        "--cases",
        str(_CASES_PATH),
        "--model",
        FLASH_MODEL,
        "--model",
        BASELINE_MODEL,
        "--output-dir",
        str(destination),
    ]

    assert main(arguments) == 2
    assert not destination.exists()


def test_entrypoint_uses_fixed_equal_parameters_and_smoke_before_full(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("GUIDE_LLM_API_KEY", _SECRET)
    monkeypatch.delenv("GUIDE_LLM_DAILY_CALL_CAP", raising=False)
    monkeypatch.setenv("GUIDE_LLM_MODEL", "provider/ignored")
    monkeypatch.setenv("GUIDE_LLM_TIMEOUT_SECONDS", "2.5")
    monkeypatch.setenv("GUIDE_LLM_MAX_TOKENS", "256")
    monkeypatch.setenv("GUIDE_LLM_FORMAT_REPAIR_ATTEMPTS", "0")
    cases = load_cases(_CASES_PATH)
    configs = []
    calls = {FLASH_MODEL: [], BASELINE_MODEL: []}
    events: list[str] = []

    def adapter_factory(config):
        configs.append(config)
        return _RecordingAdapter(
            config,
            cases,
            calls,
            events=events,
        )

    destination = tmp_path / "passing"
    result = main(
        _args(destination),
        adapter_factory=adapter_factory,
        evaluator_factory=_PassingEvaluator,
    )

    assert result == 0
    assert [config.model for config in configs] == [
        FLASH_MODEL,
        BASELINE_MODEL,
    ]
    for config in configs:
        assert config.timeout_seconds == 12.0
        assert config.max_tokens == 128
        assert config.enable_thinking is False
        assert config.format_repair_attempts == 1
        assert config.daily_call_cap == (32 + 128) * (2 + 1)
    assert replace(configs[0], model=configs[1].model) == configs[1]
    smoke_messages = [
        json.loads(line)["message"]
        for line in _SMOKE_PATH.read_text(encoding="utf-8").splitlines()
    ]
    full_messages = [case.message for case in cases]
    assert calls[FLASH_MODEL] == smoke_messages + full_messages
    assert calls[BASELINE_MODEL] == smoke_messages + full_messages
    assert events == (
        [FLASH_MODEL] * 32
        + [BASELINE_MODEL] * 32
        + [FLASH_MODEL] * 128
        + [BASELINE_MODEL] * 128
    )

    evidence = b"".join(
        path.read_bytes() for path in destination.iterdir()
    )
    assert _SECRET.encode() not in evidence
    assert cases[0].message.encode() not in evidence
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o600
        for path in destination.iterdir()
    )
    summary = _read_summary(destination)
    assert summary["selected_model"] == FLASH_MODEL
    assert summary["normalized_results_sha256"] == (
        "9472cf8d6e21b9c668d560aa9704b438ba6e842715f9e0a97d1f7aede3857c21"
    )
    assert summary["models"][FLASH_MODEL]["smoke"]["passed"] is True
    assert summary["models"][FLASH_MODEL]["full"]["passed"] is True


def test_explicit_low_call_cap_fails_before_adapter_or_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("GUIDE_LLM_API_KEY", _SECRET)
    monkeypatch.setenv("GUIDE_LLM_DAILY_CALL_CAP", "479")
    adapter_configs = []
    destination = tmp_path / "low-call-cap"

    def adapter_factory(config):
        adapter_configs.append(config)
        raise IntentAbConfigurationError(
            "adapter creation probe must not be reached"
        )

    result = main(
        _args(destination),
        adapter_factory=adapter_factory,
        evaluator_factory=_PassingEvaluator,
    )

    assert result == 2
    assert adapter_configs == []
    assert not destination.exists()


def test_provider_failure_rate_stops_after_twenty_rows() -> None:
    adapter = _AlwaysUnavailableAdapter()

    report = run_real_gate(
        adapter=adapter,
        cases=load_cases(_CASES_PATH),
        evaluator=_PassingEvaluator(),
        phase="full",
    )

    assert adapter.calls == 20
    assert report.executed_case_count == 20
    assert report.stop_reason == "provider_failure_rate"
    assert report.provider_unavailable_or_timeout_count == 20
    assert report.passed is False


def test_invalid_output_fail_closed_state_case_writes_typed_no_go(
) -> None:
    adapter = _AlwaysInvalidOutputAdapter()

    report = run_real_gate(
        adapter=adapter,
        cases=runner.load_frozen_inputs(
            cases_path=_CASES_PATH,
            smoke_cases_path=_SMOKE_PATH,
            smoke_manifest_path=_SMOKE_MANIFEST_PATH,
        ).smoke_cases,
        evaluator=MinimalTaskPlanEvaluator(),
        phase="smoke",
    )

    assert adapter.calls == 32
    assert report.executed_case_count == 32
    assert report.passed is False
    row = next(
        item
        for item in report.normalized_rows
        if item.case_id == "follow-009-budget-revision"
    )
    assert row.status == "schema_invalid"
    assert row.fail_closed_clarification is True
    assert row.safe_clarification_mismatch_count == 1
    assert row.unsafe_task_plan_mismatch_count == 0
    assert row.unauthorized_constraint_transition_count == 0


def test_failed_smoke_prevents_full_case_execution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("GUIDE_LLM_API_KEY", _SECRET)
    cases = load_cases(_CASES_PATH)
    calls = {FLASH_MODEL: [], BASELINE_MODEL: []}

    def adapter_factory(config):
        return _ClarifyingAdapter(config, cases, calls)

    destination = tmp_path / "smoke-stop"
    result = main(
        _args(destination),
        adapter_factory=adapter_factory,
        evaluator_factory=_PassingEvaluator,
    )

    assert result == 3
    assert len(calls[FLASH_MODEL]) == 32
    assert len(calls[BASELINE_MODEL]) == 32
    summary = _read_summary(destination)
    assert summary["models"][FLASH_MODEL]["full"] is None
    assert summary["models"][FLASH_MODEL]["stop_reason"] == (
        "smoke_gate"
    )
    smoke = summary["models"][FLASH_MODEL]["smoke"]
    assert smoke["unsafe_task_plan_mismatch_count"] == 0
    assert smoke["critical_route_error_count"] == 0
    assert smoke["route_critical_rate"] < 0.85
    assert smoke["stop_reason"] == "route_quality"
    assert smoke["hard_gates_passed"] is True


def test_stage_usage_changes_runtime_hash_not_stable_semantic_hash(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("GUIDE_LLM_API_KEY", _SECRET)
    cases = load_cases(_CASES_PATH)

    def execute(prompt_tokens: int, destination: Path) -> dict[str, object]:
        calls = {FLASH_MODEL: [], BASELINE_MODEL: []}

        def adapter_factory(config):
            return _RecordingAdapter(
                config,
                cases,
                calls,
                prompt_tokens=prompt_tokens,
            )

        assert main(
            _args(destination),
            adapter_factory=adapter_factory,
            evaluator_factory=_PassingEvaluator,
        ) == 0
        return _read_summary(destination)

    first = execute(10, tmp_path / "first")
    second = execute(20, tmp_path / "second")

    assert first["normalized_results_sha256"] == (
        second["normalized_results_sha256"]
    )
    assert first["runtime_metrics_sha256"] != (
        second["runtime_metrics_sha256"]
    )
    runtime = json.loads(
        (tmp_path / "second" / "runtime_metrics.json").read_text(
            encoding="utf-8"
        )
    )
    assert runtime["rows"][0]["stage_usage"][0]["stage"] == "route"
    assert runtime["rows"][0]["latency_ms"] >= 0.0


def test_hard_gate_failure_stops_after_smoke(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class UnsafeEvaluator(_PassingEvaluator):
        def evaluate(self, request):
            observed = super().evaluate(request)
            return observed.model_copy(
                update={"hard_constraint_override_count": 1}
            )

    monkeypatch.setenv("GUIDE_LLM_API_KEY", _SECRET)
    cases = load_cases(_CASES_PATH)
    calls = {FLASH_MODEL: [], BASELINE_MODEL: []}
    destination = tmp_path / "hard-gate"

    result = main(
        _args(destination),
        adapter_factory=lambda config: _RecordingAdapter(
            config,
            cases,
            calls,
        ),
        evaluator_factory=UnsafeEvaluator,
    )

    assert result == 3
    assert len(calls[FLASH_MODEL]) == 32
    assert len(calls[BASELINE_MODEL]) == 32
    summary = _read_summary(destination)
    smoke = summary["models"][FLASH_MODEL]["smoke"]
    assert smoke["hard_constraint_override_count"] == 32
    assert smoke["passed"] is False


def test_unauthorized_transition_stops_after_smoke(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class UnsafeTransitionEvaluator(_PassingEvaluator):
        def evaluate(self, request):
            observed = super().evaluate(request)
            return observed.model_copy(
                update={
                    "unauthorized_constraint_transition_count": 1
                }
            )

    monkeypatch.setenv("GUIDE_LLM_API_KEY", _SECRET)
    cases = load_cases(_CASES_PATH)
    calls = {FLASH_MODEL: [], BASELINE_MODEL: []}
    destination = tmp_path / "unauthorized-transition"

    result = main(
        _args(destination),
        adapter_factory=lambda config: _RecordingAdapter(
            config,
            cases,
            calls,
        ),
        evaluator_factory=UnsafeTransitionEvaluator,
    )

    assert result == 3
    assert len(calls[FLASH_MODEL]) == 32
    assert len(calls[BASELINE_MODEL]) == 32
    summary = _read_summary(destination)
    smoke = summary["models"][FLASH_MODEL]["smoke"]
    assert smoke["unauthorized_constraint_transition_count"] == 32
    assert smoke["passed"] is False


def test_output_symlink_fails_before_historical_adapter_creation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("GUIDE_LLM_API_KEY", _SECRET)
    target = tmp_path / "target"
    target.mkdir()
    destination = tmp_path / "output"
    destination.symlink_to(target, target_is_directory=True)
    adapter_configs: list[object] = []

    def adapter_factory(config):
        adapter_configs.append(config)
        return object()

    assert main(
        _args(destination),
        adapter_factory=adapter_factory,
        evaluator_factory=_PassingEvaluator,
    ) == 2
    assert adapter_configs == []
    assert list(target.iterdir()) == []
