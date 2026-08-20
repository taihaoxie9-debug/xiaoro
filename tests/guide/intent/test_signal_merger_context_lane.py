from __future__ import annotations

from decimal import Decimal

import pytest

from app.guide.intent.signal_merger import (
    merge_context_signals,
    merge_intent_signals,
)
from app.guide.understanding.contracts import (
    BudgetDraft,
    CategoryDraft,
    ContextConstraintSignal,
    ExclusionDraft,
    SkinDraft,
    SkinTarget,
    TopicCode,
    UnderstandingGoal,
)
from app.guide.understanding.semantic_contracts import (
    ConfirmedProfileField,
    SemanticContext,
    SemanticGoal,
    SemanticIntentProposal,
)


def _proposal(
    *,
    goal: SemanticGoal = SemanticGoal.RECOMMENDATION,
    topic: TopicCode | None = TopicCode.FRAGRANCE,
    confidence: float = 0.95,
) -> SemanticIntentProposal:
    return SemanticIntentProposal(
        goal=goal,
        topic=topic,
        concerns=(),
        observations=(),
        references=(),
        confidence=confidence,
        clarification_hint=None,
    )


def _context(
    *,
    active_topic: TopicCode | None = None,
    confirmed_profile_fields: tuple[ConfirmedProfileField, ...] = (),
    conversation_version: int = 1,
    visible_candidate_count: int = 0,
) -> SemanticContext:
    return SemanticContext(
        conversation_version=conversation_version,
        active_topic=active_topic,
        visible_candidate_count=visible_candidate_count,
        confirmed_profile_fields=confirmed_profile_fields,
    )


def test_context_argument_defaults_to_none_and_preserves_behavior() -> None:
    without_context = merge_intent_signals(
        message="推荐香水",
        exact_constraints=[CategoryDraft(value=TopicCode.FRAGRANCE)],
        exact_issues=[],
        semantic=_proposal(topic=TopicCode.FRAGRANCE),
    )
    with_none_context = merge_intent_signals(
        message="推荐香水",
        exact_constraints=[CategoryDraft(value=TopicCode.FRAGRANCE)],
        exact_issues=[],
        semantic=_proposal(topic=TopicCode.FRAGRANCE),
        context=None,
    )

    assert without_context.model_dump() == with_none_context.model_dump()


def test_session_context_fills_topic_only_when_both_lanes_are_empty() -> None:
    merged = merge_intent_signals(
        message="第二个怎么样",
        exact_constraints=[],
        exact_issues=[],
        semantic=_proposal(topic=None, confidence=0.95),
        context=_context(active_topic=TopicCode.SUNSCREEN),
    )

    assert merged.topic is TopicCode.SUNSCREEN
    assert [
        item.value
        for item in merged.exact_constraints
        if isinstance(item, CategoryDraft)
    ] == [TopicCode.SUNSCREEN]
    context_trace = [
        item
        for item in merged.signal_trace
        if item.field == "topic" and item.resolution == "context_fills"
    ]
    assert context_trace
    assert context_trace[0].semantic_value == "sunscreen"


def test_context_never_overrides_current_turn_semantic_topic() -> None:
    merged = merge_intent_signals(
        message="夏天香水",
        exact_constraints=[],
        exact_issues=[],
        semantic=_proposal(topic=TopicCode.FRAGRANCE),
        context=_context(active_topic=TopicCode.SUNSCREEN),
    )

    assert merged.topic is TopicCode.FRAGRANCE
    assert not any(
        item.resolution == "context_fills"
        for item in merged.signal_trace
    )


def test_context_never_overrides_exact_hard_topic() -> None:
    merged = merge_intent_signals(
        message="推荐防晒",
        exact_constraints=[CategoryDraft(value=TopicCode.SUNSCREEN)],
        exact_issues=[],
        semantic=_proposal(topic=None, confidence=0.95),
        context=_context(active_topic=TopicCode.FRAGRANCE),
    )

    assert merged.topic is TopicCode.SUNSCREEN
    assert not any(
        item.resolution == "context_fills"
        for item in merged.signal_trace
    )


def test_context_cannot_revive_a_hard_excluded_topic() -> None:
    merged = merge_intent_signals(
        message="不要所有的香水",
        exact_constraints=[],
        exact_issues=[],
        semantic=_proposal(topic=None, confidence=0.95),
        context=_context(active_topic=TopicCode.FRAGRANCE),
    )

    assert not any(
        isinstance(item, CategoryDraft) and item.value is TopicCode.FRAGRANCE
        for item in merged.exact_constraints
    )


def test_context_does_not_touch_exact_hard_constraints_order() -> None:
    exact = [
        BudgetDraft(minimum=None, maximum=Decimal("500")),
        ExclusionDraft(value="酒精"),
    ]
    before = [item.model_dump_json() for item in exact]

    merged = merge_intent_signals(
        message="第二个",
        exact_constraints=exact,
        exact_issues=[],
        semantic=_proposal(topic=None, confidence=0.95),
        context=_context(active_topic=TopicCode.SUNSCREEN),
    )

    assert [
        item.model_dump_json()
        for item in merged.exact_constraints[: len(exact)]
    ] == before


def test_raw_context_payload_cannot_bypass_typed_contract() -> None:
    with pytest.raises(TypeError, match="SemanticContext"):
        merge_intent_signals(
            message="推荐香水",
            exact_constraints=[],
            exact_issues=[],
            semantic=_proposal(),
            context={"active_topic": "fragrance"},  # type: ignore[arg-type]
        )


def test_context_result_still_passes_strict_validation() -> None:
    from app.guide.understanding.contracts import StructuredUnderstanding

    merged = merge_intent_signals(
        message="第二个",
        exact_constraints=[],
        exact_issues=[],
        semantic=_proposal(topic=None, confidence=0.95),
        context=_context(active_topic=TopicCode.SUNSCREEN),
    )
    assert StructuredUnderstanding.model_validate(
        merged.model_dump(),
        strict=True,
    ) == merged
    assert merged.goal is UnderstandingGoal.RECOMMENDATION


def test_context_constraints_are_merged_before_task_planning() -> None:
    merged = merge_intent_signals(
        message="继续推荐防晒",
        exact_constraints=[CategoryDraft(value=TopicCode.SUNSCREEN)],
        exact_issues=[],
        semantic=_proposal(topic=TopicCode.SUNSCREEN),
    )

    resolved = merge_context_signals(
        merged,
        signals=(
            ContextConstraintSignal(
                source="session",
                constraint=BudgetDraft(
                    minimum=None,
                    maximum=Decimal("500"),
                ),
            ),
            ContextConstraintSignal(
                source="profile",
                constraint=SkinDraft(value=SkinTarget.DRY),
            ),
            ContextConstraintSignal(
                source="profile",
                constraint=ExclusionDraft(value="酒精"),
            ),
        ),
    )

    assert any(
        isinstance(item, BudgetDraft)
        and item.maximum == Decimal("500")
        for item in resolved.exact_constraints
    )
    assert any(
        isinstance(item, SkinDraft) and item.value is SkinTarget.DRY
        for item in resolved.exact_constraints
    )
    assert any(
        isinstance(item, ExclusionDraft) and item.value == "酒精"
        for item in resolved.exact_constraints
    )
    assert {
        (item.field, item.resolution)
        for item in resolved.signal_trace
    } >= {
        ("context.budget.session", "context_fills"),
        ("context.skin.profile", "context_fills"),
        ("context.exclude.profile", "context_fills"),
    }


def test_current_exact_skin_wins_over_session_and_profile_context() -> None:
    merged = merge_intent_signals(
        message="油皮继续推荐防晒",
        exact_constraints=[
            CategoryDraft(value=TopicCode.SUNSCREEN),
            SkinDraft(value=SkinTarget.OILY),
        ],
        exact_issues=[],
        semantic=_proposal(topic=TopicCode.SUNSCREEN),
    )

    resolved = merge_context_signals(
        merged,
        signals=(
            ContextConstraintSignal(
                source="session",
                constraint=SkinDraft(value=SkinTarget.SENSITIVE),
            ),
            ContextConstraintSignal(
                source="profile",
                constraint=SkinDraft(value=SkinTarget.DRY),
            ),
        ),
    )

    skins = [
        item.value
        for item in resolved.exact_constraints
        if isinstance(item, SkinDraft)
    ]
    assert skins == [SkinTarget.OILY]
    assert any(
        item.field == "context.skin.session"
        and item.resolution == "exact_wins"
        for item in resolved.signal_trace
    )
