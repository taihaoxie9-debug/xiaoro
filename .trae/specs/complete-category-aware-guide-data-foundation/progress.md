# Progress

## Baseline

- Design commit: `a29d727` (`docs(guide): design category-aware data foundation`).
- Integration workspace: `/Users/bytedance/Desktop/xiaoro-fresh`.
- Branch: `rebuild`.
- Product baseline before Phase 3A: `4dda1ca`.
- Phase 2 product checkpoint: `ef66868`.
- Worktree status at design freeze: clean.

## Audit Facts

- Canonical products: `103`.
- Canonical raw categories: `39`.
- Guide formal topics before Phase 3A: `2` (`sunscreen`, `serum`).
- Canonical fields per product: `13`.
- Domain field known count: `239/927` (`25.8%`).
- Review HTML total candidates: `336`.
- Review strict candidates: `111`.
- Approved review sources: `6`.
- Approved review product coverage: products `42`, `49`, `55`.
- Approved review product coverage rate: about `2.9%`.
- The three original review HTML files are not present in the current
  reproducible repository or surviving temporary source directories.
- `336/111` is historical audit provenance, not a result rerun in this cycle.
- Opening audit findings: `P0=0; P1=2; P2=1`.
- Opening audit report:
  `docs/audits/category-data-foundation/opening_audit.md`.
- Opening focused verification: `52 passed`.

## Approved Scope

- Six category profiles.
- Full 39-category unique mapping.
- Strict category field authority.
- Twelve fixed pilot products.
- Category fact candidate builder and explicit promotion.
- Review candidate builder and explicit promotion.
- Formal Guide HTTP/SSE/frontend integration.
- Dynamic 2–8 Agent execution with one Integration Writer.
- Unique final independent audit.

## Explicit Non-Goals

- No one-shot completion of all 103 products.
- No automatic approval of HTML/OCR/review candidates.
- No Canonical v1 edits.
- No legacy implementation copy.
- No full release hardening or visual redesign in this loop.
- No push, deployment, or traffic switch.

## Checkpoint Log

Detailed implementation checkpoints are recorded in
`docs/audits/category-data-foundation/progress.md`.

## Round 3

- Phase 3A production checkpoint:
  `4206f45f5b0c4738c2592dc4d0115f947266132b`.
- Six profiles and all `39/39` Canonical raw categories are mapped
  fail-closed. The fixed twelve pilots remain
  `38,91 / 53,57 / 79,80 / 86,114 / 69,103 / 120,121`.
- Category facts remain honest:
  `fact_count=0`, `approved=0`, `unknown=114`, `conflict=0`.
  Candidate fixture output remains `7 pending + 12 quarantine`, with no
  automated approvals.
- Review fixture output remains `2 pending + 4 quarantine`,
  `provenance_status=fixture_only`; historical `336/111` remains
  `not_rerun`. The six approved review sources covering products
  `42,49,55` remain byte-for-byte unchanged.
- The dedicated two-image browser gate now submits and validates both
  `compare` and `negative_feedback` against the end-version feedback target.
  The final seven browser shards passed with zero page, console, SSE, HTTP
  5xx, image, cross-session, late-event, or XSS errors.
- The unique `FINAL-CATEGORY-DATA-AUDIT` ran once at frozen production
  checkpoint `5983350`, audit key
  `1b3611b13ef377099ee008cdbcb30f950797fadc09d4b025a0fb24f44c6181c7`.
  It found `P0=0;P1=1;P2=1` in review promotion. RED was
  `28 failed, 1 passed`; single-writer fix `4206f45` added externally locked
  decisions, detached HMAC authorization, immutable sources/audit
  generations, and one atomic manifest pointer. Targeted independent
  verification cleared the findings with `P0=0;P1=0;P2=0`; the same
  full-file audit was not repeated.
- Final normal gates after the audit fix:
  focused `120 passed`, Guide full `2511 passed` with one existing Pydantic
  warning, runtime full `155 passed`, compileall PASS, both boundaries PASS,
  protected diff empty, and ranking SHA-256
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`.
- Final evidence:
  `/private/tmp/xiaoro-phase3a-task12-postaudit-4206f45`.
  Browser evidence manifest SHA-256:
  `2743047e89db7727346a1cbb666885a190365735bcb6ba726cc85d5fefb23303`.
  Post-fix production blob manifest SHA-256:
  `7e6579a578270fa58370d2e082569c179590fd03f0147c0cda1ff00955450a0b`.
- Phase 3A is `COMPLETE`. No push, deployment, traffic switch, protected-path
  modification, or automated data approval was performed.

## Round 4

- **结论**: FAIL
- **审查范围**: 六画像与 39/39 映射、字段/资产合同、品类与评论候选及 promotion、12 试点、理解/路由、HTTP/SSE/前端、Guide/runtime 全量、静态保护和浏览器矩阵
- **验证结果**:
  - 构建/运行时: FAIL；compileall、双 boundary、diff/protected-path、排序 SHA 和七个隔离浏览器 shard 均通过，但非法 category payload 运行时探针确认卡片被拒绝后 conversation version 仍从空值推进到 1
  - 测试/覆盖: FAIL；focused `232 passed`、Guide full `2511 passed, 1 warning`、runtime full `155 passed`，但五个范围内对抗探针失败；锁定 `uv` 离线命令因缺少 Pillow CPython 3.12 wheel 记为 `ENVIRONMENT`，随后使用已批准 Python 3.11 combined environment 完成全量
  - 清单审计: 77/82 通过，5 项失败
- **风险与问题**: 5 个 P1：候选解析可与记录的 source SHA 脱钩；manifest swap 后目录 fsync 失败会以失败返回但生产指针已变化；带修饰语的并列否定误恢复后一个品类；非法品类 payload 在展示校验前提交会话版本/反馈状态；追问、修订和图片 intent 缺少 category_profile 时会静默丢失卡片品类事实，其中真实追问已复现 1 张卡、0 个品类事实块

## Round 7

- **最终生产代码 checkpoint**:
  `098be5a5ce4a7b9beb2a05babb557662a394dfe9`。
- **Task 14–22**:
  Task 14 来源字节绑定 `ffd41a4`；Task 15 fsync recovery
  `95bc7ba`；Task 16 修饰语并列否定 `c854ba6`；Task 17 文本/图片
  precommit validation `966bedd`、`d568ce0`；Task 18 追问、修订和图片卡片
  `9bb991f`；Task 19 正向转折 `35120f5`；Task 20 终态交付演进
  `2f21151`、`06d7ea5`、`be5263e`、`6dcb668`、`098be5a`；
  Task 21 四种明确正向转折 `bee11b3`；Task 22 products typed 整体等价
  校验 `1088fd7`。九项均完成。
- **聚焦与全量验证**:
  candidate builder `68 passed`，其中精确竞态节点 `3 passed`；最终聚焦
  执行合计 `776` 次、`0 failed`（`574 + 123` formal router +
  `79` runtime 精确）。权威 full 证据位于
  `/private/tmp/xiaoro-authoritative-full-final-098be5a/summary.txt`：
  Guide `2619 passed`、`1` 个既有 Pydantic warning，Runtime
  `187 passed`，合计 `2806 passed`。使用
  `/private/tmp/xiaoro-guide-runtime-venv/bin/python`（Python `3.11.1`，
  pytest `8.0.0`）。锁定 `UV_OFFLINE` 命令因缺少 Pillow `10.4.0`
  CPython `3.12` arm64 wheel 分类为 `ENVIRONMENT`，不宣称通过；经批准的
  Python 3.11 环境完成权威 full。
- **静态与保护门禁**:
  compileall、`app/guide` boundary、`app/guide_runtime` boundary 和
  `git diff --check` 均 PASS；相对 `a29d727`、`a88d8af` 的 protected
  diff 均为空。排序 SHA-256 保持
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`。
- **浏览器验证**:
  `/private/tmp/xiaoro-phase3a-authoritative-browser-098be5a` 的 `7/7`
  shards、`20/20` scenario classes 全部通过，共 `10` 张截图；
  page/console/SSE/server transport/unexpected HTTP 5xx/image/
  cross-session/late/XSS 指标均为 `0`。ASGI 在终态 `send()` 前取消时
  state rows=`0`、target rows=`0`；正常终态 chunk 为
  `[feedback_target,end]`，matching version=`1`；server exception、
  traceback、`generator already executing` 均为 `0`；Task 21 variants
  `4/4`；端口 `19341–19347` 均释放。证据 manifest SHA-256 为
  `5c9fa302ea2e6d16b2c75ff5616368e626bcae6a53601632af3cfd9029a97a8d`，
  summary SHA-256 为
  `896ed5f4fdba2919019742ea70cbba569f68af751df1779d2e275ed20083f3a1`。
- **审计结论**:
  唯一 `FINAL-CATEGORY-DATA-AUDIT` 仍只调用一次，checkpoint
  `5983350`、key
  `1b3611b13ef377099ee008cdbcb30f950797fadc09d4b025a0fb24f44c6181c7`；
  原始 `P1=1/P2=1` 已由 `4206f45` 清除，未重跑该 full-file audit。
  其后对 `6dcb668..098be5a` 的独立增量审计报告位于
  `/private/tmp/xiaoro_final_stage1_audit_098be5a/report.md`，SHA-256
  `0035e75201667506f61d1408ab3af78f5ee02f8b8797380d32013aa6fe6f4789`，
  结果无 `P0–P2`；更早增量审计发现的 post-send `P1` 已由
  `098be5a` 修复。最终 unresolved `P0=0;P1=0;P2=0`。
- **数据与发布边界**:
  category/review 生产资产与候选 hash 均未改变；没有自动批准，
  `fact_count=0`、`approved=0`、`unknown=114`、`conflict=0`，所有无批准
  数据字段继续保持 unknown；历史 `336/111` 仍仅为
  `not_rerun` provenance。server 提交边界是成功的终态 ASGI
  `send()` 返回，浏览器仅在 EOF 后提交本地 snapshot；没有 client
  ACK，网络端到端 exactly-once 仍需未来 delivery ID +
  ACK/query/retry 协议，作为 release remainder，不是未解决 P0–P2。
- **本轮文档变更**:
  仅更新 `tasks.md`、`checklist.md`、
  `.trae/specs/complete-category-aware-guide-data-foundation/progress.md`、
  `docs/audits/category-data-foundation/progress.md` 和
  `docs/audits/category-data-foundation/final_handoff.md`。业务代码、
  protected paths 和数据资产均未修改；未 push、未部署、未切流。

## Round 8

- **结论**: FAIL
- **审查范围**: 六画像与 39/39 映射、字段和批准资产边界、品类/评论构建与 promotion、12 试点、理解与路由、HTTP/SSE 状态提交、Guide/runtime 全量、静态保护、最终审计证据和浏览器矩阵
- **验证结果**:
  - 构建/运行时: FAIL；compileall、双 boundary、diff/protected-path、排序 SHA 及 text/category/consultation/image/feedback/session 浏览器门禁均通过，但运行时对抗探针确认 `并且`、`并`、`且` 三种并列否定均错误恢复 fragrance 并路由 `guide_text`
  - 测试/覆盖: FAIL；Guide full `2619 passed, 1 warning`、runtime full `187 passed`、data/tooling focused `276 passed`，现有 runtime focused 门禁全绿，但新增三组并列否定探针 `3/3` 失败；锁定 `UV_OFFLINE` 命令仍因缺少 Pillow CPython 3.12 wheel 记为 `ENVIRONMENT`
  - 清单审计: 86/88 通过，2 项失败
- **风险与问题**: P1：常见并列连接词逃逸品类否定，明确不要的香水会进入正式推荐；P2（中等置信度）：唯一最终审计的 42 行路径清单含不存在的 `review_evidence_reader.py`，实际 41 项 blob manifest 未包含运行时使用的 `review_reader.py`

## Round 9

- **完成任务/测试/requirements**: Tasks 23–32 与全部 requirements 已完成，`tasks.md`/`checklist.md` 未勾项均为 `0`；产品代码 checkpoint 为 `af1faf41ff6f91caa97611a312b154fbadd0f7fd`。正式路由 TDD 为 RED `72 failed, 40 passed`、GREEN `112 passed`，formal `243 passed`，focused `2084 passed`，Guide full `3890 passed, 1 warning`，runtime `187 passed`；浏览器 `7/7` shards、`20/20` classes、`13` screenshots，全部错误指标为 `0`。独立增量审计 `P0=0;P1=0;P2=0`，`full_file_invocations=0`。
- **发现并修复的问题**: 修复了并列否定逃逸与过度传播、正负谓词和最终修订边界、属性排除与品类量词作用域、unsupported attribute/quantifier span 二次消费、`不要有` 成分值归一化以及外层排除加内层 absence 反向约束；Task 24 同时以真实 `review_reader.py` blob 和 corrected scope 完成定向清除，最终无未解决 P0–P2。
- **关键决策及理由**: 保持 scope-aware、typed uncertainty、fail-closed 与后端卡片权威合同，避免把未支持属性伪装成已应用约束；复用最终独立只读增量审计并按内容寻址约定记录 audit key，避免重复 full audit；锁定 UV 离线因缺 Pillow CPython 3.12 wheel 记为 `ENVIRONMENT`，以已批准 Python 3.11 环境结果为正式证据；数据资产保持 `fact_count=0` 且不自动批准。未 push、未部署、未切流。
- **changed files**: `.trae/specs/complete-category-aware-guide-data-foundation/progress.md`、`docs/audits/category-data-foundation/audit_ledger.csv`、`docs/audits/category-data-foundation/progress.md`、`docs/audits/category-data-foundation/final_handoff.md`；未修改业务代码、测试、保护路径、数据资产或历史 Round。
