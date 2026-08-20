# Phase 2 Guide Night Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not start execution until the user explicitly approves this document.

**Goal:** 今晚修掉正常导购请求被过度澄清的共性问题，建立自然语言数字和商品名称的安全处理链，复验当前 HEAD 的 Phase 2 基础能力，并把 103 个商品推进到分品类字段完整性可验收、缺关键数据即阻断的状态。

**Architecture:** 保持“模型提名语义，代码验证硬约束”的单一链路。DeepSeek 只负责 goal/topic/reference/act、受限数字候选和原文商品提及，代码负责数值合法性、商品目录绑定和最终 `TaskPlan` 权威。数据继续使用六个品类画像和字段 registry，不做统一字段抽取；103 个商品逐品类生成适用字段矩阵，关键字段没有真实来源时阻断对应能力，不把 pending/quarantine/unknown 当成生产事实。

**Tech Stack:** Python 3.11、Pydantic v2、DeepSeek V4-Pro、FastAPI、SQLite CAS、pytest、Playwright、现有 Guide data tooling。

---

## Discussion Gate

本文档只冻结今晚执行内容。用户确认前：

- 不改业务代码。
- 不运行 DeepSeek。
- 不启动浏览器矩阵。
- 不生成 verifier 决定。
- 不执行 promotion。

用户确认后只允许在以下权威仓库执行：

```text
/Users/bytedance/Desktop/xiaoro-fresh
branch=rebuild
planning_head=5fdf2e3
```

禁止进入、读取代码、运行解释器或写入：

```text
/Users/bytedance/Desktop/xiaoro-shopping-master
```

旧仓库即使还保留，也只可能在后续前端视觉收口时由用户明确授权后作为只读截图参考。今晚完全不使用。

## Plain-Language Diagnosis

现在“动不动澄清”不是一个问题，而是三个问题叠在一起：

1. **模型已经听懂，Merger 仍然追问。**
   DeepSeek 可能已经给出 `goal=recommendation`、`topic=sunscreen`、`confidence=0.95`，但只要 proposal 里还带一个 `clarification_hint` 或 `topic_unclear` 观察，当前 `signal_merger.py` 就无条件增加 uncertainty。`task_planning.py` 看到任何 uncertainty 就直接澄清，所以用户感觉系统明明听懂了还在绕。

2. **当前文字 TaskPlan 只放行 recommendation。**
   `app/guide/intent/task_planning.py` 当前对 comparison、suitability、assessment、knowledge 和 followup 统一返回 `GOAL` 澄清。模型能识别这些目标，但代码没有把它们送到对应 Phase 2 能力，所以“帮我对比”“这个适不适合我”也会被误报成目标不清楚。

3. **中文或口语数字被正则主动挡住。**
   `app/guide/understanding/exact_parsing.py` 当前检测到“三百以内”后明确生成 `unsupported_budget_format`，文案是“请使用阿拉伯数字填写预算”。这不是模型不会，是代码设计成了只接受阿拉伯数字。

今晚不再给每句话加一条正则或 Prompt 补丁。修复必须落在这三个共性责任层。

## Language Boundary

用户不需要按模板说话。今晚把语言分成三档：

```text
直接表达:
  “三百以内推荐油皮防晒”

正常口语:
  “最近脸挺油的，又怕闷，三百左右有没有通勤防晒”

稍微绕一点:
  “我平时就上下班用，不想下午糊脸，也别太贵，油皮能用的防晒看看”
```

这三档都必须继续执行，不得因为没有标准关键词就追问。

只有以下情况允许澄清：

```text
真正缺对象:
  “帮我对比一下”但当前会话没有商品，也没说商品名

硬条件互相矛盾:
  “预算最高 200，但最低也要 500”

模糊数字不能安全落值:
  “几百上下”“百来块”

指代无法唯一绑定:
  “这个适合我吗”但当前有多款且没有焦点

超长嵌套否定、明显对抗或注入:
  无法形成唯一合法 TaskPlan
```

“稍微绕一点”不等于“巨绕”。正常导购语料和中等口语改写必须进入冻结回归；极端表达允许 fail-closed，后续上线维护。

## Current Facts

### Repository

```text
branch=rebuild
HEAD=5fdf2e3
untracked=tools/guide_gates/run_official_deepseek_smoke.py
long_running_processes=0
```

未跟踪 smoke 入口必须先通过现有测试并单独提交，不能一直留在工作区，也不能在未提交状态下承担正式证据。

### Model

- 单阶段 DeepSeek V4-Pro 是当前生产候选。
- 32 条真实 smoke 在 `max_tokens=256` 后：
  - goal `90.6%`
  - topic `90.6%`
  - concern `93.8%`
  - observation `93.8%`
  - reference `93.8%`
  - acts `90.6%`
  - schema valid `96.9%`
  - 安全硬门 `0`
- 两阶段 Flash/Pro 明显更差，不再作为今晚默认修复方向。
- 128 条正式门禁尚未运行。

### Phase 2

历史上 profile、consultation、scenario、review、pitfall、feedback、1/2/4 image、OCR 和 browser 都通过过真实门禁，但之后发生了 Guide-only cutover 和新意图链替换。

因此今晚只允许说：

```text
historically_passed=true
current_head_verified=false
```

只有当前 HEAD 重跑通过后，单项状态才能改为 `current_head_verified=true`。

### Data

现有私有候选仍在：

```text
/private/tmp/xiaoro-guide-weekend/pilot-status.jsonl
/private/tmp/xiaoro-guide-weekend/category-pending.jsonl
/private/tmp/xiaoro-guide-weekend/category-quarantine.jsonl
/private/tmp/xiaoro-guide-weekend/pilot-review-matrix.md
```

冻结计数和 hash：

```text
pilot_status=201 rows
known=89
pending=7
quarantine=19
unknown=86
pilot_status_sha256=55ea31e3ca28dbfb1e0db8880d1d8306627746cff6230388249bb27e6c343f92

category_pending=9 rows
category_pending_sha256=a7d112716fa90e803f159d23a0a41f17ef7c83a776ca118644f782b25ec08217

category_quarantine=51 rows
category_quarantine_sha256=15b1f4759520955f32a5ead635420d313bdb8c3a28dc158a70e799ebf2af7a71

pilot_review_matrix_sha256=4a2f02efdc80acf830d05703fd8e548e82da18776c3f8a0684177d2ec8f6dc82
production_fact_count=0
promotion_invocations=0
approved_review_sources=6

verifier_a=0 PASS / 7 DEFER / 2 REJECT
verifier_b=5 PASS / 2 DEFER / 2 REJECT
common_pass=0
```

64,449 是批准来源根下的 inventory 文件数，不是 64,449 个已确认商品事实。不得把这两个概念混在一起。

三份 `locked review HTML` 是旧评论恢复门的固定证据，不代表 inventory 里只有三份 HTML。其他 HTML 是否能补 103 商品字段，尚未完成 item/SKU/source-class 绑定，这正是今晚数据任务。

本次只读抽样已经确认：

```text
inventory_html=336
top_level_saved_pages=118
top_level_jd=73
top_level_tmall=36
top_level_taobao=2
top_level_other=7

existing_parser_success=109/118
pages_with_structured_parameters=106
pages_with_reviews=33
parameter_occurrences=803
review_rows=64

exact_item_bound_products=98/103
exact_item_bound_pages=99
ambiguous_item_bindings=0
unbound_or_alternate_listing_pages=10
missing_exact_product_ids=36,53,70,106,144
```

六品类精确页面覆盖：

```text
skincare=48/51
suncare=11/12
base_makeup=19/19
color_makeup=6/6
cleanser=11/12
fragrance=3/3
```

当前真正的搬运瓶颈：

```text
unique_parameter_names=116
old_map_recognized_names=8
old_map_unrecognized_names=108
mapped_parameter_occurrences=61/803
silently_skipped_parameter_occurrences=742/803
```

结论：HTML 和跨平台解析能力大体已经存在；数据大面积空缺的主因，是后续候选层仍使用很小的通用参数映射，并且保存页 manifest 只放了 3 页。

当前 103 个商品的公共 Canonical 覆盖：

```text
product_identity=103/103 known
brand=103/103 known
category=103/103 known
price=103/103 known
efficacy=41/103 known
ingredients_present=37/103 known
safety=73/103 known
suitable_skin=37/103 known
texture=26/103 known
usage=15/103 known
verified_absences=0/103 known
water_resistance=0/103 known
category_sidecar_facts=0
```

结论：商品身份和价格齐，但二期推荐、适配和对比需要的字段明显不齐。15 商品/201 字段只是旧试点，不代表 103 商品数据层完成。

## Tonight Definition Of Done

今晚结束时必须交付以下六项结果：

1. 正常导购语言不再因为已解析槽位被二次澄清。
2. 明确中文数字能进入硬预算；口语或模糊数字能给出有意义的 BUDGET 确认，不要求用户改打阿拉伯数字。
3. 用户直接给出目录内任意 2-4 个商品名称时可以比较，不要求先推荐；目录外或重名商品只做 REFERENCE 澄清。
4. 直接表达、正常口语和稍微绕一点的导购表达都进入真实回归；推荐、直接对比、适配/避坑、画像/问诊、图片/OCR 和评论/风险在当前 HEAD 上都有真实 PASS/FAIL。
5. 103 个商品全部生成分品类适用字段矩阵和 `READY/BLOCKED` 状态；现有来源能补的字段生成候选，只有双重证据通过的字段才允许 promotion。
6. 留下一份明早可复核的 checkpoint，明确通过数、失败层、未做项、DeepSeek usage、证据 hash 和残留进程检查。

今晚不要求完成 128 条正式模型门禁、全量前端重做或部署。

## Night Schedule

今晚最长执行窗口按 8 小时控制。回答链路和数据链路在两个隔离 worktree 并行，主仓库只由 Integration Writer 合并：

```text
00:00-00:30  共同 guard、冻结 HEAD、创建两个隔离 worktree

Response Track:
00:30-02:00  resolved-slot 过度澄清
02:00-03:30  直接商品名 comparison/suitability
03:30-05:15  自然语言数字候选与 focused GREEN
05:15-05:45  最多 16 条 V4-Pro 真实 probe

Data Track:
00:30-01:15  复用 inventory，生成 118 页 source manifest
01:15-03:00  109 页解析、98 商品精确绑定、来源分类
03:00-05:00  六品类参数 registry，覆盖 116 种参数名
05:00-06:15  103 商品候选、coverage 和 READY/BLOCKED
06:15-06:45  双 verifier 与可批准交集

Integration:
05:45-06:45  逐提交独立 focused verification 后合并
06:45-07:30  Phase 2 HTTP/browser verticals
07:30-08:00  Guide full 条件门、边界检查、checkpoint、进程清理
```

时间预算不是让失败自动通过。某层达到两次失败止损后，立即记录该层并把剩余时间转给独立任务，不在同一路径继续消耗。

工作线隔离：

```text
Response writer:
  只拥有 understanding/intent/text application 及对应测试

Data writer:
  只拥有 tools/guide_data、category fact tooling 及对应测试

Integration writer:
  只在独立 verifier PASS 后合并
  独占 composition、共享规格、audit 和最终文档
```

任何 worktree 同时只能一个 writer。所有 worktree 必须从
`/Users/bytedance/Desktop/xiaoro-fresh` 的冻结 HEAD 创建，并在第一条命令验证
`git rev-parse --show-toplevel`；禁止从 IDE 当前打开文件推断仓库。

## File Responsibility Map

### Clarification Policy

- Modify: `app/guide/intent/signal_merger.py`
- Modify: `app/guide/intent/task_planning.py`
- Modify only if routing requires it: `app/guide/application/text_recommendation_flow.py`
- Test: `tests/guide/intent/test_signal_merger.py`
- Test: `tests/guide/intent/test_task_planning.py`
- Test: `tests/guide/application/test_text_recommendation_flow.py`
- Test: `tests/guide/runtime/test_runtime_http.py`

### Semantic Number Candidates

- Modify: `app/guide/understanding/semantic_contracts.py`
- Modify: `app/guide/adapters/llm/intent_prompt.py`
- Modify: `app/guide/understanding/parallel_understanding.py`
- Modify: `app/guide/intent/signal_merger.py`
- Modify: `app/guide/understanding/exact_parsing.py`
- Modify: `app/guide/understanding/budget_revision_parsing.py`
- Test: `tests/guide/understanding/test_semantic_intent_contracts.py`
- Test: `tests/guide/adapters/test_intent_prompt.py`
- Test: `tests/guide/understanding/test_parallel_understanding.py`
- Test: `tests/guide/understanding/test_text_understanding.py`
- Test: `tests/guide/understanding/test_budget_revision_parsing.py`
- Test: `tests/guide/intent/test_budget_revision_planning.py`

### Phase 2 Regression

- Verify: `tests/guide/application/test_consultation_chat_flow.py`
- Verify: `tests/guide/application/test_text_recommendation_flow.py`
- Verify: `tests/guide/application/test_image_recommendation_flow.py`
- Verify: `tests/guide/runtime/test_runtime_http.py`
- Verify: `tests/guide/runtime/test_feedback_runtime_http.py`
- Execute: `tools/guide_gates/runtime_browser_smoke.py`
- Execute: `tools/guide_gates/runtime_browser_adversarial.py`
- Execute: `tools/guide_gates/runtime_browser_consultation.py`
- Execute: `tools/guide_gates/combined_image_browser_gate.py`
- Execute: `tools/guide_gates/feedback_browser_vertical.py`
- Execute: `tools/guide_gates/category_profile_browser_gate.py`

### Category Data

- Read only: `/private/tmp/xiaoro-guide-weekend/pilot-status.jsonl`
- Read only: `/private/tmp/xiaoro-guide-weekend/category-pending.jsonl`
- Read only: `/private/tmp/xiaoro-guide-weekend/category-quarantine.jsonl`
- Read only: `/private/tmp/xiaoro-guide-weekend/pilot-review-matrix.md`
- Verify: `app/guide/retrieval/category_profiles.py`
- Verify: `app/guide/retrieval/category_fact_contracts.py`
- Modify: `tools/guide_data/build_seed_database_candidates.py`
- Modify: `tools/guide_data/extract_saved_page_evidence.py`
- Modify: `tools/guide_data/reconcile_pilot_candidates.py`
- Create: `tools/guide_data/report_catalog_field_coverage.py`
- Test: `tests/guide/data/test_build_seed_database_candidates.py`
- Test: `tests/guide/data/test_extract_saved_page_evidence.py`
- Test: `tests/guide/data/test_reconcile_pilot_candidates.py`
- Create: `tests/guide/data/test_report_catalog_field_coverage.py`
- Execute only after decisions: `tools/guide_data/promote_approved_category_facts.py`
- Modify only after valid promotion: `data/guide_category_facts/**`

### Evidence And Checkpoint

- Update from real evidence only:
  `.trae/specs/complete-guide-closure-continuously/progress.md`
- Update only when a checkbox is truly satisfied:
  `.trae/specs/complete-guide-closure-continuously/tasks.md`
- Update only when a checklist item is truly satisfied:
  `.trae/specs/complete-guide-closure-continuously/checklist.md`
- Append tonight result:
  `docs/audits/guide-closure/final_handoff.md`

## Execution Order

### Task 1: Freeze One End-To-End RED Matrix

**Purpose:** 先证明到底在哪一层被改成澄清，避免继续凭感觉改 Prompt。

- [ ] **Step 1: Add a table-driven current-HEAD regression**

在 `tests/guide/application/test_text_recommendation_flow.py` 和
`tests/guide/runtime/test_runtime_http.py` 增加固定输入，至少覆盖：

```text
有没有适合油皮的防晒推荐
预算三百以内，帮我看看适合油皮的防晒
不要含酒精的爽肤水
想要保湿的精华
那第二款呢
要便宜一点的
帮我对比当前这两款
敏感肌用当前这款防晒会不会闷痘
最近脸挺油的，又怕闷，三百左右有没有通勤防晒
我平时就上下班用，不想下午糊脸，也别太贵，油皮能用的防晒看看
```

每条记录必须输出：

```text
raw_semantic.goal
raw_semantic.topic
raw_semantic.clarification_hint
exact_constraints
exact_issues
merged.goal
merged.topic
merged.uncertainties
TaskPlan.mode
TaskPlan.clarification_code
terminal_event
product_ids
```

- [ ] **Step 2: Run the RED without DeepSeek**

使用冻结的 typed proposal fixture 重放已观察到的 V4-Pro 输出：

```bash
.venv/bin/python -m pytest -c pytest-guide.ini -q \
  tests/guide/intent/test_signal_merger.py \
  tests/guide/intent/test_task_planning.py \
  tests/guide/application/test_text_recommendation_flow.py
```

Expected before fix: normal recommendation, budget, comparison or suitability cases稳定复现错误澄清。

- [ ] **Step 3: Freeze the language difficulty set**

本地 typed proposal 回归至少包含：

```text
direct=12
colloquial=12
moderately_indirect=12
adversarial_or_contradictory=12
```

验收：

```text
direct + colloquial + moderately_indirect:
  core route accuracy >= 90%
  ordinary false clarification <= 10%

all tiers:
  hard constraint override=0
  forbidden field acceptance=0
  unsafe TaskPlan=0
  legacy fallback=0
```

极端/矛盾组允许 typed clarification，但必须问到真正缺失的 goal/topic/reference/budget，不能统一报 `GOAL`。

- [ ] **Step 4: Attribute each failure to one earliest layer**

只允许以下责任层：

```text
semantic_contract
exact_parser
signal_merger
task_planning
vertical_dispatch
retrieval
decision
presentation
```

禁止使用“模型效果不好”作为没有证据的兜底结论。

### Task 2: Fix Resolved-Slot Over-Clarification

**Purpose:** 已经有合法 goal/topic/reference 时，不允许一个过时 hint 把整条链重新改成澄清。

- [ ] **Step 1: Write merger RED cases**

至少冻结：

```python
proposal = SemanticIntentProposal(
    goal=UnderstandingGoal.RECOMMENDATION,
    topic=TopicCode.SUNSCREEN,
    concerns=(),
    observations=(),
    references=(),
    acts=(),
    confidence=0.95,
    clarification_hint=ClarificationCode.TOPIC,
)
```

Expected: merged goal/topic 已完整时，`TOPIC` hint 不产生 uncertainty。

同理：

- goal 已明确时忽略 stale `GOAL` hint；
- topic 已明确时忽略 stale `TOPIC` hint；
- current item 已被 typed context 解析时忽略 stale `REFERENCE` hint；
- 没有预算诉求时忽略 `CURRENT_BUDGET_UNKNOWN`；
- 真缺槽、真实冲突、低置信仍然澄清。

- [ ] **Step 2: Implement slot-aware admission**

`signal_merger.py` 只在对应槽位最终仍未解析时接纳 hint：

```text
GOAL      -> merged goal 仍为 clarification
TOPIC     -> merged topic is None
REFERENCE -> 当前任务需要 reference 且 typed context 未解析
BUDGET    -> 用户明确提出预算但没有合法 bound
CONCERN   -> 目标能力确实要求 concern 且当前没有
```

普通 concern、观察或偏好不是推荐的强制字段，不得仅因列表为空而澄清。

- [ ] **Step 3: Keep true fail-closed behavior**

以下情况必须继续澄清：

- semantic confidence 低于既有门槛；
- exact 和 semantic 硬冲突；
- 多个不同正向品类；
- 非法或越界数字；
- 指代超出当前候选；
- comparison/suitability 确实没有商品 reference；
- provider unavailable 且不存在协议闭合精确任务。

- [ ] **Step 4: Run focused GREEN**

```bash
.venv/bin/python -m pytest -c pytest-guide.ini -q \
  tests/guide/intent/test_signal_merger.py \
  tests/guide/intent/test_signal_merger_context_lane.py \
  tests/guide/intent/test_task_planning.py
```

Expected: PASS，且 RED matrix 中普通推荐不再变成 typed clarification。

### Task 3: Route Phase 2 Goals Without Lying

**Purpose:** comparison/suitability 是基础能力；用户可以直接说商品名，不要求先经过推荐。

- [ ] **Step 1: Freeze expected behavior**

```text
帮我对比当前这两款
  -> comparison
  -> 当前 batch 有至少两款时进入比较
  -> 没有两款时澄清 REFERENCE，不是 GOAL

对比理肤泉特护清盈防晒乳和清透防晒乳
  -> comparison
  -> 直接绑定目录中的两个 Canonical product
  -> 不要求先生成推荐 batch

敏感肌用当前这款防晒会不会闷痘
  -> suitability
  -> 当前 item 可解析时进入适配/避坑
  -> 当前 item 不存在时澄清 REFERENCE，不是 GOAL

敏感肌用理肤泉特护清盈防晒乳会不会闷痘
  -> suitability
  -> 直接绑定目录商品后读取批准事实
  -> 不要求先推荐

想了解这个防晒为什么适合油皮
  -> knowledge/assessment
  -> 有当前 item 时回答证据
  -> 无 item 时澄清 REFERENCE
```

- [ ] **Step 2: Reuse existing verticals**

不得在 `task_planning.py` 里重新实现比较、适配、评论或避坑。它只产生 typed mode/reference，然后复用现有：

```text
image/text comparison contracts
review_evidence
pitfalls
scenario evidence
conversation snapshot
```

如果当前文字链没有合法的 comparison/suitability dispatcher，今晚只增加一个最小 typed dispatcher。不得回退旧 V2，不得通过关键词在 API 或前端重新识别意图。

- [ ] **Step 3: Add safe direct product-name binding**

新增目录绑定责任层：

```text
app/guide/retrieval/product_name_resolver.py
tests/guide/retrieval/test_product_name_resolver.py
```

语义模型最多提名 4 个原文商品片段，不得输出 product ID：

```python
class SemanticProductMention(_StrictModel):
    source_text: str
    source_span: SourceSpan
```

代码只在当前 103 商品目录内绑定：

```text
source span 必须逐字匹配当前 message
先匹配完整 product_identity
再匹配受控品牌/商品别名
唯一命中 -> Canonical product ID
0 命中 -> 明确说明目录无数据
多命中 -> REFERENCE 澄清并列候选
```

禁止模型直接给 ID，禁止模糊相似度偷偷选一个，禁止联网补目录外商品事实。

comparison 要求唯一绑定 2-4 个不同商品；suitability 要求唯一绑定 1 个商品。

- [ ] **Step 4: Remove the blanket serum clarification**

“精华必须明确修护”是早期窄纵切，不是 Phase 2 的正常产品行为。

今晚验收：

```text
想要保湿的精华
```

必须做到二选一：

1. 有批准 efficacy evidence 时推荐并说明依据；
2. 当前证据不足时说明证据不足，但不得问“你是不是要修护精华”。

不得假装保湿诉求已经用于硬筛，也不得静默忽略后给出确定结论。

- [ ] **Step 5: Support the existing approved efficacy vocabulary**

当前 Canonical 已有真实功效值，包括保湿、补水、舒缓、修护、紧致、抗皱等。模型负责把用户说法提名到闭合功效枚举，代码只允许映射到批准词表，并用 Canonical known evidence 做筛选或排序。

最低验收：

```text
保湿/补水 -> hydration
舒缓 -> soothing
修护/屏障 -> repair
紧致/抗皱/淡化细纹 -> anti_aging
美白/提亮/淡斑 -> brightening
控油 -> oil_control
祛痘/抗痘 -> acne_care
```

不在闭合词表中的功效只做 typed CONCERN 澄清。商品功效为 unknown 时不能声称匹配。

- [ ] **Step 6: Verify message/stream parity**

```bash
.venv/bin/python -m pytest -c pytest-guide.ini -q \
  tests/guide/application/test_chat_api_adapter.py \
  tests/guide/runtime/test_runtime_http.py
```

Expected: message 和 stream 对同一 typed goal 给出相同 intent、cards、clarification code 和单终态。

### Task 4: Add Safe Semantic Number Candidates

**Purpose:** 不再用正则穷举中文数字，也不把模型数字直接当硬约束。

- [ ] **Step 1: Extend the strict semantic contract**

在 `semantic_contracts.py` 增加受限候选，建议合同：

```python
class SemanticNumberCandidate(_StrictModel):
    kind: Literal["budget"]
    relation: Literal["maximum", "minimum", "range", "approximate"]
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    source_text: str
    source_span: SourceSpan
    confidence: float = Field(ge=0.0, le=1.0)
```

`SemanticIntentProposal` 增加：

```python
number_candidates: tuple[SemanticNumberCandidate, ...] = Field(
    default_factory=tuple,
    max_length=2,
)
```

只允许 budget。禁止 product ID、candidate ID、数量、折扣、评分和商品事实进入该字段。

- [ ] **Step 2: Require source binding**

代码接纳候选前必须全部满足：

```text
message[start:end] == source_text
span 位于当前 message
minimum/maximum 为有限 Decimal
bound > 0
minimum <= maximum
候选与文本中的方向一致
候选不与 exact 阿拉伯数字冲突
候选没有覆盖已被其他 exact token 消费的 span
```

任一失败都只产生 typed BUDGET clarification，不能进入 `BudgetDraft`。

- [ ] **Step 3: Define exact and ambiguous examples**

直接接纳：

```text
三百以内 -> maximum=300
两百五以内 -> maximum=250
三百到五百 -> minimum=300, maximum=500
```

需要确认：

```text
百来块
250左右
几百上下
三张以内
```

确认文案必须引用用户原说法和模型提名值，例如：

```text
“三张以内”我先理解成最高 300 元，可以按这个预算筛吗？
```

不能再要求用户“请使用阿拉伯数字”。

- [ ] **Step 4: Exact values remain authoritative**

```text
预算300以内，也就是三百
```

exact 300 与候选 300 一致时只保留一个硬约束。

```text
预算300以内，也就是五百
```

冲突时澄清 BUDGET，模型不得覆盖 exact 300。

- [ ] **Step 5: Cover revision**

首轮：

```text
预算三百以内推荐防晒
```

追问：

```text
再便宜点，两百以内
```

都必须经过同一个候选验证器。不得在 `budget_revision_parsing.py` 再造第二套中文数字转换逻辑。

- [ ] **Step 6: Run focused GREEN**

```bash
.venv/bin/python -m pytest -c pytest-guide.ini -q \
  tests/guide/understanding/test_semantic_intent_contracts.py \
  tests/guide/adapters/test_intent_prompt.py \
  tests/guide/understanding/test_parallel_understanding.py \
  tests/guide/understanding/test_text_understanding.py \
  tests/guide/understanding/test_budget_revision_parsing.py \
  tests/guide/intent/test_budget_revision_planning.py
```

Expected: 明确中文预算生成合法 constraint；模糊说法保持 typed clarification；非法、冲突和越权全为 0。

### Task 5: Use DeepSeek Only After Local GREEN

**Purpose:** 真实 API 只验证合同，不参与盲调。

- [ ] **Step 1: Finish the untracked official smoke entry**

先运行：

```bash
.venv/bin/python -m pytest -c pytest-guide.ini -q \
  tests/guide/tools/test_run_official_deepseek_smoke.py \
  tests/guide/tools/test_run_real_deepseek_intent_ab.py \
  tests/guide/tools/test_real_ab_evidence.py
```

Expected: PASS。

然后单独提交：

```bash
git add \
  tools/guide_gates/run_official_deepseek_smoke.py \
  tests/guide/tools/test_run_official_deepseek_smoke.py
git commit -m "test(guide): wire official DeepSeek smoke entry"
```

- [ ] **Step 2: Run one bounded normal-language probe**

今晚真实 DeepSeek 上限：

```text
model=deepseek-v4-pro
max_cases=16
max_repair_attempts=1
max_tokens=256
temperature=0
thinking=disabled
```

输入优先覆盖：

- 普通推荐 4 条；
- 中文明确数字 4 条；
- 模糊数字 4 条；
- comparison/suitability/followup 4 条。

不跑 Flash，不跑两阶段，不跑 128 条。

- [ ] **Step 3: Stop on provider or schema trouble**

满足任一条件立即停止真实调用：

```text
key precheck failure >= 1
provider unavailable/timeout > 10%
schema invalid > 10%
same contract failure appears twice
```

不允许用增加重试次数消耗额度。

### Task 6: Re-Verify Phase 2 On Current HEAD

**Purpose:** 把“以前通过过”改成“今天这版真实通过”。

- [ ] **Step 1: Run focused vertical tests**

```bash
.venv/bin/python -m pytest -c pytest-guide.ini -q \
  tests/guide/application/test_consultation_chat_flow.py \
  tests/guide/application/test_consultation_confirmation.py \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/application/test_image_recommendation_flow.py \
  tests/guide/runtime/test_feedback_runtime_http.py \
  tests/guide/runtime/test_runtime_http.py
```

记录每条纵向能力的真实 passed/failed 数，不只记录总数。

- [ ] **Step 2: Run supervised normal/adversarial browser**

```bash
OUT="/private/tmp/xiaoro-browser-matrix-$(date +%Y%m%d%H%M%S)"
PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/run_runtime_browser_matrix.py \
  --timeout-seconds 600 \
  --heartbeat-seconds 30 \
  --ready-timeout-seconds 30 \
  --output-dir "$OUT"
```

Expected:

```text
normal=PASS
adversarial=PASS
page_errors=0
SSE_parse_errors=0
failed_product_images=0
legacy_fallback=0
single_terminal_event=true
```

- [ ] **Step 3: Run the remaining Phase 2 browser verticals**

在一个受监管 Uvicorn 进程下顺序运行：

```text
runtime_browser_consultation.py
combined_image_browser_gate.py
feedback_browser_vertical.py
category_profile_browser_gate.py
```

必须覆盖：

```text
consultation -> provisional -> user confirmation -> profile write
profile -> later recommendation fill-only
single image -> identify/suitability
two images -> exact two-card comparison
four images -> exact four-card comparison
OCR observed or typed unavailable
scenario -> review evidence -> pitfalls
feedback idempotency
session switch
late response ignored
```

- [ ] **Step 4: Produce a capability ledger**

每项只能填以下状态：

```text
PASS_CURRENT_HEAD
FAIL_CURRENT_HEAD
NOT_RUN
```

禁止用 `HISTORICAL_PASS` 冒充 `PASS_CURRENT_HEAD`。

### Task 7: Build Full-Catalog Category Data Closure

**Purpose:** 15 商品试点不再代表数据完成。对全部 103 商品按所属品类生成适用字段、真实值覆盖和能力阻断状态。

- [ ] **Step 1: Freeze all 103 catalog identities**

输入只使用：

```text
data/canonical/core_products_v1.jsonl
data/canonical/core_products_v1_manifest.json
app/guide/retrieval/category_profiles.py
app/guide/retrieval/category_fact_contracts.py
```

必须证明：

```text
product_count=103
raw_category_mapping=39/39
unknown_category=0
duplicate_product_id=0
```

- [ ] **Step 2: Generate every applicable category field**

不得给六个品类套同一字段。当前 registry 的适用字段为：

```text
skincare:
  product_identity, brand, category, price, ingredients_present,
  verified_absences, safety, usage, efficacy, suitable_skin, texture,
  mechanism, clinical_evidence

suncare:
  product_identity, brand, category, price, ingredients_present,
  verified_absences, safety, usage, suitable_skin, texture, spf_pa,
  water_resistance, reapplication

base_makeup:
  product_identity, brand, category, price, ingredients_present,
  verified_absences, safety, usage, suitable_skin, texture, shade,
  finish, coverage, longevity

color_makeup:
  product_identity, brand, category, price, ingredients_present,
  verified_absences, safety, usage, texture, shade, finish, longevity

cleanser:
  product_identity, brand, category, price, ingredients_present,
  verified_absences, safety, usage, suitable_skin, texture,
  cleansing_form, cleansing_power, surfactant_type, rinse_behavior,
  double_cleanse

fragrance:
  product_identity, brand, category, price, ingredients_present,
  verified_absences, safety, usage, longevity, fragrance_family,
  top_notes, heart_notes, base_notes, sillage
```

`report_catalog_field_coverage.py` 为每个适用字段输出：

```text
known
pending
quarantine
unknown
not_applicable
```

不得只检查“字段 key 存在”。`known` 必须有 normalized value 和批准 source refs。

- [ ] **Step 3: Define product readiness from real values**

每个商品输出：

```text
IDENTITY_READY
RECOMMEND_READY
COMPARE_READY
SUITABILITY_READY
FULL_READY
BLOCKED
```

规则：

- identity/brand/category/price 任一缺失，整件 `BLOCKED`；
- 推荐使用的 hard_filter/soft_rank 字段缺失，不能声称该维度匹配；
- 比较字段缺失时，该商品不能参加该维度的确定性比较；
- suitability 缺 suitable_skin/safety/ingredients evidence 时只能回答证据不足；
- 只有全部适用字段为 known 或真实 not_applicable 才是 `FULL_READY`；
- unknown 不是齐全，不能转成空字符串、默认值或“无”。

- [ ] **Step 4: Reuse the existing 64,449-file inventory**

先验证：

```text
inventory_sha256=1e26747208d3f83c01f4137a9f1faa06a5e2384fc78594c808f23e014e51a0c5
inventory_file_count=64449
approved_source_roots=2
```

hash 一致时禁止再次遍历磁盘。直接在已有 inventory 中按可信身份查找全部 103 商品的来源：

```text
exact item ID
exact SKU
full source SHA-256
approved root ID
```

禁止按文件名、模糊商品名、OCR 文本或相似页面猜绑定。

- [ ] **Step 5: Classify every HTML value by its real source**

机器不能只抽一段文本。每个候选必须带：

```text
source_sha256
source_locator
source_class
item_id
sku_id
raw_value_sha256
normalized_value_sha256
```

`source_locator` 必须指向可重复定位的 HTML/JSON 结构，例如：

```text
official registration JSON
merchant structured parameter
merchant description block
package/OCR observation
consumer review item
Q&A item
marketing recommendation block
```

来源分类规则：

```text
official_registration:
  可写入备案、SPF/PA 等获准结构化字段

merchant_parameter:
  可写入明确规格、色号、香调、用法等获准字段

merchant_description:
  可作为商家宣称的功效、适用、质地、持久、清洁力等信息
  可用于展示、普通对比和 soft rank
  必须在回答中保留“商家宣称”来源

merchant_title_claim:
  京东等页面结构化参数很少时，可提取标题中的明确商品宣称
  只允许展示、普通对比和 soft rank
  不得证明安全、无添加或过敏适配

merchant_description_ocr:
  详情长图 OCR 必须绑定页面 SHA、图片 SHA、item 和 SKU
  能力与 merchant_description 相同
  不得因为 OCR 出现一句话就升级为硬安全事实

consumer_review:
  只允许质地、持久、清洁感、扩香等体验字段
  不得证明成分、安全、备案或“未添加”

package_ocr:
  默认 evidence only
  只有同时绑定包装 asset、item 和 SKU，且字段 policy 允许时才可升级

qa:
  quarantine，不进入生产事实

promotion_or_recommendation_block:
  价格活动、榜单、代言、推荐话术不进入商品事实
```

来源类型由 DOM/嵌入 JSON 路径和页面结构机械判定，不让 LLM 看一句话后猜“这像商家说的还是用户说的”。

- [ ] **Step 6: Extend candidate generation from 15 to 103**

`build_seed_database_candidates.py` 已支持任意 product ID 集，保留该能力。

将 `reconcile_pilot_candidates.py` 中可复用核心抽成 catalog 级函数，同时保留旧 pilot wrapper 兼容测试。不得复制第二套解析器。

旧 `_PARAMETER_FIELD_MAP` 只能识别 8/116 个真实参数名，必须替换成按 `CategoryProfile` 分组的参数 registry。不得再维护一张所有品类共用的小词典。

最低映射覆盖：

```text
skincare:
  功效/核心功效 -> efficacy
  适合肤质/适用肤质/肤质问题 -> suitable_skin
  质地 -> texture
  原料成分/核心成分/主要成分 -> ingredients_present

suncare:
  SPF/SPF值/防晒指数/PA值/防晒标准 -> spf_pa
  防水/耐水/防水分类 -> water_resistance
  成膜速度 -> texture
  使用场景/适用场景 -> usage

base_makeup:
  色号/颜色/颜色分类 -> shade
  妆效 -> finish
  遮瑕分类/遮瑕部位 -> coverage
  持久/持妆声明 -> longevity

color_makeup:
  色号/颜色/颜色分类 -> shade
  妆效/哑光/水润声明 -> finish
  持久声明 -> longevity

cleanser:
  洁面分类/洁面单品/卸妆分类 -> cleansing_form
  清洁功效/卸妆力声明 -> cleansing_power
  核心成分/原料成分 -> surfactant_type 或 ingredients_present
  起泡程度/冲洗/洗后感 -> rinse_behavior

fragrance:
  香调 -> fragrance_family
  前调/中调/后调 -> top_notes/heart_notes/base_notes
  香味/香水分类 -> fragrance_family 或 display evidence
  留香/持久声明 -> longevity
  扩香声明 -> sillage
```

同一个参数名在不同品类可以映射到不同字段；映射必须同时检查目标字段是否适用于当前 profile。

全目录候选生成必须：

```text
读取 103 个 Canonical IDs
读取现有 seed database source tags
读取所有身份绑定成功的保存页
按 category field registry 选择字段
按 source policy 标记 capability
输出稳定排序的 status/pending/quarantine
重复运行字节和 SHA 一致
```

- [ ] **Step 7: Keep source policy strict**

```text
official registration -> 可进入获准的 hard_filter/compare/rank
merchant structured parameter -> 可进入获准的 compare/rank/display
merchant title/description/description OCR -> evidence/display/compare/soft_rank
approved consumer review -> experiential evidence/display/soft_rank
package OCR/full ingredient list -> 按字段 policy 单独升级
Q&A/活动/榜单/代言 -> quarantine
跨 SKU/多规格无法绑定 -> quarantine
无来源 -> unknown
```

特别注意：

- `verified_absences` 只有明确“未添加/不含”证据才能 known；
- `water_resistance` 只有明确防水/耐水证据才能 known；
- 普通功效、肤感、持妆、遮瑕、香调允许使用已绑定的商家宣称；
- 酒精过敏、成分排除、安全风险不能只依赖商家宣称或用户评价；
- 成分硬排除必须有完整成分表、备案或明确包装证据；
- 没写不等于没有；
- 不适用品类字段必须是 not_applicable，不能是伪 unknown。

- [ ] **Step 8: Carry forward the old pilot verdicts**

旧 9 条 pending 不丢失：

```text
Verifier A: 0 PASS / 7 DEFER / 2 REJECT
Verifier B: 5 PASS / 2 DEFER / 2 REJECT
Common PASS: 0
```

处理规则：

1. 两个 Canonical-known override 候选保持 REJECT。
2. 两个共同 DEFER 且没有新 source asset/SKU binding 的候选保持 DEFER。
3. 只重新检查 5 个 `A=DEFER, B=PASS` 分歧项。
4. 如果 catalog 级来源恢复补出了真实 SKU/asset binding，两个 verifier 对新 frozen SHA 独立重跑。
5. 如果仍无绑定，保持 DEFER，不派第三个 verifier 猜测。

- [ ] **Step 9: Keep verification independent**

每个新 pending 候选必须有两个只读 verifier：

- 输入同一 frozen SHA；
- 逐项核对 product/item/SKU/field/value/source/capability；
- 不共享中间结论；
- 不写 production；
- 不进入旧仓库；
- 不在主 worktree 成为第二个 writer。

最终决策：

```text
PASS + PASS -> eligible for signed approval
任何其他组合 -> pending/quarantine/unknown
```

- [ ] **Step 10: Promote only the approved intersection**

如果共同 PASS 为 0：

```text
promotion_invocations=0
production_fact_count=0
```

如果存在共同 PASS：

1. 生成显式 reviewer、reviewed_at、decision、reason；
2. 对 decision batch 做 detached HMAC signature；
3. 锁定 candidate/quarantine/decision SHA；
4. 运行 `tools/guide_data/promote_approved_category_facts.py`；
5. promotion 后重读 manifest 和 facts；
6. 重建 103 商品 coverage/readiness；
7. 验证未批准候选不能改变 cards、winner 或 ranking。

- [ ] **Step 11: Report honest completion**

明早至少输出：

```text
每个品类商品数
每个品类适用字段总数
known/pending/quarantine/unknown/not_applicable
IDENTITY_READY/RECOMMEND_READY/COMPARE_READY/SUITABILITY_READY/FULL_READY/BLOCKED
新恢复来源页数
双 verifier PASS/DEFER/REJECT
promotion count
production fact count
```

只要还有 unknown 或 quarantine，就不能写“全字段完成”。必须同时写出缺口来源和哪些能力因此被阻断。

### Task 8: Run Tonight Closure Gates

- [ ] **Step 1: Changed-files verification**

只运行本晚变更相关 focused tests，不重复正式 full-file audit。

- [ ] **Step 2: Guide full only after vertical GREEN**

```bash
.venv/bin/python -m pytest -c pytest-guide.ini -q tests/guide
```

如果 Phase 2 纵向仍红，不运行 Guide full 来制造无意义等待。

- [ ] **Step 3: Mechanical boundaries**

```bash
.venv/bin/python -m compileall -q app tools
.venv/bin/python -m pytest -c pytest-guide.ini -q \
  tests/guide/runtime/test_import_boundary.py \
  tests/guide/runtime/test_legacy_chat_removal.py
```

- [ ] **Step 4: Protected assets**

核对：

```text
Canonical 103
deterministic ranking SHA
approved review sources=6
formal full-file audit invocations=1
legacy importer=0
```

- [ ] **Step 5: Process teardown**

结束后必须确认没有残留：

```text
pytest
uvicorn
playwright
run_official_deepseek_smoke
run_real_deepseek_intent_ab
```

### Task 9: Write The Morning Checkpoint

只写真实数据：

```text
completed
current_blocker
remaining_work
estimated_finish
test_counts
browser_verticals
model/provider/prompt/schema
usage
latency
cost
evidence_hashes
data_verdict_counts
promotion_count
production_fact_count
residual_processes
git_status
```

如果任何 Phase 2 核心能力未跑，必须写 `NOT_RUN`，不能写“代码已存在所以完成”。

## Acceptance Examples

### Should Continue Without Clarification

```text
有没有适合油皮的防晒推荐
预算三百以内，帮我找油皮防晒
不要含酒精的爽肤水
避开香精的面霜
那第二款呢
再便宜点，两百以内
最近脸挺油的，又怕闷，三百左右有没有通勤防晒
我平时就上下班用，不想下午糊脸，也别太贵，油皮能用的防晒看看
对比理肤泉特护清盈防晒乳和清透防晒乳
```

### Should Ask A Useful Clarification

```text
百来块的
  -> 问预算范围，不要求改打阿拉伯数字

帮我对比一下
  -> 当前没有两款 reference 时问“对比哪两款”

这个适合敏感肌吗
  -> 当前没有 item reference 时问“指哪一款”

粉底液还是口红
  -> 两个正向品类冲突，问选哪个
```

### Should Fail Closed

```text
预算 -100
预算 0
300以内也就是500
不存在的第五款
provider invalid JSON
模型输出 product_id/candidate_id/facts
```

## Stop Conditions

任一条件满足就停止对应路径，不继续堆补丁：

1. 同一最早失败层连续修复两次仍失败。
2. 16 条真实 probe 的正常路由准确率低于 85%。
3. provider unavailable/timeout 或 schema invalid 超过 10%。
4. Key 文件不是普通文件、不是 `0600` 或是 symlink。
5. 真实输出目录、FD binding 或 evidence 原子发布失败。
6. 出现第二个 writer 修改同一 worktree。
7. 任一命令进入 `xiaoro-shopping-master`。
8. Canonical、排序或 6 条批准评论发生未计划漂移。
9. 数据工具把未绑定 item/SKU/source SHA 的内容错误放入 pending/known；单行缺绑定只应 quarantine，不停止其他商品。
10. promotion 缺 reviewer、decision、reason、SHA 或 signature。
11. Uvicorn/Playwright/pytest/DeepSeek runner 无法完成 TERM/KILL 清理。

停止不等于宣布 COMPLETE。checkpoint 必须写明具体失败层和下一步。

## Known Traps

1. **CLI argument loss**
   `run_official_deepseek_smoke.py` 必须在 `argv is None` 时读取 `sys.argv[1:]`。

2. **Private output leaf**
   evidence parent 必须存在，但 leaf 必须由 `PrivateRunDirectory` 创建，不能预创建 leaf。

3. **Direct tool import**
   `tools/guide_data/*.py` 直接运行时需要 `PYTHONPATH=.`，否则会误报 `ModuleNotFoundError: app`。这不是业务 Bug。

4. **Single-stage fields**
   单阶段结果使用 `goal_correct/topic_correct/...`，不能再按两阶段的 `route_critical_match/detail_key_match` 读取。

5. **Prompt tuning drift**
   先修 merger/task planning，再决定 Prompt 是否真的有问题。禁止拿一个句子反复改 Prompt。

6. **Fake data progress**
   inventory 数量、candidate 数量、known 数量和 production fact 数量是四个不同指标。

7. **Historical pass**
   历史 browser PASS 不能替代当前 HEAD。

8. **Comparison scope**
   两图/四图比较已经存在，不得重新手写一个比较算法。文字 comparison 负责 typed dispatch，并把当前会话 reference 或用户原文商品名安全绑定到 103 商品目录；不能要求用户必须先推荐。

9. **Suitability certainty**
   没有批准事实时必须返回证据不足，不能生成“安全”“一定适合”。

10. **Front-end inference**
    前端只消费 typed SSE，不从答案文案猜 intent、cards、review 或 pitfalls。

## Explicit Non-Goals Tonight

- 不跑 128 条正式模型门禁。
- 不复跑 Flash 或两阶段 Pro。
- 不调整 95% 正式门槛。
- 不重新扫描 64,449 个 inventory 文件。
- 不增加新商品或新字段。
- 不做搭配推荐。
- 不重做前端视觉。
- 不调用第二次 full-file audit。
- 不 push、不部署、不切生产流量。
- 不使用旧仓库。

## Monday Path

### Saturday

- 处理今晚 Phase 2 ledger 中的真实 FAIL。
- 继续补全 103 商品矩阵中有批准来源但尚未完成核对的字段。
- 对数据共同 PASS 项完成签名 promotion、readiness 重算和卡片回归。
- 对没有真实来源的关键字段保留 `BLOCKED`，列出具体缺口，不伪造完成。
- 运行单阶段 V4-Pro 冻结 128 条正式门禁。
- 只有正式门禁通过后接入 production composition。

### Sunday

- 运行完整 normal/adversarial/consultation/image/feedback/category browser matrix。
- 运行 focused、Guide full、runtime full 和整个 `tests/`。
- 完成前端 typed rendering 的最后问题，不做视觉重构。

### Monday

- 只做最终回归、证据核对和 handoff。
- 核对 tasks/checklist 全部真实满足后才能标记 COMPLETE。
- 部署和切流仍是独立决策，不因代码 COMPLETE 自动执行。

## Morning Deliverables

明早用户应能直接看到：

1. 哪些正常句子不再澄清，带真实 terminal event 和 product IDs。
2. 中文数字、口语数字、冲突数字各自怎么处理。
3. 直接报 2-4 个目录商品名的真实对比结果，以及目录外/重名的澄清结果。
4. Phase 2 每项当前 HEAD 的 PASS/FAIL/NOT_RUN。
5. 103 商品按六品类的字段覆盖与 READY/BLOCKED 数量。
6. 全目录新增 pending/quarantine 和双 verifier 交集，另列旧 5 个分歧项结果。
7. 是否发生 promotion，若发生则有 decision/signature/hash 和 promotion 后 readiness。
8. DeepSeek 实际调用数、token、延迟、费用。
9. 当前 Git commit、工作区状态和残留进程数。

只有这九项齐全，今晚工作才算完成。
