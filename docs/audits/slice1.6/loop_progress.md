# Slice 1.6 Loop Progress

## Startup Audit

- Date: 2026-08-08
- Branch: `rebuild`
- Starting HEAD: `7572f5f4bab0480b50b3c8f142d23c55432858d2`
- Required plan ancestor: `7661ab442b3e458c52c8b9d6398c68d95bf9492e` (`yes`)
- Starting worktree: clean
- Ranking SHA-256: `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`
- Protected repository HEAD: `8658e191c05e208b2939aa37fb1ee170b2784e4f`
- Protected repository status SHA-256: `579295a4f4dce036e959e9519c5be1aa8e706ae161ffe48a71e1ea473c34a96a`
- Protected repository status lines: `363`

## Task 1

- [x] Step 1: Add failing adversarial boundary, DTO, and frontend truthfulness tests
- [x] Step 2: Run focused RED tests
- [x] Step 3: Apply the minimum boundary, DTO, and frontend implementation
- [x] Step 4: Run focused GREEN tests, both boundaries, ranking SHA, and diff checks
- [x] Step 5: Update Task 1 tracking and create the required local commit

### RED Evidence

Command:

```text
PYTHONPATH=. UV_OFFLINE=1 uv run --with-requirements requirements-guide-runtime-test.txt pytest -c pytest-guide.ini tests/guide/test_architecture_boundaries.py tests/guide/application/test_chat_api_adapter.py tests/guide/runtime/test_frontend_scope.py -q
```

Result: exit `1`; `5 failed, 25 passed in 0.35s`.

Expected failures:

- Real `application/text_recommendation_flow.py` scoring logic produced no boundary violation.
- `application/chat_api_adapter.py` fake scoring logic produced no boundary violation.
- A nonliteral `import_module(module_name)` target produced no boundary violation.
- Frontend product DTOs still contained `match_score`.
- `chat.html` still rendered `% 契合`.

Environment note: the first invocation omitted `PYTHONPATH=.` and stopped during collection
with `ModuleNotFoundError: app`; it was not accepted as RED evidence.

### GREEN Evidence

Focused command:

```text
PYTHONPATH=. UV_OFFLINE=1 uv run --with-requirements requirements-guide-runtime-test.txt pytest -c pytest-guide.ini tests/guide/test_architecture_boundaries.py tests/guide/application/test_chat_api_adapter.py tests/guide/runtime/test_frontend_scope.py -q
```

Result: exit `0`; `30 passed in 0.23s`.

Additional gates:

- `python3 app/guide/check_boundaries.py app/guide`: exit `0`;
  `Boundary check passed: app/guide`.
- `python3 app/guide/check_boundaries.py app/guide_runtime`: exit `0`;
  `Boundary check passed: app/guide_runtime`.
- `shasum -a 256 app/guide/decision/deterministic_ranking.py`: exit `0`;
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`.
- `git diff --check`: exit `0`; no output.
- `python3 tools/guide_gates/runtime_browser_smoke.py --url
  http://127.0.0.1:8765/chat --screenshot
  /tmp/xiaoro-slice16-task1-browser.png`: exit `0`; no page errors or failed product images.

## Task 2

- [x] Step 1: Add the target-aware skin RED matrix
- [x] Step 2: Run RED against the shared base
- [x] Step 3: Implement explicit match, explicit mismatch, and unknown
- [x] Step 4: Run decision, application, and backend GREEN regression
- [x] Step 5: Create the isolated worktree commit and integrate it

### Isolated Worktree Evidence

- Worktree: `/private/tmp/xiaoro-slice16-task2`
- Base: `3e72a233c06f45309a3918bb0fa3da66a164afda`
- Commit: `1021da23416207b4ef1c131002734b974ccbbe24`
  (`fix(decision): preserve unknown generic skin evidence`)
- RED reproduction: Task 2 test files from the isolated commit over the shared base;
  exit `1`, `16 failed, 43 passed in 0.39s`.
- GREEN in the isolated worktree: decision, text recommendation flow, and backend gate;
  exit `0`, `69 passed in 0.40s`.

## Task 3

- [x] Step 1: Add the concrete-adapter import RED assertion
- [x] Step 2: Run RED against the shared base
- [x] Step 3: Define runtime composition ownership
- [x] Step 4: Remove the application factory and update callers
- [x] Step 5: Run application, composition, and architecture GREEN regression
- [x] Step 6: Create the isolated worktree commit and integrate it

### Isolated Worktree Evidence

- Worktree: `/private/tmp/xiaoro-slice16-task3`
- Base: `3e72a233c06f45309a3918bb0fa3da66a164afda`
- Commit: `67d58b3303e9c22dadee7cd711e4b30d254a68b4`
  (`refactor(runtime): own concrete guide composition`)
- RED reproduction: Task 3 architecture test from the isolated commit over the shared base;
  exit `1`, `1 failed, 20 passed in 0.14s`.
- GREEN in the isolated worktree: application, runtime composition, and architecture tests;
  exit `0`, `69 passed in 0.57s`.

## Task 2 and Task 3 Integration

- Shared root starting HEAD: `3e72a233c06f45309a3918bb0fa3da66a164afda`.
- Task 2 cherry-pick: `39db4af5b209829d91f222e42ff5f6b6393f8e88`.
- Task 3 cherry-pick: `aa1b6d69d0625afbc13ea97ea5e681cee62ca974`.
- The second cherry-pick auto-merged
  `tests/guide/application/test_text_recommendation_flow.py` without a conflict. The file
  retains both the Task 2 dry-skin unknown test and the Task 3 composition import/call.
- Combined Task 2 decision/application/backend and Task 3
  application/composition/architecture regression: exit `0`;
  `106 passed in 0.67s`.
- `python3 app/guide/check_boundaries.py app/guide`: exit `0`;
  `Boundary check passed: app/guide`.
- `python3 app/guide/check_boundaries.py app/guide_runtime`: exit `0`;
  `Boundary check passed: app/guide_runtime`.
- `rg -n "build_text_recommendation_orchestrator" app tests tools -g '*.py'`:
  exit `1`; zero matches.
- Ranking SHA-256 remained
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`.
- `git diff --check 3e72a233c06f45309a3918bb0fa3da66a164afda..HEAD`:
  exit `0`; no output.
- The diff from the shared base contains no changes under `app/services/**`,
  `app/database/**`, `data/canonical/**`, or
  `app/guide/decision/deterministic_ranking.py`.
- Protected repository HEAD remained
  `8658e191c05e208b2939aa37fb1ee170b2784e4f`.
- Protected repository status SHA-256 remained
  `579295a4f4dce036e959e9519c5be1aa8e706ae161ffe48a71e1ea473c34a96a`.
- Protected repository status remained `363` lines.

## Task 4

- [x] Step 1: Add close-before-products and followup-close RED tests
- [x] Step 2: Add bounded session lock tests
- [x] Step 3: Reproduce RED against the shared base
- [x] Step 4: Add the lock port and bounded adapter
- [x] Step 5: Inject session locks and defer state saves until visible events
- [x] Step 6: Run state, concurrency, application, and runtime HTTP GREEN tests
- [x] Step 7: Create the isolated worktree commit and integrate it

### Isolated Worktree Evidence

- Worktree: `/private/tmp/xiaoro-slice16-task4`
- Base: `aa9722102729fc4a7413091e5ff2e65fbf295b98`
- Commit: `7baf878222e185f4bad434860e5ca9df0fbcaaed`
  (`fix(feedback): commit only delivered conversation turns`)
- RED reproduction: Task 4 test files over the shared base; exit `2`,
  `1 error in 0.08s` during collection because `InMemorySessionLocks` did not exist.
- GREEN in the isolated worktree: state, concurrency, application flow, and runtime HTTP;
  exit `0`, `48 passed in 1.04s`.

## Task 7

- [x] Step 1: Add manifest and image integrity RED tests
- [x] Step 2: Reproduce RED against the shared base
- [x] Step 3: Validate the canonical manifest self-digest
- [x] Step 4: Require an absolute asset root and validate every image
- [x] Step 5: Run asset, catalog, composition, runtime, and Slice 0 GREEN tests
- [x] Step 6: Create the isolated worktree commit and integrate it

### Isolated Worktree Evidence

- Worktree: `/private/tmp/xiaoro-slice16-task7`
- Base: `aa9722102729fc4a7413091e5ff2e65fbf295b98`
- Commit: `493b7dfbe9dea71fa1d78747b44c6122b4631ff2`
  (`fix(catalog): verify runtime image asset integrity`)
- RED reproduction: Task 7 integrity tests over the shared base; exit `1`,
  `7 failed in 0.54s` because the old loader did not accept `asset_root`.
- GREEN in the isolated worktree: asset, catalog, composition, runtime HTTP, and Slice 0;
  exit `0`, `31 passed in 1.33s`.

## Task 4 and Task 7 Integration

- Shared root starting HEAD: `aa9722102729fc4a7413091e5ff2e65fbf295b98`.
- Task 4 cherry-pick: `c10a698b1b159ebe50701d5773ec1c34279f8b92`.
- Task 7 cherry-pick: `e66d5ccae4d11954c14ca0b28482f46159457d46`.
- Task 7 auto-merged `app/guide_runtime/composition.py` without a conflict. The result
  retains both `SessionLockPort`/`InMemorySessionLocks` injection and
  `asset_root=repo_root`; `tests/guide/application/conftest.py` passes the absolute root.
- Combined-root Task 4 regression: exit `0`; `48 passed in 1.82s`.
- Combined-root Task 7 regression: exit `0`; `31 passed in 1.24s`.
- Full Guide suite: exit `0`; `414 passed in 4.86s`.
- `python3 -m compileall -q app/guide app/guide_runtime`: exit `0`.
- Both architecture boundaries passed with zero violations.
- Ranking SHA-256 remained
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`.
- `git diff --check` and
  `git diff --check aa9722102729fc4a7413091e5ff2e65fbf295b98..HEAD`: exit `0`.
- Protected repository HEAD remained
  `8658e191c05e208b2939aa37fb1ee170b2784e4f`.
- Protected repository status SHA-256 remained
  `579295a4f4dce036e959e9519c5be1aa8e706ae161ffe48a71e1ea473c34a96a`.
- Protected repository status remained `363` lines.

### Startup Performance

- Local `build_runtime_orchestrator()` benchmark after integration: first call
  `214.582 ms`; 20 warm calls had minimum `22.014 ms`, median `22.588 ms`, mean
  `23.564 ms`, p95 `26.375 ms`, and maximum `31.156 ms`.
- This is a local warm-filesystem benchmark, not a production cold-disk or container-start
  service-level objective.

### Remaining Risks

- Session locks are process-local. Multiple worker processes do not serialize the same
  session, and hash stripe collisions can serialize otherwise unrelated sessions.
- Asset verification is synchronous and scales with asset count and bytes. Files changed
  after startup are not revalidated until the next composition.
- Tasks 5, 6, 8, and 9 remain open, so the Slice 1.6 browser and release gates are not yet
  complete.

## Task 5

- [x] Step 1: Add category-free owner-routing and version transport RED tests
- [x] Step 2: Run focused RED tests
- [x] Step 3: Replace keyword routing with exact/followup/budget owner parsers
- [x] Step 4: Preserve nonnegative `conversation_version` in the formal API
- [x] Step 5: Run focused, formal-router, and clean runtime HTTP GREEN tests
- [x] Step 6: Run both boundaries, ranking SHA, diff, and repository protection checks

### RED Evidence

Command:

```text
PYTHONPATH=. UV_OFFLINE=1 uv run --with-requirements requirements-guide-runtime-test.txt pytest -c pytest-guide.ini tests/guide/application/test_chat_api_adapter.py tests/guide/application/test_chat_route_wiring.py tests/guide/application/test_formal_chat_router_http.py -q
```

Result: exit `1`; `5 failed, 10 passed in 1.54s`.

Expected failures:

- Category-free `第二款呢` did not enter the clean Guide route.
- `ChatRequest` had no `conversation_version` field.
- The Guide branch constructed `UserTurn` with a literal version `0`.
- A formal-router second turn entered the legacy dependency sentinel.
- A negative formal-router version was accepted with HTTP 200 instead of 422.

### GREEN Evidence

Focused command:

```text
PYTHONPATH=. UV_OFFLINE=1 uv run --with-requirements requirements-guide-runtime-test.txt pytest -c pytest-guide.ini tests/guide/application/test_chat_api_adapter.py tests/guide/application/test_chat_route_wiring.py tests/guide/application/test_formal_chat_router_http.py -q
```

Result: exit `0`; `15 passed in 0.81s`.

Clean runtime HTTP command:

```text
PYTHONPATH=. UV_OFFLINE=1 uv run --with-requirements requirements-guide-runtime-test.txt pytest -c pytest-guide.ini tests/guide/runtime/test_runtime_http.py -q
```

Result: exit `0`; `12 passed in 1.11s`.

Additional gates:

- The formal `/api/v1/chat/stream` router completed a real Guide first turn plus
  category-free ordinal followup, returning versions `1` then `2`.
- `python3 app/guide/check_boundaries.py app/guide`: exit `0`; zero violations.
- `python3 app/guide/check_boundaries.py app/guide_runtime`: exit `0`; zero violations.
- Ranking SHA-256 remained
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`.
- `git diff --check`: exit `0`; no output.
- Protected repository Task 5 baseline and final HEAD remained
  `8658e191c05e208b2939aa37fb1ee170b2784e4f`.
- Protected repository Task 5 status remained `284` lines with SHA-256
  `613faaf5f041c61e6e6fad65b3f6204b1cc3146340cc769c212a5be8ee9f826e`.

### 限制与风险

- The old formal API has heavy module-load dependencies. No package was installed and no
  network access was used.
- Formal-router HTTP coverage uses import-only stubs for legacy config, service factories,
  PostgreSQL, and Decimal conversion. The Guide orchestrator, canonical catalog, session
  state, routing branch, and SSE adapter are real; the stubs contain no business response.
- A full formal application boot with real legacy database, LLM, Redis, Milvus, and OCR
  dependencies was intentionally not run.
- The protected repository had already diverged from the loop Startup Audit before Task 5
  began (`284` current status lines versus `363` recorded there). Task 5 protection is
  therefore asserted against the fresh baseline captured at Task 5 start.

## Task 6

- [x] Step 1: Add frontend request ownership and SSE error parsing source tests
- [x] Step 2: Run source RED and verify expected failures
- [x] Step 3: Register complete per-session request contexts before DOM writes
- [x] Step 4: Separate JSON parse failures from visible SSE business errors
- [x] Step 5: Consume only real stage events in Guide runtime mode
- [x] Step 6: Add deterministic isolated-context adversarial browser scenarios
- [x] Step 7: Run source, runtime, browser, boundary, SHA, diff, and protection gates
- [x] Step 8: Prepare the required local Task 6 commit

### RED Evidence

Initial source command:

```text
PYTHONPATH=. UV_OFFLINE=1 uv run --with-requirements requirements-guide-runtime-test.txt pytest -c pytest-guide.ini tests/guide/runtime/test_frontend_scope.py -q
```

Result: exit `1`; `7 failed, 4 passed in 0.07s`.

Expected failures covered:

- no `activeChatRequests` or complete request context;
- duplicate sends were not rejected before the draft was cleared;
- session switch/delete did not abort requests;
- streaming selected a global `.typing` node and had no fetch signal or owner guards;
- cleanup did not compare the same request object;
- SSE business errors were swallowed by the JSON parse catch;
- Guide runtime still started the synthetic six-step process.

An additional owner-revival RED used the same command and exited `1` with
`1 failed, 10 passed in 0.08s`: an aborted context was not yet explicitly excluded from
ownership when a user switched rapidly back to the original session.

### GREEN Evidence

Final source command:

```text
PYTHONPATH=. UV_OFFLINE=1 uv run --with-requirements requirements-guide-runtime-test.txt pytest -c pytest-guide.ini tests/guide/runtime/test_frontend_scope.py -q
```

Result: exit `0`; `11 passed in 0.06s`.

Runtime command:

```text
PYTHONPATH=. UV_OFFLINE=1 uv run --with-requirements requirements-guide-runtime-test.txt pytest -c pytest-guide.ini tests/guide/runtime -q
```

Result: exit `0`; `28 passed in 2.18s`.

### Browser Evidence

Both browser gates started the real `app.guide_runtime.app:app` with Uvicorn from `/tmp`
through the server lifecycle helper and exited `0`.

- Adversarial gate:
  `python3 tools/guide_gates/runtime_browser_adversarial.py --url
  http://127.0.0.1:8765/chat`.
- Each error, abort/late-chunk, and stage scenario used an independent browser context.
- The gate waited for page-level request handshakes rather than fixed sleeps.
- The public `GUIDE_INTERNAL_ERROR` message was visible and was not logged as a JSON parse
  failure.
- Session switch produced an observed AbortSignal; a deliberately released late message
  and version did not enter the new session DOM or conversation-version storage.
- The real `stage` message was visible while synthetic knowledge-retrieval and
  comprehensive-scoring copy remained absent.
- Normal smoke:
  `python3 tools/guide_gates/runtime_browser_smoke.py --url
  http://127.0.0.1:8766/chat --screenshot
  /tmp/xiaoro-guide-task6-smoke-final.png`.
- Normal smoke retained three sunscreen cards, two repair-serum cards, ordinal follow-up
  version `2`, and budget-revision version `2`.

### Additional Gates

- `python3 app/guide/check_boundaries.py app/guide`: exit `0`;
  `Boundary check passed: app/guide`.
- `python3 app/guide/check_boundaries.py app/guide_runtime`: exit `0`;
  `Boundary check passed: app/guide_runtime`.
- `python3 -m py_compile tools/guide_gates/runtime_browser_adversarial.py`: exit `0`.
- `git diff --check`: exit `0`; no output.
- Ranking SHA-256 remained
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`.
- Protected repository HEAD remained
  `8658e191c05e208b2939aa37fb1ee170b2784e4f`.
- Protected repository status SHA-256 remained
  `579295a4f4dce036e959e9519c5be1aa8e706ae161ffe48a71e1ea473c34a96a`.
- Protected repository status remained `363` lines.
- The server helper printed its shutdown sequence but left Uvicorn parent/child processes
  listening on `127.0.0.1:8765` and `127.0.0.1:8766`. The four Task 6 process IDs were
  identified by exact command line, stopped with `TERM`, and then verified absent with
  both `lsof` port checks and `ps`.

### Task 6 Residual Risk

- The adversarial gate replaces only the browser fetch transport; it still loads the page
  from real Uvicorn, while the normal smoke separately exercises the real SSE backend.
- The legacy page intentionally retains its existing immediate decision animation. Guide
  runtime mode disables it and renders only backend stage events.

## Task 6 Tracking Correction + Reverify

- Tracking correction: marked Task 6 and SubTasks 6.1-6.6 complete in
  `.trae/specs/close-slice1-text-foundation/tasks.md`; the construction plan's Task 6
  Steps 1-8 were already complete and required no change.
- Reverified commit `5f30ad54dba32bbcea31749d1efe078ddc8bdb6b`.
- Source tests: exit `0`; `11 passed in 0.02s`.
- Runtime tests: exit `0`; `28 passed in 2.28s`.
- Both architecture boundaries passed for `app/guide` and `app/guide_runtime`.
- Ranking SHA-256 remained
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`.
- `git diff --check` and `git diff --check 5f30ad5^ 5f30ad5`: exit `0`;
  no output.
- Confirmed the committed
  `tools/guide_gates/runtime_browser_adversarial.py` and the Task 6 adversarial and
  normal smoke evidence above. Browser gates were not rerun for this tracking-only
  correction.
- No production code was modified.

## Task 8

- [x] Step 1: Add a shared HTTP case matrix
- [x] Step 2: Add no-fake-copy browser assertions
- [x] Step 3: Run focused HTTP and browser gates
- [x] Step 4: Prepare the required local Task 8 commit

### Existing Coverage and RED Evidence

Before editing, the existing formal-router and runtime HTTP files passed together with
`14 passed in 1.09s`. A direct probe also confirmed that all three production behaviors
already returned the required products and version:

- `第二款呢` -> `[38]`, version `2`;
- `哪个更便宜` -> `[91]`, version `2`;
- `预算降到100元呢` -> `[91]`, version `2`.

The missing behavior was therefore the shared gate, not production routing. After extending
the existing formal-router test to the three-case matrix, but before connecting runtime HTTP
to that matrix, this command established RED:

```text
PYTHONPATH=. UV_OFFLINE=1 uv run --with-requirements requirements-guide-runtime-test.txt pytest -c pytest-guide.ini tests/guide/application/test_formal_chat_router_http.py -q
```

Result: exit `1`; `1 failed, 4 passed in 0.94s`. The expected failure was
`test_runtime_http.MULTITURN_CASES` being absent. No duplicate
`test_formal_chat_contract.py` was created.

The first combined GREEN attempt had `1 failed, 18 passed`: pytest loaded the formal test
under two module names, so an object-identity assertion failed even though both tuples were
equal. The gate was corrected to compare the shared contract values; no production behavior
was changed.

### GREEN HTTP Evidence

Combined focused command:

```text
PYTHONPATH=. UV_OFFLINE=1 uv run --with-requirements requirements-guide-runtime-test.txt pytest -c pytest-guide.ini tests/guide/application/test_formal_chat_router_http.py tests/guide/runtime/test_runtime_http.py -q
```

Result: exit `0`; `19 passed in 1.31s`.

Separate final checks:

- Formal router: exit `0`; `5 passed in 0.59s`.
- Clean runtime HTTP: exit `0`; `14 passed in 1.11s`.
- Both surfaces use the same three-case values and assert version `2`.

### Browser Evidence

The real runtime was started with Uvicorn from `/tmp`, using
`PYTHONPATH=/Users/bytedance/Desktop/xiaoro-fresh`, and `/health` returned HTTP 200 with
runtime scope `slice1_text_skincare`.

Normal smoke was run from `/tmp`:

```text
python3 /Users/bytedance/Desktop/xiaoro-fresh/tools/guide_gates/runtime_browser_smoke.py --url http://127.0.0.1:8765/chat --screenshot /tmp/xiaoro-slice16-task8-browser.png
```

Result: exit `0`. The gate verified:

- three sunscreen cards and two repair-serum cards;
- both repair-serum labels are `适配待确认` and contain no `%`;
- visible Guide copy contains neither `知识检索已完成` nor `综合打分`;
- ordinal follow-up returns product `38` and version `2`;
- budget revision returns product `91` and version `2`;
- an independently cleared `500元内干性修护精华` session returns two cards, both
  `适配待确认`, with `适配证据不足` copy;
- no Playwright page errors or failed product-image responses.

The screenshot is a nonempty 1440x1000 PNG at
`/tmp/xiaoro-slice16-task8-browser.png`.

Adversarial smoke was then run from `/tmp` against the same real page server:

```text
python3 /Users/bytedance/Desktop/xiaoro-fresh/tools/guide_gates/runtime_browser_adversarial.py --url http://127.0.0.1:8765/chat
```

Result: exit `0`; public errors, abort ownership, late chunks, and truthful stage copy all
remained gated.

### Additional Gates and Protection

- Both browser gate files passed `python3 -m py_compile`.
- `python3 app/guide/check_boundaries.py app/guide`: exit `0`.
- `python3 app/guide/check_boundaries.py app/guide_runtime`: exit `0`.
- `git diff --check` and `git diff --check c9c7240`: exit `0`.
- Ranking SHA-256 remained
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`.
- No production file, canonical fact, backend CSV gate, or adversarial browser gate was
  modified.
- Protected repository HEAD remained
  `8658e191c05e208b2939aa37fb1ee170b2784e4f`.
- Its final pre-commit dirty status had 284 lines and SHA-256
  `be35dbe626b26a65c8cff09d594aba2e4540f9f8f9e55a3d5fe0a1783c9f4d8c`.
  Historical loop entries contain different dirty-status fingerprints, so Task 8 records
  the current value without claiming the protected repository is clean. Task 8 issued no
  write command in that repository.
- After browser completion, port 8765 had no listener and no Uvicorn, Playwright, smoke, or
  adversarial process remained.

## Task 10 Review Fix

- [x] Step 1: Add Task10 and the release-review checkpoint before implementation
- [x] Step 2: Replace Task 4's delivered-event tests with the no-ACK atomic boundary
- [x] Step 3: Buffer post-start events under the session lock and publish after release
- [x] Step 4: CAS before success publication and suppress products/message on conflict
- [x] Step 5: Gate formal Guide followup/budget ownership with conversation version
- [x] Step 6: Make current-session reactivation a pre-rehydrate no-op
- [x] Step 7: Run focused, browser, full, architecture, integrity, and protection gates
- [x] Step 8: Complete regression review and document deployment risk

### Review Input

- Starting HEAD: `227aae2b936611bcb020fa58fc51b1e50e40279a`.
- Reviewed report: `/tmp/xiaoro-fresh_slice16_review/report.md`.
- Confirmed findings addressed: synchronous lock across public SSE yield, version-0 legacy
  session takeover, state save after message publication, and current-session DOM
  rehydration. Process-local multi-worker state remains an explicit deployment risk rather
  than an approved Slice 1.6 implementation change.

### RED Evidence

Focused command:

```text
PYTHONPATH=. UV_OFFLINE=1 uv run --with-requirements requirements-guide-runtime-test.txt pytest -c pytest-guide.ini tests/guide/application/test_text_recommendation_flow.py tests/guide/application/test_chat_api_adapter.py tests/guide/application/test_chat_route_wiring.py tests/guide/application/test_formal_chat_router_http.py tests/guide/runtime/test_frontend_scope.py -q
```

Result: exit `1`; `13 failed, 48 passed in 7.62s`.

Expected failures proved:

- state was still absent when a client closed immediately after receiving `message`;
- followup state remained at version 1 after its message was already visible;
- the session lock was still held when a post-start event was publicly yielded;
- recommendation and followup CAS conflicts leaked success events;
- the formal owner route neither accepted nor received `conversation_version`;
- the formal async same-session router blocked its heartbeat until the isolated subprocess
  hit the 5-second deadlock timeout;
- `activateSession` had no pre-rehydrate current-session no-op.

Adversarial browser RED:

```text
python3 tools/guide_gates/runtime_browser_adversarial.py --url http://127.0.0.1:8765/chat
```

Result: exit `1`; clicking the current highlighted session disconnected the active typing
node and changed the chat DOM.

### GREEN Evidence

The identical focused command passed with `61 passed in 2.89s`.

Combined application/state/runtime/frontend command:

```text
PYTHONPATH=. UV_OFFLINE=1 uv run --with-requirements requirements-guide-runtime-test.txt pytest -c pytest-guide.ini tests/guide/application tests/guide/adapters/state tests/guide/runtime -q
```

Result: exit `0`; `103 passed in 4.59s`.

Browser gates were run from `/tmp` against the real single-process Guide runtime:

- normal Playwright: exit `0`; screenshot
  `/tmp/xiaoro-slice16-review-fix-browser.png`;
- adversarial Playwright: exit `0`; public error, session switch/late chunk, current-session
  reactivation, and real-stage scenarios all passed.

Full Guide suite:

```text
PYTHONPATH=. UV_OFFLINE=1 uv run --with-requirements requirements-guide-runtime-test.txt pytest -c pytest-guide.ini -q
```

Result: exit `0`; `438 passed in 5.69s`.

Additional gates:

- `python3 -m compileall -q app/guide app/guide_runtime`: exit `0`.
- `python3 app/guide/check_boundaries.py app/guide`: exit `0`; zero violations.
- `python3 app/guide/check_boundaries.py app/guide_runtime`: exit `0`; zero violations.
- `git diff --check HEAD`: exit `0`.
- Ranking SHA-256 remained
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`.
- Protected repository HEAD remained
  `8658e191c05e208b2939aa37fb1ee170b2784e4f`.
- Protected repository status remained 363 lines with SHA-256
  `579295a4f4dce036e959e9519c5be1aa8e706ae161ffe48a71e1ea473c34a96a`.

### Regression Review

- `bits-code-guard` reviewed the current `HEAD` worktree diff in general mode.
- Filtered review scope: 5 implementation/gate files, 403 changed lines.
- Result: no unresolved P0-P2 findings.
- Reports:
  `/tmp/xiaoro-fresh_slice16_review_fix/report.html` and
  `/tmp/xiaoro-fresh_slice16_review_fix/report.md`.

### Residual Risk

- `InMemoryConversationState` and `InMemorySessionLocks` remain process-local. Multiple
  Uvicorn workers can lose multi-turn continuity and cannot provide cross-process CAS or
  serialization.
- This Slice does not connect a database, add a distributed lock, or change either Compose
  file. Production cutover is not approved. Any pre-production deployment must use exactly
  one worker until shared atomic state is implemented.

## Task 11 - Formal Chat API Release Hardening

### Review Input

- Starting HEAD: `f72531ae89f8a824d6e16ae581502b43885227be`.
- Final Slice full-file review:
  `/tmp/xiaoro-fresh_slice16_final_review/report.md`.
- Confirmed findings: one P0 session-history IDOR and three P1 issues covering exception
  disclosure, false storage success, and unbounded chat requests.
- The previously fixed lock, CAS, Guide owner, and current-session reactivation findings
  remained closed.

### RED Evidence

Focused command:

```text
PYTHONPATH=. UV_OFFLINE=1 uv run --with-requirements requirements-guide-runtime-test.txt python -m pytest -c pytest-guide.ini tests/guide/application/test_formal_chat_router_http.py tests/guide/application/test_chat_route_wiring.py -q
```

Result: exit `1`; `19 failed, 12 passed in 2.50s`.

The failures reproduced:

- session history SQL omitted `user_id`;
- missing rows and database failures returned `200`;
- delete returned success without affected-row evidence;
- non-stream and SSE errors disclosed injected internal exception text;
- oversized bodies and structured fields reached the endpoint;
- chat endpoints had no dedicated rate-limit decorator.

The first body-size fix still trusted `Content-Length`. A chunked 270 KB request produced a
second RED result: exit `1`; `1 failed in 0.45s`, returning `422` instead of the required
pre-dispatch `413`.

### GREEN Evidence

- focused ownership, redaction, limit, and wiring tests: `31 passed in 2.37s`;
- chunked-body regression: `1 passed in 0.50s`;
- application suite: `81 passed in 3.40s`;
- final Guide suite: `458 passed in 6.41s`;
- runtime suite: `32 passed in 2.90s`;
- backend CSV gate: exit `0`, 8/8 cases in `/tmp/slice16_backend_gate.csv`;
- normal Playwright: exit `0`, screenshot
  `/tmp/xiaoro-slice16-final-browser.png`;
- adversarial Playwright: exit `0`;
- compileall, both boundaries, and `git diff --check`: exit `0`;
- ranking SHA remained
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`.

### Implementation Decisions

- History read/delete now require `get_current_user` and constrain SQL by both
  `session_id` and `user_id`; an absent owned row is `404`.
- Delete uses `RETURNING id`; database failures are generic `503`, not false success.
- Agent exceptions remain in server logs while public responses use
  `CHAT_INTERNAL_ERROR` and a stable generic message.
- Pydantic bounds messages, history, image lists, and object key counts. The route also
  counts ASGI receive bytes, so both declared and chunked bodies above 256 KiB return
  `413` before agent dispatch.
- Existing `limit_chat` is applied to both formal chat endpoints. No new dependency,
  database integration, schema change, or production cutover was added.

### Regression Review

- Task 11 full-file review found no unresolved P0-P2.
- Reports:
  `/tmp/xiaoro-fresh_slice16_task11_review/report.html` and
  `/tmp/xiaoro-fresh_slice16_task11_review/report.md`.
- Protected repository HEAD remained
  `8658e191c05e208b2939aa37fb1ee170b2784e4f`.
- Protected repository status remained 363 lines with SHA-256
  `579295a4f4dce036e959e9519c5be1aa8e706ae161ffe48a71e1ea473c34a96a`.
