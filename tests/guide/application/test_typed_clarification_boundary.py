from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.guide.application.public_event_envelope import (
    materialize_guide_public_events,
)
from app.guide.application.contracts import TurnIdentity, UserTurn
from app.guide.presentation.sse_events import (
    ClarifyData,
    ClarifyEvent,
    EndData,
    EndEvent,
    IntentData,
    IntentEvent,
    StartData,
    StartEvent,
)
from app.guide.understanding.semantic_contracts import ClarificationCode


ROOT = Path(__file__).resolve().parents[3]


def test_fit_clarification_proof_is_all_or_nothing() -> None:
    with pytest.raises(
        ValueError,
        match="fit clarification proof must be complete",
    ):
        ClarifyData(
            question="请补充一个更明确的使用场景。",
            clarification_code=ClarificationCode.GOAL,
            intended_responsibility="recommendation",
        )


def test_fit_clarification_proof_records_typed_selection_gap() -> None:
    data = ClarifyData(
        question="请补充一个更明确的使用场景。",
        clarification_code=ClarificationCode.GOAL,
        intended_responsibility="recommendation",
        intended_recommendation_mode="fit",
        clarification_basis="fit_selection_evidence_gap",
        fit_gap_stage="decision_selection",
        fit_decision_status="INSUFFICIENT_FOR_WINNER",
        fit_candidate_count=2,
        fit_evidence_ref_count=1,
        fit_public_fact_count=0,
    )

    assert data.fit_gap_stage == "decision_selection"
    assert data.fit_decision_status == "INSUFFICIENT_FOR_WINNER"


def test_public_fit_clarification_preserves_typed_selection_gap() -> None:
    class FitClarificationOrchestrator:
        def stream(self, turn):
            yield StartEvent(data=StartData(session_id=turn.session_id))
            yield IntentEvent(data=IntentData(mode="clarify"))
            yield ClarifyEvent(
                data=ClarifyData(
                    question="请补充一个更明确的使用场景。",
                    clarification_code=ClarificationCode.GOAL,
                    intended_responsibility="recommendation",
                    intended_recommendation_mode="fit",
                    clarification_basis="fit_selection_evidence_gap",
                    fit_gap_stage="decision_selection",
                    fit_decision_status="INSUFFICIENT_FOR_WINNER",
                    fit_candidate_count=2,
                    fit_evidence_ref_count=1,
                    fit_public_fact_count=0,
                )
            )
            yield EndEvent(data=EndData(conversation_version=1))

    events = list(
        materialize_guide_public_events(
            FitClarificationOrchestrator().stream(
                UserTurn(
                    identity=TurnIdentity(
                        session_id="fit-proof",
                        request_id="request_fit_proof",
                        turn_id="turn_fit_proof",
                    ),
                    session_id="fit-proof",
                    message="请选一款适合我的",
                    conversation_version=0,
                )
            ),
            session_id="fit-proof",
        )
    )

    assert events[2][1]["fit_gap_stage"] == "decision_selection"
    assert events[2][1]["fit_decision_status"] == (
        "INSUFFICIENT_FOR_WINNER"
    )
    assert events[2][1]["fit_candidate_count"] == 2


def test_public_api_boundary_has_no_parser_or_question_code_map() -> None:
    paths = [
        ROOT / "app/guide/application/public_event_envelope.py",
        *sorted((ROOT / "app/guide_runtime").rglob("*.py")),
    ]
    violations: list[str] = []

    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if (
                    module.startswith("app.guide.understanding.")
                    and module.rsplit(".", 1)[-1].endswith("_parsing")
                ):
                    violations.append(
                        f"{path}:{node.lineno}:parser import {module}"
                    )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in {
                    "should_use_slice1_guide",
                    "_build_clarification_gap_map",
                    "_clarification_gap_from_public_events",
                }:
                    violations.append(
                        f"{path}:{node.lineno}:defines {node.name}"
                    )
            elif isinstance(node, ast.Name):
                if node.id == "_CLARIFICATION_GAP_BY_QUESTION":
                    violations.append(
                        f"{path}:{node.lineno}:uses question-to-code map"
                    )
            elif isinstance(node, ast.Call):
                called = node.func
                if (
                    isinstance(called, ast.Name)
                    and called.id.startswith("parse_")
                ):
                    violations.append(
                        f"{path}:{node.lineno}:calls {called.id}"
                    )

    assert violations == []
