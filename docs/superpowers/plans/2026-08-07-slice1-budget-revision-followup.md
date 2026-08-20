# Slice 1.5 Budget Revision Follow-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为干净文本护肤运行时增加服务端结构化查询上下文，可靠支持“预算降到 100 元呢”并继承上一轮品类、肤质和功效后重新筛选。

**Architecture:** `ConversationSnapshot` 保存最近成功推荐的强类型 `RecommendationQueryContext` 和页面可见候选。Understanding 只解析明确预算上限修改，Intent 只替换预算约束，Application 重新执行现有 retrieval、decision 和 presentation，并通过同一次 CAS 原子更新上下文与候选。

**Tech Stack:** Python 3.11, Pydantic 2.8.0, FastAPI 0.115.0, pytest 8.0.0, Playwright, typed SSE.

---

## 0. Execution Contract

- 最高事实源：
  `docs/superpowers/specs/2026-08-07-slice1-budget-revision-followup-design.md`
- 用户已确认主会话内联执行，不使用子代理。
- 每个 Task 必须执行 RED -> GREEN -> 相关回归 -> boundary -> commit。
- 不修改旧仓库 `/Users/bytedance/Desktop/xiaoro-shopping-master`。
- 不修改：
  - `app/main.py`
  - `app/api/v1/chat.py`
  - `app/services/**`
  - `app/database/**`
  - `data/canonical/**`
  - `app/guide/decision/deterministic_ranking.py`
- 不实现改肤质、成分排除追问、相对预算、预算区间、换一批、图片、长期画像、
  数据库、LLM 或 BGE。
- 排序内核 SHA 必须保持：
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`
- 既有锁定结果必须保持：

```text
防晒：[55, 57, 54, 51, 102, 53, 58, 56, 52, 26, 101]
修护精华：[91, 38]
第二款呢：[38]
哪个更便宜：[91]
```

- 新两轮锁定结果：

```text
500 元内敏感肌修护精华
-> [91, 38]
-> version 1

预算降到 100 元呢
-> [91]
-> INSUFFICIENT_FOR_WINNER
-> version 2
```

## 1. File Map

### Create: Query Context and Budget Revision

- `app/guide/application/query_context.py`
  - `TaskPlan` 与会话 query context 的显式双向转换。
- `app/guide/understanding/budget_revision_parsing.py`
  - 明确预算上限修改的确定性解析。
- `app/guide/intent/budget_revision_planning.py`
  - 版本校验、旧预算替换和完整条件合并。
- `app/guide/presentation/budget_revision_response.py`
  - 预算修改确认和证据诚实文案。
- `tests/guide/application/test_query_context.py`
- `tests/guide/understanding/test_budget_revision_parsing.py`
- `tests/guide/intent/test_budget_revision_planning.py`
- `tests/guide/presentation/test_budget_revision_response.py`

### Modify: Contracts and State

- `app/guide/feedback/contracts.py`
- `app/guide/feedback/__init__.py`
- `app/guide/understanding/contracts.py`
- `app/guide/understanding/__init__.py`
- `app/guide/intent/contracts.py`
- `app/guide/intent/__init__.py`
- `app/guide/presentation/sse_events.py`
- `app/guide/application/text_recommendation_flow.py`

### Modify: Contract and Layer Tests

- `tests/guide/feedback/test_conversation_state_contracts.py`
- `tests/guide/adapters/state/test_in_memory_conversation_state.py`
- `tests/guide/decision/test_followup.py`
- `tests/guide/intent/test_followup_planning.py`
- `tests/guide/presentation/test_followup_response.py`
- `tests/guide/application/test_text_recommendation_flow.py`
- `tests/guide/test_public_contracts.py`

### Modify: Runtime and Release Gates

- `app/guide_runtime/app.py`
- `tests/guide/runtime/test_runtime_http.py`
- `tests/guide/runtime/test_composition.py`
- `tests/guide/application/test_slice1_backend_gate.py`
- `tools/guide_gates/runtime_browser_smoke.py`
- `docs/superpowers/plans/2026-08-07-slice1-budget-revision-followup.md`

---

### Task 1: Add the Strict Recommendation Query Context Contract

**Files:**
- Modify: `app/guide/feedback/contracts.py`
- Modify: `app/guide/feedback/__init__.py`
- Modify: `tests/guide/feedback/test_conversation_state_contracts.py`
- Modify: `tests/guide/test_public_contracts.py`

- [x] **Step 1: Write failing query-context contract tests**

Add to `tests/guide/feedback/test_conversation_state_contracts.py`:

```python
from decimal import Decimal

from app.guide.feedback.contracts import RecommendationQueryContext


def test_query_context_keeps_only_normalized_decision_constraints() -> None:
    context = RecommendationQueryContext(
        category="serum",
        budget_minimum=None,
        budget_maximum=Decimal("500"),
        skin="sensitive",
        efficacy="repair",
        exclusions=["酒精"],
    )

    assert context.category == "serum"
    assert context.budget_maximum == Decimal("500")
    assert context.skin == "sensitive"
    assert context.efficacy == "repair"
    assert context.exclusions == ["酒精"]


def test_query_context_allows_no_budget_but_rejects_invalid_bounds() -> None:
    no_budget = RecommendationQueryContext(
        category="sunscreen",
        budget_minimum=None,
        budget_maximum=None,
        skin=None,
        efficacy=None,
        exclusions=[],
    )
    assert no_budget.budget_maximum is None

    with pytest.raises(ValidationError, match="budget"):
        RecommendationQueryContext(
            category="serum",
            budget_minimum=None,
            budget_maximum=Decimal("0"),
            skin="sensitive",
            efficacy="repair",
            exclusions=[],
        )
    with pytest.raises(ValidationError, match="budget"):
        RecommendationQueryContext(
            category="serum",
            budget_minimum=Decimal("500"),
            budget_maximum=Decimal("100"),
            skin="sensitive",
            efficacy="repair",
            exclusions=[],
        )


def test_query_context_rejects_duplicate_or_empty_exclusions() -> None:
    with pytest.raises(ValidationError, match="exclusions"):
        RecommendationQueryContext(
            category="sunscreen",
            budget_minimum=None,
            budget_maximum=None,
            skin=None,
            efficacy=None,
            exclusions=["酒精", "酒精"],
        )
    with pytest.raises(ValidationError):
        RecommendationQueryContext(
            category="sunscreen",
            budget_minimum=None,
            budget_maximum=None,
            skin=None,
            efficacy=None,
            exclusions=[""],
        )


@pytest.mark.parametrize(
    "forbidden_field",
    ["raw_message", "candidate_ids", "product_facts", "score"],
)
def test_query_context_rejects_raw_or_privileged_fields(
    forbidden_field: str,
) -> None:
    payload = {
        "category": "serum",
        "budget_minimum": None,
        "budget_maximum": Decimal("500"),
        "skin": "sensitive",
        "efficacy": "repair",
        "exclusions": [],
        forbidden_field: "not allowed",
    }

    with pytest.raises(
        ValidationError,
        match="Extra inputs are not permitted",
    ):
        RecommendationQueryContext.model_validate(payload)
```

- [x] **Step 2: Add the contract to the public-contract RED gate**

In `tests/guide/test_public_contracts.py`, add immediately after the existing
`"FeedbackEventRef": "feedback",` entry:

```python
"RecommendationQueryContext": "feedback",
```

Add to `valid_payloads()`:

```python
"RecommendationQueryContext": {
    "category": "serum",
    "budget_minimum": None,
    "budget_maximum": Decimal("500"),
    "skin": "sensitive",
    "efficacy": "repair",
    "exclusions": ["酒精"],
},
```

- [x] **Step 3: Run tests and verify RED**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/feedback/test_conversation_state_contracts.py \
  tests/guide/test_public_contracts.py
```

Expected: collection fails because `RecommendationQueryContext` does not exist.

- [x] **Step 4: Implement the strict query-context contract**

Update the existing import block in `app/guide/feedback/contracts.py` to include
`Decimal`, then add:

```python
from decimal import Decimal


StoredExclusion = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
    ),
]


class RecommendationQueryContext(_StrictContract):
    category: Literal["sunscreen", "serum"]
    budget_minimum: Decimal | None = None
    budget_maximum: Decimal | None = None
    skin: Literal[
        "oily_sensitive",
        "oily",
        "dry",
        "combination",
        "sensitive",
        "normal",
    ] | None = None
    efficacy: Literal["repair"] | None = None
    exclusions: list[StoredExclusion] = Field(
        default_factory=list,
        max_length=16,
    )

    @model_validator(mode="after")
    def validate_context(self) -> Self:
        bounds = [
            value
            for value in (
                self.budget_minimum,
                self.budget_maximum,
            )
            if value is not None
        ]
        if any(not value.is_finite() or value <= 0 for value in bounds):
            raise ValueError("budget bounds must be positive and finite")
        if (
            self.budget_minimum is not None
            and self.budget_maximum is not None
            and self.budget_minimum > self.budget_maximum
        ):
            raise ValueError("budget minimum exceeds maximum")
        if len(self.exclusions) != len(set(self.exclusions)):
            raise ValueError("exclusions must be unique")
        return self
```

Place this contract before `DisplayedCandidateRef` and
`ConversationSnapshot`. Do not add user text, product IDs, prices, scores or
arbitrary JSON fields.

- [x] **Step 5: Export the contract**

Update `app/guide/feedback/__init__.py`:

```python
from app.guide.feedback.contracts import (
    ConversationSnapshot,
    ConversationVersionRef,
    DisplayedCandidateRef,
    FeedbackEventRef,
    RecommendationQueryContext,
)

__all__ = [
    "ConversationSnapshot",
    "ConversationVersionRef",
    "DisplayedCandidateRef",
    "FeedbackEventRef",
    "RecommendationQueryContext",
]
```

- [x] **Step 6: Run focused tests and boundary**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/feedback/test_conversation_state_contracts.py \
  tests/guide/test_public_contracts.py
python3 app/guide/check_boundaries.py app/guide
git diff --check
```

Expected: selected tests pass, boundary reports zero violations, diff check is
clean.

- [x] **Step 7: Commit**

```bash
git add \
  app/guide/feedback/contracts.py \
  app/guide/feedback/__init__.py \
  tests/guide/feedback/test_conversation_state_contracts.py \
  tests/guide/test_public_contracts.py
git commit -m "feat(feedback): type recommendation query context"
```

---

### Task 2: Attach Query Context to Every Successful Snapshot

**Files:**
- Create: `app/guide/application/query_context.py`
- Create: `tests/guide/application/test_query_context.py`
- Modify: `app/guide/feedback/contracts.py`
- Modify: `app/guide/application/text_recommendation_flow.py`
- Modify: `tests/guide/feedback/test_conversation_state_contracts.py`
- Modify: `tests/guide/adapters/state/test_in_memory_conversation_state.py`
- Modify: `tests/guide/decision/test_followup.py`
- Modify: `tests/guide/intent/test_followup_planning.py`
- Modify: `tests/guide/presentation/test_followup_response.py`
- Modify: `tests/guide/application/test_text_recommendation_flow.py`
- Modify: `tests/guide/test_public_contracts.py`

- [x] **Step 1: Write failing TaskPlan-to-context conversion tests**

Create `tests/guide/application/test_query_context.py`:

```python
from decimal import Decimal

import pytest

from app.guide.application.query_context import (
    query_context_to_constraints,
    task_plan_to_query_context,
)
from app.guide.intent.contracts import (
    BudgetConstraint,
    CategoryConstraint,
    EfficacyConstraint,
    ExclusionConstraint,
    SkinConstraint,
)
from app.guide.intent.task_planning import plan_task
from app.guide.understanding.contracts import (
    EfficacyTarget,
    SkinTarget,
    TopicCode,
)
from app.guide.understanding.text_understanding import understand_text


def test_task_plan_round_trips_through_query_context() -> None:
    task = plan_task(
        understand_text(
            "300 到 500 元敏感肌不要酒精的修护精华"
        )
    )

    context = task_plan_to_query_context(task)
    restored = query_context_to_constraints(context)

    assert context.category == "serum"
    assert context.budget_minimum == Decimal("300")
    assert context.budget_maximum == Decimal("500")
    assert context.skin == "sensitive"
    assert context.efficacy == "repair"
    assert context.exclusions == ["酒精"]
    assert any(
        isinstance(item, CategoryConstraint)
        and item.value is TopicCode.SERUM
        for item in restored
    )
    assert any(
        isinstance(item, SkinConstraint)
        and item.value is SkinTarget.SENSITIVE
        for item in restored
    )
    assert any(
        isinstance(item, EfficacyConstraint)
        and item.value is EfficacyTarget.REPAIR
        for item in restored
    )
    assert any(
        isinstance(item, ExclusionConstraint)
        and item.value == "酒精"
        for item in restored
    )
    budget = next(
        item for item in restored
        if isinstance(item, BudgetConstraint)
    )
    assert budget.minimum == Decimal("300")
    assert budget.maximum == Decimal("500")


def test_query_context_conversion_returns_fresh_constraints() -> None:
    task = plan_task(understand_text("500 元内敏感肌修护精华"))
    context = task_plan_to_query_context(task)

    first = query_context_to_constraints(context)
    second = query_context_to_constraints(context)

    assert first == second
    assert first is not second
    assert all(left is not right for left, right in zip(first, second))


def test_clarify_task_cannot_be_saved_as_query_context() -> None:
    task = plan_task(understand_text("500 元以内"))

    with pytest.raises(ValueError, match="recommend"):
        task_plan_to_query_context(task)
```

- [x] **Step 2: Write failing snapshot integration tests**

In `tests/guide/application/test_text_recommendation_flow.py`, extend
`test_recommendation_saves_only_visible_candidates`:

```python
    assert snapshot.query_context.category == "sunscreen"
    assert snapshot.query_context.budget_maximum == 500
    assert snapshot.query_context.skin == "oily_sensitive"
```

Add:

```python
def test_candidate_followup_preserves_query_context(
    orchestrator,
    conversation_state,
) -> None:
    list(orchestrator.stream(_turn("500 元内敏感肌修护精华")))
    before = conversation_state.load("s-1")

    events = list(
        orchestrator.stream(
            _turn("第二款呢", conversation_version=1)
        )
    )
    after = conversation_state.load("s-1")

    assert before is not None
    assert after is not None
    assert after.query_context == before.query_context
    assert after.version == 2
    assert events[-1].data.conversation_version == 2
```

In `tests/guide/feedback/test_conversation_state_contracts.py`, add
`query_context` to valid snapshots and assert omission fails:

```python
def test_snapshot_requires_query_context() -> None:
    with pytest.raises(ValidationError, match="query_context"):
        ConversationSnapshot(
            session_id="session-1",
            version=1,
            candidates=[candidate(91, 1)],
        )
```

- [x] **Step 3: Run tests and verify RED**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/application/test_query_context.py \
  tests/guide/feedback/test_conversation_state_contracts.py \
  tests/guide/application/test_text_recommendation_flow.py
```

Expected: conversion module is missing and `ConversationSnapshot` has no
`query_context`.

- [x] **Step 4: Implement explicit conversion helpers**

Create `app/guide/application/query_context.py`:

```python
from __future__ import annotations

from app.guide.feedback.contracts import RecommendationQueryContext
from app.guide.intent.contracts import (
    BudgetConstraint,
    CategoryConstraint,
    EfficacyConstraint,
    ExclusionConstraint,
    SkinConstraint,
    TaskConstraint,
    TaskPlan,
)
from app.guide.understanding.contracts import (
    EfficacyTarget,
    SkinTarget,
    TopicCode,
)


def task_plan_to_query_context(
    task: TaskPlan,
) -> RecommendationQueryContext:
    if task.mode != "recommend":
        raise ValueError("query context requires recommend task")
    category = _one_or_none(task.constraints, CategoryConstraint)
    if category is None:
        raise ValueError("query context requires category")
    budget = _one_or_none(task.constraints, BudgetConstraint)
    skin = _one_or_none(task.constraints, SkinConstraint)
    efficacy = _one_or_none(task.constraints, EfficacyConstraint)
    exclusions = [
        item.value
        for item in task.constraints
        if isinstance(item, ExclusionConstraint)
    ]
    return RecommendationQueryContext(
        category=category.value.value,
        budget_minimum=budget.minimum if budget else None,
        budget_maximum=budget.maximum if budget else None,
        skin=skin.value.value if skin else None,
        efficacy=efficacy.value.value if efficacy else None,
        exclusions=exclusions,
    )


def query_context_to_constraints(
    context: RecommendationQueryContext,
) -> list[TaskConstraint]:
    constraints: list[TaskConstraint] = [
        CategoryConstraint(value=TopicCode(context.category))
    ]
    if (
        context.budget_minimum is not None
        or context.budget_maximum is not None
    ):
        constraints.append(
            BudgetConstraint(
                minimum=context.budget_minimum,
                maximum=context.budget_maximum,
            )
        )
    if context.skin is not None:
        constraints.append(
            SkinConstraint(value=SkinTarget(context.skin))
        )
    if context.efficacy is not None:
        constraints.append(
            EfficacyConstraint(
                value=EfficacyTarget(context.efficacy)
            )
        )
    constraints.extend(
        ExclusionConstraint(value=value)
        for value in context.exclusions
    )
    return constraints


def _one_or_none(
    constraints: list[TaskConstraint],
    constraint_type: type,
):
    matches = [
        item for item in constraints
        if isinstance(item, constraint_type)
    ]
    if len(matches) > 1:
        raise ValueError(
            f"duplicate {constraint_type.__name__} constraints"
        )
    return matches[0] if matches else None
```

- [x] **Step 5: Require query context in snapshots**

In `app/guide/feedback/contracts.py`, update:

```python
class ConversationSnapshot(_StrictContract):
    session_id: SessionId
    version: int = Field(ge=1)
    query_context: RecommendationQueryContext
    candidates: list[DisplayedCandidateRef] = Field(
        min_length=1,
        max_length=3,
    )
```

- [x] **Step 6: Save context with visible candidates**

In `app/guide/application/text_recommendation_flow.py`, import
`task_plan_to_query_context`, pass the current task into `_visible_snapshot`,
and update the helper:

```python
from app.guide.application.query_context import (
    task_plan_to_query_context,
)
from app.guide.intent.contracts import (
    CategoryConstraint,
    FollowupPlan,
    TaskPlan,
)
```

At the save call:

```python
saved_snapshot = self._conversation_state.save(
    self._visible_snapshot(
        turn,
        list(plan.structured_events),
        task=task,
        version=expected_version + 1,
    ),
    expected_version=expected_version,
)
```

Update the helper:

```python
@staticmethod
def _visible_snapshot(
    turn: UserTurn,
    cards: list[ProductCard],
    *,
    task: TaskPlan,
    version: int,
) -> ConversationSnapshot:
    return ConversationSnapshot(
        session_id=turn.session_id,
        version=version,
        query_context=task_plan_to_query_context(task),
        candidates=[
            DisplayedCandidateRef(
                product_id=card.product_id,
                ordinal=index,
                skin_match=card.skin_match,
                matched_efficacies=list(card.matched_efficacies),
            )
            for index, card in enumerate(cards[:3], start=1)
        ],
    )
```

The existing follow-up `snapshot.model_copy(update={"version": ...})` must
remain unchanged so it preserves `query_context`.

- [x] **Step 7: Update every existing snapshot fixture**

For serum snapshots in:

- `tests/guide/feedback/test_conversation_state_contracts.py`
- `tests/guide/decision/test_followup.py`
- `tests/guide/intent/test_followup_planning.py`
- `tests/guide/presentation/test_followup_response.py`

import `RecommendationQueryContext`, add `from decimal import Decimal` in
files that do not already import it, and add:

```python
query_context=RecommendationQueryContext(
    category="serum",
    budget_minimum=None,
    budget_maximum=Decimal("500"),
    skin="sensitive",
    efficacy="repair",
    exclusions=[],
),
```

For `tests/guide/adapters/state/test_in_memory_conversation_state.py`, use:

```python
query_context=RecommendationQueryContext(
    category="serum",
    budget_minimum=None,
    budget_maximum=None,
    skin=None,
    efficacy="repair",
    exclusions=[],
),
```

Also import `Decimal` and `RecommendationQueryContext` in that file.

Add this field to the `ConversationSnapshot` payload in
`tests/guide/test_public_contracts.py`:

```python
"query_context": {
    "category": "serum",
    "budget_minimum": None,
    "budget_maximum": Decimal("500"),
    "skin": "sensitive",
    "efficacy": "repair",
    "exclusions": [],
},
```

- [x] **Step 8: Run focused and broad regressions**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/application/test_query_context.py \
  tests/guide/feedback \
  tests/guide/adapters/state \
  tests/guide/decision/test_followup.py \
  tests/guide/intent/test_followup_planning.py \
  tests/guide/presentation/test_followup_response.py \
  tests/guide/application \
  tests/guide/test_public_contracts.py
python3 app/guide/check_boundaries.py app/guide
git diff --check
```

Expected: all selected tests pass and boundary reports zero violations.

- [x] **Step 9: Commit**

```bash
git add \
  app/guide/application/query_context.py \
  app/guide/feedback/contracts.py \
  app/guide/application/text_recommendation_flow.py \
  tests/guide/application/test_query_context.py \
  tests/guide/feedback \
  tests/guide/adapters/state/test_in_memory_conversation_state.py \
  tests/guide/decision/test_followup.py \
  tests/guide/intent/test_followup_planning.py \
  tests/guide/presentation/test_followup_response.py \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/test_public_contracts.py
git commit -m "feat(application): persist recommendation query context"
```

---

### Task 3: Parse Only Explicit Budget Revisions

**Files:**
- Modify: `app/guide/understanding/contracts.py`
- Modify: `app/guide/understanding/__init__.py`
- Create: `app/guide/understanding/budget_revision_parsing.py`
- Create: `tests/guide/understanding/test_budget_revision_parsing.py`
- Modify: `tests/guide/test_public_contracts.py`

- [x] **Step 1: Write failing parser tests**

Create `tests/guide/understanding/test_budget_revision_parsing.py`:

```python
from decimal import Decimal

import pytest

from app.guide.understanding.budget_revision_parsing import (
    parse_budget_revision,
)


@pytest.mark.parametrize(
    "message",
    [
        "预算降到100元呢",
        "预算改成 100 元",
        "改成100元以内",
        "控制在 100 块以内",
    ],
)
def test_parses_explicit_budget_maximum_revision(message: str) -> None:
    draft = parse_budget_revision(message)

    assert draft is not None
    assert draft.maximum == Decimal("100")
    assert draft.issue is None


@pytest.mark.parametrize(
    ("message", "issue"),
    [
        ("预算改成0元", "invalid_budget"),
        ("预算改成-1元", "invalid_budget"),
        ("预算改成一百元", "unsupported_budget_revision"),
        ("预算改成100到200元", "unsupported_budget_revision"),
        ("预算改成100", "unsupported_budget_revision"),
        ("便宜一点", None),
        ("100元呢", None),
    ],
)
def test_budget_revision_is_fail_closed(
    message: str,
    issue: str | None,
) -> None:
    draft = parse_budget_revision(message)

    if issue is None:
        assert draft is None
    else:
        assert draft is not None
        assert draft.maximum is None
        assert draft.issue == issue


def test_explicit_category_query_wins_over_revision_parser() -> None:
    assert parse_budget_revision(
        "预算改成100元的修护精华"
    ) is None
    assert parse_budget_revision(
        "预算改成100元的防晒"
    ) is None


def test_candidate_followups_are_not_budget_revisions() -> None:
    assert parse_budget_revision("第二款呢") is None
    assert parse_budget_revision("哪个更便宜") is None
```

- [x] **Step 2: Add failing strict-contract coverage**

In `tests/guide/test_public_contracts.py`, add:

```python
"BudgetRevisionDraft": "understanding",
```

and:

```python
"BudgetRevisionDraft": {
    "maximum": Decimal("100"),
    "issue": None,
},
```

- [x] **Step 3: Run tests and verify RED**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/understanding/test_budget_revision_parsing.py \
  tests/guide/test_public_contracts.py
```

Expected: collection fails because the draft and parser do not exist.

- [x] **Step 4: Add the budget revision draft**

In `app/guide/understanding/contracts.py`, add:

```python
class BudgetRevisionDraft(_StrictContract):
    maximum: Decimal | None = None
    issue: Literal[
        "invalid_budget",
        "unsupported_budget_revision",
    ] | None = None

    @model_validator(mode="after")
    def validate_revision(self) -> Self:
        if self.issue is not None:
            if self.maximum is not None:
                raise ValueError("budget revision issue forbids maximum")
            return self
        if self.maximum is None:
            raise ValueError("budget revision requires maximum or issue")
        if not self.maximum.is_finite() or self.maximum <= 0:
            raise ValueError("budget revision maximum must be positive")
        return self
```

- [x] **Step 5: Implement deterministic parsing**

Create `app/guide/understanding/budget_revision_parsing.py`:

```python
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app.guide.understanding.contracts import (
    BudgetRevisionDraft,
    CategoryDraft,
)
from app.guide.understanding.exact_parsing import (
    parse_exact_constraints,
)


_REVISION_SIGNAL = re.compile(
    r"(?:预算\s*(?:降到|改成|调整到)|改成|控制在)"
)
_SUPPORTED_REVISION = re.compile(
    r"^\s*"
    r"(?:(?:预算\s*)?(?:降到|改成|调整到)|控制在)"
    r"\s*(?P<maximum>-?\d+(?:\.\d+)?)\s*(?:元|块)"
    r"(?:\s*(?:以内|以下))?\s*(?:呢|吗)?\s*$"
)


def parse_budget_revision(
    message: str,
) -> BudgetRevisionDraft | None:
    text = message.strip()
    constraints, _ = parse_exact_constraints(text)
    if any(isinstance(item, CategoryDraft) for item in constraints):
        return None
    if not _REVISION_SIGNAL.search(text):
        return None
    match = _SUPPORTED_REVISION.fullmatch(text)
    if match is None:
        return BudgetRevisionDraft(
            issue="unsupported_budget_revision"
        )
    try:
        maximum = Decimal(match.group("maximum"))
    except InvalidOperation:
        return BudgetRevisionDraft(issue="invalid_budget")
    if not maximum.is_finite() or maximum <= 0:
        return BudgetRevisionDraft(issue="invalid_budget")
    return BudgetRevisionDraft(maximum=maximum)
```

- [x] **Step 6: Export and verify**

Update `app/guide/understanding/__init__.py`:

```python
from app.guide.understanding.contracts import (
    BudgetRevisionDraft,
    EfficacyTarget,
    FollowupAction,
    FollowupDraft,
    ImageBundle,
    ImageObservation,
    StructuredUnderstanding,
    TopicCode,
)

__all__ = [
    "BudgetRevisionDraft",
    "EfficacyTarget",
    "FollowupAction",
    "FollowupDraft",
    "ImageBundle",
    "ImageObservation",
    "StructuredUnderstanding",
    "TopicCode",
]
```

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/understanding \
  tests/guide/test_public_contracts.py
python3 app/guide/check_boundaries.py app/guide
git diff --check
```

Expected: all selected tests pass.

- [x] **Step 7: Commit**

```bash
git add \
  app/guide/understanding/contracts.py \
  app/guide/understanding/__init__.py \
  app/guide/understanding/budget_revision_parsing.py \
  tests/guide/understanding/test_budget_revision_parsing.py \
  tests/guide/test_public_contracts.py
git commit -m "feat(understanding): parse budget revisions"
```

---

### Task 4: Plan a Versioned Budget Replacement

**Files:**
- Modify: `app/guide/intent/contracts.py`
- Modify: `app/guide/intent/__init__.py`
- Create: `app/guide/intent/budget_revision_planning.py`
- Create: `tests/guide/intent/test_budget_revision_planning.py`
- Modify: `tests/guide/test_public_contracts.py`

- [x] **Step 1: Write failing planning tests**

Create `tests/guide/intent/test_budget_revision_planning.py`:

```python
from decimal import Decimal

from app.guide.application.query_context import (
    query_context_to_constraints,
)
from app.guide.feedback.contracts import RecommendationQueryContext
from app.guide.intent.budget_revision_planning import (
    plan_budget_revision,
)
from app.guide.intent.contracts import (
    BudgetConstraint,
    CategoryConstraint,
    EfficacyConstraint,
    ExclusionConstraint,
    SkinConstraint,
)
from app.guide.understanding.budget_revision_parsing import (
    parse_budget_revision,
)
from app.guide.understanding.contracts import (
    EfficacyTarget,
    SkinTarget,
    TopicCode,
)


def base_constraints():
    return query_context_to_constraints(
        RecommendationQueryContext(
            category="serum",
            budget_minimum=None,
            budget_maximum=Decimal("500"),
            skin="sensitive",
            efficacy="repair",
            exclusions=["酒精"],
        )
    )


def test_replaces_budget_and_preserves_other_constraints() -> None:
    original = base_constraints()
    plan = plan_budget_revision(
        parse_budget_revision("预算降到100元呢"),
        base_constraints=original,
        request_version=1,
        snapshot_version=1,
    )

    assert plan is not None
    assert plan.mode == "revise"
    budgets = [
        item for item in plan.constraints
        if isinstance(item, BudgetConstraint)
    ]
    assert len(budgets) == 1
    assert budgets[0].minimum is None
    assert budgets[0].maximum == Decimal("100")
    assert any(
        isinstance(item, CategoryConstraint)
        and item.value is TopicCode.SERUM
        for item in plan.constraints
    )
    assert any(
        isinstance(item, SkinConstraint)
        and item.value is SkinTarget.SENSITIVE
        for item in plan.constraints
    )
    assert any(
        isinstance(item, EfficacyConstraint)
        and item.value is EfficacyTarget.REPAIR
        for item in plan.constraints
    )
    assert any(
        isinstance(item, ExclusionConstraint)
        and item.value == "酒精"
        for item in plan.constraints
    )
    original_budget = next(
        item for item in original
        if isinstance(item, BudgetConstraint)
    )
    assert original_budget.maximum == Decimal("500")
    assert all(
        planned is not existing
        for planned in plan.constraints
        for existing in original
        if planned.kind == existing.kind
    )


def test_revision_clears_old_budget_minimum() -> None:
    constraints = base_constraints()
    old_budget = next(
        item for item in constraints
        if isinstance(item, BudgetConstraint)
    )
    old_budget.minimum = Decimal("300")

    plan = plan_budget_revision(
        parse_budget_revision("预算改成100元"),
        base_constraints=constraints,
        request_version=1,
        snapshot_version=1,
    )

    budget = next(
        item for item in plan.constraints
        if isinstance(item, BudgetConstraint)
    )
    assert budget.minimum is None
    assert budget.maximum == Decimal("100")


def test_missing_snapshot_and_stale_version_clarify() -> None:
    missing = plan_budget_revision(
        parse_budget_revision("预算降到100元呢"),
        base_constraints=None,
        request_version=0,
        snapshot_version=None,
    )
    assert missing.mode == "clarify"
    assert "完整推荐" in missing.clarification

    stale = plan_budget_revision(
        parse_budget_revision("预算降到100元呢"),
        base_constraints=base_constraints(),
        request_version=0,
        snapshot_version=1,
    )
    assert stale.mode == "clarify"
    assert "状态已变化" in stale.clarification


def test_invalid_and_unsupported_revision_clarify() -> None:
    invalid = plan_budget_revision(
        parse_budget_revision("预算改成0元"),
        base_constraints=base_constraints(),
        request_version=1,
        snapshot_version=1,
    )
    assert invalid.mode == "clarify"
    assert "大于 0" in invalid.clarification

    unsupported = plan_budget_revision(
        parse_budget_revision("预算改成100到200元"),
        base_constraints=base_constraints(),
        request_version=1,
        snapshot_version=1,
    )
    assert unsupported.mode == "clarify"
    assert "明确上限" in unsupported.clarification


def test_none_draft_is_not_a_revision_plan() -> None:
    assert plan_budget_revision(
        None,
        base_constraints=base_constraints(),
        request_version=1,
        snapshot_version=1,
    ) is None
```

- [x] **Step 2: Add failing public-contract coverage**

In `tests/guide/test_public_contracts.py`, add:

```python
"BudgetRevisionPlan": "intent",
```

and:

```python
"BudgetRevisionPlan": {
    "mode": "revise",
    "constraints": [
        {
            "kind": "category",
            "value": importlib.import_module(
                "app.guide.understanding"
            ).TopicCode.SERUM,
        },
        {
            "kind": "budget",
            "minimum": None,
            "maximum": Decimal("100"),
        },
        {
            "kind": "skin",
            "value": importlib.import_module(
                "app.guide.understanding"
            ).SkinTarget.SENSITIVE,
        },
        {
            "kind": "efficacy",
            "value": importlib.import_module(
                "app.guide.understanding"
            ).EfficacyTarget.REPAIR,
        },
    ],
    "clarification": None,
},
```

Also update `app/guide/understanding/__init__.py` to import `SkinTarget` and
place `"SkinTarget"` in `__all__`, because the public payload must use the
exact enum instead of a coerced string:

```python
from app.guide.understanding.contracts import (
    BudgetRevisionDraft,
    EfficacyTarget,
    FollowupAction,
    FollowupDraft,
    ImageBundle,
    ImageObservation,
    SkinTarget,
    StructuredUnderstanding,
    TopicCode,
)

__all__ = [
    "BudgetRevisionDraft",
    "EfficacyTarget",
    "FollowupAction",
    "FollowupDraft",
    "ImageBundle",
    "ImageObservation",
    "SkinTarget",
    "StructuredUnderstanding",
    "TopicCode",
]
```

- [x] **Step 3: Run tests and verify RED**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/intent/test_budget_revision_planning.py \
  tests/guide/test_public_contracts.py
```

Expected: collection fails because `BudgetRevisionPlan` and planner do not
exist.

- [x] **Step 4: Add the strict revision plan**

In `app/guide/intent/contracts.py`, add:

```python
class BudgetRevisionPlan(_StrictContract):
    mode: Literal["revise", "clarify"]
    constraints: list[TaskConstraint]
    clarification: str | None = None

    @model_validator(mode="after")
    def validate_revision_mode(self) -> Self:
        if self.mode == "revise":
            if self.clarification is not None:
                raise ValueError("revise mode forbids clarification")
            if not self.constraints:
                raise ValueError("revise mode requires constraints")
        else:
            if not self.clarification:
                raise ValueError("clarify mode requires clarification")
            if self.constraints:
                raise ValueError("clarify mode forbids constraints")
        return self
```

- [x] **Step 5: Implement budget replacement planning**

Create `app/guide/intent/budget_revision_planning.py`:

```python
from __future__ import annotations

from app.guide.intent.contracts import (
    BudgetConstraint,
    BudgetRevisionPlan,
    TaskConstraint,
)
from app.guide.understanding.contracts import BudgetRevisionDraft


def plan_budget_revision(
    draft: BudgetRevisionDraft | None,
    *,
    base_constraints: list[TaskConstraint] | None,
    request_version: int,
    snapshot_version: int | None,
) -> BudgetRevisionPlan | None:
    if draft is None:
        return None
    if draft.issue == "invalid_budget":
        return BudgetRevisionPlan(
            mode="clarify",
            constraints=[],
            clarification=(
                "预算必须是大于 0 的阿拉伯数字。"
            ),
        )
    if draft.issue == "unsupported_budget_revision":
        return BudgetRevisionPlan(
            mode="clarify",
            constraints=[],
            clarification=(
                "当前预算追问先支持明确上限，"
                "例如“预算改成100元以内”。"
            ),
        )
    if base_constraints is None or snapshot_version is None:
        return BudgetRevisionPlan(
            mode="clarify",
            constraints=[],
            clarification=(
                "我找不到可继承的最近筛选条件，"
                "请先发起一次完整推荐。"
            ),
        )
    if request_version != snapshot_version:
        return BudgetRevisionPlan(
            mode="clarify",
            constraints=[],
            clarification=(
                "会话状态已变化，请基于最新结果重试。"
            ),
        )
    assert draft.maximum is not None
    merged = [
        item.model_copy(deep=True)
        for item in base_constraints
        if not isinstance(item, BudgetConstraint)
    ]
    merged.append(
        BudgetConstraint(
            minimum=None,
            maximum=draft.maximum,
        )
    )
    return BudgetRevisionPlan(
        mode="revise",
        constraints=merged,
        clarification=None,
    )
```

- [x] **Step 6: Export and verify**

Update `app/guide/intent/__init__.py`:

```python
from app.guide.intent.contracts import (
    BudgetRevisionPlan,
    FollowupPlan,
    TaskPlan,
)

__all__ = [
    "BudgetRevisionPlan",
    "FollowupPlan",
    "TaskPlan",
]
```

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/intent \
  tests/guide/test_public_contracts.py
python3 app/guide/check_boundaries.py app/guide
git diff --check
```

Expected: all selected tests and boundary pass.

- [x] **Step 7: Commit**

```bash
git add \
  app/guide/intent/contracts.py \
  app/guide/intent/__init__.py \
  app/guide/intent/budget_revision_planning.py \
  app/guide/understanding/__init__.py \
  tests/guide/intent/test_budget_revision_planning.py \
  tests/guide/test_public_contracts.py
git commit -m "feat(intent): plan budget revision followups"
```

---

### Task 5: Re-run the Full Recommendation Flow with Merged Constraints

**Files:**
- Create: `app/guide/presentation/budget_revision_response.py`
- Create: `tests/guide/presentation/test_budget_revision_response.py`
- Modify: `app/guide/presentation/sse_events.py`
- Modify: `app/guide/application/text_recommendation_flow.py`
- Modify: `tests/guide/application/test_text_recommendation_flow.py`
- Modify: `tests/guide/test_public_contracts.py`

- [x] **Step 1: Write failing presentation tests**

Create `tests/guide/presentation/test_budget_revision_response.py`:

```python
from decimal import Decimal

from app.guide.decision.contracts import (
    DecisionResult,
    RiskFinding,
    WinnerStatus,
)
from app.guide.intent.contracts import (
    BudgetConstraint,
    CategoryConstraint,
    EfficacyConstraint,
    SkinConstraint,
    TaskPlan,
)
from app.guide.presentation.budget_revision_response import (
    build_budget_revision_message,
)
from app.guide.understanding.contracts import (
    EfficacyTarget,
    SkinTarget,
    TopicCode,
)


def task() -> TaskPlan:
    return TaskPlan(
        mode="recommend",
        referenced_image_ids=[],
        constraints=[
            CategoryConstraint(value=TopicCode.SERUM),
            BudgetConstraint(
                minimum=None,
                maximum=Decimal("100"),
            ),
            SkinConstraint(value=SkinTarget.SENSITIVE),
            EfficacyConstraint(value=EfficacyTarget.REPAIR),
        ],
        required_evidence=["canonical_product"],
        clarification=None,
    )


def decision(status: WinnerStatus) -> DecisionResult:
    return DecisionResult(
        ordered_product_ids=(
            [] if status is WinnerStatus.NO_CANDIDATE else [91]
        ),
        winner_status=status,
        winner_product_id=None,
        evaluations=[],
        comparison_dimensions=["price"],
        risk_findings=(
            [
                RiskFinding(
                    kind="skin_match_unknown",
                    product_id=91,
                    detail="敏感肌适配证据缺失",
                )
            ]
            if status is WinnerStatus.INSUFFICIENT_FOR_WINNER
            else []
        ),
        evidence_refs=["efficacy=repair"],
        tie_reason=None,
    )


def test_budget_revision_message_confirms_inheritance_and_stays_honest() -> None:
    message = build_budget_revision_message(
        task(),
        decision(WinnerStatus.INSUFFICIENT_FOR_WINNER),
    )

    assert "敏感肌修护精华" in message
    assert "¥100" in message
    assert "敏感肌适配证据仍不足" in message
    assert "唯一最适合" in message
    assert "最佳" not in message


def test_no_candidate_message_says_previous_state_is_retained() -> None:
    message = build_budget_revision_message(
        task(),
        decision(WinnerStatus.NO_CANDIDATE),
    )

    assert "暂无符合硬条件" in message
    assert "保留上一轮有效结果" in message
```

- [x] **Step 2: Write failing application flow tests**

Add to `tests/guide/application/test_text_recommendation_flow.py`:

```python
from decimal import Decimal

from app.guide.feedback.ports import ConversationStateConflict
from app.guide.understanding.contracts import TopicCode


def test_budget_revision_reruns_full_flow_and_updates_snapshot(
    orchestrator,
    conversation_state,
    monkeypatch,
) -> None:
    list(orchestrator.stream(_turn("500 元内敏感肌修护精华")))

    from app.guide.application import text_recommendation_flow as flow

    original = flow.retrieve_candidates
    categories = []

    def recording_retrieval(*args, **kwargs):
        categories.append(kwargs["category"])
        return original(*args, **kwargs)

    monkeypatch.setattr(flow, "retrieve_candidates", recording_retrieval)
    events = list(
        orchestrator.stream(
            _turn("预算降到 100 元呢", conversation_version=1)
        )
    )

    assert [item.event for item in events] == [
        "start",
        "stage",
        "intent",
        "stage",
        "stage",
        "decision_process",
        "answer_contract",
        "products",
        "message",
        "end",
    ]
    intent = next(item for item in events if item.event == "intent")
    assert intent.data.mode == "revise"
    products = next(item for item in events if item.event == "products")
    assert [card.product_id for card in products.data.cards] == [91]
    decision = next(
        item for item in events if item.event == "decision_process"
    )
    assert decision.data.winner_status == "INSUFFICIENT_FOR_WINNER"
    assert categories == [TopicCode.SERUM]
    assert events[-1].data.conversation_version == 2

    snapshot = conversation_state.load("s-1")
    assert snapshot is not None
    assert snapshot.version == 2
    assert snapshot.query_context.category == "serum"
    assert snapshot.query_context.budget_maximum == Decimal("100")
    assert snapshot.query_context.skin == "sensitive"
    assert snapshot.query_context.efficacy == "repair"
    assert [item.product_id for item in snapshot.candidates] == [91]


def test_stale_budget_revision_does_not_retrieve(
    orchestrator,
    monkeypatch,
) -> None:
    list(orchestrator.stream(_turn("500 元内敏感肌修护精华")))

    def forbidden_retrieval(*args, **kwargs):
        raise AssertionError("stale revision must not retrieve")

    monkeypatch.setattr(
        "app.guide.application.text_recommendation_flow.retrieve_candidates",
        forbidden_retrieval,
    )
    events = list(
        orchestrator.stream(
            _turn("预算降到100元呢", conversation_version=0)
        )
    )

    assert "products" not in [item.event for item in events]
    clarify = next(item for item in events if item.event == "clarify")
    assert "状态已变化" in clarify.data.question
    assert events[-1].data.conversation_version == 1


def test_no_candidate_budget_revision_retains_previous_snapshot(
    orchestrator,
    conversation_state,
) -> None:
    list(orchestrator.stream(_turn("500 元内敏感肌修护精华")))
    before = conversation_state.load("s-1")

    events = list(
        orchestrator.stream(
            _turn("预算降到50元呢", conversation_version=1)
        )
    )

    products = next(item for item in events if item.event == "products")
    assert products.data.cards == []
    message = next(item for item in events if item.event == "message")
    assert "保留上一轮有效结果" in message.data.content
    assert events[-1].data.conversation_version == 1
    assert conversation_state.load("s-1") == before


def test_revision_error_is_terminal_and_keeps_previous_snapshot(
    orchestrator,
    conversation_state,
    monkeypatch,
) -> None:
    list(orchestrator.stream(_turn("500 元内敏感肌修护精华")))
    before = conversation_state.load("s-1")

    def broken_retrieval(*args, **kwargs):
        raise RuntimeError("revision retrieval failed")

    monkeypatch.setattr(
        "app.guide.application.text_recommendation_flow.retrieve_candidates",
        broken_retrieval,
    )
    events = list(
        orchestrator.stream(
            _turn("预算降到100元呢", conversation_version=1)
        )
    )

    assert events[-1].event == "error"
    assert "end" not in [item.event for item in events]
    assert conversation_state.load("s-1") == before


def test_budget_revision_cas_conflict_keeps_authoritative_snapshot(
    orchestrator,
    conversation_state,
    monkeypatch,
) -> None:
    list(orchestrator.stream(_turn("500 元内敏感肌修护精华")))
    before = conversation_state.load("s-1")

    def conflicting_save(snapshot, *, expected_version):
        raise ConversationStateConflict(snapshot.session_id)

    monkeypatch.setattr(
        conversation_state,
        "save",
        conflicting_save,
    )
    events = list(
        orchestrator.stream(
            _turn("预算降到100元呢", conversation_version=1)
        )
    )

    assert "products" not in [item.event for item in events]
    clarify = next(item for item in events if item.event == "clarify")
    assert "状态已变化" in clarify.data.question
    assert events[-1].data.conversation_version == 1
    assert conversation_state.load("s-1") == before


def test_budget_revision_changes_latest_candidate_boundary(
    orchestrator,
) -> None:
    list(orchestrator.stream(_turn("500 元内敏感肌修护精华")))
    list(
        orchestrator.stream(
            _turn("预算降到100元呢", conversation_version=1)
        )
    )
    events = list(
        orchestrator.stream(
            _turn("第二款呢", conversation_version=2)
        )
    )

    clarify = next(item for item in events if item.event == "clarify")
    assert "只展示了 1 款" in clarify.data.question
    assert events[-1].data.conversation_version == 2


def test_explicit_category_query_wins_over_budget_revision(
    orchestrator,
    conversation_state,
) -> None:
    list(orchestrator.stream(_turn("500 元内敏感肌修护精华")))
    events = list(
        orchestrator.stream(
            _turn("100 元内防晒", conversation_version=1)
        )
    )

    intent = next(item for item in events if item.event == "intent")
    products = next(item for item in events if item.event == "products")
    assert intent.data.mode == "recommend"
    assert products.data.cards
    assert all(card.category == "防晒" for card in products.data.cards)
    assert events[-1].data.conversation_version == 2
    snapshot = conversation_state.load("s-1")
    assert snapshot is not None
    assert snapshot.query_context.category == "sunscreen"
    assert snapshot.query_context.budget_maximum == Decimal("100")


def test_bare_amount_does_not_inherit_query_context(
    orchestrator,
    conversation_state,
) -> None:
    list(orchestrator.stream(_turn("500 元内敏感肌修护精华")))
    before = conversation_state.load("s-1")
    events = list(
        orchestrator.stream(
            _turn("100元呢", conversation_version=1)
        )
    )

    assert "products" not in [item.event for item in events]
    clarify = next(item for item in events if item.event == "clarify")
    assert "明确品类" in clarify.data.question
    assert events[-1].data.conversation_version == 1
    assert conversation_state.load("s-1") == before
```

- [x] **Step 3: Run tests and verify RED**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/presentation/test_budget_revision_response.py \
  tests/guide/application/test_text_recommendation_flow.py
```

Expected: presentation module is missing and budget revision currently
clarifies instead of rerunning recommendation.

- [x] **Step 4: Implement honest budget-revision presentation**

Create `app/guide/presentation/budget_revision_response.py`:

```python
from __future__ import annotations

from decimal import Decimal

from app.guide.decision.contracts import DecisionResult, WinnerStatus
from app.guide.intent.contracts import (
    BudgetConstraint,
    CategoryConstraint,
    EfficacyConstraint,
    SkinConstraint,
    TaskPlan,
)
from app.guide.understanding.contracts import (
    EfficacyTarget,
    SkinTarget,
    TopicCode,
)


_SKIN_LABELS = {
    SkinTarget.OILY_SENSITIVE: "油敏肌",
    SkinTarget.OILY: "油皮",
    SkinTarget.DRY: "干皮",
    SkinTarget.COMBINATION: "混合肌",
    SkinTarget.SENSITIVE: "敏感肌",
    SkinTarget.NORMAL: "中性肌",
}


def build_budget_revision_message(
    task: TaskPlan,
    decision: DecisionResult,
) -> str:
    budget = _required(task, BudgetConstraint)
    category = _required(task, CategoryConstraint)
    skin = _optional(task, SkinConstraint)
    efficacy = _optional(task, EfficacyConstraint)
    assert budget.maximum is not None
    label = "".join(
        part
        for part in (
            _SKIN_LABELS.get(skin.value, "") if skin else "",
            "修护"
            if efficacy
            and efficacy.value is EfficacyTarget.REPAIR
            else "",
            "精华"
            if category.value is TopicCode.SERUM
            else "防晒",
        )
        if part
    )
    prefix = (
        f"已沿用“{label}”，把预算上限调整为 "
        f"¥{_format_amount(budget.maximum)}。"
    )
    if decision.winner_status is WinnerStatus.NO_CANDIDATE:
        return (
            f"{prefix}按该上限重新筛选后暂无符合硬条件的商品，"
            "已保留上一轮有效结果。"
        )
    if (
        decision.winner_status
        is WinnerStatus.INSUFFICIENT_FOR_WINNER
    ):
        has_unknown_skin = any(
            item.kind == "skin_match_unknown"
            for item in decision.risk_findings
        )
        if has_unknown_skin and skin is not None:
            evidence_note = (
                f"{_SKIN_LABELS[skin.value]}适配证据仍不足，"
                "暂不把它表述为唯一最适合。"
            )
        else:
            evidence_note = (
                "现有业务证据仍不足，暂不强行指定唯一推荐。"
            )
        return (
            f"{prefix}现有审核事实下剩余 "
            f"{len(decision.ordered_product_ids)} 款，"
            f"但{evidence_note}"
        )
    return (
        f"{prefix}已按新预算重新执行审核事实筛选和稳定排序。"
    )


def _required(task: TaskPlan, constraint_type: type):
    value = _optional(task, constraint_type)
    if value is None:
        raise ValueError(
            f"missing {constraint_type.__name__}"
        )
    return value


def _optional(task: TaskPlan, constraint_type: type):
    values = [
        item for item in task.constraints
        if isinstance(item, constraint_type)
    ]
    if len(values) > 1:
        raise ValueError(
            f"duplicate {constraint_type.__name__}"
        )
    return values[0] if values else None


def _format_amount(value: Decimal) -> str:
    return format(value.normalize(), "f")
```

- [x] **Step 5: Extend typed SSE intent mode**

In `app/guide/presentation/sse_events.py`:

```python
class IntentData(_Strict):
    mode: Literal["recommend", "clarify", "followup", "revise"]
```

No new event type is needed.

- [x] **Step 6: Add the budget revision branch**

In `app/guide/application/text_recommendation_flow.py`, import:

```python
from typing import Literal, Mapping

from app.guide.application.query_context import (
    query_context_to_constraints,
    task_plan_to_query_context,
)
from app.guide.intent.budget_revision_planning import (
    plan_budget_revision,
)
from app.guide.intent.contracts import (
    BudgetRevisionPlan,
    CategoryConstraint,
    FollowupPlan,
    TaskPlan,
)
from app.guide.presentation.budget_revision_response import (
    build_budget_revision_message,
)
from app.guide.understanding.budget_revision_parsing import (
    parse_budget_revision,
)
```

Immediately after the existing candidate follow-up branch, add:

```python
budget_draft = parse_budget_revision(turn.message)
budget_plan = plan_budget_revision(
    budget_draft,
    base_constraints=(
        query_context_to_constraints(snapshot.query_context)
        if snapshot is not None
        else None
    ),
    request_version=turn.conversation_version,
    snapshot_version=(
        snapshot.version if snapshot is not None else None
    ),
)
if budget_plan is not None:
    yield from self._stream_budget_revision(
        turn,
        snapshot=snapshot,
        plan=budget_plan,
    )
    return
```

- [x] **Step 7: Extract the shared full recommendation path**

Replace the duplicated retrieval-to-end block in `stream()` with:

```python
yield from self._stream_recommendation(
    turn,
    snapshot=snapshot,
    task=task,
    intent_mode="recommend",
)
return
```

Add this complete private method:

```python
def _stream_recommendation(
    self,
    turn: UserTurn,
    *,
    snapshot: ConversationSnapshot | None,
    task: TaskPlan,
    intent_mode: Literal["recommend", "revise"],
) -> Iterator[SseEvent]:
    category = _category_constraint(task.constraints)
    yield StageEvent(
        data=StageData(
            stage="retrieval",
            summary="正在读取已审核的 Canonical 商品事实。",
        )
    )
    retrieval = retrieve_candidates(
        self._category_catalog,
        category=category.value,
    )
    yield StageEvent(
        data=StageData(
            stage="decision",
            summary="正在执行预算、排除项和肤质证据规则。",
        )
    )
    decision = decide_recommendation(
        self._decision_facts,
        retrieval,
        constraints=task.constraints,
    )
    response = self._build_plan(decision)
    status = self._feedback.record_turn(turn)
    if status is not FeedbackWriteStatus.SKIPPED_SLICE_SCOPE:
        raise RuntimeError("unexpected feedback write status")
    expected_version = self._snapshot_version(snapshot)
    response_version = expected_version
    if response.structured_events:
        saved_snapshot = self._conversation_state.save(
            self._visible_snapshot(
                turn,
                list(response.structured_events),
                task=task,
                version=expected_version + 1,
            ),
            expected_version=expected_version,
        )
        response_version = saved_snapshot.version

    has_unknown_skin = any(
        item.kind == "skin_match_unknown"
        for item in decision.risk_findings
    )
    yield DecisionProcessEvent(
        data=DecisionProcessData(
            ordered_product_ids=list(decision.ordered_product_ids),
            winner_status=decision.winner_status.value,
            evidence_refs=list(decision.evidence_refs),
        )
    )
    yield AnswerContractEvent(
        data=AnswerContractData(
            product_count=len(response.structured_events),
            winner_status=decision.winner_status.value,
            has_unknown_skin=has_unknown_skin,
        )
    )
    yield ProductsEvent(
        data=ProductsData(cards=list(response.structured_events))
    )
    message = (
        build_budget_revision_message(task, decision)
        if intent_mode == "revise"
        else _summary_fragment(decision)
    )
    yield MessageEvent(data=MessageData(content=message))
    yield EndEvent(
        data=EndData(conversation_version=response_version)
    )
```

The normal caller must keep its existing `IntentEvent(mode=task.mode)` before
this method, preserving the original event order.

- [x] **Step 8: Implement the revision wrapper**

Add:

```python
def _stream_budget_revision(
    self,
    turn: UserTurn,
    *,
    snapshot: ConversationSnapshot | None,
    plan: BudgetRevisionPlan,
) -> Iterator[SseEvent]:
    authoritative_version = self._snapshot_version(snapshot)
    if plan.mode == "clarify":
        assert plan.clarification is not None
        yield ClarifyEvent(
            data=ClarifyData(question=plan.clarification)
        )
        yield EndEvent(
            data=EndData(
                conversation_version=authoritative_version
            )
        )
        return
    assert snapshot is not None
    task = TaskPlan(
        mode="recommend",
        referenced_image_ids=[],
        constraints=[
            item.model_copy(deep=True)
            for item in plan.constraints
        ],
        required_evidence=["canonical_product"],
        clarification=None,
    )
    yield StageEvent(
        data=StageData(
            stage="state",
            summary="已读取最近一次成功筛选的结构化条件。",
        )
    )
    yield IntentEvent(data=IntentData(mode="revise"))
    yield from self._stream_recommendation(
        turn,
        snapshot=snapshot,
        task=task,
        intent_mode="revise",
    )
```

Keep candidate follow-up before this branch and generic stale handling after
it. This preserves the explicit routing priority.

- [x] **Step 9: Run application, presentation and public-contract tests**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/presentation \
  tests/guide/application \
  tests/guide/test_public_contracts.py
python3 app/guide/check_boundaries.py app/guide
shasum -a 256 app/guide/decision/deterministic_ranking.py
git diff --check
```

Expected:

- all selected tests pass;
- boundary passes;
- ranking SHA remains
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`.

- [x] **Step 10: Commit**

```bash
git add \
  app/guide/presentation/budget_revision_response.py \
  app/guide/presentation/sse_events.py \
  app/guide/application/text_recommendation_flow.py \
  tests/guide/presentation/test_budget_revision_response.py \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/test_public_contracts.py
git commit -m "feat(application): stream budget revision recommendations"
```

---

### Task 6: Wire Runtime Capability and Real Two-Turn Gates

**Files:**
- Modify: `app/guide_runtime/app.py`
- Modify: `tests/guide/runtime/test_runtime_http.py`
- Modify: `tests/guide/runtime/test_composition.py`
- Modify: `tests/guide/application/test_slice1_backend_gate.py`
- Modify: `tools/guide_gates/runtime_browser_smoke.py`

- [x] **Step 1: Write failing HTTP and health tests**

In `tests/guide/runtime/test_runtime_http.py`, extend health capabilities:

```python
"capabilities": [
    "sunscreen",
    "repair_serum",
    "recent_candidate_followup",
    "budget_revision_followup",
],
```

Add:

```python
def test_http_round_trips_budget_revision_context() -> None:
    client = TestClient(create_app())
    first = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "500 元内敏感肌修护精华",
            "session_id": "budget-revision-http",
            "conversation_version": 0,
        },
    )
    assert _events(first)[-1] == (
        "end",
        {"conversation_version": 1},
    )

    second = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "预算降到 100 元呢",
            "session_id": "budget-revision-http",
            "conversation_version": 1,
        },
    )
    events = _events(second)
    products = next(
        data for name, data in events if name == "products"
    )
    decision = next(
        data
        for name, data in events
        if name == "decision_process"
    )
    message = next(
        data for name, data in events if name == "message"
    )

    assert [item["id"] for item in products["products"]] == [91]
    assert decision["winner_status"] == "INSUFFICIENT_FOR_WINNER"
    assert "预算上限调整为 ¥100" in message["content"]
    assert events[-1] == (
        "end",
        {"conversation_version": 2},
    )


def test_http_client_cannot_override_server_query_context() -> None:
    client = TestClient(create_app())
    client.post(
        "/api/v1/chat/stream",
        json={
            "message": "500 元内敏感肌修护精华",
            "session_id": "server-owned-context",
            "conversation_version": 0,
        },
    )

    response = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "预算降到100元呢",
            "session_id": "server-owned-context",
            "conversation_version": 1,
            "query_context": {
                "category": "sunscreen",
                "budget_maximum": 1,
            },
        },
    )
    products = next(
        data
        for name, data in _events(response)
        if name == "products"
    )

    assert [item["id"] for item in products["products"]] == [91]
```

- [x] **Step 2: Write failing `/tmp` composition gate**

Add to `tests/guide/runtime/test_composition.py`:

```python
def test_budget_revision_composition_retains_query_context_outside_repo(
    tmp_path: Path,
) -> None:
    previous = Path.cwd()
    os.chdir(tmp_path)
    try:
        orchestrator = build_runtime_orchestrator()
        first = list(
            orchestrator.stream(
                UserTurn(
                    session_id="budget-composition-test",
                    message="500 元内敏感肌修护精华",
                    image_bundle_id=None,
                    conversation_version=0,
                )
            )
        )
        second = list(
            orchestrator.stream(
                UserTurn(
                    session_id="budget-composition-test",
                    message="预算降到100元呢",
                    image_bundle_id=None,
                    conversation_version=1,
                )
            )
        )
    finally:
        os.chdir(previous)

    assert first[-1].data.conversation_version == 1
    products = next(
        item for item in second if item.event == "products"
    )
    assert [card.product_id for card in products.data.cards] == [91]
    assert second[-1].data.conversation_version == 2
```

- [x] **Step 3: Write failing backend release gate**

Add to `tests/guide/application/test_slice1_backend_gate.py`:

```python
def test_budget_revision_followup_gate(orchestrator) -> None:
    first = list(
        orchestrator.stream(
            UserTurn(
                session_id="gate-budget-revision",
                message="500 元内敏感肌修护精华",
                image_bundle_id=None,
                conversation_version=0,
            )
        )
    )
    second = list(
        orchestrator.stream(
            UserTurn(
                session_id="gate-budget-revision",
                message="预算降到100元呢",
                image_bundle_id=None,
                conversation_version=1,
            )
        )
    )

    products = next(
        item for item in second if item.event == "products"
    )
    decision = next(
        item for item in second
        if item.event == "decision_process"
    )
    assert [card.product_id for card in products.data.cards] == [91]
    assert decision.data.winner_status == "INSUFFICIENT_FOR_WINNER"
    assert second[-1].data.conversation_version == 2
```

- [x] **Step 4: Run tests and verify RED**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/runtime/test_runtime_http.py \
  tests/guide/runtime/test_composition.py \
  tests/guide/application/test_slice1_backend_gate.py
```

Expected: flow tests pass from Task 5, but health fails until capability is
declared.

- [x] **Step 5: Declare runtime capability**

In `app/guide_runtime/app.py`:

```python
RUNTIME_CAPABILITIES = [
    "sunscreen",
    "repair_serum",
    "recent_candidate_followup",
    "budget_revision_followup",
]
```

Do not add another request field or client-owned context payload.

- [x] **Step 6: Extend the browser gate**

In `tools/guide_gates/runtime_browser_smoke.py`, keep the existing sunscreen
and `第二款呢` scenarios. After the candidate-follow-up assertions, add a fresh
session:

```python
page.evaluate(
    "() => { localStorage.clear(); sessionStorage.clear(); }"
)
page.goto(args.url, wait_until="networkidle")
page.fill("#chatInput", "500 元内敏感肌修护精华")
page.click("#sendBtn")
budget_panels = page.locator(".recommendation-panel")
expect(budget_panels.first).to_be_visible(timeout=20000)
assert budget_panels.first.locator(".recommendation-card").count() == 2

page.fill("#chatInput", "预算降到 100 元呢")
page.click("#sendBtn")
expect(budget_panels.nth(1)).to_be_visible(timeout=20000)
budget_cards = budget_panels.nth(1).locator(".recommendation-card")
assert budget_cards.count() == 1
expect(budget_cards.first).to_contain_text(
    "玉泽皮肤屏障修护精华乳50ml"
)
expect(
    page.locator(".message-markdown").last
).to_contain_text("预算上限调整为 ¥100")
expect(
    page.locator(".message-markdown").last
).to_contain_text("敏感肌适配证据仍不足")
version = page.evaluate(
    """() => {
        const sessionId = localStorage.getItem(
            'lumi_current_session_id'
        );
        const versions = JSON.parse(
            localStorage.getItem(
                'lumi_conversation_versions_v1'
            ) || '{}'
        );
        return versions[sessionId];
    }"""
)
assert version == 2
```

Keep screenshot capture, page error, failed image and hidden feedback
assertions after all three scenarios.

- [x] **Step 7: Run runtime and layer gates**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/runtime \
  tests/guide/application/test_slice1_backend_gate.py
python3 app/guide/check_boundaries.py app/guide
python3 app/guide/check_boundaries.py app/guide_runtime
git diff --check
```

Expected: all selected tests and both boundary scans pass.

- [x] **Step 8: Run the updated browser gate**

First run:

```bash
lsof -nP -iTCP:8765 -sTCP:LISTEN
```

Expected: no listener. Then run:

```bash
python3 /Users/bytedance/.trae-cn/skills/webapp-testing/scripts/with_server.py \
  --help
python3 /Users/bytedance/.trae-cn/skills/webapp-testing/scripts/with_server.py \
  --server "cd /tmp && PYTHONPATH=/Users/bytedance/Desktop/xiaoro-fresh exec /tmp/xiaoro-guide-runtime-venv/bin/uvicorn app.guide_runtime.app:app --host 127.0.0.1 --port 8765" \
  --port 8765 \
  -- python3 tools/guide_gates/runtime_browser_smoke.py \
    --screenshot /tmp/xiaoro-guide-budget-revision-task6.png
```

Expected: helper usage prints successfully, browser gate exits 0, and the
Task 6 screenshot exists.

- [x] **Step 9: Commit**

```bash
git add \
  app/guide_runtime/app.py \
  tests/guide/runtime/test_runtime_http.py \
  tests/guide/runtime/test_composition.py \
  tests/guide/application/test_slice1_backend_gate.py \
  tools/guide_gates/runtime_browser_smoke.py
git commit -m "test(guide): gate budget revision followups"
```

---

### Task 7: Run the Full Locked Release Gate

**Files:**
- Modify: `docs/superpowers/plans/2026-08-07-slice1-budget-revision-followup.md`

- [x] **Step 1: Run the full guide and runtime suites**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  -c pytest-guide.ini
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/runtime
```

Expected: both commands pass with zero failures.

- [x] **Step 2: Run both architecture scans and diff validation**

Run:

```bash
python3 app/guide/check_boundaries.py app/guide
python3 app/guide/check_boundaries.py app/guide_runtime
git diff --check
```

Expected: both scans report zero violations and diff check is clean.

- [x] **Step 3: Run the formal browser gate**

First confirm there is no stale server:

```bash
lsof -nP -iTCP:8765 -sTCP:LISTEN
```

Expected: no listener. Then confirm the helper contract:

```bash
python3 /Users/bytedance/.trae-cn/skills/webapp-testing/scripts/with_server.py \
  --help
```

Then run:

```bash
python3 /Users/bytedance/.trae-cn/skills/webapp-testing/scripts/with_server.py \
  --server "cd /tmp && PYTHONPATH=/Users/bytedance/Desktop/xiaoro-fresh exec /tmp/xiaoro-guide-runtime-venv/bin/uvicorn app.guide_runtime.app:app --host 127.0.0.1 --port 8765" \
  --port 8765 \
  -- python3 tools/guide_gates/runtime_browser_smoke.py \
    --screenshot /tmp/xiaoro-guide-budget-revision.png
```

Expected: exit 0 and screenshot exists.

- [x] **Step 4: Confirm protected paths, hashes and server cleanup**

Run:

```bash
git diff --name-only 0436fbd..HEAD -- \
  app/main.py app/api/v1/chat.py app/services app/database \
  data/canonical app/guide/decision/deterministic_ranking.py
shasum -a 256 app/guide/decision/deterministic_ranking.py
lsof -nP -iTCP:8765 -sTCP:LISTEN
ls -l /tmp/xiaoro-guide-budget-revision.png
```

Expected:

- protected-path diff is empty;
- ranking SHA is
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`;
- `lsof` prints no listener;
- screenshot exists.

- [x] **Step 5: Mark this plan complete**

Change every completed task checkbox in this file from:

```text
- [x]
```

to:

```text
- [x]
```

Do not alter the header's inline checkbox syntax example.

- [x] **Step 6: Commit the completed gate record**

```bash
git add \
  docs/superpowers/plans/2026-08-07-slice1-budget-revision-followup.md
git commit -m "docs: complete budget revision followup plan"
```

---

## Final Acceptance Checklist

- [x] `RecommendationQueryContext` is strict and excludes raw text or facts.
- [x] Every successful snapshot contains query context and visible candidates.
- [x] Candidate-only follow-ups preserve query context.
- [x] Explicit category queries win over budget revision parsing.
- [x] Only explicit maximum revisions with Arabic digits and units are accepted.
- [x] Bare numbers, relative budgets, ranges and invalid values clarify.
- [x] Revision removes old minimum and maximum before adding the new maximum.
- [x] Category, skin, efficacy and exclusions are preserved exactly.
- [x] Budget revision re-runs retrieval, decision and presentation.
- [x] Stale revisions do not retrieve or mutate state.
- [x] Zero-candidate revisions retain the previous valid snapshot and version.
- [x] Terminal errors retain the previous valid snapshot and emit no `end`.
- [x] Real two-turn result is `[91, 38] -> [91]`.
- [x] Real two-turn version is `1 -> 2`.
- [x] Product 91 remains `INSUFFICIENT_FOR_WINNER`.
- [x] Existing sunscreen, repair-serum and candidate-follow-up gates pass.
- [x] `/health` declares `budget_revision_followup`.
- [x] Browser completes all three locked scenarios.
- [x] Canonical, old API, old services and database remain untouched.
- [x] Deterministic ranking SHA remains locked.
- [x] Full guide gate, runtime gate and both boundary scans pass.

## Stop Condition

本计划完成后停止，不顺带实现改肤质、成分排除追问、相对预算、预算区间、换一批、
图片、长期画像、数据库或模型能力。下一阶段单独设计“修改肤质”。
