# Real Demo Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make all seven XiaoRo Demo entry modes return useful results through real multi-turn browser flows, then produce a bounded Demo GO report.

**Architecture:** Preserve the single Guide path and fix defects only at their earliest owner. Generic comparisons gain evidence-backed default display dimensions without changing user-requested dimensions or inventing a winner; the existing browser audit gains a Demo trajectory set and business-usefulness checks instead of creating another runtime or renderer.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, pytest, Playwright, DeepSeek V4 Pro, vanilla JavaScript, SSE

---

## Scope And File Ownership

**Production behavior**

- `app/guide/presentation/comparison_planning.py`
  selects explicit or evidence-backed default comparison rows.
- `app/guide/presentation/public_contracts.py`
  validates requested dimensions against the actual row set without requiring
  empty decorative rows.
- `app/guide/presentation/presentation_compiler.py`
  permits a winner only when a user-relevant comparison row supports it.

**Acceptance tooling**

- `tools/guide_gates/run_mainline_contract_browser_audit.py`
  remains the only browser execution and evidence writer. It gains a
  `demo` trajectory set and usefulness counters.
- `tools/guide_gates/record_manual_screenshot_review.py`
  gains Demo review issue codes and accepts the Demo browser summary without
  weakening the strict release path.

**Tests**

- `tests/guide/presentation/test_comparison_planning.py`
- `tests/guide/presentation/test_public_contracts.py`
- `tests/guide/presentation/test_presentation_compiler.py`
- `tests/guide/application/test_text_presentation_integration.py`
- `tests/guide/tools/test_run_mainline_contract_browser_audit.py`
- `tests/guide/tools/test_record_manual_screenshot_review.py`

No production sentence, product ID, case ID, or alias branch is permitted.

### Task 1: Make Generic Comparison Rows Useful

**Files:**
- Modify: `tests/guide/presentation/test_comparison_planning.py`
- Modify: `tests/guide/presentation/test_public_contracts.py`
- Modify: `app/guide/presentation/comparison_planning.py`
- Modify: `app/guide/presentation/public_contracts.py`

- [x] **Step 1: Write failing planner tests**

Add tests proving that a generic skincare comparison uses available
`efficacy`, `texture`, and `reference_price` evidence and does not emit empty
`brand_main` or `profile_match` rows.

```python
def test_generic_skincare_comparison_uses_useful_default_rows() -> None:
    rows = plan_comparison_rows(
        requested_dimensions=(),
        slots=(
            _slot(
                "p1",
                129,
                efficacy="屏障修护、抗初老",
                texture="清透蛋清质地、不粘腻",
                price="¥519",
            ),
            _slot(
                "p2",
                33,
                efficacy="修护屏障、抗老、舒缓泛红",
                texture="清润琥珀质地、轻薄不粘腻",
                price="¥968",
            ),
        ),
    )

    assert [row.dimension_id for row in rows] == [
        "efficacy",
        "texture",
        "reference_price",
    ]
    assert all(
        cell.state == "known"
        for row in rows
        for cell in row.cells
    )
```

Add a second test proving that explicitly requested dimensions remain in user
order and may expose an evidence gap without being replaced by defaults.

- [x] **Step 2: Run the planner tests and verify RED**

Run:

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/presentation/test_comparison_planning.py
```

Expected: the generic comparison test fails because the current planner emits
only `brand_main` and `profile_match`.

- [x] **Step 3: Implement category-aware default row selection**

Add deterministic priority data and evidence checks in
`comparison_planning.py`.

```python
_DEFAULT_DIMENSIONS = {
    "skincare": ("efficacy", "texture", "reference_price"),
    "suncare": (
        "spf_pa",
        "texture",
        "water_resistance",
        "reference_price",
    ),
    "base_makeup": (
        "finish",
        "coverage",
        "longevity",
        "texture",
        "reference_price",
    ),
    "color_makeup": (
        "finish",
        "coverage",
        "texture",
        "reference_price",
    ),
    "cleanser": (
        "cleansing_power",
        "texture",
        "suitable_skin",
        "reference_price",
    ),
    "fragrance": (
        "fragrance_family",
        "concentration",
        "longevity",
        "reference_price",
    ),
}
```

Rules:

- explicit dimensions are always retained in exact order;
- generic defaults are selected only when every product has a known cell;
- at most three generic rows are selected;
- `brand_main` and `profile_match` are included only when every product has a
  known value;
- no product-specific fallback exists.

- [x] **Step 4: Relax public row-shape validation without weakening evidence**

Replace exact hard-coded row equality with ordered-subsequence validation.

```python
row_dimensions = tuple(
    row.dimension_id for row in self.comparison_rows
)
requested_positions = tuple(
    row_dimensions.index(item)
    for item in self.requested_comparison_dimensions
)
if requested_positions != tuple(sorted(requested_positions)):
    raise ValueError(
        "requested comparison dimensions must preserve user order"
    )
```

Retain unique row IDs, visible-product order, and per-cell evidence
validation. For generic comparisons, require at least two rows whose cells are
all known and fact-backed.

- [x] **Step 5: Run focused GREEN tests**

Run:

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/presentation/test_comparison_planning.py \
  tests/guide/presentation/test_public_contracts.py
```

Expected: all tests pass.

- [x] **Step 6: Commit**

```bash
git add \
  app/guide/presentation/comparison_planning.py \
  app/guide/presentation/public_contracts.py \
  tests/guide/presentation/test_comparison_planning.py \
  tests/guide/presentation/test_public_contracts.py
git commit -m "fix(guide): make generic comparisons informative"
```

### Task 2: Keep Generic Comparison Winner Honest

**Files:**
- Modify: `tests/guide/presentation/test_presentation_compiler.py`
- Modify: `tests/guide/application/test_text_presentation_integration.py`
- Modify: `app/guide/presentation/presentation_compiler.py`
- Modify: `app/guide/application/text_recommendation_flow.py`

- [x] **Step 1: Write failing winner tests**

Extend the real-product integration test for:

```text
帮我对比兰蔻小黑瓶和小棕瓶
```

Assert:

```python
assert [
    row["dimension_id"]
    for row in presentation["comparison_rows"]
] == ["efficacy", "texture", "reference_price"]
assert all(
    cell["state"] == "known"
    for row in presentation["comparison_rows"]
    for cell in row["cells"]
)
assert presentation["winner"]["status"] == "insufficient"
assert decision["winner_status"] == "INSUFFICIENT_FOR_WINNER"
assert (
    answer["answer_contract"]["winner_status"]
    == "INSUFFICIENT_FOR_WINNER"
)
```

Add a compiler unit test proving that descriptive default rows cannot justify
a unique winner, while an explicitly requested or profile-backed row can.

- [x] **Step 2: Run the tests and verify RED**

Run:

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/presentation/test_presentation_compiler.py \
  tests/guide/application/test_text_presentation_integration.py \
  -k "comparison"
```

Expected: the generic comparison either has empty rows or incorrectly
authorizes the raw selected winner.

- [x] **Step 3: Restrict winner evidence to user-relevant rows**

In `_build_winner_presentation()`, build eligible winner dimensions from:

- `packet.requested_dimensions`;
- a known `profile_match` row.

Do not use inferred descriptive default rows as winner authority.

```python
eligible_dimensions = set(packet.requested_dimensions)
if any(
    row.dimension_id == "profile_match"
    and any(cell.state == "known" for cell in row.cells)
    for row in comparison_rows
):
    eligible_dimensions.add("profile_match")
```

Collect winner facts only from eligible dimensions. With no eligible facts,
return `WinnerPresentation(status="insufficient")`.

Keep `text_recommendation_flow.py` as the single projection point that copies
the final presentation winner into `decision_process` and `answer_contract`.

- [x] **Step 4: Run focused GREEN tests**

Run:

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/presentation/test_presentation_compiler.py \
  tests/guide/application/test_text_presentation_integration.py
```

Expected: all tests pass.

- [x] **Step 5: Commit**

```bash
git add \
  app/guide/presentation/presentation_compiler.py \
  app/guide/application/text_recommendation_flow.py \
  tests/guide/presentation/test_presentation_compiler.py \
  tests/guide/application/test_text_presentation_integration.py
git commit -m "fix(guide): bind comparison winners to user criteria"
```

### Task 3: Add Business-Usefulness Gates

**Files:**
- Modify: `tests/guide/tools/test_run_mainline_contract_browser_audit.py`
- Modify: `tools/guide_gates/run_mainline_contract_browser_audit.py`

- [x] **Step 1: Write failing audit tests**

Add tests that reject:

- a generic comparison containing only unknown cells;
- a recommendation whose visible products have no fact-backed product
  sections;
- a product-knowledge answer with no answer text and no precise evidence-gap
  text.

Add passing controls for explicit unknown evidence and useful generic
comparisons.

```python
def test_demo_usefulness_rejects_all_unknown_generic_comparison() -> None:
    with pytest.raises(
        AuditBundleError,
        match="comparison has no useful dimensions",
    ):
        _validate_demo_usefulness(
            contract=_generic_unknown_comparison_contract(),
            events=(),
        )
```

- [x] **Step 2: Run the tests and verify RED**

Run:

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/tools/test_run_mainline_contract_browser_audit.py \
  -k "demo_usefulness"
```

Expected: fail because `_validate_demo_usefulness` does not exist.

- [x] **Step 3: Implement a Demo-only usefulness validator**

Add `_validate_demo_usefulness()` beside `validate_audit_bundle()`. It reads
the typed terminal contract and captured events; it does not inspect product
names or fixture IDs.

```python
def _known_fact_backed(cell: object) -> bool:
    return (
        isinstance(cell, dict)
        and cell.get("state") == "known"
        and isinstance(cell.get("fact_ids"), list)
        and bool(cell["fact_ids"])
    )
```

The strict release validator remains unchanged. The Demo validator adds
content requirements after the existing structural validation passes.

- [x] **Step 4: Run focused GREEN tests**

Run:

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/tools/test_run_mainline_contract_browser_audit.py \
  -k "demo_usefulness or comparison_bundle"
```

Expected: all selected tests pass.

- [x] **Step 5: Commit**

```bash
git add \
  tools/guide_gates/run_mainline_contract_browser_audit.py \
  tests/guide/tools/test_run_mainline_contract_browser_audit.py
git commit -m "test(guide): reject structurally valid empty answers"
```

### Task 4: Add Seven Real Multi-Turn Demo Trajectories

**Files:**
- Modify: `tests/guide/tools/test_run_mainline_contract_browser_audit.py`
- Modify: `tools/guide_gates/run_mainline_contract_browser_audit.py`

- [x] **Step 1: Write failing trajectory-contract tests**

Define `DEMO_TRAJECTORIES` with seven trajectories and exactly three turns
per trajectory. Tests require:

```python
assert len(DEMO_TRAJECTORIES) == 7
assert sum(
    len(item.turns) for item in DEMO_TRAJECTORIES
) == 21
assert {
    item.release_mode for item in DEMO_TRAJECTORIES
} == {
    "explore_recommendation",
    "fit_recommendation",
    "product_knowledge",
    "comparison",
    "image_identity",
    "image_fit_recommendation",
    "image_comparison",
}
```

The comparison trajectory must start with the homepage prompt:

```text
帮我对比兰蔻小黑瓶和小棕瓶
```

and continue with:

```text
那哪个更适合油敏肌？
不考虑肤质，只看功效、质地和价格
```

Use this exact bounded matrix:

| Mode | Turn | Message / upload | Expected terminal responsibility |
|---|---:|---|---|
| explore recommendation | 1 | `预算三百以内，推荐适合海边的防晒` | recommendation / explore |
| explore recommendation | 2 | `第二款更适合油皮吗？` | single-product suitability |
| explore recommendation | 3 | `预算改成两百以内，其他要求不变` | recommendation / explore |
| fit recommendation | 1 | `给我推荐一款最适合修护屏障、清爽不黏需求的 900 到 1100 元精华` | recommendation / fit |
| fit recommendation | 2 | `功效仍然优先修护屏障，但肤感改成更水润，还是只要一款` | recommendation / fit |
| fit recommendation | 3 | `预算降到八百，其他要求不变，还是只要一款` | recommendation / fit |
| product knowledge | 1 | `理肤泉新B5多效修护精华的质地适合什么肤质？` | product knowledge |
| product knowledge | 2 | `它的主要功效方向呢？` | product knowledge |
| product knowledge | 3 | `回到质地，它更偏清爽还是滋润？` | product knowledge |
| comparison | 1 | `帮我对比兰蔻小黑瓶和小棕瓶` | comparison |
| comparison | 2 | `那哪个更适合油敏肌？` | comparison |
| comparison | 3 | `不考虑肤质，只看功效、质地和价格` | comparison |
| image identity | 1 | upload `product-38-index-control.png`, empty text | image identity |
| image identity | 2 | `图里这款叫什么，确认一下` | image identity or product knowledge |
| image identity | 3 | `那它的质地和功效是什么？` | product knowledge |
| image fit recommendation | 1 | upload `product-38-index-control.png` and ask `给我找一款最适合油敏肌、换季泛红时用的相似精华` | recommendation / fit |
| image fit recommendation | 2 | `不考虑肤质，继续参考第一轮上传的图片，只推荐一款修护屏障、清爽不黏的相似精华` | recommendation / fit |
| image fit recommendation | 3 | `预算改成三百以内，其他要求不变，还是只要一款` | recommendation / fit |
| image comparison | 1 | upload `product-38-index-control.png` and `jd_v3_10069603621835.png`, ask `比较这两张图里的商品` | comparison |
| image comparison | 2 | `第二张图里的商品质地怎么样？` | product knowledge |
| image comparison | 3 | `回到这两张，按功效、质地和价格比较` | comparison |

Where a deliberately allowed responsibility pair appears, encode it as an
explicit tuple on `BoundedBrowserTurn` rather than weakening all terminal
checks:

```python
expected_modes: tuple[str, ...]
```

Existing single-mode turns normalize their current `expected_mode` into a
one-item tuple.

- [x] **Step 2: Run trajectory tests and verify RED**

Run:

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/tools/test_run_mainline_contract_browser_audit.py \
  -k "demo_trajectories"
```

Expected: fail because the Demo trajectory set and dispatch mode do not exist.

- [x] **Step 3: Extend the existing browser runner**

Add `demo` to the existing trajectory-set CLI. Reuse:

- the production page;
- browser request interception and raw SSE capture;
- session continuity;
- artifact writer;
- canonical product validator;
- DOM and screenshot capture.

Do not add a second app, API route, dispatcher, or renderer.

For `demo`, `resolve_cli_output()` accepts `--output` and forbids
`--attempt-context`. The existing `fixture`, `bounded`, and `release`
authorization behavior remains byte-for-byte unchanged. Make
`--expected-manifest-sha256` optional at argument parsing and require it
explicitly inside the existing three strict branches.

Demo policy:

```python
if trajectory_set == "demo":
    validate_audit_bundle(turn_dir)
    _validate_demo_usefulness(
        contract=contract,
        events=stream_events,
    )
```

Permit one provider transport retry for the same turn. Do not retry wrong
bindings, internal errors, unrelated clarification, or usefulness failures.

- [x] **Step 4: Run focused GREEN tests**

Run:

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/tools/test_run_mainline_contract_browser_audit.py
```

Expected: all tests pass.

- [x] **Step 5: Commit**

```bash
git add \
  tools/guide_gates/run_mainline_contract_browser_audit.py \
  tests/guide/tools/test_run_mainline_contract_browser_audit.py
git commit -m "test(guide): add real multi-turn demo acceptance"
```

### Task 5: Run The Real Acceptance And Repair Automatically

**Files:**
- Generate:
  `docs/audits/final-release/mainline-contract-closure/demo-real-acceptance/`
- Modify only the earliest owner identified by preserved evidence.

- [x] **Step 1: Start a clean candidate runtime**

Use a new state directory and an unused loopback port:

```bash
export GUIDE_LLM_API_KEY="$(
  cat /Users/bytedance/Desktop/deepseek-key.txt
)"
export GUIDE_LLM_BASE_URL="https://api.deepseek.com"
export GUIDE_LLM_MODEL="deepseek-v4-pro"
export GUIDE_LLM_FORMAT_REPAIR_ATTEMPTS="0"
export GUIDE_COPY_LLM_API_KEY="$GUIDE_LLM_API_KEY"
export GUIDE_COPY_LLM_BASE_URL="$GUIDE_LLM_BASE_URL"
export GUIDE_COPY_LLM_MODEL="$GUIDE_LLM_MODEL"
export XIAORO_GUIDE_STATE_DIR="/tmp/xiaoro-demo-real-acceptance"

/Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/uvicorn \
  app.guide_runtime.app:app \
  --host 127.0.0.1 \
  --port 8841
```

- [x] **Step 2: Run the 21 real desktop turns**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/run_mainline_contract_browser_audit.py \
  --base-url http://127.0.0.1:8841 \
  --trajectory-set demo \
  --viewport desktop \
  --output \
  docs/audits/final-release/mainline-contract-closure/demo-real-acceptance/browser-desktop
```

Expected: `turn_count=21`, zero hard failures, and zero usefulness failures.

- [x] **Step 3: Execute bounded automatic repair loops**

For every failure:

1. preserve the failed turn directory;
2. identify semantic, task, presentation, envelope, frontend, or state owner;
3. write and run one RED class-level regression;
4. implement the minimum owner repair;
5. run the affected suite;
6. rerun the failed trajectory;
7. continue to the remaining trajectories.

Do not create sentence-specific, product-specific, or case-specific branches.
Do not rerun a provider turn repeatedly to seek a lucky answer.

- [x] **Step 4: Verify mobile layout from exact real SSE**

Replay each trajectory's final accepted SSE through the shipped frontend at
`390x844`, using the same browser reducer and renderer. Write one final mobile
screenshot per mode.

Expected: seven desktop and seven mobile final screenshots, no overlap,
clipping, duplicate answers, or missing controls.

- [x] **Step 5: Record the fourteen-row review**

Extend the existing manual screenshot review schema with:

```text
empty_or_unknown_content
irrelevant_answer
missing_fact_reason
broken_followup_context
```

Record exactly fourteen passing rows bound to the real contract and
screenshot hashes.

- [x] **Step 6: Run the affected regression suites**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/presentation \
  tests/guide/application/test_text_presentation_integration.py \
  tests/guide/application/test_unified_guide_flow.py \
  tests/guide/runtime/test_frontend_browser_contract.py \
  tests/guide/tools/test_run_mainline_contract_browser_audit.py \
  tests/guide/tools/test_record_manual_screenshot_review.py
```

Then run:

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m compileall -q app tools
git diff --check
```

Expected: all tests and static checks pass.

### Task 6: Close Debugging And Publish Demo Decision

**Files:**
- Modify:
  `docs/audits/final-release/mainline-contract-closure/practical-release-attempt-02/demo-release-handoff.md`
- Generate:
  `docs/audits/final-release/mainline-contract-closure/demo-real-acceptance/report.json`
- Delete after the debug confirmation gate is satisfied:
  `debug-demo-runtime-error.md`
- Delete after the debug confirmation gate is satisfied:
  `.dbg/trae-debug-log-demo-runtime-error.ndjson`
- Delete after the debug confirmation gate is satisfied:
  `.dbg/demo-runtime-error.env`
- Remove debug regions from:
  `app/static/chat.html`
- Remove debug regions from:
  `app/guide/application/unified_guide_flow.py`
- Remove debug regions from:
  `app/guide/application/text_recommendation_flow.py`

- [x] **Step 1: Produce the bounded acceptance report**

The report must distinguish:

```text
Demo delivery: GO or NO_GO
Strict production release: unchanged
```

Demo GO requires all criteria from the design document and no retained debug
instrumentation.

- [x] **Step 2: Remove debugging artifacts after confirmation**

Remove only regions marked for `demo-runtime-error`, stop the debug server,
and delete the three mandated debug files. Do not remove the business fix or
the regression tests.

- [x] **Step 3: Re-run post-cleanup verification**

Run the focused suites from Task 5 Step 6, `compileall`, and
`git diff --check`.

- [x] **Step 4: Update the handoff and commit**

```bash
git add \
  app/guide \
  app/static/chat.html \
  tests/guide \
  tools/guide_gates \
  docs/audits/final-release/mainline-contract-closure/demo-real-acceptance \
  docs/audits/final-release/mainline-contract-closure/practical-release-attempt-02/demo-release-handoff.md
git commit -m "fix(guide): complete real demo acceptance"
```

Do not stage unrelated workspace changes, secrets, `.dbg`, temporary state,
or repository-external browser artifacts.

## Completion Evidence

- Real desktop acceptance:
  `docs/audits/final-release/mainline-contract-closure/demo-real-acceptance/browser-desktop-final-08/summary.json`
  (`21/21`, passed).
- Exact-SSE mobile replay:
  `docs/audits/final-release/mainline-contract-closure/demo-real-acceptance/browser-mobile-final-08/summary.json`
  (`7/7`, byte-identical).
- Hash-bound visual review:
  `docs/audits/final-release/mainline-contract-closure/demo-real-acceptance/manual-screenshot-review.json`
  (`14/14`, passed).
- Final regression: `1129 passed`.
- `compileall` and `git diff --check`: passed.
- Decision:
  `Demo delivery: GO`; strict production release remains `NO_GO`.
