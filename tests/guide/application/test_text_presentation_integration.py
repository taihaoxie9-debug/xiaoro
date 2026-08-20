from __future__ import annotations

from app.guide.adapters.llm.contracts import SemanticTokenUsage
from app.guide.adapters.llm.presentation_copywriter_adapter import (
    CopywriterCallResult,
)
from app.guide.adapters.state import InMemoryConversationState
from app.guide.application.contracts import UserTurn
from app.guide.presentation.copywriter_contracts import (
    PresentationPacket,
)
from app.guide.presentation.copywriter_fallback import fallback_copy
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
    build_review_evidence_reader,
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
        return CopywriterCallResult(
            draft=fallback_copy(packet),
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


def test_recommendation_passes_approved_reviews_to_copywriter(
    real_reader,
    real_product_assets,
) -> None:
    message = "500内保湿面霜"
    copywriter = RecordingCopywriter()
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=InMemoryConversationState(),
        understanding=exact_echo_understanding(),
        review_evidence=build_review_evidence_reader(),
        presentation_copywriter=copywriter,
    )

    list(orchestrator.stream(_turn(message)))
    slot = next(
        item
        for item in copywriter.calls[0].slots
        if item.product_id == 42
    )

    assert any(
        fact.attribution == "consumer_report"
        for fact in slot.approved_soft_facts
    )


def test_named_comparison_passes_approved_reviews_to_copywriter(
    real_reader,
    real_product_assets,
) -> None:
    names = (
        "玉泽皮肤屏障修护保湿霜",
        "理肤泉B5霜40ml修护舒缓泛红保湿面霜",
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
            topic=TopicCode.SKINCARE,
        ),
        review_evidence=build_review_evidence_reader(),
        presentation_copywriter=copywriter,
    )

    list(orchestrator.stream(_turn(message)))
    slot = next(
        item
        for item in copywriter.calls[0].slots
        if item.product_id == 49
    )

    assert any(
        fact.attribution == "consumer_report"
        for fact in slot.approved_soft_facts
    )


def test_general_knowledge_reuses_contract_copy_for_compatibility_message(
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
    assert message == presentation.sections[0].copy_text
    assert "SPF 针对 UVB" in message
    assert copywriter.calls == []


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
    ) == ("summary", "answer", "full_cards")
    assert not any(
        section.kind in {"product", "closing", "pitfalls"}
        for section in presentation.sections
    )
    evidence = _event(events, "product_evidence").data.packet
    message_copy = _event(events, "message").data.content
    answer = presentation.sections[1]
    assert answer.copy_text == message_copy
    assert answer.used_fact_ids == tuple(
        item.evidence.evidence_id for item in evidence.selected
    )
    assert copywriter.calls == []


def test_product_knowledge_preserves_catalog_data_and_answer_receipts(
    real_reader,
    real_product_assets,
) -> None:
    name = "理肤泉新B5多效修护精华"
    message = f"{name}的品牌主打、核心成分和适合肤质是什么？"
    copywriter = RecordingCopywriter()
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=InMemoryConversationState(),
        understanding=_product_understanding(
            message,
            goal=UnderstandingGoal.KNOWLEDGE,
            names=(name,),
            topic=TopicCode.SERUM,
            question_meaning="询问商品主打、核心成分和适合肤质",
        ),
        product_evidence=build_product_evidence_retriever(),
        presentation_copywriter=copywriter,
    )

    events = list(orchestrator.stream(_turn(message)))
    presentation = _event(events, "presentation_contract").data
    product = _event(events, "products").data.cards[0]
    evidence = _event(events, "product_evidence").data.packet
    answer = presentation.sections[1]

    assert product.product_id == 38
    assert {
        fact.field_key
        for fact in product.category_facts
        if fact.state == "known"
    } >= {
        "efficacy",
        "ingredients_present",
        "suitable_skin",
    }
    assert evidence.selected
    assert answer.used_fact_ids == tuple(
        item.evidence.evidence_id for item in evidence.selected
    )
    assert answer.copy_text == _event(events, "message").data.content
    assert copywriter.calls == []
    assert not any(
        section.kind == "product"
        for section in presentation.sections
    )


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
