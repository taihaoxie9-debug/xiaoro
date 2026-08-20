# Guide 唯一入口 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让所有默认启动方式、公开 message/stream 和失败路径只进入 Guide，并持久化两轮澄清进度。

**Architecture:** 保留 `app.guide_runtime.app` 作为唯一 FastAPI 应用。文本澄清进度进入现有 `ConversationSnapshot` 和 SQLite CAS；公开终态送达后才提交。Guide-only focused gate 通过后，再由集成计划删除旧聊天模块。

**Tech Stack:** Python 3.11、FastAPI、Pydantic v2、SQLite WAL/CAS、pytest、SSE

---

## 文件边界

本计划 writer 独占以下文件：

- `app/guide/feedback/contracts.py`
- `app/guide/feedback/clarification_progress.py`（新建）
- `app/guide/feedback/ports.py`
- `app/guide/understanding/context_resolver.py`
- `app/guide/intent/contracts.py`
- `app/guide/intent/task_planning.py`
- `app/guide/application/text_recommendation_flow.py`
- `app/guide/application/chat_api_adapter.py`
- `app/guide_runtime/sse.py`
- `app/guide_runtime/app.py`
- `docker-compose.yml`
- `docker-compose.prod.yml`
- `start.sh`
- `README.md`
- `DEPLOY.md`
- 对应 `tests/guide/**`

不要在本计划修改 `app/guide_runtime/composition.py`、语义模型合同、数据工具、tasks/checklist/progress 或删除旧源码；这些属于其他 track 或 Integration Writer。

### Task 1: 定义澄清进度合同

**Files:**
- Modify: `app/guide/feedback/contracts.py:126-187`
- Modify: `app/guide/feedback/ports.py:34-43`
- Test: `tests/guide/feedback/test_conversation_state_contracts.py`

- [ ] **Step 1: 写澄清合同 RED**

在 `tests/guide/feedback/test_conversation_state_contracts.py` 增加：

```python
from app.guide.feedback.contracts import ClarificationProgress
from app.guide.understanding.semantic_contracts import ClarificationCode


def test_snapshot_accepts_clarification_only_state() -> None:
    snapshot = ConversationSnapshot(
        session_id="clarification-only",
        version=1,
        clarification=ClarificationProgress(
            gap=ClarificationCode.TOPIC,
            attempts=1,
        ),
    )
    assert snapshot.query_context is None
    assert snapshot.candidates == ()
    assert snapshot.clarification.attempts == 1


def test_clarification_progress_is_typed_and_bounded() -> None:
    with pytest.raises(ValidationError):
        ClarificationProgress(
            gap=ClarificationCode.TOPIC,
            attempts=0,
        )
    with pytest.raises(ValidationError):
        ClarificationProgress(
            gap=ClarificationCode.TOPIC,
            attempts=3,
        )
```

- [ ] **Step 2: 运行 RED**

Run:

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/feedback/test_conversation_state_contracts.py
```

Expected: collection fails because `ClarificationProgress` does not exist.

- [ ] **Step 3: 实现严格合同**

在 `app/guide/feedback/contracts.py` 增加：

```python
from app.guide.understanding.semantic_contracts import ClarificationCode


class ClarificationProgress(_StrictContract):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    gap: ClarificationCode
    attempts: int = Field(ge=1, le=2)
```

在 `ConversationSnapshot` 增加：

```python
clarification: ClarificationProgress | None = None
```

将“快照必须有推荐、问诊或图片状态”的 validator 改成：

```python
if (
    not has_candidates
    and self.consultation is None
    and not self.has_image_delivery
    and self.clarification is None
):
    raise ValueError(
        "snapshot requires recommendation, consultation, "
        "image delivery, or clarification state"
    )
```

- [ ] **Step 4: 增加状态转换约束**

在 `app/guide/feedback/ports.py` 的
`validate_conversation_state_transition()` 中调用：

```python
_validate_clarification_transition(
    current.clarification if current is not None else None,
    replacement.clarification,
)
```

新增完整函数：

```python
def _validate_clarification_transition(
    previous: ClarificationProgress | None,
    replacement: ClarificationProgress | None,
) -> None:
    if replacement is None:
        return
    if previous is None:
        if replacement.attempts != 1:
            raise ValueError("clarification must start at attempt one")
        return
    if replacement.gap is previous.gap:
        if replacement.attempts not in {
            previous.attempts,
            min(previous.attempts + 1, 2),
        }:
            raise ValueError(
                "clarification attempts must advance monotonically"
            )
        return
    if replacement.attempts != 1:
        raise ValueError("a new clarification gap starts at attempt one")
```

导入 `ClarificationProgress`，并增加以下测试：

```python
def test_clarification_transition_advances_or_resets_gap() -> None:
    first = ClarificationProgress(
        gap=ClarificationCode.TOPIC,
        attempts=1,
    )
    second = ClarificationProgress(
        gap=ClarificationCode.TOPIC,
        attempts=2,
    )
    reset = ClarificationProgress(
        gap=ClarificationCode.REFERENCE,
        attempts=1,
    )
    validate_conversation_state_transition(
        ConversationSnapshot(
            session_id="clarify",
            version=1,
            clarification=first,
        ),
        ConversationSnapshot(
            session_id="clarify",
            version=2,
            clarification=second,
        ),
    )
    validate_conversation_state_transition(
        ConversationSnapshot(
            session_id="clarify",
            version=2,
            clarification=second,
        ),
        ConversationSnapshot(
            session_id="clarify",
            version=3,
            clarification=reset,
        ),
    )
```

- [ ] **Step 5: GREEN**

Run the Step 2 command.

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add \
  app/guide/feedback/contracts.py \
  app/guide/feedback/ports.py \
  tests/guide/feedback/test_conversation_state_contracts.py
git commit -m "feat(guide): persist typed clarification progress"
```

### Task 2: 实现澄清推进和 scope notice

**Files:**
- Create: `app/guide/feedback/clarification_progress.py`
- Modify: `app/guide/intent/contracts.py:71-85`
- Modify: `app/guide/intent/task_planning.py:32-108`
- Test: `tests/guide/intent/test_task_planning.py`
- Test: `tests/guide/feedback/test_clarification_progress.py`（新建）

- [ ] **Step 1: 写 gap 和推进 RED**

新建 `tests/guide/feedback/test_clarification_progress.py`：

```python
from app.guide.feedback.clarification_progress import (
    advance_clarification,
)
from app.guide.feedback.contracts import ClarificationProgress
from app.guide.understanding.semantic_contracts import ClarificationCode


def test_same_gap_advances_then_emits_scope_notice() -> None:
    first = advance_clarification(None, ClarificationCode.TOPIC)
    second = advance_clarification(
        first.progress,
        ClarificationCode.TOPIC,
    )
    third = advance_clarification(
        second.progress,
        ClarificationCode.TOPIC,
    )
    assert first.progress.attempts == 1
    assert second.progress.attempts == 2
    assert third.progress.attempts == 2
    assert first.scope_notice is False
    assert second.scope_notice is False
    assert third.scope_notice is True


def test_new_gap_restarts_attempts() -> None:
    result = advance_clarification(
        ClarificationProgress(
            gap=ClarificationCode.TOPIC,
            attempts=2,
        ),
        ClarificationCode.REFERENCE,
    )
    assert result.progress.gap is ClarificationCode.REFERENCE
    assert result.progress.attempts == 1
```

在 `tests/guide/intent/test_task_planning.py` 增加：

```python
def test_clarify_task_exposes_typed_gap() -> None:
    task = plan_task(understand_text("预算300以内"))
    assert task.mode == "clarify"
    assert task.clarification_code is ClarificationCode.TOPIC
```

- [ ] **Step 2: 运行 RED**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/feedback/test_clarification_progress.py \
  tests/guide/intent/test_task_planning.py
```

Expected: imports or assertions fail.

- [ ] **Step 3: 实现推进函数**

新建 `app/guide/feedback/clarification_progress.py`：

```python
from dataclasses import dataclass

from app.guide.feedback.contracts import ClarificationProgress
from app.guide.understanding.semantic_contracts import ClarificationCode


@dataclass(frozen=True, slots=True)
class ClarificationAdvance:
    progress: ClarificationProgress
    scope_notice: bool


def advance_clarification(
    current: ClarificationProgress | None,
    gap: ClarificationCode,
) -> ClarificationAdvance:
    if not isinstance(gap, ClarificationCode):
        raise TypeError("gap must be a ClarificationCode")
    if current is None or current.gap is not gap:
        return ClarificationAdvance(
            progress=ClarificationProgress(gap=gap, attempts=1),
            scope_notice=False,
        )
    if current.attempts == 1:
        return ClarificationAdvance(
            progress=ClarificationProgress(gap=gap, attempts=2),
            scope_notice=False,
        )
    return ClarificationAdvance(
        progress=current,
        scope_notice=True,
    )
```

- [ ] **Step 4: 把 typed gap 加入 TaskPlan**

在 `app/guide/intent/contracts.py`：

```python
from app.guide.understanding.semantic_contracts import ClarificationCode


class TaskPlan(_StrictContract):
    mode: Literal["recommend", "clarify"]
    referenced_image_ids: list[str]
    constraints: list[TaskConstraint]
    references: list[ReferenceDraft] = Field(default_factory=list)
    required_evidence: list[Literal["canonical_product"]]
    clarification: str | None = None
    clarification_code: ClarificationCode | None = None

    @model_validator(mode="after")
    def validate_mode(self) -> Self:
        if self.mode == "clarify":
            if not self.clarification or self.clarification_code is None:
                raise ValueError(
                    "clarify mode requires clarification and typed code"
                )
        elif (
            self.clarification is not None
            or self.clarification_code is not None
        ):
            raise ValueError(
                "recommend mode forbids clarification metadata"
            )
        return self
```

在 `task_planning.py` 的三个 clarify 返回中分别设置：

```python
clarification_code=ClarificationCode.GOAL
clarification_code=understanding_clarification_code(understanding)
clarification_code=ClarificationCode.TOPIC
```

新增闭合函数：

```python
def understanding_clarification_code(
    understanding: StructuredUnderstanding,
) -> ClarificationCode:
    issue_codes = {issue.code for issue in understanding.uncertainties}
    if issue_codes & {
        "ambiguous_reference",
        "ambiguous_candidate_reference",
        "ambiguous_image_reference",
    }:
        return ClarificationCode.REFERENCE
    if "invalid_budget" in issue_codes:
        return ClarificationCode.BUDGET
    if issue_codes & {"missing_category", "ambiguous_category"}:
        return ClarificationCode.TOPIC
    return ClarificationCode.GOAL
```

所有 `mode="recommend"` 构造无需显式传值，默认 `None`。

- [ ] **Step 5: GREEN 和兼容扫描**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/feedback/test_clarification_progress.py \
  tests/guide/intent/test_task_planning.py \
  tests/guide/application/test_text_recommendation_flow.py
```

Expected: PASS。若旧测试手工构造 clarify `TaskPlan`，必须显式补 typed code，不得放宽 validator。

- [ ] **Step 6: Commit**

```bash
git add \
  app/guide/feedback/clarification_progress.py \
  app/guide/intent/contracts.py \
  app/guide/intent/task_planning.py \
  tests/guide/feedback/test_clarification_progress.py \
  tests/guide/intent/test_task_planning.py \
  tests/guide/application/test_text_recommendation_flow.py
git commit -m "feat(guide): bound unresolved clarification turns"
```

### Task 3: 在文本流中原子保存和清零澄清

**Files:**
- Modify: `app/guide/understanding/context_resolver.py:100-121`
- Modify: `app/guide/application/text_recommendation_flow.py:377-430, 819-855`
- Test: `tests/guide/application/test_text_recommendation_flow.py`
- Test: `tests/guide/application/test_cross_worker_text_state.py`
- Test: `tests/guide/adapters/state/test_sqlite_conversation_state.py`

- [ ] **Step 1: 写三轮和成功清零 RED**

在 `test_cross_worker_text_state.py` 增加一个使用两个独立 orchestrator、同一 SQLite
目录的测试。断言：

```python
assert first_clarify.data.question != SCOPE_NOTICE
assert second_clarify.data.question != SCOPE_NOTICE
assert third_clarify.data.question == SCOPE_NOTICE
assert worker_b_state.load(session_id).clarification.attempts == 2
```

再发送成功推荐，断言：

```python
saved = worker_a_state.load(session_id)
assert saved.clarification is None
assert saved.candidates
```

固定 scope notice：

```python
SCOPE_NOTICE = (
    "当前支持护肤、防晒、底妆、彩妆、洁面/卸妆和香水导购。"
    "请明确品类、预算、肤质，或指出要比较的商品。"
)
```

- [ ] **Step 2: 运行 RED**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/application/test_cross_worker_text_state.py \
  tests/guide/application/test_text_recommendation_flow.py
```

Expected: clarification does not persist.

- [ ] **Step 3: 实现 `_stream_clarification`**

在 `TextRecommendationOrchestrator` 增加：

```python
_SCOPE_NOTICE = (
    "当前支持护肤、防晒、底妆、彩妆、洁面/卸妆和香水导购。"
    "请明确品类、预算、肤质，或指出要比较的商品。"
)


def _stream_clarification(
    self,
    turn: UserTurn,
    *,
    snapshot: ConversationSnapshot | None,
    task: TaskPlan,
) -> Iterator[SseEvent]:
    assert task.mode == "clarify"
    assert task.clarification is not None
    assert task.clarification_code is not None
    current = snapshot.clarification if snapshot is not None else None
    advance = advance_clarification(
        current,
        task.clarification_code,
    )
    expected_version = self._snapshot_version(snapshot)
    if snapshot is None:
        replacement = ConversationSnapshot(
            session_id=turn.session_id,
            version=1,
            profile_owner=turn.profile_owner,
            clarification=advance.progress,
        )
    else:
        replacement = snapshot.model_copy(
            update={
                "version": snapshot.version + 1,
                "clarification": advance.progress,
            },
            deep=True,
        )
    saved = self._conversation_state.save(
        replacement,
        expected_version=expected_version,
    )
    yield ClarifyEvent(
        data=ClarifyData(
            question=(
                self._SCOPE_NOTICE
                if advance.scope_notice
                else task.clarification
            )
        )
    )
    yield EndEvent(
        data=EndData(conversation_version=saved.version)
    )
```

将 `_stream_planned_text()` 中原 clarify 分支替换为：

```python
yield from self._stream_clarification(
    turn,
    snapshot=snapshot,
    task=task,
)
return
```

- [ ] **Step 4: 成功路径清零**

在 `_visible_snapshot()` 的新建和更新分支都设置：

```python
clarification=None
```

成功 followup 的 `next_snapshot` 也设置：

```python
"clarification": None
```

`resolve_semantic_context()` 增加：

```python
pending_clarification=(
    snapshot.clarification.gap
    if snapshot is not None and snapshot.clarification is not None
    else None
),
```

- [ ] **Step 5: SQLite 兼容测试**

在 `test_sqlite_conversation_state.py` 增加：

```python
def test_restart_round_trips_clarification_only_state(tmp_path: Path) -> None:
    state = _state(tmp_path)
    stored = state.save(
        ConversationSnapshot(
            session_id="clarification-restart",
            version=1,
            clarification=ClarificationProgress(
                gap=ClarificationCode.TOPIC,
                attempts=1,
            ),
        ),
        expected_version=0,
    )
    restarted = type(state)(
        state.database_path,
        trusted_state_root=state.database_path.parent,
    )
    assert restarted.load(stored.session_id) == stored
```

旧 JSON 缺 `clarification` 时应依赖 Pydantic 默认 `None`，不得迁移数据库 schema。

- [ ] **Step 6: GREEN**

Run:

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/feedback/test_conversation_state_contracts.py \
  tests/guide/adapters/state/test_sqlite_conversation_state.py \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/application/test_cross_worker_text_state.py
```

Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add \
  app/guide/understanding/context_resolver.py \
  app/guide/application/text_recommendation_flow.py \
  tests/guide/adapters/state/test_sqlite_conversation_state.py \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/application/test_cross_worker_text_state.py
git commit -m "feat(guide): close clarification turns in sqlite state"
```

### Task 4: 统一默认启动和公开路由

**Files:**
- Modify: `app/guide/application/chat_api_adapter.py`
- Modify: `app/guide_runtime/sse.py`
- Modify: `app/guide_runtime/app.py`
- Modify: `docker-compose.yml`
- Modify: `docker-compose.prod.yml`
- Modify: `start.sh`
- Modify: `README.md`
- Modify: `DEPLOY.md`
- Test: `tests/guide/application/test_chat_api_adapter.py`
- Test: `tests/guide/runtime/test_runtime_http.py`
- Test: `tests/guide/runtime/test_import_boundary.py`

- [ ] **Step 1: 将旧 owner 期望改为 Guide RED**

删除测试中对 `ChatOwner.LEGACY` 的生产期望，改为：

```python
@pytest.mark.parametrize(
    "message",
    ("第二款呢", "今天天气怎么样", "帮我看看"),
)
def test_public_text_is_always_owned_by_guide(message: str) -> None:
    assert classify_chat_owner(
        message=message,
        conversation_version=0,
        has_image_bundle_reference=False,
        has_legacy_image_payload=False,
    ) is ChatOwner.GUIDE_TEXT
```

旧图片 payload 断言返回 typed `IMAGE_BUNDLE_UNAVAILABLE`，不再断言 legacy owner。

- [ ] **Step 2: 运行 RED**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/application/test_chat_api_adapter.py \
  tests/guide/runtime/test_runtime_http.py \
  tests/guide/runtime/test_import_boundary.py
```

Expected: text owner and imports fail.

- [ ] **Step 3: 收缩 owner**

将 `ChatOwner` 收缩为：

```python
class ChatOwner(str, Enum):
    GUIDE_TEXT = "guide_text"
    GUIDE_CONSULTATION = "guide_consultation"
    GUIDE_IMAGE = "guide_image"
```

`classify_chat_owner()` 的最后一个返回固定为：

```python
return ChatOwner.GUIDE_TEXT
```

`has_legacy_image_payload` 不进入 owner 分类；由 `iter_http_events()` 现有错误分支处理。

将 `iter_slice1_guide_legacy_sse_events` 重命名为
`iter_guide_public_events`，更新 Guide/runtime/tests 内所有引用。不要保留旧别名。

- [ ] **Step 4: 统一启动命令**

精确替换：

```text
docker-compose.yml:
  uvicorn app.guide_runtime.app:app --host 0.0.0.0 --port 8000 --workers 2

docker-compose.prod.yml:
  uvicorn app.guide_runtime.app:app --host 0.0.0.0 --port 8000 --workers 4

start.sh:
  python -m uvicorn app.guide_runtime.app:app --reload --host 0.0.0.0 --port 8000

README.md:
  uvicorn app.guide_runtime.app:app --host 0.0.0.0 --port 8000

DEPLOY.md:
  uvicorn/gunicorn 的 module 全部改为 app.guide_runtime.app:app
```

README 不再把 `/docs` 写成默认入口，因为 Guide runtime 关闭 OpenAPI UI。

- [ ] **Step 5: 默认导入边界**

`tests/guide/runtime/test_import_boundary.py` 新增子进程断言：

```python
blocked = (
    "app.services",
    "app.database",
    "redis",
    "pymilvus",
)
assert all(
    module != prefix and not module.startswith(f"{prefix}.")
    for prefix in blocked
    for module in imported_modules
)
```

同时扫描全部启动文件不再含 `app.main:app`：

```python
for path in (
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.prod.yml",
    "start.sh",
    "README.md",
    "DEPLOY.md",
):
    assert "app.main:app" not in Path(path).read_text()
```

- [ ] **Step 6: GREEN**

Run Step 2 command。

Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add \
  app/guide/application/chat_api_adapter.py \
  app/guide_runtime/sse.py \
  app/guide_runtime/app.py \
  docker-compose.yml docker-compose.prod.yml start.sh README.md DEPLOY.md \
  tests/guide/application/test_chat_api_adapter.py \
  tests/guide/runtime/test_runtime_http.py \
  tests/guide/runtime/test_import_boundary.py
git commit -m "feat(runtime): route every public chat through Guide"
```

### Task 5: Track A focused 验收

**Files:**
- Verify only

- [ ] **Step 1: 运行 focused gate**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/feedback/test_conversation_state_contracts.py \
  tests/guide/adapters/state/test_sqlite_conversation_state.py \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/application/test_cross_worker_text_state.py \
  tests/guide/application/test_chat_api_adapter.py \
  tests/guide/runtime/test_runtime_http.py \
  tests/guide/runtime/test_import_boundary.py \
  tests/guide/runtime/test_sse.py
```

Expected: all PASS。

- [ ] **Step 2: 运行机械边界**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python \
  -m app.guide.check_boundaries app/guide
/private/tmp/xiaoro-guide-runtime-venv/bin/python \
  -m app.guide.check_boundaries app/guide_runtime
git diff --check
rg -n 'ChatOwner\\.LEGACY|return ChatOwner\\.LEGACY|app\\.main:app' \
  app/guide app/guide_runtime Dockerfile docker-compose*.yml \
  start.sh README.md DEPLOY.md
```

Expected: boundary commands return 0；`rg` 无输出。

- [ ] **Step 3: 固定 checkpoint**

按以下格式写入执行日志，但不要修改主 tasks/checklist：

```text
已完成：Guide-only 默认入口、message/stream、两轮澄清状态
当前卡点：无 / 精确失败项
剩余工作：等待 Integration Writer 删除旧源码
预计完成：2026-08-15
```

若同一测试层连续两次修复仍失败，立即停止并讨论，不进行第三次盲修。
