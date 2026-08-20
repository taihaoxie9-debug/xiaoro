# Guide 分品类数据地基自适应长循环 Prompt

以下内容可直接作为新的 Goal / Ralph Loop 启动提示。

---

在 `/Users/bytedance/Desktop/xiaoro-fresh` 连续完成 Guide Phase 3A
“分品类数据地基”。采用 2–8 个 Agent 自适应并发、单 Integration Writer、独立只读
审计。普通实现决策由系统按权威文档自行完成，不逐次等待用户。

## 权威文档

开始前必须完整读取：

```text
docs/superpowers/specs/2026-08-10-category-aware-guide-data-foundation-design.md
docs/superpowers/plans/2026-08-10-category-aware-guide-data-foundation.md
.trae/specs/complete-category-aware-guide-data-foundation/spec.md
.trae/specs/complete-category-aware-guide-data-foundation/tasks.md
.trae/specs/complete-category-aware-guide-data-foundation/checklist.md
.trae/specs/complete-category-aware-guide-data-foundation/progress.md
.trae/specs/complete-category-aware-guide-data-foundation/autonomous-execution-policy.md
docs/superpowers/specs/2026-08-06-xiaoro-clean-growth-architecture-design.md
docs/audits/phase2-continuous/final_handoff.md
```

发生冲突时优先级：

```text
用户最新明确指令
> autonomous-execution-policy.md
> category-aware design spec
> implementation plan
> cycle spec/tasks/checklist
> 旧 Phase 2 文档
```

## 机械起点核验

必须先运行：

```bash
cd /Users/bytedance/Desktop/xiaoro-fresh
git status --short --branch
git branch --show-current
git merge-base --is-ancestor a29d727 HEAD
git log -8 --oneline --decorate
```

要求：

```text
branch = rebuild
design commit a29d727 is an ancestor of HEAD
worktree clean
no cherry-pick/rebase/merge in progress
```

如果不满足：

1. 冻结现场；
2. 检查用户改动和未完成 Git 操作；
3. 不 reset、不 checkout 覆盖、不删除用户文件；
4. 只在确认安全后恢复；
5. 无法唯一恢复时升级用户。

## 已确认审计事实

```text
Canonical products: 103
Canonical raw categories: 39
Guide formal topics before Phase 3A: sunscreen, serum
Canonical fields per product: 13
known domain fields: 239 / 927 = 25.8%
review HTML candidates: 336
strict review candidates: 111
approved review sources: 6
approved review products: 42, 49, 55
opening findings: P0=0; P1=2; P2=1
opening report: docs/audits/category-data-foundation/opening_audit.md
opening focused verification: 52 passed
```

不得把 111 个严格候选表述为 111 个已批准评论。批准评论始终只有 6 条，除非存在新的
完整人工批准决定并通过 promotion 和审计。

当前可复验仓库和现存临时来源目录中没有三份原始评论 HTML。336/111 只能作为历史审计
provenance。没有重新取得并 hash 锁定原始 HTML 时，禁止宣称本轮真实重跑得到 336/111；
评论构建器先用提交的脱敏 fixture 验证确定性，并保证现有 6 条批准资产完全不变。

## 目标

连续完成：

1. 六个严格画像：
   `skincare/suncare/base_makeup/color_makeup/cleanser/fragrance`；
2. 39/39 Canonical 原始品类完整唯一映射；
3. 通用、专属和不适用字段合同；
4. 字段来源和 evidence/display/compare/hard_filter/soft_rank 权力边界；
5. 六类自然语言理解、task planning、召回、决策、展示和 owner；
6. 12 个固定试点；
7. 品类事实 pending/quarantine candidate builder；
8. 显式人工决定 category fact promotion；
9. 评论 HTML pending/quarantine builder；
10. 显式人工决定 review promotion；
11. 正式 HTTP/SSE/frontend 和浏览器闭环；
12. 全量门禁和唯一 `FINAL-CATEGORY-DATA-AUDIT`。

## 固定试点

```text
skincare: 38, 91
suncare: 53, 57
base_makeup: 79, 80
color_makeup: 86, 114
cleanser: 69, 103
fragrance: 120, 121
```

不得替换试点来绕过缺失字段。没有批准来源时保持 unknown。

## 保护路径

以下路径不得修改：

```text
app/services/**
app/database/**
data/canonical/**
app/guide/decision/deterministic_ranking.py
```

排序 SHA 必须保持：

```text
4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f
```

新 Guide 不得 import `app.services` 或 `app.database`。旧工作区
`/Users/bytedance/Desktop/xiaoro-shopping-master` 只能作为只读设计参考，不得复制或
同步其实现。

## 事实批准硬边界

自动化只能：

- 读取声明的原始来源；
- 生成 pending candidate；
- 规范化字段；
- 去重；
- 记录 conflict；
- 执行 PII/营销/Q&A quarantine；
- 生成审核队列；
- 验证已有人工决定；
- 原子构建批准资产。

自动化禁止：

- 把自己的候选标为 approved；
- 伪造 reviewer 或 reviewed_at；
- 用多数票解决事实冲突；
- 从评论推导配方、安全、verified absence；
- 从 OCR 成分表推导功效或安全；
- 为提高覆盖率填充猜测值；
- 用 unknown/conflict/not_applicable 改变 winner 或排序；
- 将营销文案作为硬筛事实。

如果 12 个试点没有新的完整人工决定，工具链和 unknown 覆盖可以完成，但不得创造
approved category fact。此时允许生成 `fact_count=0` 的合法 sidecar manifest，reader
必须正常加载，所有专属字段保持 unknown。受阻的数据批准线路暂停，合同、工具、路由、
测试和文档继续。

## 自适应并发

硬限制：

```text
active agents: 2..8
concurrent code writers: 0..4
integration writers: exactly 1 maximum
writers per file authority: exactly 1 maximum
independent read-only audit/verifier: at least 1
```

从 `HIGH_RISK` 启动，初始 6 个角色：

1. root orchestrator；
2. Integration Writer；
3. category contract writer；
4. data/review tooling writer；
5. routing/behavior writer；
6. independent auditor/verifier。

Category contracts 与 data tooling 文件域冻结、最近两个 checkpoint 绿色后可进入
`NORMAL`。增加并发优先增加只读 verifier，不增加共享文件 writer。

以下情况立即降至 2–3 个 Agent：

- 同文件或同 authority 双 writer；
- 39-category mapping 或字段 registry 冲突；
- candidate/approved/quarantine 数量不守恒；
- stable identity 内容冲突；
- focused 与 full 结果不一致；
- 保护路径或排序 SHA 漂移；
- 未批准字段改变 winner 或卡片；
- 浏览器状态串扰；
- P0/P1 audit finding；
- Agent 无法提供提交与证据映射。

固定处理流程：

```text
freeze -> reproduce -> RED -> single-writer fix -> independent verify
```

## Worktree 与写入所有权

从同一冻结 HEAD 创建独立 worktree：

```text
/private/tmp/xiaoro-category-contracts
/private/tmp/xiaoro-category-data-tools
/private/tmp/xiaoro-category-routing
/private/tmp/xiaoro-category-integration
```

只有 `/private/tmp/xiaoro-category-integration` 的 Integration Writer 可以修改：

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

Domain writer 只提交自己文件域的 self-contained commit。集成前比较 stable patch ID 和
production blob manifest；等价提交记录 `INTEGRATION_REUSED`，不重复 cherry-pick。

## 连续执行顺序

严格按 tasks 依赖执行：

```text
Task 1 baseline/audit
-> Task 2 category profiles
-> Task 3 field authority
-> Task 4 understanding/planning
-> Task 5 approved fact loader
-> Task 6 candidate builder
-> Task 7 explicit promotion
-> Task 8 twelve pilots
-> Task 9 Guide fact projection
-> Task 10 review rebuild/promotion
-> Task 11 formal integration/browser
-> Task 12 full verification/final audit
-> Task 13 closure
```

Task 2 与 Task 3 可并行。Task 5、6、10 在字段合同冻结后并行。任何线路阻塞时继续执行
不依赖该阻塞的任务。

每个能力执行：

```text
RED
-> confirm RED fails for intended reason
-> minimal implementation
-> focused GREEN
-> commit
-> integration
-> shared focused
-> browser when user-visible
-> tasks/checklist/progress checkpoint
-> continue
```

普通 checkpoint 不等待用户，不标记总体 COMPLETE。

## 测试门禁

Focused 使用仓库 Python 3.11，并严格执行 implementation plan 当前 Task 已列出的完整测试
文件命令。RED 阶段不得用整个目录代替当前 Task 的精确测试文件，避免无关收集错误掩盖
预期失败。

Full 和 runtime 使用批准的锁定组合环境：

```bash
UV_OFFLINE=1 uv run \
  --with-requirements requirements-guide-runtime-test.txt \
  python -m pytest -c pytest-guide.ini -q

UV_OFFLINE=1 uv run \
  --with-requirements requirements-guide-runtime-test.txt \
  python -m pytest -c pytest-guide.ini -q tests/guide/runtime
```

若离线缓存缺少锁定 wheel，记录 `ENVIRONMENT`，使用此前已批准且版本可打印的 combined
environment。禁止联网静默升级依赖。

静态与保护门禁：

```bash
python3 -m compileall -q app/guide app/guide_runtime tools/guide_data
python3 -m app.guide.check_boundaries app/guide
python3 -m app.guide.check_boundaries app/guide_runtime
git diff --check
git diff --exit-code a29d727 -- app/services app/database data/canonical \
  app/guide/decision/deterministic_ranking.py
shasum -a 256 app/guide/decision/deterministic_ranking.py
```

浏览器必须使用隔离端口、`0700` 状态目录和独立浏览器上下文，覆盖：

```text
normal text
six category profiles
adversarial category/field injection
review evidence
consultation/profile
single/two/four image
feedback
session switch and late event
```

要求：

```text
page errors = 0
console errors = 0
SSE errors = 0
unexpected HTTP 5xx = 0
failed product images = 0
cross-session leakage = 0
late-event pollution = 0
```

## 审计幂等

- 每个 capability loop 只执行一次 opening full-file audit。
- audit key = audit profile version + sorted production blob manifest。
- 相同 key 复用 PASS，不因 commit/worktree/session 改变重审。
- finding 必须写 RED；修复后跑正常门禁，不重复同 key full-file audit。
- 最终只执行一次独立 `FINAL-CATEGORY-DATA-AUDIT`。
- auditor 只读，不审查自己写的代码。

审计器不可用时，同一 key 只记录一次 `LOCAL_BASELINE_ONLY`，主线程做一次有界检查并继续
独立任务，不重复等待用户。

## 自治与升级

以下问题自行解决：

- import、类型、格式、fixture；
- exact duplicate；
- isolated port/state cleanup；
- 由 spec 唯一决定的别名优先级；
- promotion 临时文件清理；
- RED 唯一证明的局部回归；
- 加法式 tasks/checklist/progress 冲突。

只有以下情况升级用户：

- 需要改变六画像、字段语义或 12 试点；
- 需要用户批准新的事实或评论；
- 需要修改保护路径、Canonical 或排序；
- destructive migration；
- push、部署、切流；
- 隐私、合规或新外部凭证；
- 同一硬阻塞隔离后连续三次；
- 所有剩余工作共享同一个外部决策。

用户不在线时暂停受阻线，继续其他可运行任务。

## 完成条件

只有同时满足以下条件才可标记 `COMPLETE`：

```text
six profiles defined
39/39 raw categories uniquely mapped
field applicability and capability gates pass
12 pilots mechanically verified
category candidate builder reproducible on committed fixtures
category promotion atomic and human-decision-only
review builder reproducible on committed fixtures
historical 336/111 not misrepresented as a rerun
existing 6 approved reviews preserved
six formal Guide HTTP/SSE/browser paths pass
Guide full passes
runtime full passes
both boundaries pass
compileall and diff check pass
protected diff = 0
ranking SHA unchanged
all browser gates pass
FINAL-CATEGORY-DATA-AUDIT has no unresolved P0-P2
tasks and checklist all checked
worktree clean
```

始终保持：

```text
no push
no deployment
no traffic switch
```
