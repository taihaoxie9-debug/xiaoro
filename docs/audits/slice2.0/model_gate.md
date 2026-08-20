# Slice 2.0 模型硬门审计

## 门禁结论

状态：`APPROVED_INTERNAL_DEV_RISK_EXCEPTION`。

初始盘点轮只完成模型、权重、运行资源、许可证和依赖的只读盘点，以及
不落盘的本地离线 probe。随后用户批准固定模型、依赖安装和受限联网；官方
核验确认 Hugging Face card 的 `license=mit`，但没有独立权重 LICENSE，
具体权重许可证作用域仍为 `UNVERIFIED`。用户之后明确给出
`WEIGHT_LICENSE_RISK_EXCEPTION_APPROVE`，接受无独立权重 LICENSE、模型卡
用途限制和训练数据风险。

该例外授权 **仅限本地内部开发和验收**，明确禁止发布、部署和分发。它不把
权重许可证改写为 MIT，不构成发布或商用授权。固定依赖已在独立 venv 验证，
固定 safetensors 已离线只读加载并完成单图 probe；没有实现 adapter、写入
向量或构建 103 图索引。Task 10 已收口，Task 11 仅可在上述用途边界内开始。

锁定模型为：

```text
OpenCLIP ViT-B/32
pretrained tag: laion2b_s34b_b79k
cache repository: laion/CLIP-ViT-B-32-laion2B-s34B-b79K
```

锁定理由仅限本机可核验事实：已有完整 safetensors、SHA 可复验、512 维和
224 预处理合同明确，且在 M4/16 GB 的 MPS 与 CPU 上完成只读运行 probe。
官方模型 API 的 `cardData.license=mit` 已核验，但具体权重许可证仍为
`UNVERIFIED`，仅由用户风险例外允许本地内部使用。当前主机不需要下载该
权重，禁止联网重下；受限联网只用于既有官方核验和本次缺失小 wheel，
不授权任何后续联网。

## 盘点与验收

1. 本地权重盘点：核对缓存路径、文件类型、字节数、SHA-256、safetensors
   元数据、输出维度、预处理配置和损坏 `.bin`。
2. M4/16 GB 运行盘点：在旧仓库 venv 中强制 offline，分别对 MPS/CPU
   执行模型加载、103 图预处理/编码、product 47 单图查询和内存检索。
3. 许可证、依赖和候选盘点：核对本地代码许可证、权重模型卡缺口、
   `xiaoro-fresh` 依赖缺口，以及 MobileCLIP、SigLIP、DINOv2 本地权重
   是否存在。
4. 正式验收：在 `/private/tmp/xiaoro-guide-image-venv` 的
   `--system-site-packages` 环境中验证完整依赖闭包、权重 SHA、MPS/FP32
   模型加载和 product 47 单图 512 维输出。

逐项证据见 `test_evidence.csv`，机械事实见 `model_gate.json`。

## 权重与预处理

有效权重 snapshot 路径：

```text
/Users/bytedance/.cache/huggingface/hub/models--laion--CLIP-ViT-B-32-laion2B-s34B-b79K/snapshots/1a25a446712ba5ee05982a381eed697ef9b435cf/open_clip_model.safetensors
```

它是指向以下本地 blob 的符号链接：

```text
/Users/bytedance/.cache/huggingface/hub/models--laion--CLIP-ViT-B-32-laion2B-s34B-b79K/blobs/ac4f8c4b88af6d963118cbf40ad93176d092abbedfcb752601ae1866352656e6
```

| 项目 | 核验值 |
| --- | --- |
| 字节数 | `605143316` |
| SHA-256 | `ac4f8c4b88af6d963118cbf40ad93176d092abbedfcb752601ae1866352656e6` |
| safetensors metadata | `{"format":"pt"}`，302 tensors |
| 图像输出维度 | 512；`visual.proj=[768,512]` |
| 输入尺寸 | 224 x 224 |
| resize | shortest edge 224，bicubic，antialias |
| crop | center crop 224 x 224 |
| color | 转 RGB |
| mean | `[0.48145466, 0.4578275, 0.40821073]` |
| std | `[0.26862954, 0.26130258, 0.27577711]` |
| tensor dtype | FP32 |

精确预处理版本字符串为：

```text
openclip-3.3.0|ViT-B-32|laion2b_s34b_b79k@1a25a446712ba5ee05982a381eed697ef9b435cf|rgb|resize-shortest-224-bicubic-antialias|center-crop-224|mean-0.48145466,0.4578275,0.40821073|std-0.26862954,0.26130258,0.27577711|tensor-fp32
```

同一 snapshot 下的
`open_clip_pytorch_model.bin` 只有 `73102311` bytes，SHA-256 为
`6e70532d22a7f26794c8d939d362627a1ce3141ddc720ec7f9046ec171ff3491`。
`torch.load(..., weights_only=True)` 实测报
`failed finding central directory`。该 `.bin` 明确为损坏文件，**禁止**
选择、复制、加载、发布或作为 fallback。即使后续获批，也只能锁定上面经
SHA 核验的 safetensors；本次风险例外也不允许使用、修复或下载替换该
损坏 `.bin`。

## M4 实测

硬件为 MacBook Air、Apple M4 10 核、16 GB；系统为 arm64 macOS。
旧仓库 venv 中实测 `open_clip_torch==3.3.0`、
`torch==2.12.0`、`torchvision==0.27.0`，MPS built/available 均为 true。

以下为同一脚本、FP32、batch size 16 的本地离线实测。模型加载指
`create_model_and_transforms`、权重读取和设备放置；103 编码是首次完整
编码。单图和检索为 12 次的中位数，精确原始数值保存在 JSON。

| 设备 | 模型加载 s | 103 预处理 s | 103 编码 s | 103 合计 s | 单图预处理 ms | 单图编码 ms | 单图合计 ms | 103 检索 ms | product 47 top-1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| MPS | 1.894 | 1.052 | 0.757 | 1.809 | 9.075 | 22.878 | 31.712 | 0.131 | 12/12 |
| CPU | 0.846 | 0.909 | 0.950 | 1.858 | 7.597 | 21.497 | 29.107 | 0.104 | 12/12 |

probe 只在内存中临时编码 103 张已有 Canonical 源图，进程退出即丢弃，
没有写向量或索引。product 47 的 12/12 只证明同一源图重复自查询在该
probe 中 top-1 稳定，**不是** 103/103 准确率，也不满足 Task 11 的索引内图
或重编码图验收。单次本机 timing 也不是生产 SLA。

本次正式验收不依赖上述旧 venv。独立环境
`/private/tmp/xiaoro-guide-image-venv` 的 `sys.path` 不含
`xiaoro-shopping-master`，`pip check` 为 `No broken requirements found`。
在 `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1` 下重新核验权重 SHA 后，
MPS/FP32 加载耗时 `1.2899197500082664s`；product 47 图片 SHA 为
`1377844ac99429a8f0ee77c8ebdfd7947a9ea822a4118c9e1134a39aef4248f8`，
输出 shape `[1, 512]`，值全部有限，L2 norm 为 `0.9999999403953552`。
probe 未写索引或向量。

运行设备合同锁定如下：

- 本批准主机默认显式选择 MPS，要求 built/available，且只使用 FP32。
- 不允许从 MPS 隐式回退 CPU；MPS 加载或推理失败直接 fail-closed。
- CPU 只能由配置显式选择且只使用 FP32；CPU 失败同样 fail-closed。
- 任一设备失败均不得跨设备自动重试或返回空成功。

## 许可证

- `open_clip_torch==3.3.0` 本地 wheel metadata 和 LICENSE 均声明
  OpenCLIP **代码为 MIT**。
- 固定 revision 为
  `1a25a446712ba5ee05982a381eed697ef9b435cf`。官方 Hugging Face API 返回
  `cardData.license=mit`；官方 LFS pointer 的
  `oid sha256:ac4f8c4b88af6d963118cbf40ad93176d092abbedfcb752601ae1866352656e6`
  和 `size 605143316` 与本地 safetensors 完全一致。
- checkpoint cache 仍只有 `refs/main`、有效 safetensors 和损坏 bin，
  没有独立权重 LICENSE。模型卡 README、OpenCLIP LICENSE 和
  `src/open_clip/pretrained.py` 已按固定 URL 与内容 SHA-256 核验；本次追加
  仅记录既有核验结果，没有重新请求这些 URL。
- 因此具体
  `laion/CLIP-ViT-B-32-laion2B-s34B-b79K` checkpoint 的许可证状态为
  **`UNVERIFIED_RISK_ACCEPTED_INTERNAL_DEV_ONLY`**。
- OpenCLIP 的 MIT 代码许可证作用对象是代码，不能替代、推导或证明具体训练
  权重的许可证。模型卡的 `mit` 声明也没有消除独立权重 LICENSE 缺失、用途
  限制和训练数据风险；风险例外不允许把权重标记为可发布、可部署或可分发。

固定官方来源：

| 证据 | 固定 URL | 内容/核验值 |
| --- | --- | --- |
| HF model API | `https://huggingface.co/api/models/laion/CLIP-ViT-B-32-laion2B-s34B-b79K/revision/1a25a446712ba5ee05982a381eed697ef9b435cf` | `cardData.license=mit` |
| HF README | `https://huggingface.co/laion/CLIP-ViT-B-32-laion2B-s34B-b79K/raw/1a25a446712ba5ee05982a381eed697ef9b435cf/README.md` | 固定 revision 内容 SHA-256 已在获批核验中计算；本次输入未携带 digest 原值，因此不伪造 |
| HF LFS pointer | `https://huggingface.co/laion/CLIP-ViT-B-32-laion2B-s34B-b79K/raw/1a25a446712ba5ee05982a381eed697ef9b435cf/open_clip_model.safetensors` | oid `ac4f8c4b88af6d963118cbf40ad93176d092abbedfcb752601ae1866352656e6`；size `605143316` |
| OpenCLIP LICENSE | `https://raw.githubusercontent.com/mlfoundations/open_clip/v3.3.0/LICENSE` | SHA-256 `4a5b4f13ea4792a8211a69f32d2b460b6d520e57cd23c6301e707c76a6e97a55` |
| OpenCLIP PRETRAINED | `https://raw.githubusercontent.com/mlfoundations/open_clip/v3.3.0/src/open_clip/pretrained.py` | SHA-256 `5ffc377bb61392ca07581b7fa3705ed358d99188082f9a260854b2044ec3bc45`；候选映射到固定 HF repository |

## 依赖锁与安装证据

`requirements-guide-runtime.txt` 当前只有 FastAPI、Uvicorn、Pydantic、
Pillow 和 multipart，缺少 OpenCLIP 运行栈。根 `requirements.txt` 中的
`torch==2.4.0` 与 `openai-clip==1.0.1` 也不是本次 probe 使用的
`open_clip_torch` 依赖合同，不能拿来宣称可复现。

新建 `requirements-guide-image.txt`，完整锁定本次递归依赖闭包，文件
SHA-256 为
`630b712f7a3fd3794f12a729e3554b0d89cd9ed1687fef2cba9c1333ce5c066e`。
该文件是独立图片模型环境合同，不与 `requirements-guide-runtime.txt`
合并；后者的 Pillow 版本不被本任务修改。

独立 venv 以 `--system-site-packages` 复用已核验系统包，包括
`torch==2.12.0`、`torchvision==0.27.0`、`safetensors==0.7.0`、
`timm==1.0.27`、`huggingface-hub==1.17.0`、`Pillow==12.3.0` 和
`numpy==2.3.4`。完整 38 包版本见 requirements 和 JSON；核心系统
distribution 的 METADATA SHA 也记录在 JSON。

最初全量 pip 安装在下载大 torch wheel 时按用户指令终止，没有安装任何包。
最终只以 `pip --no-deps` 安装三个缺失小包；`ftfy` 与 `wcwidth` 是正常
`import open_clip` 和 `pip check` 机械发现的必需缺口：

| 包 | 来源 | wheel bytes | wheel SHA-256 |
| --- | --- | ---: | --- |
| `open_clip_torch==3.3.0` | pip cache / PyPI | 1547268 | `c549ad5ed6bfc119cc11105033c0a2b9d7a2a4afeb40a58a09aab3da1a0043ce` |
| `ftfy==6.2.0` | PyPI | 54433 | `f94a2c34b76e07475720e3096f5ca80911d152406fbde66fdb45c4d0c9150026` |
| `wcwidth==0.2.14` | PyPI | 37286 | `a7bb560c8aee30f9957e5f9895805edd20602f2d7f720186dfd906e82b4982e1` |

wheel SHA 从 pip HTTP cache 的原始 response body 计算；固定下载 URL、pip
report SHA 和系统包 METADATA SHA 见 JSON。旧仓库 venv 只保留历史 benchmark
出处，不是本次验收或后续运行依赖。

## 其他候选

| 候选 | 本地状态 | 下载需求 | SHA/许可证 | 本轮结论 |
| --- | --- | --- | --- | --- |
| MobileCLIP | 只有已安装包中的模型配置，无本地权重 | 需先获批具体 checkpoint 才可下载 | 下载后核验 | 非本轮推荐 |
| SigLIP | 只有库代码/模型配置，无本地权重 | 需先获批具体 checkpoint 才可下载 | 下载后核验 | 非本轮推荐 |
| DINOv2 | 只有库代码，无本地权重 | 需先获批具体 checkpoint 才可下载 | 下载后核验 | 非本轮推荐 |

“存在代码或模型配置”不等于“存在权重”。本轮没有为这些候选选择 checkpoint，
也没有推测维度、预处理、SHA 或许可证。只有用户后续批准具体候选和下载边界
后，才允许取得权重并逐项核验。

## 最终授权

用户明确批准以下固定合同：

1. `OpenCLIP ViT-B/32`、pretrained tag `laion2b_s34b_b79k`、revision
   `1a25a446712ba5ee05982a381eed697ef9b435cf`。
2. 仅使用 605143316-byte safetensors，SHA-256 为
   `ac4f8c4b88af6d963118cbf40ad93176d092abbedfcb752601ae1866352656e6`。
3. 允许独立依赖安装和受限 PyPI 补缺失 wheel；该授权现已消费，不授权继续
   联网，也从未授权下载或替换权重。
4. `WEIGHT_LICENSE_RISK_EXCEPTION_APPROVE`：接受 HF card `license=mit`
   但权重作用域未核实、无独立权重 LICENSE、用途限制和训练数据风险。
5. 用途仅限本地内部开发/验收，禁止发布、部署、分发。

Task 10.3、10.4 和 Task 10 可标记完成。Task 11 及以后仍保持未勾；本次没有
构建 103 图索引、实现 adapter 或修改生产代码。

## Token 与保护边界

`docs/audits/slice1.7-to-2.0/token_usage.csv` 已有且仅有一条
`SLICE_2_0_MODEL_GATE`，本轮不修改该旧行。已追加一条
`SLICE_2_0_START`，cumulative/delta 均为 0，HEAD 为
`050e9ac619e730995586ae9f74daa9028c15a0c1`，状态为 `APPROVED`。
总控 `progress.md`、`data/canonical/**`、生产代码和排序内核均未修改。
