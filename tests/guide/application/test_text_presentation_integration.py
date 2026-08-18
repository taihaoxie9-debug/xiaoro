from __future__ import annotations

from app.guide.adapters.llm.contracts import SemanticTokenUsage
from app.guide.adapters.llm.presentation_copywriter_adapter import (
    CopywriterCallResult,
)
from app.guide.adapters.state import InMemoryConversationState
from app.guide.application.contracts import UserTurn
from app.guide.presentation.copywriter_contracts import (
    CopywriterDraft,
    PresentationPacket,
    ProductCopy,
)
from app.guide.retrieval.general_knowledge_retrieval import (
    GeneralKnowledgeRetriever,
)
from app.guide.understanding.contracts import (
    CategoryDraft,
    ProductMentionDraft,
    SourceSpan,
    StructuredUnderstanding,
    TopicCode,
    UnderstandingGoal,
)
from app.guide_runtime.composition import (
    build_general_knowledge_assets,
    build_product_evidence_retriever,
    compose_text_recommendation_orchestrator,
)
from tests.guide.semantic_test_port import exact_echo_understanding


class RecordingCopywriter:
    def __init__(self) -> None:
        self.calls: list[PresentationPacket] = []

    def write(
        self,
        packet: PresentationPacket,
    ) -> CopywriterCallResult:
        self.calls.append(packet)
        has_closing = any(
            section.kind == "closing"
            for section in packet.section_order
        )
        return CopywriterCallResult(
            draft=CopywriterDraft(
                mode=packet.mode,
                summary_copy=(
                    "我先按当前条件整理可继续看的方向，"
                    "证据不足处不会强行拍板。"
                ),
                product_copy=tuple(
                    ProductCopy(
                        slot_id=slot.slot_id,
                        positioning="这款走的是更轻松日常的使用路线。",
                        advisor_reason="具体取舍请结合下方商品资料。",
                        used_soft_fact_ids=(),
                    )
                    for slot in packet.slots
                ),
                closing_copy=(
                    "最后按自己的使用偏好和注意项选择。"
                    if has_closing
                    else None
                ),
            ),
            usage=SemanticTokenUsage(
                prompt_tokens=80,
                completion_tokens=30,
                total_tokens=110,
                cached_tokens=0,
            ),
            provider="recording",
            model="copy-test",
            latency_ms=12.0,
        )


class StaticUnderstanding:
    def __init__(self, result: StructuredUnderstanding) -> None:
        self.result = result

    def understand(self, message, *, context, semantic_required=True):
        del message, context, semantic_required
        return self.result.model_copy(deep=True)


def _turn(message: str) -> UserTurn:
    return UserTurn(
        session_id="presentation-session",
        message=message,
        image_bundle_id=None,
        conversation_version=0,
    )


def _product_understanding(
    message: str,
    *,
    goal: UnderstandingGoal,
    names: tuple[str, ...],
    topic: TopicCode,
    question_meaning: str | None = None,
) -> StaticUnderstanding:
    mentions = [
        ProductMentionDraft(
            text=name,
            source_span=SourceSpan(
                start=message.index(name),
                end=message.index(name) + len(name),
            ),
        )
        for name in names
    ]
    return StaticUnderstanding(
        StructuredUnderstanding(
            goal=goal,
            topic=topic,
            observations=[],
            exact_constraints=[CategoryDraft(value=topic)],
            semantic_proposals=[],
            signal_trace=[],
            product_mentions=mentions,
            image_references=[],
            uncertainties=[],
            confidence=0.99,
            question_meaning=question_meaning,
        )
    )


def _event(events, name: str):
    return next(item for item in events if item.event == name)


def test_recommendation_emits_presentation_before_message(
    real_reader,
    real_product_assets,
) -> None:
    copywriter = RecordingCopywriter()
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=InMemoryConversationState(),
        understanding=exact_echo_understanding(),
        presentation_copywriter=copywriter,
    )

    events = list(
        orchestrator.stream(_turn("500 内适合油敏肌的防晒"))
    )
    names = [item.event for item in events]

    assert names.index("products") < names.index(
        "presentation_contract"
    )
    assert names.index("presentation_contract") < names.index(
        "message"
    )
    presentation = _event(events, "presentation_contract").data
    decision = _event(events, "decision_process").data
    display = _event(events, "card_display_contract").data
    assert presentation.mode == "recommendation"
    assert presentation.copy_source == "model"
    assert presentation.card_display == display
    assert tuple(
        section.product_id
        for section in presentation.sections
        if section.kind == "product"
    ) == tuple(decision.ordered_product_ids)
    assert len(copywriter.calls) == 1


def test_named_comparison_uses_comparison_presentation(
    real_reader,
    real_product_assets,
) -> None:
    names = (
        "安热沙智感倍护防晒乳液GB",
        "理肤泉特护清盈防晒乳 SPF50 PA++++",
    )
    message = f"对比{names[0]}和{names[1]}"
    copywriter = RecordingCopywriter()
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=InMemoryConversationState(),
        understanding=_product_understanding(
            message,
            goal=UnderstandingGoal.COMPARISON,
            names=names,
            topic=TopicCode.SUNSCREEN,
        ),
        presentation_copywriter=copywriter,
    )

    events = list(orchestrator.stream(_turn(message)))
    presentation = _event(events, "presentation_contract").data

    assert presentation.mode == "comparison"
    assert presentation.card_display.visible_product_ids == (51, 53)
    assert len(copywriter.calls) == 1


def test_general_knowledge_keeps_direct_answer_and_adds_presentation(
    real_reader,
    real_product_assets,
) -> None:
    understanding = StaticUnderstanding(
        StructuredUnderstanding(
            goal=UnderstandingGoal.KNOWLEDGE,
            topic=TopicCode.SUNSCREEN,
            observations=[],
            exact_constraints=[
                CategoryDraft(value=TopicCode.SUNSCREEN)
            ],
            semantic_proposals=[],
            signal_trace=[],
            image_references=[],
            uncertainties=[],
            confidence=0.99,
            question_meaning="询问SPF和PA防晒指标的含义",
        )
    )
    copywriter = RecordingCopywriter()
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=InMemoryConversationState(),
        understanding=understanding,
        general_knowledge=GeneralKnowledgeRetriever(
            build_general_knowledge_assets().blocks
        ),
        presentation_copywriter=copywriter,
    )

    events = list(
        orchestrator.stream(_turn("SPF和PA分别是什么意思"))
    )
    names = [item.event for item in events]
    presentation = _event(events, "presentation_contract").data
    message = _event(events, "message").data.content

    assert names.index("general_knowledge") < names.index(
        "presentation_contract"
    )
    assert names.index("presentation_contract") < names.index(
        "message"
    )
    assert presentation.mode == "general_knowledge"
    assert presentation.card_display.visible_product_ids == ()
    assert tuple(
        section.kind for section in presentation.sections
    ) == ("general_knowledge",)
    assert "通用教育资料" in message
    assert len(copywriter.calls) == 1


def test_product_knowledge_emits_only_bound_product_card(
    real_reader,
    real_product_assets,
) -> None:
    name = (
        "薇诺娜（WINONA）特护面膜舒敏保湿丝滑面贴膜"
        "6片舒缓修护补水保湿"
    )
    message = f"{name}那个布会不会老往下掉？"
    copywriter = RecordingCopywriter()
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=InMemoryConversationState(),
        understanding=_product_understanding(
            message,
            goal=UnderstandingGoal.KNOWLEDGE,
            names=(name,),
            topic=TopicCode.SKINCARE,
            question_meaning="询问面膜是否服帖、是否容易滑落",
        ),
        product_evidence=build_product_evidence_retriever(),
        presentation_copywriter=copywriter,
    )

    events = list(orchestrator.stream(_turn(message)))
    presentation = _event(events, "presentation_contract").data
    products = _event(events, "products").data.cards

    assert presentation.mode == "product_knowledge"
    assert [card.product_id for card in products] == [78]
    assert presentation.card_display.visible_product_ids == (78,)
    assert tuple(
        section.kind for section in presentation.sections
    ) == ("product", "full_cards")
    product_section = presentation.sections[0]
    assert product_section.advisor_reason is None
    assert not any(
        section.kind in {"closing", "pitfalls"}
        for section in presentation.sections
    )
    assert len(copywriter.calls) == 1


def test_copywriter_toggle_cannot_change_decision_or_state(
    real_reader,
    real_product_assets,
) -> None:
    enabled_state = InMemoryConversationState()
    disabled_state = InMemoryConversationState()
    copywriter = RecordingCopywriter()
    enabled = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=enabled_state,
        understanding=exact_echo_understanding(),
        presentation_copywriter=copywriter,
    )
    disabled = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=disabled_state,
        understanding=exact_echo_understanding(),
        presentation_copywriter=None,
    )
    turn = _turn("500 内适合油敏肌的防晒")

    enabled_events = list(enabled.stream(turn))
    disabled_events = list(disabled.stream(turn))

    for event_name in (
        "decision_process",
        "answer_contract",
        "card_display_contract",
        "products",
        "end",
    ):
        assert _event(enabled_events, event_name).model_dump(
            mode="json"
        ) == _event(disabled_events, event_name).model_dump(
            mode="json"
        )
    assert enabled_state.load(turn.session_id) == disabled_state.load(
        turn.session_id
    )
    assert _event(
        disabled_events,
        "presentation_contract",
    ).data.copy_source == "fallback"
    assert len(copywriter.calls) == 1
