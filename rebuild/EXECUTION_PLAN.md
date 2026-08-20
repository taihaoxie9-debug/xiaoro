# 干净重建执行方案（EXECUTION PLAN）

> 已废弃，禁止执行 P0-P8。正式架构总纲见
> `docs/superpowers/specs/2026-08-06-xiaoro-clean-growth-architecture-design.md`。
> 用户复核正式设计后，才会按每条纵向 slice 分别生成实施计划。

> 事实源：飞书文档 rev34 + 三路只读代码审计（2026-08-06）
> 目标：以远程可跑 demo 为地板，搬入已验证真资产，重写脏编排层，得到干净、分层、可收敛的对话导购系统。
> 铁律：分层分责，边界由 `check_boundaries.py` 机器强制；商品事实只来自 canonical；LLM 只返回枚举。

---

## 0. 全局判断（先定心）

- **方向对**：意图→召回→排序→生成 是行业标准管线，非野路子。
- **架构够**：召回层、决策层已是 A 级纯净资产；意图层的正确骨架旧代码已写好，只是被默认关闭。
- **真门槛只有一个**：意图理解的"换说法"问题——纯规则无解，LLM 可解到 90%+，长尾靠追问兜底。接受"主流说得准、长尾问得巧"，不追求 100%。

---

## 1. 目标分层与禁区（每层"被禁止什么"才是价值）

| 层 | 目录 | 独占 | 禁止（机器强制） |
|---|---|---|---|
| 意图 intent | app/guide/intent | 语义理解、意图分类(LLM枚举)、槽位(代码) | 碰商品事实/字段 |
| 召回 catalog | app/guide/catalog | 读 canonical、DB 召回、归一化 | 业务判断、排序、判 winner |
| 决策 decision | app/guide/decision | 硬过滤、排序、选 winner、判兼容、风险打分 | 读 raw 描述/评论/营销词 |
| 响应 response | app/guide/response | ResponsePlan 决定输出结构 | 选品、改序 |
| 编排 orchestration | app/guide/orchestration | 串 parse→retrieve→decide→plan→present | 实现评分/过滤/词表 |
| 展示 presentation | app/guide/presentation | 渲染文本/SSE 事件 | 选品、改序、判兼容、打分 |

契约共享层：`decision_contracts`（typed 枚举与数据类）被 catalog 与 decision 共用，单独作为契约模块，不算越界。

---

## 2. 资产三分类（基于审计实证）

### 🟢 直接搬（A级纯净，自闭环）
- **数据**（已完成 ✅）：core_products_v1.jsonl(103) + manifest + review_decisions.jsonl(1234) + seed_dump.sql，sha 校验通过。
- **决策 typed 件** → `app/guide/decision/`：decision_contracts, decision_fields, candidate_evaluator, ranker, retrieval_constraint_policy, budget_constraint_parser, numeric_boundaries, ingredient_provenance, deterministic_ranking(从 app/services/ 搬)。
- **facet 全族** → `app/guide/decision/facets/`（整族搬，内部 import 零改动）：facet_registry + 9个 *_facets + product_facets + decision_fields。
- **召回件** → `app/guide/catalog/`：canonical_product_reader, canonical_consumer_adapters, product_facts, review_signals, shadow_evidence/(整目录，自闭环)。

### 🟡 参考重写（逻辑有价值，形态脏）
- **agent.py(4957)** → 参考其 11 步编排骨架（第4节），重写成 `app/guide/orchestration/pipeline.py`（薄）。
- **presenter.py(6633)** → 保留 present_* 方法签名与 result 契约，重写成 `app/guide/presentation/renderer.py`（薄）；把 4 处选品逻辑移到 decision 层。
- **retriever.py(960)** → 拆：DB 召回胶水(A) 独立成 catalog 数据源；纯归一化(B,约50%) 直接搬；canonical 集成(C) 保留。
- **意图层**：扶正 intent_classifier 的 LLM 枚举分类 + 门控；直接搬 budget_constraint_parser；保留 CATEGORY/SKIN_TYPE/CONCERN 词表当兜底；保留 risk_cues 领域词表；保留 router 的澄清追问闭环。

### 🔴 丢弃（补丁/伪语义/无关）
- semantic_intent_retriever(字符n-gram假向量)、semantic_embedding_intent(意图用向量,违背方针)。
- followup_orchestrator + followup_* 全族(约300KB 指代消解补丁) → 用"LLM指代消解 + 小typed会话状态"重建。
- turn_parser 里品类/排除项的口语正则补丁群(保留词表,丢消歧正则)。
- CanonicalTurn 上帝对象 → 拆成"意图结果 + 槽位/约束 + 会话状态"三个瘦结构。
- V1 整套：app/services/intent.py, app/prompts/test_intent_classifier.py, intent_prompts.py。
- v1_freeze_contract.py(3865行脚手架)、空文件 0 / 0,。

---

## 3. 必须先解决的破口（执行前定夺）

审计发现 **ranker.py 不是纯自闭环**：它 import 了 `.models`(CanonicalTurn) 和 `.response_plan`(requested_facets)，而这两个又拉入意图层的 `intent_constraints`。

**处理策略**（方案采用 B）：
- A. 把 models/response_plan 一起搬 → 快，但把意图层类型拖进决策层，污染分层。
- **B. 给 decision 层定义自己的轻量输入契约**：ranker 不再吃 `CanonicalTurn`，改吃 decision 层自有的 `RankRequest`(只含排序需要的 typed 字段)；`requested_facets` 抽成 decision 层自有小函数。→ 干净，符合分层，工作量中等。**推荐。**

同理 canonical_product_reader 依赖 decision_contracts：将 decision_contracts 明确为"契约层"，catalog 依赖契约层是允许的（边界脚本已按此配置）。

---

## 4. 编排骨架（重写 pipeline.py 的蓝本，源自 agent.py 11步）

```
chat_stream_events(message, session_id, conversation_history, image_context):
  1. yield start {session_id}
  2. PARSE:  turn = intent.parse(message, history, image)   # 槽位=代码, 意图=LLM枚举
  3. yield intent {intent, confidence, entities}
  4. ROUTE by AnswerMode(7值): recommendation/followup/compare/knowledge/judgement/clarify/no_match
  5. BRANCH:
       CLARIFY   → 追问最多2句(参考 router._prepare_clarification)
       其它模式   → catalog.retrieve → decision.evaluate+rank → response.plan
  6. yield decision_process, answer_contract (必须在 products 之前)
  7. yield products/comparison/citations/pitfalls/skincare_plan (按需)
  8. GENERATE: 文案(LLM可选,失败降级本地) → 分块 yield message{content,done:false}
  9. PERSIST 会话状态
  10. yield end {}
```

---

## 5. 前端契约最小保持集（重写不得破坏，前端零改动）

1. 端点 `POST /api/v1/chat/stream`，返回 text/event-stream。
2. 首帧 `start` 必须带 `{session_id, session_token}`。
3. SSE 事件名(或别名)落在清单内：start/turn_start, stage/thinking, intent, decision_process, answer_contract, clarify, chips, skincare_plan/routine_plan, products, comparison, routine, citations, pitfalls, message, error, end/done。
4. `message.content` 是增量拼接(非全量)；`message.done` 或 `end` 触发 finalize。
5. `decision_process`/`answer_contract` 必须在 `products` 之前发。
6. `comparison` 展开发；`pitfalls` 用 pitfalls key 最稳。
7. products 卡片字段：id, brand, category, platform, price/price_val, match_score, detail_url, display_name/name, image。
8. 未知事件前端静默忽略 → 允许分阶段补齐事件。
9. chat.py 入口(会话锁/鉴权/SSE胶水/图片适配)零改动复用，新编排器只需实现同签名 chat_stream_events。

---

## 6. 新旧切换策略（安全可回滚）

三态开关，V2/旧路径完全不动：
```
if USE_GUIDE_PIPELINE:  → app/guide/orchestration 新薄编排器
elif USE_V2_AGENT:      → V2ShoppingAgent (不动)
else:                   → 旧 agent
```
- 新编排器用局部 import，未完成不影响 V2 启动。
- 先 shadow 模式并行跑、比对 SSE 事件，契约一致后再翻开关。
- 回滚 = 翻开关，无需改代码。

---

## 7. 执行阶段（按依赖串行，每阶段跑 check_boundaries + 测试）

- **P0 地基**（部分完成）：数据搬入✅ + 六层骨架✅ + 边界脚本✅。剩：把 deterministic_ranking 等零依赖叶子件先搬入。
- **P1 契约层**：搬 decision_contracts + decision_fields + facet 全族到 decision/，改 import，跑边界脚本。
- **P2 决策层**：搬 candidate_evaluator + ranker(解破口,改吃 RankRequest) + retrieval_constraint_policy + budget_parser，写决策层单测(确定性,可测)。
- **P3 召回层**：搬 canonical_reader + adapters + shadow_evidence + retriever纯净部分到 catalog/，拆 DB 胶水。
- **P4 意图层**：扶正 LLM 枚举分类 + 搬 budget_parser + 词表兜底 + 澄清追问；写"换说法"变形测试。
- **P5 响应+展示**：ResponsePlan 搬入 response/；重写薄 renderer，选品逻辑上移 decision。
- **P6 编排**：写薄 pipeline.py(11步骨架)，实现 chat_stream_events 同签名。
- **P7 接线**：加 USE_GUIDE_PIPELINE 开关，shadow 比对 SSE，验证前端零改动。
- **P8 收尾**：全链路测试、边界脚本全绿、清理垃圾、push 存档。

依赖：P1→P2→P3 串行；P4 可与 P2/P3 并行；P5 依赖 P2;P6 依赖 P2-P5;P7 依赖 P6。

---

## 8. 防打转保证

- 每写一个文件跑 `check_boundaries.py`，红了就停、把逻辑移回该在的层，绝不在越界处打补丁。
- 意图层是唯一能碰"语义"的层；其它层物理上拿不到商品数据结构 + 脚本拦截。
- 决策层确定性(同输入同输出,无随机/时间/网络) → 可写死单测,回归不靠人肉。
- 接受意图 90%+ 上限,长尾走追问,不再为单个 badcase 加词表补丁。
