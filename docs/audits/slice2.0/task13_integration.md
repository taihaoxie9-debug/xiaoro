# Slice 2.0 Task 13 集成证据

## 结论

Task 13 已跑通真实单图上传到浏览器商品卡的完整链路：

```text
safe bundle payload
-> OpenCLIP observation
-> local NumPy recall
-> Canonical identity binding
-> deterministic hard conditions
-> typed SSE
-> real product cards
-> browser
```

真实商品 `53` 的视觉候选第一名仍为 `53`，查询
`150元以内找相似款` 后确定性决策卡片为 `[54, 53]`。这证明视觉相似度只
负责召回，最终顺序由品类、预算和 Canonical 决策事实决定。

## 实现边界

- 图片请求只读取经 session、version、owner token 和 TTL 原子授权的 SQLite
  payload，不信任前端候选。
- 未确认身份不进入 decision、winner 或商品卡。
- 图片候选携带 Canonical 品类状态；unknown/conflict 均 fail-closed，
  conflict 记录 `canonical_fact_conflict`。
- 预算、品类、肤质、功效和排除项由现有确定性决策层执行。
- 正式流式和非流式 API 均返回一致的公开错误及决策合同。
- 正式 async 路由通过 Starlette 线程桥执行同步模型加载和逐事件推理，不阻塞
  event loop。
- runtime 惰性加载模型；索引或模型不可用时 `/health` 返回 non-healthy。
- 页面显示真实商品图、详情链接、模型版本和完整索引 SHA，不显示无来源的
  精确识别承诺，也不持久化 owner token。

## 测试与门禁

| 门禁 | 结果 |
| --- | --- |
| Task 13 focused | `189 passed` |
| 受影响合同回归 | `206 passed` |
| Guide 全量（review 修复后） | `847 passed` |
| architecture boundary | `21 passed` |
| `compileall` | PASS |
| `git diff --check` | PASS |
| 排序内核 SHA | `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f` |
| 正常 Playwright | PASS |
| 对抗 Playwright | PASS |
| 真实 `/health` | HTTP 200，image runtime healthy |
| 保护路径 | Canonical、旧 services/database、排序内核 0 diff |

正常 Playwright 验证：

- 上传商品 `53` 的真实图片；
- 初始选择两张并删除一张后发送；
- typed `image_observation.confirmed_product_id == 53`；
- 商品卡 product IDs 为 `[54, 53]`；
- 模型名为锁定 OpenCLIP，索引 SHA 为
  `f61ba8ed45dc6f3d285e22016f7c643bfd01eec78ba65c84e75e5fabb843d340`；
- 两张真实商品图和两个详情链接可用；
- 无 page error、失败商品图请求或浏览器存储 owner token。

一次由 `with_server.py` 管理的复跑中，Uvicorn 子进程提前退出，Playwright
在图片轮次等待 120 秒后超时。随后使用前台可观测 Uvicorn 复验：
`/health` 在 18 秒内完成真实模型加载并返回 200；同一正常门禁在 24 秒内
通过，对抗门禁在 9 秒内通过。没有业务断言回归，服务随后受控关闭。

## Review

`bits-code-guard` 按 API/SSE、视觉决策、runtime/state 和前端/browser
四组执行 full-file review，并追加跨组审查。

确认并以 RED -> GREEN 修复：

1. 非流式图片响应丢失 intent、decision process 和 answer contract。
2. legacy 图片错误码在流式/非流式之间不一致。
3. 正式 async 图片流同步执行 OpenCLIP，阻塞 event loop。
4. 图片候选丢失 Canonical 品类 conflict 状态。
5. 成分 conflict 被误报为普通 evidence unknown。

两项候选按已批准合同边界驳回：

- runtime 首次 builder 失败缓存是显式 fail-closed、防止重试风暴的合同。
- 前端只承诺撤销未使用 bundle；已使用 bearer-token bundle 在显式 DELETE
  或 TTL 前保持有效。

跨组复核未发现新增 P0-P2，最终未解决缺陷为 0。审查制品位于：

```text
/private/tmp/xiaoro-fresh_task13_review_20260808-204603/
```

## 固定锁

- 模型：
  `OpenCLIP:ViT-B-32:laion2b_s34b_b79k@1a25a446712ba5ee05982a381eed697ef9b435cf`
- 权重 SHA：
  `ac4f8c4b88af6d963118cbf40ad93176d092abbedfcb752601ae1866352656e6`
- manifest 逻辑 SHA：
  `f47e183aaec1f8418f9d4dcef78481607ab4a74d38b46920025c23070a3427d9`
- index SHA：
  `f61ba8ed45dc6f3d285e22016f7c643bfd01eec78ba65c84e75e5fabb843d340`

模型许可证风险例外仍仅限本地内部开发/验收；没有 push、发布、部署、分发或
生产流量变更。
