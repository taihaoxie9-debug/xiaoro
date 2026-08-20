# Slice 1 Backend Growth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把当前“500 元内油敏肌防晒”的 happy-path 原型，生长成强合同、严格决策、可复现测试和真正增量 SSE 的 Slice 1 后端纵切。

**Architecture:** 先把字符串和通用 JSON 改成各层拥有的 Pydantic 判别联合，再按 `understanding -> intent -> retrieval -> decision -> presentation -> feedback boundary` 逐层替换原型。Canonical 只通过小端口进入各层，应用层只编排和产出 typed SSE，不拥有词表、过滤、排序或文案规则。

**Tech Stack:** Python 3.11, Pydantic 2.8.0, pytest 8.0.0, `Decimal`, generator-based SSE event stream, immutable Canonical reader, TDD.

---

## 0. Execution Contract

- 当前计划只做后端，不修改 `chat.py`、`chat.html`、FastAPI 路由或任何前端代码。
- 不修改 SHA 锁定的 `app/guide/decision/deterministic_ranking.py`。
- 不恢复已删除的 `tools/evidence_audit/`，不 import 旧 `app.services` 或 `app.services.v2`。
- 用户已明确偏好主代理内联执行。实施时使用 `executing-plans`，每个 Task 独立 RED、GREEN、提交和复核。
- 每个 Task 完成后必须同时通过该 Task 的专项测试和 `python3 app/guide/check_boundaries.py app/guide`；不能积攒到最后一起修。
- 任一公开合同不明确时停止实现，先修改本计划并让用户复核，不能靠实现者猜测补齐。

## 1. Audit Baseline

审计区间：

```text
f634ed9..bdb0443
```

当前有效门禁：

```text
python3 -m pytest -q tests/guide tests/slice0
185 passed

python3 app/guide/check_boundaries.py app/guide
Boundary check passed: app/guide
```

锁定环境复验：

```text
Python 3.11.1
Pydantic 2.8.0
pytest 8.0.0
185 passed
```

这些测试只证明现有断言通过。对抗探针已经确认以下缺陷：

| 层 | 已确认缺陷 | 当前错误行为 |
|---|---|---|
| understanding | 数字边界 | `-100` 被解析成 `100`，`500.5` 被解析成 `5`，`0` 被放行 |
| understanding | 多重否定 | `不要酒精也不要香精` 被吞成一个排除值 |
| intent | 松散合同 | 任意 `kind/operator/value` JSON 可进入 `TaskPlan` |
| retrieval | 品类家族 | 12 个防晒家族商品只召回 5 个 |
| decision | 硬约束 | `exclude` 不执行，明确肤质 mismatch 被当 unknown 保留 |
| decision | 价格类型 | `True` 被当作价格 `1` |
| decision | winner | 业务证据平局仍返回 `SELECTED` |
| decision | 证据 | 非防晒查询仍写 `category=防晒` |
| presentation | 商品卡 | 商品事实缺失仍生成全空成功卡片 |
| application | 运行路径 | 默认 Canonical 路径依赖当前工作目录 |
| application | SSE | 返回 `list[dict]`，并非增量流；异常直接抛出 |
| tests | 假覆盖 | unknown-price 测试没有构造 unknown price |
| docs | 事实漂移 | Slice 0 文档仍声称 `evidence_audit` 存在且门禁为旧数字 |

完整评审报告：

```text
/tmp/xiaoro_slice1_backend_audit/report.html
/tmp/xiaoro_slice1_backend_audit/report.md
```

## 2. Frozen Slice 1 Semantics

### 2.1 Fixed Query

核心验收问题：

```text
500 内适合油敏肌的防晒
```

Canonical 当前事实：

- 防晒家族共 12 个商品。
- 预算 `<= 500` 后剩 11 个；`product_id=130` 因 760 元排除。
- 12 个商品的 `suitable_skin` 当前全部是 `unknown`。
- 预算内候选的稳定顺序应为：

```text
[55, 57, 54, 51, 102, 53, 58, 56, 52, 26, 101]
```

- 因肤质全部 unknown，必须返回 11 个候选并逐个标注数据缺失。
- 不得产生唯一 winner，状态必须是 `INSUFFICIENT_FOR_WINNER`。

### 2.2 A2 Skin Policy

```text
known match    -> 保留，排在 unknown 前
unknown        -> 保留，排后，明确标注数据缺失
known mismatch -> 排除，不能伪装成 unknown
no constraint  -> NOT_APPLICABLE，不生成肤质风险
```

### 2.3 Budget Policy

- 数字使用 `Decimal`，拒绝 `bool`、NaN、Infinity 和非数值。
- 支持阿拉伯整数、小数、`元/块`、上限、下限和区间。
- `预算 <= 0` 进入澄清，不进入召回或决策。
- 不设置人为预算上限，按用户字面值执行。
- 中文数字如“五百”在 Slice 1 明确识别为不支持格式并澄清，不能静默忽略或猜测。
- Canonical 价格 unknown、conflict 或非法时一律排除。

### 2.4 Exclusion Policy

排除项是硬约束：

```text
ingredients_present known 且包含排除项 -> EXCLUDED_MATCH
verified_absences known 且包含排除项   -> PASS
两者不能证明不存在                      -> EXCLUDED_UNKNOWN
```

Canonical 当前对酒精、香精的 absence 证据基本为 unknown。因此“不要酒精的防晒”允许返回 `NO_CANDIDATE` 或证据不足说明，不允许返回“已筛掉酒精”的假成功。

### 2.5 SSE Policy

正常推荐最小顺序：

```text
start
stage(understanding)
intent
stage(retrieval)
stage(decision)
decision_process
answer_contract
products
message
end
```

规则：

- `decision_process` 和 `answer_contract` 必须先于 `products`。
- `message.content` 是增量片段，不携带隐藏思维链，只输出用户可见的阶段结论。
- `end` 是唯一正常终止事件。
- `error` 是异常终止事件；发出后不得再发业务事件或 `end`。
- clarification 走 `start -> stage -> intent -> clarify -> end`。
- 未接前端前，事件只作为后端 typed contract 和 generator 验收。

### 2.6 Feedback Boundary

Slice 1 不写长期画像。反馈边界必须明确返回：

```text
SKIPPED_SLICE_SCOPE
```

不能返回假 `success=true`，也不能把 feedback 层描述成已经实现持久化。

## 3. File Map

### Create

- `app/guide/understanding/exact_parsing.py`
  - 只负责预算、品类、肤质和否定的精确解析。
- `app/guide/retrieval/category_taxonomy.py`
  - Slice 1 规范品类到 Canonical 原始品类集合的唯一映射。
- `app/guide/retrieval/ports.py`
  - 召回层所需的最小商品品类端口。
- `app/guide/decision/ports.py`
  - 决策层只读授权事实端口。
- `app/guide/presentation/ports.py`
  - 展示层只读商品卡事实端口。
- `app/guide/presentation/sse_events.py`
  - 后端 SSE 事件和 payload 的判别联合。
- `app/guide/adapters/catalog/canonical_guide_catalog.py`
  - 包装 `CanonicalProductReader`，实现三个小端口并做字段类型归一。
- `app/guide/feedback/ports.py`
  - Slice 1 明确的 feedback skip 端口。
- `tests/guide/contracts/test_slice1_constraint_contracts.py`
- `tests/guide/retrieval/test_category_taxonomy.py`
- `tests/guide/adapters/catalog/test_canonical_guide_catalog.py`
- `tests/guide/application/conftest.py`
- `tests/guide/application/test_slice1_backend_gate.py`
- `tests/fixtures/guide/slice1_backend_cases.json`
- `tools/guide_gates/__init__.py`
- `tools/guide_gates/slice1_backend.py`
- `pytest-guide.ini`

### Modify

- `app/guide/application/contracts.py`
- `app/guide/application/orchestrator.py`
- `app/guide/application/text_recommendation_flow.py`
- `app/guide/understanding/contracts.py`
- `app/guide/understanding/text_understanding.py`
- `app/guide/intent/contracts.py`
- `app/guide/intent/task_planning.py`
- `app/guide/retrieval/contracts.py`
- `app/guide/retrieval/canonical_retrieval.py`
- `app/guide/decision/contracts.py`
- `app/guide/decision/recommendation.py`
- `app/guide/presentation/contracts.py`
- `app/guide/presentation/response_planning.py`
- `tests/guide/understanding/test_text_understanding.py`
- `tests/guide/intent/test_task_planning.py`
- `tests/guide/retrieval/test_canonical_retrieval.py`
- `tests/guide/decision/test_recommendation.py`
- `tests/guide/presentation/test_response_planning.py`
- `tests/guide/application/test_text_recommendation_flow.py`
- `docs/superpowers/specs/2026-08-06-xiaoro-clean-growth-architecture-design.md`
- `docs/audits/slice0-foundation/morning_handoff.md`

### Delete After Replacement Tests Are Green

- 无文件删除。
- 保留 `text_recommendation_flow.py` 路径，替换其内部原型实现，避免制造无必要的路径迁移。

---

### Task 1: Introduce Typed Constraint Models Without Switching Callers

**Files:**
- Modify: `app/guide/application/contracts.py`
- Modify: `app/guide/understanding/contracts.py`
- Modify: `app/guide/intent/contracts.py`
- Create: `tests/guide/contracts/test_slice1_constraint_contracts.py`

- [ ] **Step 1: Write strict contract tests**

Create `tests/guide/contracts/test_slice1_constraint_contracts.py`:

```python
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.guide.application.contracts import UserTurn
from app.guide.intent.contracts import (
    BudgetConstraint,
    CategoryConstraint,
)
from app.guide.understanding.contracts import TopicCode


def test_user_turn_rejects_empty_and_oversized_messages() -> None:
    base = {
        "session_id": "s-1",
        "image_bundle_id": None,
        "conversation_version": 0,
    }
    with pytest.raises(ValidationError):
        UserTurn(message="   ", **base)
    with pytest.raises(ValidationError):
        UserTurn(message="x" * 4001, **base)


def test_budget_contract_rejects_non_positive_and_reversed_range() -> None:
    with pytest.raises(ValidationError):
        BudgetConstraint(minimum=None, maximum=Decimal("0"))
    with pytest.raises(ValidationError):
        BudgetConstraint(
            minimum=Decimal("500"),
            maximum=Decimal("300"),
        )


def test_category_constraint_uses_normalized_topic_code() -> None:
    constraint = CategoryConstraint(value=TopicCode.SUNSCREEN)
    assert constraint.kind == "category"
    assert constraint.value is TopicCode.SUNSCREEN
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
python3 -m pytest -q tests/guide/contracts/test_slice1_constraint_contracts.py
```

Expected: FAIL because typed constraints, message bounds and discriminators do not exist.

- [ ] **Step 3: Bound the application input**

Replace `UserTurn` string fields in `app/guide/application/contracts.py` with:

```python
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

SessionId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]
UserMessage = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4000),
]


class _StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class UserTurn(_StrictContract):
    session_id: SessionId
    message: UserMessage
    image_bundle_id: str | None = None
    conversation_version: int = Field(ge=0)
```

- [ ] **Step 4: Define typed understanding drafts**

In `app/guide/understanding/contracts.py`, replace `exact_constraints: list[str]` and `uncertainties: list[str]` with these owned types:

```python
from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    model_validator,
)


class TopicCode(str, Enum):
    SUNSCREEN = "sunscreen"


class SkinTarget(str, Enum):
    OILY_SENSITIVE = "oily_sensitive"
    OILY = "oily"
    DRY = "dry"
    COMBINATION = "combination"
    SENSITIVE = "sensitive"
    NORMAL = "normal"


class BudgetDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["budget"] = "budget"
    minimum: Decimal | None = None
    maximum: Decimal | None = None

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.minimum is None and self.maximum is None:
            raise ValueError("budget draft requires a bound")
        values = [
            value
            for value in (self.minimum, self.maximum)
            if value is not None
        ]
        if any(not value.is_finite() or value <= 0 for value in values):
            raise ValueError("budget draft bounds must be positive")
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError("budget draft minimum exceeds maximum")
        return self


class CategoryDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["category"] = "category"
    value: TopicCode


class SkinDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["skin"] = "skin"
    value: SkinTarget


class ExclusionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["exclude"] = "exclude"
    value: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
    ]


ExactConstraintDraft = Annotated[
    BudgetDraft | CategoryDraft | SkinDraft | ExclusionDraft,
    Field(discriminator="kind"),
]


class UnderstandingIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    code: Literal[
        "invalid_budget",
        "unsupported_budget_format",
        "missing_category",
    ]
    detail: str
```

Keep `ImageObservation`, `ImageBundle` and the existing
`StructuredUnderstanding` field types unchanged in this Task. The new draft
models are additive until Task 2 switches the producer and consumer together.

- [ ] **Step 5: Define typed TaskPlan constraints**

Add the typed constraint models to `app/guide/intent/contracts.py` without
changing the existing `TaskPlan` in this Task:

```python
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.guide.understanding.contracts import SkinTarget, TopicCode


class _StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class BudgetConstraint(_StrictContract):
    kind: Literal["budget"] = "budget"
    minimum: Decimal | None = None
    maximum: Decimal | None = None

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.minimum is None and self.maximum is None:
            raise ValueError("budget requires minimum or maximum")
        if self.minimum is not None and self.minimum <= 0:
            raise ValueError("budget minimum must be positive")
        if self.maximum is not None and self.maximum <= 0:
            raise ValueError("budget maximum must be positive")
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError("budget minimum must not exceed maximum")
        return self


class CategoryConstraint(_StrictContract):
    kind: Literal["category"] = "category"
    value: TopicCode


class SkinConstraint(_StrictContract):
    kind: Literal["skin"] = "skin"
    value: SkinTarget


class ExclusionConstraint(_StrictContract):
    kind: Literal["exclude"] = "exclude"
    value: str = Field(min_length=1, max_length=64)


TaskConstraint = Annotated[
    BudgetConstraint
    | CategoryConstraint
    | SkinConstraint
    | ExclusionConstraint,
    Field(discriminator="kind"),
]


```

- [ ] **Step 6: Run contract tests**

Run:

```bash
python3 -m pytest -q tests/guide/contracts/test_slice1_constraint_contracts.py
python3 -m pytest -q tests/guide tests/slice0
python3 app/guide/check_boundaries.py app/guide
```

Expected: all commands PASS. Existing producers still use their old field shapes,
so this commit adds validated models without creating a red intermediate state.

- [ ] **Step 7: Commit the contract boundary**

```bash
git add app/guide/application/contracts.py app/guide/understanding/contracts.py app/guide/intent/contracts.py tests/guide/contracts/test_slice1_constraint_contracts.py
git commit -m "refactor(guide): type slice 1 input and constraint contracts"
```

---

### Task 2: Build Exact Parsing and Clarification

**Files:**
- Create: `app/guide/understanding/exact_parsing.py`
- Modify: `app/guide/understanding/text_understanding.py`
- Modify: `app/guide/intent/task_planning.py`
- Modify: `tests/guide/understanding/test_text_understanding.py`
- Modify: `tests/guide/intent/test_task_planning.py`

- [ ] **Step 1: Add adversarial parsing tests**

Add to `tests/guide/understanding/test_text_understanding.py`:

```python
from decimal import Decimal

import pytest

from app.guide.understanding.contracts import BudgetDraft, ExclusionDraft


@pytest.mark.parametrize(
    ("message", "minimum", "maximum"),
    [
        ("500 内防晒", None, Decimal("500")),
        ("500.5 元以内防晒", None, Decimal("500.5")),
        ("300 元以上防晒", Decimal("300"), None),
        ("300 到 500 元防晒", Decimal("300"), Decimal("500")),
    ],
)
def test_budget_directions_are_exact(
    message: str,
    minimum: Decimal | None,
    maximum: Decimal | None,
) -> None:
    result = understand()(message)
    budget = next(
        item
        for item in result.exact_constraints
        if isinstance(item, BudgetDraft)
    )
    assert budget.minimum == minimum
    assert budget.maximum == maximum


@pytest.mark.parametrize(
    "message",
    [
        "-100 内防晒",
        "-100 元防晒",
        "0 元以内防晒",
        "0 元防晒",
    ],
)
def test_invalid_budget_becomes_uncertainty(message: str) -> None:
    result = understand()(message)
    assert any(issue.code == "invalid_budget" for issue in result.uncertainties)
    assert not any(
        isinstance(item, BudgetDraft)
        for item in result.exact_constraints
    )


def test_chinese_budget_is_detected_and_clarified() -> None:
    result = understand()("五百内的防晒")
    assert any(
        issue.code == "unsupported_budget_format"
        for issue in result.uncertainties
    )


def test_multiple_exclusions_are_independent() -> None:
    result = understand()("不要酒精也不要香精的防晒")
    exclusions = {
        item.value
        for item in result.exact_constraints
        if isinstance(item, ExclusionDraft)
    }
    assert exclusions == {"酒精", "香精"}


def test_understanding_rejects_oversized_direct_input() -> None:
    with pytest.raises(ValueError, match="message length"):
        understand()("x" * 4001)
```

Add to `tests/guide/intent/test_task_planning.py`:

```python
import pytest
from pydantic import ValidationError

from app.guide.intent.contracts import TaskPlan


def test_task_plan_rejects_unknown_constraint_kind() -> None:
    with pytest.raises(ValidationError):
        TaskPlan.model_validate({
            "mode": "recommend",
            "referenced_image_ids": [],
            "constraints": [
                {"kind": "typo", "operator": "anything", "value": []}
            ],
            "required_evidence": ["canonical_product"],
            "clarification": None,
        })


def test_invalid_budget_forces_clarification() -> None:
    task = plan()(understand_text("0 元以内的防晒"))
    assert task.mode == "clarify"
    assert "预算" in task.clarification


def test_all_compiled_constraints_are_typed() -> None:
    task = plan()(understand_text("300 到 500 元、不要酒精的防晒"))
    assert {item.kind for item in task.constraints} == {
        "budget",
        "category",
        "exclude",
    }
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
python3 -m pytest -q tests/guide/understanding/test_text_understanding.py tests/guide/intent/test_task_planning.py
```

Expected: FAIL on numeric boundaries, typed output and multi-negation.

- [ ] **Step 3: Implement exact parsing**

Create `app/guide/understanding/exact_parsing.py` with these owned patterns and functions:

```python
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app.guide.understanding.contracts import (
    BudgetDraft,
    CategoryDraft,
    ExactConstraintDraft,
    ExclusionDraft,
    SkinDraft,
    SkinTarget,
    TopicCode,
    UnderstandingIssue,
)

_NUMBER = r"\d+(?:\.\d+)?"
_NEGATIVE_BUDGET = re.compile(
    rf"-\s*{_NUMBER}\s*(?:元|块|以内|内|以下|以上|到|至)"
)
_RANGE = re.compile(
    rf"(?<![-\d.])(?P<minimum>{_NUMBER})\s*"
    rf"(?:元|块)?\s*(?:到|至|~|-)\s*"
    rf"(?P<maximum>{_NUMBER})\s*(?:元|块)?"
)
_MAXIMUM = re.compile(
    rf"(?<![-\d.])(?P<maximum>{_NUMBER})\s*"
    rf"(?:元|块)?\s*(?:以内|内|以下)"
)
_MINIMUM = re.compile(
    rf"(?<![-\d.])(?P<minimum>{_NUMBER})\s*"
    rf"(?:元|块)?\s*(?:以上|起)"
)
_BUDGET_PREFIX = re.compile(
    rf"预算\s*(?P<maximum>{_NUMBER})(?:\s*(?:元|块))?"
)
_BARE_CURRENCY = re.compile(
    rf"(?<![-\d.])(?P<maximum>{_NUMBER})\s*(?:元|块)"
)
_CHINESE_BUDGET = re.compile(
    r"(?:预算\s*)?[零一二两三四五六七八九十百千万]+\s*"
    r"(?:元|块)?\s*(?:以内|内|以下|以上|到|至)"
)

_CATEGORY_ALIASES = (
    ("防晒隔离", TopicCode.SUNSCREEN),
    ("防晒乳液", TopicCode.SUNSCREEN),
    ("防晒霜", TopicCode.SUNSCREEN),
    ("防晒乳", TopicCode.SUNSCREEN),
    ("防晒", TopicCode.SUNSCREEN),
)
_SKIN_ALIASES = (
    ("油敏肌", SkinTarget.OILY_SENSITIVE),
    ("油敏", SkinTarget.OILY_SENSITIVE),
    ("油性", SkinTarget.OILY),
    ("干性", SkinTarget.DRY),
    ("混合", SkinTarget.COMBINATION),
    ("敏感", SkinTarget.SENSITIVE),
    ("中性", SkinTarget.NORMAL),
)
_NEGATION = re.compile(r"(?:也)?(?:不要含?|不含|不能有|无)\s*")
_EXCLUSION_SUFFIX = re.compile(
    r"(?:的)?(?:防晒隔离|防晒乳液|防晒霜|防晒乳|防晒|产品).*$"
)


def parse_exact_constraints(
    text: str,
) -> tuple[list[ExactConstraintDraft], list[UnderstandingIssue]]:
    constraints: list[ExactConstraintDraft] = []
    issues: list[UnderstandingIssue] = []

    budget, budget_issue = _parse_budget(text)
    if budget is not None:
        constraints.append(budget)
    if budget_issue is not None:
        issues.append(budget_issue)

    category = _parse_category(text)
    if category is not None:
        constraints.append(CategoryDraft(value=category))

    skin = _parse_skin(text)
    if skin is not None:
        constraints.append(SkinDraft(value=skin))

    constraints.extend(
        ExclusionDraft(value=value)
        for value in _parse_exclusions(text)
    )
    return constraints, issues


def _parse_budget(
    text: str,
) -> tuple[BudgetDraft | None, UnderstandingIssue | None]:
    if _NEGATIVE_BUDGET.search(text):
        return None, UnderstandingIssue(
            code="invalid_budget",
            detail="预算必须大于 0",
        )
    if _CHINESE_BUDGET.search(text):
        return None, UnderstandingIssue(
            code="unsupported_budget_format",
            detail="请使用阿拉伯数字填写预算",
        )

    match = _RANGE.search(text)
    if match:
        return _validated_budget(
            minimum=match.group("minimum"),
            maximum=match.group("maximum"),
        )
    for pattern, minimum_key, maximum_key in (
        (_MAXIMUM, None, "maximum"),
        (_MINIMUM, "minimum", None),
        (_BUDGET_PREFIX, None, "maximum"),
        (_BARE_CURRENCY, None, "maximum"),
    ):
        match = pattern.search(text)
        if not match:
            continue
        return _validated_budget(
            minimum=match.group(minimum_key) if minimum_key else None,
            maximum=match.group(maximum_key) if maximum_key else None,
        )
    return None, None


def _validated_budget(
    *,
    minimum: str | None,
    maximum: str | None,
) -> tuple[BudgetDraft | None, UnderstandingIssue | None]:
    try:
        minimum_value = Decimal(minimum) if minimum is not None else None
        maximum_value = Decimal(maximum) if maximum is not None else None
    except InvalidOperation:
        return None, UnderstandingIssue(
            code="invalid_budget",
            detail="预算数字格式无效",
        )

    values = [
        value
        for value in (minimum_value, maximum_value)
        if value is not None
    ]
    if any(not value.is_finite() or value <= 0 for value in values):
        return None, UnderstandingIssue(
            code="invalid_budget",
            detail="预算必须是大于 0 的有限数字",
        )
    if (
        minimum_value is not None
        and maximum_value is not None
        and minimum_value > maximum_value
    ):
        return None, UnderstandingIssue(
            code="invalid_budget",
            detail="预算下限不能高于上限",
        )
    return (
        BudgetDraft(
            minimum=minimum_value,
            maximum=maximum_value,
        ),
        None,
    )


def _parse_category(text: str) -> TopicCode | None:
    for alias, code in _CATEGORY_ALIASES:
        if alias in text:
            return code
    return None


def _parse_skin(text: str) -> SkinTarget | None:
    for alias, target in _SKIN_ALIASES:
        if alias in text:
            return target
    return None


def _parse_exclusions(text: str) -> list[str]:
    matches = list(_NEGATION.finditer(text))
    values: list[str] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        value = text[match.end():end].strip(" ，,。；;")
        value = _EXCLUSION_SUFFIX.sub("", value).strip(" ，,。；;")
        if value:
            values.append(value)
    return list(dict.fromkeys(values))
```

- [ ] **Step 4: Make understanding emit typed drafts**

Replace the body of `understand_text()` in `app/guide/understanding/text_understanding.py`:

```python
from app.guide.understanding.contracts import StructuredUnderstanding
from app.guide.understanding.exact_parsing import parse_exact_constraints


def understand_text(message: str) -> StructuredUnderstanding:
    text = message.strip()
    if not 1 <= len(text) <= 4000:
        raise ValueError("message length must be between 1 and 4000")
    exact_constraints, uncertainties = parse_exact_constraints(text)
    topic = next(
        (
            item.value
            for item in exact_constraints
            if item.kind == "category"
        ),
        None,
    )
    return StructuredUnderstanding(
        goal="recommend",
        topic=topic,
        observations=[f"raw_message={text}"],
        exact_constraints=exact_constraints,
        semantic_proposals=[],
        image_references=[],
        uncertainties=uncertainties,
        confidence=1.0 if exact_constraints and not uncertainties else 0.0,
    )
```

In `app/guide/understanding/contracts.py`, switch the owner contract atomically
with the producer:

```python
class StructuredUnderstanding(_StrictContract):
    goal: Literal["recommend"] = "recommend"
    topic: TopicCode | None
    observations: list[str]
    exact_constraints: list[ExactConstraintDraft]
    semantic_proposals: list[str]
    image_references: list[str]
    uncertainties: list[UnderstandingIssue]
    confidence: float = Field(ge=0.0, le=1.0)
```

Delete the old `_BUDGET_PATTERNS`, `_NEGATION_PATTERN`, `_extract_budget_max`, `_extract_category` and `_extract_skin` helpers from this file.

- [ ] **Step 5: Compile typed drafts exhaustively**

First replace `TaskPlan` in `app/guide/intent/contracts.py` so its public
constraints are the `TaskConstraint` union added in Task 1:

```python
class TaskPlan(_StrictContract):
    mode: Literal["recommend", "clarify"]
    referenced_image_ids: list[str]
    constraints: list[TaskConstraint]
    required_evidence: list[Literal["canonical_product"]]
    clarification: str | None = None

    @model_validator(mode="after")
    def validate_mode(self) -> Self:
        if self.mode == "clarify" and not self.clarification:
            raise ValueError("clarify mode requires clarification")
        if self.mode == "recommend" and self.clarification is not None:
            raise ValueError("recommend mode forbids clarification")
        return self
```

Replace `plan_task()` and `_compile_constraints()` in `app/guide/intent/task_planning.py`:

```python
from typing import assert_never

from app.guide.intent.contracts import (
    BudgetConstraint,
    CategoryConstraint,
    ExclusionConstraint,
    SkinConstraint,
    TaskConstraint,
    TaskPlan,
)
from app.guide.understanding.contracts import (
    BudgetDraft,
    CategoryDraft,
    ExclusionDraft,
    SkinDraft,
    StructuredUnderstanding,
)


def plan_task(understanding: StructuredUnderstanding) -> TaskPlan:
    constraints = _compile_constraints(understanding)
    if understanding.uncertainties:
        return TaskPlan(
            mode="clarify",
            referenced_image_ids=[],
            constraints=constraints,
            required_evidence=[],
            clarification=understanding.uncertainties[0].detail,
        )
    if not any(item.kind == "category" for item in constraints):
        return TaskPlan(
            mode="clarify",
            referenced_image_ids=[],
            constraints=constraints,
            required_evidence=[],
            clarification="当前 Slice 1 需要明确防晒品类。",
        )
    return TaskPlan(
        mode="recommend",
        referenced_image_ids=[],
        constraints=constraints,
        required_evidence=["canonical_product"],
        clarification=None,
    )


def _compile_constraints(
    understanding: StructuredUnderstanding,
) -> list[TaskConstraint]:
    compiled: list[TaskConstraint] = []
    for draft in understanding.exact_constraints:
        if isinstance(draft, BudgetDraft):
            compiled.append(BudgetConstraint(
                minimum=draft.minimum,
                maximum=draft.maximum,
            ))
        elif isinstance(draft, CategoryDraft):
            compiled.append(CategoryConstraint(value=draft.value))
        elif isinstance(draft, SkinDraft):
            compiled.append(SkinConstraint(value=draft.value))
        elif isinstance(draft, ExclusionDraft):
            compiled.append(ExclusionConstraint(value=draft.value))
        else:
            assert_never(draft)
    return compiled
```

- [ ] **Step 6: Run understanding and intent tests**

Run:

```bash
python3 -m pytest -q tests/guide/contracts tests/guide/understanding tests/guide/intent
python3 -m pytest -q tests/guide tests/slice0
python3 app/guide/check_boundaries.py app/guide
```

Expected: PASS.

- [ ] **Step 7: Commit exact understanding**

```bash
git add app/guide/understanding app/guide/intent tests/guide/understanding tests/guide/intent
git commit -m "feat(guide): parse slice 1 constraints without guessing"
```

---

### Task 3: Add Category Taxonomy and Retrieval Port

**Files:**
- Create: `app/guide/retrieval/category_taxonomy.py`
- Create: `app/guide/retrieval/ports.py`
- Create: `app/guide/adapters/catalog/canonical_guide_catalog.py`
- Modify: `app/guide/retrieval/contracts.py`
- Modify: `app/guide/retrieval/canonical_retrieval.py`
- Create: `tests/guide/retrieval/test_category_taxonomy.py`
- Modify: `tests/guide/retrieval/test_canonical_retrieval.py`

- [ ] **Step 1: Write the 12-product recall test**

Create `tests/guide/retrieval/test_category_taxonomy.py`:

```python
from app.guide.retrieval.category_taxonomy import canonical_categories_for
from app.guide.understanding.contracts import TopicCode


def test_sunscreen_family_is_explicit_and_versioned() -> None:
    values = canonical_categories_for(TopicCode.SUNSCREEN)
    assert values == frozenset({
        "防晒",
        "防晒隔离",
        "防晒乳液",
        "防晒霜",
        "防晒乳",
    })
```

Replace the main assertion in `tests/guide/retrieval/test_canonical_retrieval.py`:

```python
def test_retrieves_all_sunscreen_family_candidates() -> None:
    result = retrieve()(make_catalog(), category=TopicCode.SUNSCREEN)
    assert len(result.candidates) == 12
    assert {item.product_id for item in result.candidates} == {
        26, 51, 52, 53, 54, 55, 56, 57, 58, 101, 102, 130
    }
    assert {item.canonical_category for item in result.candidates} == {
        "防晒",
        "防晒隔离",
        "防晒乳液",
        "防晒霜",
        "防晒乳",
    }
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
python3 -m pytest -q tests/guide/retrieval/test_category_taxonomy.py tests/guide/retrieval/test_canonical_retrieval.py
```

Expected: FAIL because taxonomy, port and 12-item recall do not exist.

- [ ] **Step 3: Define the taxonomy**

Create `app/guide/retrieval/category_taxonomy.py`:

```python
from types import MappingProxyType

from app.guide.understanding.contracts import TopicCode

CATEGORY_TAXONOMY_VERSION = "slice1-category-v1"

_CATEGORY_FAMILIES = MappingProxyType({
    TopicCode.SUNSCREEN: frozenset({
        "防晒",
        "防晒隔离",
        "防晒乳液",
        "防晒霜",
        "防晒乳",
    }),
})


def canonical_categories_for(topic: TopicCode) -> frozenset[str]:
    return _CATEGORY_FAMILIES[topic]
```

- [ ] **Step 4: Define the retrieval-owned port**

Create `app/guide/retrieval/ports.py`:

```python
from collections.abc import Iterable
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict


class CategoryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    product_id: int
    value: str | None
    state: Literal["known", "unknown", "conflict", "not_applicable"]


class CategoryCatalogPort(Protocol):
    def iter_category_records(self) -> Iterable[CategoryRecord]: ...
```

- [ ] **Step 5: Implement the Canonical retrieval adapter**

Create the initial `CanonicalGuideCatalog` in `app/guide/adapters/catalog/canonical_guide_catalog.py`:

```python
from collections.abc import Iterable

from app.guide.adapters.catalog.canonical_product_reader import (
    CanonicalProductReader,
)
from app.guide.retrieval.ports import CategoryRecord


class CanonicalGuideCatalog:
    def __init__(self, reader: CanonicalProductReader) -> None:
        self._reader = reader

    def iter_category_records(self) -> Iterable[CategoryRecord]:
        for product_id in sorted(self._reader.product_ids):
            field = self._reader.get(product_id).fields.get("category")
            yield CategoryRecord(
                product_id=product_id,
                value=field.value if field is not None else None,
                state=field.resolved_state if field is not None else "unknown",
            )
```

Export `CanonicalGuideCatalog` from `app/guide/adapters/catalog/__init__.py`.

- [ ] **Step 6: Make retrieval consume the port and taxonomy**

Add `canonical_category: str` to `CandidateRef`, then replace `retrieve_candidates()`:

```python
from app.guide.retrieval.category_taxonomy import (
    CATEGORY_TAXONOMY_VERSION,
    canonical_categories_for,
)
from app.guide.retrieval.contracts import CandidateRef, RetrievalResult
from app.guide.retrieval.ports import CategoryCatalogPort
from app.guide.understanding.contracts import TopicCode


def retrieve_candidates(
    catalog: CategoryCatalogPort,
    *,
    category: TopicCode,
) -> RetrievalResult:
    allowed = canonical_categories_for(category)
    candidates = [
        CandidateRef(
            product_id=record.product_id,
            source="canonical",
            canonical_category=record.value,
            retrieval_reason=(
                f"category_family={category.value};"
                f"taxonomy={CATEGORY_TAXONOMY_VERSION};"
                f"matched={record.value}"
            ),
        )
        for record in catalog.iter_category_records()
        if record.state == "known"
        and record.value is not None
        and record.value in allowed
    ]
    return RetrievalResult(
        candidates=candidates,
        knowledge_evidence=[],
        review_evidence=[],
        memory_evidence=[],
        missing_sources=(
            [] if candidates else [f"canonical:{category.value}"]
        ),
    )
```

- [ ] **Step 7: Run retrieval and boundary tests**

Run:

```bash
python3 -m pytest -q tests/guide/retrieval
python3 -m pytest -q tests/guide tests/slice0
python3 app/guide/check_boundaries.py app/guide
```

Expected: PASS with 12 sunscreen-family candidates.

- [ ] **Step 8: Commit taxonomy retrieval**

```bash
git add app/guide/retrieval app/guide/adapters/catalog tests/guide/retrieval
git commit -m "feat(retrieval): recall the explicit sunscreen category family"
```

---

### Task 4: Expose Only Authorized Decision and Presentation Facts

**Files:**
- Create: `app/guide/decision/ports.py`
- Create: `app/guide/presentation/ports.py`
- Modify: `app/guide/decision/contracts.py`
- Modify: `app/guide/presentation/contracts.py`
- Modify: `app/guide/adapters/catalog/canonical_guide_catalog.py`
- Create: `tests/guide/adapters/catalog/test_canonical_guide_catalog.py`

- [ ] **Step 1: Write adapter fail-closed tests**

Create `tests/guide/adapters/catalog/test_canonical_guide_catalog.py`:

```python
from decimal import Decimal
from pathlib import Path

import pytest

from app.guide.adapters.catalog import CanonicalProductReader
from app.guide.adapters.catalog.canonical_guide_catalog import (
    CanonicalGuideCatalog,
)
from app.guide.decision.contracts import FactState
from app.guide.retrieval.contracts import CanonicalField, CanonicalProduct

ROOT = Path(__file__).resolve().parents[4]


def canonical_field(
    key: str,
    value,
    *,
    state: str = "known",
) -> CanonicalField:
    return CanonicalField(
        key=key,
        value=value,
        field_origin="test",
        resolved_state=state,
        source_classes=["test"],
        source_refs=["test"],
        evidence_status=None,
    )


class FakeReader:
    def __init__(self, product: CanonicalProduct) -> None:
        self.product_ids = frozenset({product.product_id})
        self._product = product

    def get(self, product_id: int) -> CanonicalProduct:
        assert product_id == self._product.product_id
        return self._product.model_copy(deep=True)


def fake_reader_factory(
    *,
    price,
    price_state: str = "known",
) -> FakeReader:
    product = CanonicalProduct(
        product_id=1,
        schema_version="canonical-decision-product-v1",
        fields={
            "category": canonical_field("category", "防晒"),
            "price": canonical_field(
                "price",
                price,
                state=price_state,
            ),
            "suitable_skin": canonical_field(
                "suitable_skin",
                None,
                state="unknown",
            ),
            "ingredients_present": canonical_field(
                "ingredients_present",
                None,
                state="unknown",
            ),
            "verified_absences": canonical_field(
                "verified_absences",
                None,
                state="unknown",
            ),
            "product_identity": canonical_field(
                "product_identity",
                "测试商品",
            ),
            "brand": canonical_field("brand", "测试品牌"),
        },
    )
    return FakeReader(product)


def make_catalog(reader) -> CanonicalGuideCatalog:
    return CanonicalGuideCatalog(reader)


@pytest.fixture
def real_catalog() -> CanonicalGuideCatalog:
    canonical = ROOT / "data" / "canonical"
    reader = CanonicalProductReader.from_files(
        manifest_path=canonical / "core_products_v1_manifest.json",
        products_path=canonical / "core_products_v1.jsonl",
    )
    return CanonicalGuideCatalog(reader)


def test_boolean_price_is_conflict_not_one() -> None:
    catalog = make_catalog(fake_reader_factory(price=True))
    facts = catalog.get_decision_facts(1)
    assert facts.price_state is FactState.CONFLICT
    assert facts.price is None


def test_unknown_price_stays_unknown() -> None:
    catalog = make_catalog(
        fake_reader_factory(price=None, price_state="unknown")
    )
    facts = catalog.get_decision_facts(1)
    assert facts.price_state is FactState.UNKNOWN
    assert facts.price is None


def test_known_price_is_decimal(real_catalog) -> None:
    facts = real_catalog.get_decision_facts(55)
    assert facts.price == Decimal("88.11")
    assert facts.price_state is FactState.KNOWN


def test_unusable_source_name_is_preserved_and_flagged(real_catalog) -> None:
    facts = real_catalog.get_presentation_facts(26)
    assert facts.name == "无"
    assert "product_identity_unusable" in facts.fact_warnings
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
python3 -m pytest -q tests/guide/adapters/catalog/test_canonical_guide_catalog.py
```

Expected: FAIL because the authorized fact ports do not exist.

- [ ] **Step 3: Define decision facts and port**

Add to `app/guide/decision/contracts.py`:

```python
from decimal import Decimal
from enum import Enum


class FactState(str, Enum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"
    NOT_APPLICABLE = "not_applicable"


class DecisionProductFacts(_StrictContract):
    product_id: int
    price: Decimal | None
    price_state: FactState
    suitable_skin: tuple[str, ...] | None
    suitable_skin_state: FactState
    ingredients_present: tuple[str, ...] | None
    ingredients_present_state: FactState
    verified_absences: tuple[str, ...] | None
    verified_absences_state: FactState

    @model_validator(mode="after")
    def validate_state_values(self) -> Self:
        pairs = (
            (self.price, self.price_state, "price"),
            (
                self.suitable_skin,
                self.suitable_skin_state,
                "suitable_skin",
            ),
            (
                self.ingredients_present,
                self.ingredients_present_state,
                "ingredients_present",
            ),
            (
                self.verified_absences,
                self.verified_absences_state,
                "verified_absences",
            ),
        )
        for value, state, field_name in pairs:
            if state is FactState.KNOWN and value is None:
                raise ValueError(
                    f"{field_name} requires value when known"
                )
            if state is not FactState.KNOWN and value is not None:
                raise ValueError(
                    f"{field_name} forbids value unless known"
                )
        return self
```

Create `app/guide/decision/ports.py`:

```python
from typing import Protocol

from app.guide.decision.contracts import DecisionProductFacts


class DecisionFactPort(Protocol):
    def get_decision_facts(
        self,
        product_id: int,
    ) -> DecisionProductFacts: ...
```

- [ ] **Step 4: Define presentation facts and port**

Add to `app/guide/presentation/contracts.py`:

```python
from decimal import Decimal


class ProductCardFacts(_StrictContract):
    product_id: int
    name: str | None
    brand: str | None
    price: Decimal | None
    fact_warnings: list[str]
```

Create `app/guide/presentation/ports.py`:

```python
from typing import Protocol

from app.guide.presentation.contracts import ProductCardFacts


class PresentationFactPort(Protocol):
    def get_presentation_facts(
        self,
        product_id: int,
    ) -> ProductCardFacts: ...
```

- [ ] **Step 5: Extend the Canonical adapter**

Add these methods and helpers to `CanonicalGuideCatalog`:

```python
from decimal import Decimal, InvalidOperation

from app.guide.decision.contracts import (
    DecisionProductFacts,
    FactState,
)
from app.guide.presentation.contracts import ProductCardFacts

_UNUSABLE_NAMES = frozenset({"", "无"})


def _fact_state(field) -> FactState:
    if field is None:
        return FactState.UNKNOWN
    try:
        return FactState(field.resolved_state)
    except ValueError:
        return FactState.CONFLICT


def _decimal_value(field) -> tuple[Decimal | None, FactState]:
    state = _fact_state(field)
    if state is not FactState.KNOWN:
        return None, state
    value = field.value
    if isinstance(value, bool):
        return None, FactState.CONFLICT
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None, FactState.CONFLICT
    if not decimal_value.is_finite() or decimal_value < 0:
        return None, FactState.CONFLICT
    return decimal_value, FactState.KNOWN


def _tuple_value(field) -> tuple[tuple[str, ...] | None, FactState]:
    state = _fact_state(field)
    if state is not FactState.KNOWN:
        return None, state
    value = field.value
    if isinstance(value, str) and value.strip():
        return (value,), FactState.KNOWN
    if isinstance(value, list) and value and all(
        isinstance(item, str) for item in value
    ):
        return tuple(value), FactState.KNOWN
    return None, FactState.CONFLICT
```

Keep the helpers above at module scope. Add these two methods inside
`CanonicalGuideCatalog`:

```python
    def get_decision_facts(
        self,
        product_id: int,
    ) -> DecisionProductFacts:
        product = self._reader.get(product_id)
        price, price_state = _decimal_value(
            product.fields.get("price")
        )
        skin, skin_state = _tuple_value(
            product.fields.get("suitable_skin")
        )
        present, present_state = _tuple_value(
            product.fields.get("ingredients_present")
        )
        absent, absent_state = _tuple_value(
            product.fields.get("verified_absences")
        )
        return DecisionProductFacts(
            product_id=product_id,
            price=price,
            price_state=price_state,
            suitable_skin=skin,
            suitable_skin_state=skin_state,
            ingredients_present=present,
            ingredients_present_state=present_state,
            verified_absences=absent,
            verified_absences_state=absent_state,
        )

    def get_presentation_facts(
        self,
        product_id: int,
    ) -> ProductCardFacts:
        product = self._reader.get(product_id)
        name_field = product.fields.get("product_identity")
        brand_field = product.fields.get("brand")
        price, price_state = _decimal_value(
            product.fields.get("price")
        )
        name = (
            str(name_field.value)
            if name_field is not None
            and name_field.resolved_state == "known"
            else None
        )
        brand = (
            str(brand_field.value)
            if brand_field is not None
            and brand_field.resolved_state == "known"
            else None
        )
        warnings: list[str] = []
        if name is None or name.strip() in _UNUSABLE_NAMES:
            warnings.append("product_identity_unusable")
        if brand is None:
            warnings.append("brand_missing")
        if price_state is not FactState.KNOWN:
            warnings.append("price_missing")
        return ProductCardFacts(
            product_id=product_id,
            name=name,
            brand=brand,
            price=price,
            fact_warnings=warnings,
        )
```

- [ ] **Step 6: Run adapter tests**

Run:

```bash
python3 -m pytest -q tests/guide/adapters/catalog/test_canonical_guide_catalog.py tests/guide/retrieval
python3 -m pytest -q tests/guide tests/slice0
python3 app/guide/check_boundaries.py app/guide
```

Expected: PASS.

- [ ] **Step 7: Commit authorized fact adapters**

```bash
git add app/guide/decision app/guide/presentation app/guide/adapters/catalog tests/guide/adapters
git commit -m "feat(guide): expose authorized canonical facts through ports"
```

---

### Task 5: Rebuild Strict Decision Semantics

**Files:**
- Modify: `app/guide/decision/contracts.py`
- Modify: `app/guide/decision/recommendation.py`
- Modify: `tests/guide/decision/test_recommendation.py`

- [ ] **Step 1: Replace the false-positive decision tests**

At the top of `tests/guide/decision/test_recommendation.py`, replace the
Canonical file helper with this complete in-memory fixture:

```python
from decimal import Decimal

from app.guide.decision.contracts import (
    CandidateEvaluation,
    DecisionProductFacts,
    DecisionResult,
    FactState,
    WinnerStatus,
)
from app.guide.decision.recommendation import decide_recommendation
from app.guide.intent.contracts import (
    BudgetConstraint,
    CategoryConstraint,
    ExclusionConstraint,
    SkinConstraint,
)
from app.guide.retrieval.contracts import CandidateRef, RetrievalResult
from app.guide.understanding.contracts import SkinTarget, TopicCode


class MemoryFacts:
    def __init__(self, products: list[DecisionProductFacts]) -> None:
        self._products = {item.product_id: item for item in products}

    def get_decision_facts(
        self,
        product_id: int,
    ) -> DecisionProductFacts:
        return self._products[product_id].model_copy(deep=True)


def facts(
    product_id: int,
    *,
    price: Decimal | None = Decimal("100"),
    price_state: FactState = FactState.KNOWN,
    skin: tuple[str, ...] | None = ("油敏",),
    skin_state: FactState = FactState.KNOWN,
    ingredients: tuple[str, ...] | None = ("水",),
    ingredients_state: FactState = FactState.KNOWN,
    absences: tuple[str, ...] | None = ("酒精",),
    absences_state: FactState = FactState.KNOWN,
) -> DecisionProductFacts:
    return DecisionProductFacts(
        product_id=product_id,
        price=price,
        price_state=price_state,
        suitable_skin=skin,
        suitable_skin_state=skin_state,
        ingredients_present=ingredients,
        ingredients_present_state=ingredients_state,
        verified_absences=absences,
        verified_absences_state=absences_state,
    )


def decide_with(
    products: list[DecisionProductFacts],
    *,
    include_skin: bool = True,
    exclude: str | None = None,
) -> DecisionResult:
    constraints = [
        CategoryConstraint(value=TopicCode.SUNSCREEN),
        BudgetConstraint(minimum=None, maximum=Decimal("500")),
    ]
    if include_skin:
        constraints.append(
            SkinConstraint(value=SkinTarget.OILY_SENSITIVE)
        )
    if exclude is not None:
        constraints.append(ExclusionConstraint(value=exclude))
    retrieval = RetrievalResult(
        candidates=[
            CandidateRef(
                product_id=item.product_id,
                source="canonical",
                canonical_category="防晒",
                retrieval_reason="test",
            )
            for item in products
        ],
        knowledge_evidence=[],
        review_evidence=[],
        memory_evidence=[],
        missing_sources=[],
    )
    return decide_recommendation(
        MemoryFacts(products),
        retrieval,
        constraints=constraints,
    )


def evaluation(
    result: DecisionResult,
    product_id: int,
) -> CandidateEvaluation:
    return next(
        item
        for item in result.evaluations
        if item.product_id == product_id
    )


def test_price_unknown_and_boolean_conflict_are_excluded() -> None:
    result = decide_with([
        facts(1, price=None, price_state=FactState.UNKNOWN),
        facts(2, price=None, price_state=FactState.CONFLICT),
        facts(3, price=Decimal("100"), price_state=FactState.KNOWN),
    ])
    assert result.ordered_product_ids == [3]


def test_a2_keeps_unknown_but_excludes_known_mismatch() -> None:
    result = decide_with([
        facts(1, skin=("油敏",), skin_state=FactState.KNOWN),
        facts(2, skin=None, skin_state=FactState.UNKNOWN),
        facts(3, skin=("干性",), skin_state=FactState.KNOWN),
    ])
    assert result.ordered_product_ids == [1, 2]
    assert evaluation(result, 1).skin_match == "matched"
    assert evaluation(result, 2).skin_match == "unknown"
    assert evaluation(result, 3).disposition == "excluded_skin_mismatch"


def test_no_skin_constraint_is_not_applicable() -> None:
    result = decide_with(
        [facts(1, skin=None, skin_state=FactState.UNKNOWN)],
        include_skin=False,
    )
    assert evaluation(result, 1).skin_match == "not_applicable"
    assert result.risk_findings == []


def test_exclusion_unknown_is_fail_closed() -> None:
    result = decide_with([
        facts(
            1,
            ingredients=None,
            ingredients_state=FactState.UNKNOWN,
            absences=None,
            absences_state=FactState.UNKNOWN,
        )
    ], exclude="酒精")
    assert result.ordered_product_ids == []
    assert evaluation(result, 1).disposition == "excluded_evidence_unknown"


def test_exclusion_known_present_is_excluded() -> None:
    result = decide_with([
        facts(
            1,
            ingredients=("水", "酒精"),
            absences=(),
        )
    ], exclude="酒精")
    assert result.ordered_product_ids == []
    assert evaluation(result, 1).disposition == "excluded_exclusion_match"


def test_verified_absence_satisfies_exclusion() -> None:
    result = decide_with([
        facts(
            1,
            ingredients=("水",),
            absences=("酒精",),
        )
    ], exclude="酒精")
    assert result.ordered_product_ids == [1]


def test_business_tie_does_not_select_product_id_winner() -> None:
    result = decide_with([
        facts(1, price=Decimal("100"), skin=("油敏",)),
        facts(2, price=Decimal("100"), skin=("油敏",)),
    ])
    assert result.winner_status is WinnerStatus.TIED_BY_BUSINESS_EVIDENCE
    assert result.winner_product_id is None
    assert result.tie_reason is not None


def test_evidence_uses_actual_category_constraint() -> None:
    result = decide_with([facts(1)])
    assert "category=sunscreen" in result.evidence_refs
    assert all("category=防晒" not in ref for ref in result.evidence_refs)
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
python3 -m pytest -q tests/guide/decision/test_recommendation.py
```

Expected: FAIL on mismatch, exclusion, tie, typed evaluations and evidence.

- [ ] **Step 3: Type evaluations and risks**

Add to `app/guide/decision/contracts.py`:

```python
from typing import Literal


class CandidateEvaluation(_StrictContract):
    product_id: int
    disposition: Literal[
        "eligible",
        "excluded_price_unknown",
        "excluded_budget",
        "excluded_skin_mismatch",
        "excluded_exclusion_match",
        "excluded_evidence_unknown",
    ]
    price: Decimal | None
    skin_match: Literal[
        "matched",
        "unknown",
        "mismatch",
        "not_applicable",
    ]
    reasons: list[str]


class RiskFinding(_StrictContract):
    kind: Literal[
        "skin_match_unknown",
        "exclusion_evidence_unknown",
        "canonical_fact_conflict",
    ]
    product_id: int
    detail: str
```

Change `DecisionResult.evaluations` to `list[CandidateEvaluation]` and `risk_findings` to `list[RiskFinding]`. Extend its model validator:

```python
if (
    self.winner_status is WinnerStatus.TIED_BY_BUSINESS_EVIDENCE
    and not self.tie_reason
):
    raise ValueError("tie_reason is required for business tie")
if (
    self.winner_status is not WinnerStatus.TIED_BY_BUSINESS_EVIDENCE
    and self.tie_reason is not None
):
    raise ValueError("tie_reason is only valid for business tie")
```

- [ ] **Step 4: Replace loose lookup with typed constraint extraction**

In `recommendation.py`, accept:

```python
def decide_recommendation(
    facts: DecisionFactPort,
    retrieval: RetrievalResult,
    *,
    constraints: list[TaskConstraint],
) -> DecisionResult:
```

Extract constraints with explicit types:

```python
budget = next(
    (item for item in constraints if isinstance(item, BudgetConstraint)),
    None,
)
category = next(
    (item for item in constraints if isinstance(item, CategoryConstraint)),
    None,
)
skin = next(
    (item for item in constraints if isinstance(item, SkinConstraint)),
    None,
)
exclusions = [
    item
    for item in constraints
    if isinstance(item, ExclusionConstraint)
]
```

- [ ] **Step 5: Implement hard filters and A2**

Replace `app/guide/decision/recommendation.py` with the following logic while
keeping the existing module docstring:

```python
from __future__ import annotations

import json
from typing import Literal

from app.guide.decision.contracts import (
    CandidateEvaluation,
    DecisionProductFacts,
    DecisionResult,
    FactState,
    RiskFinding,
    WinnerStatus,
)
from app.guide.decision.deterministic_ranking import (
    sort_product_candidates,
)
from app.guide.decision.ports import DecisionFactPort
from app.guide.intent.contracts import (
    BudgetConstraint,
    CategoryConstraint,
    ExclusionConstraint,
    SkinConstraint,
    TaskConstraint,
)
from app.guide.retrieval.contracts import RetrievalResult
from app.guide.understanding.contracts import SkinTarget

SkinMatch = Literal[
    "matched",
    "unknown",
    "mismatch",
    "not_applicable",
]

_SKIN_MARKERS = {
    SkinTarget.OILY_SENSITIVE: ("油敏",),
    SkinTarget.OILY: ("油",),
    SkinTarget.DRY: ("干",),
    SkinTarget.COMBINATION: ("混",),
    SkinTarget.SENSITIVE: ("敏",),
    SkinTarget.NORMAL: ("中性",),
}


def decide_recommendation(
    facts: DecisionFactPort,
    retrieval: RetrievalResult,
    *,
    constraints: list[TaskConstraint],
) -> DecisionResult:
    budget = next(
        (
            item
            for item in constraints
            if isinstance(item, BudgetConstraint)
        ),
        None,
    )
    category = next(
        (
            item
            for item in constraints
            if isinstance(item, CategoryConstraint)
        ),
        None,
    )
    skin = next(
        (
            item
            for item in constraints
            if isinstance(item, SkinConstraint)
        ),
        None,
    )
    exclusions = [
        item
        for item in constraints
        if isinstance(item, ExclusionConstraint)
    ]
    if category is None:
        raise ValueError("decision requires category constraint")

    rows: list[dict[str, object]] = []
    evaluations: list[CandidateEvaluation] = []
    risk_findings: list[RiskFinding] = []

    for candidate in retrieval.candidates:
        product = facts.get_decision_facts(candidate.product_id)
        if product.product_id != candidate.product_id:
            raise ValueError("decision facts product_id mismatch")

        if (
            product.price_state is not FactState.KNOWN
            or product.price is None
        ):
            evaluations.append(_evaluation(
                product,
                disposition="excluded_price_unknown",
                skin_match="not_applicable",
                reasons=[f"price_state={product.price_state.value}"],
            ))
            if product.price_state is FactState.CONFLICT:
                risk_findings.append(RiskFinding(
                    kind="canonical_fact_conflict",
                    product_id=product.product_id,
                    detail="价格事实冲突，已按 fail-closed 排除",
                ))
            continue

        if _outside_budget(product, budget):
            evaluations.append(_evaluation(
                product,
                disposition="excluded_budget",
                skin_match="not_applicable",
                reasons=["outside_budget"],
            ))
            continue

        exclusion_disposition = _exclusion_disposition(
            product,
            exclusions,
        )
        if exclusion_disposition is not None:
            evaluations.append(_evaluation(
                product,
                disposition=exclusion_disposition,
                skin_match="not_applicable",
                reasons=[exclusion_disposition],
            ))
            if exclusion_disposition == "excluded_evidence_unknown":
                risk_findings.append(RiskFinding(
                    kind="exclusion_evidence_unknown",
                    product_id=product.product_id,
                    detail="缺少排除项不存在的审核证据",
                ))
            continue

        skin_match = _skin_match(product, skin)
        if skin_match == "mismatch":
            evaluations.append(_evaluation(
                product,
                disposition="excluded_skin_mismatch",
                skin_match="mismatch",
                reasons=["known_skin_mismatch"],
            ))
            continue
        if skin_match == "unknown":
            risk_findings.append(RiskFinding(
                kind="skin_match_unknown",
                product_id=product.product_id,
                detail="肤质数据缺失，未确认是否适合",
            ))

        rows.append({
            "id": product.product_id,
            "skin_rank": 1 if skin_match == "unknown" else 0,
            "price": product.price,
        })
        evaluations.append(_evaluation(
            product,
            disposition="eligible",
            skin_match=skin_match,
            reasons=["hard_constraints_passed"],
        ))

    ordered = sort_product_candidates(
        rows,
        business_key=lambda row: (
            row["skin_rank"],
            row["price"],
        ),
        directions=("asc", "asc"),
        business_key_names=("skin_rank", "price"),
        chain="slice1_recommendation",
    )
    ordered_ids = [int(row["id"]) for row in ordered.items]
    winner_status, winner_id, tie_reason = _winner(
        ordered,
        skin_required=skin is not None,
    )

    evidence_refs = [f"category={category.value.value}"]
    if budget is not None and budget.minimum is not None:
        evidence_refs.append(f"budget_min>={budget.minimum}")
    if budget is not None and budget.maximum is not None:
        evidence_refs.append(f"budget_max<={budget.maximum}")
    evidence_refs.extend(
        f"exclude={item.value}"
        for item in exclusions
    )

    dimensions = ["price"]
    if skin is not None:
        dimensions.insert(0, "skin_match")

    return DecisionResult(
        ordered_product_ids=ordered_ids,
        winner_status=winner_status,
        winner_product_id=winner_id,
        evaluations=evaluations,
        comparison_dimensions=dimensions,
        risk_findings=risk_findings,
        evidence_refs=evidence_refs,
        tie_reason=tie_reason,
    )


def _outside_budget(
    product: DecisionProductFacts,
    budget: BudgetConstraint | None,
) -> bool:
    if budget is None:
        return False
    assert product.price is not None
    return (
        budget.minimum is not None
        and product.price < budget.minimum
    ) or (
        budget.maximum is not None
        and product.price > budget.maximum
    )


def _exclusion_disposition(
    product: DecisionProductFacts,
    exclusions: list[ExclusionConstraint],
) -> Literal[
    "excluded_exclusion_match",
    "excluded_evidence_unknown",
] | None:
    for exclusion in exclusions:
        term = exclusion.value.casefold()
        present = product.ingredients_present or ()
        absent = product.verified_absences or ()
        if (
            product.ingredients_present_state is FactState.KNOWN
            and any(term in value.casefold() for value in present)
        ):
            return "excluded_exclusion_match"
        if (
            product.verified_absences_state is FactState.KNOWN
            and any(term in value.casefold() for value in absent)
        ):
            continue
        return "excluded_evidence_unknown"
    return None


def _skin_match(
    product: DecisionProductFacts,
    constraint: SkinConstraint | None,
) -> SkinMatch:
    if constraint is None:
        return "not_applicable"
    if (
        product.suitable_skin_state is not FactState.KNOWN
        or product.suitable_skin is None
    ):
        return "unknown"
    combined = " ".join(product.suitable_skin)
    markers = _SKIN_MARKERS[constraint.value]
    if constraint.value is SkinTarget.OILY_SENSITIVE:
        matched = (
            "油敏" in combined
            or ("油" in combined and "敏" in combined)
        )
    else:
        matched = any(marker in combined for marker in markers)
    return "matched" if matched else "mismatch"


def _evaluation(
    product: DecisionProductFacts,
    *,
    disposition: Literal[
        "eligible",
        "excluded_price_unknown",
        "excluded_budget",
        "excluded_skin_mismatch",
        "excluded_exclusion_match",
        "excluded_evidence_unknown",
    ],
    skin_match: SkinMatch,
    reasons: list[str],
) -> CandidateEvaluation:
    return CandidateEvaluation(
        product_id=product.product_id,
        disposition=disposition,
        price=product.price,
        skin_match=skin_match,
        reasons=reasons,
    )


def _winner(
    ordered,
    *,
    skin_required: bool,
) -> tuple[WinnerStatus, int | None, str | None]:
    if not ordered.items:
        return WinnerStatus.NO_CANDIDATE, None, None
    top = ordered.items[0]
    top_id = int(top["id"])
    if skin_required and top["skin_rank"] == 1:
        return WinnerStatus.INSUFFICIENT_FOR_WINNER, None, None
    top_tie = ordered.tie_reason_by_id.get(top_id)
    if top_tie is not None:
        return (
            WinnerStatus.TIED_BY_BUSINESS_EVIDENCE,
            None,
            json.dumps(
                top_tie,
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
    return WinnerStatus.SELECTED, top_id, None
```

- [ ] **Step 6: Verify tie and evidence branches directly**

Run:

```bash
python3 -m pytest -q \
  tests/guide/decision/test_recommendation.py::test_business_tie_does_not_select_product_id_winner \
  tests/guide/decision/test_recommendation.py::test_evidence_uses_actual_category_constraint
```

Expected: PASS. The first case consumes `tie_reason_by_id`; the second builds
evidence only from typed constraints.

- [ ] **Step 7: Run decision tests and unchanged ranking tests**

Run:

```bash
python3 -m pytest -q tests/guide/decision
python3 -m pytest -q tests/guide tests/slice0
python3 app/guide/check_boundaries.py app/guide
```

Expected: PASS. `deterministic_ranking.py` SHA remains unchanged.

- [ ] **Step 8: Verify the ranking SHA**

Run:

```bash
shasum -a 256 app/guide/decision/deterministic_ranking.py
```

Expected:

```text
4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f
```

- [ ] **Step 9: Commit strict decision semantics**

```bash
git add app/guide/decision tests/guide/decision
git commit -m "fix(decision): enforce slice 1 hard constraints and winner states"
```

---

### Task 6: Build Typed Product Cards Without Inventing Facts

**Files:**
- Modify: `app/guide/presentation/contracts.py`
- Modify: `app/guide/presentation/response_planning.py`
- Modify: `tests/guide/presentation/test_response_planning.py`

- [ ] **Step 1: Write missing-fact and tri-state card tests**

Replace the old dict-based helpers, then add the tests:

```python
from decimal import Decimal

import pytest

from app.guide.decision.contracts import (
    CandidateEvaluation,
    DecisionResult,
    RiskFinding,
    WinnerStatus,
)
from app.guide.presentation.contracts import ProductCardFacts
from app.guide.presentation.response_planning import (
    MissingProductFactsError,
)


def _decision() -> DecisionResult:
    product_ids = [57, 51, 26, 101]
    return DecisionResult(
        ordered_product_ids=product_ids,
        winner_status=WinnerStatus.INSUFFICIENT_FOR_WINNER,
        winner_product_id=None,
        evaluations=[
            CandidateEvaluation(
                product_id=product_id,
                disposition="eligible",
                price=price,
                skin_match="unknown",
                reasons=["hard_constraints_passed"],
            )
            for product_id, price in zip(
                product_ids,
                (
                    Decimal("92.02"),
                    Decimal("99.9"),
                    Decimal("329"),
                    Decimal("500"),
                ),
                strict=True,
            )
        ],
        comparison_dimensions=["skin_match", "price"],
        risk_findings=[
            RiskFinding(
                kind="skin_match_unknown",
                product_id=product_id,
                detail="肤质数据缺失",
            )
            for product_id in product_ids
        ],
        evidence_refs=["category=sunscreen", "budget_max<=500"],
        tie_reason=None,
    )


def _facts() -> dict[int, ProductCardFacts]:
    return {
        product_id: ProductCardFacts(
            product_id=product_id,
            name=f"商品 {product_id}",
            brand="测试品牌",
            price=price,
            fact_warnings=[],
        )
        for product_id, price in (
            (57, Decimal("92.02")),
            (51, Decimal("99.9")),
            (26, Decimal("329")),
            (101, Decimal("500")),
        )
    }


def test_missing_product_fact_record_fails_closed() -> None:
    with pytest.raises(MissingProductFactsError, match="product_id 57"):
        build()(_decision(), product_facts={})


def test_card_skin_state_comes_from_evaluation() -> None:
    plan = build()(_decision(), product_facts=_facts())
    cards = plan.structured_events
    assert [card.skin_match for card in cards] == [
        "unknown",
        "unknown",
        "unknown",
        "unknown",
    ]


def test_unusable_name_is_preserved_with_warning() -> None:
    facts = _facts()
    facts[57] = ProductCardFacts(
        product_id=57,
        name="无",
        brand="测试品牌",
        price=Decimal("92.02"),
        fact_warnings=["product_identity_unusable"],
    )
    card = build()(_decision(), product_facts=facts).structured_events[0]
    assert card.name == "无"
    assert card.fact_warnings == ["product_identity_unusable"]
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
python3 -m pytest -q tests/guide/presentation/test_response_planning.py
```

Expected: FAIL because missing facts currently become null cards and card models are dicts.

- [ ] **Step 3: Define typed product cards**

Add to `app/guide/presentation/contracts.py`:

```python
from typing import Literal


class ProductCard(_StrictContract):
    type: Literal["product_card"] = "product_card"
    product_id: int
    name: str | None
    brand: str | None
    price: Decimal | None
    skin_match: Literal[
        "matched",
        "unknown",
        "not_applicable",
    ]
    fact_warnings: list[str]


class ResponsePlan(_StrictContract):
    sections: list[Literal["recommendation"]]
    structured_events: list[ProductCard]
    text_generation_context: dict[str, JsonValue]
    followup_actions: list[dict[str, JsonValue]]
```

- [ ] **Step 4: Build cards from complete fact records**

Replace `build_response_plan()`:

```python
class MissingProductFactsError(LookupError):
    pass


def build_response_plan(
    decision: DecisionResult,
    *,
    product_facts: dict[int, ProductCardFacts],
) -> ResponsePlan:
    evaluations = {
        item.product_id: item
        for item in decision.evaluations
        if item.disposition == "eligible"
    }
    cards: list[ProductCard] = []
    for product_id in decision.ordered_product_ids:
        try:
            facts = product_facts[product_id]
            evaluation = evaluations[product_id]
        except KeyError as exc:
            raise MissingProductFactsError(
                f"missing presentation facts for product_id {product_id}"
            ) from exc
        cards.append(ProductCard(
            product_id=product_id,
            name=facts.name,
            brand=facts.brand,
            price=facts.price,
            skin_match=evaluation.skin_match,
            fact_warnings=list(facts.fact_warnings),
        ))
    return ResponsePlan(
        sections=["recommendation"],
        structured_events=cards,
        text_generation_context={
            "winner_status": decision.winner_status.value,
            "evidence_refs": list(decision.evidence_refs),
            "comparison_dimensions": list(decision.comparison_dimensions),
            "risk_findings": [
                item.model_dump(mode="json")
                for item in decision.risk_findings
            ],
        },
        followup_actions=[],
    )
```

- [ ] **Step 5: Run presentation tests**

Run:

```bash
python3 -m pytest -q tests/guide/presentation
python3 -m pytest -q tests/guide tests/slice0
python3 app/guide/check_boundaries.py app/guide
```

Expected: PASS.

- [ ] **Step 6: Commit typed presentation**

```bash
git add app/guide/presentation tests/guide/presentation
git commit -m "feat(presentation): emit typed product cards with fact warnings"
```

---

### Task 7: Implement the Application Port and True SSE Generator

**Files:**
- Create: `app/guide/presentation/sse_events.py`
- Create: `app/guide/feedback/ports.py`
- Create: `tests/guide/application/conftest.py`
- Modify: `app/guide/application/orchestrator.py`
- Modify: `app/guide/application/text_recommendation_flow.py`
- Modify: `tests/guide/application/test_text_recommendation_flow.py`

- [ ] **Step 1: Write streaming and terminal-state tests**

Create `tests/guide/application/conftest.py`:

```python
from pathlib import Path

import pytest

from app.guide.adapters.catalog import CanonicalProductReader
from app.guide.application.text_recommendation_flow import (
    build_text_recommendation_orchestrator,
)

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def real_reader() -> CanonicalProductReader:
    canonical = ROOT / "data" / "canonical"
    return CanonicalProductReader.from_files(
        manifest_path=canonical / "core_products_v1_manifest.json",
        products_path=canonical / "core_products_v1.jsonl",
    )


@pytest.fixture
def orchestrator(real_reader):
    return build_text_recommendation_orchestrator(real_reader)


class BrokenReader:
    product_ids = frozenset({1})

    def get(self, product_id: int):
        raise RuntimeError(f"catalog failed for {product_id}")


@pytest.fixture
def broken_orchestrator():
    return build_text_recommendation_orchestrator(BrokenReader())
```

Replace list-based assertions in
`tests/guide/application/test_text_recommendation_flow.py` with:

```python
from collections.abc import Iterator

from app.guide.adapters.catalog import CanonicalProductReader
from app.guide.application.contracts import UserTurn
from app.guide.application.text_recommendation_flow import (
    build_text_recommendation_orchestrator,
)


def _turn(message: str) -> UserTurn:
    return UserTurn(
        session_id="s-1",
        message=message,
        image_bundle_id=None,
        conversation_version=0,
    )


def test_stream_yields_start_before_catalog_work(orchestrator) -> None:
    stream = orchestrator.stream(_turn("500 内适合油敏肌的防晒"))
    assert isinstance(stream, Iterator)
    first = next(stream)
    assert first.event == "start"


def test_full_query_has_contract_order_and_no_false_winner(
    orchestrator,
) -> None:
    events = list(
        orchestrator.stream(_turn("500 内适合油敏肌的防晒"))
    )
    names = [item.event for item in events]
    assert names[0] == "start"
    assert names[-1] == "end"
    assert names.count("end") == 1
    assert names.index("decision_process") < names.index("answer_contract")
    assert names.index("answer_contract") < names.index("products")
    products = next(item for item in events if item.event == "products")
    assert [card.product_id for card in products.data.cards] == [
        55, 57, 54, 51, 102, 53, 58, 56, 52, 26, 101
    ]
    decision = next(
        item for item in events if item.event == "decision_process"
    )
    assert decision.data.winner_status == "INSUFFICIENT_FOR_WINNER"
    messages = [item.data.content for item in events if item.event == "message"]
    assert messages
    assert all(content.strip() for content in messages)


def test_error_is_terminal_and_public(broken_orchestrator) -> None:
    events = list(
        broken_orchestrator.stream(
            _turn("500 内适合油敏肌的防晒")
        )
    )
    names = [item.event for item in events]
    assert names[-1] == "error"
    assert "end" not in names
    assert "catalog failed" not in events[-1].data.message


def test_injected_reader_prevents_per_request_file_reload(
    real_reader,
    monkeypatch,
) -> None:
    def forbidden_reload(*args, **kwargs):
        raise AssertionError("reader must be created by application lifecycle")

    monkeypatch.setattr(
        CanonicalProductReader,
        "from_files",
        forbidden_reload,
    )
    orchestrator = build_text_recommendation_orchestrator(real_reader)
    list(orchestrator.stream(_turn("防晒")))
    list(orchestrator.stream(_turn("500 内防晒")))
```

The lifecycle test must pass an already-created reader. It must not patch protected `chat.py` or start FastAPI.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
python3 -m pytest -q tests/guide/application/test_text_recommendation_flow.py
```

Expected: FAIL because the current function returns a list, leaks exceptions and only recalls 5 products.

- [ ] **Step 3: Define typed SSE events**

Create `app/guide/presentation/sse_events.py` with strict payload models:

```python
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.guide.presentation.contracts import ProductCard


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class StartData(_Strict):
    session_id: str


class StageData(_Strict):
    stage: Literal["understanding", "retrieval", "decision"]
    summary: str


class IntentData(_Strict):
    mode: Literal["recommend", "clarify"]


class ClarifyData(_Strict):
    question: str


class DecisionProcessData(_Strict):
    ordered_product_ids: list[int]
    winner_status: str
    evidence_refs: list[str]


class AnswerContractData(_Strict):
    product_count: int
    winner_status: str
    has_unknown_skin: bool


class ProductsData(_Strict):
    cards: list[ProductCard]


class MessageData(_Strict):
    content: str = Field(min_length=1)


class ErrorData(_Strict):
    code: Literal["GUIDE_INTERNAL_ERROR"]
    message: Literal["推荐暂时不可用，请稍后重试。"]


class EmptyData(_Strict):
    pass


class StartEvent(_Strict):
    event: Literal["start"] = "start"
    data: StartData


class StageEvent(_Strict):
    event: Literal["stage"] = "stage"
    data: StageData


class IntentEvent(_Strict):
    event: Literal["intent"] = "intent"
    data: IntentData


class ClarifyEvent(_Strict):
    event: Literal["clarify"] = "clarify"
    data: ClarifyData


class DecisionProcessEvent(_Strict):
    event: Literal["decision_process"] = "decision_process"
    data: DecisionProcessData


class AnswerContractEvent(_Strict):
    event: Literal["answer_contract"] = "answer_contract"
    data: AnswerContractData


class ProductsEvent(_Strict):
    event: Literal["products"] = "products"
    data: ProductsData


class MessageEvent(_Strict):
    event: Literal["message"] = "message"
    data: MessageData


class ErrorEvent(_Strict):
    event: Literal["error"] = "error"
    data: ErrorData


class EndEvent(_Strict):
    event: Literal["end"] = "end"
    data: EmptyData


SseEvent = Annotated[
    StartEvent
    | StageEvent
    | IntentEvent
    | ClarifyEvent
    | DecisionProcessEvent
    | AnswerContractEvent
    | ProductsEvent
    | MessageEvent
    | ErrorEvent
    | EndEvent,
    Field(discriminator="event"),
]
```

- [ ] **Step 4: Define an honest feedback boundary**

Create `app/guide/feedback/ports.py`:

```python
from enum import Enum
from typing import Protocol

from app.guide.application.contracts import UserTurn


class FeedbackWriteStatus(str, Enum):
    SKIPPED_SLICE_SCOPE = "SKIPPED_SLICE_SCOPE"


class FeedbackPort(Protocol):
    def record_turn(self, turn: UserTurn) -> FeedbackWriteStatus: ...


class Slice1DisabledFeedback:
    def record_turn(self, turn: UserTurn) -> FeedbackWriteStatus:
        return FeedbackWriteStatus.SKIPPED_SLICE_SCOPE
```

- [ ] **Step 5: Align the application protocol**

Replace `GuideOrchestrator` in `app/guide/application/orchestrator.py`:

```python
from collections.abc import Iterator
from typing import Protocol

from app.guide.application.contracts import UserTurn
from app.guide.presentation.contracts import ResponsePlan
from app.guide.presentation.sse_events import SseEvent


class GuideOrchestrator(Protocol):
    def orchestrate(self, turn: UserTurn) -> ResponsePlan: ...
    def stream(self, turn: UserTurn) -> Iterator[SseEvent]: ...
```

- [ ] **Step 6: Replace the list function with an injected orchestrator**

In `app/guide/application/text_recommendation_flow.py`, define:

```python
from collections.abc import Iterator
import logging

from app.guide.adapters.catalog import CanonicalProductReader
from app.guide.adapters.catalog.canonical_guide_catalog import (
    CanonicalGuideCatalog,
)
from app.guide.application.contracts import UserTurn
from app.guide.decision.contracts import DecisionResult, WinnerStatus
from app.guide.decision.ports import DecisionFactPort
from app.guide.decision.recommendation import decide_recommendation
from app.guide.feedback.ports import (
    FeedbackPort,
    FeedbackWriteStatus,
    Slice1DisabledFeedback,
)
from app.guide.intent.contracts import CategoryConstraint
from app.guide.intent.task_planning import plan_task
from app.guide.presentation.contracts import ResponsePlan
from app.guide.presentation.ports import PresentationFactPort
from app.guide.presentation.response_planning import build_response_plan
from app.guide.presentation.sse_events import (
    AnswerContractData,
    AnswerContractEvent,
    ClarifyData,
    ClarifyEvent,
    DecisionProcessData,
    DecisionProcessEvent,
    EmptyData,
    EndEvent,
    ErrorData,
    ErrorEvent,
    IntentData,
    IntentEvent,
    MessageData,
    MessageEvent,
    ProductsData,
    ProductsEvent,
    SseEvent,
    StageData,
    StageEvent,
    StartData,
    StartEvent,
)
from app.guide.retrieval.ports import CategoryCatalogPort
from app.guide.retrieval.canonical_retrieval import retrieve_candidates
from app.guide.understanding.text_understanding import understand_text

logger = logging.getLogger(__name__)


class TextRecommendationOrchestrator:
    def __init__(
        self,
        *,
        category_catalog: CategoryCatalogPort,
        decision_facts: DecisionFactPort,
        presentation_facts: PresentationFactPort,
        feedback: FeedbackPort,
    ) -> None:
        self._category_catalog = category_catalog
        self._decision_facts = decision_facts
        self._presentation_facts = presentation_facts
        self._feedback = feedback

    def orchestrate(self, turn: UserTurn) -> ResponsePlan:
        understanding = understand_text(turn.message)
        task = plan_task(understanding)
        if task.mode == "clarify":
            raise ValueError("clarification has no recommendation plan")
        category = next(
            item
            for item in task.constraints
            if isinstance(item, CategoryConstraint)
        )
        retrieval = retrieve_candidates(
            self._category_catalog,
            category=category.value,
        )
        decision = decide_recommendation(
            self._decision_facts,
            retrieval,
            constraints=task.constraints,
        )
        return self._build_plan(decision)

    def _build_plan(self, decision: DecisionResult) -> ResponsePlan:
        product_facts = {
            product_id: self._presentation_facts.get_presentation_facts(
                product_id
            )
            for product_id in decision.ordered_product_ids
        }
        return build_response_plan(
            decision,
            product_facts=product_facts,
        )
```

Implement `stream()` as a generator with one terminal branch:

```python
def stream(self, turn: UserTurn) -> Iterator[SseEvent]:
    yield StartEvent(data=StartData(session_id=turn.session_id))
    try:
        understanding = understand_text(turn.message)
        yield StageEvent(data=StageData(
            stage="understanding",
            summary="已提取明确预算、品类和适配条件。",
        ))
        task = plan_task(understanding)
        yield IntentEvent(data=IntentData(mode=task.mode))
        if task.mode == "clarify":
            yield ClarifyEvent(data=ClarifyData(
                question=task.clarification,
            ))
            yield EndEvent(data=EmptyData())
            return

        category = next(
            item
            for item in task.constraints
            if isinstance(item, CategoryConstraint)
        )
        yield StageEvent(data=StageData(
            stage="retrieval",
            summary="正在读取已审核的 Canonical 商品事实。",
        ))
        retrieval = retrieve_candidates(
            self._category_catalog,
            category=category.value,
        )
        yield StageEvent(data=StageData(
            stage="decision",
            summary="正在执行预算、排除项和肤质证据规则。",
        ))
        decision = decide_recommendation(
            self._decision_facts,
            retrieval,
            constraints=task.constraints,
        )
        yield DecisionProcessEvent(data=DecisionProcessData(
            ordered_product_ids=list(decision.ordered_product_ids),
            winner_status=decision.winner_status.value,
            evidence_refs=list(decision.evidence_refs),
        ))
        plan = self._build_plan(decision)
        has_unknown_skin = any(
            item.kind == "skin_match_unknown"
            for item in decision.risk_findings
        )
        yield AnswerContractEvent(data=AnswerContractData(
            product_count=len(plan.structured_events),
            winner_status=decision.winner_status.value,
            has_unknown_skin=has_unknown_skin,
        ))
        yield ProductsEvent(data=ProductsData(
            cards=list(plan.structured_events),
        ))
        yield MessageEvent(data=MessageData(
            content=_summary_fragment(decision),
        ))
        status = self._feedback.record_turn(turn)
        if status is not FeedbackWriteStatus.SKIPPED_SLICE_SCOPE:
            raise RuntimeError("unexpected feedback write status")
        yield EndEvent(data=EmptyData())
    except Exception:
        logger.exception(
            "slice 1 recommendation failed for session_id=%s",
            turn.session_id,
        )
        yield ErrorEvent(data=ErrorData(
            code="GUIDE_INTERNAL_ERROR",
            message="推荐暂时不可用，请稍后重试。",
        ))
```

Define `_summary_fragment()` deterministically:

```python
def _summary_fragment(decision: DecisionResult) -> str:
    if decision.winner_status is WinnerStatus.NO_CANDIDATE:
        return "没有商品能在现有证据下同时满足这些硬条件。"
    if decision.winner_status is WinnerStatus.INSUFFICIENT_FOR_WINNER:
        return "已保留符合预算的候选，但现有肤质证据不足以选出唯一推荐。"
    if decision.winner_status is WinnerStatus.TIED_BY_BUSINESS_EVIDENCE:
        return "前列商品的业务证据相同，暂不强行指定唯一推荐。"
    return "已按明确条件完成筛选和稳定排序。"
```

- [ ] **Step 7: Add an explicit lifecycle factory**

Add:

```python
def build_text_recommendation_orchestrator(
    reader: CanonicalProductReader,
) -> TextRecommendationOrchestrator:
    catalog = CanonicalGuideCatalog(reader)
    return TextRecommendationOrchestrator(
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        feedback=Slice1DisabledFeedback(),
    )
```

Do not add a relative `Path("data/canonical")` default. API integration in a later plan must construct `CanonicalProductReader` once from configured absolute paths and inject it here.

- [ ] **Step 8: Run application and full backend tests**

Run:

```bash
python3 -m pytest -q tests/guide/application tests/guide/presentation tests/guide/decision tests/guide/retrieval tests/guide/intent tests/guide/understanding tests/guide/contracts tests/guide/adapters
python3 -m pytest -q tests/guide tests/slice0
python3 app/guide/check_boundaries.py app/guide
```

Expected: PASS; no protected frontend or API file changed.

- [ ] **Step 9: Commit the true stream**

```bash
git add app/guide/application app/guide/presentation/sse_events.py app/guide/feedback tests/guide/application
git commit -m "feat(application): stream typed slice 1 backend events"
```

---

### Task 8: Add the Reproducible Backend Gate and Repair Documentation Drift

**Files:**
- Create: `pytest-guide.ini`
- Create: `tests/fixtures/guide/slice1_backend_cases.json`
- Create: `tests/guide/application/test_slice1_backend_gate.py`
- Create: `tools/guide_gates/__init__.py`
- Create: `tools/guide_gates/slice1_backend.py`
- Modify: `docs/superpowers/specs/2026-08-06-xiaoro-clean-growth-architecture-design.md`
- Modify: `docs/audits/slice0-foundation/morning_handoff.md`

- [ ] **Step 1: Create a clean pytest entry**

Create `pytest-guide.ini`:

```ini
[pytest]
testpaths =
    tests/guide
    tests/slice0
python_files = test_*.py
addopts = -ra
```

This avoids collecting legacy `scripts/*_test.py` and old `app.services` integration tests. It does not delete or hide them from their own legacy commands.

- [ ] **Step 2: Create the backend case fixture**

Create `tests/fixtures/guide/slice1_backend_cases.json`:

```json
[
  {
    "case_id": "slice1_full",
    "message": "500 内适合油敏肌的防晒",
    "terminal_event": "end",
    "winner_status": "INSUFFICIENT_FOR_WINNER",
    "product_ids": [55, 57, 54, 51, 102, 53, 58, 56, 52, 26, 101]
  },
  {
    "case_id": "slice1_decimal_budget",
    "message": "预算 100.5 元以内的防晒",
    "terminal_event": "end",
    "winner_status": "SELECTED",
    "product_ids": [55, 57, 54, 51]
  },
  {
    "case_id": "slice1_zero_budget",
    "message": "0 元以内的防晒",
    "terminal_event": "end",
    "winner_status": null,
    "product_ids": []
  },
  {
    "case_id": "slice1_negative_budget",
    "message": "-100 内的防晒",
    "terminal_event": "end",
    "winner_status": null,
    "product_ids": []
  },
  {
    "case_id": "slice1_exclusion_unknown",
    "message": "500 内不要酒精的防晒",
    "terminal_event": "end",
    "winner_status": "NO_CANDIDATE",
    "product_ids": []
  }
]
```

The decimal case excludes product `51` only if its exact price exceeds `100.5`; with current Canonical value `99.9`, the expected IDs shown above are correct.

- [ ] **Step 3: Write the table-driven gate test**

Create `tests/guide/application/test_slice1_backend_gate.py`:

```python
import json
from pathlib import Path

import pytest

from app.guide.application.contracts import UserTurn

CASES = json.loads(
    Path("tests/fixtures/guide/slice1_backend_cases.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["case_id"])
def test_slice1_backend_case(case, orchestrator) -> None:
    events = list(orchestrator.stream(UserTurn(
        session_id=f"gate-{case['case_id']}",
        message=case["message"],
        image_bundle_id=None,
        conversation_version=0,
    )))
    assert events[-1].event == case["terminal_event"]
    products = next(
        (event for event in events if event.event == "products"),
        None,
    )
    actual_ids = (
        [card.product_id for card in products.data.cards]
        if products is not None
        else []
    )
    assert actual_ids == case["product_ids"]
    decision = next(
        (
            event
            for event in events
            if event.event == "decision_process"
        ),
        None,
    )
    actual_status = (
        decision.data.winner_status if decision is not None else None
    )
    assert actual_status == case["winner_status"]
```

- [ ] **Step 4: Create the CSV evidence runner**

Create `tools/guide_gates/__init__.py` as an empty package marker.

Create `tools/guide_gates/slice1_backend.py`:

```python
from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

from app.guide.adapters.catalog import CanonicalProductReader
from app.guide.application.contracts import UserTurn
from app.guide.application.text_recommendation_flow import (
    build_text_recommendation_orchestrator,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CANONICAL = REPO_ROOT / "data" / "canonical"
CASES_PATH = (
    REPO_ROOT / "tests" / "fixtures" / "guide"
    / "slice1_backend_cases.json"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    reader = CanonicalProductReader.from_files(
        manifest_path=CANONICAL / "core_products_v1_manifest.json",
        products_path=CANONICAL / "core_products_v1.jsonl",
    )
    orchestrator = build_text_recommendation_orchestrator(reader)
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    rows: list[dict[str, str]] = []

    for case in cases:
        started = time.perf_counter()
        events = list(orchestrator.stream(UserTurn(
            session_id=f"gate-{case['case_id']}",
            message=case["message"],
            image_bundle_id=None,
            conversation_version=0,
        )))
        elapsed_ms = (time.perf_counter() - started) * 1000
        products = next(
            (event for event in events if event.event == "products"),
            None,
        )
        decision = next(
            (
                event
                for event in events
                if event.event == "decision_process"
            ),
            None,
        )
        rows.append({
            "case_id": case["case_id"],
            "input_text": case["message"],
            "image_ids": "[]",
            "final_product_ids": json.dumps(
                [
                    card.product_id
                    for card in products.data.cards
                ]
                if products is not None
                else []
            ),
            "decision_status": (
                decision.data.winner_status
                if decision is not None
                else ""
            ),
            "failure_reason": (
                events[-1].data.code
                if events[-1].event == "error"
                else ""
            ),
            "latency_ms": f"{elapsed_ms:.3f}",
            "model_version": "not_used",
            "index_version": "not_used",
        })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Verify cwd independence**

Run from `/tmp`:

```bash
cd /tmp
PYTHONPATH=/Users/bytedance/Desktop/xiaoro-fresh \
python3 -m tools.guide_gates.slice1_backend \
  --output /tmp/xiaoro_slice1_backend_gate.csv
```

Expected: exit 0 and a CSV with five rows. No relative Canonical path failure.

- [ ] **Step 6: Repair design and handoff facts**

In `docs/superpowers/specs/2026-08-06-xiaoro-clean-growth-architecture-design.md`:

- Replace section 11.3's statement that `tools/evidence_audit/` is migrated and sealed.
- State that the mechanically migrated implementation and parity tests were deleted after audit.
- Record that only source manifest/SHA, fixtures, removal rationale and import prohibition remain.
- State that any future audit tooling must be newly designed from approved contracts and human review rules.

Append a dated correction to `docs/audits/slice0-foundation/morning_handoff.md`:

```markdown
## 2026-08-07 状态更正

- `tools/evidence_audit/` 及其 parity tests 已在逻辑审计后删除。
- 旧文中的 `244 passed` 是删除前的历史门禁，不代表当前树。
- 当前正式地基门禁使用 `pytest-guide.ini`，覆盖 `tests/guide` 与
  `tests/slice0`；实际数量以本次命令输出为准。
- 删除原因与保留资产见
  `docs/audits/slice0-foundation/evidence_audit_removal.md`。
```

Do not rewrite or erase the historical record above this correction.

- [ ] **Step 7: Run the complete release gate**

Create a fresh locked environment and run:

```bash
python3 -m venv /tmp/xiaoro-slice1-gate-venv
/tmp/xiaoro-slice1-gate-venv/bin/python -m pip install \
  pydantic==2.8.0 pytest==8.0.0
/tmp/xiaoro-slice1-gate-venv/bin/python \
  -m pytest -q -c pytest-guide.ini
python3 app/guide/check_boundaries.py app/guide
/tmp/xiaoro-slice1-gate-venv/bin/python \
  -m tools.guide_gates.slice1_backend \
  --output /tmp/xiaoro_slice1_backend_gate.csv
git diff --check
```

Expected:

- all tests PASS;
- boundary check has zero violations;
- CSV has five cases and expected product IDs/statuses;
- no whitespace errors.

- [ ] **Step 8: Confirm protected files and ranking SHA**

Run:

```bash
git diff --name-only bdb0443..HEAD
shasum -a 256 app/guide/decision/deterministic_ranking.py
```

Expected:

- no `chat.py`, `chat.html`, FastAPI route or legacy `app/services` file;
- ranking SHA is
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`.

- [ ] **Step 9: Commit the gate and documentation correction**

```bash
git add pytest-guide.ini tests/fixtures/guide tests/guide/application/test_slice1_backend_gate.py tools/guide_gates docs/superpowers/specs/2026-08-06-xiaoro-clean-growth-architecture-design.md docs/audits/slice0-foundation/morning_handoff.md
git commit -m "test(guide): gate the slice 1 backend contract"
```

---

## 4. Final Acceptance Checklist

- [ ] `UserTurn` rejects blank and oversized messages.
- [ ] Negative and zero budgets clarify; decimal budgets are exact.
- [ ] Chinese numeral budgets clarify instead of disappearing.
- [ ] Range, lower-bound and upper-bound budgets preserve direction.
- [ ] Multiple exclusions become independent typed constraints.
- [ ] Unknown constraint kinds cannot instantiate `TaskPlan`.
- [ ] Sunscreen taxonomy recalls all 12 current family members.
- [ ] Price unknown/conflict/bool is fail-closed.
- [ ] A2 keeps unknown skin last and excludes known mismatch.
- [ ] Ingredient exclusion unknown is fail-closed and explained.
- [ ] Business tie returns `TIED_BY_BUSINESS_EVIDENCE`.
- [ ] Evidence refs derive from actual typed constraints.
- [ ] Missing presentation fact records fail closed.
- [ ] Canonical value `"无"` is preserved and visibly flagged, never guessed.
- [ ] Core query returns exactly 11 budget-qualified IDs in frozen order.
- [ ] Core query has `INSUFFICIENT_FOR_WINNER`, not a false winner.
- [ ] SSE is an iterator and yields `start` before catalog work.
- [ ] `answer_contract` precedes `products`.
- [ ] `message.content` is a non-empty public fragment.
- [ ] Error is terminal and contains no internal exception details.
- [ ] Normal flow has exactly one terminal `end`.
- [ ] Canonical reader is built once and injected.
- [ ] The gate runs from `/tmp` without cwd dependency.
- [ ] Feedback reports `SKIPPED_SLICE_SCOPE`, never fake success.
- [ ] `deterministic_ranking.py` SHA remains locked.
- [ ] Boundary checker reports zero violations.
- [ ] No frontend/API/protected file changed.
- [ ] Design and handoff documents match the current tree.

## 5. Stop Condition

Slice 1 后端只有在 Task 1-8 全部完成、锁定环境门禁通过、CSV 证据生成且上述 checklist 全绿后，才可进入“接 FastAPI/前端”的独立计划。

在此之前不得开始 Slice 2 图片索引、不得修改前端事件消费者，也不得宣称“六层后端已完成上线准备”。
