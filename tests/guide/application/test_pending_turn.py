from __future__ import annotations

from decimal import Decimal

import pytest

from app.guide.application.pending_turn import classify_pending_reply
from app.guide.application.chat_api_adapter import (
    commit_http_event_delivery,
    iter_guide_public_events,
)
from app.guide.application.contracts import UserTurn
from app.guide.feedback.contracts import (
    PendingBudgetRange,
    PendingRecommendationContext,
    PendingTurn,
)
from app.guide.understanding.semantic_contracts import ClarificationCode
from app.guide_runtime.composition import build_runtime_orchestrator


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
            skin="dry",
            efficacy="anti_aging",
        ),
        proposed_budget=PendingBudgetRange(
            minimum=Decimal("900"),
            maximum=Decimal("1100"),
        ),
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


def _turn(
    message: str,
    *,
    version: int,
    session_id: str = "pending-budget-flow",
) -> UserTurn:
    return UserTurn(
        session_id=session_id,
        message=message,
        image_bundle_id=None,
        conversation_version=version,
    )


def _deliver(orchestrator, turn: UserTurn):
    events = list(iter_guide_public_events(orchestrator, turn))
    assert events[-1][0] == "end"
    commit_http_event_delivery(events[-1])
    return events


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
    pending = orchestrator._conversation_state._delegate.load(
        "pending-budget-flow"
    )

    assert any(
        event == "message" and data.get("clarify") is True
        for event, data in first
    )
    assert pending is not None
    assert pending.pending_turn is not None
    assert pending.pending_turn.source_message.startswith("干敏肌")
    assert pending.pending_turn.proposed_budget == PendingBudgetRange(
        minimum=Decimal("900"),
        maximum=Decimal("1100"),
    )

    second = _deliver(
        orchestrator,
        _turn("是的", version=1),
    )
    saved = orchestrator._conversation_state._delegate.load(
        "pending-budget-flow"
    )

    assert not any(
        event == "message" and data.get("clarify") is True
        for event, data in second
    )
    assert any(event == "products" for event, _ in second)
    assert saved is not None
    assert saved.pending_turn is None
    assert saved.candidates
    assert saved.query_context is not None
    assert saved.query_context.budget_minimum == Decimal("900")
    assert saved.query_context.budget_maximum == Decimal("1100")


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
    saved = orchestrator._conversation_state._delegate.load(
        "pending-budget-flow"
    )

    assert any(event == "products" for event, _ in events)
    assert saved is not None
    assert saved.pending_turn is None
    assert saved.query_context is not None
    assert saved.query_context.budget_minimum == Decimal(minimum)
    assert saved.query_context.budget_maximum == Decimal(maximum)
    if exclusion is not None:
        assert exclusion in saved.query_context.exclusions


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
    pending = orchestrator._conversation_state._delegate.load(
        "pending-budget-flow"
    )

    assert any(
        event == "message" and data.get("clarify") is True
        for event, data in rejected
    )
    assert pending is not None
    assert pending.pending_turn is not None
    assert pending.pending_turn.expected_response == "supply_value"
    assert pending.pending_turn.proposed_budget is None

    resumed = _deliver(
        orchestrator,
        _turn("800到1000", version=2),
    )
    saved = orchestrator._conversation_state._delegate.load(
        "pending-budget-flow"
    )

    assert any(event == "products" for event, _ in resumed)
    assert saved is not None
    assert saved.pending_turn is None
    assert saved.query_context.budget_minimum == Decimal("800")
    assert saved.query_context.budget_maximum == Decimal("1000")


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
    saved = orchestrator._conversation_state._delegate.load(
        "pending-budget-flow"
    )

    assert any(
        event == "message" and data.get("clarify") is True
        for event, data in events
    )
    assert saved is not None
    assert saved.pending_turn is not None
    assert saved.pending_turn.attempts == 2
    assert saved.pending_turn.source_message == original
    assert saved.pending_turn.source_conversation_version == 0


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
    saved = orchestrator._conversation_state._delegate.load(
        "pending-budget-flow"
    )

    assert not any(
        event == "message" and data.get("clarify") is True
        for event, data in events
    )
    assert saved is not None
    assert saved.pending_turn is None
    assert saved.query_context is not None
    assert saved.query_context.category == "sunscreen"


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
    unrelated = list(
        iter_guide_public_events(
            worker_b,
            _turn("是的", version=0, session_id="session-b"),
        )
    )
    resumed = _deliver(
        worker_b,
        _turn("是的", version=1, session_id="session-a"),
    )

    assert any(
        event == "message" and data.get("clarify") is True
        for event, data in unrelated
    )
    assert any(event == "products" for event, _ in resumed)
    saved_a = worker_a._conversation_state._delegate.load("session-a")
    saved_b = worker_a._conversation_state._delegate.load("session-b")
    assert saved_a is not None
    assert saved_a.pending_turn is None
    assert saved_a.candidates
    assert saved_b is None
