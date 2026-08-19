from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from inspect import signature
from threading import Barrier, Event

import pytest

from app.guide.intent.task_planning import plan_task
from app.guide.understanding.contracts import CategoryDraft, TopicCode
from app.guide.understanding.parallel_understanding import (
    ParallelUnderstanding,
)
from app.guide.understanding.semantic_contracts import (
    SemanticContext,
    SemanticGoal,
    SemanticIntentProposal,
)


def _empty_context() -> SemanticContext:
    return SemanticContext(
        conversation_version=0,
        active_topic=None,
        visible_candidate_count=0,
        confirmed_profile_fields=(),
    )


def _proposal(
    *,
    topic: TopicCode | None = TopicCode.FRAGRANCE,
    goal: SemanticGoal = SemanticGoal.RECOMMENDATION,
    confidence: float = 0.96,
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


class StaticSemanticPort:
    def __init__(self, proposal: SemanticIntentProposal) -> None:
        self.proposal = proposal
        self.calls = 0

    def propose(
        self,
        message: str,
        context: SemanticContext,
    ) -> SemanticIntentProposal:
        del message, context
        self.calls += 1
        return self.proposal


class FailingSemanticPort:
    def __init__(self) -> None:
        self.calls = 0

    def propose(
        self,
        message: str,
        context: SemanticContext,
    ) -> SemanticIntentProposal:
        del message, context
        self.calls += 1
        raise RuntimeError("semantic provider unavailable")


class BarrierSemanticPort:
    def __init__(self, proposal: SemanticIntentProposal) -> None:
        self.proposal = proposal
        self.started = Event()
        self.release = Barrier(2)

    def propose(
        self,
        message: str,
        context: SemanticContext,
    ) -> SemanticIntentProposal:
        del message, context
        self.started.set()
        self.release.wait(timeout=2)
        return self.proposal


def test_exact_lane_survives_provider_failure() -> None:
    semantic = FailingSemanticPort()

    result = ParallelUnderstanding(semantic=semantic).understand(
        "500元内推荐防晒",
        context=_empty_context(),
    )

    # The exact hard signals survive the provider failure and are never lost.
    assert result.topic is TopicCode.SUNSCREEN
    assert any(
        isinstance(item, CategoryDraft) and item.value is TopicCode.SUNSCREEN
        for item in result.exact_constraints
    )
    assert semantic.calls == 1
    assert any(
        item.resolution == "semantic_unavailable"
        for item in result.signal_trace
    )


@pytest.mark.parametrize(
    "message",
    (
        "推荐防晒",
        "对比防晒",
        "防晒适合我吗",
        "防晒有哪些成分",
    ),
)
def test_ordinary_text_clarifies_when_provider_fails(
    message: str,
) -> None:
    semantic = FailingSemanticPort()

    result = ParallelUnderstanding(semantic=semantic).understand(
        message,
        context=_empty_context(),
    )
    task = plan_task(result)

    assert result.topic is TopicCode.SUNSCREEN
    assert result.uncertainties
    assert task.mode == "clarify"
    assert task.required_evidence == []
    assert any(
        item.resolution == "semantic_unavailable"
        for item in result.signal_trace
    )


def test_complex_request_clarifies_when_provider_fails() -> None:
    semantic = FailingSemanticPort()

    result = ParallelUnderstanding(semantic=semantic).understand(
        "给我来点那个适合夏天的",
        context=_empty_context(),
    )

    assert result.uncertainties
    assert any(
        item.resolution == "semantic_unavailable"
        for item in result.signal_trace
    )


def test_semantic_topic_fills_open_request() -> None:
    semantic = StaticSemanticPort(_proposal(topic=TopicCode.FRAGRANCE))

    result = ParallelUnderstanding(semantic=semantic).understand(
        "夏天涂的味道好闻的东西",
        context=_empty_context(),
    )

    assert result.topic is TopicCode.FRAGRANCE
    assert semantic.calls == 1


def test_semantic_future_starts_before_exact_lane_completes() -> None:
    semantic = BarrierSemanticPort(_proposal(topic=TopicCode.SUNSCREEN))
    understanding = ParallelUnderstanding(semantic=semantic)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            understanding.understand,
            "500元内推荐防晒",
            context=_empty_context(),
        )
        assert semantic.started.wait(timeout=2)
        semantic.release.wait(timeout=2)
        result = future.result(timeout=5)

    assert result.topic is TopicCode.SUNSCREEN


@pytest.mark.parametrize(
    "message",
    (
        "推荐防晒",
        "对比防晒",
        "防晒适合我吗",
        "防晒有哪些成分",
        "500元内推荐防晒",
        "油敏肌防晒",
        "第二款防晒",
        "第二张防晒",
    ),
)
def test_semantic_skip_without_closed_exact_proof_clarifies(
    message: str,
) -> None:
    semantic = FailingSemanticPort()

    result = ParallelUnderstanding(semantic=semantic).understand(
        message,
        context=_empty_context(),
        semantic_required=False,
    )
    task = plan_task(result)

    assert semantic.calls == 0
    assert result.goal is SemanticGoal.CLARIFICATION
    assert result.topic is TopicCode.SUNSCREEN
    assert result.uncertainties
    assert task.mode == "clarify"
    assert task.required_evidence == []
    assert any(
        item.resolution == "semantic_skipped_by_contract"
        for item in result.signal_trace
    )


@pytest.mark.parametrize(
    "message",
    (
        "后来改选洁面，对比一下",
        "后来改选洁面，适合我吗",
        "后来改选洁面，有哪些成分",
        "后来改选洁面对比一下",
        "后来改选洁面compare",
        "后来改选洁面123",
    ),
)
def test_closed_revision_with_open_goal_clarifies(message: str) -> None:
    semantic = FailingSemanticPort()

    result = ParallelUnderstanding(semantic=semantic).understand(
        message,
        context=_empty_context(),
        semantic_required=False,
    )
    task = plan_task(result)

    assert semantic.calls == 0
    assert result.goal is SemanticGoal.CLARIFICATION
    assert result.topic is TopicCode.CLEANSER
    assert result.uncertainties
    assert task.mode == "clarify"
    assert task.required_evidence == []


def test_pure_closed_revision_control_can_skip_semantic() -> None:
    semantic = FailingSemanticPort()

    result = ParallelUnderstanding(semantic=semantic).understand(
        "后来改选洁面！！！",
        context=_empty_context(),
        semantic_required=False,
    )
    task = plan_task(result)

    # Protocol-closed typed operations must never touch the model.
    assert semantic.calls == 0
    assert result.topic is TopicCode.CLEANSER
    assert result.uncertainties == []
    assert task.mode == "recommend"
    assert any(
        item.resolution == "semantic_skipped_by_contract"
        for item in result.signal_trace
    )


def test_semantic_required_true_by_default_calls_provider() -> None:
    semantic = StaticSemanticPort(_proposal(topic=TopicCode.SUNSCREEN))

    ParallelUnderstanding(semantic=semantic).understand(
        "推荐防晒",
        context=_empty_context(),
    )

    assert semantic.calls == 1


def test_provider_failure_never_falls_back_to_legacy_understanding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.guide.understanding.parallel_understanding as module

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("parallel understanding must not call legacy path")

    if hasattr(module, "understand_text"):
        monkeypatch.setattr(module, "understand_text", forbidden)

    semantic = FailingSemanticPort()
    result = ParallelUnderstanding(semantic=semantic).understand(
        "500元内推荐防晒",
        context=_empty_context(),
    )
    assert result.topic is TopicCode.SUNSCREEN


def test_coordinator_owns_only_the_semantic_port() -> None:
    semantic = StaticSemanticPort(_proposal(topic=TopicCode.SUNSCREEN))
    understanding = ParallelUnderstanding(semantic=semantic)

    assert tuple(signature(ParallelUnderstanding).parameters) == ("semantic",)
    assert vars(understanding) == {"_semantic": semantic}
    assert not hasattr(ParallelUnderstanding, "_cache_get")
    assert not hasattr(ParallelUnderstanding, "_cache_put")
