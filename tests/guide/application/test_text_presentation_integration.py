from __future__ import annotations

import json
from pathlib import Path

from app.guide.adapters.llm.contracts import SemanticTokenUsage
from app.guide.adapters.llm.presentation_copywriter_adapter import (
    CopywriterCallResult,
)
from app.guide.adapters.state import InMemoryConversationState
from app.guide.application.consultation_chat_flow import (
    ConsultationChatFlow,
)
from app.guide.application.contracts import TurnIdentity, UserTurn
from app.guide.application.unified_guide_flow import UnifiedGuideFlow
from app.guide.presentation.copywriter_contracts import (
    PresentationPacket,
)
from app.guide.presentation.copywriter_fallback import fallback_copy
from app.guide.presentation.presentation_compiler import (
    PresentationCompiler,
)
from app.guide.retrieval.general_knowledge_retrieval import (
    GeneralKnowledgeRetriever,
)
from app.guide.understanding.contracts import (
    TopicCode,
    UnderstandingGoal,
)
from app.guide.understanding.semantic_contracts import ClarificationCode
from app.guide.understanding.turn_meaning_contracts import TurnMeaning
from app.guide_runtime.composition import (
    build_category_fact_reader,
    build_general_knowledge_assets,
    build_product_evidence_reader,
    build_product_evidence_retriever,
    build_review_evidence_reader,
    build_selection_fact_reader,
    build_selection_parent_concept_reader,
    build_text_understanding,
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


class StaticMeaningPort:
    def __init__(self, result: TurnMeaning) -> None:
        self.result = result

    def propose(self, message, context):
        del message, context
        return self.result.model_copy(deep=True)


def _turn(message: str, *, version: int = 0) -> UserTurn:
    session_id = "presentation-session"
    return UserTurn(
        identity=TurnIdentity(
            session_id=session_id,
            request_id=(
                f"request_identity_{session_id}_{version:04d}"
            ),
            turn_id=f"turn_identity_{session_id}_{version:04d}",
        ),
        session_id=session_id,
        message=message,
        image_bundle_id=None,
        conversation_version=version,
    )


def _product_meaning(
    message: str,
    *,
    goal: UnderstandingGoal,
    names: tuple[str, ...],
    topic: TopicCode,
    question_meaning: str | None = None,
) -> StaticMeaningPort:
    operation = {
        UnderstandingGoal.COMPARISON: "comparison",
        UnderstandingGoal.KNOWLEDGE: "knowledge",
        UnderstandingGoal.SUITABILITY: "suitability",
    }[goal]
    return StaticMeaningPort(
        TurnMeaning(
            operation_hint=operation,
            topic_hint=topic.value,
            continuity_hint="new_task",
            subject_scope_hint="self",
            product_mentions=tuple(
                {"raw_text": name}
                for name in names
            ),
            question_meaning=question_meaning or message,
            safety_language="ordinary",
        )
    )


def _build_flow(
    real_reader,
    *,
    real_product_assets,
    conversation_state: InMemoryConversationState,
    semantic_intent,
    presentation_copywriter=None,
    **processor_dependencies,
) -> UnifiedGuideFlow:
    compiler = PresentationCompiler(
        copywriter=presentation_copywriter,
    )
    processor = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        presentation_copywriter=presentation_copywriter,
        **processor_dependencies,
    )
    return UnifiedGuideFlow(
        understanding=build_text_understanding(
            semantic_intent=semantic_intent,
        ),
        text_processor=processor,
        consultation_processor=ConsultationChatFlow(
            presentation_compiler=compiler,
        ),
        conversation_state=conversation_state,
    )


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


def _event(events, name: str) -> dict:
    return next(data for event, data in events if event == name)


def test_recommendation_emits_presentation_without_message(
    real_reader,
    real_product_assets,
) -> None:
    copywriter = RecordingCopywriter()
    orchestrator = _build_flow(
        real_reader,
        real_product_assets=real_product_assets,
        conversation_state=InMemoryConversationState(),
        semantic_intent=exact_echo_understanding(),
        presentation_copywriter=copywriter,
    )

    events = _decode_frames(
        orchestrator.stream(_turn("500 内适合油敏肌的防晒"))
    )
    names = [event for event, _ in events]

    assert names.index("products") < names.index(
        "presentation_contract"
    )
    assert "message" not in names
    presentation = _event(events, "presentation_contract")
    decision = _event(events, "decision_process")
    display = _event(events, "card_display_contract")
    assert presentation["mode"] == "recommendation"
    assert presentation["recommendation_mode"] == "explore"
    assert presentation["winner"]["status"] == "not_applicable"
    assert presentation["copy_source"] == "model"
    assert presentation["card_display"] == display
    assert tuple(
        section["product_id"]
        for section in presentation["sections"]
        if section["kind"] == "product"
    ) == tuple(decision["ordered_product_ids"])
    assert len(copywriter.calls) == 1


def test_fit_recommendation_emits_one_fact_backed_winner(
    real_reader,
    real_product_assets,
) -> None:
    semantic = StaticMeaningPort(
        TurnMeaning(
            operation_hint="recommendation",
            recommendation_mode="fit",
            recommendation_count=1,
            recommendation_mode_basis={
                "basis": "single_best_request",
                "source_text": "一款最适合",
            },
            topic_hint="serum",
            continuity_hint="new_task",
            subject_scope_hint="self",
            question_meaning="选择一款最适合修护需求的精华",
            safety_language="ordinary",
        )
    )
    orchestrator = _build_flow(
        real_reader,
        real_product_assets=real_product_assets,
        conversation_state=InMemoryConversationState(),
        semantic_intent=semantic,
    )

    events = _decode_frames(
        orchestrator.stream(_turn("给我选一款最适合修护需求的精华"))
    )
    presentation = _event(events, "presentation_contract")
    decision = _event(events, "decision_process")
    closing = next(
        section
        for section in presentation["sections"]
        if section["kind"] == "closing"
    )

    assert presentation["recommendation_mode"] == "fit"
    assert presentation["card_display"]["visible_product_ids"] == [
        decision["ordered_product_ids"][0]
    ]
    assert presentation["winner"]["status"] == "selected"
    assert presentation["winner"]["winner_product_id"] == (
        decision["ordered_product_ids"][0]
    )
    assert presentation["winner"]["fact_ids"]
    assert closing["copy_text"] is None
    assert "message" not in {event for event, _ in events}


def test_fit_recommendation_without_unique_winner_clarifies(
    real_reader,
    real_product_assets,
) -> None:
    semantic = StaticMeaningPort(
        TurnMeaning(
            operation_hint="recommendation",
            recommendation_mode="fit",
            recommendation_count=1,
            recommendation_mode_basis={
                "basis": "personal_suitability",
                "source_text": "最适合油敏肌",
            },
            topic_hint="sunscreen",
            continuity_hint="new_task",
            subject_scope_hint="self",
            question_meaning="选择一款最适合油敏肌的防晒",
            safety_language="ordinary",
        )
    )
    orchestrator = _build_flow(
        real_reader,
        real_product_assets=real_product_assets,
        conversation_state=InMemoryConversationState(),
        semantic_intent=semantic,
    )

    events = _decode_frames(
        orchestrator.stream(_turn("给我选一款最适合油敏肌的防晒"))
    )
    clarify = _event(events, "clarify")

    assert clarify["clarification_code"] == ClarificationCode.GOAL.value
    assert clarify["intended_responsibility"] == "recommendation"
    assert clarify["intended_recommendation_mode"] == "fit"
    assert clarify["clarification_basis"] == "fit_selection_evidence_gap"
    assert "唯一" in clarify["question"]
    assert "message" not in {event for event, _ in events}
    assert "products" not in {event for event, _ in events}
    assert "presentation_contract" not in {
        event for event, _ in events
    }


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
    orchestrator = _build_flow(
        real_reader,
        real_product_assets=real_product_assets,
        conversation_state=InMemoryConversationState(),
        semantic_intent=_product_meaning(
            message,
            goal=UnderstandingGoal.COMPARISON,
            names=names,
            topic=TopicCode.SUNSCREEN,
        ),
        presentation_copywriter=copywriter,
    )

    events = _decode_frames(orchestrator.stream(_turn(message)))
    presentation = _event(events, "presentation_contract")

    assert presentation["mode"] == "comparison"
    assert presentation["card_display"]["visible_product_ids"] == [51, 53]
    assert len(copywriter.calls) == 1


def test_comparison_rows_follow_current_texture_question(
    real_reader,
    real_product_assets,
) -> None:
    names = (
        "安热沙智感倍护防晒乳液GB",
        "理肤泉特护清盈防晒乳 SPF50 PA++++",
    )
    message = f"对比{names[0]}和{names[1]}，哪个质地更清爽"
    semantic = StaticMeaningPort(
        TurnMeaning(
            operation_hint="comparison",
            topic_hint="sunscreen",
            continuity_hint="new_task",
            subject_scope_hint="self",
            product_mentions=tuple(
                {"raw_text": name}
                for name in names
            ),
            preference_candidates=(
                {
                    "field_key": "texture",
                    "concept_id": "texture.refreshing",
                    "raw_text": "清爽",
                    "polarity": "prefer",
                    "strength": "ordinary",
                },
            ),
            question_meaning="比较两款防晒的清爽质地",
            safety_language="ordinary",
        )
    )
    orchestrator = _build_flow(
        real_reader,
        real_product_assets=real_product_assets,
        conversation_state=InMemoryConversationState(),
        semantic_intent=semantic,
        concept_reader=build_selection_parent_concept_reader(),
    )

    events = _decode_frames(orchestrator.stream(_turn(message)))
    presentation = _event(events, "presentation_contract")

    assert [
        row["dimension_id"]
        for row in presentation["comparison_rows"]
    ] == [
        "brand_main",
        "texture.refreshing",
        "profile_match",
    ]


def test_comparison_rows_include_price_only_for_current_budget(
    real_reader,
    real_product_assets,
) -> None:
    names = (
        "安热沙智感倍护防晒乳液GB",
        "理肤泉特护清盈防晒乳 SPF50 PA++++",
    )
    message = f"对比{names[0]}和{names[1]}，预算三百以内"
    semantic = StaticMeaningPort(
        TurnMeaning(
            operation_hint="comparison",
            topic_hint="sunscreen",
            continuity_hint="new_task",
            subject_scope_hint="self",
            product_mentions=tuple(
                {"raw_text": name}
                for name in names
            ),
            budget_candidates=(
                {
                    "raw_text": "三百以内",
                    "relation": "maximum",
                    "minimum": None,
                    "maximum": "300",
                },
            ),
            question_meaning="比较两款防晒是否符合当前预算",
            safety_language="ordinary",
        )
    )
    orchestrator = _build_flow(
        real_reader,
        real_product_assets=real_product_assets,
        conversation_state=InMemoryConversationState(),
        semantic_intent=semantic,
    )

    events = _decode_frames(orchestrator.stream(_turn(message)))
    presentation = _event(events, "presentation_contract")

    assert [
        row["dimension_id"]
        for row in presentation["comparison_rows"]
    ] == [
        "brand_main",
        "reference_price",
        "profile_match",
    ]


def test_comparison_profile_match_requires_public_support(
    real_reader,
    real_product_assets,
) -> None:
    names = ("润浸保湿滋润乳霜", "第二代特护霜")
    message = f"对比{names[0]}和{names[1]}，哪个更适合敏感肌"
    semantic = StaticMeaningPort(
        TurnMeaning(
            operation_hint="comparison",
            topic_hint="skincare",
            continuity_hint="new_task",
            subject_scope_hint="self",
            product_mentions=tuple(
                {"raw_text": name}
                for name in names
            ),
            preference_candidates=(
                {
                    "field_key": "suitable_skin",
                    "concept_id": "suitable_skin.sensitive",
                    "raw_text": "敏感肌",
                    "polarity": "prefer",
                    "strength": "ordinary",
                },
            ),
            question_meaning="比较两款面霜对敏感肌的适配",
            safety_language="ordinary",
        )
    )
    repo_root = Path(__file__).resolve().parents[3]
    category_facts = build_category_fact_reader(
        real_reader,
        repo_root=repo_root,
    )
    selection_facts = build_selection_fact_reader(
        category_facts=category_facts,
        product_evidence=build_product_evidence_reader(repo_root),
    )
    orchestrator = _build_flow(
        real_reader,
        real_product_assets=real_product_assets,
        conversation_state=InMemoryConversationState(),
        semantic_intent=semantic,
        category_fact_port=category_facts,
        selection_facts=selection_facts,
        concept_reader=build_selection_parent_concept_reader(repo_root),
    )

    events = _decode_frames(orchestrator.stream(_turn(message)))
    presentation = _event(events, "presentation_contract")
    profile_row = next(
        row
        for row in presentation["comparison_rows"]
        if row["dimension_id"] == "profile_match"
    )
    cells_by_product = {
        cell["product_id"]: cell
        for cell in profile_row["cells"]
    }

    assert cells_by_product[45]["state"] == "known"
    assert cells_by_product[45]["fact_ids"]
    assert "敏感肌" in cells_by_product[45]["value"]
    assert cells_by_product[50]["state"] == "unknown"
    assert cells_by_product[50]["fact_ids"] == []
    assert "reference_price" not in {
        row["dimension_id"]
        for row in presentation["comparison_rows"]
    }


def test_recommendation_passes_approved_reviews_to_copywriter(
    real_reader,
    real_product_assets,
) -> None:
    message = "500内保湿面霜"
    copywriter = RecordingCopywriter()
    orchestrator = _build_flow(
        real_reader,
        real_product_assets=real_product_assets,
        conversation_state=InMemoryConversationState(),
        semantic_intent=exact_echo_understanding(),
        review_evidence=build_review_evidence_reader(),
        presentation_copywriter=copywriter,
    )

    tuple(orchestrator.stream(_turn(message)))
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
    orchestrator = _build_flow(
        real_reader,
        real_product_assets=real_product_assets,
        conversation_state=InMemoryConversationState(),
        semantic_intent=_product_meaning(
            message,
            goal=UnderstandingGoal.COMPARISON,
            names=names,
            topic=TopicCode.SKINCARE,
        ),
        review_evidence=build_review_evidence_reader(),
        presentation_copywriter=copywriter,
    )

    tuple(orchestrator.stream(_turn(message)))
    slot = next(
        item
        for item in copywriter.calls[0].slots
        if item.product_id == 49
    )

    assert any(
        fact.attribution == "consumer_report"
        for fact in slot.approved_soft_facts
    )


def test_general_knowledge_uses_contract_as_only_public_copy(
    real_reader,
    real_product_assets,
) -> None:
    semantic = StaticMeaningPort(
        TurnMeaning(
            operation_hint="knowledge",
            topic_hint="sunscreen",
            continuity_hint="new_task",
            subject_scope_hint="self",
            question_meaning="询问SPF和PA防晒指标的含义",
            safety_language="ordinary",
        )
    )
    copywriter = RecordingCopywriter()
    orchestrator = _build_flow(
        real_reader,
        real_product_assets=real_product_assets,
        conversation_state=InMemoryConversationState(),
        semantic_intent=semantic,
        general_knowledge=GeneralKnowledgeRetriever(
            build_general_knowledge_assets().blocks
        ),
        presentation_copywriter=copywriter,
    )

    events = _decode_frames(
        orchestrator.stream(_turn("SPF和PA分别是什么意思"))
    )
    names = [event for event, _ in events]
    presentation = _event(events, "presentation_contract")
    answer = presentation["sections"][0]["copy_text"]

    assert names.index("general_knowledge") < names.index(
        "presentation_contract"
    )
    assert "message" not in names
    assert presentation["mode"] == "general_knowledge"
    assert presentation["card_display"]["visible_product_ids"] == []
    assert tuple(
        section["kind"] for section in presentation["sections"]
    ) == ("general_knowledge",)
    assert "SPF 针对 UVB" in answer
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
    orchestrator = _build_flow(
        real_reader,
        real_product_assets=real_product_assets,
        conversation_state=InMemoryConversationState(),
        semantic_intent=_product_meaning(
            message,
            goal=UnderstandingGoal.KNOWLEDGE,
            names=(name,),
            topic=TopicCode.SKINCARE,
            question_meaning="询问面膜是否服帖、是否容易滑落",
        ),
        product_evidence=build_product_evidence_retriever(),
        presentation_copywriter=copywriter,
    )

    events = _decode_frames(orchestrator.stream(_turn(message)))
    presentation = _event(events, "presentation_contract")
    products = _event(events, "products")["cards"]

    assert presentation["mode"] == "product_knowledge"
    assert [card["product_id"] for card in products] == [78]
    assert presentation["card_display"]["visible_product_ids"] == [78]
    assert tuple(
        section["kind"] for section in presentation["sections"]
    ) == ("summary", "answer", "full_cards")
    assert not any(
        section["kind"] in {"product", "closing", "pitfalls"}
        for section in presentation["sections"]
    )
    evidence = _event(events, "product_evidence")["packet"]
    answer = presentation["sections"][1]
    assert "message" not in {event for event, _ in events}
    evidence_fact_ids = {
        f"evidence:{item['evidence']['evidence_id']}"
        for item in evidence["selected"]
    }
    assert evidence_fact_ids <= set(answer["used_fact_ids"])
    assert "消费者自评" in answer["copy_text"]
    assert "不易滑落" in answer["copy_text"]
    assert copywriter.calls == []


def test_product_knowledge_preserves_catalog_data_and_answer_receipts(
    real_reader,
    real_product_assets,
) -> None:
    name = "理肤泉新B5多效修护精华"
    message = f"{name}的品牌主打、核心成分和适合肤质是什么？"
    copywriter = RecordingCopywriter()
    orchestrator = _build_flow(
        real_reader,
        real_product_assets=real_product_assets,
        conversation_state=InMemoryConversationState(),
        semantic_intent=_product_meaning(
            message,
            goal=UnderstandingGoal.KNOWLEDGE,
            names=(name,),
            topic=TopicCode.SERUM,
            question_meaning="询问商品主打、核心成分和适合肤质",
        ),
        product_evidence=build_product_evidence_retriever(),
        presentation_copywriter=copywriter,
    )

    events = _decode_frames(orchestrator.stream(_turn(message)))
    presentation = _event(events, "presentation_contract")
    product = _event(events, "products")["cards"][0]
    evidence = _event(events, "product_evidence")["packet"]
    answer = presentation["sections"][1]

    assert product["product_id"] == 38
    assert {
        fact["field_key"]
        for fact in product["category_facts"]
        if fact["state"] == "known"
    } >= {
        "efficacy",
        "ingredients_present",
        "suitable_skin",
    }
    assert evidence["selected"]
    expected_used_fact_ids = {
        "evidence:"
        f"{evidence['selected'][0]['evidence']['evidence_id']}",
        "category:38:efficacy",
        "category:38:ingredients_present",
    }
    assert set(answer["used_fact_ids"]) == expected_used_fact_ids
    assert "category:38:suitable_skin" not in answer["used_fact_ids"]
    assert "品牌主打" in answer["copy_text"]
    assert "功效方向" in answer["copy_text"]
    assert "核心成分" in answer["copy_text"]
    assert "适合肤质" not in answer["copy_text"]
    assert "message" not in {event for event, _ in events}
    assert copywriter.calls == []
    assert not any(
        section["kind"] == "product"
        for section in presentation["sections"]
    )


def test_product_knowledge_uses_catalog_facts_when_evidence_is_empty(
    real_reader,
    real_product_assets,
) -> None:
    name = "玉泽皮肤屏障修护精华乳50ml"
    message = (
        f"{name}的质地、适合肤质和修护方向是什么？"
    )
    orchestrator = _build_flow(
        real_reader,
        real_product_assets=real_product_assets,
        conversation_state=InMemoryConversationState(),
        semantic_intent=_product_meaning(
            message,
            goal=UnderstandingGoal.KNOWLEDGE,
            names=(name,),
            topic=TopicCode.SERUM,
            question_meaning="询问商品质地、适合肤质和修护方向",
        ),
        product_evidence=build_product_evidence_retriever(),
    )

    events = _decode_frames(orchestrator.stream(_turn(message)))
    presentation = _event(events, "presentation_contract")
    answer = presentation["sections"][1]["copy_text"]
    evidence = _event(events, "product_evidence")["packet"]

    assert not evidence["selected"]
    assert "message" not in {event for event, _ in events}
    assert "功效方向" in answer
    assert "适合肤质" in answer
    assert "修护" in answer
    assert "没有与这个问题直接相关" not in answer


def test_copywriter_toggle_cannot_change_decision_or_state(
    real_reader,
    real_product_assets,
) -> None:
    enabled_state = InMemoryConversationState()
    disabled_state = InMemoryConversationState()
    copywriter = RecordingCopywriter()
    enabled = _build_flow(
        real_reader,
        real_product_assets=real_product_assets,
        conversation_state=enabled_state,
        semantic_intent=exact_echo_understanding(),
        presentation_copywriter=copywriter,
    )
    disabled = _build_flow(
        real_reader,
        real_product_assets=real_product_assets,
        conversation_state=disabled_state,
        semantic_intent=exact_echo_understanding(),
        presentation_copywriter=None,
    )
    turn = _turn("500 内适合油敏肌的防晒")

    enabled_events = _decode_frames(enabled.stream(turn))
    disabled_events = _decode_frames(disabled.stream(turn))

    for event_name in (
        "decision_process",
        "answer_contract",
        "card_display_contract",
        "products",
        "end",
    ):
        assert _event(enabled_events, event_name) == _event(
            disabled_events,
            event_name,
        )
    assert enabled_state.load(turn.session_id) == disabled_state.load(
        turn.session_id
    )
    assert (
        _event(
            disabled_events,
            "presentation_contract",
        )["copy_source"]
        == "fallback"
    )
    assert len(copywriter.calls) == 1
