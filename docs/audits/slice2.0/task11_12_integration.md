# Slice 2.0 Task 11/12 主工作区集成证据

## 结论

Task 11 和 Task 12 已集成到主工作区 `rebuild`。本轮只收口本地
OpenCLIP 索引、OCR/视觉观察合同和 Canonical 身份绑定；Task 13/14、最终
发布门禁和 `progress.md` 均未提前完成或修改。

集成起点为 `68a717cc0a4a0bb6ee49903b0e3702282f5ffa79`。功能提交及审查修复为：

1. `42cf905`：Task 11，可复现 OpenCLIP NumPy 索引。
2. `be8a717`：Task 12，fail-closed 图片身份绑定。
3. `c5a1b57`、`a122859`：全量审查发现并修复权重校验到加载之间的
   snapshot symlink 切换窗口；最终使用私有临时 hardlink 锚定已校验 inode，
   同时保留 `.safetensors` 后缀供 OpenCLIP 正确识别。

Task 11/12 cherry-pick 均无冲突，源提交与集成提交 patch-id 一致。

## 离线环境

所有模型相关命令均显式使用：

```text
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
```

pytest 执行入口为：

```text
/private/tmp/xiaoro-guide-image-venv/bin/python -m pytest
```

`PYTHONPATH` 优先加载
`/private/tmp/xiaoro-guide-runtime-venv/lib/python3.11/site-packages`，
因此 pytest、FastAPI、Uvicorn、Pydantic 和 httpx 分别使用锁定的
`8.0.0`、`0.115.0`、`0.30.0`、`2.8.0`、`0.27.2`。图片环境提供
OpenCLIP `3.3.0`、torch `2.12.0`、torchvision `0.27.0` 和 numpy
`2.3.4`。没有联网、下载或替换权重。

本机离线 supplement 的 Pillow 为 `12.3.0`、python-multipart 为
`0.0.32`，高于旧 runtime 文件中的 `10.4.0`、`0.0.9`。这是环境差异，
不是依赖锁更新；`requirements-guide-runtime*.txt` 未修改。

## 测试与门禁

| 门禁 | 结果 |
| --- | --- |
| Task 11/12 focused（最终修复后） | 56 passed |
| Guide 全量（最终修复后） | 796 passed |
| runtime 全量（最终修复后） | 86 passed |
| 坏 artifact/权重与身份 fail-closed 专项 | 16 passed |
| 架构/import 专项 | 25 passed |
| `app/guide` boundary | PASS，0 violations |
| `app/guide_runtime` boundary | PASS，0 violations |
| `compileall` | PASS，pycache 输出到 `/private/tmp` |
| `git diff --check` | PASS |
| 排序内核 SHA | `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f` |
| Canonical/旧 services/database/progress | 0 diff |

最终真实 MPS 离线复建使用锁定 safetensors，primary 与 repeat 两份新目录
均逐文件匹配仓库 artifact：

- 原图 top-1 自命中：`103/103`。
- 受控重编码 top-3 自命中：`103/103`。
- 重复运行候选排序稳定。
- 103 个 product ID、source path、source SHA 和 vector SHA 均唯一。
- primary、repeat 和仓库内 103 个 vector 文件逐一 SHA 相同。

失败关闭专项确认：

- manifest、index 或 vector 损坏时启动拒绝。
- 模型身份漂移、artifact 在健康检查后换包时检索拒绝。
- 不完整 safetensors 和禁止的损坏 `.bin` 不进入模型加载。
- OCR 默认状态为 `NOT_CONFIGURED`，不伪造 OCR 成功。
- 非 Canonical、低置信、近分、无候选、Canonical 身份缺失和 OCR 冲突
  均没有 `confirmed_product_id`。
- OCR 只提供与 Canonical 的一致性/冲突观察，不写入或覆盖 Canonical。

## Artifact 锁

| 项目 | SHA-256 |
| --- | --- |
| safetensors 权重 | `ac4f8c4b88af6d963118cbf40ad93176d092abbedfcb752601ae1866352656e6` |
| manifest 文件 | `a1af55f193c37ed6b9aaa634ed82cd9993d5d688141235bae25e1dc6a0985ccd` |
| manifest 逻辑摘要 | `f47e183aaec1f8418f9d4dcef78481607ab4a74d38b46920025c23070a3427d9` |
| index | `f61ba8ed45dc6f3d285e22016f7c643bfd01eec78ba65c84e75e5fabb843d340` |
| vector SHA 聚合 | `c182ab9d45507ecaf3b8ce5f5a11bcc0f547320524529744ebe019bfcb775010` |

模型身份为
`OpenCLIP:ViT-B-32:laion2b_s34b_b79k@1a25a446712ba5ee05982a381eed697ef9b435cf`，
向量维度为 512，查询和索引共用模型锁与预处理版本。

## Review 与剩余边界

`bits-code-guard` 按模型/索引、身份合同、Canonical/artifact 三组审查
Task 11/12。发现的权重路径切换问题先以 RED 复现，再经真实模型门禁修复；
最终无未解决 P0-P2。

仍未完成且保持未勾：

- Task 13 的 orchestrator、确定性硬条件、typed SSE、商品卡和浏览器闭环。
- Task 14 的全局最终审计、Playwright、token summary 和最终 handoff。
- `/health` 对本次真实索引的 runtime composition 接线。

权重许可证仍是用户批准的
`UNVERIFIED_RISK_ACCEPTED_INTERNAL_DEV_ONLY`：只允许本地内部开发/验收，
禁止发布、部署和分发。
