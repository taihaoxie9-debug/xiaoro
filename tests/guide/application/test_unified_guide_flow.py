from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from app.guide.adapters.state import InMemoryConversationState
from app.guide.application.contracts import UserTurn
from app.guide.application.chat_api_adapter import (
    commit_http_event_delivery,
    iter_guide_public_events,
)
from app.guide.application.unified_guide_flow import UnifiedGuideFlow
from app.guide.feedback.contracts import (
    ConversationSnapshot,
    DisplayedCandidateRef,
    PendingBudgetRange,
    PendingRecommendationContext,
    PendingTurn,
    RecommendationQueryContext,
)
from app.guide.feedback.focus_state import FocusState
from app.guide.intent.executable_intent_compiler import (
    compile_turn_meaning,
)
from app.guide.retrieval.product_name_resolver import (
    ProductMentionResolution,
)
from app.guide.presentation.sse_events import (
    EndData,
    EndEvent,
    IntentData,
    IntentEvent,
    MessageData,
    MessageEvent,
    StartData,
    StartEvent,
)
from app.guide.understanding.contracts import (
    ProductMentionDraft,
    ReferenceDraft,
    SourceSpan,
    StructuredUnderstanding,
    TopicCode,
    UnderstandingGoal,
)
from app.guide.understanding.context_resolver import (
    resolve_semantic_context,
)
from app.guide.understanding.semantic_contracts import (
    ClarificationCode,
    SemanticContext,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning
from app.guide.understanding.text_understanding import understand_text
from app.guide_runtime.composition import (
    build_consultation_vertical_runtime,
    compose_text_recommendation_orchestrator,
)


def _meaning(
    operation: str,
    *,
    continuity: str = "new_task",
    next_gap: str | None = None,
):
    return TurnMeaning.model_validate(
        {
            "operation_hint": operation,
            "topic_hint": "sunscreen",
            "continuity_hint": continuity,
            "subject_scope_hint": "self",
            "reference_mentions": [],
            "product_mentions": [],
            "budget_candidates": [],
            "observation_candidates": [],
            "preference_candidates": [],
            "relative_candidates": [],
            "consultation_hypothesis": None,
            "next_observation_gap": next_gap,
            "question_meaning": "当前问题",
            "safety_language": "ordinary",
        },
        strict=True,
    )


def _understanding(goal: UnderstandingGoal):
    return StructuredUnderstanding(
        goal=goal,
        topic=TopicCode.SUNSCREEN,
        observations=[],
        exact_constraints=[],
        preference_drafts=[],
        relative_drafts=[],
        semantic_proposals=[],
        signal_trace=[],
        references=[],
        product_mentions=[],
        image_references=[],
        uncertainties=[],
        confidence=1.0,
        question_meaning="当前问题",
    )


class RecordingTranslator:
    def __init__(self, meaning, understanding) -> None:
        self.meaning = meaning
        self.understanding = understanding
        self.calls = []

    def translate(self, message: str, *, context: SemanticContext):
        self.calls.append((message, context))
        return self.meaning, self.understanding


class RecordingTextProcessor:
    def __init__(self) -> None:
        self.preunderstood_calls = []
        self.raw_calls = []

    def resolve_product_bindings(self, **kwargs):
        self.binding_request = kwargs
        return ()

    def stream_understanding(
        self,
        turn,
        *,
        understanding,
        route_decision,
        product_bindings,
    ):
        self.preunderstood_calls.append(
            (
                turn,
                understanding,
                route_decision,
                product_bindings,
            )
        )
        yield StartEvent(data=StartData(session_id=turn.session_id))
        yield IntentEvent(data=IntentData(mode="recommend"))
        yield MessageEvent(data=MessageData(content="text"))
        yield EndEvent(
            data=EndData(
                conversation_version=turn.conversation_version
            )
        )

    def stream(self, turn):
        self.raw_calls.append(turn)
        yield StartEvent(data=StartData(session_id=turn.session_id))
        yield IntentEvent(data=IntentData(mode="clarify"))
        yield MessageEvent(data=MessageData(content="pending"))
        yield EndEvent(
            data=EndData(
                conversation_version=turn.conversation_version
            )
        )


class RecordingConsultationProcessor:
    def __init__(self, *, dynamic_session: bool = False) -> None:
        self.calls = []
        self.meaning_calls = []
        self.dynamic_session = dynamic_session

    def has_dynamic_session(self, turn) -> bool:
        self.dynamic_session_turn = turn
        return self.dynamic_session

    def stream(self, turn):
        self.calls.append(turn)
        yield StartEvent(data=StartData(session_id=turn.session_id))
        yield IntentEvent(data=IntentData(mode="consultation_entry"))
        yield MessageEvent(data=MessageData(content="consultation"))
        yield EndEvent(
            data=EndData(
                conversation_version=turn.conversation_version
            )
        )

    def stream_meaning(self, turn, *, meaning):
        self.meaning_calls.append((turn, meaning))
        yield StartEvent(data=StartData(session_id=turn.session_id))
        yield IntentEvent(data=IntentData(mode="consultation_entry"))
        yield MessageEvent(data=MessageData(content="consultation"))
        yield EndEvent(
            data=EndData(
                conversation_version=turn.conversation_version
            )
        )


class RecordingImageProcessor:
    def __init__(self, *, image_count: int = 1) -> None:
        self.calls = []
        self.image_count = image_count

    def semantic_image_count(self, turn) -> int:
        self.image_count_turn = turn
        return self.image_count

    def stream_understanding(
        self,
        turn,
        *,
        meaning,
        understanding,
        snapshot,
    ):
        self.calls.append(
            (turn, meaning, understanding, snapshot)
        )
        yield StartEvent(data=StartData(session_id=turn.session_id))
        yield IntentEvent(data=IntentData(mode="image_identity"))
        yield MessageEvent(data=MessageData(content="image"))
        yield EndEvent(
            data=EndData(
                conversation_version=turn.conversation_version
            )
        )


def _turn(message: str = "推荐防晒", *, version: int = 0) -> UserTurn:
    return UserTurn(
        session_id="unified-flow",
        message=message,
        conversation_version=version,
    )


def test_unified_flow_translates_once_and_delegates_preunderstood_text() -> None:
    translator = RecordingTranslator(
        _meaning("recommendation"),
        _understanding(UnderstandingGoal.RECOMMENDATION),
    )
    text = RecordingTextProcessor()
    consultation = RecordingConsultationProcessor()
    flow = UnifiedGuideFlow(
        understanding=translator,
        text_processor=text,
        consultation_processor=consultation,
        conversation_state=InMemoryConversationState(),
    )

    events = list(flow.stream(_turn()))

    assert [event.event for event in events] == [
        "start",
        "intent",
        "message",
        "end",
    ]
    assert len(translator.calls) == 1
    assert len(text.preunderstood_calls) == 1
    assert text.raw_calls == []
    assert consultation.calls == []
    route = text.preunderstood_calls[0][2]
    assert route.processor == "recommendation"


def test_unified_flow_reconciles_return_alias_before_text_execution() -> None:
    class MissingAliasTextProcessor(RecordingTextProcessor):
        def resolve_product_resolution(self, **kwargs):
            self.resolution_request = kwargs
            return ProductMentionResolution(
                bindings=(),
                issue="missing_reference",
            )

    state = InMemoryConversationState()
    state.save(
        ConversationSnapshot(
            session_id="unified-flow",
            version=1,
            query_context=RecommendationQueryContext(category="serum"),
            candidates=(
                DisplayedCandidateRef(
                    product_id=38,
                    ordinal=1,
                    skin_match="unknown",
                    matched_efficacies=(),
                ),
            ),
            focus_state=FocusState(
                active_processor="general_knowledge",
                current_product_id=38,
                current_knowledge_topic="烟酰胺",
            ),
        ),
        expected_version=0,
    )
    meaning = _meaning("followup", continuity="return_to_focus")
    understanding = _understanding(
        UnderstandingGoal.FOLLOWUP
    ).model_copy(
        update={
            "topic": TopicCode.SERUM,
            "references": [
                ReferenceDraft(
                    kind="current_item",
                    source_span=SourceSpan(start=7, end=8),
                )
            ],
            "product_mentions": [
                ProductMentionDraft(
                    text="B5那瓶",
                    source_span=SourceSpan(start=2, end=6),
                )
            ],
        },
        deep=True,
    )
    text = MissingAliasTextProcessor()
    flow = UnifiedGuideFlow(
        understanding=RecordingTranslator(meaning, understanding),
        text_processor=text,
        consultation_processor=RecordingConsultationProcessor(),
        conversation_state=state,
    )

    events = list(
        flow.stream(
            _turn(
                "回到B5那瓶，它页面里的品牌主打有哪些",
                version=1,
            )
        )
    )

    assert events[-1].event == "end"
    route = text.preunderstood_calls[0][2]
    assert route.processor == "product_knowledge"
    assert [item.product_id for item in route.product_bindings] == [38]


def test_unified_flow_routes_exact_budget_revision_as_correction() -> None:
    state = InMemoryConversationState()
    snapshot = ConversationSnapshot(
        session_id="unified-flow",
        version=1,
        query_context=RecommendationQueryContext(
            category="serum",
            budget_maximum=Decimal("500"),
            skin="sensitive",
            efficacy="repair",
        ),
        candidates=(
            DisplayedCandidateRef(
                product_id=38,
                ordinal=1,
                skin_match="matched",
                matched_efficacies=("修护",),
            ),
            DisplayedCandidateRef(
                product_id=91,
                ordinal=2,
                skin_match="matched",
                matched_efficacies=("修护",),
            ),
        ),
        focus_state=FocusState(
            active_processor="recommendation",
        ),
    )
    state.save(snapshot, expected_version=0)
    message = "预算降到 100 元呢"
    meaning = TurnMeaning.model_validate(
        {
            "operation_hint": "recommendation",
            "topic_hint": "serum",
            "continuity_hint": "continue",
            "subject_scope_hint": "self",
            "reference_mentions": [
                {
                    "raw_text": "预算",
                    "object_family_hint": "constraint",
                    "ordinal_hint": None,
                    "plurality_hint": "single",
                }
            ],
            "product_mentions": [],
            "budget_candidates": [
                {
                    "raw_text": "100 元",
                    "relation": "maximum",
                    "minimum": None,
                    "maximum": "100",
                }
            ],
            "observation_candidates": [],
            "preference_candidates": [],
            "relative_candidates": [],
            "consultation_hypothesis": None,
            "next_observation_gap": None,
            "question_meaning": "把原推荐预算上限改为100元",
            "safety_language": "ordinary",
        },
        strict=True,
    )
    compiled = compile_turn_meaning(
        message=message,
        meaning=meaning,
        context=resolve_semantic_context(
            conversation_version=1,
            snapshot=snapshot,
        ),
    )
    text = RecordingTextProcessor()
    flow = UnifiedGuideFlow(
        understanding=RecordingTranslator(meaning, compiled),
        text_processor=text,
        consultation_processor=RecordingConsultationProcessor(),
        conversation_state=state,
    )

    list(flow.stream(_turn(message, version=1)))

    route = text.preunderstood_calls[0][2]
    assert route.processor == "recommendation"
    assert route.continuity == "correct"


@pytest.mark.parametrize(
    ("message", "raw_text"),
    (
        ("太贵了，最多一百吧", "最多一百"),
        ("其他要求照旧，价钱上限改成100", "价钱上限改成100"),
    ),
)
def test_continuing_single_budget_replaces_existing_slot(
    message: str,
    raw_text: str,
) -> None:
    state = InMemoryConversationState()
    snapshot = ConversationSnapshot(
        session_id="unified-flow",
        version=1,
        query_context=RecommendationQueryContext(
            category="serum",
            budget_maximum=Decimal("500"),
            skin="sensitive",
            efficacy="repair",
        ),
        candidates=(
            DisplayedCandidateRef(
                product_id=38,
                ordinal=1,
                skin_match="matched",
                matched_efficacies=("修护",),
            ),
            DisplayedCandidateRef(
                product_id=91,
                ordinal=2,
                skin_match="matched",
                matched_efficacies=("修护",),
            ),
        ),
        focus_state=FocusState(
            active_processor="recommendation",
        ),
    )
    state.save(snapshot, expected_version=0)
    meaning = TurnMeaning.model_validate(
        {
            "operation_hint": "recommendation",
            "topic_hint": "serum",
            "continuity_hint": "continue",
            "subject_scope_hint": "self",
            "reference_mentions": [],
            "product_mentions": [],
            "budget_candidates": [
                {
                    "raw_text": raw_text,
                    "relation": "maximum",
                    "minimum": None,
                    "maximum": "100",
                }
            ],
            "observation_candidates": [],
            "preference_candidates": [],
            "relative_candidates": [],
            "consultation_hypothesis": None,
            "next_observation_gap": None,
            "question_meaning": None,
            "safety_language": "ordinary",
        },
        strict=True,
    )
    compiled = compile_turn_meaning(
        message=message,
        meaning=meaning,
        context=resolve_semantic_context(
            conversation_version=1,
            snapshot=snapshot,
        ),
    )
    text = RecordingTextProcessor()
    flow = UnifiedGuideFlow(
        understanding=RecordingTranslator(meaning, compiled),
        text_processor=text,
        consultation_processor=RecordingConsultationProcessor(),
        conversation_state=state,
    )

    list(flow.stream(_turn(message, version=1)))

    route = text.preunderstood_calls[0][2]
    assert route.processor == "recommendation"
    assert route.continuity == "correct"


def test_unified_flow_consultation_uses_same_translation() -> None:
    meaning = _meaning("assessment", next_gap="location")
    translator = RecordingTranslator(
        meaning,
        _understanding(UnderstandingGoal.ASSESSMENT),
    )
    text = RecordingTextProcessor()
    consultation = RecordingConsultationProcessor()
    flow = UnifiedGuideFlow(
        understanding=translator,
        text_processor=text,
        consultation_processor=consultation,
        conversation_state=InMemoryConversationState(),
    )

    events = list(flow.stream(_turn("我不知道自己是什么肤质")))

    assert events[1].data.mode == "consultation_entry"
    assert len(translator.calls) == 1
    assert consultation.calls == []
    assert consultation.meaning_calls == [
        (_turn("我不知道自己是什么肤质"), meaning)
    ]
    assert text.preunderstood_calls == []


def test_unified_flow_exact_only_consultation_uses_legacy_fallback() -> None:
    translator = RecordingTranslator(
        _meaning("assessment"),
        _understanding(UnderstandingGoal.ASSESSMENT),
    )
    text = RecordingTextProcessor()
    consultation = RecordingConsultationProcessor()
    flow = UnifiedGuideFlow(
        understanding=translator,
        text_processor=text,
        consultation_processor=consultation,
        conversation_state=InMemoryConversationState(),
    )

    list(flow.stream(_turn("我不知道自己是什么肤质")))

    assert len(translator.calls) == 1
    assert consultation.calls == [
        _turn("我不知道自己是什么肤质")
    ]
    assert consultation.meaning_calls == []


def test_unified_flow_atomless_dynamic_reply_uses_meaning_lane() -> None:
    meaning = _meaning("assessment", continuity="continue")
    translator = RecordingTranslator(
        meaning,
        _understanding(UnderstandingGoal.ASSESSMENT),
    )
    consultation = RecordingConsultationProcessor(
        dynamic_session=True,
    )
    flow = UnifiedGuideFlow(
        understanding=translator,
        text_processor=RecordingTextProcessor(),
        consultation_processor=consultation,
        conversation_state=InMemoryConversationState(),
    )
    turn = _turn("对，就是这样")

    list(flow.stream(turn))

    assert consultation.calls == []
    assert consultation.meaning_calls == [(turn, meaning)]
    assert consultation.dynamic_session_turn == turn


def test_unified_flow_image_uses_the_same_single_translation() -> None:
    meaning = _meaning("knowledge")
    understanding = _understanding(UnderstandingGoal.KNOWLEDGE)
    translator = RecordingTranslator(meaning, understanding)
    image = RecordingImageProcessor(image_count=2)
    flow = UnifiedGuideFlow(
        understanding=translator,
        text_processor=RecordingTextProcessor(),
        consultation_processor=RecordingConsultationProcessor(),
        conversation_state=InMemoryConversationState(),
    )
    turn = _turn("这是什么商品")

    events = list(flow.stream_image(turn, image_processor=image))

    assert [event.event for event in events] == [
        "start",
        "intent",
        "message",
        "end",
    ]
    assert len(translator.calls) == 1
    assert translator.calls[0][1].image_count == 2
    assert translator.calls[0][1].focused_image_ordinal is None
    assert image.image_count_turn == turn
    assert image.calls == [
        (turn, meaning, understanding, None)
    ]


def test_pending_turn_is_translated_once_then_uses_existing_pending_processor(
) -> None:
    state = InMemoryConversationState()
    pending = PendingTurn(
        gap=ClarificationCode.BUDGET,
        attempts=1,
        source_conversation_version=0,
        source_message="预算一千左右的精华",
        expected_response="confirm_or_correct",
        resume_mode="recommendation",
        resume_context=PendingRecommendationContext(
            category="serum",
        ),
        proposed_budget=PendingBudgetRange(
            minimum=Decimal("900"),
            maximum=Decimal("1100"),
        ),
    )
    state.save(
        ConversationSnapshot(
            session_id="unified-flow",
            version=1,
            query_context=RecommendationQueryContext(
                category="serum",
                budget_minimum=None,
                budget_maximum=Decimal("1100"),
                skin=None,
                efficacy=None,
                exclusions=(),
            ),
            candidates=(
                DisplayedCandidateRef(
                    product_id=38,
                    ordinal=1,
                    skin_match="unknown",
                    matched_efficacies=(),
                ),
            ),
            pending_turn=pending,
            focus_state=FocusState(
                active_processor="clarification",
            ),
        ),
        expected_version=0,
    )
    translator = RecordingTranslator(
        _meaning("clarification", continuity="continue"),
        _understanding(UnderstandingGoal.CLARIFICATION),
    )
    text = RecordingTextProcessor()
    flow = UnifiedGuideFlow(
        understanding=translator,
        text_processor=text,
        consultation_processor=RecordingConsultationProcessor(),
        conversation_state=state,
    )

    events = list(flow.stream(_turn("是的", version=1)))

    assert events[2].data.content == "pending"
    assert len(translator.calls) == 1
    assert len(text.raw_calls) == 1
    assert text.preunderstood_calls == []


def test_real_text_processor_uses_one_translation_and_typed_sse(
    real_reader,
    real_product_assets,
) -> None:
    state = InMemoryConversationState()
    text = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=state,
        presentation_copywriter=None,
    )
    translator = RecordingTranslator(
        _meaning("recommendation"),
        understand_text("500 元内敏感肌修护精华"),
    )
    flow = UnifiedGuideFlow(
        understanding=translator,
        text_processor=text,
        consultation_processor=RecordingConsultationProcessor(),
        conversation_state=text._conversation_state,
    )

    events = list(
        iter_guide_public_events(
            flow,
            _turn("500 元内敏感肌修护精华"),
        )
    )

    assert len(translator.calls) == 1
    assert events[-1] == ("end", {"conversation_version": 1})
    products = next(
        data["products"]
        for event, data in events
        if event == "products"
    )
    assert [item["product_id"] for item in products] == [38, 91]
    assert state.load("unified-flow") is None
    commit_http_event_delivery(events[-1])
    stored = state.load("unified-flow")
    assert stored is not None
    assert stored.version == 1
    assert stored.focus_state is not None
    assert stored.focus_state.active_processor == "recommendation"


def test_return_to_product_focus_preserves_recommendation_context(
    real_reader,
    real_product_assets,
) -> None:
    state = InMemoryConversationState()
    snapshot = ConversationSnapshot(
        session_id="unified-flow",
        version=1,
        query_context=RecommendationQueryContext(
            category="serum",
            budget_maximum=Decimal("500"),
            skin="sensitive",
            efficacy="repair",
        ),
        candidates=(
            DisplayedCandidateRef(
                product_id=38,
                ordinal=1,
                skin_match="matched",
                matched_efficacies=("修护",),
            ),
            DisplayedCandidateRef(
                product_id=91,
                ordinal=2,
                skin_match="matched",
                matched_efficacies=("修护",),
            ),
        ),
        focus_state=FocusState(
            active_processor="general_knowledge",
            current_product_id=91,
            current_knowledge_topic="视黄醇",
            last_question_meaning="视黄醇是什么",
        ),
        last_general_knowledge_question="视黄醇是什么",
    )
    state.save(snapshot, expected_version=0)
    message = "恢复之前商品焦点，看看是否适合白天"
    meaning = TurnMeaning.model_validate(
        {
            "operation_hint": "suitability",
            "topic_hint": "serum",
            "continuity_hint": "return_to_focus",
            "subject_scope_hint": "unknown",
            "reference_mentions": [
                {
                    "raw_text": "之前商品",
                    "object_family_hint": "product",
                    "ordinal_hint": None,
                    "plurality_hint": "single",
                }
            ],
            "product_mentions": [],
            "budget_candidates": [],
            "observation_candidates": [],
            "preference_candidates": [],
            "relative_candidates": [],
            "consultation_hypothesis": None,
            "next_observation_gap": None,
            "question_meaning": "是否适合白天使用",
            "safety_language": "ordinary",
        },
        strict=True,
    )
    understanding = compile_turn_meaning(
        message=message,
        meaning=meaning,
        context=resolve_semantic_context(
            conversation_version=1,
            snapshot=snapshot,
        ),
    )
    text = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=state,
        presentation_copywriter=None,
    )
    flow = UnifiedGuideFlow(
        understanding=RecordingTranslator(meaning, understanding),
        text_processor=text,
        consultation_processor=RecordingConsultationProcessor(),
        conversation_state=text._conversation_state,
    )

    events = list(
        iter_guide_public_events(
            flow,
            _turn(message, version=1),
        )
    )

    assert events[-1] == ("end", {"conversation_version": 2})
    assert state.load("unified-flow") == snapshot
    commit_http_event_delivery(events[-1])
    stored = state.load("unified-flow")
    assert stored is not None
    assert stored.query_context == snapshot.query_context
    assert stored.candidates == snapshot.candidates
    assert stored.focus_state is not None
    assert stored.focus_state.active_processor == "product_knowledge"
    assert stored.focus_state.current_product_id == 91


def test_router_cardinality_clarification_does_not_raise_internal_error(
    tmp_path: Path,
) -> None:
    message = "B5精华、CE精华分别适合哪些使用场景"
    meaning = TurnMeaning.model_validate(
        {
            "operation_hint": "knowledge",
            "topic_hint": "serum",
            "continuity_hint": "new_task",
            "subject_scope_hint": "unknown",
            "reference_mentions": [],
            "product_mentions": [
                {"raw_text": "B5精华"},
                {"raw_text": "CE精华"},
            ],
            "budget_candidates": [],
            "observation_candidates": [],
            "preference_candidates": [],
            "relative_candidates": [],
            "consultation_hypothesis": None,
            "next_observation_gap": None,
            "question_meaning": "两款精华分别适合哪些使用场景",
            "safety_language": "unknown",
        },
        strict=True,
    )
    understanding = compile_turn_meaning(
        message=message,
        meaning=meaning,
        context=resolve_semantic_context(
            conversation_version=0,
            snapshot=None,
        ),
    )
    vertical = build_consultation_vertical_runtime(
        state_dir=tmp_path / "router-clarification",
    )
    vertical.unified._understanding = RecordingTranslator(
        meaning,
        understanding,
    )
    turn = UserTurn(
        session_id="unified-flow",
        message=message,
        profile_owner=vertical.profile_owner("unified-flow"),
        conversation_version=0,
    )

    events = list(
        iter_guide_public_events(
            vertical.unified,
            turn,
        )
    )

    assert [event for event, _ in events] == [
        "start",
        "stage",
        "intent",
        "message",
        "end",
    ]
    assert events[2][1]["intent"] == "clarify"
    assert events[3][1]["clarify"] is True
    assert vertical.conversation_state.load("unified-flow") is None


def test_explicit_comparison_dimension_does_not_filter_named_products(
    tmp_path: Path,
) -> None:
    message = "把B5精华和CE精华按修护重点、肤感、使用时段做对照"
    meaning = TurnMeaning.model_validate(
        {
            "operation_hint": "comparison",
            "topic_hint": "serum",
            "continuity_hint": "new_task",
            "subject_scope_hint": "unknown",
            "reference_mentions": [
                {
                    "raw_text": "B5精华",
                    "object_family_hint": "product",
                    "ordinal_hint": None,
                    "plurality_hint": "single",
                },
                {
                    "raw_text": "CE精华",
                    "object_family_hint": "product",
                    "ordinal_hint": None,
                    "plurality_hint": "single",
                },
            ],
            "product_mentions": [
                {"raw_text": "B5精华"},
                {"raw_text": "CE精华"},
            ],
            "budget_candidates": [],
            "observation_candidates": [],
            "preference_candidates": [],
            "relative_candidates": [],
            "consultation_hypothesis": None,
            "next_observation_gap": None,
            "question_meaning": "按修护重点、肤感和使用时段比较两款精华",
            "safety_language": "unknown",
        },
        strict=True,
    )
    understanding = compile_turn_meaning(
        message=message,
        meaning=meaning,
        context=resolve_semantic_context(
            conversation_version=0,
            snapshot=None,
        ),
    )
    vertical = build_consultation_vertical_runtime(
        state_dir=tmp_path / "explicit-comparison",
    )
    vertical.unified._understanding = RecordingTranslator(
        meaning,
        understanding,
    )
    turn = UserTurn(
        session_id="unified-flow",
        message=message,
        profile_owner=vertical.profile_owner("unified-flow"),
        conversation_version=0,
    )

    events = list(iter_guide_public_events(vertical.unified, turn))

    assert events[-1] == ("end", {"conversation_version": 1})
    products = next(
        data["products"]
        for event, data in events
        if event == "products"
    )
    assert [item["product_id"] for item in products] == [38, 34]
