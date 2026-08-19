# Slice 1.6 晨间交接

## 结论

Slice 1.6 文本主链已收口。Guide 全量、runtime、backend CSV、双 boundary、
compileall、正常/对抗 Playwright 和生产文件 full-file review 均通过；所有确认的
P0-P2 已修复。工作停止在 Slice 1.6，未开始 Slice 1.7。

## HEAD 与提交

- 起始 HEAD：`7572f5f4bab0480b50b3c8f142d23c55432858d2`
- 最终已验证实现 HEAD：`3be7f34` (`fix(api): harden formal chat boundaries`)
- 本文件与证据表由后续 `docs: close slice 1.6 text foundation` 收口提交承载

本轮提交：

```text
3e72a23 fix(guide): enforce truthful application boundaries
39db4af fix(decision): preserve unknown generic skin evidence
aa1b6d6 refactor(runtime): own concrete guide composition
aa97221 docs: record slice 1.6 tasks 2 and 3
c10a698 fix(feedback): commit only delivered conversation turns
e66d5cc fix(catalog): verify runtime image asset integrity
33dd983 docs: record slice 1.6 tasks 4 and 7
29ad05c fix(api): preserve clean guide multi-turn routing
5f30ad5 fix(frontend): isolate guide stream requests by session
c9c7240 docs: record slice 1.6 task 6
227aae2 test(guide): gate the slice 1.6 text foundation
f72531a fix(guide): resolve slice 1.6 release review findings
3be7f34 fix(api): harden formal chat boundaries
```

## 生产文件

本 Slice 修改的生产/发布门禁文件：

```text
app/api/v1/chat.py
app/guide/adapters/catalog/seed_product_assets.py
app/guide/adapters/state/__init__.py
app/guide/adapters/state/in_memory_session_locks.py
app/guide/application/chat_api_adapter.py
app/guide/application/text_recommendation_flow.py
app/guide/check_boundaries.py
app/guide/decision/recommendation.py
app/guide/feedback/ports.py
app/guide_runtime/composition.py
app/static/chat.html
tools/guide_gates/runtime_browser_adversarial.py
tools/guide_gates/runtime_browser_smoke.py
tools/guide_gates/slice1_backend.py
```

未修改 `app/services/**`、`app/database/**`、`data/canonical/**` 或
`app/guide/decision/deterministic_ranking.py`。

## 发布证据

- Guide 全量：`458 passed in 6.41s`
- Runtime：`32 passed in 2.90s`
- Application：`81 passed in 3.40s`
- Backend CSV：8/8，`/tmp/slice16_backend_gate.csv`
- `compileall`：通过
- `app/guide` boundary：0 violations
- `app/guide_runtime` boundary：0 violations
- 正常 Playwright：exit 0
- 对抗 Playwright：exit 0
- 最终截图：`/tmp/xiaoro-slice16-final-browser.png`
- 排序内核 SHA：
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`

正常浏览器验证了防晒、干性修护精华 unknown 标注和三类多轮追问；对抗门禁验证
了公开错误、session 切换、迟到 chunk、当前 session 重激活和真实 stage。页面无
page error、失败图片、伪契合百分比或 Guide 假工具步骤。

完整命令与结果见 `docs/audits/slice1.6/test_evidence.csv`。

## 审查与修复

首次全文件审查发现 1 个 P0 和 4 个 P1：

- 同步锁跨公开 SSE yield；
- CAS 保存晚于可见回答；
- version 0 旧会话被 Guide 接管；
- 当前 session 重激活替换在途 DOM；
- process-local 状态无法支持多 worker。

前四项由 Task 10 修复。多 worker 项因本 Slice 未批准部署、未接共享数据库或分布式
锁，改为明确的单 worker 发布前约束。

最终 14 文件 full-file review 又发现 1 个 P0 和 3 个 P1：

- 会话历史按可控 `session_id` 跨用户读删；
- 内部异常文本外泄；
- 数据库存储失败伪装为空历史/删除成功；
- chat 请求无体量上限。

Task 11 增加认证归属 SQL、真实删除证据、404/503、稳定错误码、256 KiB ASGI
body 限制、结构化字段上限和现有 chat rate limit。补充审查时又发现 chunked body
可绕过声明长度，已用 receive 字节计数修复并补 RED/GREEN 回归。

审查报告：

```text
/tmp/xiaoro-fresh_slice16_final_review/report.md
/tmp/xiaoro-fresh_slice16_final_review/report.html
/tmp/xiaoro-fresh_slice16_task11_review/report.md
/tmp/xiaoro-fresh_slice16_task11_review/report.html
```

当前无未解决 P0-P2。

## 保护值

旧仓库前后均保持：

```text
HEAD: 8658e191c05e208b2939aa37fb1ee170b2784e4f
git status --porcelain=v1 -uall: 363 lines
status SHA-256: 579295a4f4dce036e959e9519c5be1aa8e706ae161ffe48a71e1ea473c34a96a
```

未 push、发布、部署、联网或下载模型。

## 残余风险

- Guide 状态和 session locks 仍是 process-local；预生产必须使用单 worker，直到
  后续阶段提供共享原子状态和跨进程协调。
- 会话历史接口现在只允许读取/删除已绑定当前 `user_id` 的记录；旧匿名记录
  fail-closed 为 404，本 Slice 不做数据库迁移。
- 正式生产切流未批准，Compose 未修改。

## 停止点

Slice 1.6 到此停止。未实施修改肤质、verified-absence、图片索引或单图闭环，
即未开始 Slice 1.7、1.8、1.9 或 2.0。
