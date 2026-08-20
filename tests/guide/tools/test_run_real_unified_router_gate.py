from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.guide.adapters.llm.contracts import (
    SemanticProviderFailure,
    SemanticProviderFailureCode,
    SemanticTokenUsage,
    TurnMeaningCallResult,
)
from app.guide.intent.concept_preferences import (
    ConceptPreferenceCatalog,
)
from app.guide_runtime.composition import build_selection_concept_assets
from tools.guide_gates import run_real_unified_router_gate as real_gate
from tools.guide_gates import unified_router_smoke_fixture as smoke_fixture
from tools.guide_gates.run_real_unified_router_gate import (
    RealUnifiedRouterCase,
    run_real_unified_router_gate,
)
from tools.guide_gates.unified_router_smoke_fixture import (
    build_unified_router_smoke_cases,
)
from tools.guide_gates.unified_router_gate import load_replay_cases


class RecordingAdapter:
    model = "offline/real-unified-router"
    prompt_version = "test-prompt-v1"

    def __init__(self, meaning) -> None:
        self.meaning = meaning
        self.calls: list[tuple[str, object]] = []

    def propose_with_result(self, message, context):
        self.calls.append((message, context))
        raw_content = self.meaning.model_dump_json()
        return TurnMeaningCallResult(
            meaning=self.meaning,
            usage=SemanticTokenUsage(
                prompt_tokens=11,
                completion_tokens=7,
                total_tokens=18,
                cached_tokens=0,
            ),
            raw_content=raw_content,
            trace_id="sha256:testtrace000000",
        )


class InvalidRawAdapter:
    model = "offline/invalid-raw"
    prompt_version = "test-prompt-v1"

    def __init__(self) -> None:
        self.calls = 0

    def propose_with_result(self, message, context):
        del message, context
        self.calls += 1
        raise SemanticProviderFailure(
            SemanticProviderFailureCode.INVALID_OUTPUT,
            raw_content='{"operation_hint":"recommendation"',
            trace_id="sha256:invalidraw0000",
            usage=SemanticTokenUsage(
                prompt_tokens=9,
                completion_tokens=4,
                total_tokens=13,
                cached_tokens=0,
            ),
        )


def _catalog() -> ConceptPreferenceCatalog:
    return ConceptPreferenceCatalog.from_projections(
        build_selection_concept_assets().projections
    )


def test_runner_calls_model_once_and_records_full_local_trace(
    tmp_path: Path,
) -> None:
    replay = load_replay_cases(
        "tests/fixtures/guide/intent/unified_router_offline_v1.jsonl",
        manifest_path=(
            "tests/fixtures/guide/intent/"
            "unified_router_offline_v1_manifest.json"
        ),
    )[0]
    case = RealUnifiedRouterCase.from_replay_case(
        replay,
        category="recommendation",
    )
    adapter = RecordingAdapter(replay.raw_turn_meaning)
    output_path = tmp_path / "real-gate.json"

    report = run_real_unified_router_gate(
        adapter=adapter,
        cases=(case,),
        concept_catalog=_catalog(),
        repo_root=Path.cwd(),
        state_root=tmp_path / "state",
        output_path=output_path,
    )
    artifact = json.loads(output_path.read_text(encoding="utf-8"))
    row = artifact["results"][0]

    assert len(adapter.calls) == 1
    assert adapter.calls[0][0] == case.message
    assert report.provider_call_count == 1
    assert report.copywriter_call_count == 0
    assert report.passed_count == 1
    assert report.end_to_end_rate == 1.0
    assert report.prompt_tokens == 11
    assert report.completion_tokens == 7
    assert report.total_tokens == 18
    assert row["input"]["message"] == case.message
    assert row["semantic_context"] == adapter.calls[0][1].model_dump(
        mode="json"
    )
    assert row["provider_output"] == replay.raw_turn_meaning.model_dump(
        mode="json"
    )
    assert row["provider_raw_output"] == (
        replay.raw_turn_meaning.model_dump_json()
    )
    assert row["provider_trace_id"] == "sha256:testtrace000000"
    assert row["trace"]["card_ids"] == list(
        replay.expected_card_ids
    )
    assert row["evaluation"]["passed"] is True
    assert len(row["input_sha256"]) == 64
    assert len(row["context_sha256"]) == 64
    assert len(row["provider_output_sha256"]) == 64
    assert len(row["provider_raw_output_sha256"]) == 64
    assert len(row["result_sha256"]) == 64
    assert artifact["summary"]["results_sha256"]


def test_invalid_output_is_recorded_without_retry(
    tmp_path: Path,
) -> None:
    replay = load_replay_cases(
        "tests/fixtures/guide/intent/unified_router_offline_v1.jsonl",
        manifest_path=(
            "tests/fixtures/guide/intent/"
            "unified_router_offline_v1_manifest.json"
        ),
    )[0]
    case = RealUnifiedRouterCase.from_replay_case(
        replay,
        category="recommendation",
    )
    adapter = InvalidRawAdapter()
    output_path = tmp_path / "invalid-real-gate.json"

    report = run_real_unified_router_gate(
        adapter=adapter,
        cases=(case,),
        concept_catalog=_catalog(),
        repo_root=Path.cwd(),
        state_root=tmp_path / "invalid-state",
        output_path=output_path,
    )
    row = json.loads(output_path.read_text(encoding="utf-8"))[
        "results"
    ][0]

    assert adapter.calls == 1
    assert report.provider_call_count == 1
    assert report.passed_count == 0
    assert report.total_tokens == 13
    assert row["status"] == "invalid_output"
    assert row["provider_raw_output"] == (
        '{"operation_hint":"recommendation"'
    )
    assert row["provider_trace_id"] == "sha256:invalidraw0000"
    assert len(row["provider_raw_output_sha256"]) == 64


def test_captured_provider_outputs_replay_without_model_calls(
    tmp_path: Path,
) -> None:
    replay = load_replay_cases(
        "tests/fixtures/guide/intent/unified_router_offline_v1.jsonl",
        manifest_path=(
            "tests/fixtures/guide/intent/"
            "unified_router_offline_v1_manifest.json"
        ),
    )[0]
    case = RealUnifiedRouterCase.from_replay_case(
        replay,
        category="recommendation",
    )
    evidence_path = tmp_path / "captured-source.json"
    run_real_unified_router_gate(
        adapter=RecordingAdapter(replay.raw_turn_meaning),
        cases=(case,),
        concept_catalog=_catalog(),
        repo_root=Path.cwd(),
        state_root=tmp_path / "capture-state",
        output_path=evidence_path,
    )
    replay_path = tmp_path / "captured-replay.json"

    report = real_gate.replay_captured_unified_router_results(
        cases=(case,),
        evidence_path=evidence_path,
        repo_root=Path.cwd(),
        state_root=tmp_path / "replay-state",
        output_path=replay_path,
    )
    artifact = json.loads(replay_path.read_text(encoding="utf-8"))

    assert report.case_count == 1
    assert report.captured_output_count == 1
    assert report.replayed_count == 1
    assert report.passed_count == 1
    assert report.provider_call_count == 0
    assert report.copywriter_call_count == 0
    assert report.passed
    assert artifact["results"][0]["evaluation"]["passed"] is True


def test_captured_replay_uses_blind_thresholds_without_ignoring_outputs(
) -> None:
    category_rates = {
        "recommendation": 0.96,
        "image": 0.86,
        "state_transition": 0.95,
    }

    assert real_gate.captured_replay_meets_blind_thresholds(
        case_count=100,
        captured_output_count=100,
        end_to_end_rate=0.98,
        category_rates=category_rates,
        wrong_product_selection_count=0,
        unauthorized_state_transition_count=0,
        hard_condition_override_count=0,
        unsafe_downgrade_count=0,
        cross_session_leak_count=0,
    )
    assert not real_gate.captured_replay_meets_blind_thresholds(
        case_count=100,
        captured_output_count=99,
        end_to_end_rate=0.98,
        category_rates=category_rates,
        wrong_product_selection_count=0,
        unauthorized_state_transition_count=0,
        hard_condition_override_count=0,
        unsafe_downgrade_count=0,
        cross_session_leak_count=0,
    )
    assert not real_gate.captured_replay_meets_blind_thresholds(
        case_count=100,
        captured_output_count=100,
        end_to_end_rate=0.98,
        category_rates={**category_rates, "image": 0.79},
        wrong_product_selection_count=0,
        unauthorized_state_transition_count=0,
        hard_condition_override_count=0,
        unsafe_downgrade_count=0,
        cross_session_leak_count=0,
    )
    assert not real_gate.captured_replay_meets_blind_thresholds(
        case_count=100,
        captured_output_count=100,
        end_to_end_rate=0.98,
        category_rates=category_rates,
        wrong_product_selection_count=1,
        unauthorized_state_transition_count=0,
        hard_condition_override_count=0,
        unsafe_downgrade_count=0,
        cross_session_leak_count=0,
    )


def test_real_case_manifest_rejects_tampered_fixture(
    tmp_path: Path,
) -> None:
    replay = load_replay_cases(
        "tests/fixtures/guide/intent/unified_router_offline_v1.jsonl",
        manifest_path=(
            "tests/fixtures/guide/intent/"
            "unified_router_offline_v1_manifest.json"
        ),
    )[0]
    case = RealUnifiedRouterCase.from_replay_case(
        replay,
        category="recommendation",
    )
    raw = case.model_dump_json().encode("utf-8") + b"\n"
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_bytes(raw)
    manifest = real_gate.build_real_case_manifest(
        raw,
        cases=(case,),
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        manifest.model_dump_json(),
        encoding="utf-8",
    )

    assert real_gate.load_real_unified_router_cases(
        cases_path,
        manifest_path=manifest_path,
    ) == (case,)

    cases_path.write_bytes(raw.replace(b"500", b"501", 1))
    with pytest.raises(ValueError, match="SHA-256"):
        real_gate.load_real_unified_router_cases(
            cases_path,
            manifest_path=manifest_path,
        )


def test_cli_runs_frozen_cases_with_copywriter_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    replay = load_replay_cases(
        "tests/fixtures/guide/intent/unified_router_offline_v1.jsonl",
        manifest_path=(
            "tests/fixtures/guide/intent/"
            "unified_router_offline_v1_manifest.json"
        ),
    )[0]
    case = RealUnifiedRouterCase.from_replay_case(
        replay,
        category="recommendation",
    )
    raw = case.model_dump_json().encode("utf-8") + b"\n"
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_bytes(raw)
    manifest = real_gate.build_real_case_manifest(
        raw,
        cases=(case,),
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        manifest.model_dump_json(),
        encoding="utf-8",
    )
    adapter = RecordingAdapter(replay.raw_turn_meaning)
    monkeypatch.setattr(
        real_gate,
        "read_private_api_key",
        lambda path: "test-key",
        raising=False,
    )
    monkeypatch.setattr(
        real_gate,
        "_build_adapter",
        lambda **kwargs: adapter,
        raising=False,
    )
    output_path = tmp_path / "cli-evidence.json"

    exit_code = real_gate.main(
        [
            "--cases",
            str(cases_path),
            "--manifest",
            str(manifest_path),
            "--output",
            str(output_path),
            "--repo-root",
            str(Path.cwd()),
            "--key-path",
            str(tmp_path / "unused.key"),
            "--disable-copywriter",
        ]
    )
    summary = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert summary["passed"] is True
    assert summary["case_count"] == 1
    assert len(adapter.calls) == 1
    assert output_path.is_file()


def test_smoke_builder_freezes_exactly_forty_mixed_cases() -> None:
    replays = load_replay_cases(
        "tests/fixtures/guide/intent/unified_router_offline_v1.jsonl",
        manifest_path=(
            "tests/fixtures/guide/intent/"
            "unified_router_offline_v1_manifest.json"
        ),
    )

    first = build_unified_router_smoke_cases(replays)
    second = build_unified_router_smoke_cases(replays)

    assert len(first) == 40
    assert len({case.case_id for case in first}) == 40
    assert {case.category for case in first} == {
        "recommendation",
        "comparison",
        "product_knowledge",
        "general_knowledge",
        "image",
        "consultation",
        "clarification",
        "safety",
        "state_transition",
    }
    assert (
        b"\n".join(
            case.model_dump_json().encode("utf-8")
            for case in first
        )
        == b"\n".join(
            case.model_dump_json().encode("utf-8")
            for case in second
        )
    )
    by_id = {case.case_id: case for case in first}
    returned = by_id["offline-return-product-focus-001"]
    assert returned.acceptable_task_modes == (
        "knowledge",
        "followup",
    )
    assert returned.acceptable_presentation_modes == (
        "product_knowledge",
        "followup",
    )
    safety = by_id["offline-safety-active-damage-001"]
    assert set(safety.acceptable_semantic.topic_hints) == {
        "skincare",
        None,
    }
    assert set(safety.acceptable_semantic.continuity_hints) == {
        "new_task",
        "unknown",
    }
    friend = by_id["offline-friend-profile-isolation-001"]
    assert friend.acceptable_semantic.subject_scope_hints == (
        "other",
    )
    followup = by_id["offline-followup-second-product-001"]
    assert "recommendation" not in (
        followup.acceptable_semantic.operation_hints
    )


def test_frozen_smoke_v2_matches_current_offline_bases() -> None:
    replays = load_replay_cases(
        "tests/fixtures/guide/intent/unified_router_offline_v1.jsonl",
        manifest_path=(
            "tests/fixtures/guide/intent/"
            "unified_router_offline_v1_manifest.json"
        ),
    )
    generated = (
        b"\n".join(
            case.model_dump_json().encode("utf-8")
            for case in build_unified_router_smoke_cases(replays)
        )
        + b"\n"
    )

    assert (
        Path(
            "tests/fixtures/guide/intent/"
            "unified_router_smoke_v2.jsonl"
        ).read_bytes()
        == generated
    )


def test_smoke_v3_allows_confirmed_image_topic_from_binding() -> None:
    replays = load_replay_cases(
        "tests/fixtures/guide/intent/unified_router_offline_v1.jsonl",
        manifest_path=(
            "tests/fixtures/guide/intent/"
            "unified_router_offline_v1_manifest.json"
        ),
    )

    cases = smoke_fixture.build_unified_router_smoke_v3_cases(replays)
    by_id = {case.case_id: case for case in cases}

    assert len(cases) == 40
    assert set(
        by_id[
            "offline-confirmed-image-suitability-001"
        ].acceptable_semantic.topic_hints
    ) == {"sunscreen", None}


def test_frozen_smoke_v3_matches_v3_builder() -> None:
    replays = load_replay_cases(
        "tests/fixtures/guide/intent/unified_router_offline_v1.jsonl",
        manifest_path=(
            "tests/fixtures/guide/intent/"
            "unified_router_offline_v1_manifest.json"
        ),
    )
    generated = (
        b"\n".join(
            case.model_dump_json().encode("utf-8")
            for case in (
                smoke_fixture.build_unified_router_smoke_v3_cases(
                    replays
                )
            )
        )
        + b"\n"
    )

    assert (
        Path(
            "tests/fixtures/guide/intent/"
            "unified_router_smoke_v3.jsonl"
        ).read_bytes()
        == generated
    )


def test_production_adapter_uses_supported_output_limit() -> None:
    adapter = real_gate._build_adapter(
        api_key="not-a-real-key",
        model="deepseek-v4-pro",
        concept_ids=("texture.refreshing",),
        case_count=1,
    )
    try:
        assert adapter._max_tokens == 1024
    finally:
        adapter.close()


def test_real_case_can_freeze_multiple_acceptable_presentations() -> None:
    replay = next(
        case
        for case in load_replay_cases(
            "tests/fixtures/guide/intent/unified_router_offline_v1.jsonl",
            manifest_path=(
                "tests/fixtures/guide/intent/"
                "unified_router_offline_v1_manifest.json"
            ),
        )
        if case.case_id == "offline-return-product-focus-001"
    )
    payload = RealUnifiedRouterCase.from_replay_case(
        replay,
        category="state_transition",
    ).model_dump(mode="python")
    payload["acceptable_task_modes"] = ("knowledge", "followup")
    payload["acceptable_presentation_modes"] = (
        "product_knowledge",
        "followup",
    )
    case = RealUnifiedRouterCase.model_validate(payload, strict=True)

    evaluation_case = case.to_evaluation_replay_case(
        replay.raw_turn_meaning,
        task_mode="followup",
        presentation_mode="followup",
    )

    assert evaluation_case.expected_task_plan["mode"] == "followup"
    assert evaluation_case.expected_presentation_mode == "followup"
