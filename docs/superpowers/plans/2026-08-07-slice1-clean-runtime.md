# Slice 1.2 Clean Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立一个不依赖旧服务、数据库、向量或 LLM 的独立 FastAPI 运行外壳，正式承载 Slice 1 文本防晒 SSE 和现有商品卡页面。

**Architecture:** 新增 `app.guide_runtime` 作为六层之外的 composition root 与 HTTP 驱动适配器；它一次性加载 Canonical reader、图片资产和 `TextRecommendationOrchestrator`，复用现有 SSE 前端兼容 adapter。旧 `app.main` 保持不动，新运行时只暴露健康检查、聊天页、静态资源和文本 SSE。

**Tech Stack:** Python 3.11, FastAPI 0.115.0, Uvicorn 0.30.0, Pydantic 2.8.0, HTTPX 0.27.2, pytest 8.0.0, Playwright.

---

## 0. Execution Contract

- 只实现设计文档
  `docs/superpowers/specs/2026-08-07-slice1-clean-runtime-design.md`。
- 不修改推荐、召回、预算、肤质、排序或 winner 语义。
- 不修改 `app/guide/decision/deterministic_ranking.py`。
- 新运行时不得 import `app.services`、`app.database`、`slowapi`、`openai`、
  `redis` 或 `pymilvus`。
- 不删除或重写旧 `app.main`、`app/api/v1/chat.py`。
- `chat.html` 只增加 runtime scope、离线图标 fallback 和不支持入口隐藏。
- 用户已确认主会话内联执行，不使用子代理。
- 每个 Task 独立 RED、GREEN、边界检查和提交。

## 1. File Map

### Create

- `requirements-guide-runtime.txt`
  - 正式运行所需的最小锁定依赖。
- `requirements-guide-runtime-test.txt`
  - 继承运行依赖并加入 HTTP 集成测试依赖。
- `app/guide_runtime/__init__.py`
  - 独立 HTTP 外壳包标记。
- `app/guide_runtime/composition.py`
  - 从仓库绝对路径一次性构建 orchestrator。
- `app/guide_runtime/contracts.py`
  - FastAPI 请求合同。
- `app/guide_runtime/sse.py`
  - SSE 单行 wire-format 和 runtime scope 事件。
- `app/guide_runtime/app.py`
  - FastAPI app factory、页面、静态资源和 SSE 路由。
- `tests/guide/runtime/test_import_boundary.py`
  - 禁止旧模块加载。
- `tests/guide/runtime/test_composition.py`
  - CWD 独立和真实资产组合测试。
- `tests/guide/runtime/test_runtime_http.py`
  - HTTP/SSE 集成合同。
- `tests/guide/runtime/test_frontend_scope.py`
  - `chat.html` runtime scope 静态合同。
- `tools/guide_gates/runtime_browser_smoke.py`
  - Playwright 正式页面烟测。

### Modify

- `app/static/chat.html`
  - runtime scope 标识、图片/反馈入口隐藏、Feather fallback。

### Explicitly Unchanged

- `app/main.py`
- `app/api/v1/chat.py`
- `app/services/**`
- `app/guide/decision/deterministic_ranking.py`
- Canonical 与图片资产文件

---

### Task 1: Lock the Minimal Runtime Environment and Package Boundary

**Files:**
- Create: `requirements-guide-runtime.txt`
- Create: `requirements-guide-runtime-test.txt`
- Create: `app/guide_runtime/__init__.py`
- Create: `tests/guide/runtime/test_import_boundary.py`

- [ ] **Step 1: Add the minimal dependency locks**

Create `requirements-guide-runtime.txt`:

```text
fastapi==0.115.0
uvicorn==0.30.0
pydantic==2.8.0
```

Create `requirements-guide-runtime-test.txt`:

```text
-r requirements-guide-runtime.txt
httpx==0.27.2
pytest==8.0.0
```

- [ ] **Step 2: Create a fresh runtime gate venv**

Run:

```bash
python3 -m venv /tmp/xiaoro-guide-runtime-venv
/tmp/xiaoro-guide-runtime-venv/bin/python -m pip install \
  -r requirements-guide-runtime-test.txt
```

Expected:

```text
Successfully installed ... fastapi-0.115.0 ... pydantic-2.8.0 ...
pytest-8.0.0 ... uvicorn-0.30.0
```

- [ ] **Step 3: Write the failing package/import test**

Create `tests/guide/runtime/test_import_boundary.py`:

```python
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_guide_runtime_package_imports_without_legacy_modules() -> None:
    script = """
import sys

before = set(sys.modules)
import app.guide_runtime
loaded = set(sys.modules) - before
forbidden = (
    "app.services",
    "app.database",
    "slowapi",
    "openai",
    "redis",
    "pymilvus",
)
unexpected = sorted(
    name
    for name in loaded
    if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden)
)
if unexpected:
    raise RuntimeError(unexpected)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ""
    assert completed.stderr == ""
```

- [ ] **Step 4: Run the test and verify RED**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/runtime/test_import_boundary.py
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.guide_runtime'`.

- [ ] **Step 5: Add the empty outer-shell package**

Create `app/guide_runtime/__init__.py` as an empty package marker.

- [ ] **Step 6: Run the test and verify GREEN**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/runtime/test_import_boundary.py
```

Expected: `1 passed`.

- [ ] **Step 7: Run both architecture scanners**

Run:

```bash
python3 app/guide/check_boundaries.py app/guide
python3 app/guide/check_boundaries.py app/guide_runtime
```

Expected:

```text
Boundary check passed: app/guide
Boundary check passed: app/guide_runtime
```

- [ ] **Step 8: Commit**

```bash
git add requirements-guide-runtime.txt requirements-guide-runtime-test.txt \
  app/guide_runtime/__init__.py tests/guide/runtime/test_import_boundary.py
git commit -m "build(guide): lock clean runtime dependencies"
```

---

### Task 2: Build the CWD-Independent Composition Root

**Files:**
- Create: `app/guide_runtime/composition.py`
- Create: `tests/guide/runtime/test_composition.py`

- [ ] **Step 1: Write the failing composition tests**

Create `tests/guide/runtime/test_composition.py`:

```python
from __future__ import annotations

import os
from pathlib import Path

from app.guide.application.contracts import UserTurn
from app.guide_runtime.composition import (
    REPO_ROOT,
    build_runtime_orchestrator,
)


def test_runtime_composition_uses_repo_absolute_assets(
    tmp_path: Path,
) -> None:
    previous = Path.cwd()
    os.chdir(tmp_path)
    try:
        orchestrator = build_runtime_orchestrator()
        events = list(
            orchestrator.stream(
                UserTurn(
                    session_id="composition-test",
                    message="500 内适合油敏肌的防晒",
                    image_bundle_id=None,
                    conversation_version=0,
                )
            )
        )
    finally:
        os.chdir(previous)

    products = next(event for event in events if event.event == "products")
    assert [card.product_id for card in products.data.cards] == [
        55, 57, 54, 51, 102, 53, 58, 56, 52, 26, 101
    ]
    assert products.data.cards[0].image_url == (
        "/static/images/products/tmall_v3_746513552108.png"
    )
    assert REPO_ROOT == Path(__file__).resolve().parents[3]
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/runtime/test_composition.py
```

Expected: FAIL because `app.guide_runtime.composition` does not exist.

- [ ] **Step 3: Implement the composition root**

Create `app/guide_runtime/composition.py`:

```python
from pathlib import Path

from app.guide.adapters.catalog import CanonicalProductReader
from app.guide.adapters.catalog.seed_product_assets import (
    load_seed_product_assets,
)
from app.guide.application.text_recommendation_flow import (
    TextRecommendationOrchestrator,
    build_text_recommendation_orchestrator,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def build_runtime_orchestrator(
    repo_root: Path = REPO_ROOT,
) -> TextRecommendationOrchestrator:
    canonical = repo_root / "data" / "canonical"
    reader = CanonicalProductReader.from_files(
        manifest_path=canonical / "core_products_v1_manifest.json",
        products_path=canonical / "core_products_v1.jsonl",
    )
    assets = load_seed_product_assets(
        manifest_path=canonical / "seed_product_images_v1_manifest.json",
        products_path=canonical / "seed_product_images_v1.jsonl",
    )
    return build_text_recommendation_orchestrator(
        reader,
        product_assets=assets,
    )
```

- [ ] **Step 4: Run the test and verify GREEN**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/runtime/test_composition.py
```

Expected: `1 passed`.

- [ ] **Step 5: Run the existing backend gate**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q -c pytest-guide.ini
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add app/guide_runtime/composition.py \
  tests/guide/runtime/test_composition.py
git commit -m "feat(runtime): compose guide assets without cwd"
```

---

### Task 3: Implement the Minimal FastAPI and SSE Contract

**Files:**
- Create: `app/guide_runtime/contracts.py`
- Create: `app/guide_runtime/sse.py`
- Create: `app/guide_runtime/app.py`
- Create: `tests/guide/runtime/test_runtime_http.py`
- Modify: `tests/guide/runtime/test_import_boundary.py`

- [ ] **Step 1: Write the failing HTTP integration tests**

Create `tests/guide/runtime/test_runtime_http.py`:

```python
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.guide.presentation.sse_events import (
    ErrorData,
    ErrorEvent,
    StartData,
    StartEvent,
)
from app.guide_runtime.app import create_app


def _events(response) -> list[tuple[str, dict]]:
    blocks = [
        block
        for block in response.text.split("\n\n")
        if block.strip()
    ]
    parsed: list[tuple[str, dict]] = []
    for block in blocks:
        name = ""
        payload = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line.removeprefix("event: ").strip()
            elif line.startswith("data: "):
                payload += line.removeprefix("data: ")
        parsed.append((name, json.loads(payload)))
    return parsed


def test_health_and_page_contract() -> None:
    client = TestClient(create_app())

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {
        "status": "healthy",
        "runtime": "guide",
        "scope": "slice1_text_sunscreen",
    }

    root = client.get("/", follow_redirects=False)
    assert root.status_code == 307
    assert root.headers["location"] == "/chat"

    chat = client.get("/chat")
    assert chat.status_code == 200
    assert "小 ro 导购" in chat.text
    assert "slice1_text_sunscreen" in chat.text
    assert "no-store" in chat.headers["cache-control"]


def test_static_product_image_is_served() -> None:
    client = TestClient(create_app())

    response = client.get(
        "/static/images/products/tmall_v3_746513552108.png"
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\\x89PNG")


def test_stream_returns_locked_slice1_contract() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "500 内适合油敏肌的防晒",
            "session_id": "http-test",
            "stream": True,
            "image_results": [],
        },
    )
    events = _events(response)
    names = [name for name, _ in events]

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert names[0] == "start"
    assert names[-1] == "end"
    assert names.count("end") == 1
    products = next(data for name, data in events if name == "products")
    assert [item["id"] for item in products["products"]] == [
        55, 57, 54, 51, 102, 53, 58, 56, 52, 26, 101
    ]
    assert products["products"][0]["image_url"].startswith("/static/")
    assert products["products"][0]["detail_url"].startswith("https://")


def test_image_request_is_publicly_rejected_without_legacy_fallback() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "这张图适合敏感肌吗",
            "session_id": "image-test",
            "stream": True,
            "image_results": [{"product_id": "55"}],
        },
    )
    events = _events(response)

    assert [name for name, _ in events] == ["start", "message", "end"]
    assert "只支持文本防晒" in events[1][1]["content"]


def test_invalid_budget_is_visible_clarification() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "0 元以内的防晒",
            "session_id": "invalid-budget",
            "stream": True,
        },
    )
    events = _events(response)
    names = [name for name, _ in events]

    assert names[-1] == "end"
    assert "products" not in names
    message = next(data for name, data in events if name == "message")
    assert message["content"].strip()


def test_public_error_is_terminal_and_hides_internal_detail() -> None:
    class PublicErrorOrchestrator:
        def stream(self, turn):
            yield StartEvent(
                data=StartData(session_id=turn.session_id)
            )
            yield ErrorEvent(
                data=ErrorData(
                    code="GUIDE_INTERNAL_ERROR",
                    message="推荐暂时不可用，请稍后重试。",
                )
            )

    client = TestClient(
        create_app(orchestrator=PublicErrorOrchestrator())
    )
    response = client.post(
        "/api/v1/chat/stream",
        json={
            "message": "500 内适合油敏肌的防晒",
            "session_id": "error-test",
            "stream": True,
        },
    )
    events = _events(response)

    assert [name for name, _ in events] == ["start", "error"]
    assert "end" not in [name for name, _ in events]
    assert events[-1][1] == {
        "error": "GUIDE_INTERNAL_ERROR",
        "message": "推荐暂时不可用，请稍后重试。",
    }


def test_app_reuses_the_injected_orchestrator() -> None:
    sentinel = object()

    app = create_app(orchestrator=sentinel)

    assert app.state.orchestrator is sentinel
```

- [ ] **Step 2: Extend the import test to import the real app**

In `tests/guide/runtime/test_import_boundary.py`, change:

```python
import app.guide_runtime
```

to:

```python
import app.guide_runtime.app
```

- [ ] **Step 3: Run the tests and verify RED**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/runtime/test_import_boundary.py \
  tests/guide/runtime/test_runtime_http.py
```

Expected: FAIL because `contracts.py`, `sse.py` and `app.py` do not exist.

- [ ] **Step 4: Add the HTTP request contract**

Create `app/guide_runtime/contracts.py`:

```python
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChatStreamRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=128)
    stream: bool = True
    image_results: list[dict[str, Any]] | None = None
```

- [ ] **Step 5: Add deterministic SSE serialization**

Create `app/guide_runtime/sse.py`:

```python
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

from app.guide.application.chat_api_adapter import (
    iter_slice1_guide_legacy_sse_events,
)
from app.guide.application.contracts import UserTurn
from app.guide_runtime.contracts import ChatStreamRequest


def encode_sse(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"event: {event}\\ndata: {payload}\\n\\n"


def iter_http_events(
    orchestrator,
    payload: ChatStreamRequest,
) -> Iterator[tuple[str, dict[str, Any]]]:
    session_id = payload.session_id or f"guide-{uuid4().hex}"
    if payload.image_results:
        yield "start", {"session_id": session_id}
        yield "message", {
            "content": "当前干净运行外壳只支持文本防晒推荐。",
            "done": False,
        }
        yield "end", {}
        return

    turn = UserTurn(
        session_id=session_id,
        message=payload.message,
        image_bundle_id=None,
        conversation_version=0,
    )
    yield from iter_slice1_guide_legacy_sse_events(
        orchestrator,
        turn,
    )
```

- [ ] **Step 6: Add the FastAPI app factory**

Create `app/guide_runtime/app.py`:

```python
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.guide_runtime.composition import (
    REPO_ROOT,
    build_runtime_orchestrator,
)
from app.guide_runtime.contracts import ChatStreamRequest
from app.guide_runtime.sse import encode_sse, iter_http_events

RUNTIME_SCOPE = "slice1_text_sunscreen"


def create_app(*, orchestrator=None, repo_root: Path = REPO_ROOT) -> FastAPI:
    runtime_orchestrator = orchestrator or build_runtime_orchestrator(
        repo_root
    )
    static_root = repo_root / "app" / "static"
    chat_path = static_root / "chat.html"
    app = FastAPI(
        title="XiaoRo Guide Runtime",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.orchestrator = runtime_orchestrator
    app.mount("/static", StaticFiles(directory=static_root), name="static")

    @app.get("/")
    def root() -> RedirectResponse:
        return RedirectResponse(url="/chat", status_code=307)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {
            "status": "healthy",
            "runtime": "guide",
            "scope": RUNTIME_SCOPE,
        }

    @app.get("/chat")
    def chat() -> HTMLResponse:
        html = chat_path.read_text(encoding="utf-8")
        scope = (
            '<script>window.__XIAORO_RUNTIME_SCOPE__='
            f'"{RUNTIME_SCOPE}";</script>'
        )
        html = html.replace("</head>", f"{scope}\\n</head>", 1)
        return HTMLResponse(
            html,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "Pragma": "no-cache",
            },
        )

    @app.post("/api/v1/chat/stream")
    def chat_stream(payload: ChatStreamRequest) -> StreamingResponse:
        def generate():
            for event, data in iter_http_events(
                app.state.orchestrator,
                payload,
            ):
                yield encode_sse(event, data)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    return app


app = create_app()
```

- [ ] **Step 7: Run the tests and verify GREEN**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/runtime/test_import_boundary.py \
  tests/guide/runtime/test_composition.py \
  tests/guide/runtime/test_runtime_http.py
```

Expected: all tests PASS.

- [ ] **Step 8: Run both boundary checks**

Run:

```bash
python3 app/guide/check_boundaries.py app/guide
python3 app/guide/check_boundaries.py app/guide_runtime
```

Expected: zero violations.

- [ ] **Step 9: Commit**

```bash
git add app/guide_runtime/contracts.py app/guide_runtime/sse.py \
  app/guide_runtime/app.py tests/guide/runtime/test_import_boundary.py \
  tests/guide/runtime/test_runtime_http.py
git commit -m "feat(runtime): serve clean guide SSE"
```

---

### Task 4: Make the Shared Chat Page Honest in Guide Runtime Mode

**Files:**
- Modify: `app/static/chat.html`
- Create: `tests/guide/runtime/test_frontend_scope.py`

- [ ] **Step 1: Write the failing frontend scope test**

Create `tests/guide/runtime/test_frontend_scope.py`:

```python
from pathlib import Path

CHAT_HTML = Path("app/static/chat.html")


def test_chat_page_has_offline_icons_and_runtime_scope_controls() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")

    assert "window.feather = window.feather || { replace() {} }" in html
    assert "GUIDE_RUNTIME_MODE" in html
    assert "runtimeStatusPill" in html
    assert "Slice 1 · 文本防晒" in html
    assert "if (GUIDE_RUNTIME_MODE) return;" in html


def test_feedback_buttons_are_disabled_only_in_guide_runtime() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")

    function_start = html.index(
        "function addFeedbackButtons(messageWrapper, messageId)"
    )
    function_body = html[function_start:function_start + 300]
    assert "if (GUIDE_RUNTIME_MODE) return;" in function_body
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/runtime/test_frontend_scope.py
```

Expected: FAIL because the runtime scope controls are absent.

- [ ] **Step 3: Add the Feather offline fallback and status selector**

After the existing Feather CDN script in `app/static/chat.html`, add:

```html
<script>
    window.feather = window.feather || { replace() {} };
</script>
```

Change:

```html
<div class="status-pill">支持图片咨询</div>
```

to:

```html
<div class="status-pill" id="runtimeStatusPill">支持图片咨询</div>
```

- [ ] **Step 4: Add runtime scope initialization**

At the beginning of the main inline script, before `feather.replace()`, add:

```javascript
const GUIDE_RUNTIME_MODE =
    window.__XIAORO_RUNTIME_SCOPE__ === 'slice1_text_sunscreen';
```

After DOM element lookup, add:

```javascript
const runtimeStatusPill = document.getElementById('runtimeStatusPill');
if (GUIDE_RUNTIME_MODE) {
    runtimeStatusPill.textContent = 'Slice 1 · 文本防晒';
    imageUploadBtn.style.display = 'none';
    imageInput.disabled = true;
}
```

- [ ] **Step 5: Disable unsupported feedback and image interactions**

At the start of `addFeedbackButtons` add:

```javascript
if (GUIDE_RUNTIME_MODE) return;
```

At the start of the image upload button click handler add:

```javascript
if (GUIDE_RUNTIME_MODE) return;
```

At the start of the image input change handler add:

```javascript
if (GUIDE_RUNTIME_MODE) return;
```

At the start of the chat input area drop handler, after `preventDefault`, add:

```javascript
if (GUIDE_RUNTIME_MODE) return;
```

- [ ] **Step 6: Run the frontend scope tests and verify GREEN**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/runtime/test_frontend_scope.py
```

Expected: `2 passed`.

- [ ] **Step 7: Run legacy frontend static contracts**

Run:

```bash
python3 -m pytest -q \
  tests/test_unified_chat_contract.py::UnifiedChatContractTest::test_frontend_keeps_display_only_and_does_not_make_image_decisions
```

Expected: PASS when the legacy test environment dependencies are available. If collection is blocked by a missing pre-existing legacy dependency such as `openai`, record the exact missing module and rely on the new frontend scope tests plus browser gate; do not install the entire legacy stack into the clean runtime venv.

- [ ] **Step 8: Commit**

```bash
git add app/static/chat.html tests/guide/runtime/test_frontend_scope.py
git commit -m "feat(frontend): expose clean runtime scope"
```

---

### Task 5: Add the Locked Runtime and Browser Release Gate

**Files:**
- Create: `tools/guide_gates/runtime_browser_smoke.py`

- [ ] **Step 1: Add the Playwright smoke script**

Create `tools/guide_gates/runtime_browser_smoke.py`:

```python
from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8765/chat",
    )
    parser.add_argument(
        "--screenshot",
        type=Path,
        default=Path("/tmp/xiaoro-guide-runtime.png"),
    )
    args = parser.parse_args()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page_errors: list[str] = []
        failed_images: list[str] = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "response",
            lambda response: failed_images.append(response.url)
            if "/static/images/products/" in response.url
            and response.status != 200
            else None,
        )
        page.goto(args.url, wait_until="networkidle")
        expect(
            page.locator("#runtimeStatusPill")
        ).to_have_text("Slice 1 · 文本防晒")
        expect(page.locator("#imageUploadBtn")).to_be_hidden()
        page.fill("#chatInput", "500 内适合油敏肌的防晒")
        page.click("#sendBtn")
        expect(
            page.locator(".recommendation-card").first
        ).to_be_visible(timeout=20000)
        expect(
            page.locator("text=真实商品图").first
        ).to_be_visible(timeout=20000)
        expect(
            page.locator(".recommendation-link").first
        ).to_be_visible(timeout=20000)
        assert page.locator(".recommendation-card").count() == 3
        assert page.locator(".message-feedback").count() == 0
        assert not page_errors, page_errors
        assert not failed_images, failed_images
        page.screenshot(path=str(args.screenshot), full_page=True)
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the full locked HTTP gate**

Run:

```bash
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  -c pytest-guide.ini
/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q \
  tests/guide/runtime
python3 app/guide/check_boundaries.py app/guide
python3 app/guide/check_boundaries.py app/guide_runtime
git diff --check
```

Expected:

- all guide/runtime tests PASS;
- both boundary scans PASS;
- no whitespace errors.

- [ ] **Step 3: Verify CWD-independent startup from `/tmp`**

Run:

```bash
cd /tmp
PYTHONPATH=/Users/bytedance/Desktop/xiaoro-fresh \
  /tmp/xiaoro-guide-runtime-venv/bin/uvicorn \
  app.guide_runtime.app:app \
  --host 127.0.0.1 --port 8765
```

In another process run:

```bash
curl --fail http://127.0.0.1:8765/health
curl --fail --no-buffer \
  -H 'Content-Type: application/json' \
  -d '{"message":"500 内适合油敏肌的防晒","stream":true}' \
  http://127.0.0.1:8765/api/v1/chat/stream
```

Expected:

- health contains `"scope":"slice1_text_sunscreen"`;
- stream starts with `event: start`;
- stream contains `event: products`;
- stream ends with one `event: end`.

- [ ] **Step 4: Run the browser gate against the formal runtime**

First inspect the helper interface:

```bash
python3 /Users/bytedance/.trae-cn/skills/webapp-testing/scripts/with_server.py \
  --help
```

Then run:

```bash
python3 /Users/bytedance/.trae-cn/skills/webapp-testing/scripts/with_server.py \
  --server "cd /tmp && PYTHONPATH=/Users/bytedance/Desktop/xiaoro-fresh /tmp/xiaoro-guide-runtime-venv/bin/uvicorn app.guide_runtime.app:app --host 127.0.0.1 --port 8765" \
  --port 8765 \
  -- python3 tools/guide_gates/runtime_browser_smoke.py \
    --screenshot /tmp/xiaoro-guide-runtime.png
```

Expected: exit 0 and screenshot
`/tmp/xiaoro-guide-runtime.png`.

- [ ] **Step 5: Confirm protected files and ranking SHA**

Run:

```bash
git diff --name-only fec2de0..HEAD
shasum -a 256 app/guide/decision/deterministic_ranking.py
```

Expected:

- no `app/services/**`, `app/database/**` or `app/main.py` changes;
- ranking SHA remains
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`.

- [ ] **Step 6: Commit the release gate**

```bash
git add tools/guide_gates/runtime_browser_smoke.py
git commit -m "test(runtime): gate clean guide startup"
```

---

## Final Acceptance Checklist

- [ ] Fresh minimal venv installs without legacy packages.
- [ ] `app.guide_runtime.app` imports without forbidden modules.
- [ ] Canonical and image assets use repo-absolute paths.
- [ ] Orchestrator is constructed once per app process.
- [ ] `/health` reports the exact Slice 1 scope.
- [ ] `/chat` disables cache and injects runtime scope.
- [ ] `/static` serves real product images.
- [ ] `/api/v1/chat/stream` returns the locked 11 product IDs.
- [ ] Invalid budgets produce visible clarification.
- [ ] Image requests receive an honest unsupported message.
- [ ] Internal exceptions do not leak.
- [ ] Guide runtime never falls back to legacy Agent.
- [ ] Runtime page hides image and feedback controls.
- [ ] Browser renders three cards with real images and links.
- [ ] Browser has no uncaught page errors.
- [ ] CWD-independent startup succeeds from `/tmp`.
- [ ] Existing guide/slice0 gate remains green.
- [ ] Both boundary scans report zero violations.
- [ ] Protected legacy files are unchanged.
- [ ] Deterministic ranking SHA is unchanged.

## Stop Condition

Slice 1.2 is complete only when the fresh minimal venv, HTTP integration tests,
`/tmp` Uvicorn launch and Playwright browser gate all pass. Until then, do not
start category expansion, multi-turn, image recognition or feedback persistence.
