# Backend Handoff Vertical Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking. The main agent executes all work;
> sub-agents are forbidden by the user.

**Goal:** Prove the complete backend handoff across profile, image, light
consultation, product/general knowledge, recommendation, comparison, and
follow-up, then stop before frontend rendering.

**Architecture:** Add one cross-vertical typed matrix that exercises the real
composed Guide runtime and frozen assets without duplicating vertical logic.
Run architecture audits and local/official gates, publish a production-gap
report, and preserve the frontend byte lock.

**Tech Stack:** Python 3.11, pytest, FastAPI/typed SSE, SQLite CAS state,
content-addressed Guide assets, official DeepSeek gate runner.

---

## 0. Prerequisites and Execution Rules

Complete first:

1. `2026-08-15-semantic-code-owned-transitions.md`
2. `2026-08-15-trusted-general-knowledge.md`

Use `/Users/bytedance/Desktop/xiaoro-fresh`, branch `rebuild`, and the existing
dirty worktree.

Do not:

- use sub-agents;
- implement frontend rendering;
- modify gate expectations to match a bad model output;
- import legacy services;
- add vertical-specific answer patches;
- push or deploy.

Long-running commands are polled every 30 seconds until exit. A quiet process
is not duplicated.

If two consecutive fixes fail at the same layer, stop. Write an architecture
checkpoint identifying the earliest failure and responsibility overload,
choose a general fix, and only then resume. The Goal runs autonomously; the
main agent makes that design decision and records it for final review.

The worktree contains approved uncommitted implementation from prior goals.
Do not stage or commit implementation during this closure plan. Keep
`git diff --cached --name-only` empty, preserve all unrelated changes, and
record the final path inventory in the closure report.

## 1. File and Ownership Map

Create:

- `tests/guide/runtime/test_backend_handoff_matrix.py`
  Real composed cross-vertical cases.
- `docs/audits/backend-handoff/handoff_matrix_v1.jsonl`
  Frozen input and expected typed outcomes.
- `docs/audits/backend-handoff/architecture_review.md`
  Final ownership and production-risk review.
- `docs/audits/backend-handoff/closure_report.md`
  Final backend GO/NO-GO report.

Modify only when a matrix case exposes a real earliest-layer defect:

- profile ownership/policy files for profile defects;
- image flow/contracts for image defects;
- consultation coordinator/contracts for consultation defects;
- knowledge retrieval/flow for knowledge defects;
- semantic transition/recommendation files for text defects.

Do not fix a vertical failure in `chat_api_adapter.py` or presentation unless
the earliest failure is actually serialization/presentation.

## Task 1: Freeze the Cross-Vertical Matrix Contract

**Files:**

- Create: `docs/audits/backend-handoff/handoff_matrix_v1.jsonl`
- Create: `tests/guide/runtime/test_backend_handoff_matrix.py`

- [ ] **Step 1: Define strict matrix rows**

Each JSONL row contains:

```json
{
  "case_id": "profile-confirm-consume-text",
  "vertical": "profile",
  "turns": [{"message": "..."}],
  "expected": {
    "event_types": ["profile_confirmation", "end"],
    "product_ids": [],
    "profile_fields": {"skin_type": "dry"},
    "knowledge_source": null,
    "medical_escalation": false,
    "clarification_code": null
  }
}
```

Use strict Pydantic fixture contracts in the test module. Do not freeze prose.

- [ ] **Step 2: Add required cases**

Profile:

```text
consultation confirmation writes profile
confirmed profile affects later text recommendation
confirmed profile affects image suitability
current explicit input overrides profile
other owner cannot read or mutate profile
rejection/escalation does not write ordinary fact
```

Image:

```text
single identify
single visual similarity
single suitability with profile
multi-image comparison
low similarity fail closed
invalid image ordinal clarifies
```

Consultation:

```text
entry
question sequence
provisional conclusion
confirmation
rejection
medical escalation
post-confirmation recommendation
```

Knowledge:

```text
general SPF/PA
general niacinamide
general knowledge follow-up
product-specific evidence
product evidence follow-up
general no-hit
medical escalation
product/general isolation
```

Recommendation:

```text
multi-facet soft rank
allergy hard gate
named comparison
current-item follow-up
ordinal follow-up
budget replace with exclusion retain
skin replace with budget retain
fresh request noninheritance
```

- [ ] **Step 3: Write the matrix runner RED test**

Use real composition and production assets. For each row, assert typed events,
state, selected IDs, evidence source class, and safety outcome.

- [ ] **Step 4: Run the matrix and observe RED**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/runtime/test_backend_handoff_matrix.py
```

Expected: failures only for behavior not yet wired or true cross-vertical
defects.

## Task 2: Close Profile Vertical Findings

**Files:**

- Modify only the earliest owner identified by profile matrix failures.
- Test: `tests/guide/runtime/test_backend_handoff_matrix.py`
- Test: `tests/guide/feedback/test_profile_policy.py`
- Test: `tests/guide/adapters/state/test_sqlite_profile_state.py`

- [ ] **Step 1: Classify every profile failure**

Choose exactly one earliest layer:

```text
consultation confirmation
profile persistence
profile ownership
profile resolution priority
text/image consumption
SSE serialization
```

- [ ] **Step 2: Add one focused RED test per behavior class**

Do not add a matrix-only special case.

- [ ] **Step 3: Implement the minimal owner-layer fix**

Preserve:

```text
current explicit > confirmed session > long-term profile > default
owner immutability
explicit user confirmation before persistence
medical escalation does not become ordinary profile fact
```

- [ ] **Step 4: Run profile suites**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/feedback/test_profile_policy.py \
  tests/guide/adapters/state/test_sqlite_profile_state.py \
  tests/guide/application/test_consultation_coordinator.py \
  tests/guide/runtime/test_backend_handoff_matrix.py -k profile
```

Expected: PASS.

## Task 3: Close Image Vertical Findings

**Files:**

- Modify only the earliest image owner.
- Test: `tests/guide/application/test_image_recommendation_flow.py`
- Test: `tests/guide/application/test_image_suitability_gate.py`
- Test: `tests/guide/runtime/test_image_runtime.py`

- [ ] **Step 1: Classify failures**

Use:

```text
upload/input validation
identity/similarity
reference resolution
profile suitability
multi-image comparison
typed event serialization
```

- [ ] **Step 2: Add focused RED tests**

Freeze real asset IDs and deterministic similarity order, not prose.

- [ ] **Step 3: Fix the earliest owner**

Do not alter similarity thresholds per example. A threshold change requires a
matrix-wide before/after report.

- [ ] **Step 4: Run image suites**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/application/test_image_recommendation_flow.py \
  tests/guide/application/test_image_suitability_gate.py \
  tests/guide/application/test_image_reference_resolution.py \
  tests/guide/runtime/test_image_runtime.py \
  tests/guide/runtime/test_backend_handoff_matrix.py -k image
```

Expected: PASS.

## Task 4: Close Light Consultation Findings

**Files:**

- Modify only the earliest consultation owner.
- Test: `tests/guide/application/test_consultation_coordinator.py`
- Test: `tests/guide/application/test_consultation_chat_flow.py`
- Test: `tests/guide/runtime/test_consultation_vertical_composition.py`

- [ ] **Step 1: Classify failures**

Use:

```text
entry claim
answer parsing
observation collection
assessment
confirmation/rejection
medical escalation
profile reconciliation
post-consultation handoff
```

- [ ] **Step 2: Add focused RED tests**

Do not convert the consultation into a model diagnosis path.

- [ ] **Step 3: Fix the earliest owner**

Keep:

```text
provisional conclusion until confirmation
zero product cards during consultation
medical escalation is terminal for ordinary assessment
profile persistence is CAS and owner-bound
```

- [ ] **Step 4: Run consultation suites**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/application/test_consultation_collection.py \
  tests/guide/application/test_consultation_coordinator.py \
  tests/guide/application/test_consultation_chat_flow.py \
  tests/guide/runtime/test_consultation_vertical_composition.py \
  tests/guide/runtime/test_backend_handoff_matrix.py -k consultation
```

Expected: PASS.

## Task 5: Close Knowledge Findings

**Files:**

- Modify only the earliest knowledge owner.
- Test: general-knowledge and ProductEvidence suites.

- [ ] **Step 1: Classify failures**

Use:

```text
intent route
product binding
general retrieval
product evidence retrieval
packet isolation
follow-up state
educational/safety rendering
typed event serialization
```

- [ ] **Step 2: Add focused RED tests**

No test may expect general knowledge to prove a product formula or safety
guarantee.

- [ ] **Step 3: Fix the earliest owner**

Keep product and general packets separate.

- [ ] **Step 4: Run knowledge suites**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/retrieval/test_general_knowledge_contracts.py \
  tests/guide/retrieval/test_general_knowledge_assets.py \
  tests/guide/retrieval/test_general_knowledge_retrieval.py \
  tests/guide/retrieval/test_product_evidence_retrieval.py \
  tests/guide/application/test_general_knowledge_answer.py \
  tests/guide/application/test_product_evidence_answer.py \
  tests/guide/runtime/test_backend_handoff_matrix.py -k knowledge
```

Expected: PASS.

## Task 6: Close Recommendation, Comparison, and Follow-Up Findings

**Files:**

- Modify only the earliest semantic, transition, decision, or state owner.
- Test: `tests/guide/application/test_text_recommendation_flow.py`
- Test: `tests/guide/decision/test_recommendation.py`
- Test: `tests/guide/intent/test_constraint_transitions.py`

- [ ] **Step 1: Classify failures**

Use:

```text
semantic translation
source-span binding
constraint transition
TaskPlan
hard eligibility
soft ordering
reference resolution
snapshot/CAS
typed payload
```

- [ ] **Step 2: Add focused RED tests**

Test final constraints and selected IDs, not model wording.

- [ ] **Step 3: Fix the earliest owner**

Never repair a ranking failure in the presenter or answer renderer.

- [ ] **Step 4: Run text suites**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/understanding \
  tests/guide/intent \
  tests/guide/decision/test_recommendation.py \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/runtime/test_backend_handoff_matrix.py -k "recommendation or comparison or followup"
```

Expected: PASS.

## Task 7: Intermediate Architecture Review

**Files:**

- Create: `docs/audits/backend-handoff/architecture_review.md`

- [ ] **Step 1: Review responsibility boundaries**

Answer:

```text
Is the model still translation-only?
Does code own every state transition?
Can general knowledge influence product ranking?
Can ProductEvidence escape product scope?
Can profile data cross owners?
Can consultation produce a diagnosis?
Can image similarity bypass hard conditions?
Are there duplicate recommendation or retrieval engines?
Does any frontend/presenter code hide a backend defect?
```

- [ ] **Step 2: Review complexity added during fixes**

List:

- abstractions added;
- duplicated logic removed;
- files that now own more than one responsibility;
- temporary compatibility branches;
- remaining architectural risks.

Any newly discovered responsibility collision that can affect production must
be fixed with TDD before final gates. Do not defer it as a cosmetic concern.

- [ ] **Step 3: Re-run the complete handoff matrix**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/runtime/test_backend_handoff_matrix.py
```

Expected: PASS.

## Task 8: Full Local Gates

- [ ] **Step 1: Run focused vertical suites**

Run the five vertical commands from Tasks 2-6. Expected: PASS.

- [ ] **Step 2: Run full Guide**

Start once and poll every 30 seconds:

```bash
.venv/bin/python -m pytest -q tests/guide
```

Expected: PASS.

- [ ] **Step 3: Run runtime**

```bash
.venv/bin/python -m pytest -q tests/guide/runtime
```

Expected: PASS.

- [ ] **Step 4: Run application, state, SSE, and public contracts**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/application \
  tests/guide/adapters/state \
  tests/guide/presentation \
  tests/guide/test_public_contracts.py
```

Expected: PASS.

- [ ] **Step 5: Run static and boundary gates**

```bash
.venv/bin/python -m compileall -q app tools
.venv/bin/python -m pytest -q \
  tests/guide/test_architecture_boundaries.py \
  tests/guide/runtime/test_import_boundary.py
git diff --check
```

Expected: PASS.

## Task 9: Official Model Gates

- [ ] **Step 1: Confirm no old gate process is running**

```bash
ps -o pid,etime,state,command -ax | \
  rg "run_official_deepseek_smoke|run_real_two_stage_intent_ab" | \
  rg -v "rg " || true
```

- [ ] **Step 2: Run gate 1**

```bash
.venv/bin/python -m tools.guide_gates.run_official_deepseek_smoke \
  --output-dir /private/tmp/xiaoro-backend-handoff-official-run-1
```

Poll to exit.

- [ ] **Step 3: Run gate 2**

```bash
.venv/bin/python -m tools.guide_gates.run_official_deepseek_smoke \
  --output-dir /private/tmp/xiaoro-backend-handoff-official-run-2
```

Poll to exit.

- [ ] **Step 4: Run gate 3**

```bash
.venv/bin/python -m tools.guide_gates.run_official_deepseek_smoke \
  --output-dir /private/tmp/xiaoro-backend-handoff-official-run-3
```

Poll to exit.

- [ ] **Step 5: Compare summaries**

Record:

```text
selected_lane
route rate
detail rate
invalid output count
unsafe TaskPlan mismatch
unauthorized transition count
hard override count
wrong product count
p95 latency
summary SHA
```

Production-ready semantic status requires the same non-null selected lane in
all three runs and zero hard-gate violations.

## Task 10: Frontend Freeze and Closure Report

**Files:**

- Create: `docs/audits/backend-handoff/closure_report.md`

- [ ] **Step 1: Verify frontend bytes**

```bash
shasum -a 256 app/static/chat.html
git diff --name-only 71e4735..HEAD -- app/static/chat.html
```

The hash must equal the pre-goal frozen hash. The commit-range command must
produce no goal-owned frontend change.

- [ ] **Step 2: Verify no residual process**

```bash
ps -o pid,etime,state,command -ax | \
  rg "pytest|uvicorn|http.server|run_official_deepseek_smoke" | \
  rg -v "rg " || true
```

Stop only sessions started by this Goal.

- [ ] **Step 3: Write the closure report**

Include:

- profile, image, consultation, knowledge, and text matrix outcomes;
- semantic transition architecture;
- knowledge asset audit and hashes;
- local test commands and counts;
- three official gate summaries;
- architecture review findings;
- deficiencies discovered and general fixes selected;
- remaining limitations and production risks;
- frontend handoff contract;
- GO/NO-GO.

- [ ] **Step 4: Final architecture verdict**

Explicitly answer:

```text
Did this phase reach the target architecture?
What responsibilities remain overloaded?
What is still missing for production?
Which issues are acceptable bounded failures?
Which issues block frontend work?
Which issues block production release?
```

- [ ] **Step 5: Stop before frontend**

Do not modify renderer code, push, deploy, or switch traffic. Present the
closure report for the user's design review.
