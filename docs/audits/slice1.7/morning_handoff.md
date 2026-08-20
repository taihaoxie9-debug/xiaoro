# Slice 1.7 肤质修改重筛 Morning Handoff

## 结论

**Slice 1.7 已完成，自动进入 Slice 1.8，但全局目标未完成。**

Slice 1.7 已交付六种明确肤质修改、服务端 query context 单约束替换、
完整 retrieval/decision/presentation 重跑、CAS 快照提交、正式/runtime HTTP
共用合同和真实三轮浏览器闭环。最终门禁与二次独立 review 均通过。

总目标仍以 Slice 1.8、1.9、2.0 全部退出且 Slice 2.0 真实单图浏览器闭环
通过为完成条件；本阶段 PASS 不代表全局 COMPLETE。

## 范围与 HEAD

- 分支：`rebuild`
- Slice 1.7 起始 HEAD：
  `a5f510fd8fa86d67b387cf436c9920398305f63a`
- Slice 1.7 代码完成 HEAD：
  `d6ae62f0b0413ce3ea499f3bb0f221520ab43c1d`
- 比较范围：`a5f510f..d6ae62f`

Slice 1.7 本地提交：

```text
e67eb37 feat(intent): plan skin revision followups
e1fa3d0 feat(application): stream skin revision recommendations
74d1a94 feat(api): route skin revision followups
d6ae62f fix(guide): resolve slice 1.7 review findings
```

## RED / GREEN

### Task 1：理解与规划合同

- RED：新增六种明确肤质、模糊/症状/复合表达、完整品类优先级、严格
  draft/plan 合同和 query context 继承测试；基线缺少 parser、draft、planner
  与公开导出，测试按预期失败。
- GREEN：`e67eb37` 实现 `SkinRevisionDraft`、精确 parser、
  `SkinRevisionPlan` 和只替换 skin 的规划器；保留 category、budget、
  efficacy、exclusions。

### Task 2：完整重筛与状态

- RED：新增 missing snapshot、stale version、模糊/复合修改、零候选、
  presentation error、CAS conflict、修改后序号追问测试；基线没有肤质修改
  编排和原子状态提交，测试按预期失败。
- GREEN：`e1fa3d0` 接入完整 retrieval、decision、presentation 重跑；
  成功结果升至 version 2，失败路径保持最近有效快照，“第二款呢”读取新快照
  并升至 version 3。

### Task 3：正式 API 与浏览器

- RED：新增 Guide owner 分流、正式/runtime HTTP 共用 matrix、version 0
  旧会话边界和真实 Playwright SSE 轮次断言；基线缺少肤质修改正式路由与
  浏览器闭环。
- GREEN：`74d1a94` 完成正式 API/runtime 接线和浏览器门禁；
  `d6ae62f` 为首轮 review 的四项 finding 补回归并修复。最终 focused
  `152 passed`。

## 最终门禁

修复后全部命令重新执行，没有复用首轮结果：

- focused skin + API + runtime + frontend：
  `152 passed in 5.14s`
- Guide 全量：`528 passed in 7.09s`
- runtime 全量：`35 passed in 2.35s`
- backend CSV：`8/8` case 完整匹配
- `app/guide` boundary：0 violations
- `app/guide_runtime` boundary：0 violations
- `python3 -m compileall -q app/guide app/guide_runtime`：PASS
- `git diff --check a5f510f..d6ae62f`：PASS
- 正常 Playwright：PASS
- 对抗 Playwright：4/4 PASS
- 结束清理：0 个 Uvicorn/pytest/Playwright/Chromium 匹配进程，
  端口 8765 无 listener

逐命令结果见：

```text
docs/audits/slice1.7/test_evidence.csv
docs/audits/slice1.7/gate_report.md
```

## 浏览器三轮

1. Task 3 开发轮：
   `/tmp/xiaoro-slice17-task3-browser.png`，真实三轮肤质修改链通过；
   SHA-256
   `4e3559af4e7386d533b244b00beed17ad29006fa340ff3c091edd5b15a933d75`。
2. 首次完整门禁轮：
   `/tmp/xiaoro-slice17-final-browser.png`；focused `142`、Guide `518`、
   runtime `33`，正常/对抗 Playwright 均通过；SHA-256
   `dbc52de11ed6585fa67823f64f11d79827cc4cb267ff93ea03fbf55c104e9c01`。
3. review 修复后二次门禁轮：
   `/tmp/xiaoro-slice17-final-browser-rerun.png`；修复后全部门禁重跑，
   正常链和 4/4 对抗场景通过，0 page errors、0 失败商品图、0 SSE parse
   errors；截图 `1440x1000`、`203863` bytes，SHA-256
   `149a5dcb7ad999f55a07cc01bd819a303eb3258059db5380dc0bf398606f69de`。

最终正常链证明：

- “500 元内修护精华”：
  `[91, 38] / SELECTED / version 1`
- “改成敏感肌呢”：
  `[91, 38] / INSUFFICIENT_FOR_WINNER / version 2`
- “第二款呢”：
  `[38] / version 3`，使用新快照且不重新召回

## 首轮 Review 与修复

首轮 full-file review：

```text
/tmp/xiaoro-fresh_slice17_review/report.md
/tmp/xiaoro-fresh_slice17_review/report.html
```

报告发现 `1 P0 + 2 P1 + 1 P2`：

- P0：客户端可控、低熵 session ID 与 version 可被复用来访问并推进其他
  process-local 快照。修复为浏览器 `crypto.randomUUID()`，并提供
  `crypto.getRandomValues()` 的 UUID v4 fallback；新增 256 次双路径唯一性
  与格式回归。
- P1：多肤质别名句会按词表顺序选到旧肤质。修复为完整匹配
  “从 `<旧肤质>` 改/换成 `<新肤质>`”，只提取修改动词后的目标。
- P1：一般“那敏感肌适合用什么呢”被误判成肤质修改。修复为仅接受完整
  “那 `<肤质>` 呢”省略式修改，一般问句不被该分支接管。
- P2：runtime `/health` 未声明 `skin_revision_followup`。能力列表和 HTTP
  合同已同步修复。

修复提交为 `d6ae62f`。修复后 focused 从 `142` 增至 `152`，Guide 从
`518` 增至 `528`，runtime 从 `33` 增至 `35`。

## 二次独立 Review

结论：**PASS: no unresolved P0-P2**。

- 覆盖：`10/10` 文件
- 变更：`635` 行
- review 验证：`123 tests`
- 报告：
  - `/tmp/xiaoro-fresh_second_review_1786167722/report.html`
  - `/tmp/xiaoro-fresh_second_review_1786167722/report.md`

## Token 检查点

根 `get_goal` 权威返回保持：

- `goal_id=6a76acf2a50b6afe00c97e8c`
- `tokens_used=0`

`docs/audits/slice1.7-to-2.0/token_usage.csv` 已按 append-only 追加
`SLICE_1_7_COMPLETE` 和 `SLICE_1_8_START`；两个检查点的
`cumulative_tokens=0`、`stage_delta=0`，HEAD 均为代码完成点
`d6ae62f0b0413ce3ea499f3bb0f221520ab43c1d`。

## 保护值

- 排序内核 SHA-256 保持：
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`
- `data/canonical/**`、`app/services/**`、`app/database/**` 和排序内核
  相对 `a5f510f` 均无变更。
- 旧仓库保持 HEAD
  `8658e191c05e208b2939aa37fb1ee170b2784e4f`，状态前后 SHA-256 保持
  `579295a4f4dce036e959e9519c5be1aa8e706ae161ffe48a71e1ea473c34a96a`。
- 未 push、发布、部署、联网下载模型或切换生产流量。
- 4 个遗留 Slice 1.6 worktree 未继续开发或删除。

## 残余风险

Guide conversation state 和 session locks 仍是 **process-local**。当前门禁
明确以 Uvicorn `--workers 1` 运行；多 worker 或进程重启会丢失/分裂状态。
在引入共享、带所有权的持久状态前，预生产必须继续保持 single-worker。

## 下一任务

自动进入但尚未执行：

`Task 4: 执行 Slice 1.8 verified-absence 事实审计`

该任务先只读盘点 Canonical、审核决定和正式来源，生成结构化候选事实或
NO-GO 证据；未经用户明确批准，不修改 Canonical、不开放成分排除成功能力。
