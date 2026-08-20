# 周末集成与最终收口 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 集成入口、数据和意图三个 track，物理删除旧聊天链，并在受监管测试下完成最终机械与浏览器验收。

**Architecture:** Integration Writer 串行接收三个冻结 track 提交，先切 composition，再生成 importer inventory，最后删除已证明不可达的旧链。所有长命令由统一 bounded runner 管理进程组、心跳、TERM/KILL 和结果文件。

**Tech Stack:** Git、Python 3.11、AST、subprocess/process group、pytest、compileall、FastAPI、Playwright

---

## Integration Writer 独占文件

- `app/guide_runtime/composition.py`
- `app/main.py`
- `app/config.py`
- `app/services/__init__.py`
- `app/tasks/worker.py`
- `.trae/specs/complete-guide-closure-continuously/tasks.md`
- `.trae/specs/complete-guide-closure-continuously/checklist.md`
- `.trae/specs/complete-guide-closure-continuously/progress.md`
- `docs/audits/guide-closure/**`
- 本计划列出的 `git rm` 文件

任何 track writer 不得修改这些文件。

### Task 1: 集成前冻结和证据核对

**Files:**
- Verify only

- [ ] **Step 1: 核对三个 track 提交**

每个 track 必须提供：

```text
track_name
source_commit
focused_command
focused_result
diffcheck_result
known_blockers
```

拒绝集成以下状态：

- 工作区脏；
- track commit 不是 `rebuild` 当前 HEAD 的可验证提交/祖先；
- focused gate 未运行或失败；
- 修改越过文件所有权；
- 使用第二个 formal audit key；
- 原始 HTML、Key、用户正文或 private candidate queue 被加入 Git。

- [ ] **Step 2: 核对唯一正式审计**

```bash
wc -l docs/audits/guide-closure/audit_ledger.csv
cut -d, -f3,9 docs/audits/guide-closure/audit_ledger.csv
```

Expected:

- 1 行表头 + 1 行数据；
- audit key 仍为
  `b874c83c4f79b594a80de475b9a353755b27a9b90e7dd03a743e392aad40d0da`；
- `real_invocations=1`；
- 本计划不调用 formal audit。

- [ ] **Step 3: 核对安全进程状态**

```bash
ps -axo pid=,ppid=,pgid=,etime=,command= | \
  awk 'BEGIN{IGNORECASE=1}
  /run_real_intent_ab|intent_model_ab|pytest|uvicorn|playwright/ &&
  $0 !~ /awk/ {print}'
```

Expected: no output。

### Task 2: 增加受监管 bounded runner

**Files:**
- Create: `tools/guide_gates/run_bounded_command.py`
- Create: `tests/guide/tools/test_run_bounded_command.py`

- [ ] **Step 1: 写超时和进程组 RED**

```python
def test_runner_emits_heartbeat_and_returns_child_code(tmp_path: Path) -> None:
    result = run_bounded(
        [sys.executable, "-c", "print('done')"],
        timeout_seconds=5,
        heartbeat_seconds=1,
        output_path=tmp_path / "run.log",
    )
    assert result.returncode == 0
    assert result.timed_out is False


def test_runner_terminates_process_group_on_timeout(tmp_path: Path) -> None:
    result = run_bounded(
        [
            sys.executable,
            "-c",
            (
                "import subprocess,sys,time;"
                "subprocess.Popen([sys.executable,'-c','import time;"
                "time.sleep(60)']);time.sleep(60)"
            ),
        ],
        timeout_seconds=1,
        heartbeat_seconds=0.2,
        output_path=tmp_path / "timeout.log",
    )
    assert result.timed_out is True
    assert result.term_sent is True
    assert no_process_contains("time.sleep(60)")
```

- [ ] **Step 2: 实现 runner**

核心流程：

```python
process = subprocess.Popen(
    command,
    cwd=cwd,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    start_new_session=True,
    env=env,
)
```

- reader thread 持续写 mode-0600 log；
- 每 `heartbeat_seconds` 向 stderr 输出
  `heartbeat elapsed=30 output_lines=12` 这种只含计数的状态行；
- 达到 timeout：

```python
os.killpg(process.pid, signal.SIGTERM)
process.wait(timeout=5)
```

- TERM 后仍存活：

```python
os.killpg(process.pid, signal.SIGKILL)
```

- finally 必须 wait reader、关闭 fd、写 JSON summary；
- 不把环境变量值写入 summary；
- command 中检测到 `GUIDE_LLM_API_KEY=` 或 `Authorization` 时拒绝执行。

CLI：

```bash
python tools/guide_gates/run_bounded_command.py \
  --timeout-seconds 1800 \
  --heartbeat-seconds 30 \
  --output /private/tmp/gate.log \
  --summary /private/tmp/gate.json \
  -- \
  /private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q tests/guide/runtime/test_runtime_http.py
```

- [ ] **Step 3: GREEN 和 Commit**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/tools/test_run_bounded_command.py
git add \
  tools/guide_gates/run_bounded_command.py \
  tests/guide/tools/test_run_bounded_command.py
git commit -m "test(guide): supervise long-running closure gates"
```

### Task 3: 将 composition 切换为两步 adapter

**Files:**
- Modify: `app/guide_runtime/composition.py:306-384`
- Modify: `tests/guide/runtime/test_composition_understanding.py`
- Modify: `tests/guide/runtime/test_consultation_vertical_composition.py`

- [ ] **Step 1: 写 composition RED**

```python
def test_ready_config_builds_two_stage_understanding(
    monkeypatch,
    tmp_path,
) -> None:
    configure_ready_llm(monkeypatch)
    understanding = build_text_understanding(state_dir=tmp_path)
    assert isinstance(understanding, ParallelUnderstanding)
    assert isinstance(
        understanding._semantic,
        TwoStageCachedSemanticPort,
    )


def test_missing_key_remains_exact_only() -> None:
    assert isinstance(
        build_text_understanding(),
        ExactOnlyTextUnderstanding,
    )
```

- [ ] **Step 2: 修改 lazy composition**

Key 缺失仍返回 exact-only。Key + model 就绪时：

```python
from app.guide.adapters.llm.siliconflow_two_stage_intent import (
    SiliconFlowTwoStageIntentAdapter,
)
from app.guide.understanding.two_stage_semantic import (
    TwoStageCachedSemanticPort,
)

adapter = SiliconFlowTwoStageIntentAdapter.from_config(config)
cache = IntentProposalCache(
    state_root / "intent_cache.sqlite3",
    trusted_state_root=state_root,
)
semantic = TwoStageCachedSemanticPort(
    delegate=adapter,
    cache=cache,
    provider=adapter.provider,
    model=adapter.model,
)
return ParallelUnderstanding(semantic=semantic)
```

删除 composition 对旧单阶段 `INTENT_PROMPT_VERSION` 的依赖。

显式注入 `semantic_intent` 仍用于测试，但必须满足 `SemanticIntentPort`。

- [ ] **Step 3: GREEN 和 Commit**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/runtime/test_composition_understanding.py \
  tests/guide/runtime/test_consultation_vertical_composition.py
git add \
  app/guide_runtime/composition.py \
  tests/guide/runtime/test_composition_understanding.py \
  tests/guide/runtime/test_consultation_vertical_composition.py
git commit -m "feat(runtime): compose staged semantic understanding"
```

### Task 4: 建立旧链 importer inventory

**Files:**
- Create: `tools/guide_gates/inventory_legacy_chat_importers.py`
- Create: `tests/guide/tools/test_inventory_legacy_chat_importers.py`
- Generate: `docs/audits/guide-closure/legacy_importers_before.json`

- [ ] **Step 1: 写 AST 和字符串目标 RED**

fixture 覆盖：

```python
import app.services.agent
from app.services.v2 import presenter
import importlib
importlib.import_module("app.services.intent")
__import__("app.services.v2.agent")
CELERY_TARGET = "app.services.agent.ShoppingAgent"
```

断言 inventory 分类：

```python
assert result.direct_imports == 2
assert result.dynamic_imports == 2
assert result.string_targets == 1
```

- [ ] **Step 2: 实现 inventory**

扫描固定 roots：

```python
ROOTS = ("app", "tests", "scripts", "tools")
TARGETS = (
    "app.services.agent",
    "app.services.intent",
    "app.services.conversation",
    "app.services.v2",
)
```

AST 检查：

- `Import`；
- `ImportFrom`；
- `importlib.import_module("app.services.intent")` 这类 literal dynamic import；
- `__import__("app.services.v2.agent")` 这类 literal built-in import；
- 字符串常量中的完整模块目标；
- Celery include/task 字符串。

输出按 path/line/module 排序，不读 `__pycache__`，不把源码正文写入报告。

- [ ] **Step 3: 生成删除前 inventory**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python \
  tools/guide_gates/inventory_legacy_chat_importers.py \
  --root . \
  --output docs/audits/guide-closure/legacy_importers_before.json
jq '.counts' docs/audits/guide-closure/legacy_importers_before.json
```

Expected: 非零；它是删除输入，不是失败。

- [ ] **Step 4: Commit**

```bash
git add \
  tools/guide_gates/inventory_legacy_chat_importers.py \
  tests/guide/tools/test_inventory_legacy_chat_importers.py \
  docs/audits/guide-closure/legacy_importers_before.json
git commit -m "docs(guide): inventory legacy chat importers"
```

### Task 5: 收缩 app.main 和后台任务

**Files:**
- Replace: `app/main.py`
- Modify: `app/config.py`
- Modify: `app/services/__init__.py`
- Modify: `app/tasks/worker.py`
- Delete: `app/tasks/product/tasks.py`
- Modify: `docker-compose.yml`
- Modify: `docker-compose.prod.yml`
- Test: `tests/guide/runtime/test_import_boundary.py`
- Test: `tests/guide/tools/test_inventory_legacy_chat_importers.py`

- [ ] **Step 1: 写兼容导出 RED**

```python
def test_app_main_is_guide_compatibility_export() -> None:
    from app.guide_runtime.app import app as guide_app
    from app.main import app as compatibility_app
    assert compatibility_app is guide_app
```

源码断言：

```python
source = Path("app/main.py").read_text()
assert "app.database" not in source
assert "app.services" not in source
assert "include_router" not in source
```

- [ ] **Step 2: 替换 app.main**

完整内容：

```python
"""Compatibility export for the Guide-only runtime."""

from app.guide_runtime.app import app, create_app

__all__ = ["app", "create_app"]
```

- [ ] **Step 3: 清除旧聊天配置**

删除：

```python
USE_V2_AGENT
INTENT_LLM_ENABLED
INTENT_LLM_CONFIDENCE_THRESHOLD
V2_DISABLE_LLM
V2_STATE_MACHINE_ENABLED
```

只有 inventory 证明无剩余 importer 后才删其他 V2 专属设置。

将 `app/services/__init__.py` 改成无 eager import：

```python
"""Non-chat service package.

The public runtime is owned by app.guide_runtime and does not import this
package.
"""
```

- [ ] **Step 4: 删除 Celery 聊天推荐任务**

从 `worker.py` 删除 `tasks.product.recommend` 和 `ShoppingAgent` import。Celery include
删除 `app.tasks.product.tasks`。`git rm app/tasks/product/tasks.py`。

保留 evaluation/rag/image 任务，但它们不能 import old Agent/Intent/V2。

Compose 若保留 celery 服务，健康检查不能依赖已删除的 product queue。

- [ ] **Step 5: GREEN 和 Commit**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/runtime/test_import_boundary.py \
  tests/guide/tools/test_inventory_legacy_chat_importers.py
git add \
  app/main.py app/config.py app/services/__init__.py \
  app/tasks/worker.py docker-compose.yml docker-compose.prod.yml \
  tests/guide/runtime/test_import_boundary.py \
  tests/guide/tools/test_inventory_legacy_chat_importers.py
git rm app/tasks/product/tasks.py
git commit -m "refactor(runtime): detach default runtime from legacy chat"
```

### Task 6: 物理删除旧聊天链和专属测试脚本

**Files:**
- Delete: `app/api/v1/chat.py`
- Delete: `app/services/agent.py`
- Delete: `app/services/intent.py`
- Delete: `app/services/conversation.py`
- Delete: `app/services/v2/`
- Delete conditionally: `app/prompts/intent_prompts.py`
- Delete conditionally: `app/prompts/test_intent_classifier.py`
- Delete old-only tests/scripts listed below

- [ ] **Step 1: 再跑 importer inventory**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python \
  tools/guide_gates/inventory_legacy_chat_importers.py \
  --root . \
  --output /private/tmp/legacy-importers-after-routing.json
jq '.entries' /private/tmp/legacy-importers-after-routing.json
```

先处理活动 runtime importer；tests/scripts importer 可以通过删除其 owner 文件清零。

- [ ] **Step 2: 删除固定旧源码**

```bash
git rm \
  app/api/v1/chat.py \
  app/services/agent.py \
  app/services/intent.py \
  app/services/conversation.py \
  app/services/v2/__init__.py \
  app/services/v2/agent.py \
  app/services/v2/intent_classifier.py \
  app/services/v2/models.py \
  app/services/v2/presenter.py \
  app/services/v2/ranker.py \
  app/services/v2/retriever.py \
  app/services/v2/router.py \
  app/services/v2/semantic_embedding_intent.py \
  app/services/v2/semantic_intent_retriever.py \
  app/services/v2/state.py \
  app/services/v2/turn_parser.py
```

不删除 `__pycache__`（ignored，不进 Git）；执行后可清本地缓存，但不提交。

- [ ] **Step 3: 删除旧专属 tests/scripts**

```bash
git rm \
  tests/test_intent_integration.py \
  tests/test_unified_chat_contract.py \
  tests/test_v2_image_and_frontend_regressions.py \
  tests/test_v2_state_machine.py \
  scripts/batch_backend_test.py \
  scripts/e2e_regression_test.py \
  scripts/intent_baseline_probe.py \
  scripts/layered_test_30.py \
  scripts/llm_e2e_test.py \
  scripts/llm50_quality_test.py \
  scripts/quick_regression.py \
  scripts/test_v2_semantic_matrix.py
```

若某测试同时覆盖 Guide 外部合同，先迁移“公开合同”断言到 `tests/guide/**`，不得复制旧
内部函数。

- [ ] **Step 4: 条件删除旧 prompt**

运行：

```bash
rg -n 'app\\.prompts\\.(intent_prompts|test_intent_classifier)' \
  app tests scripts tools
```

无 Guide/非聊天 importer 时：

```bash
git rm \
  app/prompts/intent_prompts.py \
  app/prompts/test_intent_classifier.py
```

有非聊天 importer 时保留，并在 importer 报告写明 owner；不得为了删除而搬运旧代码。

- [ ] **Step 5: 生成删除后 inventory**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python \
  tools/guide_gates/inventory_legacy_chat_importers.py \
  --root . \
  --output docs/audits/guide-closure/legacy_importers_after.json
jq '.counts' docs/audits/guide-closure/legacy_importers_after.json
```

Expected: direct/dynamic/string/runtime/test/script/background 全部 0。

- [ ] **Step 6: compile/import RED 优先**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m compileall -q \
  app tools tests/guide
/private/tmp/xiaoro-guide-runtime-venv/bin/python - <<'PY'
import app.main
import app.guide_runtime.app
assert app.main.app is app.guide_runtime.app.app
PY
```

任何 missing import 必须回到 importer owner 删除/迁移，不恢复旧模块占位文件。

- [ ] **Step 7: Commit**

```bash
git add -A \
  app tests scripts tools \
  docs/audits/guide-closure/legacy_importers_after.json
git commit -m "refactor(guide): remove unreachable legacy chat chain"
```

### Task 7: 更新数据证据但不越权 promotion

**Files:**
- Integrate track B commits
- Verify data assets

- [ ] **Step 1: 核对错误报告已修正**

```bash
rg -n \
  'locked_review_sources_found=3|locked_review_sources_missing=0' \
  docs/audits/guide-closure/data/source_inventory_summary.md
```

Expected: both present。

- [ ] **Step 2: 核对 promotion 决策**

```bash
jq '.automatic_approvals,.automatic_reviewers,.promotion_invocations' \
  docs/audits/guide-closure/data/candidate_queue_summary.json
```

- 没有用户批准：三项都为 0，生产 fact 可保持 0；
- 有用户批准：automatic 两项仍为 0，promotion 次数等于明确批准批次；
- 不允许把 pending 直接当 approved。

- [ ] **Step 3: 保护资产**

```bash
shasum -a 256 \
  data/canonical/core_products_v1_manifest.json \
  data/canonical/core_products_v1.jsonl \
  app/guide/decision/deterministic_ranking.py \
  data/guide_review_sources/approved_tmall_feed_reviews_v1_manifest.json \
  data/guide_review_sources/approved_tmall_feed_reviews_v1.jsonl
```

Expected:

```text
e0430a244af451a3fa73642295c4a79128e1622dfeed19ff8140eda9f2df0c69
0ba95df8c38d39f5bc0d73a32c318b157903abb64778c3e7b0acebfb75e95734
4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f
2d4acdb1251e1b65d2b92fb2b052734f58b56cd4cd558e783c0391432c630460
22bac50e053a621826c831565b3a18e1df3592049ac35377298bac0ab0536171
```

### Task 8: 分层机械和测试收口

**Files:**
- Verify only

- [ ] **Step 1: focused suites（20 分钟硬超时）**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python \
  tools/guide_gates/run_bounded_command.py \
  --timeout-seconds 1200 \
  --heartbeat-seconds 30 \
  --output /private/tmp/guide-focused.log \
  --summary /private/tmp/guide-focused.json \
  -- \
  /private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/understanding \
  tests/guide/intent \
  tests/guide/adapters \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/application/test_cross_worker_text_state.py \
  tests/guide/runtime/test_composition_understanding.py \
  tests/guide/runtime/test_import_boundary.py \
  tests/guide/tools
```

Expected: returncode 0，timed_out false。

- [ ] **Step 2: Guide full（30 分钟硬超时）**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python \
  tools/guide_gates/run_bounded_command.py \
  --timeout-seconds 1800 \
  --heartbeat-seconds 30 \
  --output /private/tmp/guide-full.log \
  --summary /private/tmp/guide-full.json \
  -- \
  /private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q tests/guide
```

- [ ] **Step 3: 剩余 tests（30 分钟硬超时）**

先用 `pytest --collect-only`，若仍收集旧已删除模块，修测试 owner；不要恢复旧模块。

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python \
  tools/guide_gates/run_bounded_command.py \
  --timeout-seconds 1800 \
  --heartbeat-seconds 30 \
  --output /private/tmp/tests-full.log \
  --summary /private/tmp/tests-full.json \
  -- \
  /private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest -q tests
```

- [ ] **Step 4: 机械门禁**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m compileall -q \
  app tools tests
/private/tmp/xiaoro-guide-runtime-venv/bin/python \
  -m app.guide.check_boundaries app/guide
/private/tmp/xiaoro-guide-runtime-venv/bin/python \
  -m app.guide.check_boundaries app/guide_runtime
git diff --check
jq '.counts' docs/audits/guide-closure/legacy_importers_after.json
```

Expected: 0 violations、0 importers。

- [ ] **Step 5: 状态门禁**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/application/test_cross_worker_text_state.py \
  tests/guide/adapters/state/test_sqlite_conversation_state.py \
  tests/guide/runtime/test_sse.py
```

必须覆盖 2/4 worker、进程重启、stale/CAS、断流不提交、终态一次提交、澄清两轮。

出现同一层第二次失败后停止，不做第三轮盲修。

### Task 9: 浏览器和公开 API 收口

**Files:**
- Create: `tools/guide_gates/run_runtime_browser_matrix.py`
- Create: `tests/guide/tools/test_run_runtime_browser_matrix.py`
- Verify: `tools/guide_gates/runtime_browser_smoke.py`
- Verify: `tools/guide_gates/runtime_browser_adversarial.py`

- [ ] **Step 1: 写 server/browser 生命周期 RED**

```python
def test_browser_matrix_always_stops_server_process_group(
    tmp_path: Path,
) -> None:
    result = run_browser_matrix(
        server_command=fake_http_server_command(),
        browser_commands=(successful_probe_command(),),
        ready_url="http://127.0.0.1:8765/health",
        timeout_seconds=10,
        output_dir=tmp_path,
    )
    assert result.returncode == 0
    assert result.server_term_sent is True
    assert not process_is_alive(result.server_pid)


def test_failed_browser_probe_still_stops_server(tmp_path: Path) -> None:
    result = run_browser_matrix(
        server_command=fake_http_server_command(),
        browser_commands=(failing_probe_command(),),
        ready_url="http://127.0.0.1:8765/health",
        timeout_seconds=10,
        output_dir=tmp_path,
    )
    assert result.returncode != 0
    assert not process_is_alive(result.server_pid)
```

- [ ] **Step 2: 实现单进程受监管 matrix**

`run_runtime_browser_matrix.py`：

- 以 `start_new_session=True` 启动 Uvicorn；
- 最多 30 秒轮询 `/health`；
- 依次运行 normal 和 adversarial browser，每个子命令 10 分钟硬超时；
- 每 30 秒输出心跳；
- 任一 probe 失败立即停止后续 probe；
- finally 对 server 进程组 TERM，5 秒后 KILL；
- 输出 mode-0600 JSON summary，不包含环境变量值。

默认命令固定为：

```python
SERVER_COMMAND = (
    sys.executable,
    "-m",
    "uvicorn",
    "app.guide_runtime.app:app",
    "--host",
    "127.0.0.1",
    "--port",
    "8765",
)
BROWSER_COMMANDS = (
    (
        sys.executable,
        "tools/guide_gates/runtime_browser_smoke.py",
        "--url",
        "http://127.0.0.1:8765/chat",
    ),
    (
        sys.executable,
        "tools/guide_gates/runtime_browser_adversarial.py",
        "--url",
        "http://127.0.0.1:8765/chat",
    ),
)
```

- [ ] **Step 3: 运行 RED/GREEN**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python \
  -m pytest -c pytest-guide.ini -q \
  tests/guide/tools/test_run_runtime_browser_matrix.py
/private/tmp/xiaoro-guide-runtime-venv/bin/python \
  tools/guide_gates/run_runtime_browser_matrix.py \
  --timeout-seconds 1800 \
  --heartbeat-seconds 30 \
  --output-dir /private/tmp/xiaoro-browser-matrix
```

- [ ] **Step 4: 验证 normal browser 结果**

读取 matrix summary 中 normal probe，验证：

- 页面加载；
- message/stream 一致；
- 推荐、追问、预算修订、图片；
- 单终态；
- 无 console/page/SSE/HTTP/image error。

- [ ] **Step 5: 验证 adversarial browser 结果**

读取 matrix summary 中 adversarial probe，验证：

- XSS 不执行；
- session switch 不串状态；
- late event 不污染新会话；
- disconnect 不提交；
- 未支持文本两轮澄清后 scope notice；
- 任意失败无 legacy fallback。

- [ ] **Step 6: 进程审计**

```bash
ps -axo pid=,ppid=,pgid=,etime=,command= | \
  awk 'BEGIN{IGNORECASE=1}
  /pytest|uvicorn|playwright|run_real_two_stage_intent_ab/ &&
  $0 !~ /awk/ {print}'
```

Expected: no output。

- [ ] **Step 7: Commit**

```bash
git add \
  tools/guide_gates/run_runtime_browser_matrix.py \
  tests/guide/tools/test_run_runtime_browser_matrix.py
git commit -m "test(runtime): supervise final browser matrix"
```

### Task 10: 最终文档和状态

**Files:**
- Modify: `.trae/specs/complete-guide-closure-continuously/tasks.md`
- Modify: `.trae/specs/complete-guide-closure-continuously/checklist.md`
- Append: `.trae/specs/complete-guide-closure-continuously/progress.md`
- Modify: `docs/audits/guide-closure/model_selection.md`
- Create: `docs/audits/guide-closure/final_handoff.md`

- [ ] **Step 1: 只按证据勾选**

必须满足才勾：

- Task 6：两步 gate 选出通过模型，或明确记录 Guide fail-closed 模式且完成定义已按批准
  设计更新；
- Task 8：默认入口、message/stream、澄清闭环全绿；
- Task 11：旧链删除且 importer 0；
- Task 12：所有受监管 gate 通过；
- Task 13：证据 hash、工作区和发布边界核对完成。

不得仅因截止日期勾选。

- [ ] **Step 2: final handoff**

写明：

```text
source_commit
Guide-only entrypoint
selected model / fail-closed mode
route/detail quality metrics
hard gate counts
15 product coverage counts
three locked HTML hashes
promotion decisions
legacy importer count
focused/full/runtime/browser results
formal audit invocation=1 repeat=0
not pushed / not deployed / no traffic switch
```

- [ ] **Step 3: 最终工作区**

```bash
git status --short
git diff --check
git log -12 --oneline
```

Expected: commit 前只有预期文档变更；最终提交后 clean。

- [ ] **Step 4: Commit**

```bash
git add \
  .trae/specs/complete-guide-closure-continuously/tasks.md \
  .trae/specs/complete-guide-closure-continuously/checklist.md \
  .trae/specs/complete-guide-closure-continuously/progress.md \
  docs/audits/guide-closure/model_selection.md \
  docs/audits/guide-closure/final_handoff.md
git commit -m "docs(guide): close three-track weekend delivery"
```

- [ ] **Step 5: 最终 checkpoint**

```text
已完成：Guide-only、15 商品数据、两步意图、旧链删除、全门禁
当前卡点：无 / 明确未完成项
剩余工作：无 / 明确列出
预计完成：2026-08-16
```

不 push、不 deploy、不切生产流量。
