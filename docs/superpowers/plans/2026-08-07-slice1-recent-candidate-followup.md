# Slice 1.4 Recent Candidate Follow-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为干净文本护肤运行时增加服务端最近候选快照，可靠支持“第二款呢”和“哪个更便宜”两类候选集内追问。

**Architecture:** 会话状态由 feedback 层合同和 `ConversationStatePort` 拥有，进程内 adapter 提供 CAS、TTL 和容量控制。Understanding/Intent 只识别受支持追问，Decision 只在 snapshot ID 内选择，Application 负责版本编排和 typed SSE；追问不执行 retrieval。

**Tech Stack:** Python 3.11, Pydantic 2.8.0, FastAPI 0.115.0, pytest 8.0.0, Playwright, typed SSE.

---

## 0. Execution Contract

- 最高事实源：
  `docs/superpowers/specs/2026-08-07-slice1-recent-candidate-followup-design.md`
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
- 不实现条件继承、换一批、图片、长期画像、数据库、LLM 或 BGE。
- 排序内核 SHA 必须保持：
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`
- 单轮锁定结果必须保持：

```text
防晒：[55, 57, 54, 51, 102, 53, 58, 56, 52, 26, 101]
修护精华：[91, 38]
修护精华 winner_status：INSUFFICIENT_FOR_WINNER
```

## 1. File Map

### Create: Conversation State

- `app/guide/adapters/state/__init__.py`
  - 导出进程内 state adapter。
- `app/guide/adapters/state/in_memory_conversation_state.py`
  - CAS、TTL、容量和复制隔离。
- `tests/guide/feedback/test_conversation_state_contracts.py`
  - 快照强合同。
- `tests/guide/adapters/state/test_in_memory_conversation_state.py`
  - store 行为。

### Create: Follow-up Understanding and Intent

- `app/guide/understanding/followup_parsing.py`
  - 序号、最低价和不支持代词的确定性解析。
- `app/guide/intent/followup_planning.py`
  - snapshot、版本和越界澄清。
- `tests/guide/understanding/test_followup_parsing.py`
- `tests/guide/intent/test_followup_planning.py`

### Create: Follow-up Decision and Presentation

- `app/guide/decision/followup.py`
  - ordinal 和 cheapest 的 snapshot 内决策。
- `app/guide/presentation/followup_response.py`
  - 从决策结果和授权事实构造卡片、文案。
- `tests/guide/decision/test_followup.py`
- `tests/guide/presentation/test_followup_response.py`

### Modify: Existing Contracts and Orchestration

- `app/guide/feedback/contracts.py`
- `app/guide/feedback/ports.py`
- `app/guide/feedback/__init__.py`
- `app/guide/understanding/contracts.py`
- `app/guide/intent/contracts.py`
- `app/guide/decision/contracts.py`
- `app/guide/presentation/sse_events.py`
- `app/guide/application/text_recommendation_flow.py`
- `app/guide/application/chat_api_adapter.py`
- `app/guide_runtime/composition.py`
- `app/guide_runtime/contracts.py`
- `app/guide_runtime/sse.py`
- `app/guide_runtime/app.py`
- `app/static/chat.html`

### Modify: Gates

- `tests/guide/test_package_layout.py`
- `tests/guide/test_public_contracts.py`
- `tests/guide/application/conftest.py`
- `tests/guide/application/test_text_recommendation_flow.py`
- `tests/guide/application/test_chat_api_adapter.py`
- `tests/guide/runtime/test_runtime_http.py`
- `tests/guide/runtime/test_frontend_scope.py`
- `tools/guide_gates/runtime_browser_smoke.py`

---

### Task 1: Build the Typed Conversation State Port and In-Memory Adapter

**Files:**
- Modify: `app/guide/feedback/contracts.py`
- Modify: `app/guide/feedback/ports.py`
- Modify: `app/guide/feedback/__init__.py`
- Create: `app/guide/adapters/state/__init__.py`
- Create: `app/guide/adapters/state/in_memory_conversation_state.py`
- Create: `tests/guide/feedback/test_conversation_state_contracts.py`
- Create: `tests/guide/adapters/state/test_in_memory_conversation_state.py`
- Modify: `tests/guide/test_package_layout.py`
- Modify: `tests/guide/test_public_contracts.py`

- [x] **Step 1: Write failing snapshot contract tests**

Create `tests/guide/feedback/test_conversation_state_contracts.py`:

```python
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.guide.feedback.contracts import (
    ConversationSnapshot,
    DisplayedCandidateRef,
)


def candidate(product_id: int, ordinal: int) -> DisplayedCandidateRef:
    return DisplayedCandidateRef(
        product_id=product_id,
        ordinal=ordinal,
        skin_match="unknown",
        matched_efficacies=["修护"],
    )


def test_snapshot_requires_contiguous_unique_displayed_candidates() -> None:
    snapshot = ConversationSnapshot(
        session_id="session-1",
        version=1,
        candidates=[candidate(91, 1), candidate(38, 2)],
    )
    assert [item.product_id for item in snapshot.candidates] == [91, 38]

    with pytest.raises(ValidationError, match="ordinal"):
        ConversationSnapshot(
            session_id="session-1",
            version=1,
            candidates=[candidate(91, 1), candidate(38, 3)],
        )
    with pytest.raises(ValidationError, match="product_id"):
        ConversationSnapshot(
            session_id="session-1",
            version=1,
            candidates=[candidate(91, 1), candidate(91, 2)],
        )


def test_snapshot_limits_visible_candidates_and_positive_version() -> None:
    with pytest.raises(ValidationError):
        ConversationSnapshot(
            session_id="session-1",
            version=0,
            candidates=[candidate(91, 1)],
        )
    with pytest.raises(ValidationError):
        ConversationSnapshot(
            session_id="session-1",
            version=1,
            candidates=[
                candidate(1, 1),
                candidate(2, 2),
                candidate(3, 3),
                candidate(4, 4),
            ],
        )
```

- [x] **Step 2: Write failing store tests**

Create `tests/guide/adapters/state/test_in_memory_conversation_state.py`:

```python
from __future__ import annotations

import pytest

from app.guide.adapters.state import InMemoryConversationState
from app.guide.feedback.contracts import (
    ConversationSnapshot,
    DisplayedCandidateRef,
)
from app.guide.feedback.ports import ConversationStateConflict


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


def snapshot(
    session_id: str,
    version: int,
    product_id: int,
) -> ConversationSnapshot:
    return ConversationSnapshot(
        session_id=session_id,
        version=version,
        candidates=[
            DisplayedCandidateRef(
                product_id=product_id,
                ordinal=1,
                skin_match="unknown",
                matched_efficacies=[],
            )
        ],
    )


def test_store_compare_and_set_and_copy_isolation() -> None:
    store = InMemoryConversationState()
    saved = store.save(snapshot("s-1", 1, 91), expected_version=0)
    loaded = store.load("s-1")

    assert saved == loaded
    assert loaded is not saved
    with pytest.raises(ConversationStateConflict):
        store.save(snapshot("s-1", 2, 38), expected_version=0)


def test_store_expires_by_injected_clock() -> None:
    clock = FakeClock()
    store = InMemoryConversationState(
        ttl_seconds=30,
        clock=clock,
    )
    store.save(snapshot("s-1", 1, 91), expected_version=0)
    clock.value = 30
    assert store.load("s-1") is None


def test_store_evicts_least_recently_updated_session() -> None:
    clock = FakeClock()
    store = InMemoryConversationState(
        max_sessions=2,
        ttl_seconds=300,
        clock=clock,
    )
    store.save(snapshot("s-1", 1, 1), expected_version=0)
    clock.value = 1
    store.save(snapshot("s-2", 1, 2), expected_version=0)
    clock.value = 2
    store.save(snapshot("s-3", 1, 3), expected_version=0)

    assert store.load("s-1") is None
    assert store.load("s-2") is not None
    assert store.load("s-3") is not None


def test_store_instances_do_not_share_state() -> None:
    first = InMemoryConversationState()
    second = InMemoryConversationState()
    first.save(snapshot("s-1", 1, 91), expected_version=0)
    assert second.load("s-1") is None
```

- [x] **Step 3: Run tests and verify RED**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/feedback/test_conversation_state_contracts.py \
  tests/guide/adapters/state/test_in_memory_conversation_state.py
```

Expected: collection fails because snapshot contracts and state adapter do not
exist.

- [x] **Step 4: Add strict snapshot contracts**

Append to `app/guide/feedback/contracts.py`:

```python
from typing import Annotated, Literal, Self

from pydantic import StringConstraints, model_validator


SessionId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]


class DisplayedCandidateRef(_StrictContract):
    product_id: int
    ordinal: int = Field(ge=1, le=3)
    skin_match: Literal["matched", "unknown", "not_applicable"]
    matched_efficacies: list[str]


class ConversationSnapshot(_StrictContract):
    session_id: SessionId
    version: int = Field(ge=1)
    candidates: list[DisplayedCandidateRef] = Field(
        min_length=1,
        max_length=3,
    )

    @model_validator(mode="after")
    def validate_candidates(self) -> Self:
        ordinals = [item.ordinal for item in self.candidates]
        if ordinals != list(range(1, len(self.candidates) + 1)):
            raise ValueError("candidate ordinal must be contiguous")
        product_ids = [item.product_id for item in self.candidates]
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("candidate product_id must be unique")
        return self
```

Move the new imports to the existing import block instead of creating duplicate
import statements.

- [x] **Step 5: Add the state port and conflict**

Append to `app/guide/feedback/ports.py`:

```python
from app.guide.feedback.contracts import ConversationSnapshot


class ConversationStateConflict(RuntimeError):
    pass


class ConversationStatePort(Protocol):
    def load(self, session_id: str) -> ConversationSnapshot | None: ...

    def save(
        self,
        snapshot: ConversationSnapshot,
        *,
        expected_version: int,
    ) -> ConversationSnapshot: ...
```

Export `ConversationSnapshot` and `DisplayedCandidateRef` from
`app/guide/feedback/__init__.py`.

- [x] **Step 6: Implement the bounded in-memory adapter**

Create `app/guide/adapters/state/in_memory_conversation_state.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from time import monotonic

from app.guide.feedback.contracts import ConversationSnapshot
from app.guide.feedback.ports import ConversationStateConflict


@dataclass(slots=True)
class _Entry:
    snapshot: ConversationSnapshot
    updated_at: float


class InMemoryConversationState:
    def __init__(
        self,
        *,
        max_sessions: int = 512,
        ttl_seconds: float = 1800,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if max_sessions <= 0:
            raise ValueError("max_sessions must be positive")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._max_sessions = max_sessions
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._entries: dict[str, _Entry] = {}
        self._lock = RLock()

    def load(self, session_id: str) -> ConversationSnapshot | None:
        with self._lock:
            now = self._clock()
            self._purge_expired(now)
            entry = self._entries.get(session_id)
            if entry is None:
                return None
            return entry.snapshot.model_copy(deep=True)

    def save(
        self,
        snapshot: ConversationSnapshot,
        *,
        expected_version: int,
    ) -> ConversationSnapshot:
        with self._lock:
            now = self._clock()
            self._purge_expired(now)
            current = self._entries.get(snapshot.session_id)
            current_version = (
                current.snapshot.version if current is not None else 0
            )
            if current_version != expected_version:
                raise ConversationStateConflict(snapshot.session_id)
            if snapshot.version != expected_version + 1:
                raise ValueError("snapshot version must increment by one")
            if current is None and len(self._entries) >= self._max_sessions:
                oldest_session_id = min(
                    self._entries,
                    key=lambda key: (
                        self._entries[key].updated_at,
                        key,
                    ),
                )
                del self._entries[oldest_session_id]
            stored = snapshot.model_copy(deep=True)
            self._entries[snapshot.session_id] = _Entry(
                snapshot=stored,
                updated_at=now,
            )
            return stored.model_copy(deep=True)

    def _purge_expired(self, now: float) -> None:
        expired = [
            session_id
            for session_id, entry in self._entries.items()
            if now - entry.updated_at >= self._ttl_seconds
        ]
        for session_id in expired:
            del self._entries[session_id]
```

Create `app/guide/adapters/state/__init__.py`:

```python
from app.guide.adapters.state.in_memory_conversation_state import (
    InMemoryConversationState,
)

__all__ = ["InMemoryConversationState"]
```

- [x] **Step 7: Update package and public-contract gates**

Add `"adapters.state"` to `FORMAL_PACKAGES` in
`tests/guide/test_package_layout.py`.

Add these public contracts to `CONTRACT_MODULES` in
`tests/guide/test_public_contracts.py`:

```python
    "DisplayedCandidateRef": "feedback",
    "ConversationSnapshot": "feedback",
```

Add valid payloads matching the contracts from Step 4.

- [x] **Step 8: Run focused and broad tests**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/feedback \
  tests/guide/adapters/state \
  tests/guide/test_package_layout.py \
  tests/guide/test_public_contracts.py
python3 app/guide/check_boundaries.py app/guide
```

Expected: all selected tests pass and boundary check reports zero violations.

- [x] **Step 9: Commit**

```bash
git add \
  app/guide/feedback \
  app/guide/adapters/state \
  tests/guide/feedback \
  tests/guide/adapters/state \
  tests/guide/test_package_layout.py \
  tests/guide/test_public_contracts.py
git commit -m "feat(feedback): store recent candidate snapshots"
```

---

### Task 2: Parse and Plan Supported Candidate Follow-ups

**Files:**
- Modify: `app/guide/understanding/contracts.py`
- Modify: `app/guide/understanding/__init__.py`
- Create: `app/guide/understanding/followup_parsing.py`
- Modify: `app/guide/intent/contracts.py`
- Modify: `app/guide/intent/__init__.py`
- Create: `app/guide/intent/followup_planning.py`
- Create: `tests/guide/understanding/test_followup_parsing.py`
- Create: `tests/guide/intent/test_followup_planning.py`
- Modify: `tests/guide/test_public_contracts.py`

- [x] **Step 1: Write failing parser tests**

Create `tests/guide/understanding/test_followup_parsing.py`:

```python
import pytest

from app.guide.understanding.contracts import FollowupAction
from app.guide.understanding.followup_parsing import parse_followup


@pytest.mark.parametrize(
    ("message", "ordinal"),
    [
        ("第二款呢", 2),
        ("第2款", 2),
        ("第一款怎么样", 1),
        ("第三款", 3),
        ("第四款", 4),
    ],
)
def test_parses_ordinal_reference(message: str, ordinal: int) -> None:
    draft = parse_followup(message)
    assert draft is not None
    assert draft.action is FollowupAction.ORDINAL_REFERENCE
    assert draft.ordinal == ordinal
    assert draft.issue is None


@pytest.mark.parametrize("message", ["哪个更便宜", "哪款最便宜"])
def test_parses_cheapest_followup(message: str) -> None:
    draft = parse_followup(message)
    assert draft is not None
    assert draft.action is FollowupAction.CHEAPEST
    assert draft.ordinal is None


@pytest.mark.parametrize("message", ["它怎么样", "这两个怎么选", "哪个好"])
def test_marks_unsupported_ambiguous_followup(message: str) -> None:
    draft = parse_followup(message)
    assert draft is not None
    assert draft.action is None
    assert draft.issue == "unsupported_followup"


def test_complete_new_query_is_not_followup() -> None:
    assert parse_followup("500 元内敏感肌修护精华") is None
    assert parse_followup("第二款防晒") is None
```

- [x] **Step 2: Write failing planning tests**

Create `tests/guide/intent/test_followup_planning.py`:

```python
from app.guide.feedback.contracts import (
    ConversationSnapshot,
    DisplayedCandidateRef,
)
from app.guide.intent.followup_planning import plan_followup
from app.guide.understanding.followup_parsing import parse_followup


def snapshot() -> ConversationSnapshot:
    return ConversationSnapshot(
        session_id="s-1",
        version=1,
        candidates=[
            DisplayedCandidateRef(
                product_id=91,
                ordinal=1,
                skin_match="unknown",
                matched_efficacies=["修护"],
            ),
            DisplayedCandidateRef(
                product_id=38,
                ordinal=2,
                skin_match="unknown",
                matched_efficacies=["修护"],
            ),
        ],
    )


def test_valid_ordinal_followup_plan() -> None:
    plan = plan_followup(
        parse_followup("第二款呢"),
        snapshot=snapshot(),
        request_version=1,
    )
    assert plan is not None
    assert plan.mode == "followup"
    assert plan.ordinal == 2


def test_missing_snapshot_clarifies() -> None:
    plan = plan_followup(
        parse_followup("第二款呢"),
        snapshot=None,
        request_version=1,
    )
    assert plan.mode == "clarify"
    assert "最近一轮候选" in plan.clarification


def test_stale_version_and_out_of_range_clarify() -> None:
    stale = plan_followup(
        parse_followup("第二款呢"),
        snapshot=snapshot(),
        request_version=0,
    )
    assert stale.mode == "clarify"
    assert "状态已变化" in stale.clarification

    out_of_range = plan_followup(
        parse_followup("第四款"),
        snapshot=snapshot(),
        request_version=1,
    )
    assert out_of_range.mode == "clarify"
    assert "只展示了 2 款" in out_of_range.clarification


def test_unsupported_ambiguous_followup_clarifies() -> None:
    plan = plan_followup(
        parse_followup("它怎么样"),
        snapshot=snapshot(),
        request_version=1,
    )
    assert plan.mode == "clarify"
    assert "序号和最低价" in plan.clarification
```

- [x] **Step 3: Run tests and verify RED**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/understanding/test_followup_parsing.py \
  tests/guide/intent/test_followup_planning.py
```

Expected: collection fails because follow-up contracts and modules do not
exist.

- [x] **Step 4: Add follow-up understanding contracts**

In `app/guide/understanding/contracts.py`, add:

```python
class FollowupAction(str, Enum):
    ORDINAL_REFERENCE = "ordinal_reference"
    CHEAPEST = "cheapest"


class FollowupDraft(_StrictContract):
    action: FollowupAction | None = None
    ordinal: int | None = Field(default=None, ge=1, le=9)
    issue: Literal["unsupported_followup"] | None = None

    @model_validator(mode="after")
    def validate_action(self) -> Self:
        if self.issue is not None:
            if self.action is not None or self.ordinal is not None:
                raise ValueError("followup issue forbids action")
            return self
        if self.action is FollowupAction.ORDINAL_REFERENCE:
            if self.ordinal is None:
                raise ValueError("ordinal reference requires ordinal")
            return self
        if self.action is FollowupAction.CHEAPEST:
            if self.ordinal is not None:
                raise ValueError("cheapest forbids ordinal")
            return self
        raise ValueError("followup draft requires action or issue")
```

- [x] **Step 5: Implement deterministic parsing**

Create `app/guide/understanding/followup_parsing.py`:

```python
from __future__ import annotations

import re

from app.guide.understanding.contracts import (
    CategoryDraft,
    FollowupAction,
    FollowupDraft,
)
from app.guide.understanding.exact_parsing import parse_exact_constraints


_ORDINAL = re.compile(r"第\s*(?P<value>[1-9一二三四五六七八九])\s*款")
_ORDINALS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CHEAPEST = ("哪个更便宜", "哪款更便宜", "哪个最便宜", "哪款最便宜")
_UNSUPPORTED = ("它", "那个", "这两个怎么选", "哪个好")


def parse_followup(message: str) -> FollowupDraft | None:
    text = message.strip()
    constraints, _ = parse_exact_constraints(text)
    if any(isinstance(item, CategoryDraft) for item in constraints):
        return None
    ordinal = _ORDINAL.search(text)
    if ordinal:
        raw = ordinal.group("value")
        value = int(raw) if raw.isdigit() else _ORDINALS[raw]
        return FollowupDraft(
            action=FollowupAction.ORDINAL_REFERENCE,
            ordinal=value,
        )
    if any(value in text for value in _CHEAPEST):
        return FollowupDraft(action=FollowupAction.CHEAPEST)
    if any(value in text for value in _UNSUPPORTED):
        return FollowupDraft(issue="unsupported_followup")
    return None
```

- [x] **Step 6: Add follow-up intent contract and planner**

In `app/guide/intent/contracts.py`, import `FollowupAction` and add:

```python
class FollowupPlan(_StrictContract):
    mode: Literal["followup", "clarify"]
    action: FollowupAction | None = None
    ordinal: int | None = Field(default=None, ge=1, le=9)
    clarification: str | None = None

    @model_validator(mode="after")
    def validate_followup_mode(self) -> Self:
        if self.mode == "followup":
            if self.action is None or self.clarification is not None:
                raise ValueError("followup mode requires action")
            if (
                self.action is FollowupAction.ORDINAL_REFERENCE
                and self.ordinal is None
            ):
                raise ValueError("ordinal followup requires ordinal")
            if (
                self.action is FollowupAction.CHEAPEST
                and self.ordinal is not None
            ):
                raise ValueError("cheapest followup forbids ordinal")
        else:
            if self.clarification is None:
                raise ValueError("clarify mode requires clarification")
            if self.action is not None or self.ordinal is not None:
                raise ValueError("clarify mode forbids action")
        return self
```

Create `app/guide/intent/followup_planning.py`:

```python
from app.guide.feedback.contracts import ConversationSnapshot
from app.guide.intent.contracts import FollowupPlan
from app.guide.understanding.contracts import (
    FollowupAction,
    FollowupDraft,
)


def plan_followup(
    draft: FollowupDraft | None,
    *,
    snapshot: ConversationSnapshot | None,
    request_version: int,
) -> FollowupPlan | None:
    if draft is None:
        return None
    if draft.issue is not None:
        return FollowupPlan(
            mode="clarify",
            clarification="当前追问只支持商品序号和最低价比较。",
        )
    if snapshot is None:
        return FollowupPlan(
            mode="clarify",
            clarification="我找不到最近一轮候选，请先重新发起推荐。",
        )
    if request_version != snapshot.version:
        return FollowupPlan(
            mode="clarify",
            clarification="会话状态已变化，请基于最新结果重试。",
        )
    if (
        draft.action is FollowupAction.ORDINAL_REFERENCE
        and draft.ordinal is not None
        and draft.ordinal > len(snapshot.candidates)
    ):
        return FollowupPlan(
            mode="clarify",
            clarification=(
                f"上一轮只展示了 {len(snapshot.candidates)} 款，"
                f"没有第 {draft.ordinal} 款。"
            ),
        )
    return FollowupPlan(
        mode="followup",
        action=draft.action,
        ordinal=draft.ordinal,
    )
```

- [x] **Step 7: Run focused and layer tests**

Export `FollowupAction` and `FollowupDraft` from
`app/guide/understanding/__init__.py`. Export `FollowupPlan` from
`app/guide/intent/__init__.py`.

Add to `CONTRACT_MODULES`:

```python
    "FollowupDraft": "understanding",
    "FollowupPlan": "intent",
```

Add strict valid payloads:

```python
"FollowupDraft": {
    "action": importlib.import_module(
        "app.guide.understanding"
    ).FollowupAction.ORDINAL_REFERENCE,
    "ordinal": 2,
    "issue": None,
},
"FollowupPlan": {
    "mode": "followup",
    "action": importlib.import_module(
        "app.guide.understanding"
    ).FollowupAction.ORDINAL_REFERENCE,
    "ordinal": 2,
    "clarification": None,
},
```

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/understanding \
  tests/guide/intent \
  tests/guide/test_public_contracts.py
python3 app/guide/check_boundaries.py app/guide
```

Expected: all selected tests pass.

- [x] **Step 8: Commit**

```bash
git add \
  app/guide/understanding/contracts.py \
  app/guide/understanding/__init__.py \
  app/guide/understanding/followup_parsing.py \
  app/guide/intent/contracts.py \
  app/guide/intent/__init__.py \
  app/guide/intent/followup_planning.py \
  tests/guide/understanding/test_followup_parsing.py \
  tests/guide/intent/test_followup_planning.py \
  tests/guide/test_public_contracts.py
git commit -m "feat(intent): plan recent candidate followups"
```

---

### Task 3: Decide and Present Snapshot-Only Follow-ups

**Files:**
- Modify: `app/guide/decision/contracts.py`
- Modify: `app/guide/decision/__init__.py`
- Create: `app/guide/decision/followup.py`
- Create: `app/guide/presentation/followup_response.py`
- Create: `tests/guide/decision/test_followup.py`
- Create: `tests/guide/presentation/test_followup_response.py`
- Modify: `tests/guide/test_public_contracts.py`

- [x] **Step 1: Write failing decision tests**

Create `tests/guide/decision/test_followup.py` with this preamble:

```python
from decimal import Decimal

from app.guide.decision.contracts import DecisionProductFacts, FactState
from app.guide.decision.followup import decide_followup
from app.guide.feedback.contracts import (
    ConversationSnapshot,
    DisplayedCandidateRef,
)
from app.guide.intent.contracts import FollowupPlan
from app.guide.understanding.contracts import FollowupAction


class MemoryFacts:
    def __init__(self, products: list[DecisionProductFacts]) -> None:
        self._products = {
            product.product_id: product
            for product in products
        }

    def get_decision_facts(
        self,
        product_id: int,
    ) -> DecisionProductFacts:
        return self._products[product_id].model_copy(deep=True)


def facts(
    product_id: int,
    price: str | None,
    price_state: FactState = FactState.KNOWN,
) -> DecisionProductFacts:
    return DecisionProductFacts(
        product_id=product_id,
        price=Decimal(price) if price is not None else None,
        price_state=price_state,
        efficacy=None,
        efficacy_state=FactState.UNKNOWN,
        suitable_skin=None,
        suitable_skin_state=FactState.UNKNOWN,
        ingredients_present=None,
        ingredients_present_state=FactState.UNKNOWN,
        verified_absences=None,
        verified_absences_state=FactState.UNKNOWN,
    )


def snapshot() -> ConversationSnapshot:
    return ConversationSnapshot(
        session_id="s-1",
        version=1,
        candidates=[
            DisplayedCandidateRef(
                product_id=91,
                ordinal=1,
                skin_match="unknown",
                matched_efficacies=["修护"],
            ),
            DisplayedCandidateRef(
                product_id=38,
                ordinal=2,
                skin_match="unknown",
                matched_efficacies=["修护"],
            ),
        ],
    )
```

Add these assertions after the preamble:

```python
def test_ordinal_selects_exact_snapshot_position() -> None:
    result = decide_followup(
        MemoryFacts([facts(91, "88"), facts(38, "294")]),
        snapshot(),
        FollowupPlan(
            mode="followup",
            action=FollowupAction.ORDINAL_REFERENCE,
            ordinal=2,
        ),
    )
    assert result.status == "selected"
    assert result.ordinal == 2
    assert result.source_candidate_ids == [91, 38]
    assert result.selected_product_ids == [38]
    assert "ordinal=2" in result.evidence_refs


def test_cheapest_uses_only_snapshot_prices() -> None:
    result = decide_followup(
        MemoryFacts([
            facts(91, "88"),
            facts(38, "294"),
            facts(999, "1"),
        ]),
        snapshot(),
        FollowupPlan(
            mode="followup",
            action=FollowupAction.CHEAPEST,
        ),
    )
    assert result.status == "selected"
    assert result.selected_product_ids == [91]
    assert 999 not in result.source_candidate_ids


def test_cheapest_handles_tie_and_missing_prices() -> None:
    tied = decide_followup(
        MemoryFacts([facts(91, "88"), facts(38, "88")]),
        snapshot(),
        FollowupPlan(
            mode="followup",
            action=FollowupAction.CHEAPEST,
        ),
    )
    assert tied.status == "tied"
    assert tied.selected_product_ids == [91, 38]

    unavailable = decide_followup(
        MemoryFacts([
            facts(91, None, FactState.UNKNOWN),
            facts(38, None, FactState.CONFLICT),
        ]),
        snapshot(),
        FollowupPlan(
            mode="followup",
            action=FollowupAction.CHEAPEST,
        ),
    )
    assert unavailable.status == "insufficient_evidence"
    assert unavailable.selected_product_ids == []
```

- [x] **Step 2: Write failing presentation tests**

Create `tests/guide/presentation/test_followup_response.py`:

```python
from decimal import Decimal

from app.guide.decision.contracts import FollowupDecisionResult
from app.guide.feedback.contracts import (
    ConversationSnapshot,
    DisplayedCandidateRef,
)
from app.guide.presentation.contracts import ProductCardFacts
from app.guide.presentation.followup_response import (
    build_followup_cards,
    build_followup_message,
)
from app.guide.understanding.contracts import FollowupAction


def snapshot() -> ConversationSnapshot:
    return ConversationSnapshot(
        session_id="s-1",
        version=1,
        candidates=[
            DisplayedCandidateRef(
                product_id=91,
                ordinal=1,
                skin_match="unknown",
                matched_efficacies=["修护"],
            ),
            DisplayedCandidateRef(
                product_id=38,
                ordinal=2,
                skin_match="unknown",
                matched_efficacies=["修护"],
            ),
        ],
    )


def presentation_facts(
    product_id: int,
    name: str,
) -> ProductCardFacts:
    return ProductCardFacts(
        product_id=product_id,
        name=name,
        brand="测试品牌",
        category="精华",
        price=Decimal("88") if product_id == 91 else Decimal("294"),
        fact_warnings=[],
    )


def ordinal_result() -> FollowupDecisionResult:
    return FollowupDecisionResult(
        action=FollowupAction.ORDINAL_REFERENCE,
        ordinal=2,
        status="selected",
        source_candidate_ids=[91, 38],
        selected_product_ids=[38],
        evidence_refs=["ordinal=2"],
    )


def cheapest_result() -> FollowupDecisionResult:
    return FollowupDecisionResult(
        action=FollowupAction.CHEAPEST,
        ordinal=None,
        status="selected",
        source_candidate_ids=[91, 38],
        selected_product_ids=[91],
        evidence_refs=["price_min=88"],
    )


def test_ordinal_card_preserves_snapshot_evidence() -> None:
    cards = build_followup_cards(
        ordinal_result(),
        snapshot=snapshot(),
        product_facts={38: presentation_facts(38, "理肤泉新B5多效修护精华")},
    )
    assert [card.product_id for card in cards] == [38]
    assert cards[0].skin_match == "unknown"
    assert cards[0].matched_efficacies == ["修护"]


def test_followup_messages_do_not_claim_comprehensive_winner() -> None:
    ordinal = build_followup_message(
        ordinal_result(),
        product_facts={38: presentation_facts(38, "理肤泉新B5多效修护精华")},
    )
    assert "第二款" in ordinal
    assert "综合最适合" not in ordinal

    cheapest = build_followup_message(
        cheapest_result(),
        product_facts={91: presentation_facts(91, "玉泽修护精华")},
    )
    assert "审核参考价最低" in cheapest
    assert "不代表综合适配更好" in cheapest
```

- [x] **Step 3: Run tests and verify RED**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/decision/test_followup.py \
  tests/guide/presentation/test_followup_response.py
```

Expected: collection fails because follow-up decision and presentation modules
do not exist.

- [x] **Step 4: Add follow-up decision contract**

In `app/guide/decision/contracts.py`, add:

```python
class FollowupDecisionResult(_StrictContract):
    action: FollowupAction
    ordinal: int | None = Field(default=None, ge=1, le=3)
    status: Literal["selected", "tied", "insufficient_evidence"]
    source_candidate_ids: list[int] = Field(min_length=1, max_length=3)
    selected_product_ids: list[int] = Field(max_length=3)
    evidence_refs: list[str]

    @model_validator(mode="after")
    def validate_selection(self) -> Self:
        if self.action is FollowupAction.ORDINAL_REFERENCE:
            if self.ordinal is None:
                raise ValueError("ordinal result requires ordinal")
        elif self.ordinal is not None:
            raise ValueError("cheapest result forbids ordinal")
        if self.status == "insufficient_evidence":
            if self.selected_product_ids:
                raise ValueError("insufficient evidence forbids selection")
        elif not self.selected_product_ids:
            raise ValueError("selected or tied status requires products")
        if not set(self.selected_product_ids) <= set(
            self.source_candidate_ids
        ):
            raise ValueError("selected product must come from snapshot")
        return self
```

Import `Field` and `FollowupAction` in the existing import blocks.

- [x] **Step 5: Implement snapshot-only decision**

Create `app/guide/decision/followup.py`:

```python
from decimal import Decimal

from app.guide.decision.contracts import (
    FactState,
    FollowupDecisionResult,
)
from app.guide.decision.ports import DecisionFactPort
from app.guide.feedback.contracts import ConversationSnapshot
from app.guide.intent.contracts import FollowupPlan
from app.guide.understanding.contracts import FollowupAction


def decide_followup(
    facts: DecisionFactPort,
    snapshot: ConversationSnapshot,
    plan: FollowupPlan,
) -> FollowupDecisionResult:
    source_ids = [item.product_id for item in snapshot.candidates]
    if plan.mode != "followup" or plan.action is None:
        raise ValueError("decision requires followup plan")
    if plan.action is FollowupAction.ORDINAL_REFERENCE:
        assert plan.ordinal is not None
        selected = snapshot.candidates[plan.ordinal - 1].product_id
        return FollowupDecisionResult(
            action=plan.action,
            ordinal=plan.ordinal,
            status="selected",
            source_candidate_ids=source_ids,
            selected_product_ids=[selected],
            evidence_refs=[f"ordinal={plan.ordinal}"],
        )

    priced: list[tuple[int, Decimal]] = []
    for product_id in source_ids:
        product = facts.get_decision_facts(product_id)
        if (
            product.price_state is FactState.KNOWN
            and product.price is not None
        ):
            priced.append((product_id, product.price))
    if not priced:
        return FollowupDecisionResult(
            action=plan.action,
            ordinal=None,
            status="insufficient_evidence",
            source_candidate_ids=source_ids,
            selected_product_ids=[],
            evidence_refs=["price_evidence=unavailable"],
        )
    minimum = min(price for _, price in priced)
    selected_ids = [
        product_id
        for product_id, price in priced
        if price == minimum
    ]
    return FollowupDecisionResult(
        action=plan.action,
        ordinal=None,
        status="tied" if len(selected_ids) > 1 else "selected",
        source_candidate_ids=source_ids,
        selected_product_ids=selected_ids,
        evidence_refs=[f"price_min={minimum}"],
    )
```

- [x] **Step 6: Implement evidence-preserving presentation**

Create `app/guide/presentation/followup_response.py`:

```python
from app.guide.decision.contracts import FollowupDecisionResult
from app.guide.feedback.contracts import ConversationSnapshot
from app.guide.presentation.contracts import ProductCard, ProductCardFacts
from app.guide.understanding.contracts import FollowupAction


_ORDINAL_LABELS = {
    1: "第一款",
    2: "第二款",
    3: "第三款",
}


def build_followup_cards(
    result: FollowupDecisionResult,
    *,
    snapshot: ConversationSnapshot,
    product_facts: dict[int, ProductCardFacts],
) -> list[ProductCard]:
    references = {
        item.product_id: item for item in snapshot.candidates
    }
    cards: list[ProductCard] = []
    for product_id in result.selected_product_ids:
        reference = references[product_id]
        facts = product_facts[product_id]
        cards.append(
            ProductCard(
                product_id=product_id,
                name=facts.name,
                brand=facts.brand,
                category=facts.category,
                price=facts.price,
                image_url=facts.image_url,
                detail_url=facts.detail_url,
                platform=facts.platform,
                image_source_sha256=facts.image_source_sha256,
                skin_match=reference.skin_match,
                matched_efficacies=list(
                    reference.matched_efficacies
                ),
                fact_warnings=list(facts.fact_warnings),
            )
        )
    return cards


def build_followup_message(
    result: FollowupDecisionResult,
    *,
    product_facts: dict[int, ProductCardFacts],
) -> str:
    if result.status == "insufficient_evidence":
        return "这些候选缺少可比较的审核价格，暂时无法判断哪款更便宜。"
    names = [
        product_facts[product_id].name or f"商品 {product_id}"
        for product_id in result.selected_product_ids
    ]
    if result.action is FollowupAction.ORDINAL_REFERENCE:
        assert result.ordinal is not None
        label = _ORDINAL_LABELS[result.ordinal]
        return (
            f"你问的是{label}：{names[0]}。"
            f"这是上一轮展示顺序中的{label}。"
        )
    joined = "、".join(names)
    if result.status == "tied":
        return (
            f"这几款里，{joined} 的审核参考价并列最低；"
            "这只代表价格维度，不代表综合适配更好。"
        )
    return (
        f"这几款里，{joined} 的审核参考价最低；"
        "这只代表价格维度，不代表综合适配更好。"
    )
```

- [x] **Step 7: Run decision and presentation tests**

Export `FollowupDecisionResult` from `app/guide/decision/__init__.py`.
Add it to `CONTRACT_MODULES` and add this valid payload:

```python
"FollowupDecisionResult": {
    "action": importlib.import_module(
        "app.guide.understanding"
    ).FollowupAction.ORDINAL_REFERENCE,
    "ordinal": 2,
    "status": "selected",
    "source_candidate_ids": [91, 38],
    "selected_product_ids": [38],
    "evidence_refs": ["ordinal=2"],
},
```

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/decision \
  tests/guide/presentation \
  tests/guide/test_public_contracts.py
python3 app/guide/check_boundaries.py app/guide
shasum -a 256 app/guide/decision/deterministic_ranking.py
```

Expected: tests pass, boundary passes, ranking SHA is unchanged.

- [x] **Step 8: Commit**

```bash
git add \
  app/guide/decision/contracts.py \
  app/guide/decision/__init__.py \
  app/guide/decision/followup.py \
  app/guide/presentation/followup_response.py \
  tests/guide/decision/test_followup.py \
  tests/guide/presentation/test_followup_response.py \
  tests/guide/test_public_contracts.py
git commit -m "feat(decision): resolve snapshot-only followups"
```

---

### Task 4: Integrate State, Versions and Follow-up SSE

**Files:**
- Modify: `app/guide/presentation/sse_events.py`
- Modify: `app/guide/application/text_recommendation_flow.py`
- Modify: `app/guide/application/chat_api_adapter.py`
- Modify: `tests/guide/application/conftest.py`
- Modify: `tests/guide/application/test_text_recommendation_flow.py`
- Modify: `tests/guide/application/test_chat_api_adapter.py`
- Modify: `tests/guide/test_public_contracts.py`

- [x] **Step 1: Write failing application tests**

Add a shared injected `InMemoryConversationState` fixture. Add tests:

```python
def test_recommendation_saves_only_visible_candidates(
    orchestrator,
    conversation_state,
) -> None:
    events = list(
        orchestrator.stream(
            _turn(
                "500 内适合油敏肌的防晒",
                conversation_version=0,
            )
        )
    )
    snapshot = conversation_state.load("s-1")
    assert [item.product_id for item in snapshot.candidates] == [55, 57, 54]
    end = events[-1]
    assert end.event == "end"
    assert end.data.conversation_version == 1


def test_ordinal_followup_uses_snapshot_without_retrieval(
    orchestrator,
    conversation_state,
    monkeypatch,
) -> None:
    list(orchestrator.stream(_turn("500 元内敏感肌修护精华")))

    def forbidden_retrieval(*args, **kwargs):
        raise AssertionError("followup must not retrieve")

    monkeypatch.setattr(
        "app.guide.application.text_recommendation_flow.retrieve_candidates",
        forbidden_retrieval,
    )
    events = list(
        orchestrator.stream(
            _turn("第二款呢", conversation_version=1)
        )
    )
    products = next(item for item in events if item.event == "products")
    assert [card.product_id for card in products.data.cards] == [38]
    assert events[-1].data.conversation_version == 2


def test_cheapest_followup_uses_snapshot_without_retrieval(
    orchestrator,
    monkeypatch,
) -> None:
    list(orchestrator.stream(_turn("500 元内敏感肌修护精华")))
    monkeypatch.setattr(
        "app.guide.application.text_recommendation_flow.retrieve_candidates",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("followup must not retrieve")
        ),
    )
    events = list(
        orchestrator.stream(
            _turn("哪个更便宜", conversation_version=1)
        )
    )
    products = next(item for item in events if item.event == "products")
    assert [card.product_id for card in products.data.cards] == [91]
    message = next(item for item in events if item.event == "message")
    assert "不代表综合适配更好" in message.data.content


def test_missing_snapshot_stale_version_and_out_of_range_clarify(
    orchestrator,
) -> None:
    missing = list(
        orchestrator.stream(
            _turn("第二款呢", conversation_version=1)
        )
    )
    assert "最近一轮候选" in next(
        item for item in missing if item.event == "clarify"
    ).data.question
    assert missing[-1].data.conversation_version == 0


def test_terminal_error_does_not_write_conversation_state(
    broken_orchestrator,
    conversation_state,
) -> None:
    events = list(
        broken_orchestrator.stream(
            _turn("500 元内敏感肌修护精华")
        )
    )
    assert events[-1].event == "error"
    assert conversation_state.load("s-1") is None
```

Extend `_turn` to accept `conversation_version`.

- [x] **Step 2: Write failing SSE contract tests**

Update public payloads and add assertions:

```python
def test_end_event_requires_conversation_version() -> None:
    event = EndEvent(data=EndData(conversation_version=2))
    assert event.data.conversation_version == 2


def test_followup_stream_omits_fake_winner_events(orchestrator) -> None:
    list(orchestrator.stream(_turn("500 元内敏感肌修护精华")))
    events = list(
        orchestrator.stream(
            _turn("第二款呢", conversation_version=1)
        )
    )
    names = [item.event for item in events]
    assert names == [
        "start",
        "stage",
        "intent",
        "products",
        "message",
        "end",
    ]
```

- [x] **Step 3: Run tests and verify RED**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/application \
  tests/guide/test_public_contracts.py
```

Expected: missing state injection, follow-up flow and EndData failures.

- [x] **Step 4: Extend typed SSE**

In `app/guide/presentation/sse_events.py`:

```python
class StageData(_Strict):
    stage: Literal["understanding", "retrieval", "decision", "state"]
    summary: str


class IntentData(_Strict):
    mode: Literal["recommend", "clarify", "followup"]


class EndData(_Strict):
    conversation_version: int = Field(ge=0)
```

Change `EndEvent.data` from `EmptyData` to `EndData`. Update every existing
`EndEvent` constructor to pass the authoritative version.

In `chat_api_adapter._to_legacy_data`, map `EndEvent` to:

```python
return {"conversation_version": event.data.conversation_version}
```

- [x] **Step 5: Inject conversation state**

Extend `TextRecommendationOrchestrator.__init__` with
`conversation_state: ConversationStatePort`.

Extend `build_text_recommendation_orchestrator` with optional
`conversation_state`. When omitted, create one
`InMemoryConversationState` for that orchestrator instance.

Update application fixtures to construct and inject one shared store per test:

```python
@pytest.fixture
def conversation_state():
    return InMemoryConversationState()


@pytest.fixture
def orchestrator(real_reader, real_product_assets, conversation_state):
    return build_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
    )


@pytest.fixture
def broken_orchestrator(conversation_state):
    return build_text_recommendation_orchestrator(
        BrokenReader(),
        conversation_state=conversation_state,
    )
```

- [x] **Step 6: Add authoritative version helpers**

Add to `TextRecommendationOrchestrator`:

```python
def _snapshot_version(
    self,
    snapshot: ConversationSnapshot | None,
) -> int:
    return snapshot.version if snapshot is not None else 0


def _visible_snapshot(
    self,
    turn: UserTurn,
    cards: list[ProductCard],
    *,
    version: int,
) -> ConversationSnapshot:
    return ConversationSnapshot(
        session_id=turn.session_id,
        version=version,
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

Before a regular recommendation:

- load snapshot;
- if snapshot exists and request version differs, emit clarification and
  `EndData(snapshot.version)`;
- if snapshot is missing, accept a complete new query even when client version
  is stale and use expected version 0.

After building the response plan, validate feedback before changing state:

```python
status = self._feedback.record_turn(turn)
if status is not FeedbackWriteStatus.SKIPPED_SLICE_SCOPE:
    raise RuntimeError("unexpected feedback write status")
```

Remove the old feedback call after `MessageEvent`.

Before emitting cards, write state only when at least one card will be
displayed:

```python
expected_version = self._snapshot_version(snapshot)
if plan.structured_events:
    saved_snapshot = self._conversation_state.save(
        self._visible_snapshot(
            turn,
            list(plan.structured_events),
            version=expected_version + 1,
        ),
        expected_version=expected_version,
    )
    response_version = saved_snapshot.version
else:
    response_version = expected_version
```

Emit `EndData(response_version)`.

If task mode is clarify, do not write state and emit the authoritative current
version.

- [x] **Step 7: Add the follow-up branch**

Immediately after `StartEvent`, load state and parse the message:

```python
snapshot = self._conversation_state.load(turn.session_id)
followup_draft = parse_followup(turn.message)
followup_plan = plan_followup(
    followup_draft,
    snapshot=snapshot,
    request_version=turn.conversation_version,
)
if followup_plan is not None:
    yield from self._stream_followup(
        turn,
        snapshot=snapshot,
        plan=followup_plan,
    )
    return
```

Implement `_stream_followup`:

```python
def _stream_followup(
    self,
    turn: UserTurn,
    *,
    snapshot: ConversationSnapshot | None,
    plan: FollowupPlan,
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
    result = decide_followup(
        self._decision_facts,
        snapshot,
        plan,
    )
    if result.status == "insufficient_evidence":
        yield ClarifyEvent(
            data=ClarifyData(
                question=(
                    "这些候选缺少可比较的审核价格，"
                    "暂时无法判断哪款更便宜。"
                )
            )
        )
        yield EndEvent(
            data=EndData(
                conversation_version=authoritative_version
            )
        )
        return
    facts = {
        product_id: self._presentation_facts.get_presentation_facts(
            product_id
        )
        for product_id in result.selected_product_ids
    }
    cards = build_followup_cards(
        result,
        snapshot=snapshot,
        product_facts=facts,
    )
    message = build_followup_message(
        result,
        product_facts=facts,
    )
    status = self._feedback.record_turn(turn)
    if status is not FeedbackWriteStatus.SKIPPED_SLICE_SCOPE:
        raise RuntimeError("unexpected feedback write status")
    next_snapshot = snapshot.model_copy(
        update={"version": snapshot.version + 1},
        deep=True,
    )
    saved = self._conversation_state.save(
        next_snapshot,
        expected_version=snapshot.version,
    )
    yield StageEvent(
        data=StageData(
            stage="state",
            summary="已读取最近一次展示的候选商品。",
        )
    )
    yield IntentEvent(data=IntentData(mode="followup"))
    yield ProductsEvent(data=ProductsData(cards=cards))
    yield MessageEvent(
        data=MessageData(content=message)
    )
    yield EndEvent(
        data=EndData(conversation_version=saved.version)
    )
```

Add this branch before the existing generic exception handler:

```python
        except ConversationStateConflict:
            latest = self._conversation_state.load(turn.session_id)
            yield ClarifyEvent(
                data=ClarifyData(
                    question=(
                        "会话状态已变化，请基于最新结果重试。"
                    )
                )
            )
            yield EndEvent(
                data=EndData(
                    conversation_version=self._snapshot_version(
                        latest
                    )
                )
            )
```

The generic exception branch remains terminal `GUIDE_INTERNAL_ERROR`.

- [x] **Step 8: Run application and SSE tests**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/application \
  tests/guide/presentation \
  tests/guide/test_public_contracts.py
python3 app/guide/check_boundaries.py app/guide
```

Expected: all selected tests pass.

- [x] **Step 9: Commit**

```bash
git add \
  app/guide/presentation/sse_events.py \
  app/guide/application/text_recommendation_flow.py \
  app/guide/application/chat_api_adapter.py \
  tests/guide/application \
  tests/guide/test_public_contracts.py
git commit -m "feat(application): stream versioned candidate followups"
```

---

### Task 5: Wire Runtime Version Transport and Frontend State

**Files:**
- Modify: `app/guide_runtime/composition.py`
- Modify: `app/guide_runtime/contracts.py`
- Modify: `app/guide_runtime/sse.py`
- Modify: `app/guide_runtime/app.py`
- Modify: `app/static/chat.html`
- Modify: `tests/guide/runtime/test_runtime_http.py`
- Modify: `tests/guide/runtime/test_frontend_scope.py`

- [x] **Step 1: Write failing HTTP version tests**

Add:

```python
def test_http_round_trips_followup_conversation_version() -> None:
    client = TestClient(create_app())
    first = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "500 元内敏感肌修护精华",
            "session_id": "followup-http",
            "conversation_version": 0,
        },
    )
    first_events = _events(first)
    assert first_events[-1] == (
        "end",
        {"conversation_version": 1},
    )

    second = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "第二款呢",
            "session_id": "followup-http",
            "conversation_version": 1,
        },
    )
    second_events = _events(second)
    products = next(
        data for name, data in second_events if name == "products"
    )
    assert [item["id"] for item in products["products"]] == [38]
    assert second_events[-1] == (
        "end",
        {"conversation_version": 2},
    )
```

Add stale/missing snapshot HTTP tests and assert `/health` contains:

```json
{
  "capabilities": [
    "sunscreen",
    "repair_serum",
    "recent_candidate_followup"
  ],
  "conversation_state": "process_local"
}
```

Add:

```python
def test_runtime_app_instances_do_not_share_conversation_state() -> None:
    first = TestClient(create_app())
    second = TestClient(create_app())
    first.post(
        "/api/v1/chat/stream",
        json={
            "message": "500 元内敏感肌修护精华",
            "session_id": "isolated-session",
            "conversation_version": 0,
        },
    )
    response = second.post(
        "/api/v1/chat/stream",
        json={
            "message": "第二款呢",
            "session_id": "isolated-session",
            "conversation_version": 1,
        },
    )
    events = _events(response)
    message = next(data for name, data in events if name == "message")
    assert "最近一轮候选" in message["content"]
```

- [x] **Step 2: Write failing frontend static tests**

Assert `chat.html` contains:

```text
lumi_conversation_versions_v1
getConversationVersion
setConversationVersion
conversation_version
eventName === 'end'
```

Also assert deleting a session removes its version entry.

- [x] **Step 3: Run tests and verify RED**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/runtime/test_runtime_http.py \
  tests/guide/runtime/test_frontend_scope.py
```

Expected: request contract, health capability and frontend version failures.

- [x] **Step 4: Add runtime request transport**

In `app/guide_runtime/composition.py`, construct and inject:

```python
conversation_state=InMemoryConversationState(),
```

Import the adapter from `app.guide.adapters.state`.

In `ChatStreamRequest` add:

```python
conversation_version: int = Field(default=0, ge=0)
```

Pass it into `UserTurn` in `iter_http_events`:

```python
conversation_version=payload.conversation_version,
```

Ensure image rejection ends with the request version:

```python
yield "end", {
    "conversation_version": payload.conversation_version,
}
```

- [x] **Step 5: Declare runtime capability honestly**

Add `"recent_candidate_followup"` to `RUNTIME_CAPABILITIES`.

Add to `/health`:

```python
"conversation_state": "process_local",
```

Update the health return annotation to include all returned value types.

- [x] **Step 6: Add frontend version storage**

Add to `STORAGE_KEYS`:

```javascript
conversationVersions: 'lumi_conversation_versions_v1'
```

Add:

```javascript
function getConversationVersion(sessionId = getSessionId()) {
    const versions = loadStoredJson(
        STORAGE_KEYS.conversationVersions,
        {}
    );
    const value = Number(versions[sessionId] ?? 0);
    return Number.isInteger(value) && value >= 0 ? value : 0;
}

function setConversationVersion(sessionId, version) {
    const numeric = Number(version);
    if (!Number.isInteger(numeric) || numeric < 0) return;
    const versions = loadStoredJson(
        STORAGE_KEYS.conversationVersions,
        {}
    );
    versions[sessionId] = numeric;
    saveStoredJson(STORAGE_KEYS.conversationVersions, versions);
}

function clearConversationVersion(sessionId) {
    const versions = loadStoredJson(
        STORAGE_KEYS.conversationVersions,
        {}
    );
    delete versions[sessionId];
    saveStoredJson(STORAGE_KEYS.conversationVersions, versions);
}
```

Build request body with one stable session value:

```javascript
const sessionId = getSessionId();
const bodyPayload = {
    message: text,
    session_id: sessionId,
    conversation_version: getConversationVersion(sessionId),
    stream: true
};
```

In the `end` branch:

```javascript
if (Number.isInteger(data.conversation_version)) {
    setConversationVersion(
        getSessionId(),
        data.conversation_version
    );
}
```

In `deleteSession`, call `clearConversationVersion(sessionId)` before creating
or rendering another session.

- [x] **Step 7: Run runtime and boundary tests**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/runtime
python3 app/guide/check_boundaries.py app/guide
python3 app/guide/check_boundaries.py app/guide_runtime
git diff --check
```

Expected: runtime tests and both boundary scans pass.

- [x] **Step 8: Commit**

```bash
git add \
  app/guide_runtime/composition.py \
  app/guide_runtime/contracts.py \
  app/guide_runtime/sse.py \
  app/guide_runtime/app.py \
  app/static/chat.html \
  tests/guide/runtime/test_runtime_http.py \
  tests/guide/runtime/test_frontend_scope.py
git commit -m "feat(runtime): transport followup conversation versions"
```

---

### Task 6: Lock the Two-Turn Real-Data and Browser Gates

**Files:**
- Modify: `tests/guide/runtime/test_composition.py`
- Modify: `tests/guide/application/test_slice1_backend_gate.py`
- Modify: `tools/guide_gates/runtime_browser_smoke.py`
- Modify: `docs/superpowers/plans/2026-08-07-slice1-recent-candidate-followup.md`

- [x] **Step 1: Add a real-data two-turn backend gate**

Add a dedicated test:

```python
def test_recent_candidate_followup_gate(orchestrator) -> None:
    first = list(
        orchestrator.stream(
            UserTurn(
                session_id="gate-followup",
                message="500 元内敏感肌修护精华",
                image_bundle_id=None,
                conversation_version=0,
            )
        )
    )
    assert first[-1].data.conversation_version == 1

    second = list(
        orchestrator.stream(
            UserTurn(
                session_id="gate-followup",
                message="第二款呢",
                image_bundle_id=None,
                conversation_version=1,
            )
        )
    )
    products = next(
        item for item in second if item.event == "products"
    )
    assert [card.product_id for card in products.data.cards] == [38]
    assert second[-1].data.conversation_version == 2
```

Add a `/tmp` composition test proving the same orchestrator instance retains
state while cwd is outside the repository.

- [x] **Step 2: Extend the Playwright browser gate**

After the existing repair-serum card assertions, send:

```python
page.fill("#chatInput", "第二款呢")
page.click("#sendBtn")
panels = page.locator(".recommendation-panel")
expect(panels.nth(1)).to_be_visible(timeout=20000)
latest_cards = panels.nth(1).locator(".recommendation-card")
assert latest_cards.count() == 1
expect(latest_cards.first).to_contain_text("理肤泉新B5多效修护精华")
expect(panels.nth(1)).to_contain_text("第二款")
```

Read local storage and assert the active session version is 2:

```python
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

Keep all existing sunscreen, repair serum, image, link, pageerror,
failed-image and hidden-feedback assertions.

- [x] **Step 3: Run the full locked gate**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  -c pytest-guide.ini
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/runtime
python3 app/guide/check_boundaries.py app/guide
python3 app/guide/check_boundaries.py app/guide_runtime
git diff --check
```

Expected: all tests pass and both boundary scans report zero violations.

- [x] **Step 4: Run the formal browser gate**

Run:

```bash
python3 /Users/bytedance/.trae-cn/skills/webapp-testing/scripts/with_server.py \
  --server "cd /tmp && PYTHONPATH=/Users/bytedance/Desktop/xiaoro-fresh exec /tmp/xiaoro-guide-runtime-venv/bin/uvicorn app.guide_runtime.app:app --host 127.0.0.1 --port 8765" \
  --port 8765 \
  -- python3 tools/guide_gates/runtime_browser_smoke.py \
    --screenshot /tmp/xiaoro-guide-recent-followup.png
```

Expected: exit 0, no listener remains on port 8765, and screenshot exists.

- [x] **Step 5: Confirm protected files and hashes**

Run:

```bash
git diff --name-only 5c43021..HEAD
git diff --name-only 5c43021..HEAD -- \
  app/main.py app/api/v1/chat.py app/services app/database \
  data/canonical app/guide/decision/deterministic_ranking.py
shasum -a 256 app/guide/decision/deterministic_ranking.py
lsof -nP -iTCP:8765 -sTCP:LISTEN
```

Expected:

- protected-path diff is empty;
- ranking SHA remains locked;
- final `lsof` prints no listener.

- [x] **Step 6: Commit release gates**

```bash
git add \
  tests/guide/runtime/test_composition.py \
  tests/guide/application/test_slice1_backend_gate.py \
  tools/guide_gates/runtime_browser_smoke.py \
  docs/superpowers/plans/2026-08-07-slice1-recent-candidate-followup.md
git commit -m "test(guide): gate recent candidate followups"
```

---

## Final Acceptance Checklist

- [x] Snapshot contains only the latest visible 1..3 candidates.
- [x] Snapshot ordinals are contiguous and product IDs unique.
- [x] In-memory store enforces CAS, TTL and 512-session capacity.
- [x] Store instances do not share process state.
- [x] `第二款呢` resolves exact ordinal 2.
- [x] `哪个更便宜` only compares snapshot IDs.
- [x] Ambiguous pronouns clarify instead of guessing.
- [x] Missing snapshot, stale version and out-of-range ordinal clarify.
- [x] Follow-ups do not execute retrieval.
- [x] Follow-up stream does not emit fake winner events.
- [x] Successful turns increment conversation version.
- [x] Clarifications return authoritative version without increment.
- [x] Terminal errors do not update state or emit end.
- [x] Frontend stores versions per session and sends them back.
- [x] `/health` declares `recent_candidate_followup` and `process_local`.
- [x] Browser completes the real two-turn serum flow.
- [x] Original sunscreen and repair-serum gates remain unchanged.
- [x] Canonical, old API, old services and database remain untouched.
- [x] Deterministic ranking SHA remains locked.
- [x] Full guide gate and both architecture scans pass.

## Stop Condition

本计划完成后停止，不顺带实现改预算、改肤质、换一批、跳回旧轮、图片、长期
画像、数据库或模型能力。下一阶段单独设计“改条件再筛选”。
