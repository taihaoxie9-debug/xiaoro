from __future__ import annotations

import ast
from pathlib import Path

from app.guide.adapters.state import InMemoryConversationState
from app.guide.application.chat_api_adapter import (
    PublicEventCommitConversationState,
    commit_http_event_delivery,
    iter_guide_public_events,
)
from app.guide.application.contracts import UserTurn
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


def _persist_clarification(
    *,
    session_id: str,
    question: str,
    code: ClarificationCode,
) -> tuple[list[tuple[str, dict[str, object]]], ClarificationCode]:
    state = InMemoryConversationState()

    class ClarificationOrchestrator:
        _conversation_state = PublicEventCommitConversationState(state)

        def stream(self, turn):
            yield StartEvent(data=StartData(session_id=turn.session_id))
            yield IntentEvent(data=IntentData(mode="clarify"))
            yield ClarifyEvent(
                data=ClarifyData(
                    question=question,
                    clarification_code=code,
                )
            )
            yield EndEvent(
                data=EndData(
                    conversation_version=turn.conversation_version
                )
            )

    events = list(
        iter_guide_public_events(
            ClarificationOrchestrator(),
            UserTurn(
                session_id=session_id,
                message="原始文本故意不参与 code 选择",
                conversation_version=0,
            ),
        )
    )
    commit_http_event_delivery(events[-1])
    stored = state.load(session_id)
    assert stored is not None
    assert stored.clarification is not None
    return events, stored.clarification.gap


def test_new_clarification_copy_persists_typed_code_without_public_tuple_change(
) -> None:
    events, stored_code = _persist_clarification(
        session_id="typed-new-copy",
        question="这是一条此前从未登记过的新追问文案。",
        code=ClarificationCode.CONCERN,
    )

    assert events[2] == (
        "message",
        {
            "content": "这是一条此前从未登记过的新追问文案。",
            "done": False,
            "clarify": True,
        },
    )
    assert events[-1] == ("end", {"conversation_version": 1})
    assert stored_code is ClarificationCode.CONCERN


def test_same_clarification_copy_persists_each_distinct_typed_code() -> None:
    question = "同一显示文案不能决定澄清类型。"

    _, first_code = _persist_clarification(
        session_id="typed-same-copy-goal",
        question=question,
        code=ClarificationCode.GOAL,
    )
    _, second_code = _persist_clarification(
        session_id="typed-same-copy-budget",
        question=question,
        code=ClarificationCode.BUDGET,
    )

    assert first_code is ClarificationCode.GOAL
    assert second_code is ClarificationCode.BUDGET


def test_public_api_boundary_has_no_parser_or_question_code_map() -> None:
    paths = [
        ROOT / "app/guide/application/chat_api_adapter.py",
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
