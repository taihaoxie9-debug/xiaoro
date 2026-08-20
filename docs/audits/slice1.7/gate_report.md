# Slice 1.7 SubTask 3.3 发布门禁重跑

## 结论

**PASS - rerun after review fixes.** 本轮在 review 修复提交
`d6ae62f0b0413ce3ea499f3bb0f221520ab43c1d` 上重新执行全部命令，没有沿用
首轮结果。Slice 1.7 比较基线为
`a5f510fd8fa86d67b387cf436c9920398305f63a`。

未修改生产代码、tasks/checklist、Canonical、旧 services/database 或排序
内核，未暂存、未提交。

## 门禁结果

- focused skin + API + runtime + frontend：`152 passed in 5.14s`
- Guide 全量：`528 passed in 7.09s`
- runtime 全量：`35 passed in 2.35s`
- backend CSV：`8/8` 锁定 case 完整匹配，9 行
- `compileall`：PASS
- `app/guide` boundary：0 violations
- `app/guide_runtime` boundary：0 violations
- baseline `a5f510f..HEAD` diff check：PASS
- 受保护路径 diff：PASS
- 排序 SHA-256：
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`

## Runtime 与浏览器

Uvicorn 从 `/tmp` 以 `env -i`、`--workers 1` 启动，只有一个 Python
listener。`/health` 返回 `healthy`，包含 `skin_revision_followup`，
`conversation_state=process_local`。

正常 Playwright 验证：

- 防晒 3 卡、真实商品图和链接；
- 修护精华 `[91, 38] / SELECTED / version 1`；
- 改成敏感肌后 `[91, 38] / INSUFFICIENT_FOR_WINNER / version 2`；
- “第二款呢”只返回 `[38] / version 3`；
- 预算修改、干皮证据不足、无虚假百分比/阶段；
- 0 page errors，0 失败商品图。

对抗 Playwright 的 4 个场景全部通过：公开错误、会话切换 abort 与迟到
chunk/version 隔离、当前会话重激活、真实 stage；0 page errors，0 SSE
parse errors。

结束后已发送受控 SIGINT。Uvicorn、pytest、Playwright/Chromium 匹配进程为
0，端口 8765 listener 为 0。

## 证据与保护

- 逐命令证据：`docs/audits/slice1.7/test_evidence.csv`
- backend CSV：`/tmp/xiaoro-slice17-backend-gate-rerun.csv`
  - SHA-256：
    `61bde35c47b06d0d4a6fbc2d966d57f7a87de29ba07cad8c02e7062d6e060194`
- 最终截图：`/tmp/xiaoro-slice17-final-browser-rerun.png`
  - `1440x1000`，`203863` bytes
  - SHA-256：
    `149a5dcb7ad999f55a07cc01bd819a303eb3258059db5380dc0bf398606f69de`
- 原始日志：`/tmp/xiaoro-slice17-rerun-*.log`
- 旧仓库前后保持：
  - HEAD `8658e191c05e208b2939aa37fb1ee170b2784e4f`
  - `363` 条 status
  - status SHA-256
    `579295a4f4dce036e959e9519c5be1aa8e706ae161ffe48a71e1ea473c34a96a`
- tasks SHA-256：
  `fb7ab6c24d0ebac40657fc96fa04cd2a98ff357f4635d1191c895108e641ae04`
- checklist SHA-256：
  `d4b72e450a892470616c8c2a5a1064eaf0799334370c941a4e35cf6b05880403`

最终工作树只有本目录两份未跟踪审计文件，0 tracked diff、0 staged files。
