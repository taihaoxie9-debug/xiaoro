from __future__ import annotations

from decimal import Decimal
import json

import pytest

from app.guide.application.pending_turn import (
    PendingReply,
    classify_pending_reply,
    resolve_semantic_pending_reply,
    resume_pending_recommendation,
)
from app.guide.application.pending_turn import build_pending_turn
from app.guide.application.contracts import TurnIdentity, UserTurn
from app.guide.feedback.contracts import (
    PendingBudgetRange,
    PendingRecommendationContext,
    PendingTurn,
    PendingClarificationSlot,
    PendingReplySlot,
)
from app.guide.intent.executable_intent_compiler import (
    compile_turn_meaning,
)
from app.guide.intent.contracts import (
    CategoryConstraint,
    TaskPlan,
)
from app.guide.understanding.contracts import (
    StructuredUnderstanding,
    TopicCode,
    UnderstandingGoal,
)
from app.guide.understanding.turn_meaning_contracts import TurnMeaning
from app.guide.intent.task_planning import plan_task
from app.guide.understanding.context_resolver import (
    resolve_semantic_context,
)
from app.guide.understanding.semantic_contracts import (
    ClarificationCode,
    SemanticContext,
)
from app.guide_runtime.composition import (
    build_consultation_vertical_runtime,
)
from tests.guide.semantic_test_port import exact_echo_understanding


class _PendingTurnMeaningPort:
    def propose(
        self,
        message: str,
        context: SemanticContext,
    ) -> TurnMeaning:
        return _pending_turn_meaning(
            message,
            context=context,
        )


def build_runtime_orchestrator(*args, **kwargs):
    kwargs.setdefault(
        "semantic_intent",
        _PendingTurnMeaningPort(),
    )
    return build_consultation_vertical_runtime(
        *args,
        **kwargs,
    ).unified


def _pending_turn_meaning(
    message: str,
    *,
    context: SemanticContext,
) -> TurnMeaning:
    pending_replies = {
        "是的": ("affirm", ()),
        "不是": ("reject", ()),
        "差不多吧": ("unknown", ()),
        "改成800到1000": (
            "correct",
            (
                {
                    "raw_text": "800到1000",
                    "relation": "range",
                    "minimum": "800",
                    "maximum": "1000",
                },
            ),
        ),
        "800到1000": (
            "correct",
            (
                {
                    "raw_text": "800到1000",
                    "relation": "range",
                    "minimum": "800",
                    "maximum": "1000",
                },
            ),
        ),
        "对，五百就是上限": (
            "correct",
            (
                {
                    "raw_text": "五百就是上限",
                    "relation": "maximum",
                    "minimum": None,
                    "maximum": "500",
                },
            ),
        ),
        "是的，而且不要酒精": ("supplement", ()),
    }
    if message in pending_replies:
        pending_response_hint, budget_candidates = pending_replies[
            message
        ]
        return TurnMeaning(
            operation_hint="clarification",
            topic_hint=None,
            continuity_hint="continue",
            subject_scope_hint="self",
            pending_response_hint=pending_response_hint,
            budget_candidates=budget_candidates,
            preference_candidates=(
                (
                    {
                        "field_key": "ingredient_exclusion",
                        "concept_id": None,
                        "raw_text": "酒精",
                        "polarity": "avoid",
                        "strength": "ordinary",
                    },
                )
                if message == "是的，而且不要酒精"
                else ()
            ),
            question_meaning=message,
            safety_language="ordinary",
        )
    if message == "改看防晒吧":
        return TurnMeaning(
            operation_hint="recommendation",
            recommendation_mode="explore",
            recommendation_mode_basis={
                "basis": "broad_exploration",
                "source_text": message,
            },
            topic_hint="sunscreen",
            continuity_hint="continue",
            subject_scope_hint="self",
            pending_response_hint="replace_task",
            question_meaning=message,
            safety_language="ordinary",
        )
    approximate_budget = {
        "干敏肌想要抗初老精华，预算1000左右": (
            "预算1000左右",
            "900",
            "1100",
        ),
        "想看敏感肌修护精华，预算大概五百吧": (
            "预算大概五百",
            "450",
            "550",
        ),
    }.get(message)
    if approximate_budget is not None:
        raw_text, minimum, maximum = approximate_budget
        return TurnMeaning(
            operation_hint="recommendation",
            recommendation_mode="explore",
            recommendation_mode_basis={
                "basis": "broad_exploration",
                "source_text": message,
            },
            topic_hint="serum",
            continuity_hint=(
                "new_task"
                if context.conversation_version == 0
                else "continue"
            ),
            subject_scope_hint="self",
            budget_candidates=(
                {
                    "raw_text": raw_text,
                    "relation": "approximate",
                    "minimum": minimum,
                    "maximum": maximum,
                },
            ),
            question_meaning=message,
            safety_language="ordinary",
        )
    return exact_echo_understanding().translate(
        message,
        context=context,
    )


def _pending() -> PendingTurn:
    return PendingTurn(
        gap=ClarificationCode.BUDGET,
        attempts=1,
        source_conversation_version=0,
        source_message="干敏肌想要抗初老精华，预算1000左右",
        expected_response="confirm_or_correct",
        resume_mode="recommendation",
        resume_context=PendingRecommendationContext(
            category="serum",
            recommendation_mode_basis="broad_exploration",
            skin="dry",
            efficacy="anti_aging",
        ),
        proposed_budget=PendingBudgetRange(
            minimum=Decimal("900"),
            maximum=Decimal("1100"),
        ),
    )


def test_pending_resume_preserves_recommendation_mode_basis() -> None:
    pending = PendingTurn(
        gap=ClarificationCode.BUDGET,
        attempts=1,
        source_conversation_version=0,
        source_message="给我选最适合敏感肌的一款精华",
        expected_response="confirm_or_correct",
        resume_mode="recommendation",
        resume_context=PendingRecommendationContext(
            category="serum",
            recommendation_mode="fit",
            recommendation_mode_basis="personal_suitability",
            recommendation_count=1,
            skin="sensitive",
        ),
        proposed_budget=PendingBudgetRange(
            minimum=Decimal("900"),
            maximum=Decimal("1100"),
        ),
    )

    task = resume_pending_recommendation(
        pending=pending,
        reply=PendingReply(
            kind="affirm",
            accepted_proposal=True,
            budget=pending.proposed_budget,
        ),
    )

    assert task.recommendation_mode == "fit"
    assert task.recommendation_mode_basis == "personal_suitability"
    assert task.recommendation_count == 1


def test_pending_builder_rejects_missing_recommendation_basis() -> None:
    task = TaskPlan(
        mode="clarify",
        recommendation_mode="explore",
        recommendation_mode_basis="broad_exploration",
        recommendation_count=3,
        referenced_image_ids=[],
        constraints=[CategoryConstraint(value=TopicCode.SERUM)],
        required_evidence=[],
        clarification="请确认预算范围。",
        clarification_code=ClarificationCode.BUDGET,
    ).model_copy(
        update={"recommendation_mode_basis": None},
        deep=True,
    )

    with pytest.raises(
        ValueError,
        match="pending recommendation requires complete outcome",
    ):
        build_pending_turn(
            message="精华两三百左右",
            source_conversation_version=0,
            task=task,
        )


@pytest.mark.parametrize(
    "message",
    (
        "是的",
        "对",
        "没错",
        "嗯，对的",
        "对，就按这个预算",
        "是，我确认",
        "没错，继续吧",
        "没问题，按你问的值继续",
        "我同意这个预算，往下选",
        "是这个数，继续",
        "确认无误，接着推荐",
        "嗯，那个范围没错",
        "确认这个预算，继续推荐",
    ),
)
def test_short_affirmations_accept_proposed_budget(message: str) -> None:
    reply = classify_pending_reply(
        message=message,
        pending=_pending(),
    )

    assert reply.kind == "affirm"
    assert reply.accepted_proposal
    assert reply.budget == _pending().proposed_budget


@pytest.mark.parametrize(
    "message",
    (
        "不是",
        "不是这个意思",
        "不是，预算我重说",
        "先不要，就不是这个数",
        "先别确认，我要重新报价格",
        "这个数不对，等我补充",
        "先停，价格理解错了",
        "刚才的数理解错了，我再补",
    ),
)
def test_short_rejection_keeps_task_but_requests_exact_value(
    message: str,
) -> None:
    reply = classify_pending_reply(
        message=message,
        pending=_pending(),
    )

    assert reply.kind == "reject"
    assert not reply.accepted_proposal
    assert reply.budget is None


def test_exact_budget_correction_replaces_proposal() -> None:
    reply = classify_pending_reply(
        message="改成800到1000",
        pending=_pending(),
    )

    assert reply.kind == "correct"
    assert reply.accepted_proposal
    assert reply.budget == PendingBudgetRange(
        minimum=Decimal("800"),
        maximum=Decimal("1000"),
    )


def test_maximum_only_budget_confirmation_replaces_proposal() -> None:
    reply = classify_pending_reply(
        message="对，五百就是上限",
        pending=_pending(),
    )

    assert reply.kind == "correct"
    assert reply.accepted_proposal
    assert reply.budget == PendingBudgetRange(
        minimum=None,
        maximum=Decimal("500"),
    )


def test_negated_budget_bound_rejects_pending_proposal() -> None:
    reply = classify_pending_reply(
        message="不是三百封顶，我还没决定具体上限",
        pending=_pending(),
    )

    assert reply.kind == "reject"
    assert not reply.accepted_proposal
    assert reply.budget is None


def test_adjacent_hundreds_clarification_builds_pending_turn() -> None:
    message = "修护精华两三百左右都行"
    context = resolve_semantic_context(
        conversation_version=0,
        snapshot=None,
    )
    meaning = exact_echo_understanding().translate(
        message,
        context=context,
    )
    understanding = compile_turn_meaning(
        message=message,
        meaning=meaning,
        context=context,
    )
    task = plan_task(understanding, message=message)

    assert task.mode == "clarify"
    assert task.recommendation_mode == "explore"
    assert task.recommendation_mode_basis == "broad_exploration"
    assert task.recommendation_count == 3

    pending = build_pending_turn(
        message=message,
        source_conversation_version=0,
        task=task,
    )

    assert pending is not None
    assert pending.proposed_budget == PendingBudgetRange(
        minimum=Decimal("200"),
        maximum=Decimal("300"),
    )
    assert pending.resume_context.category == "serum"
    assert (
        pending.resume_context.recommendation_mode_basis
        == "broad_exploration"
    )
    assert pending.resume_context.efficacy == "repair"


def test_affirmation_with_compatible_constraint_supplements_task() -> None:
    reply = classify_pending_reply(
        message="是的，而且不要酒精",
        pending=_pending(),
    )

    assert reply.kind == "supplement"
    assert reply.accepted_proposal
    assert reply.budget == _pending().proposed_budget
    assert reply.exclusions == ("酒精",)


def test_explicit_new_category_replaces_pending_task() -> None:
    reply = classify_pending_reply(
        message="改看防晒吧",
        pending=_pending(),
    )

    assert reply.kind == "replace_task"
    assert reply.replacement_category == "sunscreen"
    assert not reply.accepted_proposal


def test_ambiguous_short_reply_preserves_pending_task() -> None:
    reply = classify_pending_reply(
        message="差不多吧",
        pending=_pending(),
    )

    assert reply.kind == "ambiguous"
    assert not reply.accepted_proposal
    assert reply.budget is None


def test_semantic_pending_affirmation_owns_open_language() -> None:
    meaning = TurnMeaning.model_validate(
        {
            "operation_hint": "clarification",
            "topic_hint": None,
            "continuity_hint": "continue",
            "subject_scope_hint": "self",
            "pending_response_hint": "affirm",
            "reference_mentions": [],
            "product_mentions": [],
            "budget_candidates": [],
            "observation_candidates": [],
            "preference_candidates": [],
            "relative_candidates": [],
            "constraint_changes": [],
            "consultation_hypothesis": None,
            "next_observation_gap": None,
            "question_meaning": None,
            "safety_language": "ordinary",
        },
        strict=True,
    )
    understanding = StructuredUnderstanding(
        goal=UnderstandingGoal.CLARIFICATION,
        topic=None,
        observations=[],
        exact_constraints=[],
        semantic_proposals=["pending_response:admitted:affirm:照刚才方案走"],
        signal_trace=[],
        image_references=[],
        uncertainties=[],
        confidence=1.0,
        semantic_authoritative=True,
    )

    reply = resolve_semantic_pending_reply(
        meaning=meaning,
        understanding=understanding,
        pending=_pending(),
    )

    assert reply.kind == "affirm"
    assert reply.accepted_proposal
    assert reply.budget == _pending().proposed_budget


def test_semantic_pending_exact_maximum_correction_owns_old_quiz() -> None:
    message = "对，五百就是上限"
    meaning = TurnMeaning(
        operation_hint="clarification",
        topic_hint=None,
        continuity_hint="continue",
        subject_scope_hint="self",
        pending_response_hint="correct",
        budget_candidates=(
            {
                "raw_text": "五百就是上限",
                "relation": "maximum",
                "minimum": None,
                "maximum": "500",
            },
        ),
        safety_language="ordinary",
    )
    understanding = compile_turn_meaning(
        message=message,
        meaning=meaning,
        context=SemanticContext(
            conversation_version=1,
            active_topic=None,
            visible_candidate_count=0,
            image_count=0,
            pending_clarification=ClarificationCode.BUDGET,
            confirmed_profile_fields=(),
        ),
    )

    reply = resolve_semantic_pending_reply(
        meaning=meaning,
        understanding=understanding,
        pending=_pending(),
    )

    assert reply.kind == "correct"
    assert reply.budget == PendingBudgetRange(
        minimum=None,
        maximum=Decimal("500"),
    )


def test_semantic_pending_negated_old_bound_rejects_old_quiz() -> None:
    message = "不是三百封顶，我还没决定具体上限"
    meaning = TurnMeaning(
        operation_hint="clarification",
        topic_hint=None,
        continuity_hint="continue",
        subject_scope_hint="self",
        pending_response_hint="reject",
        safety_language="ordinary",
    )
    understanding = compile_turn_meaning(
        message=message,
        meaning=meaning,
        context=SemanticContext(
            conversation_version=1,
            active_topic=None,
            visible_candidate_count=0,
            image_count=0,
            pending_clarification=ClarificationCode.BUDGET,
            confirmed_profile_fields=(),
        ),
    )

    reply = resolve_semantic_pending_reply(
        meaning=meaning,
        understanding=understanding,
        pending=_pending(),
    )

    assert reply.kind == "reject"
    assert not reply.accepted_proposal
    assert reply.budget is None


def _turn(
    message: str,
    *,
    version: int,
    session_id: str = "pending-budget-flow",
) -> UserTurn:
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


def _deliver(orchestrator, turn: UserTurn):
    events = _decode_frames(orchestrator.stream(turn))
    assert events[-1][0] == "end"
    return events


def _decode_frames(frames):
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


def _stored_pending(snapshot):
    return (
        snapshot.reply_slot.value
        if isinstance(snapshot.reply_slot, PendingReplySlot)
        else None
    )


def _stored_clarification(snapshot):
    return (
        snapshot.reply_slot.value
        if isinstance(snapshot.reply_slot, PendingClarificationSlot)
        else None
    )


def _stored_query(snapshot):
    return (
        snapshot.recommendation_slot.query_context
        if snapshot.recommendation_slot is not None
        else None
    )


def test_real_budget_confirmation_resumes_original_recommendation(
    tmp_path,
) -> None:
    orchestrator = build_runtime_orchestrator(
        state_dir=tmp_path / "pending-state",
    )

    first = _deliver(
        orchestrator,
        _turn(
            "干敏肌想要抗初老精华，预算1000左右",
            version=0,
        ),
    )
    pending = orchestrator._conversation_state.load(
        "pending-budget-flow"
    )

    assert any(
        event == "clarify"
        for event, data in first
    )
    assert pending is not None
    stored_pending = _stored_pending(pending)
    assert stored_pending is not None
    assert stored_pending.source_message.startswith("干敏肌")
    assert stored_pending.proposed_budget == PendingBudgetRange(
        minimum=Decimal("900"),
        maximum=Decimal("1100"),
    )

    second = _deliver(
        orchestrator,
        _turn("是的", version=1),
    )
    saved = orchestrator._conversation_state.load(
        "pending-budget-flow"
    )

    assert not any(
        event == "clarify"
        for event, data in second
    )
    assert any(event == "products" for event, _ in second)
    assert saved is not None
    assert saved.reply_slot is None
    assert saved.recommendation_slot.candidates
    query = _stored_query(saved)
    assert query is not None
    assert query.budget_minimum == Decimal("900")
    assert query.budget_maximum == Decimal("1100")


def test_chinese_approximate_budget_then_maximum_resumes_original_task(
    tmp_path,
) -> None:
    orchestrator = build_runtime_orchestrator(
        state_dir=tmp_path / "pending-chinese-approximate",
    )
    first = _deliver(
        orchestrator,
        _turn(
            "想看敏感肌修护精华，预算大概五百吧",
            version=0,
        ),
    )
    pending = orchestrator._conversation_state.load(
        "pending-budget-flow"
    )

    assert any(
        event == "clarify"
        for event, data in first
    )
    assert pending is not None
    stored_pending = _stored_pending(pending)
    assert stored_pending is not None
    assert stored_pending.proposed_budget == PendingBudgetRange(
        minimum=Decimal("450"),
        maximum=Decimal("550"),
    )

    second = _deliver(
        orchestrator,
        _turn("对，五百就是上限", version=1),
    )
    saved = orchestrator._conversation_state.load(
        "pending-budget-flow"
    )

    assert any(event == "products" for event, _ in second)
    assert saved is not None
    assert saved.reply_slot is None
    query = _stored_query(saved)
    assert query is not None
    assert query.budget_minimum is None
    assert query.budget_maximum == Decimal("500")


@pytest.mark.parametrize(
    ("reply", "minimum", "maximum", "exclusion"),
    (
        ("改成800到1000", "800", "1000", None),
        ("是的，而且不要酒精", "900", "1100", "酒精"),
    ),
)
def test_pending_correction_and_supplement_resume_with_merged_context(
    tmp_path,
    reply: str,
    minimum: str,
    maximum: str,
    exclusion: str | None,
) -> None:
    orchestrator = build_runtime_orchestrator(
        state_dir=tmp_path / f"pending-{minimum}",
    )
    _deliver(
        orchestrator,
        _turn(
            "干敏肌想要抗初老精华，预算1000左右",
            version=0,
        ),
    )

    events = _deliver(
        orchestrator,
        _turn(reply, version=1),
    )
    saved = orchestrator._conversation_state.load(
        "pending-budget-flow"
    )

    assert any(event == "products" for event, _ in events)
    assert saved is not None
    assert saved.reply_slot is None
    query = _stored_query(saved)
    assert query is not None
    assert query.budget_minimum == Decimal(minimum)
    assert query.budget_maximum == Decimal(maximum)
    if exclusion is not None:
        assert exclusion in query.exclusions


def test_pending_rejection_then_exact_range_resumes_original_task(
    tmp_path,
) -> None:
    orchestrator = build_runtime_orchestrator(
        state_dir=tmp_path / "pending-reject",
    )
    _deliver(
        orchestrator,
        _turn(
            "干敏肌想要抗初老精华，预算1000左右",
            version=0,
        ),
    )

    rejected = _deliver(
        orchestrator,
        _turn("不是", version=1),
    )
    pending = orchestrator._conversation_state.load(
        "pending-budget-flow"
    )

    assert any(
        event == "clarify"
        for event, data in rejected
    )
    assert pending is not None
    stored_pending = _stored_pending(pending)
    assert stored_pending is not None
    assert stored_pending.expected_response == "supply_value"
    assert stored_pending.proposed_budget is None

    resumed = _deliver(
        orchestrator,
        _turn("800到1000", version=2),
    )
    saved = orchestrator._conversation_state.load(
        "pending-budget-flow"
    )

    assert any(event == "products" for event, _ in resumed)
    assert saved is not None
    assert saved.reply_slot is None
    query = _stored_query(saved)
    assert query.budget_minimum == Decimal("800")
    assert query.budget_maximum == Decimal("1000")


def test_ambiguous_reply_preserves_original_pending_source(
    tmp_path,
) -> None:
    orchestrator = build_runtime_orchestrator(
        state_dir=tmp_path / "pending-ambiguous",
    )
    original = "干敏肌想要抗初老精华，预算1000左右"
    _deliver(orchestrator, _turn(original, version=0))

    events = _deliver(
        orchestrator,
        _turn("差不多吧", version=1),
    )
    saved = orchestrator._conversation_state.load(
        "pending-budget-flow"
    )

    assert any(
        event == "clarify"
        for event, data in events
    )
    assert saved is not None
    stored_pending = _stored_pending(saved)
    assert stored_pending is not None
    assert stored_pending.attempts == 2
    assert stored_pending.source_message == original
    assert stored_pending.source_conversation_version == 0


def test_explicit_new_category_cancels_pending_task(
    tmp_path,
) -> None:
    orchestrator = build_runtime_orchestrator(
        state_dir=tmp_path / "pending-replace",
    )
    _deliver(
        orchestrator,
        _turn(
            "干敏肌想要抗初老精华，预算1000左右",
            version=0,
        ),
    )

    events = _deliver(
        orchestrator,
        _turn("改看防晒吧", version=1),
    )
    saved = orchestrator._conversation_state.load(
        "pending-budget-flow"
    )

    assert not any(
        event == "clarify"
        for event, data in events
    )
    assert saved is not None
    assert saved.reply_slot is None
    query = _stored_query(saved)
    assert query is not None
    assert query.category == "sunscreen"


def test_pending_turn_resumes_across_workers_and_isolates_sessions(
    tmp_path,
) -> None:
    state_root = tmp_path / "pending-cross-worker"
    worker_a = build_runtime_orchestrator(state_dir=state_root)
    worker_b = build_runtime_orchestrator(state_dir=state_root)
    original = "干敏肌想要抗初老精华，预算1000左右"

    _deliver(
        worker_a,
        _turn(original, version=0, session_id="session-a"),
    )
    unrelated = _decode_frames(
        worker_b.stream(
            _turn(
                "是的",
                version=0,
                session_id="session-b",
            )
        )
    )
    resumed = _deliver(
        worker_b,
        _turn("是的", version=1, session_id="session-a"),
    )

    assert any(
        event == "clarify"
        for event, data in unrelated
    )
    assert any(event == "products" for event, _ in resumed)
    saved_a = worker_a._conversation_state.load("session-a")
    saved_b = worker_a._conversation_state.load("session-b")
    assert saved_a is not None
    assert saved_a.reply_slot is None
    assert saved_a.recommendation_slot.candidates
    assert saved_b is not None
    assert saved_b.version == 1
    assert _stored_pending(saved_b) is None
    clarification = _stored_clarification(saved_b)
    assert clarification is not None
    assert clarification.gap is ClarificationCode.GOAL
    assert saved_b.recommendation_slot is None
