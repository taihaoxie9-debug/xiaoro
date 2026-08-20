from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.guide.adapters.llm.contracts import (
    SemanticIntentCallResult,
    SemanticTokenUsage,
)
from app.guide.adapters.llm.siliconflow_intent import (
    SiliconFlowIntentAdapter,
)
from app.guide.understanding.contracts import TopicCode
from app.guide.understanding.semantic_contracts import (
    SemanticContext,
    SemanticIntentProposal,
)
from tools.guide_gates.intent_model_ab import (
    AbInvocation,
    MinimalTaskPlanEvaluator,
    PipelineEvaluation,
    load_cases,
    run_ab,
)
from tools.guide_gates.run_real_intent_ab import (
    BASELINE_MODEL,
    FLASH_MODEL,
    build_real_adapters,
    main,
)


CASES_PATH = Path(
    "tests/fixtures/guide/intent/semantic_intent_ab_v2.jsonl"
)
V1_CASES_PATH = Path(
    "tests/fixtures/guide/intent/semantic_intent_ab_v1.jsonl"
)
SECRET = "entrypoint-secret-must-not-leak"
PROVIDER_BODY = "provider-body-must-not-leak"


def _args(
    output_dir: Path,
    *,
    cases_path: Path = CASES_PATH,
) -> list[str]:
    return [
        "--cases",
        str(cases_path),
        "--model",
        FLASH_MODEL,
        "--model",
        BASELINE_MODEL,
        "--output-dir",
        str(output_dir),
    ]


def _write_noncanonical_case_set(
    tmp_path: Path,
    variant: str,
) -> Path:
    if variant == "v1":
        return V1_CASES_PATH

    lines = CASES_PATH.read_text(encoding="utf-8").splitlines()
    destination = tmp_path / f"{variant}.jsonl"
    if variant == "case":
        row = json.loads(lines[0])
        row["message"] = f"{row['message']} "
        lines[0] = json.dumps(
            row,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    elif variant == "reordered":
        lines[0], lines[1] = lines[1], lines[0]
    elif variant == "tags":
        row = json.loads(lines[0])
        row["tags"].append("variant")
        lines[0] = json.dumps(
            row,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    elif variant == "other-120":
        lines = lines[:120]
    else:
        raise AssertionError(f"unknown test variant: {variant}")
    destination.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    return destination


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


class RecordingAdapter:
    provider = "siliconflow"
    prompt_version = "recording-prompt-v1"

    def __init__(self, config, cases, calls) -> None:
        self.model = config.model
        self._cases = {case.message: case for case in cases}
        self._calls = calls

    def propose_with_result(self, message, context):
        self._calls[self.model].append((message, context))
        return SemanticIntentCallResult(
            proposal=_proposal_for_expected(self._cases[message]),
            usage=None,
        )

    def close(self) -> None:
        pass


class PassingEvaluator:
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


def test_missing_key_exits_two_without_creating_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("GUIDE_LLM_API_KEY", raising=False)
    destination = tmp_path / "missing-key"

    result = main(_args(destination))

    assert result == 2
    assert not destination.exists()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_entrypoint_uses_explicit_pair_same_parameters_and_128_cases(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("GUIDE_LLM_API_KEY", SECRET)
    monkeypatch.setenv("GUIDE_LLM_MODEL", "provider/ignored-default")
    monkeypatch.setenv("GUIDE_LLM_TIMEOUT_SECONDS", "2.5")
    monkeypatch.setenv("GUIDE_LLM_MAX_TOKENS", "192")
    cases = load_cases(CASES_PATH)
    configs = []
    calls = {FLASH_MODEL: [], BASELINE_MODEL: []}

    def adapter_factory(config):
        configs.append(config)
        return RecordingAdapter(config, cases, calls)

    destination = tmp_path / "real-entry"
    result = main(
        _args(destination),
        adapter_factory=adapter_factory,
        evaluator_factory=PassingEvaluator,
    )

    assert result == 0
    assert [config.model for config in configs] == [
        FLASH_MODEL,
        BASELINE_MODEL,
    ]
    comparable = [
        (
            config.base_url,
            config.timeout_seconds,
            config.max_tokens,
            config.daily_budget_cny,
            config.daily_call_cap,
            config.format_repair_attempts,
        )
        for config in configs
    ]
    assert comparable[0] == comparable[1]
    assert len(calls[FLASH_MODEL]) == 128
    assert [item[0] for item in calls[FLASH_MODEL]] == [
        item[0] for item in calls[BASELINE_MODEL]
    ]
    evidence = "\n".join(
        path.read_text(encoding="utf-8")
        for path in destination.iterdir()
    )
    assert SECRET not in evidence
    assert "provider/ignored-default" not in evidence


def test_real_adapter_wrapper_returns_usage_from_one_http_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.guide_runtime.llm_config import GuideLlmConfig

    monkeypatch.setenv("GUIDE_LLM_API_KEY", SECRET)
    monkeypatch.delenv("GUIDE_LLM_MODEL", raising=False)
    config = GuideLlmConfig.from_environment()
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.read()))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "goal": "recommendation",
                                    "topic": "fragrance",
                                    "concerns": [],
                                    "observations": [],
                                    "references": [],
                                    "confidence": 0.99,
                                    "clarification_hint": None,
                                }
                            )
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            },
        )

    transport = httpx.MockTransport(handler)
    adapters = build_real_adapters(
        base_config=config,
        models=(FLASH_MODEL, BASELINE_MODEL),
        adapter_factory=lambda item: (
            SiliconFlowIntentAdapter.from_config(
                item,
                transport=transport,
            )
        ),
    )
    context = SemanticContext(
        conversation_version=0,
        active_topic=None,
        visible_candidate_count=0,
        confirmed_profile_fields=(),
    )
    try:
        results = [
            adapter.propose("夏天闻起来清爽的东西", context)
            for adapter in adapters.values()
        ]
    finally:
        for adapter in adapters.values():
            adapter.close()

    assert len(requests) == 2
    assert all(isinstance(result, AbInvocation) for result in results)
    assert [result.proposal.topic for result in results] == [
        TopicCode.FRAGRANCE,
        TopicCode.FRAGRANCE,
    ]
    assert [result.usage.total_tokens for result in results] == [15, 15]


def test_real_usage_changes_metrics_not_stable_semantic_hash(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.guide_runtime.llm_config import GuideLlmConfig

    monkeypatch.setenv("GUIDE_LLM_API_KEY", SECRET)
    monkeypatch.delenv("GUIDE_LLM_MODEL", raising=False)
    config = GuideLlmConfig.from_environment()
    cases = load_cases(CASES_PATH)
    by_message = {case.message: case for case in cases}

    def execute(usage: dict[str, int], destination: Path):
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.read())
            user_payload = json.loads(
                body["messages"][1]["content"]
            )
            case = by_message[user_payload["message"]]
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    _proposal_for_expected(case)
                                    .model_dump_json()
                                )
                            }
                        }
                    ],
                    "usage": usage,
                },
            )

        transport = httpx.MockTransport(handler)
        adapters = build_real_adapters(
            base_config=config,
            models=(FLASH_MODEL, BASELINE_MODEL),
            adapter_factory=lambda item: (
                SiliconFlowIntentAdapter.from_config(
                    item,
                    transport=transport,
                )
            ),
        )
        try:
            return run_ab(
                cases=cases,
                adapters=adapters,
                evaluator=PassingEvaluator(),
                output_dir=destination,
            )
        finally:
            for adapter in adapters.values():
                adapter.close()

    first = execute(
        {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "cached_tokens": 2,
        },
        tmp_path / "first",
    )
    second = execute(
        {
            "prompt_tokens": 20,
            "completion_tokens": 7,
            "total_tokens": 27,
            "cached_tokens": 3,
        },
        tmp_path / "second",
    )

    assert first.normalized_results_sha256 == (
        second.normalized_results_sha256
    )
    assert (
        tmp_path / "first" / "normalized_results.jsonl"
    ).read_bytes() == (
        tmp_path / "second" / "normalized_results.jsonl"
    ).read_bytes()
    assert (tmp_path / "first" / "runtime_metrics.json").read_bytes() != (
        tmp_path / "second" / "runtime_metrics.json"
    ).read_bytes()


def test_typed_usage_never_accepts_cost() -> None:
    with pytest.raises(ValidationError):
        SemanticTokenUsage(
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            cached_tokens=0,
            cost_cny="0.01",
        )


def test_entrypoint_rejects_non_frozen_model_set(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("GUIDE_LLM_API_KEY", SECRET)
    destination = tmp_path / "wrong-models"
    args = [
        "--cases",
        str(CASES_PATH),
        "--model",
        FLASH_MODEL,
        "--model",
        "provider/not-approved",
        "--output-dir",
        str(destination),
    ]

    assert main(args) == 2
    assert not destination.exists()


@pytest.mark.parametrize(
    "variant",
    ("v1", "case", "reordered", "tags", "other-120"),
)
def test_entrypoint_rejects_noncanonical_case_set_before_configuration(
    variant: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cases_path = _write_noncanonical_case_set(tmp_path, variant)
    destination = tmp_path / f"rejected-{variant}"
    configuration_calls: list[bool] = []

    def fail_if_configuration_is_loaded(cls):
        configuration_calls.append(True)
        pytest.fail(
            "noncanonical cases must fail before loading real configuration"
        )

    monkeypatch.setattr(
        "tools.guide_gates.run_real_intent_ab."
        "GuideLlmConfig.from_environment",
        classmethod(fail_if_configuration_is_loaded),
    )

    result = main(
        _args(destination, cases_path=cases_path),
        adapter_factory=lambda config: pytest.fail(
            "noncanonical cases must fail before adapter creation"
        ),
    )

    assert result == 2
    assert configuration_calls == []
    assert not destination.exists()
