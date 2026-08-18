# Slice 1.9 安全图片输入与索引地基 Morning Handoff

## 结论

**Slice 1.9 已达到阶段退出门槛，状态为 CERTIFIED PASS；全局目标尚未完成。**

独立认证基于代码完成 HEAD
`6b327da043d3434b2243d653c8d5ddc71f9f86c8`，结论为
`P0=0; P1=0; P2=0`。Guide 全量 740、runtime 全量 86、关键合同 173、
103/103 源图预检、正常/对抗 Playwright、双 boundary、compileall、
diff check 和排序 SHA 均通过。

本阶段只交付安全图片接收、bundle 状态和可复现索引合同。没有选择、下载或
授权模型，没有生成真实向量或索引，也没有开放图片识别/找相似成功能力。
Slice 2.0 停在模型硬决策门，状态为 `WAITING_FOR_USER_DECISION`。

## 范围与 HEAD

- 分支：`rebuild`
- Slice 1.9 起始检查点 HEAD：
  `27c02b0ea93158bc0b866cdff53f7bc4def31ae1`
- Slice 1.8 NO-GO 收口 HEAD：
  `ae421f6c6046008919d571cfb953a0233aeaaebd`
- Slice 1.9 代码完成 HEAD：
  `6b327da043d3434b2243d653c8d5ddc71f9f86c8`
- 代码比较范围：`ae421f6..6b327da`
- 变更规模：52 个文件，10786 insertions，268 deletions

Slice 1.9 提交按当前分支祖先顺序完整列出：

```text
463194e7cfb8a20a2563e4210023e9468b62216b feat(guide): add safe image input contract
211a2a86bcf634a72fe3a6deaa757aaf99e81e7e fix(guide): enforce host-wide inference limit
abd156211d29ed1253d56b0dd725cdd75b2d58db feat(guide): add reproducible image index foundation
44fe2c232f03541dbb231cf144dffb6b99a9c386 feat(guide): secure image bundle state and api
0513f62c6ce4307a2186bf1aedf744020eb9ddd0 docs(integration): record Slice 1.9 tasks 7 and 8
71a2faa84e52e60e5be45acf5e4e066a23a01d64 fix(guide): close Slice 1.9 index review findings
44d3fcdc6dd5f45a989f00d0b42bea76eff5b3c6 fix(guide): harden image bundle upload lifecycle
962b56556d2560d39ae873266a10aad8d1b01985 fix(integration): close Task 7A review findings
d44201125f2d07beeedc8b4e9a9c477477a65082 fix(guide): isolate image admission domains
6b327da043d3434b2243d653c8d5ddc71f9f86c8 fix(guide): share bounded upload rate limits
```

Task 9 文档收口提交是包含本文件的下一提交，SHA 由提交后 `git log -1`
确定，避免在提交内容中写入不可成立的自引用 SHA。

## 已交付合同

- 只接受 1..4 张 JPEG、PNG、WebP；校验 MIME、扩展名、magic、真实解码、
  动画、单图 8 MB、总量 20 MB 和单图 2000 万像素边界。
- 推理 admission 在同一主机、同一共享文件系统和同一 OS 账号内最多放行
  2 个任务；锁目录、锁文件、owner、mode、symlink、inode 替换均 fail-closed。
- bundle/image ID 不可猜测，owner token 只保存 SHA-256；session、token、
  version、TTL、删除和 CAS 任一不匹配均拒绝。
- multipart 在 Starlette 解析前执行 body、字段、文件数、文件名和 header
  硬限；拒绝路径关闭临时文件且不创建可用 bundle。
- 正式 API、clean runtime 和前端统一使用 strip 后 1..100 字符
  `SessionId`；图片草稿按会话隔离，切换/删除/取消会中止并撤销未使用 bundle。
- 上传限速在同机 worker 间共享，client key 只落 SHA-256；状态有 TTL、容量
  上限和确定性淘汰。
- `ImageRetrievalPort`、构建输入输出、manifest、runtime lock 和健康检查合同
  已建立；未批准模型时构建明确 NO-GO。
- 103/103 只表示 Canonical 源图的路径、字节数、SHA 和稳定顺序预检通过，
  **不表示**真实向量或索引已经构建。
- UI 只声明“图片安全接收/图片处理，识别尚未启用”，不展示假候选、假识别、
  品牌/品类识别承诺或绝对安全结论。

## 最终认证证据

| 门禁 | 结果 |
| --- | --- |
| 关键 Slice 1.9 合同 | 173 passed |
| Guide 全量 | 740 passed |
| runtime 全量 | 86 passed |
| Canonical 源图预检 | 103/103 |
| 正常 Playwright | PASS |
| 对抗 Playwright | PASS |
| `app/guide` boundary | 0 violations |
| `app/guide_runtime` boundary | 0 violations |
| `compileall` | PASS |
| `git diff --check` | PASS |
| 排序内核 SHA | PASS |
| full-file 独立认证 | P0=0, P1=0, P2=0 |

逐项记录见 `docs/audits/slice1.9/test_evidence.csv`。最终独立认证报告：

```text
/private/tmp/xiaoro-fresh_cert_6b327da_full/report.md
/private/tmp/xiaoro-fresh_cert_6b327da_full/report.html
```

正常浏览器截图：

```text
/private/tmp/xiaoro-cert-smoke.png
```

## 三轮 Review 与修复

### 第一轮：Index/Core

报告：

```text
/private/tmp/xiaoro-fresh_slice19_review_20260808/report.md
/private/tmp/xiaoro-fresh_slice19_review_20260808/report.html
```

发现 `P0=0, P1=3, P2=2`：

- P1：可预测锁路径接受不安全目录/symlink。
- P1：自洽的 102/104 或部分索引可被误判 healthy。
- P1：source root resolve/symlink loop 异常逃逸 fail-closed health。
- P2：检索请求声明 SHA 未与 content 真实摘要绑定。
- P2：原子构建失败时 staging 清理错误被静默吞掉。

`71a2faa` 增加固定 canonical count=103、锁目录与 inode 加固、脱敏 unhealthy、
content SHA 一致性和显式 `index_cleanup_failed` 合同。修复后 focused 69、
Guide 634、runtime 49 及静态门禁通过。

### 第二轮：Bundle/Upload 生命周期

报告：

```text
/private/tmp/xiaoro-fresh_slice19_task7_review_1786175199/report.md
/private/tmp/xiaoro-fresh_slice19_task7_review_1786175199/report.html
```

发现 `P0=0, P1=4, P2=1`：

- P1：multipart 在有界读取前可无上限解析。
- P1：进程内 bundle 状态与 2/4 worker 部署不兼容。
- P1：上传与聊天 `session_id` 长度合同不一致。
- P1：图片草稿、取消和在途请求未按会话隔离。
- P2：clean runtime 可见引导承诺尚未启用的图片识别。

`44d3fcd` 和 `962b565` 补 pre-parse 限制、同机私有 SQLite bundle 状态、
统一 `SessionId`、前端撤销语义和中性文案。随后对 `962b565` 的独立复验又
定位 admission 域串扰、registry capacity/回收、可信父路径别名和页头问题；
`d442011` 以按 canonical lock directory 分域的 registry、路径校验和静态/
Playwright 文案断言修复。Task 7A/7B 复验均无未解决 P0-P2。

### 第三轮：最终 Full-File

报告：

```text
/private/tmp/xiaoro-fresh_slice1.9_final_review/report.md
/private/tmp/xiaoro-fresh_slice1.9_final_review/report.html
```

在 `ae421f6..d442011` 发现 `P0=0, P1=2, P2=1`：

- P1：per-client 限速为 worker 私有，可由两个 worker 合计放行 24 次。
- P1：共享 `chat.html` 仍残留图片识别、品牌/品类识别承诺。
- P2：client registry 可被高基数来源无界推高。

`6b327da` 以独立私有 SQLite fixed-window、`BEGIN IMMEDIATE`、120 秒 TTL、
512 client 硬上限、确定性淘汰和全页禁词断言修复。最终认证覆盖 29 个生产/
门禁文件、约 10181 行变更，结论 `P0=0, P1=0, P2=0`。

## SQLite 与单机边界

- bundle 状态：私有 `image_bundles.sqlite3`，为同机跨 worker 的 owner、TTL、
  删除和 CAS 提供原子状态。
- 上传限速：独立私有 `image_upload_rate.sqlite3`，以
  `BEGIN IMMEDIATE` 原子检查/计数，同机 worker 共享。
- 推理/上传 admission：`fcntl` 文件锁加进程内 semaphore，要求所有 worker
  使用同一 canonical lock directory、同一共享本地文件系统和同一 OS 账号。
- 以上合同均为 **single-host**。不同主机、容器隔离文件系统、网络文件系统
  语义差异或不同 OS 账号不会共享该上限；多主机部署必须在 Slice 2.0/部署前
  引入外部 admission、共享状态和一致性方案，不能把当前 SQLite/`fcntl`
  实现解释为集群级保证。

## Pillow 版本风险

- 仓库运行时 pin：`Pillow==10.4.0`。
- 当前主机 `python3` 实测：`Pillow 12.3.0`。
- `UV_OFFLINE=1 uv run --with-requirements requirements-guide-runtime-test.txt`
  当前无法解析 10.4.0，因为离线缓存没有该 wheel；本轮按约束没有联网下载。
- 因此现有认证证明当前认证环境的行为，但本机尚不能离线重建精确 10.4.0
  环境。发布前必须由获准的依赖供应链提供并校验 10.4.0 wheel，在精确 pin
  环境重跑图片解码、解压炸弹和全量门禁；不得静默改用 12.3.0 或放宽 pin。

## Token 检查点

主代理最新 `get_goal` 权威返回：

- `goal_id=6a76acf2a50b6afe00c97e8c`
- `tokens_used=0`
- `status=active`

append-only ledger 已记录：

- `SLICE_1_9_COMPLETE`：累计 `0`，delta `0`，状态 `RECORDED`
- `SLICE_2_0_MODEL_GATE`：累计 `0`，delta `0`，状态
  `WAITING_FOR_USER_DECISION`

模型切换不得重置该 Goal 的累计计数。

## 保护值

- 排序内核：
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`
- `core_products_v1.jsonl`：
  `0ba95df8c38d39f5bc0d73a32c318b157903abb64778c3e7b0acebfb75e95734`
- `core_products_v1_manifest.json`：
  `e0430a244af451a3fa73642295c4a79128e1622dfeed19ff8140eda9f2df0c69`
- `review_decisions.jsonl`：
  `12b0e1f82df3509ad8886af68a04ddcc62b28f3d3a5c72f4496ea22708fe50e9`
- `review_decisions_manifest.json`：
  `999be8b3238176ed57cab47d2fa7db30ed76a2840908bc9c2d52c06a3ec7f633`
- `seed_product_images_v1.jsonl`：
  `5a5a0c40deb80050b59b52203339497c73c3df1adc37b90799b1a62b1e5d9ab0`
- `seed_product_images_v1_manifest.json`：
  `47e3680b6b6d5c497890ae320c61b8a8deea8cd5e5ff8baccd2b7c13d661fdd7`

`data/canonical/**`、`app/services/**`、`app/database/**` 和排序内核相对
`ae421f6` 无变更。未联网、下载模型、push、发布、部署或切换生产流量。
总控 `.trae/specs/complete-slice1.7-to-2.0/progress.md` 本阶段未修改。

## 下一步

停止在 `Task 10: 准备并通过 Slice 2.0 模型硬决策门`。模型候选、许可证、
权重来源、SHA、下载权限和运行资源必须先获得用户明确批准；批准前不得选择/
下载模型、构建 103/103 向量索引或宣布全局 COMPLETE。
