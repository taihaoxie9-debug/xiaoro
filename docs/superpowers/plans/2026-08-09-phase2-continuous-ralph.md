# Phase 2 Continuous Ralph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Continuously implement the complete local Phase 2 capability matrix without stopping at intermediate milestones.

**Architecture:** Milestone 1 freezes shared contracts and fixes the common entry points. Three isolated worktrees then implement consultation/profile, multi-image/OCR, and scenario/review/feedback in parallel while one integration owner exclusively controls shared API, SSE, and frontend files. Every capability is merged and browser-verified incrementally; milestone PASS records progress and immediately continues.

**Tech Stack:** Python 3.11, FastAPI, Starlette, Pydantic v2, SQLite/PostgreSQL adapters, OpenCLIP, approved OCR adapter, vanilla JavaScript, pytest, Node.js, Playwright.

---

## 1. Continuous Execution Rules

The overall Goal is complete only when every item in
`.trae/specs/complete-phase2-continuously/tasks.md` and `checklist.md` is checked.

After each milestone:

1. commit the working capability;
2. run its focused, boundary, HTTP, and browser gates;
3. append one progress checkpoint;
4. update task/checklist boxes;
5. continue immediately to the next available task.

Do not stop for ordinary review checkpoints. Continue independent work when one
workstream is blocked. Stop only when:

- complete local Phase 2 passes final verification;
- all remaining tasks share one user decision blocker;
- Ralph reaches its system round limit;
- the user explicitly pauses.

Never push, deploy, switch traffic, edit `data/canonical/**`, edit
`app/services/**`, edit `app/database/**`, or change
`app/guide/decision/deterministic_ranking.py`.

## 1A. Audit Idempotency and Telemetry

Each capability loop freezes one `capability_key`, `iteration_id`, audit profile,
and sorted production-file blob manifest before implementation.

Compute the audit identity from the audit profile version and sorted
`path + NUL + blob SHA-256` records. Commit SHA, branch, worktree, and session
identity are provenance only and must not invalidate an equivalent audit.

Apply these rules:

1. Run no more than one opening full-file audit per capability loop.
2. Reuse an existing PASS with the same audit key as `REUSED_PASS`; do not call
   an auditor again after cherry-pick, rebase, context recovery, or restart.
3. Convert confirmed findings to RED tests. Verify fixes with RED/GREEN,
   focused, boundary, HTTP, and browser gates; do not repeat a full-file audit
   in the same loop.
4. If an auditor is unavailable, record `LOCAL_BASELINE_ONLY` once for that
   audit key, perform one bounded main-thread baseline inspection, and continue
   all runnable work. Do not retry-loop or wait for the user.
5. Before integration, compare stable patch ID and the final production blob
   manifest. Record `INTEGRATION_REUSED` and skip an equivalent cherry-pick or
   commit.
6. Run exactly one independent full-file audit in the distinct
   `FINAL-PHASE2-AUDIT` loop after all capabilities are integrated.

Persist audit invocations, reuse, and state changes in:

`docs/audits/phase2-continuous/audit_ledger.csv`

At every checkpoint, append one row to:

`docs/audits/phase2-continuous/agent_token_usage.csv`

Record cumulative, prompt, uncached prompt, cache-read, cache-write, and output
tokens only from platform/provider telemetry. Calculate cache hit rate and cost
only when the exact model, compatible usage semantics, and dated pricing
snapshot are available. Missing cache, model, pricing, or usage fields are
`UNAVAILABLE` and never block execution.

## 2. Shared Ownership

Only the integration owner modifies:

- `app/api/v1/chat.py`
- `app/static/chat.html`
- `app/guide/presentation/sse_events.py`
- `app/guide/presentation/contracts.py`
- formal owner matrix and shared browser gates

Workstream agents submit domain commits and explicit integration requirements;
they do not edit shared files.

Workstream ownership:

| Worktree | Owned scope |
| --- | --- |
| `/private/tmp/xiaoro-phase2-consultation-profile` | consultation understanding/intent/application, confirmed profile facts and profile state |
| `/private/tmp/xiaoro-phase2-multi-image-ocr` | image ordinals, two/four-image orchestration, suitability, OCR adapters |
| `/private/tmp/xiaoro-phase2-scenario-feedback` | scenario retrieval, review evidence, pitfalls, feedback events |

## 3. Milestone 1: Shared Stabilization

Execute every task in:

`docs/superpowers/plans/2026-08-09-phase2-day1-stabilization.md`

Required exit evidence:

```text
five P1 regressions pass
backend card display contract frozen
frontend inference/fill removed
owner matrix frozen
consultation/profile/multi-image contracts frozen
Guide full green
runtime full green
normal browser green
adversarial browser green
three worktrees created from identical HEAD
```

Do not mark the overall Goal complete. Launch Milestone 2 immediately.

## 4. Milestone 2: Three Parallel End-to-End Workstreams

Spawn three implementation agents concurrently. Each agent must read:

- `docs/superpowers/specs/2026-08-09-phase2-ten-day-completion-design.md`
- `.trae/specs/complete-phase2-continuously/spec.md`
- the frozen shared contracts from Milestone 1

### 4.1 Consultation and Profile Workstream

Implement in this order:

1. observation questions for post-cleanse tightness, T-zone oiliness, recurrent
   redness, stinging, and flaking;
2. deterministic provisional skin conclusion with evidence, uncertainties,
   confidence band, and escalation copy;
3. explicit user confirmation flow;
4. profile storage with owner, source turn, source kind, confirmation time, and
   CAS version;
5. precedence: current explicit input > confirmed session > profile > default;
6. profile only fills missing fields and never persists temporary budget,
   transient symptoms, or unconfirmed inference.

TDD gates:

```text
unknown skin starts consultation without cards
each answer updates session version
insufficient observations ask the next observable question
provisional conclusion has zero cards
medical-risk answer escalates and stops recommendation
unconfirmed conclusion does not write profile
confirmed stable fact increments profile version
new explicit input overrides but does not silently overwrite profile
```

Commit each vertical behavior separately.

### 4.2 Multi-Image, Suitability, and OCR Workstream

Implement in this order:

1. stable 1–4 image ordinal references;
2. two confirmed images comparison with Canonical facts;
3. first/second image reference parsing;
4. winner, tie, and insufficient-evidence outcomes;
5. single-image suitability using explicit/session/profile context;
6. approved OCR adapter for packaging and ingredient labels;
7. OCR consistency/conflict observations without Canonical overwrite;
8. three-to-four confirmed image comparison.

TDD gates:

```text
two confirmed images produce exactly two comparison cards
unconfirmed image stops comparison
duplicate/non-contiguous ordinals fail
"第一张/第二张" resolves only within the current bundle
single-image suitability has one card or a clarification
OCR unavailable fails closed
OCR conflict blocks identity confirmation
three/four images produce exact ordered card counts
```

Do not use old OCR, CLIP, Milvus, image agent, or V2 modules.

### 4.3 Scenario, Review, Pitfall, and Feedback Workstream

Implement in this order:

1. typed scenario constraints for commuting, travel, outdoor, repair, and
   sensitive periods;
2. auditable review evidence reader;
3. review summary that distinguishes source facts from synthesis;
4. high/medium/low pitfall evidence without fabricated safety claims;
5. click, favorite, compare, and negative-feedback events;
6. event ownership, session/profile reference, timestamp, and idempotency key.

TDD gates:

```text
scenario constraints enter deterministic decision
missing scenario facts remain unknown
review summary requires auditable source IDs
missing review sources produce no fake summary
pitfalls retain severity and evidence refs
feedback replay is idempotent
feedback does not directly mutate product facts or ranking
```

## 5. Incremental Integration Loop

The integration owner repeats this loop whenever a workstream has a green
vertical commit:

1. inspect the workstream diff and focused test evidence;
2. cherry-pick or fast-forward only the self-contained domain commit;
3. add the typed SSE/API/frontend adapter in the shared integration branch;
4. run focused shared-contract and route tests;
5. run one real browser scenario;
6. commit the integration;
7. append progress and continue.

Integration order:

```text
consultation observations
-> profile confirmation
-> two-image compare
-> single-image suitability
-> OCR observations
-> three/four-image compare
-> scenario guidance
-> review/pitfall output
-> feedback events
```

Do not wait for an entire workstream to finish before integrating its first
complete capability.

## 6. Guide Ownership Expansion

Expand the owner matrix only after the corresponding capability is integrated
and browser-green.

Required final ownership:

| Capability | Owner |
| --- | --- |
| supported text recommendation and followups | Guide |
| knowledge consultation entry | Guide |
| light consultation and confirmation | Guide |
| server Bundle image identify/similar/suitability | Guide |
| two-to-four image compare | Guide |
| supported scenario guidance | Guide |
| review/pitfall and feedback events | Guide |
| unsupported or unrelated text | legacy until explicitly removed |
| client-supplied legacy image candidates | rejected or legacy, never trusted by Guide |

No migrated capability may fall back to old V2 after an internal Guide error.

## 7. Frontend Integration

The frontend renders only typed backend events:

```text
consultation_observation
profile_confirmation
image_observation
decision_process
answer_contract
card_display_contract
products
citations
pitfalls
message
end
```

Required card behavior:

```text
single product/suitability -> 1
recommendation -> exact 1..3
two-image compare -> 2
three-image compare -> 3
four-image compare -> 4
knowledge/consultation collection/clarify/error -> 0
```

The frontend never infers product IDs from generated text and never fills card
slots.

## 8. Continuous Verification

After every integration commit:

```bash
$GUIDE_PYTHON -m pytest -c pytest-guide.ini -q <focused tests>
$GUIDE_PYTHON app/guide/check_boundaries.py app/guide
$GUIDE_PYTHON app/guide/check_boundaries.py app/guide_runtime
git diff --check
```

After each milestone:

```bash
$GUIDE_PYTHON -m pytest -c pytest-guide.ini -q
$GUIDE_PYTHON -m pytest -c pytest-guide.ini -q tests/guide/runtime
```

Run a real browser gate for each newly integrated user journey. Mock-only proof
does not complete a capability.

## 9. Final Four Vertical Gates

### Text Gate

```text
natural language
-> understanding
-> constraints
-> Canonical retrieval
-> deterministic decision
-> exact card contract
-> SSE/browser
```

### Image Gate

```text
one/two/four real images
-> safe bundle
-> OpenCLIP/OCR observation
-> confirmed identities
-> deterministic recommendation/comparison
-> exact cards
```

### Multi-Turn Gate

```text
knowledge question
-> light consultation
-> observations
-> provisional conclusion
-> user confirmation
-> profile fill
-> later recommendation uses profile only for missing context
```

### Clean Runtime Gate

```text
fresh environment
-> locked dependencies and assets
-> startup health
-> text/image/multi-turn browser flows
-> no old app.services imports
```

## 10. Final Audit and Completion

Run independent full-file review across every changed production file for:

```text
logic
business semantics
security
concurrency
robustness
performance
```

Every confirmed P0–P2 requires a RED test, fix, and complete gate rerun.
Do not run a second full-file audit after those fixes in the same final loop.

Completion requires:

- all tasks and checklist boxes checked;
- all ten Phase 2 capabilities in the design matrix complete;
- four vertical gates pass;
- Guide and runtime full suites pass;
- normal and adversarial browsers pass;
- no protected path or ranking SHA drift;
- no push/deploy/traffic switch;
- clean shared workspace;
- final append-only progress entry and handoff.

Intermediate milestone PASS is never overall COMPLETE.
