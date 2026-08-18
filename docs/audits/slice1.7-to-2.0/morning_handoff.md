# Slice 1.7 至 2.0 最终 Handoff

## 结论

`COMPLETE`

Slice 1.7、1.8 NO-GO 分支、1.9 和 2.0 已按总控规格完成。真实单图链路为：

```text
安全上传
-> OpenCLIP 视觉观察
-> 本地 NumPy 召回
-> Canonical 身份绑定
-> 确定性硬条件决策
-> typed SSE
-> 真实商品卡
-> 浏览器
```

最终 full-file review 的确认 P1/P2 及复验新增问题均已修复，未解决
`P0=0; P1=0; P2=0`。

## 关键提交

- `d6ae62f`：Slice 1.7 肤质修改收口
- `ae421f6`：Slice 1.8 确认 NO-GO
- `b25a014`：Slice 1.9 发布门禁收口
- `42cf905`：构建 103/103 OpenCLIP 索引
- `7ff7e54`：完成真实单图推荐浏览器闭环
- `fef6d87`：修复最终审查、事务、正式 API、资源释放和前端安全问题

## 最终门禁

| 门禁 | 结果 |
| --- | --- |
| Task 14 focused | `210 passed` |
| Guide 全量 | `901 passed` |
| Runtime 全量 | `105 passed` |
| 正式 API focused | `65 passed` |
| `app/guide` boundary | PASS |
| `app/guide_runtime` boundary | PASS |
| `compileall` | PASS |
| `git diff --check` | PASS |
| 排序内核 SHA | `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f` |
| 103/103 原图 top-1 | `103/103` |
| 103/103 重编码 top-3 | `103/103` |
| 重复排序稳定 | PASS |
| `/health` | HTTP 200，image runtime healthy |
| 正常 Playwright | PASS |
| 对抗 Playwright | PASS |
| 持久化 XSS 浏览器探针 | PASS |

正常浏览器截图：

- 路径：`/private/tmp/xiaoro-final-smoke.png`
- SHA-256：`256128acf0f985c723898f294b06d588c9877b6ea954135f11aa1766e885ab91`

健康响应保存在 `/private/tmp/xiaoro-final-health.json`。

## 模型与索引锁

- 模型：`OpenCLIP:ViT-B-32:laion2b_s34b_b79k@1a25a446712ba5ee05982a381eed697ef9b435cf`
- 权重 SHA：`ac4f8c4b88af6d963118cbf40ad93176d092abbedfcb752601ae1866352656e6`
- manifest SHA：`f47e183aaec1f8418f9d4dcef78481607ab4a74d38b46920025c23070a3427d9`
- index SHA：`f61ba8ed45dc6f3d285e22016f7c643bfd01eec78ba65c84e75e5fabb843d340`
- 向量维度：512
- 商品图：103/103

## 最终修复摘要

- 限速满容量时不再淘汰活跃窗口，避免绕过已触发的限制。
- 所有上传流均尝试关闭；业务异常优先于 close 异常。
- SQLite bundle 损坏统一映射为公开 unavailable。
- 索引发布使用原子 no-clobber，失败报告、cleanup 与 rollback 保持事务语义。
- provenance 覆盖实际执行的本地 import closure。
- 正式非流式文本请求进入 Guide；同步构建和事件迭代均通过线程桥。
- 图片 Data URL 不持久化；旧快照执行属性和危险 URL 在恢复前清除。
- 商品图、详情、citation、历史会话和 legacy 图片结果关闭动态 HTML/JS XSS。
- GUIDE 多图在上传和流请求前拒绝；DELETE 对抗 mock 校验完整所有权凭证。

## 风险与边界

- 权重许可证风险例外仍仅限本地内部开发/验收，不授权发布、部署或分发。
- conversation state 仍为 `process_local`，这是已记录的部署边界。
- Token 早期检查点存在计量盲区；`update_goal` 最终权威总量为
  `26788605`，耗时 11 小时 40 分 27 秒，详见 `token_usage_summary.md`。
- 未 push、未发布、未部署、未切换生产流量。
- `data/canonical/**`、`app/services/**`、`app/database/**` 和排序内核无本轮
  diff。
- 无残留 Uvicorn、pytest 或 Playwright 进程。
