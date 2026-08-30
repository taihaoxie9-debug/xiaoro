from __future__ import annotations

import pytest

from app.guide.presentation.sse_events import (
    ClarifyData,
    ClarifyEvent,
    EndData,
    EndEvent,
    IntentData,
    IntentEvent,
    MessageData,
    MessageEvent,
    StageData,
    StageEvent,
    StartData,
    StartEvent,
)
from app.guide.understanding.semantic_contracts import ClarificationCode


def _guard():
    from app.guide.presentation.terminal_contract_guard import (
        GuideTerminalContractGuard,
    )

    return GuideTerminalContractGuard()


def test_terminal_guard_rejects_guide_end_without_presentation() -> None:
    guard = _guard()

    guard.observe(StartEvent(data=StartData(session_id="guard-test")))
    guard.observe(IntentEvent(data=IntentData(mode="recommend")))

    with pytest.raises(RuntimeError, match="missing contract"):
        guard.observe(EndEvent(data=EndData(conversation_version=1)))


def test_terminal_guard_rejects_guide_message_event() -> None:
    guard = _guard()

    with pytest.raises(RuntimeError, match="MessageEvent"):
        guard.observe(MessageEvent(data=MessageData(content="legacy copy")))


def test_terminal_guard_requires_start_as_first_event() -> None:
    guard = _guard()

    with pytest.raises(RuntimeError, match="start with StartEvent"):
        guard.observe(IntentEvent(data=IntentData(mode="recommend")))


def test_clarification_uses_typed_event_without_presentation() -> None:
    guard = _guard()

    guard.observe(StartEvent(data=StartData(session_id="guard-test")))
    guard.observe(IntentEvent(data=IntentData(mode="clarify")))
    guard.observe(
        ClarifyEvent(
            data=ClarifyData(
                question="请明确要比较哪两款。",
                clarification_code=ClarificationCode.REFERENCE,
            )
        )
    )
    guard.observe(EndEvent(data=EndData(conversation_version=1)))
    guard.finish()


def test_terminal_guard_rejects_events_after_clarification_body() -> None:
    guard = _guard()

    guard.observe(StartEvent(data=StartData(session_id="guard-test")))
    guard.observe(IntentEvent(data=IntentData(mode="clarify")))
    guard.observe(
        ClarifyEvent(
            data=ClarifyData(
                question="请明确要比较哪两款。",
                clarification_code=ClarificationCode.REFERENCE,
            )
        )
    )

    with pytest.raises(RuntimeError, match="after terminal body"):
        guard.observe(
            StageEvent(
                data=StageData(
                    stage="state",
                    summary="不应出现在澄清正文之后。",
                )
            )
        )
