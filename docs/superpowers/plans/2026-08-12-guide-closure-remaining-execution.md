# Guide Closure Remaining Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从当前 `rebuild` checkpoint 完成真实双模型 A/B、Guide-only、旧聊天链物理删除和最终机械收口，不重复已完成任务或正式审计。

**Architecture:** 保持“精确代码路 + 受限语义路 + session/profile 路 -> 唯一 `IntentSignalMerger` -> TaskPlan -> Guide 六层链路”。真实 A/B 是 cutover 的硬前置；Guide-only 全门禁通过后，才用依赖清单证明旧链不可达并执行 `git rm`。所有失败按最早 typed contract 归责，不在 API、Presenter、前端或旧 `app/services/**` 添加兼容补丁。

**Tech Stack:** Python 3.11/3.12、Pydantic v2、FastAPI/Starlette、SQLite CAS、httpx/SiliconFlow、pytest、Playwright、AST 静态依赖分析。

---

## Authority And Current Checkpoint

执行优先级：

1. `docs/superpowers/specs/2026-08-10-guide-intent-cutover-and-pragmatic-data-recovery-design.md`
2. `docs/superpowers/specs/2026-08-06-xiaoro-clean-growth-architecture-design.md`
3. `docs/superpowers/plans/2026-08-11-guide-intent-cutover-closure.md`
4. `.trae/specs/complete-guide-closure-continuously/spec.md`
5. `.trae/specs/complete-guide-closure-continuously/tasks.md`
6. `.trae/specs/complete-guide-closure-continuously/checklist.md`
7. `docs/superpowers/prompts/2026-08-11-guide-closure-resume-after-strict-audit.md`
8. 本计划；本计划只细化剩余执行，不覆盖前述产品语义。

当前冻结事实：

- 实施仓库：`/Users/bytedance/Desktop/xiaoro-fresh`，分支 `rebuild`。
- 计划生成时 HEAD：`cd99287176684d1c357b319624f5651ed0123b5f`。
- Tasks 1-5、7、9、10 已完成；Task 6 完成 6.1-6.4d。
- Tasks 6.5-6.7、8、11、12、13 未完成。
- tasks `71/110`，checklist `142/220`。
- 唯一 audit key：
  `b874c83c4f79b594a80de475b9a353755b27a9b90e7dd03a743e392aad40d0da`。
- `formal_full_file_audit_invocations=1`，`repeat=0`；禁止第二次正式审计。
- 当前 `GUIDE_LLM_API_KEY=MISSING`；Key 到位前不得开始 Task 8。
- `data/canonical/**`、`app/guide/decision/deterministic_ranking.py` 和 6 条批准评论受保护。
- 不 push、不 deploy、不切生产流量。

## File Responsibility Map

### Task 6.5-6.7

- Execute: `tools/guide_gates/run_real_intent_ab.py`
- Read/verify: `tools/guide_gates/intent_model_ab.py`
- Read/verify: `tools/guide_gates/guide_pipeline_evaluator.py`
- Read/verify: `tools/guide_gates/production_routing_gate.py`
- Test: `tests/guide/tools/test_intent_model_ab.py`
- Test: `tests/guide/tools/test_run_real_intent_ab.py`
- Test: `tests/guide/tools/test_production_routing_gate.py`
- Input: `tests/fixtures/guide/intent/semantic_intent_ab_v1.jsonl`
- Create after a real run: `docs/audits/guide-closure/model_selection.md`

### Task 8

- Modify: `app/guide/session_contract.py`
- Modify: `app/guide/feedback/contracts.py`
- Modify: `app/guide/feedback/ports.py`
- Modify: `app/guide/intent/contracts.py`
- Modify: `app/guide/intent/task_planning.py`
- Modify: `app/guide/understanding/context_resolver.py`
- Modify: `app/guide/application/text_recommendation_flow.py`
- Modify: `app/guide/application/chat_api_adapter.py`
- Modify: `app/guide_runtime/sse.py`
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`
- Modify: `docker-compose.prod.yml`
- Modify: `start.sh`
- Modify: `README.md`
- Modify: `DEPLOY.md`
- Create: `tests/guide/runtime/test_guide_only_entrypoint.py`
- Test: `tests/guide/application/test_cross_worker_text_state.py`
- Test: `tests/guide/application/test_chat_api_adapter.py`
- Test: `tests/guide/runtime/test_runtime_http.py`
- Test: `tests/guide/runtime/test_import_boundary.py`

### Task 11

- Create: `tools/guide_gates/legacy_dependency_inventory.py`
- Create: `tests/guide/runtime/test_legacy_chat_removed.py`
- Modify: `app/main.py`
- Modify or delete after inventory: `app/api/v1/chat.py`
- Modify after inventory: `app/services/__init__.py`
- Modify or delete after inventory: `app/services/conversation.py`
- Modify after inventory: `app/tasks/product/tasks.py`
- Modify after inventory: `app/tasks/worker.py`
- Modify or delete after inventory: old prompt exports, V2 tests and V2 scripts
- Delete after proof: `app/services/v2/`
- Delete after proof: `app/services/agent.py`
- Delete after proof: `app/services/intent.py`

### Tasks 12-13

- Verify: all `tests/guide/**`
- Verify: remaining `tests/**`
- Verify: `tools/guide_gates/runtime_browser_*.py`
- Verify: image/consultation/feedback browser gates
- Verify: protected assets and dependency inventory
- Create: `docs/audits/guide-closure/final_handoff.md`
- Append: `.trae/specs/complete-guide-closure-continuously/progress.md`
- Update only from real evidence:
  `.trae/specs/complete-guide-closure-continuously/tasks.md`
  and `.trae/specs/complete-guide-closure-continuously/checklist.md`

## Global Execution Rules

- Run at most one heavy test, browser, server or A/B process at a time.
- Any process running longer than 30 seconds receives a status heartbeat and
  an OS-process audit; absence of output is not treated as progress.
- Every long process has a stage-specific hard timeout. On timeout, send
  `TERM`, wait briefly, send `KILL` only if needed, then prove the PID exited.
- Do not rerun a broad suite to diagnose one failure. Freeze the input, locate
  the earliest failing layer, write one RED, run the smallest focused suite.
- `app/services/**` remains read-only until Task 8 is completely green.
- Key material is never printed, searched, passed as a command argument,
  written to evidence, cached in an identity or committed.
- A/B raw evidence stays under `/private/tmp`; only normalized aggregates and
  hashes enter `model_selection.md`.

### Task 1: Resume Guard And External Precondition

**Files:**
- Read: `.trae/specs/complete-guide-closure-continuously/tasks.md`
- Read: `docs/audits/guide-closure/audit_ledger.csv`
- Read: `docs/audits/guide-closure/baseline_manifest.json`

- [ ] **Step 1: Prove the checkpoint is a legal successor**

Run:

```bash
git status --short --branch
git merge-base --is-ancestor b20a714c0bde21bd500228b94bcb67c79f5c52fe HEAD
git log -6 --oneline --decorate
```

Expected: branch `rebuild`, clean worktree, merge-base exit `0`, and HEAD equal
to the recorded checkpoint or a reviewed strict successor.

- [ ] **Step 2: Prove audit identity without invoking it**

Run:

```bash
cat docs/audits/guide-closure/audit_ledger.csv
```

Expected: exactly one data row, the fixed audit key, and
`real_invocations=1`. Do not call any audit tool.

- [ ] **Step 3: Check only Key presence**

Run:

```bash
if [ -n "${GUIDE_LLM_API_KEY:-}" ]; then
  printf 'GUIDE_LLM_API_KEY=PRESENT\n'
else
  printf 'GUIDE_LLM_API_KEY=MISSING\n'
fi
```

Expected before Task 6.5: `PRESENT`. If `MISSING`, stop here and report that a
fresh Key is the only external prerequisite. Do not enter Task 8.

- [ ] **Step 4: Verify the dedicated runtime environment**

Run:

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -c \
  'import anyio, sniffio; assert hasattr(sniffio, "current_async_library")'
```

Expected: exit `0`. If the isolated venv is corrupt, recreate that venv from
the repository's pinned dependencies; do not patch application code to hide an
environment failure.

### Task 2: Run The Frozen Real A/B (Spec Task 6.5)

**Files:**
- Execute: `tools/guide_gates/run_real_intent_ab.py`
- Test: `tests/guide/tools/test_intent_model_ab.py`
- Test: `tests/guide/tools/test_run_real_intent_ab.py`
- Test: `tests/guide/tools/test_production_routing_gate.py`

- [ ] **Step 1: Re-run only the Task 6 offline guard**

Run:

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/tools/test_intent_model_ab.py \
  tests/guide/tools/test_run_real_intent_ab.py \
  tests/guide/tools/test_production_routing_gate.py \
  tests/guide/tools/test_guide_pipeline_evaluator.py
```

Expected: PASS. This confirms the frozen pair, 128 cases, typed usage,
model-vertical/production-routing separation and zero offline legacy fallback.

- [ ] **Step 2: Run both frozen models against one case manifest**

Create a new, non-existing output directory name and run:

```bash
AB_DIR="/private/tmp/xiaoro-guide-intent-ab-$(git rev-parse --short HEAD)-$(date +%Y%m%d%H%M%S)"
PYTHONPATH=. /private/tmp/xiaoro-guide-runtime-venv/bin/python \
  tools/guide_gates/run_real_intent_ab.py \
  --cases tests/fixtures/guide/intent/semantic_intent_ab_v1.jsonl \
  --model deepseek-ai/DeepSeek-V4-Flash \
  --model deepseek-ai/DeepSeek-V3.2 \
  --output-dir "$AB_DIR"
```

Execution control:

- poll the PTY at least every 30 seconds;
- run no other heavy command concurrently;
- use a 45-minute process hard timeout for the complete 256-request run;
- if timed out, terminate and prove no runner process remains before retrying.

Exit meanings:

- `0`: at least one model passed all hard gates;
- `2`: configuration/Key/case input unavailable; no cutover;
- `3`: neither model passed; no cutover.

- [ ] **Step 3: Verify the generated evidence**

Run:

```bash
shasum -a 256 -c "$AB_DIR/SHA256SUMS"
/private/tmp/xiaoro-guide-runtime-venv/bin/python -c \
  'import json,sys; p=json.load(open(sys.argv[1])); print(json.dumps({"case_count":p["case_count"],"selected_model":p["selected_model"],"exit_code":p["exit_code"],"models":{k:v["hard_gates"] for k,v in p["models"].items()}},ensure_ascii=False,sort_keys=True))' \
  "$AB_DIR/summary.json"
```

Expected:

- `case_count=128`;
- a selected model is present;
- for the selected model, all four hard counts are AVAILABLE and `0`:
  `hard_constraint_override_count`,
  `forbidden_field_acceptance_count`,
  `wrong_product_selection_count`,
  `legacy_fallback_count`;
- `invalid_output_task_plan_invocation_count=0`;
- `task_plan_mismatch_count=0`;
- `critical_failure_count=0`.

Do not grep evidence for the Key value. Key non-persistence is proven by the
offline runner contract and by the fixed evidence schema.

- [ ] **Step 4: Handle a no-go at the earliest failing layer**

If exit code is `3`, inspect the normalized rows in this order:

```text
semantic proposal
-> exact constraints
-> merger trace
-> TaskPlan
-> retrieval/decision
-> public events
-> state
```

For each generalizable failure:

1. add one RED to the responsible existing focused test file;
2. make the smallest prompt/schema/context/merger fix;
3. run the focused test and Task 6 offline guard;
4. repeat the real A/B with a new output directory.

Maximum: three consecutive repair loops. If neither model passes after three
loops, write a NO-GO result and keep typed clarification. Never add a
sentence-specific production regex.

### Task 3: Freeze Model Selection (Spec Tasks 6.6-6.7)

**Files:**
- Create: `docs/audits/guide-closure/model_selection.md`
- Modify from evidence:
  `.trae/specs/complete-guide-closure-continuously/tasks.md`
- Modify from evidence:
  `.trae/specs/complete-guide-closure-continuously/checklist.md`
- Append: `.trae/specs/complete-guide-closure-continuously/progress.md`

- [ ] **Step 1: Select the model mechanically**

Selection rule:

```text
both pass      -> deepseek-ai/DeepSeek-V4-Flash
only V3.2 pass -> deepseek-ai/DeepSeek-V3.2
neither passes -> NO-GO, Task 8 forbidden
```

Do not choose from latency or cost when a model fails a hard gate.

- [ ] **Step 2: Write `model_selection.md`**

Generate the document from the normalized evidence:

```bash
AB_DIR="$AB_DIR" /private/tmp/xiaoro-guide-runtime-venv/bin/python - <<'PY'
import hashlib
import json
import os
from pathlib import Path

ab_dir = Path(os.environ["AB_DIR"])
summary = json.loads(
    (ab_dir / "summary.json").read_text(encoding="utf-8")
)
runtime = json.loads(
    (ab_dir / "runtime_metrics.json").read_text(encoding="utf-8")
)
selected = summary["selected_model"]
if not isinstance(selected, str):
    raise SystemExit("selected model is unavailable")
model = summary["models"][selected]
hard = model["hard_gates"]
metrics = runtime["models"][selected]
runtime_sha = hashlib.sha256(
    (ab_dir / "runtime_metrics.json").read_bytes()
).hexdigest()
required_zero = (
    "hard_constraint_override_count",
    "forbidden_field_acceptance_count",
    "invalid_output_task_plan_invocation_count",
    "wrong_product_selection_count",
    "legacy_fallback_count",
)
if any(hard[name] != 0 for name in required_zero):
    raise SystemExit("selected model failed a hard gate")
identity = next(
    item
    for item in summary["identity"]["model_identities"]
    if item["model"] == selected
)
lines = [
    "# Guide Semantic Model Selection",
    "",
    f"- runner: {summary['identity']['runner_schema_version']}",
    f"- prompt: {identity['prompt_version']}",
    (
        "- schema: "
        f"{summary['identity']['semantic_schema_version']}"
    ),
    f"- case_count: {summary['case_count']}",
    (
        "- case_manifest_sha256: "
        f"{summary['identity']['case_manifest_sha256']}"
    ),
    (
        "- stable_evidence_sha256: "
        f"{summary['stable_evidence_sha256']}"
    ),
    f"- runtime_metrics_sha256: {runtime_sha}",
    f"- selected_model: {selected}",
    *[f"- {name}: {hard[name]}" for name in required_zero],
    (
        "- usage: "
        + json.dumps(
            metrics["usage"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    ),
    f"- latency_p50_ms: {metrics['latency_ms']['p50']}",
    f"- latency_p95_ms: {metrics['latency_ms']['p95']}",
    (
        "- actual_cost_cny: "
        f"{metrics['usage']['actual_cost_cny']}"
    ),
]
Path(
    "docs/audits/guide-closure/model_selection.md"
).write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
```

Do not copy raw messages, provider bodies, profiles, product facts or secrets.

- [ ] **Step 3: Record completion and commit**

Only after the evidence exists, mark 6.5-6.7 and matching checklist rows.

Run:

```bash
git add \
  docs/audits/guide-closure/model_selection.md \
  .trae/specs/complete-guide-closure-continuously/tasks.md \
  .trae/specs/complete-guide-closure-continuously/checklist.md \
  .trae/specs/complete-guide-closure-continuously/progress.md
git commit -m "test(intent): select the real Guide semantic model"
```

Expected: one evidence commit; no raw `/private/tmp` output committed.

### Task 4: Persist Bounded Clarification State (Spec Task 8.4-8.5)

**Files:**
- Modify: `app/guide/session_contract.py`
- Modify: `app/guide/feedback/contracts.py`
- Modify: `app/guide/feedback/ports.py`
- Modify: `app/guide/intent/contracts.py`
- Modify: `app/guide/intent/task_planning.py`
- Modify: `app/guide/understanding/context_resolver.py`
- Modify: `app/guide/application/text_recommendation_flow.py`
- Test: `tests/guide/intent/test_task_planning.py`
- Test: `tests/guide/understanding/test_context_resolver.py`
- Test: `tests/guide/application/test_cross_worker_text_state.py`
- Test: `tests/guide/adapters/state/test_sqlite_conversation_state.py`
- Test: `tests/guide/runtime/test_runtime_http.py`

- [ ] **Step 1: Write RED contracts for a typed gap**

Add tests requiring:

- every `TaskPlan(mode="clarify")` has a typed `clarification_gap`;
- first unresolved gap persists with attempt `1`;
- the same gap can advance to `2`;
- a third request returns a fixed scope notice and does not select products;
- a different gap resets to attempt `1`;
- a successful understanding clears clarification state atomically;
- recommendation candidates/query context remain unchanged while clarification
  metadata advances;
- the next semantic call receives only the typed pending gap, never the prior
  question or raw turn text;
- message and stream endpoints expose the same version and terminal result;
- two orchestrators sharing SQLite see the same clarification count.

- [ ] **Step 2: Add the shared typed contract**

In `app/guide/session_contract.py` add:

```python
from enum import Enum


class ClarificationGap(str, Enum):
    GOAL = "goal"
    TOPIC = "topic"
    REFERENCE = "reference"
    BUDGET = "budget"
    CONCERN = "concern"
    HARD_CONSTRAINT = "hard_constraint"
```

In `app/guide/feedback/contracts.py` add:

```python
class ClarificationProgress(_StrictContract):
    gap: ClarificationGap
    attempts: int = Field(ge=1, le=2)
```

Add
`clarification_progress: ClarificationProgress | None = None` to
`ConversationSnapshot`. A snapshot is valid when it contains recommendation,
consultation, image-delivery or clarification state.

- [ ] **Step 3: Preserve gap identity through TaskPlan**

In `app/guide/intent/contracts.py`, add:

```python
clarification_gap: ClarificationGap | None = None
```

Contract rules:

- `mode="clarify"` requires both question and gap;
- `mode="recommend"` forbids both.

In `task_planning.py`, map:

- unsupported/non-recommendation goal -> `GOAL`;
- missing/ambiguous category -> `TOPIC`;
- ambiguous candidate/image/current reference -> `REFERENCE`;
- invalid budget -> `BUDGET`;
- serum efficacy/concern gap -> `CONCERN`;
- hard-constraint confirmation -> `HARD_CONSTRAINT`.

Question text remains code-generated from the typed gap; the LLM never writes
the final question.

- [ ] **Step 4: Project only the typed gap into semantic context**

In `app/guide/understanding/context_resolver.py`, map persisted gaps
`GOAL`, `TOPIC`, `REFERENCE`, `BUDGET` and `CONCERN` to the existing
`ClarificationCode` values and set
`SemanticContext.pending_clarification`. Map code-owned
`HARD_CONSTRAINT` to `None`; never expose the previous question, raw message,
candidate IDs or product facts.

The serialized SemanticContext shape is unchanged, so
`guide-semantic-intent-v2` and `guide-semantic-intent-prompt-v3` remain the
frozen A/B identities. The typed context value already participates in the
cache fingerprint.

- [ ] **Step 5: Implement bounded state transitions**

In `feedback/ports.py`, validate:

- a new gap starts at `1`;
- the same gap increments by exactly one and never exceeds `2`;
- clarification-only writes cannot mutate prior query context, candidates,
  image delivery or consultation state;
- a successful terminal recommendation may clear clarification progress;
- errors, stale requests and disconnects do not advance it.

In `text_recommendation_flow.py`, centralize clarification output in one helper:

```python
def _stream_bounded_clarification(
    self,
    turn: UserTurn,
    *,
    snapshot: ConversationSnapshot | None,
    gap: ClarificationGap,
    question: str,
) -> Iterator[SseEvent]:
    previous = (
        snapshot.clarification_progress
        if snapshot is not None
        else None
    )
    if (
        previous is not None
        and previous.gap == gap
        and previous.attempts >= 2
    ):
        yield IntentEvent(data=IntentData(mode="clarify"))
        yield ClarifyEvent(
            data=ClarifyData(
                question=(
                    "当前支持护肤、防晒、底妆、彩妆、洁面/卸妆和"
                    "香水导购；请明确品类、预算或要比较的商品。"
                )
            )
        )
        yield EndEvent(
            data=EndData(
                conversation_version=self._snapshot_version(snapshot)
            )
        )
        return

    attempts = (
        previous.attempts + 1
        if previous is not None and previous.gap == gap
        else 1
    )
    expected_version = self._snapshot_version(snapshot)
    progress = ClarificationProgress(
        gap=gap,
        attempts=attempts,
    )
    if snapshot is None:
        next_snapshot = ConversationSnapshot(
            session_id=turn.session_id,
            version=1,
            profile_owner=turn.profile_owner,
            clarification_progress=progress,
        )
    else:
        next_snapshot = snapshot.model_copy(
            update={
                "version": snapshot.version + 1,
                "clarification_progress": progress,
            },
            deep=True,
        )
    saved = self._conversation_state.save(
        next_snapshot,
        expected_version=expected_version,
    )
    yield IntentEvent(data=IntentData(mode="clarify"))
    yield ClarifyEvent(data=ClarifyData(question=question))
    yield EndEvent(
        data=EndData(conversation_version=saved.version)
    )
```

The helper saves attempt 1/2 through the existing
`PublicEventCommitConversationState` transaction. If the same gap is already
at 2, it emits the fixed supported-scope notice without a product event or
legacy call. `_visible_snapshot()` clears `clarification_progress` on success.

- [ ] **Step 6: Run focused RED/GREEN**

Run:

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/intent \
  tests/guide/understanding/test_context_resolver.py \
  tests/guide/adapters/state/test_sqlite_conversation_state.py \
  tests/guide/application/test_cross_worker_text_state.py \
  tests/guide/runtime/test_runtime_http.py
```

Expected: PASS, including cross-worker count, success reset, disconnect and
single-terminal assertions.

- [ ] **Step 7: Commit**

```bash
git add \
  app/guide/session_contract.py \
  app/guide/feedback/contracts.py \
  app/guide/feedback/ports.py \
  app/guide/intent/contracts.py \
  app/guide/intent/task_planning.py \
  app/guide/understanding/context_resolver.py \
  app/guide/application/text_recommendation_flow.py \
  tests/guide
git commit -m "feat(guide): persist bounded clarification progress"
```

### Task 5: Make Guide The Only Default Public Runtime (Spec Task 8)

**Files:**
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`
- Modify: `docker-compose.prod.yml`
- Modify: `start.sh`
- Modify: `README.md`
- Modify: `DEPLOY.md`
- Modify: `app/guide/application/chat_api_adapter.py`
- Modify: `app/guide_runtime/sse.py`
- Create: `tests/guide/runtime/test_guide_only_entrypoint.py`
- Test: `tests/guide/runtime/test_import_boundary.py`
- Test: `tests/guide/runtime/test_runtime_http.py`

- [ ] **Step 1: Write default-entry RED**

The test must inspect all six launch/documentation files and assert:

```python
assert "app.guide_runtime.app:app" in text
assert "app.main:app" not in text
```

Also import `app.guide_runtime.app` in a clean subprocess and reject modules
whose names equal or start with:

```text
app.services
app.database
redis
pymilvus
old V1/V2 Agent modules
```

- [ ] **Step 2: Write public-route RED**

Against `app.guide_runtime.app:create_app`, assert:

- `/api/v1/chat/message` and `/api/v1/chat/stream` both execute Guide;
- unsupported text emits typed clarification/scope notice;
- provider failure emits typed clarification or sanitized failure;
- no event owner or marker equals `legacy`;
- exactly one terminal result is exposed;
- image bundle errors remain typed and do not enter the old image payload path.

- [ ] **Step 3: Switch every default launcher**

Replace all default targets with:

```text
app.guide_runtime.app:app
```

Keep existing worker counts. In README/DEPLOY examples, document the selected
model as an explicit deployment variable. Read `selected_model` from
`model_selection.md` and write its actual literal ID
(`deepseek-ai/DeepSeek-V4-Flash` or `deepseek-ai/DeepSeek-V3.2`) into the
example; do not leave a template token.

Keep `GuideLlmConfig` fail-closed when a Key is present without an explicit
model; do not hide model identity behind an unversioned code fallback.

- [ ] **Step 4: Remove legacy naming from the Guide transport**

Rename `iter_slice1_guide_legacy_sse_events()` to
`iter_guide_sse_events()` and update Guide callers/tests. This function may
adapt typed Guide events to the public SSE contract, but it must not classify,
import or call a legacy owner.

Do not repair `app/api/v1/chat.py` or `app/services/**`. Once default launchers
use `app.guide_runtime`, the old route is handled by Task 11's unreachability
proof and deletion.

- [ ] **Step 5: Run Task 8 focused gates**

Run:

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/runtime/test_guide_only_entrypoint.py \
  tests/guide/runtime/test_import_boundary.py \
  tests/guide/runtime/test_runtime_http.py \
  tests/guide/runtime/test_sse.py \
  tests/guide/application/test_chat_api_adapter.py \
  tests/guide/application/test_cross_worker_text_state.py
```

Expected: PASS and zero legacy public execution.

- [ ] **Step 6: Run bounded HTTP/browser verification**

Start:

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/uvicorn \
  app.guide_runtime.app:app --host 127.0.0.1 --port 8765
```

Then, one at a time:

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python \
  tools/guide_gates/runtime_browser_smoke.py \
  --url http://127.0.0.1:8765/chat

/private/tmp/xiaoro-guide-runtime-venv/bin/python \
  tools/guide_gates/runtime_browser_adversarial.py \
  --url http://127.0.0.1:8765/chat \
  --evidence-dir /private/tmp/xiaoro-guide-adversarial

/private/tmp/xiaoro-guide-runtime-venv/bin/python \
  tools/guide_gates/runtime_browser_consultation.py \
  --url http://127.0.0.1:8765/chat
```

Expected: exit `0`, no page/SSE/XSS/cross-session/late-event error. Terminate
Uvicorn and prove the PID exited before continuing.

- [ ] **Step 7: Commit and mark Task 8 only after all gates pass**

```bash
git add \
  Dockerfile docker-compose.yml docker-compose.prod.yml \
  start.sh README.md DEPLOY.md \
  app/guide app/guide_runtime tests/guide \
  .trae/specs/complete-guide-closure-continuously
git commit -m "feat(runtime): make Guide the only default public entry"
```

### Task 6: Inventory And Remove The Legacy Chat Chain (Spec Task 11)

**Files:**
- Create: `tools/guide_gates/legacy_dependency_inventory.py`
- Create: `tests/guide/runtime/test_legacy_chat_removed.py`
- Modify/delete only after proof: files listed in the responsibility map

- [ ] **Step 1: Write the inventory RED**

The AST scanner must report sorted:

```json
{
  "runtime_importers": [],
  "test_importers": [],
  "script_importers": [],
  "background_importers": [],
  "dynamic_literal_importers": []
}
```

It must detect:

- `import app.services.agent`;
- `from app.services.v2 import presenter`;
- literal `importlib.import_module("app.services.v2.presenter")`;
- literal `__import__("app.services.intent")`;
- literal module targets in worker/task registration.

Targets include `app.services.agent`, `app.services.intent`,
`app.services.v2`, old Presenter and old chat routing modules.

- [ ] **Step 2: Generate the pre-delete report**

Run:

```bash
PYTHONPATH=. /private/tmp/xiaoro-guide-runtime-venv/bin/python \
  tools/guide_gates/legacy_dependency_inventory.py \
  --root . \
  --output /private/tmp/xiaoro-legacy-dependency-inventory.json
```

Expected before migration: importers are listed. Do not delete while
`runtime_importers` or `background_importers` is non-empty.

- [ ] **Step 3: Remove importers at their owning boundary**

- Replace `app/main.py` with:

```python
from app.guide_runtime.app import app

__all__ = ["app"]
```

- Remove old chat router registration and old LLM/embedding startup from the
  default app graph.
- Remove old `ShoppingAgent` worker/beat registrations; do not wrap them in a
  Guide-named adapter.
- Remove stale exports from `app/services/__init__.py`.
- Migrate behavior-level tests to `tests/guide/**`; delete tests/scripts that
  only exercise removed V2 internals.
- Do not copy old Agent, Intent or Presenter functions into Guide.

- [ ] **Step 4: Prove runtime importers are zero**

Re-run:

```bash
PYTHONPATH=. /private/tmp/xiaoro-guide-runtime-venv/bin/python \
  tools/guide_gates/legacy_dependency_inventory.py \
  --root . \
  --assert-empty-runtime
```

Expected: exit `0`. Test/script importers must each be explicitly classified as
migrated, deleted or intentionally non-chat; no unexplained entry remains.

- [ ] **Step 5: Delete the proven-unreachable modules**

Use `git rm`, never a `legacy/` move:

```bash
git rm -r app/services/v2
git rm app/services/agent.py app/services/intent.py
```

Delete the old chat route, old Presenter-only tests and old V2-only scripts
only when they are present in the reviewed inventory.

- [ ] **Step 6: Run deletion gates**

Run:

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/runtime/test_legacy_chat_removed.py \
  tests/guide/runtime/test_import_boundary.py \
  tests/guide/test_architecture_boundaries.py

PYTHONPATH=. /private/tmp/xiaoro-guide-runtime-venv/bin/python \
  tools/guide_gates/legacy_dependency_inventory.py \
  --root . \
  --assert-empty-runtime
```

Expected: PASS, zero runtime importers, no new `legacy/` or archive code tree.

- [ ] **Step 7: Commit deletion in reviewable batches**

Commit importer migration separately from physical deletion:

```bash
git add -A
git commit -m "refactor(runtime): remove legacy chat importers"
```

Then:

```bash
git add -A
git commit -m "refactor(guide): delete the unreachable legacy chat chain"
```

### Task 7: Run Bounded Final Closure Gates (Spec Task 12)

**Files:**
- Verify: all active code/tests
- Do not modify: protected assets

- [ ] **Step 1: Run focused semantic/state shards**

Run one command at a time:

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q tests/guide/understanding tests/guide/intent

/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q tests/guide/adapters

/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q tests/guide/application

/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q tests/guide/runtime tests/guide/tools
```

Expected: PASS. Poll at 30 seconds; do not start the next shard until the
previous PID is gone.

- [ ] **Step 2: Run Guide full, runtime full and remaining tests**

Run serially with heartbeat and hard timeout:

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q

/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q tests/guide/runtime

/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -q tests
```

Before the final all-tests command, run it once with `--maxfail=1` only if a
collection failure is suspected. Do not run duplicate full suites
concurrently.

- [ ] **Step 3: Run mechanical boundaries**

```bash
python3 -m compileall -q app/guide app/guide_runtime tools/guide_gates
python3 -m app.guide.check_boundaries
git diff --check
PYTHONPATH=. /private/tmp/xiaoro-guide-runtime-venv/bin/python \
  tools/guide_gates/legacy_dependency_inventory.py \
  --root . \
  --assert-empty-runtime
```

Expected: zero violations.

- [ ] **Step 4: Run cross-worker and terminal-delivery gates**

Run:

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/application/test_cross_worker_text_state.py \
  tests/guide/runtime/test_runtime_http.py \
  tests/guide/runtime/test_feedback_runtime_http.py
```

Expected: 2/4-worker-compatible SQLite CAS behavior, restart recovery,
stale/CAS safety, disconnect safety and one terminal delivery.

- [ ] **Step 5: Run the complete browser matrix**

Against a fresh Guide runtime, run normal, adversarial, consultation, combined
image and feedback gates one at a time. Use separate `/private/tmp` evidence
paths and stop the server after the matrix.

Expected: no page error, unexpected HTTP/SSE error, failed image, XSS,
cross-session mutation or late-event mutation.

- [ ] **Step 6: Replay the frozen real A/B**

With the same selected model pair and unchanged case/prompt/schema identities,
run Task 2 again into a new `/private/tmp` directory.

Expected: same `case_manifest_sha256`, same selected model, all four hard
counts `0`. Latency/usage may differ and remain outside the stable semantic
hash.

- [ ] **Step 7: Verify protected assets**

Run:

```bash
shasum -a 256 app/guide/decision/deterministic_ranking.py
git diff --exit-code 2199164 -- \
  data/canonical \
  data/guide_category_facts \
  data/guide_review_sources \
  app/guide/decision/deterministic_ranking.py
```

Expected ranking SHA:

```text
4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f
```

Expected: Canonical 103, production fact count, six approved reviews and their
source IDs/hashes unchanged; automatic approvals remain `0`.

### Task 8: Final Evidence And Status Closure (Spec Task 13)

**Files:**
- Create: `docs/audits/guide-closure/final_handoff.md`
- Append: `.trae/specs/complete-guide-closure-continuously/progress.md`
- Update from evidence: `.trae/specs/complete-guide-closure-continuously/tasks.md`
- Update from evidence: `.trae/specs/complete-guide-closure-continuously/checklist.md`
- Read only: `docs/audits/guide-closure/audit_ledger.csv`

- [ ] **Step 1: Write `final_handoff.md`**

Include:

- start/end SHA;
- audit key, invocation `1`, repeat `0`;
- selected model, prompt/schema and stable evidence hashes;
- usage, latency and cost status;
- all hard-gate counts;
- Guide-only launcher and public route evidence;
- clarification 1/2/scope/reset evidence;
- 2/4 worker, restart, stale/CAS and terminal-delivery evidence;
- legacy deletion inventory with `runtime_importers=0`;
- focused/full/runtime/all-tests/browser results;
- protected hashes and data non-promotion result;
- `push=NO`, `deploy=NO`, `traffic_switch=NO`;
- unresolved blockers or `none`.

- [ ] **Step 2: Reconcile tasks and checklist**

Mark an item complete only when its cited evidence exists. Mechanical target:

```text
tasks=110/110
checklist=220/220
```

Do not mark overall COMPLETE before both counts are exact.

- [ ] **Step 3: Append one final progress checkpoint**

Append, do not rewrite history. Record final SHA, gate results, hashes,
selection, deletion proof and release boundary.

- [ ] **Step 4: Prove final repository state**

Run:

```bash
git status --short --branch
git diff --check
cat docs/audits/guide-closure/audit_ledger.csv
```

Expected: clean `rebuild`, one audit ledger row, invocation `1`, no repeat.

- [ ] **Step 5: Commit the final handoff**

```bash
git add \
  docs/audits/guide-closure/final_handoff.md \
  .trae/specs/complete-guide-closure-continuously/tasks.md \
  .trae/specs/complete-guide-closure-continuously/checklist.md \
  .trae/specs/complete-guide-closure-continuously/progress.md
git commit -m "docs(guide): close the Guide-only program"
```

After the commit, run `git status --short --branch` once more. Do not push,
deploy or switch traffic.

## Stop Conditions

Pause and report rather than bypassing the gate when:

- a fresh `GUIDE_LLM_API_KEY` is absent;
- neither model passes after three generalizable repair loops;
- Task 8 browser/runtime gates are not fully green;
- legacy inventory still has a runtime/background importer;
- a protected hash changes;
- the selected model cannot be replayed in Task 12;
- push, deploy, production traffic or destructive data migration is requested.

In every other case, continue to the next dependency-ordered task without
requesting a routine checkpoint approval.
