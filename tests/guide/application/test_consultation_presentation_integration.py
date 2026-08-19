from __future__ import annotations

from datetime import UTC, datetime

from app.guide.adapters.llm.contracts import SemanticTokenUsage
from app.guide.adapters.llm.presentation_copywriter_adapter import (
    CopywriterCallResult,
)
from app.guide.adapters.state import (
    InMemoryConversationState,
    InMemorySessionLocks,
)
from app.guide.adapters.state.sqlite_profile_state import (
    SqliteProfileState,
)
from app.guide.application.consultation_chat_flow import (
    ConsultationChatFlow,
)
from app.guide.application.consultation_coordinator import (
    ConsultationApplicationCoordinator,
)
from app.guide.presentation.copywriter_contracts import (
    CopywriterDraft,
    PresentationPacket,
)
from app.guide.presentation.presentation_compiler import (
    PresentationCompiler,
)
from tests.guide.application.test_consultation_chat_flow import (
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
            draft=CopywriterDraft(
                mode=packet.mode,
                summary_copy="我先按当前观察继续确认，不提前下诊断。",
                product_copy=(),
                closing_copy=None,
            ),
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
    conversation_state = InMemoryConversationState()
    state_root = tmp_path / "state"
    profile_state = SqliteProfileState(
        state_root / "profiles.sqlite3",
        trusted_state_root=state_root,
    )
    coordinator = ConsultationApplicationCoordinator(
        conversation_state=conversation_state,
        profile_state=profile_state,
    )
    copywriter = RecordingCopywriter()
    flow = ConsultationChatFlow(
        coordinator=coordinator,
        conversation_state=conversation_state,
        session_locks=InMemorySessionLocks(),
        presentation_compiler=PresentationCompiler(
            copywriter=copywriter
        ),
        clock=lambda: datetime(2026, 8, 16, 10, 0, tzinfo=UTC),
    )
    return flow, copywriter


def _event(events, name: str):
    return next(item for item in events if item.event == name)


def test_consultation_entry_uses_zero_card_presentation(
    tmp_path,
) -> None:
    flow, copywriter = _flow(tmp_path)

    events = list(
        flow.stream(
            _turn(
                "我不知道自己是什么肤质",
                version=0,
            )
        )
    )
    presentation = _event(events, "presentation_contract").data
    names = [item.event for item in events]

    assert presentation.mode == "consultation"
    assert presentation.card_display.visible_product_ids == ()
    assert names.index("card_display_contract") < names.index(
        "presentation_contract"
    )
    assert names.index("presentation_contract") < names.index(
        "message"
    )
    assert len(copywriter.calls) == 1


def test_medical_escalation_skips_copywriter_and_keeps_zero_cards(
    tmp_path,
) -> None:
    flow, copywriter = _flow(tmp_path)
    entered = list(
        flow.stream(
            _turn(
                "我不知道自己是什么肤质",
                version=0,
            )
        )
    )
    version = entered[-1].data.conversation_version

    events = list(
        flow.stream(
            _turn(
                "会，而且明显疼痛",
                version=version,
            )
        )
    )
    presentation = _event(events, "presentation_contract").data

    assert presentation.mode == "consultation"
    assert presentation.copy_source == "fallback"
    assert presentation.telemetry.fallback_reason == (
        "medical_escalation"
    )
    assert presentation.card_display.visible_product_ids == ()
    assert len(copywriter.calls) == 1
