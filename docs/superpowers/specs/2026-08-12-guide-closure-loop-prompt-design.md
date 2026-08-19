# Guide Closure Loop Prompt Design

## Goal

新增一份当前 checkpoint 专用的 `/ralph-loop` 续跑 Prompt，引导执行者从
Task 6.5 继续完成 Guide closure，同时避免重复正式审计、缺 Key 空转和无监管长进程。

## Current Authority

- 实施仓库：`/Users/bytedance/Desktop/xiaoro-fresh`
- 分支：`rebuild`
- 生成设计时 HEAD：`cd99287176684d1c357b319624f5651ed0123b5f`
- 剩余实施计划：
  `docs/superpowers/plans/2026-08-12-guide-closure-remaining-execution.md`
- 开场正式审计已经执行：
  - audit key:
    `b874c83c4f79b594a80de475b9a353755b27a9b90e7dd03a743e392aad40d0da`
  - invocation: `1`
  - repeat: `0`
  - ledger: `docs/audits/guide-closure/audit_ledger.csv`

用户要求的“开始时审计一次，之后不重复”已经由上述历史事实满足。新 Prompt 只读取
ledger 核验，不调用任何 audit 工具，不创建新 audit key，也不以“复审”或“final
audit”等名称重复执行。

## Prompt Strategy

采用新增 checkpoint Prompt，不覆盖
`2026-08-11-guide-closure-resume-after-strict-audit.md`。新文件只描述当前恢复点和剩余
执行规则，权威产品语义继续由已有 spec、tasks、checklist 和剩余实施计划拥有。

Prompt 开始时依次检查：

1. 当前目录是 `xiaoro-fresh`，不是旧 `xiaoro-shopping-master`。
2. 分支为 `rebuild`，工作区没有未理解的修改。
3. HEAD 是当前 checkpoint 的严格后继。
4. audit ledger 仍只有唯一 audit key，invocation 为 1。
5. 没有遗留 pytest、Playwright、Uvicorn 或 A/B runner 进程。
6. `GUIDE_LLM_API_KEY` 只检查 PRESENT/MISSING，不读取值。

## Missing-Key Behavior

若 Key 为 MISSING：

- 输出一次当前阻塞状态；
- 不运行测试、网络、浏览器或实现任务；
- 不追加重复 Round/progress blocker；
- 不提交空 checkpoint；
- 立即结束当前循环。

Key 恢复后重新运行同一 Prompt，从 Task 6.5 开始。

## Execution Order

Key 为 PRESENT 时严格串行执行：

```text
Task 6.5-6.7 真实双模型 A/B
-> Task 8 Guide-only 与澄清状态
-> Task 11 旧链依赖证明和物理删除
-> Task 12 全量/状态/浏览器/模型门禁
-> Task 13 最终证据与状态收口
```

任何前置未通过时禁止进入下一阶段。

## Long-Process Control

- 同时最多一个 heavy process。
- 每 30 秒检查输出和 OS 进程状态。
- 每个长任务必须有硬超时。
- 超时后先 TERM，仍存活才 KILL，并复核 PID 退出。
- 不用重复 broad suite 诊断一个失败。

## Repair Discipline

失败按以下顺序冻结 typed evidence：

```text
exact
-> semantic
-> merger
-> TaskPlan
-> RetrievalResult
-> DecisionResult
-> ResponsePlan/SSE
-> conversation state
```

只在最早失败层写 RED 和通用修复。禁止：

- 单句关键词/正则补丁；
- API、Presenter、前端重解释意图；
- retrieval/presentation 二次选 winner；
- 修补或复制待删除的旧 `app/services/**`；
- 修改 expected 掩盖生产行为；
- 用 UNAVAILABLE 或常量零冒充真实 hard gate。

## Stop Conditions

仅在以下情况停止：

- fresh Key 缺失；
- 双模型经过最多三轮通用修复仍未通过；
- Task 8 完整门禁未通过；
- legacy runtime/background importer 非零；
- 保护资产 hash 漂移；
- 需要 push、deploy、生产切流或破坏性数据操作。

普通 RED/GREEN、focused verification、提交和 checkpoint 不等待用户确认。

## Acceptance

生成的 Prompt 必须：

- 明确禁止 Task 0 和第二次正式审计；
- 引用当前剩余实施计划；
- Key 缺失时单次报告并退出；
- Key 存在时从 Task 6.5 自动推进；
- 保留 30 秒进程审计和硬超时；
- 禁止提前 Task 8、Task 11；
- 最终要求 tasks/checklist 全勾选、工作区干净；
- 保持未 push、未 deploy、未切流。
