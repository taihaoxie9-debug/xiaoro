# Phase 2 Audit Idempotency and Agent Token Telemetry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every Phase 2 capability loop perform at most one opening full-file audit, prevent equivalent integration commits, and add honest Agent token cache/cost telemetry.

**Architecture:** The authoritative spec and Ralph plan define an audit key based on file blobs and audit profile rather than commit SHA. Two append-only CSV ledgers persist audit reuse and provider token usage, while the resume prompt bootstraps existing worktree evidence and continues unattended work without audit retry loops.

**Tech Stack:** Markdown execution contracts, append-only CSV ledgers, Git blob SHA/stable patch ID, Goal/provider usage telemetry.

---

## File Map

Modify:

- `.trae/specs/complete-phase2-continuously/spec.md` - normative audit, commit, unattended, and token telemetry requirements.
- `.trae/specs/complete-phase2-continuously/tasks.md` - executable subtasks for the new standard.
- `.trae/specs/complete-phase2-continuously/checklist.md` - completion assertions.
- `.trae/specs/complete-phase2-continuously/progress.md` - append-only standard amendment record.
- `docs/superpowers/plans/2026-08-09-phase2-continuous-ralph.md` - operational loop rules.

Create:

- `docs/audits/phase2-continuous/audit_ledger.csv` - append-only audit invocation/reuse ledger.
- `docs/audits/phase2-continuous/agent_token_usage.csv` - append-only provider usage and cache ledger.
- `docs/superpowers/prompts/2026-08-09-phase2-continuous-resume.md` - restart prompt.

## Task 1: Add Normative Audit and Token Requirements

**Files:**
- Modify: `.trae/specs/complete-phase2-continuously/spec.md`
- Modify: `docs/superpowers/plans/2026-08-09-phase2-continuous-ralph.md`

- [ ] **Step 1: Add the audit idempotency requirement to the spec**

Insert under `## ADDED Requirements`:

```markdown
### Requirement: 审计幂等与单轮唯一审计

每个能力循环 SHALL 只在开头执行一次 full-file audit。审计身份 SHALL
由 audit profile version 和排序后的 scope file blob SHA-256 决定，不得由
commit SHA、branch、worktree 或会话 ID 决定。

#### Scenario: 相同内容已审计通过
- **WHEN** 当前 scope manifest 与已有 PASS 的 audit key 相同
- **THEN** 记录 REUSED_PASS，不再调用审计器

#### Scenario: 审计发现问题
- **WHEN** 开头审计产生确认 finding
- **THEN** 先建立 RED，再修复并运行 focused/boundary/HTTP/browser 门禁；同一循环不得再次 full-file audit

#### Scenario: 审计器不可用
- **WHEN** 独立审计器失败、超时或不可用
- **THEN** 同一 audit key 只记录一次 LOCAL_BASELINE_ONLY，主线程完成一次有界基线检查并继续所有可运行任务，不等待用户在线

#### Scenario: 最终收口
- **WHEN** 全部能力已集成并进入最终收口
- **THEN** 建立唯一 FINAL-PHASE2-AUDIT 循环并执行一次独立 full-file audit
```

- [ ] **Step 2: Add duplicate commit prevention**

Insert immediately after the audit requirement:

```markdown
### Requirement: 等价提交去重

集成前 SHALL 比较 stable patch ID 与最终 production blob manifest。已集成
的等价 patch/blob SHALL 记录 INTEGRATION_REUSED，不得再次 cherry-pick、
amend 或创建语义等价提交。
```

- [ ] **Step 3: Add Agent token telemetry**

Insert immediately after duplicate commit prevention:

```markdown
### Requirement: Agent Token 缓存与成本遥测

每个 checkpoint SHALL 记录平台真实提供的 cumulative、prompt、output、
cache read 和 cache write tokens。只有模型、usage 语义和价格快照齐全时
才计算命中率与成本；缺失字段 SHALL 写 UNAVAILABLE，不得估算或反推。

历史 Slice 1.7-2.0 的 26,788,605 tokens 保持权威总量，其缓存与成本拆分
SHALL 标记 UNAVAILABLE。
```

- [ ] **Step 4: Add the operational policy to the Ralph plan**

Add a new `## 1A. Audit Idempotency and Telemetry` section after continuous
execution rules. It must state:

```markdown
- one opening full-file audit per capability loop;
- audit reuse by audit profile + sorted file blob hashes;
- no review-fix re-audit inside the loop;
- tests and normal gates verify fixes;
- one final independent audit;
- one unavailable-auditor record per key, then continue;
- stable patch-id/blob checks before integration;
- one Agent token ledger row per checkpoint;
- UNAVAILABLE for missing cache/model/pricing telemetry.
```

- [ ] **Step 5: Remove the conflicting final re-audit wording**

Change the final audit section from:

```text
Every confirmed P0–P2 requires a RED test, fix, and complete gate rerun.
```

to:

```text
Every confirmed P0–P2 requires a RED test, fix, and complete gate rerun.
Do not run a second full-file audit after those fixes in the same final loop.
```

- [ ] **Step 6: Validate the normative documents**

Run:

```bash
rg -n "单轮唯一审计|REUSED_PASS|LOCAL_BASELINE_ONLY|FINAL-PHASE2-AUDIT|INTEGRATION_REUSED|cache read|UNAVAILABLE" \
  .trae/specs/complete-phase2-continuously/spec.md \
  docs/superpowers/plans/2026-08-09-phase2-continuous-ralph.md
git diff --check
```

Expected: every required term is present and `git diff --check` exits `0`.

## Task 2: Make the Rules Executable and Checkable

**Files:**
- Modify: `.trae/specs/complete-phase2-continuously/tasks.md`
- Modify: `.trae/specs/complete-phase2-continuously/checklist.md`

- [ ] **Step 1: Add Task 5 audit and commit-dedup subtasks**

Append these subtasks under Task 5:

```markdown
  - [ ] SubTask 5.7: 每个 capability loop 冻结 capability_key、iteration_id、scope manifest 和 audit profile
  - [ ] SubTask 5.8: 开头最多调用一次 full-file audit；相同 audit key 复用 PASS
  - [ ] SubTask 5.9: finding 修复只用 RED/GREEN 与正常门禁验证，不在同一循环重复审计
  - [ ] SubTask 5.10: cherry-pick 前比较 stable patch ID 和 final blob manifest，跳过等价提交
  - [ ] SubTask 5.11: 审计器不可用只记录一次并继续其他独立工作
  - [ ] SubTask 5.12: 每个 checkpoint 追加 Agent token ledger；audit ledger 仅在首次调用、复用或状态变化时追加
```

- [ ] **Step 2: Narrow Task 8 final review**

Change Task 8.5 to:

```markdown
  - [ ] SubTask 8.5: 在唯一 FINAL-PHASE2-AUDIT 循环对最终生产文件执行一次独立 full-file review
```

Change Task 8.7 to:

```markdown
  - [ ] SubTask 8.7: 修复后重新执行 SubTask 8.1–8.4，不重复 full-file review
```

- [ ] **Step 3: Add checklist assertions**

Append:

```markdown
- [ ] 每个 capability loop 只有一次真实 full-file audit invocation
- [ ] 相同 audit profile 与 blob manifest 复用已有 PASS
- [ ] finding 修复没有触发同循环第二次 full-file audit
- [ ] 审计器不可用未导致重复重试或等待用户在线
- [ ] 等价 stable patch ID/blob manifest 未产生重复集成提交
- [ ] 最终收口只有一个 FINAL-PHASE2-AUDIT
- [ ] 每个新 checkpoint 均记录 Agent token cache 字段或明确 UNAVAILABLE
- [ ] Token 成本只使用真实 usage、明确模型和带日期价格快照
```

- [ ] **Step 4: Validate task wording**

Run:

```bash
test "$(rg -c "full-file (audit|review)" .trae/specs/complete-phase2-continuously/tasks.md)" -ge 3
rg -n "SubTask 5\\.(7|8|9|10|11|12)|FINAL-PHASE2-AUDIT|UNAVAILABLE" \
  .trae/specs/complete-phase2-continuously/tasks.md \
  .trae/specs/complete-phase2-continuously/checklist.md
git diff --check
```

Expected: all new subtasks and assertions are present; diff check passes.

## Task 3: Create the Append-Only Ledgers

**Files:**
- Create: `docs/audits/phase2-continuous/audit_ledger.csv`
- Create: `docs/audits/phase2-continuous/agent_token_usage.csv`

- [ ] **Step 1: Create the audit ledger header**

Use exactly:

```csv
timestamp,goal_id,capability_key,iteration_id,audit_key,audit_profile_version,scope_manifest_sha256,source_commit,result,reused_from_audit_key,finding_counts,evidence_path,notes
```

- [ ] **Step 2: Create the Agent token ledger header**

Use exactly:

```csv
timestamp,goal_id,iteration_id,event,cumulative_tokens,prompt_tokens_total,prompt_uncached_tokens,cache_read_tokens,cache_write_tokens,output_tokens,cache_hit_rate,model,pricing_snapshot,estimated_cost,telemetry_source,status
```

- [ ] **Step 3: Add the historical authoritative row**

Append:

```csv
2026-08-08T16:01:33Z,6a76acf2a50b6afe00c97e8c,slice1.7-to-2.0-final,FINAL_AUDIT_COMPLETE,26788605,UNAVAILABLE,UNAVAILABLE,UNAVAILABLE,UNAVAILABLE,UNAVAILABLE,UNAVAILABLE,UNAVAILABLE,UNAVAILABLE,UNAVAILABLE,update_goal,PARTIAL_TELEMETRY
```

- [ ] **Step 4: Validate both CSV schemas**

Run:

```bash
test "$(head -1 docs/audits/phase2-continuous/audit_ledger.csv | awk -F, '{print NF}')" = "13"
test "$(head -1 docs/audits/phase2-continuous/agent_token_usage.csv | awk -F, '{print NF}')" = "16"
test "$(tail -1 docs/audits/phase2-continuous/agent_token_usage.csv | awk -F, '{print NF}')" = "16"
rg -n "26788605.*UNAVAILABLE.*update_goal.*PARTIAL_TELEMETRY" \
  docs/audits/phase2-continuous/agent_token_usage.csv
```

Expected: all commands exit `0`.

## Task 4: Add Resume Prompt and Progress Evidence

**Files:**
- Create: `docs/superpowers/prompts/2026-08-09-phase2-continuous-resume.md`
- Modify: `.trae/specs/complete-phase2-continuously/progress.md`

- [ ] **Step 1: Write the resume prompt**

The prompt must explicitly:

```text
target /Users/bytedance/Desktop/xiaoro-fresh
resume existing phase2-integration without discarding its four dirty files
read the approved audit-idempotency design and authoritative standard from rebuild
bootstrap existing review evidence instead of re-auditing identical blobs
run no more than one opening full-file audit for any genuinely new capability loop
verify fixes with RED/GREEN and normal gates
skip equivalent patch IDs/blob manifests
append one Agent token row at every checkpoint
append an audit row only for an invocation, reuse, or audit state change
record missing cache telemetry as UNAVAILABLE
continue while the user is absent
stop only on completion, a shared hard decision blocker, round limit, or explicit pause
never push, deploy, switch traffic, or modify protected paths
```

- [ ] **Step 2: Append the standard amendment progress entry**

Append a heading:

```markdown
## Execution Standard Amendment: Audit Idempotency and Agent Token Telemetry
```

Record:

- approved design commit `567aa33`;
- one opening audit per capability loop;
- final independent audit once;
- stable patch/blob commit deduplication;
- auditor-unavailable continuation behavior;
- historical cache fields unavailable;
- both ledger paths;
- no production code changes.

- [ ] **Step 3: Validate prompt completeness and progress append**

Run:

```bash
rg -n "phase2-integration|4 个未提交文件|开头一次|RED/GREEN|patch ID|blob manifest|UNAVAILABLE|继续|不 push" \
  docs/superpowers/prompts/2026-08-09-phase2-continuous-resume.md
rg -n "Execution Standard Amendment|567aa33|audit_ledger.csv|agent_token_usage.csv" \
  .trae/specs/complete-phase2-continuously/progress.md
git diff --check
```

Expected: all required continuation and evidence clauses are present.

- [ ] **Step 4: Commit the implementation**

Run:

```bash
git add \
  .trae/specs/complete-phase2-continuously/spec.md \
  .trae/specs/complete-phase2-continuously/tasks.md \
  .trae/specs/complete-phase2-continuously/checklist.md \
  .trae/specs/complete-phase2-continuously/progress.md \
  docs/audits/phase2-continuous/audit_ledger.csv \
  docs/audits/phase2-continuous/agent_token_usage.csv \
  docs/superpowers/plans/2026-08-09-phase2-continuous-ralph.md \
  docs/superpowers/prompts/2026-08-09-phase2-continuous-resume.md
git commit -m "docs(phase2): enforce idempotent audit telemetry"
```

- [ ] **Step 5: Fast-forward the authoritative branch**

Run from `/Users/bytedance/Desktop/xiaoro-fresh`:

```bash
git merge --ff-only phase2-audit-standard
git status --short
```

Expected: fast-forward succeeds and `rebuild` is clean.
