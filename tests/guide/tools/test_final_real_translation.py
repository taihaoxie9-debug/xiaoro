from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.guide.adapters.llm.contracts import SemanticTokenUsage
from app.guide.feedback.contracts import RecommendationQueryContext
from app.guide.understanding.turn_meaning_contracts import TurnMeaning
from tools.guide_gates import run_final_real_translation as translation_gate
from tools.guide_gates.run_final_real_translation import (
    FINAL_TRANSLATION_CASE_COUNT,
    FINAL_TRANSLATION_TURNS_PER_TRAJECTORY,
    load_final_translation_trajectories,
    replay_final_translation_gate,
    run_final_translation_gate,
)


FIXTURE = Path(
    "tests/fixtures/guide/final_release/"
    "real_translation_12x4_v5.jsonl"
)
V4_FIXTURE = Path(
    "tests/fixtures/guide/final_release/"
    "real_translation_12x4_v4.jsonl"
)


@dataclass(frozen=True)
class FakeCall:
    meaning: TurnMeaning
    raw_content: str
    trace_id: str
    usage: SemanticTokenUsage


class RecordingAdapter:
    model = "deepseek-v4-pro"
    prompt_version = "test-final-translation-v1"

    def __init__(self) -> None:
        self.calls = 0

    def propose_with_result(
        self,
        message: str,
        context,
    ) -> FakeCall:
        del message, context
        self.calls += 1
        meaning = TurnMeaning(
            operation_hint="clarification",
            topic_hint=None,
            continuity_hint="unknown",
            subject_scope_hint="unknown",
            pending_response_hint="unknown",
            safety_language="unknown",
        )
        return FakeCall(
            meaning=meaning,
            raw_content=meaning.model_dump_json(),
            trace_id=f"trace-{self.calls}",
            usage=SemanticTokenUsage(
                prompt_tokens=1,
                completion_tokens=1,
                total_tokens=2,
            ),
        )


class WrongRecommendationModeAdapter(RecordingAdapter):
    def propose_with_result(
        self,
        message: str,
        context,
    ) -> FakeCall:
        del message, context
        self.calls += 1
        meaning = TurnMeaning.model_validate(
            {
                "operation_hint": "recommendation",
                "recommendation_mode": "explore",
                "recommendation_count": None,
                "recommendation_mode_basis": {
                    "basis": "broad_exploration",
                    "source_text": "推荐",
                },
                "topic_hint": "sunscreen",
                "continuity_hint": "new_task",
                "subject_scope_hint": "self",
                "pending_response_hint": "unknown",
                "reference_mentions": [],
                "product_mentions": [],
                "budget_candidates": [
                    {
                        "raw_text": "三百以内",
                        "relation": "maximum",
                        "minimum": None,
                        "maximum": "300",
                    }
                ],
                "observation_candidates": [],
                "preference_candidates": [],
                "constraint_changes": [],
                "relative_candidates": [],
                "consultation_hypothesis": None,
                "next_observation_gap": None,
                "question_meaning": None,
                "safety_language": "ordinary",
            },
            strict=True,
        )
        return FakeCall(
            meaning=meaning,
            raw_content=meaning.model_dump_json(),
            trace_id=f"trace-{self.calls}",
            usage=SemanticTokenUsage(
                prompt_tokens=1,
                completion_tokens=1,
                total_tokens=2,
            ),
        )


def test_final_translation_fixture_is_twelve_four_turn_trajectories() -> None:
    trajectories = load_final_translation_trajectories(FIXTURE)

    assert len(trajectories) == FINAL_TRANSLATION_CASE_COUNT
    assert all(
        len(item.turns) == FINAL_TRANSLATION_TURNS_PER_TRAJECTORY
        for item in trajectories
    )
    assert len({
        turn.turn_id
        for item in trajectories
        for turn in item.turns
    }) == 48


def test_v5_fixture_preserves_v4_messages_and_seals_mode_truth() -> None:
    v4 = [
        json.loads(line)
        for line in V4_FIXTURE.read_text(encoding="utf-8").splitlines()
    ]
    v5 = [
        json.loads(line)
        for line in FIXTURE.read_text(encoding="utf-8").splitlines()
    ]

    assert [
        turn["case"]["message"]
        for trajectory in v5
        for turn in trajectory["turns"]
    ] == [
        turn["case"]["message"]
        for trajectory in v4
        for turn in trajectory["turns"]
    ]
    assert all(
        {
            "expected_recommendation_mode",
            "expected_recommendation_mode_basis",
            "image_product_ids",
        }
        <= set(turn)
        for trajectory in v5
        for turn in trajectory["turns"]
    )
    assert all(
        len(turn["image_product_ids"])
        == turn["case"]["context"]["image_count"]
        and len(set(turn["image_product_ids"]))
        == len(turn["image_product_ids"])
        and all(
            type(product_id) is int and product_id > 0
            for product_id in turn["image_product_ids"]
        )
        for trajectory in v5
        for turn in trajectory["turns"]
    )


def test_embedded_identity_operation_forbids_recommendation_outcome() -> None:
    expected = translation_gate.derive_final_turn_expectations(
        operation_hints=("image_identity",),
        embedded_recommendation_mode="explore",
        embedded_recommendation_mode_basis="similar_alternatives",
        expected_objects=("image:1",),
        conversation_version=2,
        allowed_continuity_hints=("new_task", "unknown"),
    )

    assert expected.recommendation_mode is None
    assert expected.recommendation_mode_basis is None


def test_bound_context_allows_continue_without_case_identity() -> None:
    expected = translation_gate.derive_final_turn_expectations(
        operation_hints=("comparison",),
        embedded_recommendation_mode=None,
        embedded_recommendation_mode_basis=None,
        expected_objects=("candidate_batch",),
        conversation_version=2,
        allowed_continuity_hints=("new_task", "unknown"),
    )

    assert expected.allowed_continuity_hints == (
        "continue",
        "new_task",
        "unknown",
    )


def test_v5_truth_is_derived_from_each_embedded_contract() -> None:
    trajectories = load_final_translation_trajectories(FIXTURE)

    for trajectory in trajectories:
        for turn in trajectory.turns:
            expected = translation_gate.derive_final_turn_expectations(
                operation_hints=(
                    turn.case.translation.allowed_operation_hints
                ),
                embedded_recommendation_mode=(
                    turn.case.execution.expected_recommendation_mode
                ),
                embedded_recommendation_mode_basis=(
                    turn.case.execution
                    .expected_recommendation_mode_basis
                ),
                expected_objects=turn.case.binding.expected_objects,
                conversation_version=turn.case.context.conversation_version,
                allowed_continuity_hints=turn.allowed_continuity_hints,
                must_clarify=turn.case.execution.must_clarify,
            )

            assert turn.expected_recommendation_mode == (
                expected.recommendation_mode
            )
            assert turn.expected_recommendation_mode_basis == (
                expected.recommendation_mode_basis
            )
            assert turn.case.execution.expected_recommendation_mode == (
                expected.recommendation_mode
            )
            assert (
                turn.case.execution.expected_recommendation_mode_basis
                == expected.recommendation_mode_basis
            )
            assert turn.allowed_continuity_hints == (
                expected.allowed_continuity_hints
            )


def test_v5_recommendation_before_states_match_current_schema() -> None:
    trajectories = load_final_translation_trajectories(FIXTURE)

    for trajectory in trajectories:
        for turn in trajectory.turns:
            before_state = turn.case.before_state
            if before_state is None:
                continue
            RecommendationQueryContext.model_validate_json(
                json.dumps(before_state, ensure_ascii=False),
                strict=True,
            )


def test_final_translation_gate_stops_after_first_failed_turn(
    tmp_path: Path,
) -> None:
    trajectories = load_final_translation_trajectories(FIXTURE)
    adapter = RecordingAdapter()

    report = run_final_translation_gate(
        trajectories=trajectories,
        adapter=adapter,
        output_dir=tmp_path / "capture",
    )

    assert adapter.calls == 1
    assert report.provider_call_count == 1
    assert report.turn_count == 1
    assert not report.passed
    assert report.stopped_early


def test_final_translation_rejects_wrong_recommendation_mode_truth(
    tmp_path: Path,
) -> None:
    trajectories = load_final_translation_trajectories(FIXTURE)
    output = tmp_path / "wrong-mode"

    report = run_final_translation_gate(
        trajectories=trajectories,
        adapter=WrongRecommendationModeAdapter(),
        output_dir=output,
    )

    row = json.loads(
        (output / "results.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert report.passed is False
    assert row["recommendation_mode_passed"] is False


def test_final_translation_replay_uses_zero_provider_calls(
    tmp_path: Path,
) -> None:
    trajectories = load_final_translation_trajectories(FIXTURE)
    source_dir = tmp_path / "capture"
    adapter = RecordingAdapter()
    run_final_translation_gate(
        trajectories=trajectories,
        adapter=adapter,
        output_dir=source_dir,
    )

    replay = replay_final_translation_gate(
        trajectories=trajectories,
        capture_path=source_dir / "results.jsonl",
        output_dir=tmp_path / "replay",
    )

    assert replay.provider_call_count == 0
    assert replay.turn_count == 1
    assert not replay.passed


def test_final_translation_replay_rejects_duplicate_prefix_turn(
    tmp_path: Path,
) -> None:
    trajectories = load_final_translation_trajectories(FIXTURE)
    source_dir = tmp_path / "capture"
    run_final_translation_gate(
        trajectories=trajectories,
        adapter=RecordingAdapter(),
        output_dir=source_dir,
    )
    first = (
        source_dir / "results.jsonl"
    ).read_text(encoding="utf-8").splitlines()[0]
    duplicate_capture = tmp_path / "duplicate-results.jsonl"
    duplicate_capture.write_text(f"{first}\n{first}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="contiguous prefix"):
        replay_final_translation_gate(
            trajectories=trajectories,
            capture_path=duplicate_capture,
            output_dir=tmp_path / "replay",
        )


def test_completed_translation_evidence_accepts_complete_validated_capture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    trajectories = load_final_translation_trajectories(FIXTURE)
    rows = tuple(
        translation_gate.FinalTranslationRow(
            trajectory_id=trajectory.trajectory_id,
            turn_id=turn.turn_id,
            case_id=turn.case.case_id,
            status="ok",
            provider_failure_code=None,
            schema_valid=True,
            translation_passed=True,
            source_grounded=True,
            binding_passed=True,
            task_plan_passed=True,
            continuity_passed=True,
            subject_scope_passed=True,
            recommendation_mode_passed=True,
            passed=True,
            failure_layer=None,
            wrong_product_or_image_binding_count=0,
            unsafe_downgrade_count=0,
            internal_public_language_count=0,
            provider_raw_output="{}",
            provider_output={},
            compiled_references=(),
            responsibility=turn.case.execution.expected_task_mode,
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            latency_ms=1.0,
            input_sha256="1" * 64,
            context_sha256="2" * 64,
            provider_raw_output_sha256="3" * 64,
            provider_output_sha256="4" * 64,
        )
        for trajectory in trajectories
        for turn in trajectory.turns
    )
    attempt_root = tmp_path / "translation-attempt-01"
    attempt_root.mkdir()
    focused = attempt_root / "focused.json"
    focused.write_text(
        json.dumps(
            {
                "schema_version": "guide-final-focused-gate-v1",
                "passed": True,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    report = translation_gate._write_report(
        rows=rows,
        trajectories=trajectories,
        model=translation_gate.DEEPSEEK_V4_PRO_MODEL,
        prompt_version="test-complete-capture-v1",
        provider_call_count=FINAL_TRANSLATION_CASE_COUNT
        * FINAL_TRANSLATION_TURNS_PER_TRAJECTORY,
        output_dir=attempt_root / "real-translation",
        stop_reason=None,
        focused_summary_sha256=sha256(focused.read_bytes()).hexdigest(),
        fixture_path=translation_gate.FINAL_TRANSLATION_FIXTURE_PATH,
        fixture_sha256=sha256(FIXTURE.read_bytes()).hexdigest(),
    )
    observed: dict[str, object] = {}

    def validate_rows(*, trajectories, rows):
        observed["trajectory_count"] = len(trajectories)
        observed["row_count"] = len(rows)
        assert [
            (row["trajectory_id"], row["turn_id"], row["case_id"])
            for row in rows
        ] == [
            (row.trajectory_id, row.turn_id, row.case_id)
            for row in rows_expected
        ]
        return rows_expected

    rows_expected = rows

    monkeypatch.setattr(
        translation_gate,
        "validate_final_translation_rows",
        validate_rows,
    )

    validated = (
        translation_gate.validate_completed_final_translation_evidence(
            attempt_root
        )
    )

    assert validated == report
    assert observed == {"trajectory_count": 12, "row_count": 48}


def test_cli_requires_attempt_context_and_translation_phase() -> None:
    parsed = translation_gate._parse_args([
        "--cases",
        str(FIXTURE),
        "--attempt-context",
        "attempt-context.json",
        "--phase",
        "translation",
        "--key-path",
        "private-key",
        "--model",
        "deepseek-v4-pro",
        "--state-dir",
        "/tmp/xiaoro-final-translation-test-state",
    ])

    assert parsed.attempt_context == "attempt-context.json"
    assert parsed.phase == "translation"
    assert not hasattr(parsed, "output_dir")

    with pytest.raises(SystemExit):
        translation_gate._parse_args([
            "--cases",
            str(FIXTURE),
            "--output-dir",
            "arbitrary-output",
        ])


def test_cli_defaults_to_frozen_v5_translation_fixture() -> None:
    parsed = translation_gate._parse_args([
        "--attempt-context",
        "attempt-context.json",
        "--phase",
        "translation",
        "--state-dir",
        "/tmp/xiaoro-final-translation-test-state",
    ])

    assert Path(parsed.cases).resolve() == FIXTURE.resolve()


def test_authorized_translation_rejects_noncanonical_model_before_context(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ValueError,
        match="model must be deepseek-v4-pro",
    ):
        translation_gate.run_authorized_final_translation(
            cases_path=FIXTURE,
            attempt_context_path=tmp_path / "missing-context.json",
            phase="translation",
            key_path=tmp_path / "missing-key",
            model="deepseek-chat",
            state_dir=tmp_path / "shared-state",
        )


def test_authorized_translation_consumes_before_provider_and_completes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context_path = tmp_path / "attempt" / "attempt-context.json"
    context_path.parent.mkdir(parents=True)
    readiness_path = tmp_path / "release-readiness.json"
    ledger_path = tmp_path / "ledger.json"
    context_path.write_text(
        json.dumps({
            "readiness_path": str(readiness_path),
            "ledger_path": str(ledger_path),
            "output_directory": str(context_path.parent),
            "current_phase": "translation",
            "phase_attempt_ids": {"translation": "translation-attempt-01"},
        }),
        encoding="utf-8",
    )
    focused_path = context_path.parent / "focused.json"
    focused_path.write_text(
        json.dumps(
            {
                "schema_version": "guide-final-focused-gate-v1",
                "passed": True,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    calls: list[str] = []
    shared_limiter = object()

    monkeypatch.setattr(
        translation_gate,
        "read_attempt_context",
        lambda *args, **kwargs: (
            calls.append("context")
            or json.loads(context_path.read_text(encoding="utf-8"))
        ),
        raising=False,
    )
    monkeypatch.setattr(
        translation_gate,
        "verify_task11_readiness",
        lambda **kwargs: calls.append("readiness") or {"passed": True},
        raising=False,
    )
    monkeypatch.setattr(
        translation_gate,
        "read_private_api_key",
        lambda path: calls.append("key") or "private-key",
    )
    monkeypatch.setattr(
        translation_gate,
        "consume_attempt_context",
        lambda *args, **kwargs: calls.append("consume"),
        raising=False,
    )
    monkeypatch.setattr(
        translation_gate,
        "build_provider_usage_limiter",
        lambda **kwargs: (
            calls.append(f"quota:{kwargs['state_dir']}")
            or shared_limiter
        ),
        raising=False,
    )

    def build_adapter(**kwargs):
        assert kwargs["usage_limiter"] is shared_limiter
        calls.append("adapter")
        return SimpleNamespace(close=lambda: calls.append("close"))

    monkeypatch.setattr(
        translation_gate,
        "DeepSeekTurnMeaningAdapter",
        build_adapter,
    )
    report = SimpleNamespace(
        passed=True,
        model_dump_json=lambda: "{}",
    )

    def run_gate(**kwargs):
        calls.append("provider")
        assert kwargs["output_dir"] == (
            context_path.parent / "real-translation"
        )
        assert kwargs["focused_summary_sha256"] == sha256(
            focused_path.read_bytes()
        ).hexdigest()
        assert kwargs["fixture_path"] == FIXTURE.as_posix()
        assert kwargs["fixture_sha256"] == sha256(
            FIXTURE.read_bytes()
        ).hexdigest()
        return report

    monkeypatch.setattr(
        translation_gate,
        "run_final_translation_gate",
        run_gate,
    )
    monkeypatch.setattr(
        translation_gate,
        "complete_attempt",
        lambda *args, **kwargs: calls.append(
            f"complete:{kwargs['result']}"
        ),
        raising=False,
    )

    result = translation_gate.run_authorized_final_translation(
        cases_path=FIXTURE,
        attempt_context_path=context_path,
        phase="translation",
        key_path=tmp_path / "private-key",
        model="deepseek-v4-pro",
        state_dir=tmp_path / "shared-state",
    )

    assert result is report
    assert calls.index("readiness") < calls.index("consume")
    assert calls.index(f"quota:{tmp_path / 'shared-state'}") < (
        calls.index("consume")
    )
    assert calls.index("consume") < calls.index("provider")
    assert calls[-1] == "complete:passed"


def test_cli_requires_shared_provider_state_directory() -> None:
    with pytest.raises(SystemExit):
        translation_gate._parse_args([
            "--attempt-context",
            "attempt-context.json",
            "--phase",
            "translation",
        ])


def test_authorized_translation_rejects_noncanonical_fixture_before_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context_path = tmp_path / "attempt" / "attempt-context.json"
    context_path.parent.mkdir(parents=True)
    readiness_path = tmp_path / "release-readiness.json"
    ledger_path = tmp_path / "ledger.json"
    context = {
        "readiness_path": str(readiness_path),
        "ledger_path": str(ledger_path),
        "output_directory": str(context_path.parent),
        "current_phase": "translation",
        "phase_attempt_ids": {
            "translation": "translation-attempt-01"
        },
    }
    context_path.write_text(json.dumps(context), encoding="utf-8")
    (context_path.parent / "focused.json").write_text(
        json.dumps(
            {
                "schema_version": "guide-final-focused-gate-v1",
                "passed": True,
            }
        ),
        encoding="utf-8",
    )
    alternate = tmp_path / "real_translation_12x4_v5.jsonl"
    alternate.write_bytes(FIXTURE.read_bytes())
    monkeypatch.setattr(
        translation_gate,
        "read_attempt_context",
        lambda *args, **kwargs: context,
    )
    monkeypatch.setattr(
        translation_gate,
        "verify_task11_readiness",
        lambda **kwargs: {},
    )
    monkeypatch.setattr(
        translation_gate,
        "read_private_api_key",
        lambda path: pytest.fail("key must not be read"),
    )
    monkeypatch.setattr(
        translation_gate,
        "consume_attempt_context",
        lambda *args, **kwargs: pytest.fail(
            "authorization must not be consumed"
        ),
    )

    with pytest.raises(ValueError, match="canonical v5 fixture"):
        translation_gate.run_authorized_final_translation(
            cases_path=alternate,
            attempt_context_path=context_path,
            phase="translation",
            key_path=tmp_path / "private-key",
            model="deepseek-v4-pro",
            state_dir=tmp_path / "shared-state",
        )


def test_authorized_translation_requires_passed_focused_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    context_path = tmp_path / "attempt" / "attempt-context.json"
    context_path.parent.mkdir(parents=True)
    readiness_path = tmp_path / "release-readiness.json"
    ledger_path = tmp_path / "ledger.json"
    context = {
        "readiness_path": str(readiness_path),
        "ledger_path": str(ledger_path),
        "output_directory": str(context_path.parent),
        "current_phase": "translation",
        "phase_attempt_ids": {
            "translation": "translation-attempt-01"
        },
    }
    context_path.write_text(json.dumps(context), encoding="utf-8")
    monkeypatch.setattr(
        translation_gate,
        "read_attempt_context",
        lambda *args, **kwargs: context,
    )
    monkeypatch.setattr(
        translation_gate,
        "verify_task11_readiness",
        lambda **kwargs: {},
    )
    monkeypatch.setattr(
        translation_gate,
        "consume_attempt_context",
        lambda *args, **kwargs: pytest.fail(
            "authorization must not be consumed"
        ),
    )

    with pytest.raises(
        ValueError,
        match="focused release summary",
    ):
        translation_gate.run_authorized_final_translation(
            cases_path=FIXTURE,
            attempt_context_path=context_path,
            phase="translation",
            key_path=tmp_path / "private-key",
            model="deepseek-v4-pro",
            state_dir=tmp_path / "shared-state",
        )
