from __future__ import annotations

import ast
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.guide.adapters.catalog.canonical_product_reader import (
    CanonicalProductReader,
)
from app.guide.understanding.turn_meaning_contracts import (
    TurnBudgetCandidate,
    TurnMeaning,
    TurnRecommendationModeBasis,
)
from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.retrieval.category_taxonomy import canonical_categories_for
from app.guide.understanding.contracts import TopicCode
from tools.guide_gates import attempt_ledger
from tools.guide_gates import replay_final_real_backend as backend_replay
from tools.guide_gates import run_final_real_translation as translation_gate
from tools.guide_gates.replay_final_real_backend import (
    BackendReplayError,
    replay_final_real_backend,
)
from tools.guide_gates.run_final_real_translation import (
    FINAL_TRANSLATION_FIXTURE_PATH,
)


SOURCE_PATH = Path("tools/guide_gates/replay_final_real_backend.py")
BASE_FIXTURE = Path(
    "tests/fixtures/guide/final_release/"
    "real_translation_12x4_v5.jsonl"
)
_HEAD = "a" * 40
_EXPECTED_MANIFEST_SHA256 = "f" * 64


@pytest.fixture(autouse=True)
def _verified_release_readiness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        backend_replay,
        "verify_task11_readiness",
        lambda **_: {},
        raising=False,
    )
    monkeypatch.setattr(
        translation_gate,
        "_DEFAULT_CASES",
        tmp_path / "real_translation_12x4_v5.jsonl",
    )


def _canonical_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _sha256_json(payload: object) -> str:
    return sha256(_canonical_bytes(payload).rstrip(b"\n")).hexdigest()


def _attempt_allocation_sha256(attempt: dict[str, object]) -> str:
    fields = {
        key: attempt.get(key)
        for key in (
            "attempt_id",
            "plan_revision",
            "repair_epoch",
            "retry_authorization_id",
            "code_revision",
            "started_at",
            "trajectory_set",
            "context_path",
        )
    }
    payload = (
        json.dumps(
            fields,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _meaning(kind: str) -> TurnMeaning:
    if kind == "recommendation":
        return TurnMeaning(
            operation_hint="recommendation",
            recommendation_mode="explore",
            recommendation_mode_basis=TurnRecommendationModeBasis(
                basis="bounded_exploration",
                source_text="预算三百以内",
            ),
            topic_hint="sunscreen",
            continuity_hint="new_task",
            subject_scope_hint="self",
            pending_response_hint="unknown",
            budget_candidates=(
                TurnBudgetCandidate(
                    raw_text="三百以内",
                    relation="maximum",
                    maximum="300",
                ),
            ),
            safety_language="ordinary",
        )
    if kind == "clarification":
        return TurnMeaning(
            operation_hint="clarification",
            topic_hint=None,
            continuity_hint="unknown",
            subject_scope_hint="unknown",
            pending_response_hint="unknown",
            safety_language="ordinary",
        )
    return TurnMeaning(
        operation_hint="knowledge",
        topic_hint="sunscreen",
        continuity_hint="new_task",
        subject_scope_hint="self",
        pending_response_hint="unknown",
        question_meaning="防晒为什么需要补涂",
        safety_language="ordinary",
    )


def test_captured_meaning_port_requires_exact_sealed_context() -> None:
    trajectory = translation_gate.load_final_translation_trajectories(
        BASE_FIXTURE
    )[0]
    turn = trajectory.turns[0]
    meaning = _meaning("recommendation")
    provider = backend_replay._CapturedMeaningPort()
    provider.bind(
        message=turn.case.message,
        meaning=meaning,
        expected_context=turn.case.context,
    )

    assert provider.propose(turn.case.message, turn.case.context) == meaning
    with pytest.raises(
        BackendReplayError,
        match="sealed context",
    ):
        provider.propose(
            turn.case.message,
            turn.case.context.model_copy(
                update={
                    "conversation_version": (
                        turn.case.context.conversation_version + 1
                    )
                }
            ),
        )


def test_canonical_fixture_contexts_are_materializable_for_backend() -> None:
    trajectories = translation_gate.load_final_translation_trajectories(
        BASE_FIXTURE
    )
    candidate_product_ids = (24, 26, 30, 32)

    for trajectory in trajectories:
        for turn in trajectory.turns:
            snapshot = backend_replay._materialize_replay_snapshot(
                turn=turn,
                session_id=f"replay-{turn.turn_id}",
                candidate_product_ids=candidate_product_ids,
            )
            assert backend_replay._resolved_replay_context(
                turn=turn,
                snapshot=snapshot,
            ) == turn.case.context


def test_replay_candidates_match_the_sealed_active_topic() -> None:
    reader = CanonicalProductReader.from_files(
        manifest_path=Path(
            "data/canonical/core_products_v1_manifest.json"
        ),
        products_path=Path("data/canonical/core_products_v1.jsonl"),
    )

    product_ids = backend_replay._candidate_product_ids_for_context(
        reader=reader,
        topic=TopicCode.SERUM,
        count=3,
    )

    assert len(product_ids) == 3
    assert all(
        reader.get(product_id).fields["category"].value
        in canonical_categories_for(TopicCode.SERUM)
        for product_id in product_ids
    )


def test_replay_responsibility_ignores_provisional_translation_mode() -> None:
    turns = tuple(
        turn
        for trajectory in translation_gate.load_final_translation_trajectories(
            BASE_FIXTURE
        )
        for turn in trajectory.turns
    )
    assessment = next(
        turn
        for turn in turns
        if turn.case.family == "assessment"
        and turn.required_safety_language != "safety"
    )
    safety = next(
        turn
        for turn in turns
        if turn.required_safety_language == "safety"
    )
    identity = next(
        turn
        for turn in turns
        if tuple(turn.case.translation.allowed_operation_hints)
        == ("image_identity",)
    )
    similarity = next(
        turn
        for turn in turns
        if "image_similarity"
        in turn.case.translation.allowed_operation_hints
        and not turn.case.execution.must_clarify
    )
    provisional = {"responsibility": "clarify"}

    assert backend_replay._expected_responsibility(
        provisional,
        assessment,
    ) == Responsibility.CONSULTATION.value
    assert backend_replay._expected_responsibility(
        provisional,
        safety,
    ) == Responsibility.SAFETY_ESCALATION.value
    assert backend_replay._expected_responsibility(
        provisional,
        identity,
    ) == Responsibility.IMAGE_IDENTITY.value
    assert backend_replay._expected_responsibility(
        provisional,
        similarity,
    ) == Responsibility.RECOMMENDATION.value


def _fixture_and_capture(
    tmp_path: Path,
    *,
    capture_count: int = 48,
) -> tuple[Path, list[dict[str, object]]]:
    source_rows = [
        json.loads(line)
        for line in BASE_FIXTURE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    recommendation_template = source_rows[0]["turns"][0]
    knowledge_template = source_rows[4]["turns"][0]
    clarification_template = source_rows[9]["turns"][0]
    fixture_rows: list[dict[str, object]] = []
    capture_rows: list[dict[str, object]] = []

    for trajectory_index in range(12):
        trajectory_id = f"backend-{trajectory_index + 1:02d}"
        turns: list[dict[str, object]] = []
        for turn_index in range(4):
            is_recommendation = turn_index == 0
            is_clarification = (
                trajectory_index == 11 and turn_index == 3
            )
            if is_clarification:
                turn = deepcopy(clarification_template)
                kind = "clarification"
                responsibility = "clarification"
            elif is_recommendation:
                turn = deepcopy(recommendation_template)
                kind = "recommendation"
                responsibility = "recommendation"
            else:
                turn = deepcopy(knowledge_template)
                kind = "knowledge"
                responsibility = "general_knowledge"
            turn_id = (
                f"backend-{trajectory_index + 1:02d}-"
                f"{turn_index + 1:02d}"
            )
            turn["trajectory_id"] = trajectory_id
            turn["turn_id"] = turn_id
            turn["case"]["case_id"] = turn_id
            turn["case"]["message"] = (
                "预算三百以内，推荐适合海边的防晒"
                if kind == "recommendation"
                else (
                    "第二个"
                    if kind == "clarification"
                    else "防晒为什么需要补涂"
                )
            )
            turn["case"]["execution"]["expected_task_mode"] = {
                "recommendation": "recommend",
                "knowledge": "knowledge",
                "clarification": "clarify",
            }[kind]
            task_mode = turn["case"]["execution"]["expected_task_mode"]
            turn["case"]["binding"]["expected_objects"] = []
            turns.append(turn)

            meaning_payload = _meaning(kind).model_dump(mode="json")
            typed_context = (
                translation_gate.FinalTranslationTurn.from_payload(
                    turn
                ).case.context.model_dump(mode="json")
            )
            raw_output = json.dumps(
                meaning_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            capture_rows.append(
                {
                    "trajectory_id": trajectory_id,
                    "turn_id": turn_id,
                    "case_id": turn_id,
                    "status": "ok",
                    "provider_failure_code": None,
                    "schema_valid": True,
                    "translation_passed": True,
                    "source_grounded": True,
                    "binding_passed": True,
                    "task_plan_passed": True,
                    "continuity_passed": True,
                    "subject_scope_passed": True,
                    "recommendation_mode_passed": True,
                    "passed": True,
                    "failure_layer": None,
                    "wrong_product_or_image_binding_count": 0,
                    "unsafe_downgrade_count": 0,
                    "internal_public_language_count": 0,
                    "provider_raw_output": raw_output,
                    "provider_output": meaning_payload,
                    "compiled_references": [],
                    "provider_output_sha256": _sha256_json(
                        meaning_payload
                    ),
                    "responsibility": task_mode,
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                    "latency_ms": 1.0,
                    "input_sha256": _sha256_json({
                        "message": turn["case"]["message"],
                        "context": typed_context,
                    }),
                    "context_sha256": _sha256_json(typed_context),
                    "provider_raw_output_sha256": sha256(
                        raw_output.encode("utf-8")
                    ).hexdigest(),
                }
            )
        fixture_rows.append(
            {
                "trajectory_id": trajectory_id,
                "family": "offline backend replay",
                "turns": turns,
                "critical": True,
            }
        )

    fixture = tmp_path / "real_translation_12x4_v5.jsonl"
    fixture.write_bytes(
        b"".join(_canonical_bytes(row) for row in fixture_rows)
    )
    return fixture, capture_rows[:capture_count]


def test_clarification_replay_rejects_wrong_route_responsibility() -> None:
    turn = next(
        turn
        for trajectory in (
            translation_gate.load_final_translation_trajectories(
                BASE_FIXTURE
            )
        )
        for turn in trajectory.turns
        if turn.case.execution.expected_task_mode == "clarify"
    )
    capture = backend_replay.CapturedMeaning(
        trajectory_id=turn.trajectory_id,
        turn_id=turn.turn_id,
        case_id=turn.case.case_id,
        meaning=_meaning("clarification"),
        expected_responsibility="clarification",
    )
    decision = SimpleNamespace(
        responsibility=Responsibility.RECOMMENDATION,
        product_bindings=(),
    )
    payload = (
        b'event: start\ndata: {"session_id":"replay"}\n\n'
        b'event: clarify\ndata: {"question":"\\u8bf7\\u8865\\u5145\\u9700\\u6c42",'
        b'"clarification_code":"goal"}\n\n'
        b'event: end\ndata: {"conversation_version":1}\n\n'
    )

    trace = backend_replay._evaluate_http_turn(
        turn=turn,
        capture=capture,
        status_code=200,
        payload=payload,
        injected_meaning=capture.meaning,
        decision=decision,
        result=SimpleNamespace(decision=decision),
        translation_injection_count=1,
        image_product_ids=(),
        image_asset_sha256s=(),
        sealed_context_sha256="a" * 64,
        observed_context_sha256="a" * 64,
    )

    assert trace.wrong_responsibility_count == 1
    assert trace.passed is False


def test_image_comparison_accepts_typed_topic_clarification() -> None:
    turn = next(
        turn
        for trajectory in (
            translation_gate.load_final_translation_trajectories(
                BASE_FIXTURE
            )
        )
        for turn in trajectory.turns
        if (
            "comparison"
            in turn.case.translation.allowed_operation_hints
            and turn.case.context.image_count > 0
        )
    )
    meaning = TurnMeaning(
        operation_hint="comparison",
        topic_hint=None,
        continuity_hint="continue",
        subject_scope_hint="unknown",
        pending_response_hint="unknown",
        safety_language="ordinary",
    )
    capture = backend_replay.CapturedMeaning(
        trajectory_id=turn.trajectory_id,
        turn_id=turn.turn_id,
        case_id=turn.case.case_id,
        meaning=meaning,
        expected_responsibility="comparison",
    )
    decision = SimpleNamespace(
        responsibility=Responsibility.COMPARISON,
        product_bindings=(),
    )
    payload = (
        b'event: start\ndata: {"session_id":"replay"}\n\n'
        b'event: clarify\ndata: {"question":"'
        b'\\u8bf7\\u9009\\u62e9\\u540c\\u54c1\\u7c7b\\u5546\\u54c1",'
        b'"clarification_code":"topic"}\n\n'
        b'event: end\ndata: {"conversation_version":1}\n\n'
    )

    trace = backend_replay._evaluate_http_turn(
        turn=turn,
        capture=capture,
        status_code=200,
        payload=payload,
        injected_meaning=meaning,
        decision=decision,
        result=SimpleNamespace(decision=decision),
        translation_injection_count=1,
        image_product_ids=turn.image_product_ids,
        image_asset_sha256s=tuple(
            "a" * 64 for _ in turn.image_product_ids
        ),
        sealed_context_sha256="b" * 64,
        observed_context_sha256="b" * 64,
    )

    assert trace.clarification is True
    assert trace.passed is True


def _attempt_context(
    tmp_path: Path,
    capture_rows: list[dict[str, object]],
    fixture: Path,
) -> Path:
    attempt_root = tmp_path / "translation-attempt-01"
    translation = attempt_root / "real-translation"
    translation.mkdir(parents=True)
    results_bytes = b"".join(
        _canonical_bytes(row) for row in capture_rows
    )
    results_sha256 = sha256(results_bytes).hexdigest()
    (translation / "results.jsonl").write_bytes(results_bytes)
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
    summary = {
        "schema_version": "guide-final-real-translation-summary-v1",
        "passed": True,
        "trajectory_count": 12,
        "critical_trajectory_count": 12,
        "critical_trajectory_passed": 12,
        "expected_turn_count": 48,
        "turn_count": len(capture_rows),
        "provider_call_count": len(capture_rows),
        "stopped_early": False,
        "passed_turn_count": len(capture_rows),
        "schema_valid_count": len(capture_rows),
        "translation_passed_count": len(capture_rows),
        "source_grounded_count": len(capture_rows),
        "binding_passed_count": len(capture_rows),
        "task_plan_passed_count": len(capture_rows),
        "recommendation_mode_passed_count": len(capture_rows),
        "wrong_binding_count": 0,
        "wrong_product_or_image_binding_count": 0,
        "unsafe_downgrade_count": 0,
        "internal_language_count": 0,
        "internal_public_language_count": 0,
        "serious_failure_count": 0,
        "focused_summary_sha256": sha256(
            focused.read_bytes()
        ).hexdigest(),
        "fixture_path": FINAL_TRANSLATION_FIXTURE_PATH,
        "fixture_sha256": sha256(fixture.read_bytes()).hexdigest(),
        "results_sha256": results_sha256,
    }
    summary_bytes = _canonical_bytes(summary)
    (translation / "summary.json").write_bytes(summary_bytes)
    (translation / "SHA256SUMS").write_text(
        (
            f"{results_sha256}  results.jsonl\n"
            f"{sha256(summary_bytes).hexdigest()}  summary.json\n"
        ),
        encoding="ascii",
    )

    readiness = tmp_path / "readiness.json"
    readiness.write_text(
        json.dumps(
            {
                "schema_version": "guide-task11-readiness-v1",
                "plan_revision": "2026-08-23-task11-r5",
                "candidate_head": _HEAD,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    ledger = tmp_path / "ledger.json"
    context = attempt_root / "attempt-context.json"
    attempt: dict[str, object] = {
        "attempt_id": "translation-attempt-01",
        "plan_revision": "2026-08-23-task11-r5",
        "repair_epoch": 8,
        "retry_authorization_id": "auth-translation",
        "code_revision": _HEAD,
        "expected_manifest_sha256": _EXPECTED_MANIFEST_SHA256,
        "started_at": "2026-08-23T00:00:00Z",
        "trajectory_set": "translation",
        "first_failure_turn_id": None,
        "first_failure_owner": None,
        "failure_code": None,
        "evidence_directory": str(attempt_root.resolve()),
        "local_reproduction": None,
        "focused_test": None,
        "shared_owner_repair": None,
        "independent_audit": None,
        "result": "passed",
        "context_path": str(context.resolve()),
        "allocated_ledger_revision": 1,
        "allocated_ledger_hash": None,
        "context_sha256": None,
    }
    ledger_payload = {
        "schema_version": "guide-smoke-attempt-ledger-v1",
        "ledger_path": str(ledger.resolve()),
        "revision": 0,
        "attempts": [],
        "authorizations": [],
        "circuit_state": "closed",
        "revision_chain": [],
    }
    attempt_ledger._append_revision(
        ledger_payload,
        operation="initialized",
    )
    ledger_payload["attempts"].append(attempt)
    ledger_payload["revision"] = 1
    allocation = attempt_ledger._append_revision(
        ledger_payload,
        operation="attempt_allocated",
        attempt_id=attempt["attempt_id"],
        authorization_id=attempt["retry_authorization_id"],
    )
    attempt["allocated_ledger_hash"] = allocation["revision_hash"]
    context_payload = {
        "schema_version": "guide-smoke-attempt-context-v1",
        "expected_manifest_sha256": _EXPECTED_MANIFEST_SHA256,
        "context_id": "context_backend_replay",
        "current_phase": "translation",
        "parent_attempt_id": None,
        "phase_attempt_ids": {
            "translation": "translation-attempt-01",
        },
        "phase_authorization_ids": {
            "translation": "auth-translation",
        },
        "output_directory": str(attempt_root.resolve()),
        "readiness_path": str(readiness.resolve()),
        "readiness_sha256": sha256(readiness.read_bytes()).hexdigest(),
        "ledger_path": str(ledger.resolve()),
        "allocated_ledger_revision": 1,
        "allocated_ledger_hash": allocation["revision_hash"],
        "attempt_record_sha256": _attempt_allocation_sha256(
            attempt
        ),
    }
    context.write_bytes(attempt_ledger._canonical_bytes(context_payload))
    attempt["context_sha256"] = sha256(context.read_bytes()).hexdigest()
    attempt["terminal_evidence"] = (
        attempt_ledger._terminal_evidence_manifest(
            output_directory=attempt_root,
            evidence_directory=attempt_root,
        )
    )
    attempt["completed_at"] = "2026-08-23T00:30:00Z"
    ledger_payload["revision"] = 2
    attempt_ledger._append_revision(
        ledger_payload,
        operation="attempt_completed",
        attempt_id=attempt["attempt_id"],
        authorization_id=attempt["retry_authorization_id"],
    )
    ledger.write_bytes(attempt_ledger._canonical_bytes(ledger_payload))
    return context


def test_replay_runs_all_captured_meanings_through_real_http_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture, capture_rows = _fixture_and_capture(tmp_path)
    context = _attempt_context(tmp_path, capture_rows, fixture)
    context_before = context.read_bytes()
    monkeypatch.setenv("GUIDE_LLM_API_KEY", "must-not-call")
    monkeypatch.setenv("GUIDE_COPY_LLM_API_KEY", "must-not-call")

    report = replay_final_real_backend(
        cases_path=fixture,
        attempt_context_path=context,
        phase="backend",
        repo_root=Path.cwd(),
    )

    assert report.passed is True
    assert report.context_replay_mode == "sealed_case_context"
    assert report.stateful_transition_count == 0
    assert report.turn_count == 48
    assert report.completed_turn_count == 48
    assert report.translation_injection_count == 48
    assert report.context_mismatch_count == 0
    assert report.provider_call_count == 0
    assert report.copywriter_call_count == 0
    assert report.non_clarification_turn_count == 47
    assert report.presentation_contract_count == 47
    assert report.clarification_turn_count == 1
    assert report.message_event_count == 0
    assert report.wrong_responsibility_count == 0
    assert report.wrong_binding_count == 0
    assert report.wrong_product_count == 0
    assert report.price_specification_mismatch_count == 0
    assert report.section_order_violation_count == 0
    assert report.raw_ad_leak_count == 0
    assert report.internal_language_count == 0
    assert report.serious_failure_count == 0
    translation = context.parent / "real-translation"
    assert report.translation_results_sha256 == sha256(
        (translation / "results.jsonl").read_bytes()
    ).hexdigest()
    assert report.translation_summary_sha256 == sha256(
        (translation / "summary.json").read_bytes()
    ).hexdigest()
    assert report.translation_checksums_sha256 == sha256(
        (translation / "SHA256SUMS").read_bytes()
    ).hexdigest()
    assert report.fixture_path == FINAL_TRANSLATION_FIXTURE_PATH
    assert report.fixture_sha256 == sha256(fixture.read_bytes()).hexdigest()
    assert all(
        trace.sealed_context_sha256 == trace.observed_context_sha256
        for trace in report.turn_traces
    )
    backend_output = context.parent / "real-backend"
    assert all(
        trace.raw_sse_path
        == (
            f"turns/{trace.trajectory_id}/{trace.turn_id}/stream.sse"
        )
        for trace in report.turn_traces
    )
    assert all(
        sha256(
            (backend_output / trace.raw_sse_path).read_bytes()
        ).hexdigest()
        == trace.raw_sse_sha256
        for trace in report.turn_traces
    )
    assert all(
        tuple(
            name
            for name, _ in backend_replay._parse_sse(
                (backend_output / trace.raw_sse_path).read_bytes()
            )[0]
        )
        == trace.event_names
        for trace in report.turn_traces
    )
    assert all(
        attempt_ledger._backend_sse_event_names(
            backend_output / trace.raw_sse_path
        )
        == trace.event_names
        for trace in report.turn_traces
    )
    assert context.read_bytes() == context_before
    assert (backend_output / "results.jsonl").is_file()
    assert (backend_output / "summary.json").is_file()
    assert (backend_output / "SHA256SUMS").is_file()
    assert os.environ["GUIDE_LLM_API_KEY"] == "must-not-call"
    assert os.environ["GUIDE_COPY_LLM_API_KEY"] == "must-not-call"


def test_replay_image_turn_uses_real_bundle_and_exact_sealed_context(
    tmp_path: Path,
) -> None:
    trajectories = translation_gate.load_final_translation_trajectories(
        BASE_FIXTURE
    )
    turn = next(
        turn
        for trajectory in trajectories
        for turn in trajectory.turns
        if turn.case.context.image_count == 1
    )
    meaning = TurnMeaning.model_validate(
        {
            "operation_hint": "image_identity",
            "topic_hint": turn.case.context.active_topic,
            "continuity_hint": "new_task",
            "subject_scope_hint": "self",
            "pending_response_hint": "unknown",
            "reference_mentions": [
                {
                    "raw_text": "第一张图",
                    "object_family_hint": "image",
                    "ordinal_hint": 1,
                    "plurality_hint": "single",
                }
            ],
            "safety_language": "ordinary",
        },
        strict=True,
    )
    capture = backend_replay.CapturedMeaning(
        trajectory_id=turn.trajectory_id,
        turn_id=turn.turn_id,
        case_id=turn.case.case_id,
        meaning=meaning,
        expected_responsibility="image_identity",
    )

    traces, raw_streams, network_attempts = (
        backend_replay._run_http_replay(
            repo_root=Path.cwd(),
            state_root=tmp_path / "image-state",
            trajectories=(SimpleNamespace(turns=(turn,)),),
            captures=(capture,),
        )
    )

    assert network_attempts == 0
    assert len(traces) == 1
    assert raw_streams == (
        (traces[0].raw_sse_path, raw_streams[0][1]),
    )
    assert sha256(raw_streams[0][1]).hexdigest() == (
        traces[0].raw_sse_sha256
    )
    assert traces[0].translation_injection_count == 1
    assert traces[0].image_product_ids == turn.image_product_ids
    assert len(traces[0].image_asset_sha256s) == len(
        turn.image_product_ids
    )
    assert all(
        len(digest) == 64
        for digest in traces[0].image_asset_sha256s
    )
    assert (
        traces[0].sealed_context_sha256
        == traces[0].observed_context_sha256
    )
    assert "image_observation" in traces[0].event_names


def test_replay_rejects_anything_other_than_all_48_captured_meanings(
    tmp_path: Path,
) -> None:
    fixture, capture_rows = _fixture_and_capture(
        tmp_path,
        capture_count=47,
    )
    context = _attempt_context(tmp_path, capture_rows, fixture)

    with pytest.raises(
        BackendReplayError,
        match="exactly 48 captured meanings",
    ):
        replay_final_real_backend(
            cases_path=fixture,
            attempt_context_path=context,
            phase="backend",
            repo_root=Path.cwd(),
        )

    assert not (context.parent / "real-backend").exists()


def test_replay_rejects_missing_recommendation_mode_proof(
    tmp_path: Path,
) -> None:
    fixture, capture_rows = _fixture_and_capture(tmp_path)
    capture_rows[0].pop("recommendation_mode_passed")
    context = _attempt_context(tmp_path, capture_rows, fixture)

    with pytest.raises(
        BackendReplayError,
        match="row schema",
    ):
        replay_final_real_backend(
            cases_path=fixture,
            attempt_context_path=context,
            phase="backend",
            repo_root=Path.cwd(),
        )


def test_replay_rejects_fabricated_translation_context_hash(
    tmp_path: Path,
) -> None:
    fixture, capture_rows = _fixture_and_capture(tmp_path)
    capture_rows[0]["context_sha256"] = "0" * 64
    context = _attempt_context(tmp_path, capture_rows, fixture)

    with pytest.raises(
        BackendReplayError,
        match="translation row provenance",
    ):
        replay_final_real_backend(
            cases_path=fixture,
            attempt_context_path=context,
            phase="backend",
            repo_root=Path.cwd(),
        )


def test_replay_rejects_translation_terminal_evidence_drift(
    tmp_path: Path,
) -> None:
    fixture, capture_rows = _fixture_and_capture(tmp_path)
    context = _attempt_context(tmp_path, capture_rows, fixture)
    (context.parent / "focused.json").unlink()

    with pytest.raises(
        BackendReplayError,
        match="attempt context is invalid: terminal evidence changed",
    ):
        replay_final_real_backend(
            cases_path=fixture,
            attempt_context_path=context,
            phase="backend",
            repo_root=Path.cwd(),
        )


def test_replay_rejects_tampered_attempt_context(
    tmp_path: Path,
) -> None:
    fixture, capture_rows = _fixture_and_capture(tmp_path)
    context = _attempt_context(tmp_path, capture_rows, fixture)
    payload = json.loads(context.read_text(encoding="utf-8"))
    payload["output_directory"] = str(tmp_path / "redirected")
    context.write_bytes(_canonical_bytes(payload))

    with pytest.raises(
        BackendReplayError,
        match="attempt context",
    ):
        replay_final_real_backend(
            cases_path=fixture,
            attempt_context_path=context,
            phase="backend",
            repo_root=Path.cwd(),
        )


def test_replay_verifies_release_readiness_before_loading_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture, capture_rows = _fixture_and_capture(tmp_path)
    context = _attempt_context(tmp_path, capture_rows, fixture)
    calls: list[str] = []

    monkeypatch.setattr(
        backend_replay,
        "verify_task11_readiness",
        lambda **_: calls.append("readiness") or {},
        raising=False,
    )

    def stop_before_capture(**_: object) -> tuple[object, ...]:
        calls.append("capture")
        raise RuntimeError("stop after readiness verification")

    monkeypatch.setattr(
        backend_replay,
        "_load_captured_meanings",
        stop_before_capture,
    )

    with pytest.raises(
        RuntimeError,
        match="stop after readiness verification",
    ):
        replay_final_real_backend(
            cases_path=fixture,
            attempt_context_path=context,
            phase="backend",
            repo_root=Path.cwd(),
        )

    assert calls == ["readiness", "capture"]


def test_replay_rejects_noncanonical_fixture_before_loading_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture, capture_rows = _fixture_and_capture(tmp_path)
    context = _attempt_context(tmp_path, capture_rows, fixture)
    alternate = tmp_path / "alternate-12x4.jsonl"
    alternate.write_bytes(fixture.read_bytes())
    monkeypatch.setattr(
        backend_replay,
        "_load_captured_meanings",
        lambda **_: pytest.fail("capture must not be loaded"),
    )

    with pytest.raises(
        BackendReplayError,
        match="canonical v5 fixture",
    ):
        replay_final_real_backend(
            cases_path=alternate,
            attempt_context_path=context,
            phase="backend",
            repo_root=Path.cwd(),
        )


def test_replay_source_uses_only_real_unified_http_entrypoint() -> None:
    tree = ast.parse(SOURCE_PATH.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
    }
    source = SOURCE_PATH.read_text(encoding="utf-8")

    assert "app.guide_runtime.app" in imported_modules
    assert "app.guide_runtime.composition" in imported_modules
    assert "/api/v1/chat/stream" in source
    assert "tools.guide_gates.run_task11_production_path_matrix" not in (
        imported_modules
    )
    assert "app.guide.intent.executable_intent_compiler" not in (
        imported_modules
    )
    assert "app.guide.intent.unified_turn_router" not in imported_modules
    assert "slice1_backend" not in source
