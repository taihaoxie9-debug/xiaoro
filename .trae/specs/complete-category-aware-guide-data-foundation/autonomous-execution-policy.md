# Phase 3A 自治执行与动态并发政策

## 1. 不可变约束

- 活跃 Agent：2–8。
- 并发代码 writer：0–4。
- Integration Writer：最多 1。
- 同一文件域 writer：最多 1。
- 至少保留 1 个 independent read-only audit/verifier 槽位。
- `app/services/**`、`app/database/**`、`data/canonical/**` 和排序内核为保护路径。
- 新 Guide 不得 import legacy service/database。
- 自动化不得批准 HTML、OCR、官方资料或评论候选。
- OCR、评论和营销文案不得覆盖 Canonical 核心事实。
- 未知、冲突和不适用字段不得产生 winner、过滤或排序分。
- 不 push、不部署、不切流。

## 2. 初始角色

1. Root orchestrator：只负责调度、风险、证据和状态。
2. Integration Writer：唯一写 integration branch 和共享文件。
3. Category contract writer：品类画像、字段合同、taxonomy。
4. Data tooling writer：candidate builder、promotion、资产 loader。
5. Routing/behavior writer：理解、task plan、Guide 行为 focused tests。
6. Independent auditor/verifier：冻结 SHA 只读审查。

测试和浏览器稳定后可增加只读 verifier，最多 8 个 Agent。不得为占满并发创建无所有权
任务。

## 3. 文件所有权

### Category contract writer

```text
app/guide/retrieval/category_profiles.py
app/guide/retrieval/category_fact_contracts.py
app/guide/retrieval/category_taxonomy.py
tests/guide/retrieval/test_category_*.py
```

### Data tooling writer

```text
app/guide/retrieval/category_fact_assets.py
app/guide/retrieval/category_fact_reader.py
tools/guide_data/**
tests/guide/tools/test_*category*
tests/guide/tools/test_*review*
tests/fixtures/guide/category_*
```

### Routing/behavior writer

```text
app/guide/understanding/contracts.py
app/guide/understanding/exact_parsing.py
app/guide/intent/task_planning.py
focused understanding/intent tests
```

### Integration Writer

```text
app/guide/adapters/catalog/canonical_guide_catalog.py
app/guide/decision/contracts.py
app/guide/presentation/**
app/guide/application/chat_api_adapter.py
app/guide_runtime/composition.py
app/api/v1/chat.py
app/static/chat.html
tools/guide_gates/**
.trae/specs/complete-category-aware-guide-data-foundation/**
docs/audits/category-data-foundation/**
```

## 4. 并发状态

| 模式 | Agent | Writer | 条件 |
| --- | ---: | ---: | --- |
| `INCIDENT` | 2–3 | 1 | 保护路径、事实权力、跨会话或审计高风险 |
| `HIGH_RISK` | 3–5 | 1–2 | 共享合同和 integration |
| `NORMAL` | 5–7 | 2–4 | 文件域独立、focused 稳定 |
| `LOW_RISK_PARALLEL` | 6–8 | 1–3 | 测试、浏览器、审计、文档核验 |

从 `HIGH_RISK` 启动。Category contracts 和 data tooling 文件域冻结后进入 `NORMAL`。
integration、全量和浏览器阶段降回 3 个 Agent。

## 5. 自动升并发

同时满足以下条件才增加一个 Agent：

1. 最近两个 checkpoint 绿色；
2. 新任务文件域与现有 writer 无交集；
3. integration worktree 干净；
4. 没有未解释 flaky；
5. 测试端口、状态目录和浏览器上下文隔离；
6. 新 Agent 有明确输出、停止条件和 owner。

每个 checkpoint 最多增加一个 Agent。

## 6. 自动降并发

出现任一情况立即降并发：

- 同文件或同 authority 双 writer；
- 39-category mapping 或字段 registry 语义冲突；
- candidate、approved、quarantine 数量不守恒；
- stable identity 内容冲突；
- focused 与 full 结论不一致；
- browser 状态串扰；
- 保护路径或排序 SHA 漂移；
- 未批准字段改变 winner 或卡片；
- 审计提出 P0/P1；
- Agent 无法提供提交、测试和证据映射。

处理流程：

```text
freeze -> reproduce -> RED -> single-writer fix -> independent verify
```

## 7. 自治边界

执行系统可自行处理：

- import、类型、格式和 fixture；
- 只读 hash/manifest 漂移定位；
- isolated port/state cleanup；
- 可由 spec 唯一决定的别名优先级；
- exact duplicate collapse；
- 失败资产 promotion 的临时文件清理；
- RED 已唯一证明的局部回归。

必须升级用户：

- 需要改变六个画像、字段语义或 12 个试点；
- 需要批准新的事实或评论；
- 需要修改 Canonical、排序或保护路径；
- destructive migration 或删除数据；
- push、部署、切流；
- 隐私、合规或外部凭证决策；
- 同一硬阻塞隔离后连续三次。

用户不在线时，暂停受阻线路并继续其他独立工作。

## 8. 审计政策

- 每个 capability loop 只在开头执行一次 full-file audit。
- audit key 由 audit profile 和排序后的 production blob manifest 决定。
- 相同 key 复用 PASS，不因 commit、worktree 或会话变化重审。
- finding 必须转为 RED；修复后跑正常门禁，不重复同 key full-file audit。
- 最终建立独立 `FINAL-CATEGORY-DATA-AUDIT`。
- auditor 只读，不修改被审计 worktree。

## 9. Checkpoint

每个 checkpoint 必须记录：

```text
source commit
integration commit
stable patch-id
production blob manifest
focused result
boundary result
data counts and hashes
browser result when applicable
audit state
remaining blockers
```

普通 checkpoint 通过后自动继续，不等待用户。只有 COMPLETE、重大决策、连续三次硬阻塞或
用户暂停才停止。
