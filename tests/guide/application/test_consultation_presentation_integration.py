from __future__ import annotations

import json

from app.guide.adapters.llm.contracts import SemanticTokenUsage
from app.guide.adapters.llm.presentation_copywriter_adapter import (
    CopywriterCallResult,
)
from app.guide.application.consultation_chat_flow import (
    ConsultationChatFlow,
)
from app.guide.application.conversation_state_reducer import (
    reduce_conversation_state,
)
from app.guide.application.execution_contracts import (
    materialize_execution_envelope,
)
from app.guide.intent.executable_intent_compiler import compile_turn_meaning
from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.intent.task_planning import plan_task
from app.guide.intent.unified_turn_router import UnifiedRouteDecision
from app.guide.presentation.copywriter_contracts import (
    PresentationPacket,
)
from app.guide.presentation.copywriter_fallback import fallback_copy
from app.guide.presentation.presentation_compiler import (
    PresentationCompiler,
)
from app.guide.understanding.context_resolver import (
    resolve_semantic_context,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning
from tests.guide.application.test_consultation_chat_flow import (
    _execute,
    _turn,
)


class RecordingCopywriter:
    def __init__(self) -> None:
        self.calls: list[PresentationPacket] = []

    def write(
        self,
        packet: PresentationPacket,
    ) -> CopywriterCallResult:
        self.calls.append(packet)
        return CopywriterCallResult(
            draft=fallback_copy(packet),
            usage=SemanticTokenUsage(
                prompt_tokens=50,
                completion_tokens=15,
                total_tokens=65,
                cached_tokens=0,
            ),
            provider="recording",
            model="consultation-copy",
            latency_ms=8.0,
        )


def _flow(tmp_path):
    del tmp_path
    copywriter = RecordingCopywriter()
    flow = ConsultationChatFlow(
        presentation_compiler=PresentationCompiler(
            copywriter=copywriter
        ),
    )
    return flow, copywriter


def _decode_frames(frames) -> list[tuple[str, dict]]:
    events = []
    for frame in frames:
        event_line, data_line, _ = frame.split(b"\n", maxsplit=2)
        events.append(
            (
                event_line.removeprefix(b"event: ").decode("ascii"),
                json.loads(
                    data_line.removeprefix(b"data: ").decode("utf-8")
                ),
            )
        )
    return events


def _event(events, name: str):
    return next(data for event, data in events if event == name)


def test_consultation_entry_uses_zero_card_presentation(
    tmp_path,
) -> None:
    flow, copywriter = _flow(tmp_path)
    turn = _turn(
        "我不知道自己是什么肤质",
        version=0,
    )
    meaning = TurnMeaning(
        operation_hint="assessment",
        topic_hint="skincare",
        continuity_hint="new_task",
        subject_scope_hint="self",
        next_observation_gap="location",
        question_meaning="开始肤质问诊",
        safety_language="ordinary",
    )
    understanding = compile_turn_meaning(
        message=turn.message,
        meaning=meaning,
        context=resolve_semantic_context(
            conversation_version=0,
            snapshot=None,
        ),
    )
    result = _execute(
        flow,
        turn,
        meaning=meaning,
        understanding=understanding,
        snapshot=None,
        route_decision=UnifiedRouteDecision(
            processor="consultation",
            responsibility=Responsibility.CONSULTATION,
            presentation_mode="consultation",
            continuity="replace_task",
            focus_source="consultation",
            task_plan=plan_task(
                understanding,
                responsibility=Responsibility.CONSULTATION,
                message=turn.question_summary,
            ),
        ),
    )
    events = _decode_frames(
        materialize_execution_envelope(
            result,
            session_id=turn.session_id,
            conversation_version=1,
        ).frames
    )
    presentation = _event(events, "presentation_contract")
    names = [event for event, _ in events]

    assert presentation["mode"] == "consultation"
    assert presentation["card_display"]["visible_product_ids"] == []
    assert names.index("card_display_contract") < names.index(
        "presentation_contract"
    )
    assert "message" not in names
    assert len(copywriter.calls) == 1


def test_medical_escalation_skips_copywriter_and_keeps_zero_cards(
    tmp_path,
) -> None:
    flow, copywriter = _flow(tmp_path)
    entry_turn = _turn(
        "我不知道自己是什么肤质",
        version=0,
    )
    entry_meaning = TurnMeaning(
        operation_hint="assessment",
        topic_hint="skincare",
        continuity_hint="new_task",
        subject_scope_hint="self",
        next_observation_gap="location",
        question_meaning="开始肤质问诊",
        safety_language="ordinary",
    )
    entry_understanding = compile_turn_meaning(
        message=entry_turn.message,
        meaning=entry_meaning,
        context=resolve_semantic_context(
            conversation_version=0,
            snapshot=None,
        ),
    )
    entry_decision = UnifiedRouteDecision(
        processor="consultation",
        responsibility=Responsibility.CONSULTATION,
        presentation_mode="consultation",
        continuity="replace_task",
        focus_source="consultation",
        task_plan=plan_task(
            entry_understanding,
            responsibility=Responsibility.CONSULTATION,
            message=entry_turn.question_summary,
        ),
    )
    entry_result = _execute(
        flow,
        entry_turn,
        meaning=entry_meaning,
        understanding=entry_understanding,
        snapshot=None,
        route_decision=entry_decision,
    )
    snapshot = reduce_conversation_state(
        current=None,
        turn_identity=entry_turn.identity,
        decision=entry_decision,
        delta=entry_result.state_delta,
    )
    turn = _turn(
        "会，而且明显疼痛",
        version=snapshot.version,
    )
    meaning = TurnMeaning(
        operation_hint="assessment",
        topic_hint="skincare",
        continuity_hint="continue",
        subject_scope_hint="self",
        observation_candidates=(
            {
                "observation_id": "obs_pain",
                "code": "pain",
                "present": True,
                "qualifier": None,
                "raw_text": "明显疼痛",
                "location": None,
                "trigger": None,
                "duration": "current",
                "severity": "severe",
            },
        ),
        question_meaning="问诊中出现明显疼痛",
        safety_language="safety",
    )
    understanding = compile_turn_meaning(
        message=turn.message,
        meaning=meaning,
        context=resolve_semantic_context(
            conversation_version=snapshot.version,
            snapshot=snapshot,
        ),
    )
    result = _execute(
        flow,
        turn,
        meaning=meaning,
        understanding=understanding,
        snapshot=snapshot,
        route_decision=UnifiedRouteDecision(
            processor="safety_escalation",
            responsibility=Responsibility.SAFETY_ESCALATION,
            presentation_mode="consultation",
            continuity="continue",
            focus_source="consultation",
            task_plan=plan_task(
                understanding,
                responsibility=Responsibility.SAFETY_ESCALATION,
                message=turn.question_summary,
            ),
        ),
    )
    events = _decode_frames(
        materialize_execution_envelope(
            result,
            session_id=turn.session_id,
            conversation_version=snapshot.version + 1,
        ).frames
    )
    presentation = _event(events, "presentation_contract")

    assert presentation["mode"] == "consultation"
    assert presentation["copy_source"] == "authoritative"
    assert presentation["telemetry"]["fallback_reason"] is None
    assert presentation["card_display"]["visible_product_ids"] == []
    assert len(copywriter.calls) == 1
