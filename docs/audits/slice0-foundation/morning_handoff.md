# Slice 0 Contract Foundation Morning Handoff

## 最重要结论

Task 11 已修复最终证据的可复现性。旧仓库 parity 均从
`/Users/bytedance/Desktop/xiaoro-fresh` 调用旧 `.venv/bin/pytest` 现场执行，
分别得到 ranking `13 passed` 和 tooling `88 passed`；新仓库最终组合门禁为
`244 passed / 0 failed`。独立验收确认全部 52 项 checklist 重新审计通过。
Task 11 与 Task 10（含 10.4、10.5）均已最终完成；Task 11 docs 修复提交为
`72bb9d73246bb506fe8ca0a45e9e5b0718f782fb`。

## Completed

- 建立 understanding、intent、retrieval、decision、presentation、feedback
  六层严格公开合同及薄 application/adapters 外壳。
- 建立 AST 边界、只读 Canonical reader、deterministic ranking kernel、
  sealed evidence audit tooling 和严格 LLM cache contracts。
- 使用旧仓库声明环境重跑 ranking/tooling source parity，修正旧证据中的
  pytest 可执行文件、cwd、warning 数和结果描述。
- 重跑组合门禁、分项测试、边界检查、来源 SHA、受保护路径和 Git 当前状态
  检查。
- 明确 no-push 的证据边界，不再用 Git 当前状态推导历史行为。
- 完成 Task 10 与 Task 11 最终勾选和独立 52/52 checklist 验收。

## Local Commits

Task 1 至 Task 9 共 10 个本地实施提交：

- `9afb5a9` feat(guide): establish package layout
- `53ee1ac` feat(decision): preserve deterministic ranking kernel
- `6af596c` feat(llm): define cache identity contracts
- `02b4380` feat(architecture): enforce guide boundaries
- `b49132a` feat(guide): define public layer contracts
- `4e89a77` feat(application): define orchestrator protocol
- `8b16a87` feat(tools): seal evidence audit modules
- `8c90cee` feat(catalog): add canonical product reader
- `646904b` feat(llm): bind cache entries to validated schemas
- `0f8a3bf` fix(llm): require target schema type for cache entries

初始文档提交为 `41304b9`。Task 11 使用独立本地 docs 修复提交
`72bb9d73246bb506fe8ca0a45e9e5b0718f782fb` 收口。当前交接状态由本次最终
本地 docs commit 承载；为避免提交自引用，本文件不记录该最终提交的 SHA。

## Evidence

- `test_evidence.csv` 记录 Task 11 现场命令、cwd、可执行文件、通过数、失败数
  和状态。
- `stale_guide_inventory.csv` 留存旧空骨架路径和 SHA。
- `evidence_audit_source_manifest.csv` 含 23 条来源记录；本轮逐行复核
  23 个 source SHA 和 20 个 target SHA，全部一致。
- 新旧 deterministic ranking 文件 SHA-256 均为
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`。

## Verification Results

- 新仓库组合门禁：`244 passed / 0 failed`，`1.01s`。
- `tests/guide`：`154 passed / 0 failed`，`0.71s`。
- `tests/tools/evidence_audit`：`88 passed / 0 failed`，`0.24s`。
- `tests/slice0`：`2 passed / 0 failed`，`0.35s`。
- 真实 `app/guide` AST boundary check：PASS。
- 新仓库 deterministic ranking：`13 passed / 0 failed`，`0.08s`。
- 旧仓库 deterministic ranking parity：`13 passed / 0 failed`，
  `4 warnings`，`6.30s`。
- 旧仓库 evidence audit tooling parity：`88 passed / 0 failed`，
  `4 warnings`，`2.90s`。
- `git diff --check 73b3481..HEAD`、当前工作树 `git diff --check`、旧 V1/V2
  import 扫描和受保护路径差异检查均通过。
- checklist 逐项复核：`52 / 52 PASS`。

旧 tooling 源测试使用 cwd 相对路径
`tests/fixtures/shadow_evidence`。可复现命令先在新仓库创建临时只读 symlink
指向旧仓库 source fixtures，并用 shell `trap` 清理；pytest 进程 cwd 始终为
`xiaoro-fresh`，旧仓库未写入 cache 或 bytecode。

## Protection State

- 旧仓库 HEAD 保持
  `8658e191c05e208b2939aa37fb1ee170b2784e4f`。
- 旧仓库状态 SHA 保持
  `be35dbe626b26a65c8cff09d594aba2e4540f9f8f9e55a3d5fe0a1783c9f4d8c`。
- 相对 `73b3481`，`app/static/chat.html`、`app/api/v1/chat.py` 和
  `data/canonical/` 无差异。
- Git 当前状态证据显示：不存在 `origin/rebuild`，`rebuild` 无 upstream，
  无 remote ref contains 当前 HEAD，`origin/main` 保持
  `7cb6b25c9c33009cea901763d59b8ffa36473efc`。

以上 Git 项只证明检查时的当前引用和跟踪状态，不能证明历史上从未发生 push。
Task 11 本轮实际命令审计未出现 `git push` 或其他远端写命令；no-push 声明仅限
这一可观察的本轮命令范围。

## Deferred/Risks

- 新仓库没有 `.venv`；其门禁运行于 Pydantic 2.13.4，而
  `requirements.txt` 锁定 2.8.0。旧 parity 已在旧 `.venv` 的 Pydantic 2.8.0
  执行，但这不等于新仓库全量门禁已在 2.8.0 复验。
- Slice 1 不属于本轮范围；未提前实现文本推荐闭环、OCR、CLIP、向量 adapter、
  反馈学习或旧 runtime/cache 迁移。

## Next Step

独立规划 Slice 1；本轮不提前实现 Slice 1 功能。

## Workspace State

- 工作区：`/Users/bytedance/Desktop/xiaoro-fresh`
- 分支：`rebuild`
- Task 11 开始前 HEAD：
  `41304b9a8bca617efc27e2c9c151a23bc2dad383`
- Task 11 docs 修复提交：
  `72bb9d73246bb506fe8ca0a45e9e5b0718f782fb`。
- 最终收口修改 `morning_handoff.md`、忽略目录中的 `tasks.md` 和
  append-only `progress.md`；`checklist.md` 保持 52 项原文不变。
- 本次最终本地 docs commit 仅承载 tracked `morning_handoff.md`，本文件不
  自引用该提交 SHA；生产代码、测试、旧仓库和受保护路径未修改。
- 当前无 upstream；Task 11 与最终收口的可观察命令审计未出现 push。

## 2026-08-07 状态更正

- `tools/evidence_audit/` 及其 parity tests 已在逻辑审计后删除。
- 旧文中的 `244 passed` 是删除前的历史门禁，不代表当前树。
- 当前正式地基门禁使用 `pytest-guide.ini`，覆盖 `tests/guide` 与
  `tests/slice0`；实际数量以本次命令输出为准。
- 删除原因与保留资产见
  `docs/audits/slice0-foundation/evidence_audit_removal.md`。
