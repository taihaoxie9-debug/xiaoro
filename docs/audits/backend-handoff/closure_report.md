# Backend Handoff Closure Report

Date: 2026-08-15

Repository: `/Users/bytedance/Desktop/xiaoro-fresh`

Branch: `rebuild`

Final release status: `NO-GO`

## Executive Verdict

The backend ownership and evidence architecture requested for this phase is
closed:

```text
user message
  -> model translates current-turn meaning with source spans
  -> code validates references and exact revision proof
  -> one deterministic reducer computes state changes
  -> isolated evidence domains answer or rank only within allowed uses
  -> typed TaskPlan, SSE, and owner-bound CAS state
```

The local backend is green. The official model lane is not production-ready.
All three required official runs returned `selected_lane = null`, so this
phase stops before frontend implementation and does not release, push, deploy,
or switch traffic.

This is not a data, ranking, state-transition, or cross-vertical integration
failure. The remaining release blocker is the first semantic layer: official
model route/detail translation quality.

## Requirement Closure

### Selection concept identity

The main agent reviewed all 40 machine-style soft SelectionFacts across eight
products:

```text
reviewed: 40
kept closed enums: 6
normalized source-faithful concepts: 30
dropped weaker ordinary duplicates: 4
unresolved machine-style soft facts: 0
```

The audit preserves exact answer text, source locators, evidence strength,
qualifiers, disclaimers, and `allowed_uses`. It introduces no runtime alias or
global keyword dictionary.

```text
selection audit SHA-256:
7093fe8bfd4051d177ed6cd7121c8e368b7fd8ba2c5807cfc684e88633724413

final SelectionFacts:
total 2322
strength 1: 1312
strength 2: 463
non-ranking: 547
```

Fact identity is the scoring boundary. Repeated images or repeated projections
of one fact cannot accumulate extra score; the strongest admissible evidence
wins once per concept slot.

### Code-owned state transitions

`SemanticIntentProposal` no longer contains mutation acts. The model may
translate current-turn meaning and emit source-bound references, but it cannot
choose `add`, `retain`, `replace`, or `remove`.

The single state authority is:

```text
StoredState + current translated meaning
  -> exact/source validation
  -> reduce_constraint_state
  -> StateDelta
  -> TaskPlan
```

The reducer enforces:

- an unmentioned constraint is retained;
- an equal old/new value is retained, not modified;
- replacement requires exact revision proof;
- removal is value-bound;
- fresh recommendation does not inherit stale constraints;
- category replacement clears category-scoped slots;
- semantic output cannot weaken a safety state;
- exact and semantic equivalents deduplicate to one slot.

Runtime, budget/skin revision paths, and the official evaluator use the same
transition compiler and reducer. No reviewer model call or second state
decision engine was added.

### Trusted general knowledge

All 22 existing local Markdown documents were parsed and manually reviewed
block by block:

```text
candidate blocks: 241
reviewed blocks: 241
published blocks: 209
general_answer: 174
escalation_only: 27
product_specific_redirect: 8
rejected: 32
missing/duplicate/invalid/source mismatches: 0
```

Every reviewed block forbids:

```text
product_fact
hard_filter
soft_rank
safety_guarantee
profile_write
```

Content locks:

```text
manual review catalog:
afde2f019b05a5fb3a02acb30656217dc50aa2a4b132aecbaa84f234a7d40051

published blocks:
6ca9dfa1acda79972842645737760764662e7d53a5fc3276109110ea81d3e453

manifest logical self-hash:
562161e524dc63cd418cd8ddf098c3f41add86ecd9ef5a9cffee83865cadd10e
```

Retrieval and answer rendering are deterministic. GeneralKnowledge and
ProductEvidence are separate typed packets. A general block cannot prove a
product formula, rank a product, satisfy a hard condition, guarantee safety,
or write profile state. ProductEvidence requires explicit product scope.

### Cross-vertical handoff

The frozen matrix contains 35 real composed rows:

```text
profile: 6
image: 6
consultation: 7
knowledge: 8
recommendation/comparison/follow-up: 8
```

It proves:

- consultation confirmation writes an owner-bound profile;
- the same confirmed profile is consumed by text recommendation and the
  production image suitability flow;
- current explicit input overrides, but does not overwrite, long-term profile;
- another owner cannot read or mutate that profile;
- medical escalation does not become an ordinary profile fact;
- image identify, similarity, suitability, comparison, ambiguity, and ordinal
  paths remain typed and fail closed;
- general and product knowledge remain isolated through follow-up;
- safety conditions hard-gate while ordinary claims remain weak soft evidence;
- comparison/current-item/ordinal follow-up use bound objects;
- budget/skin replacement and fresh-request noninheritance use the one reducer.

```text
matrix rows and contract: 36 passed in 2.67s

matrix SHA-256:
1c6cf19865021628b064df24184081645804d172ff7147b7792211dba4f4a1b8

matrix test SHA-256:
1d645a2a528a19f483ce8ffcc022105589f4c7330cc769494c51a53bb53bf4a7
```

## Final Local Gates

All final local gates passed after the last implementation change:

```text
focused profile/image/consultation/knowledge/text verticals:
4719 passed in 35.51s

Guide full:
7492 passed, 5 warnings in 450.55s

Guide runtime:
275 passed in 80.95s

application + state + presentation/SSE + public contracts:
1137 passed in 32.79s

architecture and import boundaries:
25 passed in 2.44s

compileall app/tools:
passed

git diff --check:
passed

staged index:
empty
```

The five Guide-full warnings are pre-existing Pydantic protected-namespace and
legacy script invalid-escape warnings. They are not test failures and are not
on the production Guide path changed by this closure.

## Official Model Gates

Frozen thresholds were not changed:

```text
route >= 0.95
detail >= 0.90
hard-gate violations = 0
same non-null selected lane in all three runs
```

| Run | Selected lane | Pro route | Pro detail | Unsafe TaskPlan | Unauthorized transition | Hard override | Wrong product | Pro p95 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | `null` | 118/128 (92.19%) full | 55/112 (49.11%) full | 1 | 0 | 0 | 0 | 5821 ms |
| 2 | `null` | 119/128 (92.97%) full | 55/112 (49.11%) full | 1 | 0 | 0 | 0 | 6359 ms |
| 3 | `null` | 29/32 (90.63%) smoke | 14/26 (53.85%) smoke | 1 | 0 | 0 | 0 | 7577 ms |

Run 3 correctly skipped the 128-case full phase because Pro failed a smoke
hard gate.

Each run had one Flash schema-invalid row and one schema-invalid single-stage
control row. In all runs:

```text
invalid-output TaskPlan invocation: 0
unauthorized constraint transition: 0
hard constraint override: 0
wrong product selection: 0
```

Official evidence:

| Run | Summary SHA-256 | Stable normalized evidence SHA-256 |
|---|---|---|
| 1 | `34ee40db32ecc71a549fd14ebc1bc2a6f5f2a5e4c4db2881d4dfb008c2a11540` | `b9461ef3b40fdff033b36b405824ce19fdf148beea3111478cb207f9f5d5a08a` |
| 2 | `bd45111bd3b0395858354cf28372d62f404a9c928837f67810cce768828ed8d4` | `a3255e3a19aa7a170630dbfd99d119d0e86f5b711a4ad8e285e7ab29e2bdd6bd` |
| 3 | `1af51a5d7fd5896ff25a799ac9155dda96e2b354e3ed465b6e6e4f6bf4b2ae30` | `fc27f5c096511133c5bf6f3dd193e6364ff017fb2aea9ecdc7634ee93166c5da` |

The official result is therefore:

```text
semantic release: NO-GO
overall release: NO-GO
```

## Architecture Verdict

### Did this phase reach the target architecture?

Yes for backend responsibility ownership and typed integration. Model output
is treated as untrusted translation; code owns binding, state transitions,
safety, ranking, evidence permissions, and final TaskPlan construction.

No for production admission. The official translator does not meet the frozen
route/detail quality contract in any of three independent runs.

### What remains overloaded?

- The route model still performs the legitimate but difficult open-language
  job of choosing goal and topic. Deterministic binding availability has been
  removed from it, but its translation quality remains unstable.
- `text_recommendation_flow.py` orchestrates recommendation, product evidence,
  and general knowledge. Typed ports keep the domains isolated, but this is
  the broadest runtime coordinator.
- `composition.py` owns several content-addressed asset locks and dependency
  assembly. It does not make business decisions.

No remaining component owns both semantic translation and stored-state
mutation.

### What is still missing for production?

- a semantic lane that passes the unchanged 95% route and 90% detail gates
  three consecutive times;
- formal medical/regulatory review or a primary-source medical corpus for
  health-sensitive general education;
- frontend rendering of the new typed general-knowledge event;
- normal release engineering, deployment, observability, and traffic checks.

### Which failures are acceptable and bounded?

- lexical general-knowledge no-hit when no meaningful source anchor exists;
- product-specific redirect instead of treating general text as product fact;
- clarification when an ordinal, image, or focused object is not bound;
- blocked/ambiguous image evidence remaining unavailable rather than guessed;
- exact-excerpt answers retaining limitations of the reviewed source.

### What blocks frontend work?

By the agreed admission rule, the three-run official semantic gate blocks
starting frontend implementation. The backend event contract itself is ready,
but this Goal intentionally stops before renderer changes.

### What blocks production release?

The official semantic gate is the immediate blocker. Frontend implementation,
medical-content governance, and deployment validation are additional
production prerequisites.

## Frontend Freeze

```text
app/static/chat.html SHA-256:
70ec29f8298fb912e578b718a214619d590214ddcd556ad0ad7ab1613efdbc95
```

The file matches the pre-goal frozen hash. No frontend rendering change was
made during this closure.

## Final Path Inventory

Goal-owned production domains:

```text
app/guide/understanding/semantic_* and two_stage_semantic.py
app/guide/intent/constraint_transitions.py
app/guide/intent/transition_planning.py
app/guide/retrieval/selection_fact_*.py
app/guide/retrieval/merchant_claim_*.py
app/guide/retrieval/product_evidence_*.py
app/guide/retrieval/general_knowledge_*.py
app/guide/application/product_evidence_answer.py
app/guide/application/general_knowledge_answer.py
app/guide/application/text_recommendation_flow.py
app/guide/application/chat_api_adapter.py
app/guide/feedback/contracts.py
app/guide/presentation/sse_events.py
app/guide_runtime/composition.py
```

Goal-owned tools and frozen assets:

```text
tools/guide_data/
tools/guide_gates/
data/guide_merchant_claims/
data/guide_product_evidence/
data/guide_general_knowledge/
docs/audits/evidence-use/
docs/audits/product-evidence/
docs/audits/general-knowledge/
docs/audits/semantic-transitions/
docs/audits/backend-handoff/
```

Goal-owned verification lives under the corresponding
`tests/guide/{data,retrieval,understanding,intent,application,runtime,tools}`
modules and the frozen intent fixtures.

The worktree remains intentionally dirty and shared. No implementation or
asset was staged or committed by this closure. No legacy `app.services` RAG
was imported, no new webpage was crawled, no sub-agent was used, and nothing
was pushed or deployed.

