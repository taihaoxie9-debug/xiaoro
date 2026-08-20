# Slice 1.2 干净运行外壳设计

状态：对话中已确认，等待书面版本复核  
日期：2026-08-07  
工作区：`/Users/bytedance/Desktop/xiaoro-fresh`  
分支：`rebuild`

## 1. 目标

为现有 Slice 1 文本防晒纵切建立一个可独立启动的 FastAPI 外壳，使它能在
不安装或启动 PostgreSQL、Redis、Milvus、CLIP、LLM 和旧
`app.services` 的情况下提供真实页面、静态商品图和 SSE 对话接口。

完成后，以下命令应能启动新运行时：

```bash
uvicorn app.guide_runtime.app:app --host 127.0.0.1 --port 8765
```

核心问题：

```text
500 内适合油敏肌的防晒
```

必须从正式 `/api/v1/chat/stream` 返回已锁定的 11 个预算内候选，当前
`chat.html` 应显示回答、真实商品图和平台链接。

## 2. 非目标

- 不修改理解、意图、召回、决策或排序语义。
- 不扩大到面霜、精华、彩妆等新类目。
- 不接图片上传、OCR、CLIP、向量检索或多轮画像。
- 不把旧 `app.main`、`app.api.v1.chat` 或 `app.services.v2` 搬进新运行时。
- 不声明现有 `chat.html` 上的图片、反馈等旧功能已在干净运行时可用。
- 不修改 SHA 锁定的 `app/guide/decision/deterministic_ranking.py`。

## 3. 方案比较

### 方案 A：继续改旧 `app.main`

优点是沿用原启动命令。缺点是模块导入和 lifespan 仍会牵出数据库、缓存、
Milvus、CLIP、LLM、限流和十个旧路由，无法证明新后端可以独立运行。

结论：不采用。

### 方案 B：复制一套临时页面和 HTTP 服务

优点是实现快。缺点是形成第二份页面、第二套 SSE 转换和第二条商品卡合同，
后续容易漂移；此前 `/tmp` 服务只能作为烟测工具，不能成为正式实现。

结论：不采用。

### 方案 C：新增独立 `app.guide_runtime`

新包位于六层业务实现之外，只承担 composition root 和 HTTP 传输职责。它
复用 `app.guide`、现有 `app/static/chat.html` 与商品图片目录，不 import
旧服务。

结论：采用。

## 4. 物理结构

```text
app/
  guide/                         # 已有六层业务与 adapters
  guide_runtime/                 # 新增干净 HTTP 外壳
    __init__.py
    app.py                       # FastAPI app factory、路由、静态挂载
    composition.py               # 一次性加载 Canonical 与图片资产
    contracts.py                 # HTTP 请求合同
    sse.py                       # SSE wire-format 序列化

requirements-guide-runtime.txt
requirements-guide-runtime-test.txt

tests/guide/runtime/
  test_import_boundary.py
  test_runtime_http.py
  test_runtime_cwd_independence.py
```

`app.guide_runtime` 不是第七业务层。它是和现有 API 类似的外部驱动适配器，
只调用 `app.guide` 的公开入口。

## 5. 依赖合同

正式运行依赖只包含：

```text
fastapi==0.115.0
uvicorn==0.30.0
pydantic==2.8.0
```

测试环境额外包含：

```text
httpx==0.27.2
pytest==8.0.0
```

新运行时禁止 import：

```text
app.services
app.services.v2
app.database
redis
pymilvus
openai
slowapi
```

导入边界由 subprocess 测试和 AST boundary checker 共同验证。

## 6. Composition Root

`composition.py` 使用文件自身位置计算仓库根目录，不依赖当前工作目录：

```text
repo_root/
  data/canonical/core_products_v1_manifest.json
  data/canonical/core_products_v1.jsonl
  data/canonical/seed_product_images_v1_manifest.json
  data/canonical/seed_product_images_v1.jsonl
```

启动时只构建一次：

1. `CanonicalProductReader`
2. seed product asset mapping
3. `TextRecommendationOrchestrator`

FastAPI 路由通过闭包或 `app.state` 复用同一个 orchestrator。每次请求不得重新
读取 Canonical 文件。

`create_app()` 必须支持注入测试 orchestrator，使 HTTP 测试不需要 monkeypatch
生产对象内部。

## 7. HTTP 合同

### `GET /health`

返回：

```json
{
  "status": "healthy",
  "runtime": "guide",
  "scope": "slice1_text_sunscreen"
}
```

这个响应明确说明当前只完成 Slice 1 文本防晒范围。

### `GET /`

使用 307 重定向到 `/chat`。

### `GET /chat`

返回现有 `app/static/chat.html`，并设置：

```text
Cache-Control: no-store, no-cache, must-revalidate
Pragma: no-cache
```

运行时在返回 HTML 时注入：

```javascript
window.__XIAORO_RUNTIME_SCOPE__ = "slice1_text_sunscreen";
```

`chat.html` 只做以下 scope-aware 调整：

- 状态文案从“支持图片咨询”改成“Slice 1 · 文本防晒”。
- 隐藏图片上传按钮和文件输入，并禁用图片拖放处理。
- 不创建反馈按钮，不请求未实现的 feedback API。

旧 `app.main` 直接服务同一份 HTML 时没有这个 scope 变量，保持原行为。

现有页面依赖外部 Feather Icons。为保证离线运行，页面在 CDN script 后增加
一个无副作用 fallback：

```javascript
window.feather = window.feather || { replace() {} };
```

不复制第二份 HTML。

### `GET /static/*`

只挂载现有 `app/static`，用于商品图片和页面资源。

### `POST /api/v1/chat/stream`

请求继续兼容当前页面：

```json
{
  "message": "500 内适合油敏肌的防晒",
  "session_id": "optional",
  "stream": true,
  "image_results": []
}
```

行为：

- 纯文本请求进入现有 `TextRecommendationOrchestrator`。
- 缺少防晒品类或预算非法时，复用现有 clarify 语义并转换成可见 message。
- 携带 `image_results` 时不调用旧图片链，返回公开说明后正常 `end`。
- 内部异常只返回 `GUIDE_INTERNAL_ERROR`，不泄露文件路径或异常文本。

响应保持当前前端已验证的 SSE wire format：

```text
event: <name>
data: <single-line JSON>

```

正常流只能有一个 `end`；异常流以 `error` 终止且不得再发 `end`。

## 8. 前端范围说明

新运行时复用当前页面的文本输入、流式回答和商品卡部分。图片上传、反馈提交、
旧搜索接口不属于本 Slice。图片和反馈入口在 guide runtime scope 下隐藏；
不能通过页面触发，也不得静默调用旧服务。

本 Slice 不重构 `chat.html`，只增加 runtime scope 分支和 Feather 离线
fallback。页面现有商品卡继续消费兼容 adapter 输出的：

```text
id
name
brand
price
image_url
detail_url
platform
fact_warnings
```

## 9. 错误与启动策略

- Canonical manifest、SHA 或商品图片资产校验失败：启动失败，不提供假健康状态。
- HTTP 请求验证失败：FastAPI 返回 422。
- 业务流内部异常：SSE 只返回公开 `error` 事件。
- 不存在“旧服务降级”。干净运行时失败时不能偷偷调用旧 Agent。
- 不捕获并吞掉 composition root 的资产完整性错误。

## 10. 验证策略

### 导入门禁

在新 Python 进程中 import `app.guide_runtime.app`，确认未加载任何禁止模块。

### HTTP 集成

使用 FastAPI `TestClient` 验证：

- `/health`
- `/` 重定向
- `/chat` 与 no-cache headers
- 一张真实商品图 `/static/images/products/...`
- `/api/v1/chat/stream` 的事件顺序
- 11 个锁定商品 ID
- 真实 `image_url` 与 `detail_url`
- 非法预算澄清
- 公开 error 终止

### CWD 独立

从 `/tmp` 显式指向仓库包启动，验证 Canonical 绝对路径正确：

```bash
cd /tmp
PYTHONPATH=/Users/bytedance/Desktop/xiaoro-fresh \
  /tmp/xiaoro-guide-runtime-venv/bin/uvicorn \
  app.guide_runtime.app:app --host 127.0.0.1 --port 8765
```

### 浏览器

使用 Playwright 打开正式 `/chat`，发送核心问题，确认：

- 回答文本可见
- 三张商品卡可见
- “真实商品图”可见
- 商品图片请求为 200
- 平台链接存在
- 页面显示“Slice 1 · 文本防晒”
- 图片与反馈入口不可见
- 浏览器控制台没有未捕获错误

### 既有门禁

```bash
python -m pytest -q -c pytest-guide.ini
python app/guide/check_boundaries.py app/guide
python app/guide/check_boundaries.py app/guide_runtime
git diff --check
```

## 11. 验收标准

- 新运行时可在仅安装最小依赖的全新 venv 中启动。
- import 新运行时不会加载旧服务、数据库、向量或 LLM 模块。
- 从 `/tmp` 启动不依赖 cwd。
- 核心问题通过正式 HTTP SSE 返回锁定结果。
- 页面显示真实商品图和平台链接。
- Canonical reader 与图片资产每个进程只加载一次。
- 既有 guide gate 全绿。
- 排序内核 SHA 保持
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`。

## 12. 后续方向

完成本 Slice 后，再单独规划业务生长：

```text
类目扩展 -> 多轮追问 -> 图片识别 -> 反馈画像
```

这些能力不得借由干净运行外壳提前实现。
