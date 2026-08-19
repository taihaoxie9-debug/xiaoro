# 两步语义理解 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将八字段单次长 Prompt 拆成“路由语义 + 场景语义”，保留唯一 merger 和硬约束权威，并通过实用生产门禁。

**Architecture:** 第一步 `SemanticRouteProposal` 只决定 goal/topic/是否需要细化；第二步按场景返回严格的 detail proposal。两步结果投影回现有 `SemanticIntentProposal`，因此唯一 merger、TaskPlan 和下游不用建立第二条主链。

**Tech Stack:** Python 3.11、Pydantic v2、httpx、SiliconFlow OpenAI-compatible API、SQLite cache、pytest

---

## 文件边界

本计划 writer 独占：

- `app/guide/understanding/semantic_route_contracts.py`（新建）
- `app/guide/understanding/semantic_detail_contracts.py`（新建）
- `app/guide/understanding/two_stage_semantic.py`（新建）
- `app/guide/understanding/ports.py`
- `app/guide/adapters/llm/intent_route_prompt.py`（新建）
- `app/guide/adapters/llm/intent_detail_prompt.py`（新建）
- `app/guide/adapters/llm/siliconflow_two_stage_intent.py`（新建）
- `app/guide/adapters/llm/intent_cache.py`
- `tools/guide_gates/two_stage_intent_gate.py`（新建）
- `tools/guide_gates/run_real_two_stage_intent_ab.py`（新建）
- 对应 tests/fixtures

不要修改 `app/guide_runtime/composition.py`、`signal_merger.py`、公开 API 或任务文档。
Integration Writer 最后切 composition。

### Task 1: 定义第一步路由合同

**Files:**
- Create: `app/guide/understanding/semantic_route_contracts.py`
- Modify: `app/guide/understanding/ports.py`
- Create: `tests/guide/understanding/test_semantic_route_contracts.py`

- [ ] **Step 1: 写 strict route RED**

```python
def valid_route_payload() -> dict[str, object]:
    return {
        "goal": "recommendation",
        "topic": "sunscreen",
        "detail_stage": "recommendation",
        "confidence": 0.95,
        "clarification_hint": None,
    }


def test_route_contract_is_strict_and_forbids_business_facts() -> None:
    proposal = SemanticRouteProposal.model_validate(
        valid_route_payload(),
        strict=True,
    )
    assert proposal.goal is UnderstandingGoal.RECOMMENDATION
    for forbidden in (
        "product_id",
        "candidate_id",
        "price",
        "winner",
        "score",
        "sql",
        "profile",
    ):
        payload = {**valid_route_payload(), forbidden: "bad"}
        with pytest.raises(ValidationError):
            SemanticRouteProposal.model_validate(payload, strict=True)


def test_route_detail_stage_matches_goal() -> None:
    payload = valid_route_payload()
    payload["detail_stage"] = "assessment"
    with pytest.raises(ValidationError, match="detail stage"):
        SemanticRouteProposal.model_validate(payload, strict=True)
```

- [ ] **Step 2: 运行 RED**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/understanding/test_semantic_route_contracts.py
```

- [ ] **Step 3: 实现合同**

```python
from enum import Enum
from typing import ClassVar, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.guide.understanding.contracts import (
    TopicCode,
    UnderstandingGoal,
)
from app.guide.understanding.semantic_contracts import ClarificationCode


class SemanticDetailStage(str, Enum):
    RECOMMENDATION = "recommendation"
    ASSESSMENT = "assessment"
    COMPARISON = "comparison"
    FOLLOWUP = "followup"
    KNOWLEDGE = "knowledge"
    IMAGE = "image"
    NONE = "none"


_DETAIL_STAGE_BY_GOAL = {
    UnderstandingGoal.RECOMMENDATION: SemanticDetailStage.RECOMMENDATION,
    UnderstandingGoal.SUITABILITY: SemanticDetailStage.ASSESSMENT,
    UnderstandingGoal.ASSESSMENT: SemanticDetailStage.ASSESSMENT,
    UnderstandingGoal.COMPARISON: SemanticDetailStage.COMPARISON,
    UnderstandingGoal.FOLLOWUP: SemanticDetailStage.FOLLOWUP,
    UnderstandingGoal.KNOWLEDGE: SemanticDetailStage.KNOWLEDGE,
    UnderstandingGoal.IMAGE_SIMILARITY: SemanticDetailStage.IMAGE,
    UnderstandingGoal.CLARIFICATION: SemanticDetailStage.NONE,
}


class SemanticRouteProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    schema_version: ClassVar[str] = "guide-semantic-route-v1"

    goal: UnderstandingGoal
    topic: TopicCode | None
    detail_stage: SemanticDetailStage
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    clarification_hint: ClarificationCode | None = None

    @model_validator(mode="after")
    def validate_stage(self) -> Self:
        if self.detail_stage is not _DETAIL_STAGE_BY_GOAL[self.goal]:
            raise ValueError("detail stage must match route goal")
        if (
            self.goal is UnderstandingGoal.CLARIFICATION
            and self.clarification_hint is None
        ):
            raise ValueError(
                "clarification route requires clarification hint"
            )
        return self
```

在 `ports.py` 增加：

```python
class SemanticRoutePort(Protocol):
    def route(
        self,
        message: str,
        context: SemanticContext,
    ) -> SemanticRouteProposal: ...
```

- [ ] **Step 4: GREEN 和 Commit**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/understanding/test_semantic_route_contracts.py
git add \
  app/guide/understanding/semantic_route_contracts.py \
  app/guide/understanding/ports.py \
  tests/guide/understanding/test_semantic_route_contracts.py
git commit -m "feat(intent): define strict semantic route contract"
```

### Task 2: 定义场景专属 detail 合同

**Files:**
- Create: `app/guide/understanding/semantic_detail_contracts.py`
- Modify: `app/guide/understanding/ports.py`
- Create: `tests/guide/understanding/test_semantic_detail_contracts.py`

- [ ] **Step 1: 写场景字段隔离 RED**

```python
def test_assessment_accepts_observations_but_not_actions() -> None:
    proposal = AssessmentDetails(
        concerns=[ConcernCode.SKIN],
        observations=[
            SemanticObservation(
                code=ObservationCode.TIGHTNESS,
                present=True,
                qualifier=ObservationQualifier.POST_CLEANSE,
            )
        ],
    )
    assert proposal.observations
    with pytest.raises(ValidationError):
        AssessmentDetails.model_validate(
            {
                **proposal.model_dump(mode="python"),
                "acts": [],
            },
            strict=True,
        )


def test_followup_accepts_references_and_acts_only() -> None:
    proposal = FollowupDetails(
        references=[
            SemanticReference(kind="current_item", ordinal=None)
        ],
        acts=[],
    )
    assert proposal.references[0].kind == "current_item"
```

- [ ] **Step 2: 实现六个严格模型**

```python
class _DetailModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class RecommendationDetails(_DetailModel):
    schema_version: ClassVar[str] = "guide-detail-recommendation-v1"
    concerns: tuple[ConcernCode, ...] = Field(default_factory=tuple)
    observations: tuple[SemanticObservation, ...] = Field(
        default_factory=tuple
    )
    acts: tuple[SemanticAct, ...] = Field(default_factory=tuple)


class AssessmentDetails(_DetailModel):
    schema_version: ClassVar[str] = "guide-detail-assessment-v1"
    concerns: tuple[ConcernCode, ...] = Field(default_factory=tuple)
    observations: tuple[SemanticObservation, ...] = Field(
        default_factory=tuple
    )


class ComparisonDetails(_DetailModel):
    schema_version: ClassVar[str] = "guide-detail-comparison-v1"
    references: tuple[SemanticReference, ...] = Field(min_length=1)


class FollowupDetails(_DetailModel):
    schema_version: ClassVar[str] = "guide-detail-followup-v1"
    references: tuple[SemanticReference, ...] = Field(min_length=1)
    acts: tuple[SemanticAct, ...] = Field(default_factory=tuple)


class KnowledgeDetails(_DetailModel):
    schema_version: ClassVar[str] = "guide-detail-knowledge-v1"
    concerns: tuple[ConcernCode, ...] = Field(default_factory=tuple)


class ImageDetails(_DetailModel):
    schema_version: ClassVar[str] = "guide-detail-image-v1"
    references: tuple[SemanticReference, ...] = Field(min_length=1)
    observations: tuple[SemanticObservation, ...] = Field(
        default_factory=tuple
    )
```

增加闭合类型：

```python
SemanticDetailsProposal = (
    RecommendationDetails
    | AssessmentDetails
    | ComparisonDetails
    | FollowupDetails
    | KnowledgeDetails
    | ImageDetails
)
```

每个模型 validator 必须去重；reference 上限 4、act 上限 8、concern/observation 上限
沿用 v3。

在 ports.py：

```python
class SemanticDetailsPort(Protocol):
    def extract(
        self,
        message: str,
        context: SemanticContext,
        route: SemanticRouteProposal,
    ) -> SemanticDetailsProposal: ...
```

- [ ] **Step 3: 运行 GREEN**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/understanding/test_semantic_detail_contracts.py
```

- [ ] **Step 4: Commit**

```bash
git add \
  app/guide/understanding/semantic_detail_contracts.py \
  app/guide/understanding/ports.py \
  tests/guide/understanding/test_semantic_detail_contracts.py
git commit -m "feat(intent): isolate scenario semantic contracts"
```

### Task 3: 编写短路由 Prompt 和场景 Prompt

**Files:**
- Create: `app/guide/adapters/llm/intent_route_prompt.py`
- Create: `app/guide/adapters/llm/intent_detail_prompt.py`
- Create: `tests/guide/adapters/test_intent_route_prompt.py`
- Create: `tests/guide/adapters/test_intent_detail_prompt.py`

- [ ] **Step 1: 写 Prompt 体积和权限 RED**

```python
def test_route_prompt_is_short_and_has_no_detail_enums() -> None:
    messages = build_route_messages("第二款呢", context())
    system = messages[0]["content"]
    assert len(system.encode("utf-8")) < 4500
    assert "observations" not in system
    assert "acts" not in system
    assert "product_id" in system
    assert "never emit" in system


@pytest.mark.parametrize(
    ("stage", "required", "forbidden"),
    [
        ("assessment", "observations", "acts"),
        ("comparison", "references", "observations"),
        ("followup", "acts", "concerns"),
        ("knowledge", "concerns", "references"),
    ],
)
def test_detail_prompt_exposes_only_stage_fields(
    stage: str,
    required: str,
    forbidden: str,
) -> None:
    system = build_detail_messages(
        "测试",
        context(),
        route(stage),
    )[0]["content"]
    assert required in system
    assert forbidden not in system
```

- [ ] **Step 2: 实现 route prompt v1**

固定版本：

```python
ROUTE_PROMPT_VERSION = "guide-semantic-route-prompt-v1"
```

System prompt 只包含：

```text
Return JSON with exactly:
goal, topic, detail_stage, confidence, clarification_hint.

Goal priority:
image_similarity > comparison > suitability > knowledge >
assessment > followup > recommendation > clarification.

Typed context controls whether current item/image/batch exists.
Do not extract budget, numeric bounds, polarity, ingredient exclusions,
ordinals, product IDs, facts, scores, winners, SQL, or profile writes.
```

不得复制旧七组矩阵。

- [ ] **Step 3: 实现 stage prompt v1**

`build_detail_messages()` 根据 `route.detail_stage` 从闭合字典选择 prompt 和 schema
skeleton：

```python
_PROMPT_BY_STAGE = {
    SemanticDetailStage.RECOMMENDATION: _RECOMMENDATION_PROMPT,
    SemanticDetailStage.ASSESSMENT: _ASSESSMENT_PROMPT,
    SemanticDetailStage.COMPARISON: _COMPARISON_PROMPT,
    SemanticDetailStage.FOLLOWUP: _FOLLOWUP_PROMPT,
    SemanticDetailStage.KNOWLEDGE: _KNOWLEDGE_PROMPT,
    SemanticDetailStage.IMAGE: _IMAGE_PROMPT,
}
```

每个 prompt 必须：

- 只列本 stage 字段和枚举；
- 重复禁止 product/candidate ID、价格、事实、score/winner/SQL/profile；
- context 只提供 typed 摘要；
- 不回答用户；
- JSON only；
- UTF-8 字节长度小于 6500。

- [ ] **Step 4: GREEN 和 Commit**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/adapters/test_intent_route_prompt.py \
  tests/guide/adapters/test_intent_detail_prompt.py
git add \
  app/guide/adapters/llm/intent_route_prompt.py \
  app/guide/adapters/llm/intent_detail_prompt.py \
  tests/guide/adapters/test_intent_route_prompt.py \
  tests/guide/adapters/test_intent_detail_prompt.py
git commit -m "feat(intent): add staged semantic prompts"
```

### Task 4: 实现共享调用预算的两步 SiliconFlow adapter

**Files:**
- Create: `app/guide/adapters/llm/siliconflow_two_stage_intent.py`
- Modify: `app/guide/adapters/llm/contracts.py`
- Create: `tests/guide/adapters/test_siliconflow_two_stage_intent.py`

- [ ] **Step 1: 写最多三请求 RED**

```python
def test_two_stages_share_one_format_repair_budget() -> None:
    transport = SequenceTransport(
        [
            invalid_route_response(),
            valid_route_response(),
            invalid_detail_response(),
        ]
    )
    adapter = build_adapter(transport=transport)
    with pytest.raises(SemanticProviderFailure):
        adapter.propose("推荐防晒", context())
    assert transport.request_count == 3


def test_route_clarification_skips_detail_call() -> None:
    transport = SequenceTransport([clarification_route_response()])
    proposal = build_adapter(transport=transport).propose(
        "看看",
        context(),
    )
    assert proposal.goal is UnderstandingGoal.CLARIFICATION
    assert transport.request_count == 1
```

- [ ] **Step 2: 增加 staged usage 合同**

```python
class SemanticStageUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    stage: Literal["route", "detail"]
    usage: SemanticTokenUsage | None
    repair_used: bool


class TwoStageSemanticCallResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    proposal: SemanticIntentProposal
    stage_usage: tuple[SemanticStageUsage, ...]
```

- [ ] **Step 3: 实现 adapter**

公开接口保持兼容：

```python
class SiliconFlowTwoStageIntentAdapter:
    provider = "siliconflow"
    prompt_version = (
        f"{ROUTE_PROMPT_VERSION}+{DETAIL_PROMPT_VERSION}"
    )

    def propose(
        self,
        message: str,
        context: SemanticContext,
    ) -> SemanticIntentProposal:
        return self.propose_with_result(message, context).proposal
```

调用流程：

```python
repair_available = self._format_repair_attempts == 1
route, route_usage, route_repaired = self._request_route(
    message,
    context,
    allow_repair=repair_available,
)
repair_available = repair_available and not route_repaired
if route.detail_stage is SemanticDetailStage.NONE:
    return compose_semantic_proposal(route, None)
details, detail_usage, detail_repaired = self._request_details(
    message,
    context,
    route,
    allow_repair=repair_available,
)
return compose_semantic_proposal(route, details)
```

实现必须复用旧 adapter 的：

- https-only base URL；
- `trust_env=False`；
- Authorization 不进入 repr/log；
- daily call/budget limiter；
- typed 401/429/5xx/timeout/empty/invalid/forbidden failure；
- `temperature=0`、`enable_thinking=false`；
- no transport retry。

不要让两个 stage 各建一个 httpx.Client 或各建一个 daily limiter。

- [ ] **Step 4: 实现投影回 v3 proposal**

在 `two_stage_semantic.py`：

```python
def compose_semantic_proposal(
    route: SemanticRouteProposal,
    details: SemanticDetailsProposal | None,
) -> SemanticIntentProposal:
    if route.detail_stage is SemanticDetailStage.NONE:
        return SemanticIntentProposal(
            goal=route.goal,
            topic=route.topic,
            concerns=(),
            observations=(),
            references=(),
            acts=(),
            confidence=route.confidence,
            clarification_hint=route.clarification_hint,
        )
    if details is None:
        raise ValueError("routed semantic proposal requires details")
    return SemanticIntentProposal(
        goal=route.goal,
        topic=route.topic,
        concerns=getattr(details, "concerns", ()),
        observations=getattr(details, "observations", ()),
        references=getattr(details, "references", ()),
        acts=getattr(details, "acts", ()),
        confidence=route.confidence,
        clarification_hint=route.clarification_hint,
    )
```

投影函数必须检查 details 类型与 route stage 精确匹配。

- [ ] **Step 5: GREEN 和 Commit**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/adapters/test_siliconflow_two_stage_intent.py \
  tests/guide/adapters/test_siliconflow_intent.py
git add \
  app/guide/adapters/llm/contracts.py \
  app/guide/adapters/llm/siliconflow_two_stage_intent.py \
  app/guide/understanding/two_stage_semantic.py \
  tests/guide/adapters/test_siliconflow_two_stage_intent.py
git commit -m "feat(intent): add bounded two-stage SiliconFlow adapter"
```

### Task 5: 泛化分阶段严格缓存

**Files:**
- Modify: `app/guide/adapters/llm/contracts.py:40-60`
- Modify: `app/guide/adapters/llm/intent_cache.py:52-99`
- Modify: `app/guide/understanding/two_stage_semantic.py`
- Modify: `tests/guide/adapters/test_intent_cache.py`

- [ ] **Step 1: 写 stage identity RED**

```python
def test_route_and_detail_cache_keys_never_collide() -> None:
    route_key = build_intent_cache_key(
        stage="route",
        result_schema=SemanticRouteProposal,
        **common,
    )
    detail_key = build_intent_cache_key(
        stage="detail:recommendation",
        result_schema=RecommendationDetails,
        **common,
    )
    assert route_key.fingerprint() != detail_key.fingerprint()
```

- [ ] **Step 2: 泛化 key**

`LLMCacheKey` 增加：

```python
stage: StrictString
```

`build_intent_cache_key()` 改为：

```python
def build_intent_cache_key(
    *,
    stage: str,
    result_schema: type[BaseModel],
    provider: str,
    model: str,
    prompt_version: str,
    message: str,
    context: SemanticContext,
    temperature: float,
    max_tokens: int,
    enable_thinking: bool = False,
) -> LLMCacheKey:
    schema_version = getattr(result_schema, "schema_version", None)
    if not isinstance(schema_version, str) or not schema_version:
        raise TypeError("result schema requires schema_version")
    return LLMCacheKey(
        stage=stage,
        provider=provider,
        model=model,
        prompt_version=prompt_version,
        schema_version=schema_version,
        context_sha256=_context_sha256(
            message=message,
            context=context,
        ),
        generation_parameters=LLMGenerationParameters(
            temperature=temperature,
            max_tokens=max_tokens,
            enable_thinking=enable_thinking,
        ),
    )
```

现有单阶段调用使用 `stage="legacy-intent-v3"` 保持显式身份，不做隐式默认。

- [ ] **Step 3: 两阶段分别缓存**

在 adapter 外层 `TwoStageCachedSemanticPort`：

- route cache hit 后仍严格校验 `SemanticRouteProposal`；
- detail cache key 额外把 canonical route JSON hash 放入 typed context hash；
- 只缓存 strict success；
- route failure/detail failure 都不缓存；
- 原始消息仅以 SHA 进入 key，不落 SQLite。

- [ ] **Step 4: GREEN 和 Commit**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/adapters/test_intent_cache.py \
  tests/guide/adapters/test_siliconflow_two_stage_intent.py
git add \
  app/guide/adapters/llm/contracts.py \
  app/guide/adapters/llm/intent_cache.py \
  app/guide/understanding/two_stage_semantic.py \
  tests/guide/adapters/test_intent_cache.py \
  tests/guide/adapters/test_siliconflow_two_stage_intent.py
git commit -m "feat(intent): cache validated semantic stages separately"
```

### Task 6: 保持 exact 并行和唯一 merger

**Files:**
- Modify: `app/guide/understanding/parallel_understanding.py`
- Create: `tests/guide/understanding/test_two_stage_parallel_understanding.py`
- Existing verifier: `tests/guide/intent/test_signal_merger.py`

- [ ] **Step 1: 写并行与失败 RED**

```python
def test_exact_starts_while_route_is_in_flight() -> None:
    semantic = BlockingTwoStagePort()
    understanding = ParallelUnderstanding(semantic=semantic)
    result = understanding.understand(
        "预算300以内推荐防晒",
        context=context(),
    )
    assert semantic.exact_started_before_release is True
    assert budget_maximum(result) == Decimal("300")


def test_detail_failure_never_enters_task_plan_as_partial_semantics() -> None:
    result = ParallelUnderstanding(
        semantic=RouteSuccessDetailFailurePort()
    ).understand("它适合我吗", context=context())
    task = plan_task(result)
    assert task.mode == "clarify"
    assert not result.semantic_proposals
```

- [ ] **Step 2: 保持 port 兼容**

`ParallelUnderstanding` 仍只依赖 `SemanticIntentPort.propose()`。两阶段细节封装在新
adapter/port 内；不要让 `ParallelUnderstanding` 自己知道 route/detail。

仅更新：

- 类型注释接受两阶段 port；
- cache 从 `ParallelUnderstanding` 移到 staged port 后，删除这里的旧 cache 参数和
  `_cache_get/_cache_put`；
- semantic future 与 exact parser 的启动顺序保持不变；
- 所有 semantic failure 仍投影为 `semantic=None`；
- 最终仍只调用 `merge_intent_signals()` 一次。

- [ ] **Step 3: 运行 merger 回归**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/understanding/test_parallel_understanding.py \
  tests/guide/understanding/test_two_stage_parallel_understanding.py \
  tests/guide/intent/test_signal_merger.py \
  tests/guide/intent/test_signal_merger_context_lane.py
```

Expected: PASS；模型覆盖硬约束仍为 0。

- [ ] **Step 4: Commit**

```bash
git add \
  app/guide/understanding/parallel_understanding.py \
  tests/guide/understanding/test_two_stage_parallel_understanding.py
git commit -m "refactor(intent): keep staged semantics behind one port"
```

### Task 7: 建立 32 条 smoke gate 和分层 128 条门禁

**Files:**
- Create: `tests/fixtures/guide/intent/two_stage_smoke_v1.jsonl`
- Create: `tests/fixtures/guide/intent/two_stage_smoke_v1_manifest.json`
- Create: `tools/guide_gates/two_stage_intent_gate.py`
- Create: `tests/guide/tools/test_two_stage_intent_gate.py`

- [ ] **Step 1: 冻结 32 条 smoke 子集**

从 v2 的 128 条按原 case ID 选：

- 4 recommendation；
- 4 comparison；
- 4 suitability/assessment；
- 4 followup/reference；
- 4 knowledge/image；
- 4 revision/budget；
- 4 prompt injection/out of scope；
- 4 low information/provider failure。

不得修改原 message/context/expected。manifest 包含 case ID 顺序和文件 SHA。

- [ ] **Step 2: 写分层 gate RED**

```python
def test_optional_detail_difference_does_not_fail_route_gate() -> None:
    row = evaluated_row(
        goal_correct=True,
        topic_correct=True,
        detail_key_correct=False,
        safe_clarification_mismatch_count=0,
        unsafe_task_plan_mismatch_count=0,
        wrong_product_selection_count=0,
    )
    summary = summarize([row] * 120)
    assert summary.route_critical_rate == 1.0
    assert summary.hard_gates_passed is True


def test_wrong_task_plan_is_always_hard_failure() -> None:
    rows = [perfect_row() for _ in range(120)]
    rows[0] = rows[0].model_copy(
        update={"unsafe_task_plan_mismatch_count": 1}
    )
    assert summarize(rows).passed is False
```

- [ ] **Step 3: 实现门禁**

每行输出：

```python
class TwoStageGateRow(_StrictModel):
    case_id: str
    model: str
    route_schema_valid: bool
    route_critical_match: bool
    detail_schema_valid: bool | None
    detail_key_match: bool | None
    fail_closed_clarification: bool
    safe_clarification_mismatch_count: int
    unsafe_task_plan_mismatch_count: int
    hard_constraint_override_count: int
    forbidden_field_acceptance_count: int
    invalid_output_task_plan_invocation_count: int
    wrong_product_selection_count: int
    legacy_fallback_count: int
```

模型通过条件：

```python
passed = (
    case_count >= 120
    and route_critical_rate >= 0.95
    and detail_key_rate >= 0.90
    and all_failed_cases_fail_closed
    and hard_constraint_override_count == 0
    and forbidden_field_acceptance_count == 0
    and invalid_output_task_plan_invocation_count == 0
    and unsafe_task_plan_mismatch_count == 0
    and wrong_product_selection_count == 0
    and legacy_fallback_count == 0
)
```

`route_critical_match` 只包含 goal/topic/是否 clarify；reference/acts 属于对应 detail
stage 的关键字段。concern/observation 非关键差异单独计数。

TaskPlan mismatch 必须拆成两类：

- expected 是可执行 plan，但实际安全地返回 clarify：
  `safe_clarification_mismatch_count += 1`，进入质量分母但不是硬失败；
- 实际执行了错误 mode、错误约束、错误 reference 或错误选品：
  `unsafe_task_plan_mismatch_count += 1`，硬失败。

不得简单删除原 mismatch 观测，也不得把错误 recommend 标成 safe clarification。

- [ ] **Step 4: smoke stop rule**

32 条 smoke：

- route-critical < 85%：立即 NO-GO，不跑 128；
- 任一硬门非零：立即 NO-GO；
- 达标后才允许 128 离线/真实 A/B。

- [ ] **Step 5: GREEN 和 Commit**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/tools/test_two_stage_intent_gate.py
git add \
  tests/fixtures/guide/intent/two_stage_smoke_v1.jsonl \
  tests/fixtures/guide/intent/two_stage_smoke_v1_manifest.json \
  tools/guide_gates/two_stage_intent_gate.py \
  tests/guide/tools/test_two_stage_intent_gate.py
git commit -m "test(intent): add practical two-stage production gate"
```

### Task 8: 真实 A/B 入口和 provider 早停

**Files:**
- Create: `tools/guide_gates/run_real_two_stage_intent_ab.py`
- Create: `tests/guide/tools/test_run_real_two_stage_intent_ab.py`
- Modify after run: `docs/audits/guide-closure/model_selection.md`

- [ ] **Step 1: 写 canonical 和早停 RED**

```python
def test_noncanonical_cases_fail_before_config_or_network() -> None:
    assert main(args_for(modified_cases)) == 2
    assert config_calls == []
    assert adapter_calls == []


def test_provider_failure_rate_stops_after_twenty_rows() -> None:
    adapter = AlwaysUnavailableAdapter()
    report = run_real_gate(adapter=adapter, cases=cases)
    assert report.executed_case_count == 20
    assert report.stop_reason == "provider_failure_rate"
```

- [ ] **Step 2: 实现真实入口**

固定：

- v2 canonical 128 case 文件 SHA；
- 两个 frozen model；
- `temperature=0`；
- `enable_thinking=false`；
- stage max tokens 各 128；
- timeout 12 秒；
- 共享 repair 1；
- 不 transport retry。

早停：

```python
if attempted == 20 and unavailable_or_timeout / attempted > 0.10:
    stop_reason = "provider_failure_rate"
    break
```

密钥只读环境变量，不进入 argv、日志、报告、cache key 或 Git。

- [ ] **Step 3: 先跑 32 条 smoke**

使用受监管 PTY，45 分钟硬超时不是 smoke 的目标；smoke 应在 15 分钟内完成。每 30 秒
心跳。若 10 分钟无新行，TERM/KILL 并审计进程。

Expected:

- route-critical >= 85%；
- 所有硬门为 0；
- 否则立即停下讨论，不运行 128。

- [ ] **Step 4: 再跑 128 A/B**

只有 Step 3 通过时执行。输出：

- normalized results；
- stage usage/latency；
- route/detail rates；
- hard gates；
- provider stop reason；
- evidence SHA。

选择规则：

- 两者通过：选 V4-Flash；
- 仅一个通过：选通过者；
- 都不通过：NO-GO，但不回退旧链；Guide 继续 fail-closed clarification。

- [ ] **Step 5: GREEN 和 Commit**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/tools/test_run_real_two_stage_intent_ab.py \
  tests/guide/tools/test_two_stage_intent_gate.py
git add \
  tools/guide_gates/run_real_two_stage_intent_ab.py \
  tests/guide/tools/test_run_real_two_stage_intent_ab.py \
  docs/audits/guide-closure/model_selection.md
git commit -m "docs(intent): record two-stage model selection"
```

### Task 9: Track C focused 验收

- [ ] **Step 1: 运行 focused**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/understanding/test_semantic_route_contracts.py \
  tests/guide/understanding/test_semantic_detail_contracts.py \
  tests/guide/understanding/test_two_stage_parallel_understanding.py \
  tests/guide/understanding/test_parallel_understanding.py \
  tests/guide/adapters/test_intent_route_prompt.py \
  tests/guide/adapters/test_intent_detail_prompt.py \
  tests/guide/adapters/test_siliconflow_two_stage_intent.py \
  tests/guide/adapters/test_intent_cache.py \
  tests/guide/intent/test_signal_merger.py \
  tests/guide/intent/test_signal_merger_context_lane.py \
  tests/guide/tools/test_two_stage_intent_gate.py \
  tests/guide/tools/test_run_real_two_stage_intent_ab.py
```

- [ ] **Step 2: 边界检查**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python \
  -m app.guide.check_boundaries app/guide
git diff --check
rg -n 'product_id|candidate_id|winner|score|SQL|profile' \
  app/guide/adapters/llm/intent_route_prompt.py \
  app/guide/adapters/llm/intent_detail_prompt.py
```

Expected: boundary 0 violations；Prompt 中这些词只出现在明确禁止句中。

- [ ] **Step 3: 固定 checkpoint**

```text
已完成：两步语义合同、短 Prompt、共享调用预算、分层门禁
当前卡点：smoke/真实 A/B 的精确失败簇
剩余工作：Integration Writer 切 composition
预计完成：2026-08-15
```

同一失败簇两次修复仍失败时必须停止讨论；禁止第三次给 Prompt 追加单句规则。
