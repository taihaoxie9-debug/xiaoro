from __future__ import annotations

from app.guide.adapters.llm.contracts import (
    SemanticProviderFailure,
    SemanticProviderFailureCode,
)
from app.guide.intent.task_planning import plan_task
from app.guide.understanding.contracts import TopicCode
from app.guide.understanding.parallel_understanding import (
    ParallelUnderstanding,
)
from app.guide.understanding.semantic_contracts import SemanticContext


def _context() -> SemanticContext:
    return SemanticContext(
        conversation_version=1,
        active_topic=TopicCode.SUNSCREEN,
        visible_candidate_count=1,
        focused_candidate_ordinal=1,
        confirmed_profile_fields=(),
    )


class RouteSuccessDetailFailurePort:
    def propose(self, message: str, context: SemanticContext):
        del message, context
        raise SemanticProviderFailure(
            SemanticProviderFailureCode.INVALID_OUTPUT
        )


def test_detail_failure_never_enters_task_plan_as_partial_semantics() -> None:
    result = ParallelUnderstanding(
        semantic=RouteSuccessDetailFailurePort()
    ).understand(
        "它适合我吗",
        context=_context(),
    )
    task = plan_task(result)

    assert task.mode == "clarify"
    assert result.semantic_proposals == []
    assert any(
        item.resolution == "semantic_unavailable"
        for item in result.signal_trace
    )


def test_two_stage_port_still_uses_the_only_merger_once(
    monkeypatch,
) -> None:
    import app.guide.understanding.parallel_understanding as module

    calls = 0
    real_merge = module.merge_intent_signals

    def counted_merge(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real_merge(*args, **kwargs)

    monkeypatch.setattr(module, "merge_intent_signals", counted_merge)

    ParallelUnderstanding(
        semantic=RouteSuccessDetailFailurePort()
    ).understand(
        "预算300以内推荐防晒",
        context=_context(),
    )

    assert calls == 1
