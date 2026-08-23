# XiaoRo Mainline Contract Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every production Guide turn render exactly one fact-backed public presentation, with correct product facts, price/spec bindings, recommendation intent, image behavior, and browser evidence.

**Architecture:** Keep `PublicPresentationContract` as the only public display owner. Add an explicit recommendation outcome (`explore` or `fit`), make price/spec alignment fail closed, and introduce one reusable projection that combines approved category facts and approved product evidence before either direct display or copywriter polishing. The browser consumes only the contract plus contract-bound product data; legacy messages and legacy display panels cannot become a second answer.

**Task 11 r4 architecture reset, strengthened by the r5 single-path
enforcement addendum approved on 2026-08-23:**

```text
HTTP UserTurn / typed image action
-> TurnMeaning                              untrusted translation proposal
-> compile_turn_meaning
-> StructuredUnderstanding                 admitted understanding
-> pre-routing typed evidence               facts needed to choose ownership
-> route_unified_turn                       exactly once
-> UnifiedRouteDecision                    only executable decision
-> processor.execute(decision, evidence)
-> ExecutionResult                         same decision + typed StateDelta
-> reduce_conversation_state
-> one validated ConversationSnapshot
-> one immutable validated envelope of encoded SSE frames
-> one optimistic-CAS save
-> emit the exact validated bytes
-> frontend-only rendering
```

`UnifiedRouteDecision` is the sole owner of executable responsibility,
processor, continuity, focus source, product bindings, and presentation mode.
The router consumes the admitted/compiled goal, never a superseded raw
operation. A processor may add evidence and outcome data but may not reinterpret
ownership. State and presentation are sibling projections of the same typed
execution result; presentation events are not parsed to guess business state.
The SSE boundary emits an already validated application envelope and never
creates a decision, processor identity, focus, lane mutation, or snapshot.

Keep the existing names `StructuredUnderstanding` and
`UnifiedRouteDecision`; do not add synonymous `AdmittedTurn` or
`ExecutableDecision` aliases. Add only the missing application boundary:

```text
ExecutionResult
  decision: the exact UnifiedRouteDecision passed to the processor
  state_delta: typed per-lane mutations
  terminal: PublicPresentationContract | typed clarification | typed error
  audit_events: typed non-public evidence
```

This is a **large architecture reset**, not a full product rewrite. Preserve
the already validated semantic contracts, routing rules, retrieval and
decision algorithms, public fact projection, presentation compiler, frontend
renderer, and bounded lane data. Replace the orchestration ownership,
processor return boundary, state construction/commit path, production ingress,
and production-path proof system. Do not make old and new orchestration coexist
in production.

Conversation memory is semantic, not a chronological transcript:

```text
exactly one active owner
+ latest recommendation slot (query + candidate batch)
+ latest product slot
+ latest confirmed-image slot
+ current consultation slot
+ latest general-knowledge slot
+ pending clarification/reply slot
```

Each lane keeps only its latest resumable state. A newer task in the same lane
overwrites that lane's older state. Cross-lane state remains dormant and may
be reactivated only by an admitted explicit return/reference. The system never
automatically jumps back after an interruption. Purely temporal or ambiguous
references such as "上上轮那个" must clarify unless the current typed authority
resolves exactly one object; no complete turn-history stack is added in this
release.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, typed SSE, SQLite conversation state, DeepSeek V4 Pro, OpenCLIP, RapidOCR, Playwright Chromium, pytest.

Plan revision: 2026-08-23-task11-r5

---

## Current Execution Status (2026-08-23)

```text
Tasks 1-10: completed and committed
Task 11: IN_PROGRESS_APPROVED; the r5 anti-patch amendment was approved
  through Goal continuation on 2026-08-23, and production execution resumes
  only in the exact Step 4.6.0a sequence
Task 12: BLOCKED
Release status: NOT READY
Latest r5 audit-only verification:
  176-turn HTTP matrix test file: 29 passed, but non-authorizing because
  several bypass/network counters and observed state edges are self-asserted
  focused mainline/state/HTTP suite: 550 passed, 1 failed because the current
  no-sentence-patch gate rejects ordinary product_id equality
  Task 11 file reconciliation: all intended changes/deletions are classified;
  one historical audit input must move to tests/fixtures and be restored, and
  unapproved transient/debug residue must be removed before commit
Latest complete zero-API candidate suite: 1320 passed (repair-epoch-07;
  historical and non-authorizing because it omitted production paths)
Latest zero-API browser fixture gate: 14/14 passed (frontend-only evidence)
All existing Task 11 readiness artifacts: historical and non-authorizing
Next authoritative candidate evidence: repair-epoch-08 after the complete r5
  single-path enforcement; repair-epoch-07 remains immutable historical
  evidence
Latest bounded real smoke: attempt-06 stopped at admission after a collecting
  consultation inherited a stale current-item reference; the historical row
  is independently reclassified and the r2 circuit remains open
Current revision: the r5 anti-patch amendment is approved and execution has
  resumed at Step 4.6.0a. The current worktree is not a
  candidate, no real-call authorization exists before complete local proof,
  and r1/r2/r3/r4 evidence remains immutable history
```

Completed task headings and steps are struck through or checked below, but
their detailed contracts, commands, and acceptance criteria remain in this
plan as permanent implementation history. Completion never disables the hard
prohibitions in Section 0.5.

## 0. Scope, Locked Decisions, And Non-Negotiable Rules

### 0.1 Repository and plan status

All implementation happens in:

```text
/Users/bytedance/Desktop/xiaoro-fresh
```

Do not edit:

```text
/Users/bytedance/Desktop/xiaoro-shopping-master
```

This plan supersedes the unresolved mainline portions of:

```text
docs/superpowers/plans/2026-08-20-final-guide-release-closure.md
```

The recording plan:

```text
docs/superpowers/plans/2026-08-20-recording-ready-guide-path.md
```

is historical. It described `/guide-recording`; the delivered recording
experience is `/chat?demo=1`. Task 1 freezes that experience as
`recording-v1` before any mainline work changes shared assets.

### 0.2 Final visual ownership

The following three surfaces are distinct and must never be merged:

```text
Product inline card:
  image + product name + price/specification only
  no favorite, no realtime-price link, no compact tags

Product detail block below the inline card:
  brand main
  + one to three selected public facts
  + XiaoRo recommendation reason when the responsibility permits it

"Products mentioned this turn" shelf:
  image + product name + price/specification + compact tags
  + favorite + realtime-price link
  no recommendation reason and no fit-pending text
```

The detail block is chosen by backend projection. The frontend must not
choose labels or infer facts from `category_facts`, `description`, raw
evidence, or ranking metadata.

### 0.3 Final recommendation semantics

Add one typed public distinction:

```text
recommendation_mode = explore | fit

explore:
  "recommend several products"
  candidate routes are parallel
  unique winner is forbidden

fit:
  "recommend the one that best fits me"
  usable user constraints are present
  exactly one selected product, fact-backed fit reason, and public
  "comprehensive recommendation" conclusion are required

comparison:
  user chooses among already known two or three products
  comparison rows + winner/tie/insufficient outcome are required
```

`fit` is not a product-ID shortcut. It is selected from the same decision
result, with user constraints and approved facts recorded in the contract.

### 0.4 Final comparison layout

Comparison rows are:

```text
brand main
+ only the dimensions the user asked for
+ current profile match
+ comprehensive judgment
```

Price is a comparison row only when the user asks about price, budget, or
value. A colloquial request is mapped to a controlled parent dimension:

```text
"怕闷" -> texture / fresh-feel dimension
"白天通勤" -> scene / daytime-use dimension
```

Do not append every available field to a table.

### 0.5 Hard prohibitions

```text
1. No product-ID special cases.
2. No input- or output-sentence keyword branch, literal match, regex, string
   replacement, or Prompt-only patch to repair a failure.
3. No second public answer from MessageEvent, legacy evidence panels, or
   displayProducts in Guide mode.
4. No unresolved/conflict price-specification pair in public UI.
5. No model decides what product facts exist or what direct fact rows render.
6. No lowering image identity thresholds before trace evidence identifies the
   earliest failing stage.
7. No real-model retry after a hard failure until a local proof identifies and
   repairs the earliest shared owner.
8. No full suite or 48-turn real batch before focused zero-API proofs and one
   bounded real smoke pass.
9. No raw exact_text, OCR transcript, source locator, fact ID, or internal
   validation language in public copy.
10. No normal deterministic presentation may be labeled as fallback merely
    because the copywriter is intentionally not called.
11. No attribution repair may scan a whole section and prepend a Chinese
    phrase to an unrelated copy block. Attribution must be block-owned and
    fact-ID-backed.
12. No semantic gate, state-restoration path, or Pydantic default may invent a
    missing recommendation mode basis. Missing typed state must fail locally.
13. No frontend-generated Chinese sentence may act as a hidden image router.
    Empty-text image actions must cross the API as a typed operation.
14. No release gate may accept an arbitrary clarification as proof that a fit
    request reached a legitimate evidence gap.
15. No real-model, paid-provider, non-loopback, or production-equivalent call
    with a real provider is allowed while any Task 11 Step 0, 0.5, 4.5, or 4.6
    item is open. The network-blocked local HTTP production-path proof required
    by Step 4.6 is explicitly allowed.
16. No Task 12 step, including local verification or evidence allocation, may
    begin before Task 11's machine completion precondition and commit exist.
17. No expected-contract matrix, handcrafted StructuredUnderstanding, direct
    router call, or prebuilt SSE fixture may be presented as proof for a
    production layer that it bypasses.
18. No zero-API summary may assert provider_call_count=0 merely because API
    keys were removed. Outbound non-loopback network must be blocked and
    attempted calls must be measured.
19. No `model_copy(update=...)` may change a discriminating field such as
    goal, mode, responsibility, recommendation outcome, focus, or state shape
    without reconstructing and validating the complete destination contract.
20. No in-memory, SQLite, or other production state boundary may accept a
    snapshot or expected-version value that another production state backend
    rejects.
21. No production configuration flag may select a legacy path that bypasses
    `TurnMeaning -> compile_turn_meaning -> route_unified_turn`.
22. `route_unified_turn` runs exactly once per accepted business turn. Flow,
    processor, adapter, clarification, and fallback code may not override,
    reconstruct, or synthesize its decision.
23. No processor or adapter may derive state from SSE, a presentation contract,
    intent text, or a processor-name table. State and presentation must be
    sibling fields of the same `ExecutionResult`.
24. No thread-local, context-local, global mutable slot, or adjacent-generator
    `next()` assumption may transport the canonical decision.
25. A processor may not persist conversation state. One accepted business turn
    performs one final validated optimistic-CAS save; pre-decision rejection or
    internal failure performs zero saves. Staged multi-save loops are forbidden.
26. A unit test that calls a processor, router, reducer, or frontend fixture
    directly may prove only that named layer. It may not authorize bounded
    smoke or claim production-path coverage.
27. No processor may call another processor. Image/OCR work before routing is
    a typed evidence collector, not a processor wrapper or secondary
    dispatcher.
28. After `route_unified_turn`, no production code may parse raw user text to
    add a product, scenario, constraint, operation, recommendation mode, mode
    basis, count, responsibility, or focus. A downstream inconsistency must
    fail closed and be repaired at the compiler/router owner.
29. Presentation and SSE code may not infer responsibility from presentation
    mode, inspect a later terminal to rewrite an earlier intent, or otherwise
    translate one business decision into another.
30. A typed lane name in `ConversationStateDelta` is insufficient. The
    persisted `ConversationSnapshot` must contain physically independent
    recommendation, product, confirmed-image, consultation, knowledge, and
    pending-reply slots. Two lanes may not share one storage field.
31. Public wire events are projected, encoded to final SSE bytes, and validated
    exactly once before CAS. The exact immutable byte envelope that passed
    validation is emitted after CAS; post-save projection, model dumping, JSON
    encoding, or SSE framing is forbidden.
32. Production-path counters, state edges, test scope, and network attempts
    must be measured at their real boundaries. A literal zero, fixture-declared
    observed edge, filename-derived scope, or caller-authored pass boolean is
    not evidence.
33. Test-only seams are allowed only for a frozen `TurnMeaning` provider,
    explicit initial-state setup, direct layer-contract tests, and prebuilt SSE
    frontend fixtures, plus request-scoped read-only observers that cannot
    return values or alter control flow. They must be named and classified.
    Only the frozen provider may appear in the Task 11
    `production_path_from_turn_meaning` proof, whose claimed boundary starts at
    `TurnMeaning`; every other seam is a bypass and disqualifies that test from
    a production-path claim. No test seam may be imported or selected by
    default production composition.
34. Historical compatibility is allowed only as a one-way, fail-closed data
    migration at a persistence boundary. Legacy request fields, domain unions,
    processor entrypoints, output adapters, and dead fixtures are not permitted
    in the final production or test surface.
35. A browser gate may not trust a caller-supplied `base_url`. A fixture
    runtime identity contains the candidate manifest hash, plan revision, code
    revision, protected-payload hash, process identity, and runtime nonce. Each
    browser invocation obtains and atomically consumes its own fresh health
    challenge from that runtime. A bounded/release runtime identity additionally
    contains the readiness hash and attempt ID. The runner verifies the
    applicable identity before consuming authorization or sending a business
    request. A consumed challenge cannot authorize a second invocation.
36. Guide has one production response transport: the typed streaming endpoint.
    A sibling JSON/non-streaming endpoint may not collect, reshape, or expose
    the same business events as a second public path.
37. "Uncommitted", "temporary", "needed for migration", and "will be deleted
    later" are not exemptions. No intermediate production revision may add a
    compatibility bridge, second dispatcher, result wrapper, semantic
    reconstruction, fake identity, or alternate encoder that the final
    architecture forbids.
38. A migration seam may exist only under `tests/` and only with an explicit
    `unit`, `layer_contract`, or `frontend_fixture` scope. Production modules,
    production composition, release tools, and authorizing evidence may not
    import, select, or transitively execute it. The architecture gate must
    prove this physical isolation; naming a production helper "test-only" is
    not isolation. The frozen provider allowed by Rule 33 is a declared proof
    boundary, not a migration bridge, and remains subject to Rule 33's narrower
    claim.
39. A legacy test is never authority to restore a removed production
    interface, field, registry override, result adapter, output collector, or
    second semantic pass. Migrate, reclassify, or delete that test while
    preserving its legitimate layer assertion.
40. Every RED-to-GREEN slice must end in the final architecture for the
    capability it touches. A slice may not first add a production bridge to
    turn old tests green and defer bridge deletion to another slice or commit.
    GREEN means both the focused behavior test and the architecture gate pass.
41. When a required final boundary does not yet exist, implement that boundary
    first: `ProcessorExecutionInput`, one fixed processor registry, ingress-
    owned `TurnIdentity`, the canonical pre-CAS byte-envelope owner, and the
    AST/import/call-graph gate. Do not temporarily substitute a wrapper,
    adapter, dynamic registry override, copied `ExecutionResult`, or fabricated
    request/turn identity.
42. Processor selection may depend only on `decision.processor` against one
    registry constructed once by production composition. Request source, image
    presence, endpoint, pending state, or test configuration may not replace a
    registry entry. If two implementations are genuinely distinct processors,
    the Router emits distinct canonical processor IDs.
43. No processor result may be post-wrapped to add or rewrite intent,
    responsibility, typed evidence, profile ownership, image state, audit
    events, or another lane mutation. Required data enters through
    `ProcessorExecutionInput`; the selected processor returns the complete
    `ExecutionResult` once.
44. The architecture checker and its negative mutation tests are a prerequisite
    to further Task 11 production edits. It must fail on the current bridges
    before they are removed and must run after every focused GREEN. Deferring
    this checker until production migration is complete is forbidden.
45. The production bridges listed in Step 4.6.0 are stop-work blockers. Remove
    them through the final typed owners before test migration, matrix expansion,
    readiness work, bounded smoke, or any other Task 11 implementation.
```

These prohibitions remain active after the corresponding task is marked
complete. A green test that encodes a prohibited shortcut is not release
evidence.

### 0.6 Required audit artifact per production-equivalent browser turn

Every final browser turn stores one directory containing:

```text
request.json              exact user input and browser viewport
stream.sse                raw production SSE bytes
presentation-contract.json
terminal-dom.json         visible text, section kinds, product IDs, card count
screenshot.png
console.json
network.json
```

The screenshot is accepted only if the same directory has a valid contract
and DOM audit. A screenshot alone is not release evidence.

### 0.7 Existing WIP and commit safety

Execution starts on the existing non-main branch:

```text
wip/final-guide-release-closure-20260820
```

The worktree already contains reviewed but uncommitted Guide work. Preserve it:

```text
1. Before Task 1, run the focused tests that cover every modified source file.
2. Create one exact-file WIP checkpoint commit for the existing Guide source,
   tests, accepted `/chat?demo=1` fixture, and this plan.
3. Do not stage `app/static/demo.html`, debug notes, temporary screenshots,
   `.dbg/`, `.tmp-*`, or historical audit output in that checkpoint.
4. Before every later commit, inspect `git diff -- <exact task files>`.
5. Every `git add` uses exact files. Directory-level staging such as
   `git add app/guide/presentation` or `git add tests/guide` is forbidden.
6. Never revert, stash, or overwrite unrelated dirty files.
```

The current branch is already isolated from `main`; do not create a clean
worktree that would silently drop this WIP baseline.

Except for a major unresolved architecture issue that genuinely requires a user decision, including a circuit-breaker condition that requires an approved plan revision, the executor must autonomously diagnose, repair, test, independently audit, and continue past every minor implementation, test, evidence, or tooling issue without pausing for user confirmation.

### 0.8 Smoke-loop circuit breaker

Every real-model or production-equivalent smoke run follows this stop rule:

```text
1. Stop at the first serious failure and preserve its complete evidence bundle.
2. Classify the earliest failing owner:
   translation -> admission -> planning/state -> retrieval/identity ->
   fact projection -> copy/attribution -> presentation provenance ->
   SSE contract -> DOM rendering.
3. If the same owner fails twice anywhere in the persistent attempt ledger,
   freeze all further real calls. The failures need not be consecutive and
   reopening an agent session does not reset the count.
4. Before another real call, require all four:
   a deterministic local reproduction,
   a focused regression test that failed before the repair,
   a repair in the earliest shared owner rather than the observed sentence,
   and an independent read-only audit of the resulting diff.
5. Run focused zero-API tests and the desktop/mobile fixture browser gate.
6. Make exactly one newly authorized real-call phase. The phase is explicitly
   one of: Task 11 bounded browser smoke, Task 12 48-turn translation, or
   Task 12 release browser audit.
7. If that attempt exposes a different owner, repeat from Step 1. Never stack
   multiple smoke-specific patches before identifying the new earliest owner.
8. If the post-proof phase fails at the same owner again, stop the currently
   active task, reopen the owner contract design, and request user review. No
   further real call is allowed under the current plan revision.
```

Changing Prompt wording, adding a product ID branch, changing the synthetic
frontend sentence, weakening a validator, or allowing a new fallback does not
reset the failure count.

Persist every attempt in:

```text
docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json
```

Each ledger row records:

```text
attempt_id
plan_revision
repair_epoch
retry_authorization_id
code_revision
started_at
trajectory_set
first_failure_turn_id
first_failure_owner
failure_code
evidence_directory
local_reproduction
focused_test
shared_owner_repair
independent_audit
result
```

Before starting a real smoke, the runner must read this ledger and refuse the
run when the circuit breaker is open for the readiness plan revision. Every
attempt uses a new immutable directory such as
`bounded-smoke-attempt-03`; never delete, reuse, or overwrite an earlier
attempt directory. Historical failures remain in the ledger forever; a
user-approved new plan revision starts a new count without deleting history.

After the local reproduction, focused regression, shared-owner repair, and
independent audit required by Step 4 exist, a reviewer may issue one
`retry_authorization_id` for one owner, one `repair_epoch`, and one
`plan_revision`. The runner consumes that authorization before its first
request. It cannot be reused. If the authorized attempt fails at the same
owner, the circuit is permanently open for that plan revision. Only a
user-approved new plan revision may allocate another authorization.

Changing an owner label or failure code does not reset the count. A proposed
reclassification must cite the same evidence bundle and pass independent
review before the ledger owner may change.

Authorization is issued only through:

```text
attempt_ledger.py authorize
  --phase <bounded|translation|browser>
  --readiness <candidate-or-release-readiness>
  --ledger <ledger>
  --independent-audit <review-result.json>
```

The command derives `first_failure_owner`, `repair_epoch`, and `plan_revision`
from the ledger and readiness; callers cannot supply or override them. It
verifies the repair evidence and independent audit hashes recorded in
readiness, writes one allocated authorization, and prints its ID. `allocate`
and `allocate-child` require that exact ID and reject phase, plan revision,
repair epoch, owner, or readiness mismatches.

For the first execution of a phase with no historical failure in the current
plan revision, the tool assigns owner `planned_gate` and `repair_epoch=0`, and
requires the independent audit already bound into readiness. After any
failure, `planned_gate` authorization is forbidden and the repair evidence
rules above apply.

`tools/guide_gates/attempt_ledger.py` is the only ledger writer. It uses an
`fcntl.flock` lock file, compares an integer ledger revision before every
mutation, writes a sibling temporary file, flushes and `fsync`s the file,
atomically replaces the ledger with `os.replace`, then `fsync`s the parent
directory. Authorization state transitions are:

```text
allocated -> consumed -> passed | failed
```

A consumed authorization can never return to allocated. Startup recovery may
delete an orphan temporary file only while holding the lock and only when the
canonical ledger parses and its revision is valid. Tests must cover two
concurrent consumers, stale-revision rejection, interruption after temporary
file write, recovery from an orphan temporary file, and permanent rejection of
a consumed authorization.

The same tool creates an immutable attempt-context JSON. Every later command
receives only `--attempt-context`; it does not depend on shell variables from a
previous command block. The context contains:

```text
parent_attempt_id
phase_attempt_ids
phase_authorization_ids
output_directory
readiness_path
ledger_path
allocated_ledger_revision
```

The tool rejects an existing context path or output directory. Reading a
context requires the current ledger revision to be at least the allocation
revision, then revalidates the referenced immutable attempt record instead of
requiring revision equality after later legal transitions. `allocate` and
`allocate-child` print the newly created unique context path to stdout.
`current` prints a context only when exactly one matching,
nonterminal context exists for the requested phase and plan revision;
otherwise it fails. `current` and `latest` both require `--readiness`; they
derive the plan revision from that file and never search across plan
revisions. `latest --result X` inspects the newest matching context and asserts
that its result is `X`; it never searches backward for an older context with
the requested result.

## 1. File Map

| Area | Files | Responsibility |
| --- | --- | --- |
| Frozen recording mode | `app/guide_runtime/app.py`, `app/static/recording-v1/chat.html`, `app/static/recording-v1/guide-presentation.js`, `app/static/recording-v1/guide-demo-fixture.js`, `app/static/recording-v1/vendor/feather.min.js`, `app/static/recording-v1/images/`, `app/static/recording-v1/manifest.json` | Immutable typed-input recording surface including visual dependencies |
| Public contract | `app/guide/presentation/public_contracts.py`, `app/guide/presentation/copywriter_contracts.py`, `app/guide/presentation/presentation_packet.py`, `app/guide/presentation/presentation_compiler.py` | Typed `explore`/`fit`/comparison shapes from request meaning through the public SSE payload |
| Product cards and price/spec | `app/guide/presentation/contracts.py`, `app/guide/presentation/response_planning.py`, `app/guide/application/chat_api_adapter.py`, `app/static/chat.html`, `app/guide/presentation/presentation_packet.py` | Fail-closed price/spec serialization and display |
| Shared fact projection | Create `app/guide/presentation/public_fact_contracts.py` and `app/guide/presentation/public_fact_projection.py`; modify `app/guide/application/product_evidence_answer.py`, `app/guide/application/text_recommendation_flow.py`, `app/guide/presentation/presentation_packet.py` | One A-cabinet + B-cabinet public fact source without circular imports |
| Card detail selection | Create `app/guide/presentation/product_detail_selection.py`; modify `app/guide/presentation/copywriter_contracts.py`, `app/guide/presentation/presentation_packet.py`, `app/guide/presentation/presentation_compiler.py`, `app/guide/presentation/public_contracts.py`, `app/static/guide-presentation.js` | Product detail block beneath a recommendation or image-identity inline card |
| Comparison row policy | `app/guide/presentation/comparison_planning.py`, `app/guide/presentation/presentation_packet.py`, `app/guide/presentation/public_contracts.py` | Brand main + requested dimensions + current profile match; price only when requested |
| One public render | `app/guide/application/unified_guide_flow.py`, `app/guide/application/text_recommendation_flow.py`, `app/guide/application/image_recommendation_flow.py`, `app/guide/application/consultation_chat_flow.py`, `app/guide/application/chat_api_adapter.py`, `app/static/chat.html` | One presentation contract per Guide terminal turn |
| Canonical turn orchestration | `app/guide/application/unified_guide_flow.py`, `app/guide/application/execution_contracts.py`, `app/guide/intent/executable_intent_compiler.py`, `app/guide/intent/unified_turn_router.py` | One compiler, one route decision, one `ExecutionResult`; no alternate production ingress |
| State reduction and commit | `app/guide/application/conversation_state_reducer.py`, `app/guide/adapters/state/in_memory_conversation_state.py`, `app/guide/adapters/state/sqlite_conversation_state.py` | Typed lane mutations, one reducer, one validated optimistic-CAS save |
| Image root-cause trace | Create `tools/guide_gates/trace_image_identity_pipeline.py`; modify `app/guide/understanding/image_identity.py`, `app/guide/application/image_recommendation_flow.py` | Identify OCR, visual, fusion, retrieval, or presentation owner |
| Semantic mode ownership | `app/guide/understanding/turn_meaning_contracts.py`, `app/guide/adapters/llm/turn_meaning_prompt.py`, `app/guide/adapters/llm/turn_meaning_adapter.py`, `app/guide/intent/semantic_admission.py`, `app/guide/understanding/contracts.py`, `app/guide/intent/executable_intent_compiler.py`, `tools/guide_gates/build_semantic_equivalence_matrix.py` | Recommendation parent mode plus source-grounded child basis; no raw-message keyword or regex routing |
| Semantic and copy gate | `app/guide/understanding/exact_parsing.py`, `app/guide/intent/unified_turn_router.py`, `app/guide/presentation/copywriter_validation.py`, `app/guide/presentation/copywriter_prompt.py` | Shared semantic equivalence and fact-ID validation |
| Evidence harness | Create `tools/guide_gates/run_task11_production_path_matrix.py`, `tools/guide_gates/zero_api_network_guard.py`, and `tools/guide_gates/run_mainline_contract_browser_audit.py`; modify `tools/guide_gates/build_task11_readiness.py` and `tools/guide_gates/run_final_release_gate.py` | Prove the real HTTP path, measured zero-network execution, raw SSE, contract, DOM, screenshot, and browser telemetry |

## 2. Implementation Tasks

### Execution preflight: seal the accepted WIP baseline

Run zero-API checks over the already modified Guide files:

```bash
git diff --check
PYTHONPATH=. .venv/bin/python -m compileall -q app tools tests
PYTHONPATH=. .venv/bin/pytest -q \
  tests/guide/adapters/test_presentation_copywriter.py \
  tests/guide/application/test_image_presentation_integration.py \
  tests/guide/application/test_product_evidence_answer.py \
  tests/guide/application/test_text_presentation_integration.py \
  tests/guide/presentation/test_copywriter_prompt.py \
  tests/guide/runtime/test_composition.py \
  tests/guide/runtime/test_frontend_card_binding.py \
  tests/guide/runtime/test_frontend_presentation_stream.py \
  tests/guide/runtime/test_runtime_http.py \
  tests/guide/tools/test_run_real_continuous_conversation_browser_audit.py \
  tests/guide/understanding/test_exact_parsing.py \
  tests/guide/understanding/test_image_identity_observation.py
```

If green, inspect and checkpoint only the accepted WIP:

```bash
git diff -- \
  app/guide app/static/chat.html app/static/guide-presentation.js \
  tests/guide tools/guide_gates/run_real_continuous_conversation_browser_audit.py \
  docs/superpowers/plans/2026-08-20-final-guide-release-closure.md \
  docs/superpowers/plans/2026-08-21-guide-mainline-contract-closure.md

git add \
  app/guide/adapters/llm/presentation_copywriter_adapter.py \
  app/guide/application/product_evidence_answer.py \
  app/guide/application/text_recommendation_flow.py \
  app/guide/application/unified_guide_flow.py \
  app/guide/intent/unified_turn_router.py \
  app/guide/presentation/copywriter_prompt.py \
  app/guide/presentation/copywriter_references.py \
  app/guide/understanding/exact_parsing.py \
  app/guide/understanding/image_contracts.py \
  app/guide/understanding/image_identity.py \
  app/static/chat.html \
  app/static/guide-presentation.js \
  app/static/guide-demo-fixture.js \
  tests/guide/adapters/test_presentation_copywriter.py \
  tests/guide/application/test_image_presentation_integration.py \
  tests/guide/application/test_product_evidence_answer.py \
  tests/guide/application/test_text_presentation_integration.py \
  tests/guide/presentation/test_copywriter_prompt.py \
  tests/guide/presentation/test_winner_presentation_contract.py \
  tests/guide/runtime/test_composition.py \
  tests/guide/runtime/test_frontend_card_binding.py \
  tests/guide/runtime/test_frontend_presentation_stream.py \
  tests/guide/runtime/test_runtime_http.py \
  tests/guide/tools/test_run_real_continuous_conversation_browser_audit.py \
  tests/guide/tools/test_semantic_equivalence_matrix.py \
  tests/guide/understanding/test_exact_parsing.py \
  tests/guide/understanding/test_image_identity_observation.py \
  tools/guide_gates/run_real_continuous_conversation_browser_audit.py \
  tools/guide_gates/build_semantic_equivalence_matrix.py \
  docs/superpowers/plans/2026-08-20-final-guide-release-closure.md \
  docs/superpowers/plans/2026-08-21-guide-mainline-contract-closure.md
git commit -m "chore(guide): checkpoint final closure wip"
```

Confirm `app/static/demo.html`, debug notes, `.dbg/`, `.tmp-*`, screenshots,
and historical audit directories remain unstaged.

### ~~Task 1: Freeze the recording demo before changing shared production assets~~ (completed)

**Files:**
- Create: `app/static/recording-v1/chat.html`
- Create: `app/static/recording-v1/guide-presentation.js`
- Create: `app/static/recording-v1/guide-demo-fixture.js`
- Create: `app/static/recording-v1/vendor/feather.min.js`
- Create: `app/static/recording-v1/images/jd_v3_100022610146.png`
- Create: `app/static/recording-v1/images/jd_v3_100049220178.png`
- Create: `app/static/recording-v1/images/jd_v3_100160480140.png`
- Create: `app/static/recording-v1/images/tmall_v3_998532090974.png`
- Create: `app/static/recording-v1/images/jd_v3_10069603621835.png`
- Create: `app/static/recording-v1/images/jd_v3_100005935030.png`
- Create: `app/static/recording-v1/images/jd_v3_100022610088.png`
- Create: `app/static/recording-v1/manifest.json`
- Modify: `app/guide_runtime/app.py`
- Modify: `tests/guide/runtime/test_runtime_http.py`
- Modify: `tests/guide/runtime/test_frontend_presentation_stream.py`

- [x] **Step 1: Write the failing immutable-route tests**

```python
def test_recording_v1_serves_versioned_chat_snapshot(client) -> None:
    response = client.get("/chat?demo=recording-v1")

    assert response.status_code == 200
    assert "/static/recording-v1/guide-presentation.js" in response.text
    assert "/static/recording-v1/guide-demo-fixture.js" in response.text
    snapshot = Path("app/static/recording-v1/chat.html").read_text(
        encoding="utf-8"
    )
    assert "recording-v1" in snapshot
    assert "window.XiaoRoDemoFixture.createResponse" in snapshot
    assert "fetch('/api/v1/chat/stream'" not in snapshot


def test_recording_manifest_hashes_every_loaded_asset() -> None:
    manifest = json.loads(
        Path("app/static/recording-v1/manifest.json").read_text()
    )

    assert manifest["version"] == "recording-v1"
    assert set(manifest["assets"]) == {
        "chat.html",
        "guide-presentation.js",
        "guide-demo-fixture.js",
        "vendor/feather.min.js",
        "images/jd_v3_100022610146.png",
        "images/jd_v3_100049220178.png",
        "images/jd_v3_100160480140.png",
        "images/tmall_v3_998532090974.png",
        "images/jd_v3_10069603621835.png",
        "images/jd_v3_100005935030.png",
        "images/jd_v3_100022610088.png",
    }
    assert all(
        re.fullmatch(r"[0-9a-f]{64}", digest)
        for digest in manifest["assets"].values()
    )
    assert all(
        digest == hashlib.sha256(
            (Path("app/static/recording-v1") / name).read_bytes()
        ).hexdigest()
        for name, digest in manifest["assets"].items()
    )
    assert "https://unpkg.com" not in snapshot
    assert "/static/images/products/" not in (
        Path("app/static/recording-v1/guide-demo-fixture.js")
        .read_text(encoding="utf-8")
    )
```

- [x] **Step 2: Run the tests to prove the route is not frozen**

Run:

```bash
PYTHONPATH=. .venv/bin/pytest -q \
  tests/guide/runtime/test_runtime_http.py \
  tests/guide/runtime/test_frontend_presentation_stream.py \
  -k 'recording_v1 or recording_manifest'
```

Expected: FAIL because `recording-v1` assets and route do not exist.

- [x] **Step 3: Create the snapshot and route**

Copy the currently accepted recording chat implementation, renderer, fixture,
the exact seven referenced product images, and Feather Icons 4.29.2 into the
immutable directory. Rewrite the snapshot HTML and fixture to use only
`/static/recording-v1/...` assets. Extract the existing chat response
assembly (runtime scope injection, no-cache headers, and feedback cookie) into
one private helper so the normal page and snapshot retain the same response
envelope. In `app/guide_runtime/app.py`, choose only the page path by explicit
version:

```python
def _chat_response(
    *,
    request: Request,
    page_path: Path,
) -> HTMLResponse:
    html = page_path.read_text(encoding="utf-8")
    scope = (
        '<script>window.__XIAORO_RUNTIME_SCOPE__='
        f'"{RUNTIME_SCOPE}";</script>'
    )
    html = html.replace("</head>", f"{scope}\n</head>", 1)
    response = HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
        },
    )
    actor_session = resolve_feedback_actor_session(
        request,
        authorized_session_id="feedback-cookie-bootstrap",
    )
    set_feedback_session_cookie(
        response,
        actor_session,
        secure=request.url.scheme == "https",
    )
    return response


@app.get("/chat")
def chat(request: Request) -> HTMLResponse:
    page_path = (
        static_root / "recording-v1" / "chat.html"
        if request.query_params.get("demo") == "recording-v1"
        else chat_path
    )
    return _chat_response(request=request, page_path=page_path)
```

The snapshot's `GUIDE_DEMO_MODE` must accept only `recording-v1`, and its
request branch must call only
`window.XiaoRoDemoFixture.createResponse({ message, images, sessionId, conversationVersion })`.
The snapshot must not retain an executable production `fetch()` branch. Keep
the existing `?demo=1` page untouched until the recorded artifact has been
checksum-verified; it is not the frozen route. Generate `manifest.json` with
SHA-256 digests of every snapshot code and image asset listed in Step 1.
Do not make production `/chat` load snapshot scripts. The frozen page must make
zero external network requests during a Playwright smoke run.

- [x] **Step 4: Run the focused recording tests**

Run:

```bash
PYTHONPATH=. .venv/bin/pytest -q \
  tests/guide/runtime/test_runtime_http.py \
  tests/guide/runtime/test_frontend_presentation_stream.py \
  -k 'recording_v1 or demo_fixture'
```

Expected: PASS.

- [x] **Step 5: Commit the frozen recording boundary**

```bash
git add \
  app/guide_runtime/app.py \
  app/static/recording-v1/chat.html \
  app/static/recording-v1/guide-presentation.js \
  app/static/recording-v1/guide-demo-fixture.js \
  app/static/recording-v1/vendor/feather.min.js \
  app/static/recording-v1/images/jd_v3_100022610146.png \
  app/static/recording-v1/images/jd_v3_100049220178.png \
  app/static/recording-v1/images/jd_v3_100160480140.png \
  app/static/recording-v1/images/tmall_v3_998532090974.png \
  app/static/recording-v1/images/jd_v3_10069603621835.png \
  app/static/recording-v1/images/jd_v3_100005935030.png \
  app/static/recording-v1/images/jd_v3_100022610088.png \
  app/static/recording-v1/manifest.json \
  tests/guide/runtime/test_runtime_http.py \
  tests/guide/runtime/test_frontend_presentation_stream.py
git commit -m "feat(recording): freeze recording-v1 chat experience"
```

### ~~Task 2: Add typed explore and fit recommendation outcomes~~ (completed)

**Files:**
- Modify: `app/guide/understanding/turn_meaning_contracts.py`
- Modify: `app/guide/adapters/llm/turn_meaning_prompt.py`
- Modify: `app/guide/adapters/llm/turn_meaning_adapter.py`
- Modify: `app/guide/understanding/single_call_understanding.py`
- Modify: `app/guide/intent/semantic_admission.py`
- Modify: `app/guide/intent/contracts.py`
- Modify: `app/guide/intent/task_planning.py`
- Modify: `app/guide/intent/executable_intent_compiler.py`
- Modify: `app/guide/presentation/public_contracts.py`
- Modify: `app/guide/presentation/copywriter_contracts.py`
- Modify: `app/guide/presentation/presentation_packet.py`
- Modify: `app/guide/presentation/presentation_compiler.py`
- Modify: `app/guide/application/text_recommendation_flow.py`
- Modify: `app/guide/application/image_recommendation_flow.py`
- Modify: `app/static/guide-presentation.js`
- Test: `tests/guide/understanding/test_turn_meaning_contracts.py`
- Test: `tests/guide/adapters/test_turn_meaning_prompt.py`
- Test: `tests/guide/adapters/test_deepseek_turn_meaning.py`
- Test: `tests/guide/adapters/test_siliconflow_turn_meaning.py`
- Test: `tests/guide/intent/test_semantic_admission.py`
- Test: `tests/guide/intent/test_task_planning.py`
- Test: `tests/guide/intent/test_executable_intent_compiler.py`
- Test: `tests/guide/presentation/test_public_contracts.py`
- Test: `tests/guide/presentation/test_winner_presentation_contract.py`
- Test: `tests/guide/application/test_text_presentation_integration.py`
- Test: `tests/guide/application/test_image_presentation_integration.py`

- [x] **Step 1: Add failing contract tests**

```python
def test_explore_recommendation_forbids_selected_product() -> None:
    with pytest.raises(ValueError, match="explore recommendation"):
        PublicPresentationContract(
            responsibility=Responsibility.RECOMMENDATION,
            recommendation_mode="explore",
            winner=WinnerPresentation(
                status="selected",
                winner_product_id=33,
                reason="换季泛红优先时更贴修护舒缓方向。",
                fact_ids=("f-33",),
                dimension_ids=("repair",),
            ),
            **_recommendation_fields(),
        )


def test_fit_recommendation_requires_fact_backed_selected_product() -> None:
    contract = PublicPresentationContract(
        responsibility=Responsibility.RECOMMENDATION,
        recommendation_mode="fit",
        winner=WinnerPresentation(
            status="selected",
            winner_product_id=33,
            reason="换季泛红优先时更贴修护舒缓方向。",
            fact_ids=("card:33:efficacy",),
            dimension_ids=("repair", "skin_fit"),
        ),
        **_recommendation_fields(visible_product_ids=(33,)),
    )

    assert contract.recommendation_mode == "fit"
    assert contract.visible_product_ids == (33,)


def test_fit_recommendation_forbids_multiple_visible_products() -> None:
    with pytest.raises(ValueError, match="fit recommendation requires one"):
        PublicPresentationContract(
            responsibility=Responsibility.RECOMMENDATION,
            recommendation_mode="fit",
            winner=WinnerPresentation(
                status="selected",
                winner_product_id=33,
                reason="换季泛红优先时更贴修护舒缓方向。",
                fact_ids=("card:33:efficacy",),
                dimension_ids=("repair", "skin_fit"),
            ),
            **_recommendation_fields(visible_product_ids=(33, 39)),
        )


def _recommendation_fields(
    *,
    visible_product_ids: tuple[int, ...] = (33, 39),
) -> dict[str, object]:
    return {
        "mode": "recommendation",
        "copy_source": "fallback",
        "sections": (
            PresentationSection(kind="summary", copy_text="先看两条路线。"),
            *(
                PresentationSection(
                    kind="product",
                    slot_id=f"p{index}",
                    product_id=product_id,
                    copy_text="按当前条件继续判断。",
                    advisor_reason="结合当前需求取舍。",
                )
                for index, product_id in enumerate(
                    visible_product_ids,
                    start=1,
                )
            ),
            PresentationSection(kind="closing", copy_text="再按重点收窄。"),
            PresentationSection(kind="full_cards"),
        ),
        "comparison_rows": (),
        "visible_product_ids": visible_product_ids,
        "compact_tags": (),
        "card_display": CardDisplayContract(
            mode="recommendation",
            visible_product_ids=visible_product_ids,
            max_cards=len(visible_product_ids),
            reason="recommendation",
        ),
        "telemetry": _telemetry(),
    }
```

- [x] **Step 2: Run the tests to prove recommendation has no typed outcome**

Run:

```bash
PYTHONPATH=. .venv/bin/pytest -q \
  tests/guide/understanding/test_turn_meaning_contracts.py \
  tests/guide/adapters/test_turn_meaning_prompt.py \
  tests/guide/intent/test_semantic_admission.py \
  tests/guide/intent/test_task_planning.py \
  tests/guide/intent/test_executable_intent_compiler.py \
  tests/guide/presentation/test_public_contracts.py \
  tests/guide/presentation/test_winner_presentation_contract.py \
  -k 'explore or fit'
```

Expected: FAIL because non-comparison responsibilities currently forbid every
winner outcome.

- [x] **Step 3: Add `RecommendationMode` through packet and compiler**

Define `RecommendationMode` beside the source semantic contract in
`app/guide/understanding/turn_meaning_contracts.py`; re-export that exact
alias from `app/guide/intent/contracts.py` for presentation consumers. Thread the field through
`TurnMeaning`, `TaskPlan`, `PresentationPacket`,
`build_presentation_packet()`, and `PublicPresentationContract`:

```python
RecommendationMode = Literal["explore", "fit"]


# app/guide/understanding/turn_meaning_contracts.py
class TurnMeaning(_StrictFrozenModel):
    recommendation_mode: RecommendationMode | None = None


# app/guide/intent/contracts.py
class TaskPlan(_StrictContract):
    recommendation_mode: RecommendationMode | None = None


# app/guide/presentation/copywriter_contracts.py
class PresentationPacket(_StrictFrozen):
    recommendation_mode: RecommendationMode | None = None


# app/guide/presentation/public_contracts.py
class PublicPresentationContract(_StrictFrozen):
    recommendation_mode: RecommendationMode | None = None
```

Apply these invariants:

```python
if self.responsibility is Responsibility.RECOMMENDATION:
    if recommendation_mode not in {"explore", "fit"}:
        raise ValueError("recommendation requires recommendation_mode")
    if recommendation_mode == "explore":
        if self.winner.status != "not_applicable":
            raise ValueError("explore recommendation forbids winner")
    else:
        if len(self.visible_product_ids) != 1:
            raise ValueError("fit recommendation requires one product")
        if self.winner.status != "selected":
            raise ValueError("fit recommendation requires selected winner")
        if self.winner.winner_product_id != self.visible_product_ids[0]:
            raise ValueError("fit winner must equal the visible product")
else:
    if recommendation_mode is not None:
        raise ValueError("non-recommendation forbids recommendation_mode")
```

`TaskPlan.recommendation_mode` is populated from the typed
`TurnMeaning.recommendation_mode`, not by raw message matching in a flow. Its
only legal values are:

```text
explore: multiple parallel routes, or a recommendation request without enough
         usable constraints to select one product safely
fit:     the user explicitly requests the best-fit single product and has a
         category/budget plus at least one usable need, skin, concern, or
         scenario constraint
```

When `fit` is requested but the usable constraints are incomplete, create a
typed clarification instead of silently downgrading to a ranked first item.
Update `turn_meaning_prompt.py`, bump its prompt version, and require
`recommendation_mode` as an exact JSON key. It is `explore|fit` for
`recommendation` and `image_similarity`, and `null` for all other operations.
Before `TurnMeaning.model_validate_json()`, parse the provider JSON as an
object and require its key set to equal `TurnMeaning`'s public schema key set.
This prevents Pydantic's optional default from silently accepting a provider
response that omitted `recommendation_mode`. Add adapter tests for both a
missing key and an extra key. Add the closed value to semantic admission. The
exact-parser fallback sets it to `null`; task planning must clarify rather than
guess when a one-best request cannot be typed safely.
Modify `_build_winner_presentation()` so it accepts the selected decision
product for `recommendation_mode == "fit"` and builds its reason from the
selected approved facts and constraint IDs rather than the hard-coded
comparison sentence.

In the text and image flows, use the precomputed `TaskPlan.recommendation_mode`
to select the visible-card limit:

```text
explore:
  the typed batch size from TurnMeaning, defaulting to three only when the
  semantic result has no batch-size hint

fit:
  exactly one selected product
```

Do not infer `fit` from product rank, and do not add a new raw-message regex
to `requested_recommendation_result_count()`.

Use these section orders:

```text
explore:
  summary -> product... -> closing -> full_cards

fit:
  summary -> product -> closing -> full_cards
```

For `fit`, the closing section has no model-written `copy_text`. It renders
only the structured `WinnerPresentation` beneath one `综合推荐` heading. The
renderer passes an empty label to `createWinnerConclusion()` in that section,
so neither the heading nor the conclusion is duplicated.

- [x] **Step 4: Permit only the formal outcome in the renderer**

In `guide-presentation.js`, validate:

```javascript
if (mode === 'recommendation') {
    const recommendationMode = presentation.recommendation_mode;
    if (!['explore', 'fit'].includes(recommendationMode)) {
        throw new Error('PRESENTATION_RECOMMENDATION_MODE_INVALID');
    }
    if (recommendationMode === 'explore'
        && winner.status !== 'not_applicable') {
        throw new Error('PRESENTATION_WINNER_INVALID');
    }
    if (recommendationMode === 'fit'
        && winner.status !== 'selected') {
        throw new Error('PRESENTATION_WINNER_INVALID');
    }
}
```

Render a single `综合推荐` block only for `fit`. Render no selection block for
`explore`.

- [x] **Step 5: Run focused unit and integration tests**

Run:

```bash
PYTHONPATH=. .venv/bin/pytest -q \
  tests/guide/understanding/test_turn_meaning_contracts.py \
  tests/guide/adapters/test_turn_meaning_prompt.py \
  tests/guide/adapters/test_deepseek_turn_meaning.py \
  tests/guide/adapters/test_siliconflow_turn_meaning.py \
  tests/guide/intent/test_semantic_admission.py \
  tests/guide/intent/test_task_planning.py \
  tests/guide/intent/test_executable_intent_compiler.py \
  tests/guide/presentation/test_public_contracts.py \
  tests/guide/presentation/test_winner_presentation_contract.py \
  tests/guide/application/test_text_presentation_integration.py \
  tests/guide/application/test_image_presentation_integration.py
```

Expected: PASS. The cases must cover: multi-product explore, one-product fit,
and two-product comparison.

- [x] **Step 6: Commit**

```bash
git add \
  app/guide/understanding/turn_meaning_contracts.py \
  app/guide/adapters/llm/turn_meaning_prompt.py \
  app/guide/adapters/llm/turn_meaning_adapter.py \
  app/guide/understanding/single_call_understanding.py \
  app/guide/intent/semantic_admission.py \
  app/guide/intent/contracts.py \
  app/guide/intent/task_planning.py \
  app/guide/intent/executable_intent_compiler.py \
  app/guide/presentation/public_contracts.py \
  app/guide/presentation/copywriter_contracts.py \
  app/guide/presentation/presentation_packet.py \
  app/guide/presentation/presentation_compiler.py \
  app/guide/application/text_recommendation_flow.py \
  app/guide/application/image_recommendation_flow.py \
  app/static/guide-presentation.js \
  tests/guide/understanding/test_turn_meaning_contracts.py \
  tests/guide/adapters/test_turn_meaning_prompt.py \
  tests/guide/adapters/test_deepseek_turn_meaning.py \
  tests/guide/adapters/test_siliconflow_turn_meaning.py \
  tests/guide/intent/test_semantic_admission.py \
  tests/guide/intent/test_task_planning.py \
  tests/guide/intent/test_executable_intent_compiler.py \
  tests/guide/presentation/test_public_contracts.py \
  tests/guide/presentation/test_winner_presentation_contract.py \
  tests/guide/application/test_text_presentation_integration.py \
  tests/guide/application/test_image_presentation_integration.py
git commit -m "feat(guide): distinguish explore and fit recommendations"
```

### ~~Task 3: Make Guide presentation contract ownership fail closed~~ (completed)

**Files:**
- Create: `app/guide/presentation/terminal_contract_guard.py`
- Modify: `app/guide/application/unified_guide_flow.py`
- Modify: `app/guide/application/text_recommendation_flow.py`
- Modify: `app/guide/application/image_recommendation_flow.py`
- Modify: `app/guide/application/consultation_chat_flow.py`
- Modify: `app/guide/application/chat_api_adapter.py`
- Create: `app/guide/application/conversation_state_reducer.py`
- Modify: `app/static/chat.html`
- Create: `tests/guide/presentation/test_terminal_contract_guard.py`
- Test: `tests/guide/runtime/test_frontend_presentation_stream.py`
- Test: `tests/guide/runtime/test_frontend_presentation_reducer.py`
- Test: `tests/guide/application/test_chat_presentation_adapter.py`
- Modify: `tools/guide_gates/run_real_continuous_conversation_browser_audit.py`
- Test: `tests/guide/tools/test_run_real_continuous_conversation_browser_audit.py`

- [x] **Step 1: Add failing server-side event-sequence tests**

```python
def test_terminal_guard_rejects_guide_end_without_presentation() -> None:
    guard = GuideTerminalContractGuard()

    guard.observe(IntentEvent(data=IntentData(mode="recommend")))
    with pytest.raises(GuideTerminalContractError, match="missing contract"):
        guard.observe(EndEvent(data=EndData(conversation_version=1)))


def test_terminal_guard_rejects_guide_message_event() -> None:
    guard = GuideTerminalContractGuard()

    with pytest.raises(GuideTerminalContractError, match="MessageEvent"):
        guard.observe(MessageEvent(data=MessageData(content="legacy copy")))


def test_clarification_uses_typed_clarify_event_without_message() -> None:
    guard = GuideTerminalContractGuard()

    guard.observe(
        ClarifyEvent(
            data=ClarifyData(
                question="请明确要比较哪两款。",
                clarification_code=ClarificationCode.REFERENCE,
            )
        )
    )
    guard.observe(EndEvent(data=EndData(conversation_version=1)))
    guard.finish()
```

- [x] **Step 2: Add failing browser reducer tests**

```python
def test_guide_terminal_without_contract_never_calls_legacy_renderers() -> None:
    result = run_stream_reducer(
        events=[
            ["intent", {"intent": "recommend", "guide": True}],
            ["products", {"cards": [_product_card_payload()]}],
            ["end", {"conversation_version": 1}],
        ]
    )

    assert result["error"] == "GUIDE_RESPONSE_CONTRACT_INVALID"
    assert result["legacy_display_products_calls"] == 0
    assert result["visible_answer_count"] == 0
```

- [x] **Step 3: Implement a progressive terminal guard**

Create these types in `terminal_contract_guard.py`:

```python
class GuideTerminalContractError(RuntimeError):
    pass


class GuideTerminalContractGuard:
    def __init__(self) -> None:
        self._presentation_count = 0
        self._terminal_kind: Literal["guide", "clarification", None] = None
        self._ended = False

    def observe(self, event: SseEvent) -> None:
        self._observe_event(event)

    def finish(self) -> None:
        if not self._ended:
            raise GuideTerminalContractError("stream ended before EndEvent")
```

`GuideTerminalContractGuard` applies these exact per-turn rules:

```text
Guide terminal turn:
  exactly one PresentationContractEvent before EndEvent
  zero MessageEvent
  ProductsEvent and CardDisplayContractEvent may exist only to bind the
  contract's visible_product_ids
  typed evidence, image observation, consultation observation, pitfalls, and
  citation events may remain for audit/telemetry, but are never public render
  owners and must occur before PresentationContractEvent

Clarification terminal turn:
  exactly one ClarifyEvent or ErrorEvent
  zero PresentationContractEvent
```

Wrap the generator returned by `UnifiedGuideFlow` with:

```python
for event in guide_events:
    guard.observe(event)
    yield event
guard.finish()
```

Delete Guide-mode compatibility `MessageEvent` emissions from text,
image, consultation, and general-knowledge flows. Preserve the existing
non-Guide API behavior outside `UnifiedGuideFlow`.
Do not delete typed evidence events merely to hide frontend duplication; the
frontend owner rule below is responsible for preventing them from rendering.
Migrate every current Guide clarification branch that emits
`MessageEvent(clarify=True)` to `ClarifyEvent(ClarifyData(...))`. The frontend
renders `ClarifyEvent` as the sole clarification body. `ErrorEvent` remains the
sole error body. Neither path may create a presentation contract or invoke a
legacy typewriter.

In `chat_api_adapter.py`, make `collect_guide_chat_response()` reject a Guide
`MessageEvent` rather than accepting it after the presentation contract. Its
public `response["message"]` is the deterministic concatenation of visible
contract section copy, in section order; it is not a second source of user
text. Update the existing browser audit's `_event_evidence()` and
`_assert_turn()` to require one presentation contract and zero `message`
events, replacing its current `assert event["message"]` condition.

- [x] **Step 4: Remove the frontend legacy fallback in Guide mode**

In `flushDeferredPanels()` in `app/static/chat.html`, replace the ownership
test with:

```javascript
if (GUIDE_RUNTIME_MODE && !deferredPanels.presentationContract) {
    throw new Error('GUIDE_RESPONSE_CONTRACT_INVALID');
}
const guideOwnsPresentation = GUIDE_RUNTIME_MODE;
```

When `GUIDE_RUNTIME_MODE` is true:

```text
never call displayProducts
never call displayImageObservation
never call displayImageSuitability
never call flushLegacyEvidencePanels
never typewrite MessageEvent content
```

`renderPresentation()` and `saveProductsToShelf()` remain the only visible
Guide rendering path.

- [x] **Step 5: Run focused tests**

Run:

```bash
PYTHONPATH=. .venv/bin/pytest -q \
  tests/guide/presentation/test_terminal_contract_guard.py \
  tests/guide/runtime/test_frontend_presentation_stream.py \
  tests/guide/runtime/test_frontend_presentation_reducer.py \
  tests/guide/runtime/test_presentation_runtime_http.py \
  tests/guide/application/test_chat_presentation_adapter.py \
  tests/guide/tools/test_run_real_continuous_conversation_browser_audit.py
```

Expected: PASS. Add a DOM assertion that a Guide turn has one answer root,
one shelf root, and no legacy product or evidence panels.

- [x] **Step 6: Commit**

```bash
git add app/guide/presentation/terminal_contract_guard.py \
  app/guide/application/unified_guide_flow.py \
  app/guide/application/text_recommendation_flow.py \
  app/guide/application/image_recommendation_flow.py \
  app/guide/application/consultation_chat_flow.py \
  app/guide/application/chat_api_adapter.py \
  app/static/chat.html \
  tools/guide_gates/run_real_continuous_conversation_browser_audit.py \
  tests/guide/presentation/test_terminal_contract_guard.py \
  tests/guide/runtime/test_frontend_presentation_stream.py \
  tests/guide/runtime/test_frontend_presentation_reducer.py \
  tests/guide/application/test_chat_presentation_adapter.py \
  tests/guide/tools/test_run_real_continuous_conversation_browser_audit.py
git commit -m "fix(guide): fail closed on missing presentation contracts"
```

### ~~Task 4: Close the price, specification, and product-name binding gate~~ (completed)

**Files:**
- Modify: `app/guide/presentation/contracts.py`
- Modify: `app/guide/presentation/response_planning.py`
- Modify: `app/guide/presentation/presentation_packet.py`
- Modify: `app/guide/application/chat_api_adapter.py`
- Modify: `app/static/chat.html`
- Test: `tests/guide/presentation/test_response_planning.py`
- Test: `tests/guide/presentation/test_presentation_packet.py`
- Test: `tests/guide/runtime/test_frontend_card_binding.py`
- Test: `tests/guide/application/test_chat_presentation_adapter.py`

- [x] **Step 1: Write failing three-layer alignment tests**

```python
@pytest.mark.parametrize("alignment", ["unresolved", "conflict"])
def test_public_card_removes_unbound_specification(alignment: str) -> None:
    card = build_product_card(
        _facts(
            price_specification_alignment=alignment,
            specification="50ml",
            price=Decimal("968"),
        ),
        skin_match="unknown",
    )

    assert card.specification is None
    assert card.price_specification_alignment == alignment


def test_frontend_formatter_requires_explicit_aligned_binding() -> None:
    html = Path("app/static/chat.html").read_text(encoding="utf-8")
    start = html.index("function formatProductPrice(product")
    end = html.index("\n        function formatProductPriceMeta", start)
    formatter = html[start:end]

    assert "price_specification_alignment === 'aligned'" in formatter
    assert " && typeof product?.specification === 'string'" in formatter
```

- [x] **Step 2: Run the price/spec tests**

Run:

```bash
PYTHONPATH=. .venv/bin/pytest -q \
  tests/guide/presentation/test_response_planning.py \
  tests/guide/presentation/test_presentation_packet.py \
  tests/guide/runtime/test_frontend_card_binding.py \
  tests/guide/application/test_chat_presentation_adapter.py \
  -k 'specification or alignment or price'
```

Expected: FAIL because `ProductCard` keeps unbound specification, the API
omits alignment, and frontend formatting joins any nonempty specification.

- [x] **Step 3: Make public `ProductCard` fail closed**

Keep raw `ProductCardFacts.specification` for internal audit, but normalize the
public card in `build_product_card()`:

```python
public_specification = (
    facts.specification
    if facts.price_specification_alignment == "aligned"
    else None
)
```

Add a `ProductCard` model validator:

```python
if (
    self.price_specification_alignment != "aligned"
    and self.specification is not None
):
    raise ValueError("unbound public card forbids specification")
```

In `_locked_facts()`, use `card.specification` only after checking:

```python
card.price_specification_alignment == "aligned"
```

so no locked reference-price sentence can leak an unbound specification.

- [x] **Step 4: Preserve alignment through SSE and frontend formatting**

Add this key in `_card_to_frontend_product()`:

```python
"price_specification_alignment": card[
    "price_specification_alignment"
],
```

Use this condition in `formatProductPrice()`:

```javascript
const hasAlignedSpecification = (
    product?.price_specification_alignment === 'aligned'
    && typeof product?.specification === 'string'
    && product.specification.trim()
);
```

Append ` / specification` only when `hasAlignedSpecification` is true.
`publicProductName()` must continue using `display_name || name`; it must
never use `specification` to build a title.

In `ProductCard.validate_category_facts()`, reject a public
`display_name`/`name` that contains its exact public `specification` token.
That rejects a product data binding which has already mixed title and SKU;
the repair belongs in the canonical display binding, not in browser string
replacement. Add a test where `display_name="修护精华 50ml"` and
`specification="50ml"` raises `ValueError("public product title contains specification")`.

- [x] **Step 5: Run the focused gate**

Run:

```bash
PYTHONPATH=. .venv/bin/pytest -q \
  tests/guide/presentation/test_response_planning.py \
  tests/guide/presentation/test_presentation_packet.py \
  tests/guide/runtime/test_frontend_card_binding.py \
  tests/guide/application/test_chat_presentation_adapter.py
```

Expected: PASS, including aligned `¥968 / 50ml`, unresolved `¥968`, and a
product name that never contains `50ml`.

- [x] **Step 6: Commit**

```bash
git add app/guide/presentation/contracts.py \
  app/guide/presentation/response_planning.py \
  app/guide/presentation/presentation_packet.py \
  app/guide/application/chat_api_adapter.py app/static/chat.html \
  tests/guide/presentation/test_response_planning.py \
  tests/guide/presentation/test_presentation_packet.py \
  tests/guide/runtime/test_frontend_card_binding.py \
  tests/guide/application/test_chat_presentation_adapter.py
git commit -m "fix(guide): enforce public price specification alignment"
```

### ~~Task 5: Build the shared public fact projection and detail-field selector~~ (completed)

**Files:**
- Create: `app/guide/presentation/public_fact_contracts.py`
- Create: `app/guide/presentation/public_fact_projection.py`
- Create: `app/guide/presentation/product_detail_selection.py`
- Modify: `app/guide/presentation/contracts.py`
- Modify: `app/guide/presentation/presentation_packet.py`
- Modify: `app/guide/presentation/presentation_compiler.py`
- Modify: `app/guide/presentation/copywriter_contracts.py`
- Modify: `app/guide/presentation/public_contracts.py`
- Create: `tests/guide/presentation/test_public_fact_projection.py`
- Create: `tests/guide/presentation/test_product_detail_selection.py`
- Test: `tests/guide/presentation/test_presentation_packet.py`

- [x] **Step 1: Write the failing A-cabinet + B-cabinet projection tests**

```python
def test_projection_merges_category_and_product_evidence() -> None:
    projection = project_public_facts(
        card=_serum_card(
            texture="轻盈凝露",
            ingredients_present=("海茴香精粹", "植物抗老多肽"),
        ),
        approved_soft_facts=(
            _brand_main("轻盈修护抗老"),
            _faq_fact("多肤质可用、偏油皮友好"),
        ),
        requested_dimensions=("texture",),
    )

    assert [fact.field_key for fact in projection.facts] == [
        "brand_main",
        "texture",
        "ingredients_present",
        "suitable_skin",
    ]
    assert all(fact.fact_id for fact in projection.facts)
    assert all(fact.source_refs for fact in projection.facts)


def test_detail_selector_uses_product_facts_not_product_id() -> None:
    selected = select_product_detail_facts(
        projection=_serum_projection(),
        responsibility=Responsibility.RECOMMENDATION,
        requested_dimensions=("texture",),
    )

    assert [item.field_key for item in selected] == [
        "brand_main",
        "texture",
        "ingredients_present",
    ]
```

- [x] **Step 2: Run the tests to prove the two cabinets are still separate**

Run:

```bash
PYTHONPATH=. .venv/bin/pytest -q \
  tests/guide/presentation/test_public_fact_projection.py \
  tests/guide/presentation/test_product_detail_selection.py \
  tests/guide/presentation/test_presentation_packet.py
```

Expected: FAIL because no projection or selector exists.

- [x] **Step 3: Define source-backed projection types**

Define the frozen data-only contracts in
`public_fact_contracts.py`. That module imports no Copywriter, projector, or
compiler type:

```python
class _StrictFrozen(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )


class ProjectedPublicFact(_StrictFrozen):
    fact_id: str
    product_id: int
    field_key: str
    label: str
    display_value: str
    source_refs: tuple[str, ...]
    source_kind: Literal["category", "evidence", "merchant", "review"]
    attribution: Literal[
        "verified_fact",
        "merchant_claim",
        "consumer_report",
    ]


class ProductPublicFactProjection(_StrictFrozen):
    product_id: int
    facts: tuple[ProjectedPublicFact, ...]
```

`public_fact_projection.py` imports those data contracts plus
`ApprovedSoftFact` and defines `project_public_facts()`. It accepts:

```python
def project_public_facts(
    *,
    card: ProductCard,
    approved_soft_facts: Sequence[ApprovedSoftFact],
    requested_dimensions: Collection[str],
) -> ProductPublicFactProjection:
```

It must:

```text
include known public ProductCard category facts (A cabinet)
include approved soft facts after product evidence, merchant claims, reviews,
selection facts, and concepts have already been merged (B cabinet)
prefer brand_main when an approved merchant-attributed fact exists
include requested dimensions first
preserve source_refs and deterministic fact IDs
never include unavailable/conflict facts
never create facts from raw exact_text or OCR text
deduplicate by (product_id, field_key, normalized display value)
```

Preserve existing approved fact IDs. New category projection IDs use:

```text
category:<product_id>:<field_key>
```

- [x] **Step 4: Define the selector used by every product detail block**

In `product_detail_selection.py`, define:

```python
def select_product_detail_facts(
    *,
    projection: ProductPublicFactProjection,
    responsibility: Responsibility,
    requested_dimensions: Collection[str],
) -> tuple[ProjectedPublicFact, ...]:
```

Apply these exact limits:

```text
recommendation:
  brand_main when available
  + one or two highest-priority requested/category facts
  maximum three facts total

product_knowledge:
  requested fact
  + up to two directly supporting facts
  maximum three facts total

image_identity:
  brand_main when available
  + two identity-safe category facts
  maximum three facts total

comparison:
  no product-detail facts in the comparison body;
  comparison_rows own the data
```

Selection priority after an explicit requested dimension:

```text
brand_main -> ingredients_present -> texture -> efficacy -> usage ->
suitable_skin -> category-specific profile fields
```

The selector must not inspect product IDs or Chinese copy text.

Add the selected facts to the existing copy packet, not to an untyped
side-channel:

```python
class CopySlot(_StrictFrozen):
    # Existing fields remain unchanged.
    detail_facts: tuple[ProjectedPublicFact, ...] = Field(
        default_factory=tuple,
        max_length=3,
    )
```

`copywriter_contracts.py` imports `ProjectedPublicFact` only from the neutral
`public_fact_contracts.py`, so `public_fact_projection.py` may safely import
`ApprovedSoftFact` without a cycle. `CopySlot.validate_fact_ownership()` must
require every `detail_facts` item to
belong to the slot product and require every `detail_facts.fact_id` to be a
subset of that slot's `approved_soft_facts.fact_id`. Convert every selected
projection fact into an `ApprovedSoftFact` before constructing the slot, so
the existing Copywriter and compact-Tag validators keep one canonical fact-ID
universe. `projected_fact_to_soft_fact()` preserves the projection's exact
`attribution`; it must not infer attribution from display text or ID prefixes.

- [x] **Step 5: Feed selected detail facts into the presentation compiler**

In `build_presentation_packet()`, first build the existing slots and merge
`additional_soft_facts`. Then, for each `(card, slot)` pair:

```python
projection = project_public_facts(
    card=card,
    approved_soft_facts=slot.approved_soft_facts,
    requested_dimensions=requested_dimensions,
)
projected_soft_facts = tuple(
    projected_fact_to_soft_fact(item)
    for item in projection.facts
    if item.fact_id not in {
        fact.fact_id for fact in slot.approved_soft_facts
    }
)
slot = slot.model_copy(update={
    "approved_soft_facts": (
        *slot.approved_soft_facts,
        *projected_soft_facts,
    ),
    "detail_facts": select_product_detail_facts(
        projection=projection,
        responsibility=responsibility,
        requested_dimensions=requested_dimensions,
    ),
})
```

This ordering guarantees product-knowledge evidence added by Task 6 participates
in the same projection. Replace the current
unconditional `slot.locked_facts` expansion in `_compile_sections()` with
the selected `slot.detail_facts`:

```python
direct_facts=tuple(
    DirectFactComponent(
        fact_id=fact.fact_id,
        label=fact.label,
        display_value=fact.display_value,
    )
        for fact in slot.detail_facts
)
```

Keep price/specification out of recommendation body prose. Price/spec remains
in the inline card and shelf only.

For an image-identity contract with one confirmed product, make the typed
layout exactly:

```text
observation -> product(p1) -> full_cards
```

Modify `PresentationPacket.validate_slots_and_sections()`,
`_section_order()`, and `PublicPresentationContract._validate_layout()` to
allow this one inline product only for `Responsibility.IMAGE_IDENTITY`.
`image_identity` still forbids a Winner. This formalizes the already-supported
renderer surface; it does not reuse the shelf card as an inline card.

- [x] **Step 6: Run focused projection tests**

Run:

```bash
PYTHONPATH=. .venv/bin/pytest -q \
  tests/guide/presentation/test_public_fact_projection.py \
  tests/guide/presentation/test_product_detail_selection.py \
  tests/guide/presentation/test_presentation_packet.py \
  tests/guide/presentation/test_copy_evidence_validation.py
```

Expected: PASS. Add test cases for serum, sunscreen, and cream to prove the
field list changes by category facts rather than by a hard-coded card template.

- [x] **Step 7: Commit**

```bash
git add app/guide/presentation/public_fact_projection.py \
  app/guide/presentation/public_fact_contracts.py \
  app/guide/presentation/product_detail_selection.py \
  app/guide/presentation/contracts.py \
  app/guide/presentation/presentation_packet.py \
  app/guide/presentation/presentation_compiler.py \
  app/guide/presentation/copywriter_contracts.py \
  app/guide/presentation/public_contracts.py \
  tests/guide/presentation/test_public_fact_projection.py \
  tests/guide/presentation/test_product_detail_selection.py \
  tests/guide/presentation/test_presentation_packet.py \
  tests/guide/presentation/test_copy_evidence_validation.py
git commit -m "feat(guide): project public product facts once"
```

### ~~Task 6: Replace product-knowledge A-or-B lookup with the shared projection~~ (completed)

**Files:**
- Modify: `app/guide/application/product_evidence_answer.py`
- Modify: `app/guide/application/text_recommendation_flow.py`
- Modify: `app/guide/presentation/presentation_compiler.py`
- Test: `tests/guide/application/test_product_evidence_answer.py`
- Test: `tests/guide/application/test_text_presentation_integration.py`
- Test: `tests/guide/runtime/test_product_evidence_real_matrix.py`

- [x] **Step 1: Write failing behavior tests**

```python
def test_texture_question_uses_category_facts_when_evidence_lacks_texture(
    orchestrator: TextRecommendationOrchestrator,
) -> None:
    events = list(
        orchestrator.stream(
            _turn("第二款的质地适合什么肤质？"),
            snapshot=_recommendation_snapshot(visible_ids=(33, 39, 35)),
        )
    )

    contract = _presentation(events)
    answer = _section(contract, "answer")

    assert "轻盈凝露" in answer.copy_text
    assert "海茴香精粹" in answer.copy_text
    assert "暂时没有与这个问题直接相关" not in answer.copy_text


def test_product_knowledge_fact_ids_include_category_and_evidence_sources() -> None:
    contract = _product_knowledge_contract()

    answer = _section(contract, "answer")
    assert any(fact_id.startswith("category:39:texture") for fact_id in answer.used_fact_ids)
    assert any(fact_id.startswith("evidence:") for fact_id in answer.used_fact_ids)
```

- [x] **Step 2: Run the product-knowledge tests**

Run:

```bash
PYTHONPATH=. .venv/bin/pytest -q \
  tests/guide/application/test_product_evidence_answer.py \
  tests/guide/application/test_text_presentation_integration.py \
  tests/guide/runtime/test_product_evidence_real_matrix.py \
  -k 'knowledge or texture or evidence'
```

Expected: FAIL because `_stream_product_evidence_task()` currently chooses
`render_product_evidence_answer()` *or*
`render_catalog_product_facts_answer()`.

- [x] **Step 3: Replace the binary renderer with a projection answer plan**

Delete the current branch that picks either product evidence or catalog facts.
Define this return type in `product_evidence_answer.py`:

```python
class ProductKnowledgeAnswerPlan(_StrictFrozenModel):
    answer_text: str
    direct_facts: tuple[ProjectedPublicFact, ...]
    used_fact_ids: tuple[str, ...]


def build_product_knowledge_answer_plan(
    *,
    projection: ProductPublicFactProjection,
    question: str,
) -> ProductKnowledgeAnswerPlan:
    selected = select_product_detail_facts(
        projection=projection,
        responsibility=Responsibility.PRODUCT_KNOWLEDGE,
        requested_dimensions=resolve_product_knowledge_dimensions(question),
    )
    return ProductKnowledgeAnswerPlan(
        answer_text=render_product_knowledge_text(selected),
        direct_facts=selected,
        used_fact_ids=tuple(item.fact_id for item in selected),
    )
```

For one selected product:

```python
knowledge_source_facts = (
    *_approved_product_evidence_facts(packet),
    *_approved_merchant_claim_facts(merchant_claims),
    *_approved_review_summary_facts(review_summaries),
)
projection = project_public_facts(
    card=cards[0],
    approved_soft_facts=knowledge_source_facts,
    requested_dimensions=resolve_product_knowledge_dimensions(
        task.question_meaning or turn.message
    ),
)
answer_plan = build_product_knowledge_answer_plan(
    projection=projection,
    question=turn.message,
)
```

`build_product_knowledge_answer_plan()` must return:

```text
answer text built from selected projected facts
selected projected facts for authoritative copy and fact-ID validation
all used fact IDs
```

When no relevant approved fact exists, use the public label resolved from the
requested dimension and say only:

```text
“这款目前没有明确标注的<public label>信息。”
```

For example: `这款目前没有明确标注的质地信息。` It must not say “资料不足”,
“可公开确认”, “当前卡片记录”, “页面”, “证据”, “系统”, or “不知道”.

- [x] **Step 4: Make authoritative copy cite projection IDs**

Build:

```python
authoritative_public_copy = SourceTaggedCopy(
    text=answer_plan.answer_text,
    used_fact_ids=answer_plan.used_fact_ids,
)
```

Do not set `used_fact_ids` to only long-evidence IDs. The compiler must
receive `knowledge_source_facts` as `additional_soft_facts`, while
`SourceTaggedCopy.used_fact_ids` names only the selected answer-plan facts:

```python
additional_soft_facts=knowledge_source_facts
merchant_claims=()
review_summaries=()
```

For this product-knowledge call, pass empty raw merchant/review sequences so
`build_presentation_packet()` does not generate duplicate IDs from the same
sources. Task 5 projects category facts after merging these additional facts,
so the compiler and answer plan see the same A+B fact set.

`PublicPresentationContract` keeps the product-knowledge layout as
`summary -> answer -> full_cards`; it must not attach `direct_facts` to the
`answer` section because that section type deliberately forbids a second
inline card. The answer prose, its selected projection IDs, and the shelf
therefore refer to the same fact universe without creating a duplicate surface.

- [x] **Step 5: Run focused tests**

Run:

```bash
PYTHONPATH=. .venv/bin/pytest -q \
  tests/guide/application/test_product_evidence_answer.py \
  tests/guide/application/test_text_presentation_integration.py \
  tests/guide/runtime/test_product_evidence_real_matrix.py \
  tests/guide/presentation/test_copy_evidence_validation.py
```

Expected: PASS. Cover texture, ingredients, usage, and an honest
no-public-fact result.

- [x] **Step 6: Commit**

```bash
git add app/guide/application/product_evidence_answer.py \
  app/guide/application/text_recommendation_flow.py \
  app/guide/presentation/presentation_compiler.py \
  tests/guide/application/test_product_evidence_answer.py \
  tests/guide/application/test_text_presentation_integration.py \
  tests/guide/runtime/test_product_evidence_real_matrix.py \
  tests/guide/presentation/test_copy_evidence_validation.py
git commit -m "fix(guide): project product knowledge across fact sources"
```

### ~~Task 7: Make comparison rows follow the current user question~~ (completed)

**Files:**
- Modify: `app/guide/intent/contracts.py`
- Modify: `app/guide/intent/task_planning.py`
- Modify: `app/guide/presentation/presentation_packet.py`
- Modify: `app/guide/presentation/comparison_planning.py`
- Modify: `app/guide/presentation/public_contracts.py`
- Test: `tests/guide/intent/test_task_planning.py`
- Test: `tests/guide/presentation/test_comparison_planning.py`
- Test: `tests/guide/presentation/test_presentation_compiler.py`
- Test: `tests/guide/application/test_text_presentation_integration.py`

- [x] **Step 1: Write failing row-policy tests**

```python
def test_comparison_without_price_question_omits_reference_price() -> None:
    rows = plan_comparison_rows(
        requested_dimensions=("texture.refreshing",),
        slots=(_slot("p1", 38), _slot("p2", 42)),
    )

    assert [row.dimension_id for row in rows] == [
        "brand_main",
        "texture.refreshing",
        "profile_match",
    ]


def test_comparison_with_current_budget_question_includes_price() -> None:
    rows = plan_comparison_rows(
        requested_dimensions=("reference_price",),
        slots=(_slot("p1", 38), _slot("p2", 42)),
    )

    assert [row.dimension_id for row in rows] == [
        "brand_main",
        "reference_price",
        "profile_match",
    ]
```

- [x] **Step 2: Run the focused comparison tests**

Run:

```bash
PYTHONPATH=. .venv/bin/pytest -q \
  tests/guide/intent/test_task_planning.py \
  tests/guide/presentation/test_comparison_planning.py \
  tests/guide/presentation/test_presentation_compiler.py \
  -k 'comparison or price or profile_match or brand_main'
```

Expected: FAIL because `plan_comparison_rows()` currently always appends
`reference_price`, has no profile-match row, and derives brand focus from an
arbitrary compact Tag.

- [x] **Step 3: Add current-turn comparison dimension authority**

Add to `TaskPlan`:

```python
requested_comparison_dimensions: tuple[str, ...] = ()
```

Populate it only from admitted atoms in the current turn:

```text
current budget candidate or relative price request -> reference_price
texture concept/facet                           -> texture or texture.<concept>
efficacy concept/facet                          -> efficacy or efficacy.<concept>
scene/daytime concept                           -> the controlled scene dimension
other reviewed concept                          -> its controlled concept ID
```

Inherited budget constraints must not create a price row by themselves.
No raw Chinese phrase, regex, product ID, or database field inventory may add
a row. Thread this tuple through the comparison flow into
`build_presentation_packet(requested_dimensions=...)`; do not reconstruct it
inside the presentation layer.

- [x] **Step 4: Build only the owned rows**

`plan_comparison_rows()` uses this exact order:

```text
brand_main
current-turn requested dimensions in admitted order
profile_match
```

`reference_price` appears only when it is in `requested_dimensions`.
`brand_main` reads only a projected `brand_main` fact; it must not fall back
to the first compact Tag. `profile_match` reads typed
`ComparisonDimensionEvidence(dimension_id="profile_match")` built from the
candidate evaluation plus its supporting approved suitable-skin/need facts.
If a product has no approved support, its cell is `unknown`; do not emit
“暂无明确描述” as the whole-row conclusion.

Winner evidence may use only known cells from these visible rows. The
`综合判断` remains `WinnerPresentation` after the table and is not duplicated
as a comparison row.

- [x] **Step 5: Run comparison integration tests**

Run:

```bash
PYTHONPATH=. .venv/bin/pytest -q \
  tests/guide/intent/test_task_planning.py \
  tests/guide/presentation/test_comparison_planning.py \
  tests/guide/presentation/test_presentation_compiler.py \
  tests/guide/application/test_text_presentation_integration.py
```

Expected: PASS for texture-only, budget/price, profile-driven, and
brand-main-missing cases.

- [x] **Step 6: Commit**

```bash
git add \
  app/guide/intent/contracts.py \
  app/guide/intent/task_planning.py \
  app/guide/presentation/presentation_packet.py \
  app/guide/presentation/comparison_planning.py \
  app/guide/presentation/public_contracts.py \
  tests/guide/intent/test_task_planning.py \
  tests/guide/presentation/test_comparison_planning.py \
  tests/guide/presentation/test_presentation_compiler.py \
  tests/guide/application/test_text_presentation_integration.py
git commit -m "fix(guide): scope comparison rows to current question"
```

### ~~Task 8: Make image identity and image recommendation evidence-driven~~ (completed)

**Files:**
- Create: `tools/guide_gates/trace_image_identity_pipeline.py`
- Create: `tests/guide/tools/test_trace_image_identity_pipeline.py`
- Create: `tests/fixtures/guide/images/product-38-index-control.png`
- Create: `tests/fixtures/guide/images/product-38-original.png`
- Create: `tests/fixtures/guide/images/product-38-low-resolution.jpg`
- Create: `tests/fixtures/guide/images/product-38-trace-manifest.json`
- Modify: `app/guide/adapters/image/ocr_observation.py`
- Modify: `app/guide/understanding/ports.py`
- Modify: `app/guide/understanding/image_contracts.py`
- Modify: `app/guide/understanding/image_identity.py`
- Modify: `app/guide/application/image_recommendation_flow.py`
- Modify: `app/guide/presentation/presentation_compiler.py`
- Test: `tests/guide/understanding/test_image_identity_observation.py`
- Create: `tests/guide/adapters/image/test_ocr_observation.py`
- Test: `tests/guide/application/test_image_recommendation_flow.py`
- Test: `tests/guide/application/test_image_presentation_integration.py`
- Test: `tests/guide/retrieval/test_image_retrieval_contracts.py`

- [x] **Step 1: Add a deterministic image trace test**

```python
def test_trace_records_every_identity_stage(
    tmp_path: Path,
    trace_image_bundles: ImageBundleService,
    trace_runtime: ImageRecommendationOrchestrator,
) -> None:
    result = trace_image_identity_pipeline(
        image_path=Path(
            "tests/fixtures/guide/images/product-38-index-control.png"
        ),
        output_path=tmp_path / "trace.json",
        image_bundles=trace_image_bundles,
        runtime=trace_runtime,
    )

    assert result["input"]["sha256"]
    assert result["validated_input"]["width"] > 0
    assert result["visual"]["preprocessing_version"]
    assert "ocr_diagnostic" in result
    assert result["visual_candidates"][0]["product_id"] == 38
    assert result["identity"]["confirmed_product_id"] == 38
```

Add a second test for:

```text
tests/fixtures/guide/images/product-38-low-resolution.jpg
```

It may be rejected, but its trace must record the exact earliest failure layer
and must not pretend to identify product 38. Define `trace_image_bundles` in
the test file with `InMemoryImageBundleState` and define `trace_runtime` with
`build_image_recommendation_runtime(repo_root=ROOT, image_bundle_service=trace_image_bundles)`;
the test uses no LLM or network call.

- [x] **Step 2: Run the trace and image-flow tests**

Run:

```bash
PYTHONPATH=. .venv/bin/pytest -q \
  tests/guide/understanding/test_image_identity_observation.py \
  tests/guide/application/test_image_recommendation_flow.py \
  tests/guide/application/test_image_presentation_integration.py \
  tests/guide/retrieval/test_image_retrieval_contracts.py \
  tests/guide/tools/test_trace_image_identity_pipeline.py
```

Expected: FAIL because no end-to-end trace artifact exists.

- [x] **Step 3: Implement the trace through the actual observer ports before changing thresholds**

Add private diagnostic contracts to `image_contracts.py`. They are never
members of `ImageIdentityObservation` and are never serialized to public SSE:

```python
class OcrTraceLine(_StrictFrozenContract):
    text: str
    confidence: float


class OcrIdentityTrace(_StrictFrozenContract):
    engine: str
    engine_version: str | None = None
    minimum_evidence_confidence: float
    lines: tuple[OcrTraceLine, ...] = ()
    evidence_line_count: int


class ImageIdentityTrace(_StrictFrozenContract):
    visual: VisualCandidateObservation
    ocr_observation: OcrIdentityObservation
    ocr_diagnostic: OcrIdentityTrace
    observation: ImageIdentityObservation
    minimum_similarity: float
    minimum_margin: float
```

Extend `OcrObservationPort` and both OCR adapters with:

```python
def observe_with_trace(
    self,
    request: ImageRetrievalRequest,
    canonical_identity: CanonicalIdentity,
) -> tuple[OcrIdentityObservation, OcrIdentityTrace]:
```

`RapidOcrObservationAdapter.observe_with_trace()` invokes RapidOCR exactly
once, preserves every parsed `(text, confidence)` line in the private trace,
and derives the public consistency observation from those same lines.
`observe()` returns only the first tuple item. The not-configured adapter
returns an empty diagnostic trace.

Then add to `ImageIdentityObserver`:

```python
def observe(
    self,
    request: ImageRetrievalRequest,
) -> ImageIdentityObservation:
    observation, _ = self._observe_once(request)
    return observation


def observe_with_trace(
    self,
    request: ImageRetrievalRequest,
) -> tuple[ImageIdentityObservation, ImageIdentityTrace]:
    return self._observe_once(request)
```

Rename the current `observe()` body to
`_observe_once(request) -> tuple[ImageIdentityObservation, ImageIdentityTrace]`.
It calls the visual port once and, when OCR is reached, calls
`ocr_observation.observe_with_trace()` once. Every existing early return must
return the observation plus a trace built from that same visual result,
OCR result, and binding policy. No mutable `_last_trace` field is allowed.

```python
class ImageIdentityObserver:
    def _observe_once(
        self,
        request: ImageRetrievalRequest,
    ) -> tuple[ImageIdentityObservation, ImageIdentityTrace]:
        visual = self._visual_observation.observe(request)
        if visual.state is VisualObservationState.UNAVAILABLE:
            observation = _unavailable_observation(request.image_id)
            return observation, ImageIdentityTrace(
                visual=visual,
                ocr_observation=_not_run_ocr_observation(),
                ocr_diagnostic=_not_run_ocr_trace(),
                observation=observation,
                minimum_similarity=self._policy.minimum_similarity,
                minimum_margin=self._policy.minimum_margin,
            )
        # Continue through the existing typed decision branches.
```

The remaining existing branches use the same `return observation, trace`
shape and preserve all current thresholds. Update
`ImageIdentityObserverPort` with this method and add
`ImageRecommendationOrchestrator.trace_identity_request()` as its public
delegation point.

The CLI tool first submits `image_path` through the production
`ImageBundleService.create()` and then reads its authorized payload through
`authorize_bundle_payloads()`. The submitted file hash, validated bundle
dimensions, stored payload hash, and stored payload bytes are all written to
the trace before it invokes the observer. This proves whether failure occurred
before or after upload validation. The tool builds the production-equivalent
image runtime through `build_image_recommendation_runtime()` and writes the
observer trace plus image dimensions and hashes. Its only callable API is:

```python
def trace_image_identity_pipeline(
    *,
    image_path: Path,
    output_path: Path,
    image_bundles: ImageBundleService,
    runtime: ImageRecommendationOrchestrator,
) -> dict[str, object]:
    submitted = image_path.read_bytes()
    media_type_by_suffix = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }
    receipt = image_bundles.create(
        session_id="image-trace",
        images=(
            UntrustedImageInput(
                file_name=image_path.name,
                declared_media_type=media_type_by_suffix[
                    image_path.suffix.lower()
                ],
                content=submitted,
            ),
        ),
    )
    bundle, payloads = image_bundles.authorize_bundle_payloads(
        bundle_id=receipt.bundle_id,
        version=receipt.version,
        session_id="image-trace",
        owner_token=receipt.owner_token,
    )
    payload = payloads[0]
    request = ImageRetrievalRequest(
        image_id=payload.image_id,
        content_sha256=payload.content_sha256,
        content=payload.content,
        max_results=10,
    )
    observation, trace = runtime.trace_identity_request(request)
    output = _trace_payload(
        submitted=submitted,
        bundle=bundle,
        payload=payload,
        trace=trace,
        observation=observation,
    )
    output_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output
```

`_trace_payload()` serializes the submitted hash, validated upload metadata,
exact observer return values, private OCR diagnostic, all visual candidate
scores, model/index identity, and computes
`earliest_failure_layer` with this order:

```text
safe-image validation failure             -> input_validation
visual unavailable/no candidate/low score -> visual_retrieval
OCR conflict                              -> ocr
insufficient margin without OCR support   -> fusion
all preceding evidence present, no binding -> identity_contract
confirmed identity                        -> null
```

It must include:

```json
{
  "input": {"sha256": "", "width": 0, "height": 0},
  "validated_input": {
    "sha256": "", "width": 0, "height": 0, "bytes_unchanged": true
  },
  "visual": {
    "model_name": "", "weights_sha256": "",
    "preprocessing_version": "", "index_sha256": ""
  },
  "ocr_diagnostic": {
    "engine": "rapidocr-onnxruntime", "engine_version": "1.3.0",
    "lines": [{"text": "", "confidence": 0.0}],
    "evidence_line_count": 0
  },
  "visual_candidates": [
    {"rank": 1, "product_id": 0, "similarity": 0.0}
  ],
  "fusion": {
    "minimum_similarity": 0.8, "minimum_margin": 0.1,
    "observed_margin": 0.0, "ocr_support": false
  },
  "identity": {"state": "", "confirmed_product_id": null},
  "earliest_failure_layer": null
}
```

The upload service preserves validated bytes; there is no materialized
“normalized image” to hash. OpenCLIP normalization is represented truthfully
by its locked `preprocessing_version`. Do not invent a normalized-image
artifact or candidate source hash. Do not alter identity thresholds until a
trace names one earliest failure layer.

Execution trace on 2026-08-21 proved that the originally selected wiki image
was mislabeled upstream: OCR identifies it as an Effaclar anti-imperfection
serum, not product 38. Do not force that image to pass as product 38. Keep
three immutable fixtures:

```text
positive index control:
  app/static/images/products/jd_v3_100160480140.png
  expected SHA-256:
  7916573dc1cc11239edea3229f145f00ccfc7716f98d81d220197413cef2d98b
  expected identity:
  confirmed product 38

mislabeled external negative:
  data/guide_merchant_claims/smzdm_wiki_v1/source_images/38/
  001_4793bb487b52c153.jpg
  expected SHA-256:
  4793bb487b52c1535d006e9281323ccf2ccc19a87345d167d8f246b66fe3435d
  expected identity:
  low_confidence, top product 94, no confirmed product

verified product-38 domain-shift negative:
  data/guide_merchant_claims/smzdm_crawl_v1/source_images/38/
  smzdm_177005703_main_250.jpg
  expected SHA-256:
  39357629c3bdc39aa8f577bd94c06f1228826dcc2241ee6499b54d9a4dfc5973
  expected identity:
  low_confidence, top product 145, no confirmed product
```

Record each fixture filename, source path, SHA-256, dimensions, expected
identity state, and expected top product in
`product-38-trace-manifest.json`. Do not resize or re-encode any fixture.
The two external failures name `visual_retrieval` as the earliest failure
layer. Do not lower the 0.8 identity threshold and do not add a product-38
branch. A future multi-view index may admit externally reviewed exemplars only
through a generic, source-reviewed index contract.

- [x] **Step 4: Add image candidate and fit rules**

In `_stream_single_image()` and `_image_retrieval_result()` enforce and test:

```text
confirmed source product is excluded from image similarity candidates
every candidate category equals the confirmed image topic
candidate list is deduplicated before decision
fit recommendation uses recommendation_mode="fit" only when usable profile
constraints exist
the source image product returns only when the user asks a comparison
```

The existing `exclude_product_id` call is not sufficient proof; assert the
final `ProductsEvent`, `CardDisplayContractEvent`, and
`PresentationContractEvent` contain the same filtered IDs.

- [x] **Step 5: Compile fit winners through the official contract**

For an image recommendation with `recommendation_mode == "fit"`, pass the
selected decision product and decision fact IDs into the same winner builder
added in Task 2. Delete dependence on `_summary_fragment()` for public
conclusion text. `_summary_fragment()` may remain only for internal logs.

- [x] **Step 6: Run focused image tests**

Run:

```bash
PYTHONPATH=. .venv/bin/pytest -q \
  tests/guide/understanding/test_image_identity_observation.py \
  tests/guide/application/test_image_recommendation_flow.py \
  tests/guide/application/test_image_presentation_integration.py \
  tests/guide/retrieval/test_image_retrieval_contracts.py \
  tests/guide/tools/test_trace_image_identity_pipeline.py
```

Expected: PASS. The positive index control proves product 38 identity; the two
external fixtures remain honest visual-retrieval failures; recommendation
candidates exclude 38 and keep serum category; profile-driven image fit chooses
one candidate; and a later comparison can select product 38.

- [x] **Step 7: Commit**

```bash
git add app/guide/understanding/image_identity.py \
  app/guide/understanding/image_contracts.py \
  app/guide/understanding/ports.py \
  app/guide/adapters/image/ocr_observation.py \
  app/guide/application/image_recommendation_flow.py \
  app/guide/presentation/presentation_compiler.py \
  tools/guide_gates/trace_image_identity_pipeline.py \
  tests/guide/understanding/test_image_identity_observation.py \
  tests/guide/adapters/image/test_ocr_observation.py \
  tests/guide/application/test_image_recommendation_flow.py \
  tests/guide/application/test_image_presentation_integration.py \
  tests/guide/retrieval/test_image_retrieval_contracts.py \
  tests/guide/tools/test_trace_image_identity_pipeline.py \
  tests/fixtures/guide/images/product-38-index-control.png \
  tests/fixtures/guide/images/product-38-original.png \
  tests/fixtures/guide/images/product-38-low-resolution.jpg \
  tests/fixtures/guide/images/product-38-trace-manifest.json
git commit -m "fix(guide): trace and contract image recommendation flow"
```

### ~~Task 9: Finish typed copy validation without Prompt-driven repair~~ (completed)

**Files:**
- Modify: `app/guide/presentation/copywriter_contracts.py`
- Modify: `app/guide/presentation/copywriter_validation.py`
- Modify: `app/guide/presentation/copywriter_prompt.py`
- Modify: `app/guide/presentation/copywriter_fallback.py`
- Modify: `app/guide/adapters/llm/presentation_copywriter_adapter.py`
- Test: `tests/guide/presentation/test_copywriter_section_contract.py`
- Test: `tests/guide/presentation/test_copywriter_validation.py`
- Test: `tests/guide/presentation/test_copy_evidence_validation.py`
- Test: `tests/guide/adapters/test_presentation_copywriter.py`

- [x] **Step 1: Write failing tests for selected projection facts**

```python
def test_copywriter_validates_required_dimensions_not_all_allowed_facts() -> None:
    packet = _product_knowledge_packet(
        required_dimensions=("texture",),
        approved_soft_facts=(
            _fact("category:39:texture", "texture"),
            _fact("category:39:ingredients_present", "ingredients_present"),
            _fact("evidence:faq", "suitable_skin"),
        ),
    )
    draft = _section_draft(
        answer=_copy(
            "它是轻盈凝露质地。",
            fact_ids=("category:39:texture",),
        )
    )

    assert validate_copywriter_draft(packet, draft) == draft


def test_copywriter_rejects_unselected_hard_fact() -> None:
    packet = _product_knowledge_packet(
        required_dimensions=("texture",),
        approved_soft_facts=(_fact("category:39:texture", "texture"),),
    )
    draft = _section_draft(
        answer=_copy(
            "它是轻盈凝露，并含三肽-32。",
            fact_ids=("category:39:texture",),
        )
    )

    with pytest.raises(CopyValidationError, match="hard fact"):
        validate_copywriter_draft(packet, draft)
```

- [x] **Step 2: Run the copywriter validation tests**

Run:

```bash
PYTHONPATH=. .venv/bin/pytest -q \
  tests/guide/presentation/test_copywriter_section_contract.py \
  tests/guide/presentation/test_copywriter_validation.py \
  tests/guide/presentation/test_copy_evidence_validation.py \
  tests/guide/adapters/test_presentation_copywriter.py
```

Expected: FAIL where legacy generic fields or all-allowed-fact coverage are
still required.

- [x] **Step 3: Derive the model schema from final section order**

For every packet:

```text
section_order is the only required model output shape
direct facts are already selected by Task 5 and are never model-written
required_dimensions are only the dimensions visible in final sections
allowed facts are an upper bound, not a coverage denominator
```

Remove any required `summary_copy`, `product_copy`, or `closing_copy` field
that does not correspond to a final section. Keep `SourceTaggedCopy` with:

```python
text: str
winner_claim: Literal["none", "not_selected", "selected"]
used_fact_ids: tuple[str, ...]
used_constraint_ids: tuple[str, ...]
```

- [x] **Step 4: Keep fallback deterministic and public**

`copywriter_fallback.py` must use selected projection facts and the final
section order. It must never emit:

```text
资料不足
证据不足
当前卡片记录
页面
商家宣传
无核验资料
内部错误
```

Fallback is allowed only for provider unavailability or a validated model
draft failure; it is not allowed to hide a projection or contract bug.

- [x] **Step 5: Run focused validation tests**

Run:

```bash
PYTHONPATH=. .venv/bin/pytest -q \
  tests/guide/presentation/test_copywriter_section_contract.py \
  tests/guide/presentation/test_copywriter_validation.py \
  tests/guide/presentation/test_copy_evidence_validation.py \
  tests/guide/adapters/test_presentation_copywriter.py
```

Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add app/guide/presentation/copywriter_contracts.py \
  app/guide/presentation/copywriter_validation.py \
  app/guide/presentation/copywriter_prompt.py \
  app/guide/presentation/copywriter_fallback.py \
  app/guide/adapters/llm/presentation_copywriter_adapter.py \
  tests/guide/presentation/test_copywriter_section_contract.py \
  tests/guide/presentation/test_copywriter_validation.py \
  tests/guide/presentation/test_copy_evidence_validation.py \
  tests/guide/adapters/test_presentation_copywriter.py
git commit -m "fix(guide): validate copy against selected public facts"
```

### ~~Task 10: Finish semantic-equivalence admission after presentation owners are stable~~ (completed)

**Files:**
- Modify: `app/guide/understanding/exact_parsing.py`
- Modify: `app/guide/intent/unified_turn_router.py`
- Modify: `app/guide/application/unified_guide_flow.py`
- Modify: `tools/guide_gates/build_semantic_equivalence_matrix.py`
- Test: `tests/guide/understanding/test_exact_parsing.py`
- Test: `tests/guide/intent/test_unified_turn_router.py`
- Test: `tests/guide/tools/test_semantic_equivalence_matrix.py`

- [x] **Step 1: Add representative equivalence tests**

```python
@pytest.mark.parametrize(
    "message",
    [
        "回到刚才的推荐，第一款和第二款哪个更适合我？",
        "前面那两款按我的情况怎么选？",
        "这两款里更适合我的是哪支？",
    ],
)
def test_current_batch_suitability_maps_to_comparison(message: str) -> None:
    decision = route_unified_turn(
        meaning=_equivalent_meaning(message),
        understanding=_current_batch_understanding(message),
        snapshot=_recommendation_snapshot(),
    )

    assert decision.responsibility is Responsibility.COMPARISON
    assert decision.processor == "comparison"
```

- [x] **Step 2: Run the semantic tests**

Run:

```bash
PYTHONPATH=. .venv/bin/pytest -q \
  tests/guide/understanding/test_exact_parsing.py \
  tests/guide/intent/test_unified_turn_router.py \
  tests/guide/tools/test_semantic_equivalence_matrix.py
```

Expected: PASS for known families before any new real call is made.

- [x] **Step 3: Keep the matrix typed**

The matrix may normalize only:

```text
operation
object cardinality
object type
continuity
state
requested comparison dimensions
```

It must not normalize by raw Chinese phrase, product name, product ID, or
literal winner language.

- [x] **Step 4: Commit**

```bash
git add app/guide/understanding/exact_parsing.py \
  app/guide/intent/unified_turn_router.py \
  app/guide/application/unified_guide_flow.py \
  tools/guide_gates/build_semantic_equivalence_matrix.py \
  tests/guide/understanding/test_exact_parsing.py \
  tests/guide/intent/test_unified_turn_router.py \
  tests/guide/tools/test_semantic_equivalence_matrix.py
git commit -m "fix(guide): admit equivalent typed recommendation turns"
```

### Task 11: Close audited contracts, then bind SSE, DOM, and screenshot

**Status:** `IN_PROGRESS_APPROVED`. The base strict turn-meaning contract,
request-scoped browser bundle, and zero-API fixtures exist, but the current
worktree has multiple production ownership paths and a second state projection
in the HTTP adapter. The amendment is approved and production execution follows
the exact Step 4.6.0a sequence. Step 4.6 is one indivisible architecture migration;
partially completed substeps do not reopen smoke. Real calls remain forbidden
until the complete local r5 proof is sealed.

**Files:**
- Create: `tools/guide_gates/run_mainline_contract_browser_audit.py`
- Create: `tests/guide/tools/test_run_mainline_contract_browser_audit.py`
- Modify: `app/guide/understanding/__init__.py`
- Modify: `app/guide/understanding/turn_meaning_contracts.py`
- Modify: `app/guide/adapters/llm/turn_meaning_prompt.py`
- Modify: `app/guide/adapters/llm/turn_meaning_adapter.py`
- Modify: `app/guide/intent/semantic_admission.py`
- Modify: `app/guide/understanding/contracts.py`
- Modify: `app/guide/understanding/semantic_contracts.py`
- Modify: `app/guide/understanding/semantic_route_contracts.py`
- Modify: `app/guide/understanding/context_resolver.py`
- Modify: `app/guide/understanding/scenario_parsing.py`
- Modify: `app/guide/understanding/text_understanding.py`
- Modify: `app/guide/understanding/single_call_understanding.py`
- Modify: `app/guide/understanding/ports.py`
- Delete: `app/guide/understanding/parallel_understanding.py`
- Delete: `app/guide/understanding/semantic_detail_contracts.py`
- Delete: `app/guide/understanding/two_stage_semantic.py`
- Create: `app/guide/understanding/typed_image_action.py`
- Modify: `app/guide/adapters/llm/contracts.py`
- Delete: `app/guide/adapters/llm/deepseek_two_stage_intent.py`
- Delete: `app/guide/adapters/llm/intent_detail_prompt.py`
- Delete: `app/guide/adapters/llm/intent_route_prompt.py`
- Delete: `app/guide/adapters/llm/siliconflow_two_stage_intent.py`
- Modify: `app/guide/intent/executable_intent_compiler.py`
- Modify: `app/guide/intent/reference_admission.py`
- Modify: `app/guide/intent/contracts.py`
- Delete: `app/guide/intent/budget_revision_planning.py`
- Delete: `app/guide/intent/consultation_planning.py`
- Modify: `app/guide/intent/signal_merger.py`
- Delete: `app/guide/intent/skin_revision_planning.py`
- Modify: `app/guide/intent/task_planning.py`
- Modify: `app/guide/intent/transition_planning.py`
- Modify: `app/guide/intent/responsibility_matrix.py`
- Modify: `app/guide/intent/unified_turn_router.py`
- Modify: `app/guide/feedback/contracts.py`
- Modify: `app/guide/feedback/focus_state.py`
- Modify: `app/guide/feedback/ports.py`
- Modify: `app/guide/adapters/state/in_memory_conversation_state.py`
- Modify: `app/guide/adapters/state/sqlite_conversation_state.py`
- Modify: `app/guide/application/contracts.py`
- Delete: `app/guide/application/orchestrator.py`
- Create: `app/guide/application/consultation_contracts.py`
- Create: `app/guide/application/execution_contracts.py`
- Create: `app/guide/application/session_profile_resolution.py`
- Delete: `app/guide/application/consultation_collection.py`
- Delete: `app/guide/application/consultation_coordinator.py`
- Modify: `app/guide/application/conversation_state_reducer.py`
- Modify: `app/guide/application/consultation_chat_flow.py`
- Modify: `app/guide/application/image_recommendation_flow.py`
- Modify: `app/guide/application/query_context.py`
- Modify: `app/guide/application/pending_turn.py`
- Modify: `app/guide/application/recommendation_terminal.py`
- Modify: `app/guide/application/scenario_inputs.py`
- Modify: `app/guide/application/text_recommendation_flow.py`
- Modify: `app/guide/application/unified_guide_flow.py`
- Modify: `app/guide/application/chat_api_adapter.py`
- Modify: `app/guide/presentation/copywriter_contracts.py`
- Modify: `app/guide/presentation/copywriter_prompt.py`
- Modify: `app/guide/presentation/copywriter_references.py`
- Modify: `app/guide/presentation/copywriter_validation.py`
- Modify: `app/guide/presentation/presentation_compiler.py`
- Modify: `app/guide/presentation/presentation_packet.py`
- Modify: `app/guide/presentation/public_contracts.py`
- Modify: `app/guide/presentation/sse_events.py`
- Modify: `app/guide/adapters/llm/presentation_copywriter_adapter.py`
- Modify: `app/guide/adapters/llm/provider_common.py`
- Modify: `app/guide/adapters/llm/deepseek_turn_meaning.py`
- Modify: `app/guide/understanding/semantic_equivalence.py`
- Modify: `app/guide_runtime/composition.py`
- Modify: `app/guide_runtime/contracts.py`
- Modify: `app/guide_runtime/app.py`
- Modify: `app/guide_runtime/llm_config.py`
- Modify: `app/guide_runtime/sse.py`
- Modify: `tools/guide_data/build_copy_gate_v3_production.py`
- Modify: `tools/guide_data/promote_approved_category_facts.py`
- Modify: `tools/guide_gates/build_semantic_equivalence_matrix.py`
- Modify: `tools/guide_gates/presentation_copy_gate.py`
- Modify: `tools/guide_gates/replay_presentation_copy_contract.py`
- Modify: `tools/guide_gates/run_real_continuous_conversation_browser_audit.py`
- Modify: `tools/guide_gates/turn_meaning_gate.py`
- Modify: `tools/guide_gates/continuous_conversation_runtime.py`
- Modify: `tools/guide_gates/continuous_conversation_gate.py`
- Modify: `tools/guide_gates/unified_router_gate.py`
- Modify: `tools/guide_gates/run_transition_matrix.py`
- Modify: `tools/guide_gates/local_browser_app.py`
- Modify: `tools/guide_gates/real_transition_probes.py`
- Modify: `tools/guide_gates/run_final_real_translation.py`
- Create: `tools/guide_gates/replay_final_real_backend.py`
- Modify: `tools/guide_gates/run_final_release_gate.py`
- Create: `tools/guide_gates/record_manual_screenshot_review.py`
- Modify: `tools/guide_gates/run_real_continuous_conversation_gate.py`
- Modify: `tools/guide_gates/run_real_presentation_copy_gate.py`
- Modify: `tools/guide_gates/run_real_turn_meaning_gate.py`
- Modify: `tools/guide_gates/single_call_semantic_pilot.py`
- Create: `tools/guide_gates/attempt_ledger.py`
- Create: `tools/guide_gates/build_task11_readiness.py`
- Create: `tools/guide_gates/check_single_path_architecture.py`
- Create: `tools/guide_gates/private_api_key.py`
- Create: `tools/guide_gates/run_bound_runtime.py`
- Create: `tools/guide_gates/run_task11_independent_audit.py`
- Create: `tools/guide_gates/run_task11_production_path_matrix.py`
- Create: `tools/guide_gates/run_zero_api_runtime.py`
- Create: `tools/guide_gates/zero_api_network_guard.py`
- Delete: `tools/guide_gates/guide_pipeline_evaluator.py`
- Delete: `tools/guide_gates/production_routing_gate.py`
- Delete: `tools/guide_gates/real_ab_evidence.py`
- Delete: `tools/guide_gates/run_official_deepseek_smoke.py`
- Delete: `tools/guide_gates/run_real_deepseek_intent_ab.py`
- Delete: `tools/guide_gates/run_real_intent_ab.py`
- Delete: `tools/guide_gates/run_real_two_stage_intent_ab.py`
- Delete: `tools/guide_gates/run_real_unified_router_gate.py`
- Delete: `tools/guide_gates/slice1_backend.py`
- Delete: `tools/guide_gates/two_stage_intent_gate.py`
- Delete: `tools/guide_gates/unified_router_blind_fixture.py`
- Delete: `tools/guide_gates/unified_router_final_blind_fixture.py`
- Delete: `tools/guide_gates/unified_router_qualification_fixture.py`
- Delete: `tools/guide_gates/unified_router_smoke_fixture.py`
- Modify: `tests/guide/tools/test_semantic_equivalence_matrix.py`
- Modify: `tests/guide/tools/test_turn_meaning_gate.py`
- Create: `tests/guide/tools/test_attempt_ledger.py`
- Create: `tests/guide/tools/test_build_task11_readiness.py`
- Create: `tests/guide/tools/test_single_path_architecture.py`
- Create: `tests/guide/tools/test_private_api_key.py`
- Create: `tests/guide/tools/test_run_bound_runtime.py`
- Create: `tests/guide/tools/test_run_task11_independent_audit.py`
- Modify: `tests/guide/tools/test_continuous_conversation_runtime.py`
- Modify: `tests/guide/tools/test_continuous_conversation_gate.py`
- Modify: `tests/guide/tools/test_continuous_conversation_mechanical_truth.py`
- Modify: `tests/guide/tools/test_transition_matrix.py`
- Modify: `tests/guide/tools/test_unified_router_gate.py`
- Modify: `tests/guide/tools/test_run_real_continuous_conversation_gate.py`
- Modify: `tests/guide/tools/test_run_real_turn_meaning_gate.py`
- Modify: `tests/guide/tools/test_final_real_translation.py`
- Create: `tests/guide/tools/test_replay_final_real_backend.py`
- Modify: `tests/guide/tools/test_final_release_gate.py`
- Create: `tests/guide/tools/test_record_manual_screenshot_review.py`
- Create: `tests/guide/tools/test_task11_production_path_matrix.py`
- Create: `tests/guide/tools/test_run_zero_api_runtime.py`
- Create: `tests/guide/tools/test_zero_api_network_guard.py`
- Delete: `tests/guide/tools/test_guide_pipeline_evaluator.py`
- Delete: `tests/guide/tools/test_production_routing_gate.py`
- Delete: `tests/guide/tools/test_real_ab_evidence.py`
- Delete: `tests/guide/tools/test_run_official_deepseek_smoke.py`
- Delete: `tests/guide/tools/test_run_real_deepseek_intent_ab.py`
- Delete: `tests/guide/tools/test_run_real_intent_ab.py`
- Delete: `tests/guide/tools/test_run_real_two_stage_intent_ab.py`
- Delete: `tests/guide/tools/test_run_real_unified_router_gate.py`
- Delete: `tests/guide/tools/test_two_stage_intent_gate.py`
- Delete: `tests/guide/tools/test_two_stage_offline_smoke.py`
- Delete: `tests/guide/tools/test_unified_router_blind_fixture.py`
- Modify: `tests/guide/adapters/test_deepseek_turn_meaning.py`
- Modify: `tests/guide/adapters/test_intent_cache.py`
- Modify: `tests/guide/adapters/test_presentation_copywriter.py`
- Modify: `tests/guide/adapters/test_siliconflow_turn_meaning.py`
- Modify: `tests/guide/adapters/test_turn_meaning_prompt.py`
- Delete: `tests/guide/adapters/test_deepseek_two_stage_intent.py`
- Delete: `tests/guide/adapters/test_intent_detail_prompt.py`
- Delete: `tests/guide/adapters/test_intent_route_prompt.py`
- Delete: `tests/guide/adapters/test_siliconflow_two_stage_intent.py`
- Modify: `tests/guide/application/conftest.py`
- Modify: `tests/guide/application/test_chat_presentation_adapter.py`
- Delete: `tests/guide/application/test_chat_api_adapter.py`
- Modify: `tests/guide/application/test_consultation_assessment.py`
- Modify: `tests/guide/application/test_consultation_chat_flow.py`
- Modify: `tests/guide/application/test_consultation_presentation_integration.py`
- Modify: `tests/guide/application/test_dynamic_consultation.py`
- Create: `tests/guide/application/test_execution_contracts.py`
- Create: `tests/guide/application/test_conversation_state_reducer.py`
- Create: `tests/guide/application/test_session_profile_resolution.py`
- Delete: `tests/guide/application/test_consultation_collection.py`
- Delete: `tests/guide/application/test_consultation_coordinator.py`
- Delete: `tests/guide/application/test_consultation_lifecycle.py`
- Modify: `tests/guide/application/test_cross_worker_text_state.py`
- Delete: `tests/guide/application/test_image_presentation_integration.py`
- Modify: `tests/guide/application/test_image_recommendation_flow.py`
- Modify: `tests/guide/application/test_pending_turn.py`
- Modify: `tests/guide/application/test_query_context.py`
- Modify: `tests/guide/application/test_scenario_inputs.py`
- Modify: `tests/guide/application/test_slice1_backend_gate.py`
- Modify: `tests/guide/application/test_text_presentation_integration.py`
- Modify: `tests/guide/application/test_text_recommendation_flow.py`
- Modify: `tests/guide/application/test_typed_clarification_boundary.py`
- Modify: `tests/guide/application/test_unified_guide_flow.py`
- Modify: `tests/guide/data/test_selection_concept_identity.py`
- Modify: `tests/guide/decision/test_recommendation.py`
- Modify: `tests/guide/decision/test_followup.py`
- Delete: `tests/guide/intent/test_budget_revision_planning.py`
- Modify: `tests/guide/intent/test_concept_preferences.py`
- Modify: `tests/guide/intent/test_constraint_transitions.py`
- Modify: `tests/guide/intent/test_executable_intent_compiler.py`
- Modify: `tests/guide/intent/test_followup_planning.py`
- Modify: `tests/guide/intent/test_reference_admission.py`
- Modify: `tests/guide/intent/test_semantic_admission.py`
- Modify: `tests/guide/intent/test_signal_merger.py`
- Delete: `tests/guide/intent/test_skin_revision_planning.py`
- Modify: `tests/guide/intent/test_task_planning.py`
- Modify: `tests/guide/intent/test_unified_turn_router.py`
- Modify: `tests/guide/adapters/state/test_in_memory_conversation_state.py`
- Modify: `tests/guide/adapters/state/test_sqlite_conversation_state.py`
- Modify: `tests/guide/feedback/test_conversation_state_contracts.py`
- Modify: `tests/guide/feedback/test_focus_state.py`
- Modify: `tests/guide/presentation/test_copywriter_contracts.py`
- Modify: `tests/guide/presentation/test_followup_response.py`
- Modify: `tests/guide/presentation/test_presentation_compiler.py`
- Modify: `tests/guide/presentation/test_presentation_packet.py`
- Modify: `tests/guide/presentation/test_presentation_sse_contracts.py`
- Modify: `tests/guide/presentation/test_budget_revision_response.py`
- Modify: `tests/guide/presentation/test_copywriter_validation.py`
- Modify: `tests/guide/presentation/test_copywriter_prompt.py`
- Modify: `tests/guide/presentation/test_skin_revision_response.py`
- Modify: `tests/guide/retrieval/test_card_specification.py`
- Delete: `tests/guide/runtime/test_backend_handoff_matrix.py`
- Modify: `tests/guide/runtime/test_composition.py`
- Modify: `tests/guide/runtime/test_composition_understanding.py`
- Modify: `tests/guide/runtime/test_consultation_vertical_composition.py`
- Delete: `tests/guide/runtime/test_feedback_runtime_http.py`
- Modify: `tests/guide/runtime/test_frontend_scope.py`
- Modify: `tests/guide/runtime/test_image_upload_request_limits.py`
- Modify: `tests/guide/runtime/test_llm_config.py`
- Delete: `tests/guide/runtime/test_presentation_runtime_http.py`
- Modify: `tests/guide/runtime/test_product_evidence_real_matrix.py`
- Modify: `tests/guide/runtime/test_runtime_http.py`
- Modify: `tests/guide/semantic_test_port.py`
- Modify: `tests/guide/tools/test_no_sentence_patch.py`
- Modify: `tests/guide/tools/test_presentation_copy_gate.py`
- Modify: `tests/guide/tools/test_recovery_is_non_promoting.py`
- Modify: `tests/guide/understanding/test_semantic_equivalence.py`
- Modify: `tests/guide/understanding/test_semantic_route_contracts.py`
- Modify: `tests/guide/understanding/test_category_profile_parsing.py`
- Modify: `tests/guide/understanding/test_scenario_parsing.py`
- Modify: `tests/guide/understanding/test_text_understanding.py`
- Modify: `tests/guide/understanding/test_turn_meaning_contracts.py`
- Modify: `tests/guide/understanding/test_context_resolver.py`
- Modify: `tests/guide/understanding/test_single_call_understanding.py`
- Delete: `tests/guide/understanding/test_parallel_understanding.py`
- Delete: `tests/guide/understanding/test_semantic_detail_contracts.py`
- Delete: `tests/guide/understanding/test_two_stage_parallel_understanding.py`
- Delete: `tests/guide/understanding/test_two_stage_semantic.py`
- Delete: `tests/guide/test_orchestrator_contract.py`
- Create: `tests/guide/legacy_text_understanding.py`
- Modify: `app/static/chat.html`
- Create: `tests/fixtures/guide/intent/task11_production_path_matrix_v1.jsonl`
- Create: `tests/fixtures/guide/intent/turn_meaning_gate_review_v1.jsonl`
- Create: `tests/fixtures/guide/final_release/real_translation_12x4_v5.jsonl`
- Modify: `tests/fixtures/guide/conversation/continuous_trajectory_pool_v1.jsonl`
- Modify: `tests/fixtures/guide/intent/transition_metamorphic_v1.jsonl`
- Modify: `tests/fixtures/guide/intent/turn_meaning_gate_v1.jsonl`
- Delete: `tests/fixtures/guide/intent/two_stage_smoke_v1.jsonl`
- Delete: `tests/fixtures/guide/intent/two_stage_smoke_v1_manifest.json`
- Delete: `tests/fixtures/guide/intent/unified_router_blind_a_v1.jsonl`
- Delete: `tests/fixtures/guide/intent/unified_router_blind_a_v1_manifest.json`
- Delete: `tests/fixtures/guide/intent/unified_router_blind_a_v2.jsonl`
- Delete: `tests/fixtures/guide/intent/unified_router_blind_a_v2_manifest.json`
- Delete: `tests/fixtures/guide/intent/unified_router_blind_a_v3.jsonl`
- Delete: `tests/fixtures/guide/intent/unified_router_blind_a_v3_manifest.json`
- Delete: `tests/fixtures/guide/intent/unified_router_blind_a_v4.jsonl`
- Delete: `tests/fixtures/guide/intent/unified_router_blind_a_v4_manifest.json`
- Delete: `tests/fixtures/guide/intent/unified_router_blind_b_v1.jsonl`
- Delete: `tests/fixtures/guide/intent/unified_router_blind_b_v1_manifest.json`
- Delete: `tests/fixtures/guide/intent/unified_router_blind_b_v2.jsonl`
- Delete: `tests/fixtures/guide/intent/unified_router_blind_b_v2_manifest.json`
- Delete: `tests/fixtures/guide/intent/unified_router_blind_b_v3.jsonl`
- Delete: `tests/fixtures/guide/intent/unified_router_blind_b_v3_manifest.json`
- Delete: `tests/fixtures/guide/intent/unified_router_blind_b_v4.jsonl`
- Delete: `tests/fixtures/guide/intent/unified_router_blind_b_v4_manifest.json`
- Delete: `tests/fixtures/guide/intent/unified_router_blind_b_v5.jsonl`
- Delete: `tests/fixtures/guide/intent/unified_router_blind_b_v5_manifest.json`
- Delete: `tests/fixtures/guide/intent/unified_router_offline_v1.jsonl`
- Delete: `tests/fixtures/guide/intent/unified_router_offline_v1_manifest.json`
- Delete: `tests/fixtures/guide/intent/unified_router_smoke_v1.jsonl`
- Delete: `tests/fixtures/guide/intent/unified_router_smoke_v1_manifest.json`
- Delete: `tests/fixtures/guide/intent/unified_router_smoke_v2.jsonl`
- Delete: `tests/fixtures/guide/intent/unified_router_smoke_v2_manifest.json`
- Delete: `tests/fixtures/guide/intent/unified_router_smoke_v3.jsonl`
- Delete: `tests/fixtures/guide/intent/unified_router_smoke_v3_manifest.json`
- Modify: `tests/fixtures/guide/presentation/copy_gate_v3_production.jsonl`
- Modify: `tests/fixtures/guide/presentation/copy_gate_v3_production_manifest.json`
- Modify: `docs/superpowers/plans/2026-08-21-guide-mainline-contract-closure.md`
- Create: `docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-candidate-manifest.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-candidate-readiness.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-change-manifest.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-semantic-matrix-summary.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-zero-api-summary.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-independent-audit.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-test-path-audit.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-production-path-summary.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-zero-api-network.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-zero-api-runtime-network.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-single-path-architecture.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-08/fixture-browser-desktop/`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-08/fixture-browser-mobile/`
- Generate: `docs/audits/final-release/mainline-contract-closure/bounded-smoke-attempt-*/`

- [x] **Step 0: Lock recommendation mode as parent plus child basis end to end**

Replace any temporary `fit_request_evidence` shape with a single typed
recommendation-mode basis:

```python
RecommendationMode = Literal["explore", "fit"]
RecommendationModeBasis = Literal[
    "broad_exploration",
    "bounded_exploration",
    "count_requested",
    "similar_alternatives",
    "single_best_request",
    "personal_suitability",
    "profile_match_choice",
    "best_among_candidates",
]

class TurnRecommendationModeBasis(_StrictFrozenModel):
    basis: RecommendationModeBasis
    source_text: str = Field(min_length=1, max_length=160)
```

The provider must emit:

```text
recommendation_mode = explore | fit | null
recommendation_mode_basis = {basis, source_text} | null
```

`explore` basis values are:

```text
broad_exploration
bounded_exploration
count_requested
similar_alternatives
```

`fit` basis values are:

```text
single_best_request
personal_suitability
profile_match_choice
best_among_candidates
```

`source_text` is evidence only. It must be an exact current-message substring
validated by `ground_unique_text()`. It is not a router. Do not add code such
as `if "最适合" in message`, `if "推荐一款" in message`, or any equivalent
raw-message regex to decide `explore` or `fit`.

If the provider emits `fit` without a usable profile, skin, concern,
preference, scenario, relative, or confirmed-profile signal, normalize the
typed result to:

```text
recommendation_mode = explore
recommendation_mode_basis.basis = broad_exploration
```

This preserves a normal recommendation instead of turning a broad first turn
into a clarification dead end. If the user truly asked for one best-fit result
and usable fit conditions are present, keep `fit`; the later decision layer may
still return typed clarification when approved public facts are insufficient to
select a Winner.

Add tests that fail before implementation:

```python
def test_turn_meaning_requires_parent_scoped_recommendation_basis() -> None:
    ...

def test_deepseek_normalizes_unsupported_fit_to_explore_basis() -> None:
    ...

def test_no_recommendation_mode_keyword_router_exists() -> None:
    ...
```

The basis must also survive every state boundary:

```text
TurnMeaning
-> StructuredUnderstanding
-> TaskPlan
-> RecommendationQueryContext
-> PendingRecommendationContext
-> transition/revision planning
-> restored TaskPlan
```

`personal_suitability` must never silently restore as
`single_best_request`. Remove code-owned basis fabrication from generic model
validators. Every `model_copy(update=...)` that can create a recommendation
task must be revalidated against the parent-scoped basis contract.

- [x] **Step 0.5: Extend semantic-equivalence output with recommendation mode**

Extend the semantic-equivalence matrix rows with a second-level recommendation
contract:

```json
{
  "responsibility": "recommendation",
  "recommendation_mode": "explore",
  "recommendation_mode_basis": "count_requested"
}
```

For non-recommendation responsibilities, both fields are `null`. The matrix
must include image handoff cases:

```text
single confirmed image + "这是什么" -> image_identity
single confirmed image + similar alternatives -> recommendation/explore
single confirmed image + best-fit similar alternative -> recommendation/fit
confirmed image + product fact question -> product_knowledge
confirmed image + another candidate -> comparison
two or three uploaded/confirmed images + compare wording -> comparison
```

For the multi-image comparison case, the browser audit must verify that the
terminal contract contains comparison sections/rows and that the DOM has a
visible comparison block/table under the same `data-guide-request-id`.

The 128-row matrix must contain both `explore` and `fit` rows. The actual
outcome projector may only report mode/basis carried by production contracts;
it must not synthesize `explore/similar_alternatives` when those fields are
missing. The generated semantic summary describes the reviewed expected
contract matrix and must identify itself as `matrix_kind=expected_contract`;
it must not claim to contain live/provider actual outcomes. The fixed zero-API
suite separately runs the production actual-outcome projector tests. Required
local proof:

```text
fit row count > 0
explore row count > 0
image fit handoff row count > 0
missing expected mode/basis -> expected-contract summary failure
missing actual mode/basis -> production projector test failure
cross-parent basis -> matrix failure
```

- [x] **Step 1: Write the failing audit-bundle test**

```python
def test_audit_bundle_requires_same_turn_contract_dom_and_screenshot(
    tmp_path: Path,
) -> None:
    with pytest.raises(AuditBundleError, match="presentation-contract.json"):
        validate_audit_bundle(
            tmp_path,
            expected_turn_id="text-fit-001",
        )
```

- [x] **Step 2: Implement the browser artifact writer**

Define the bundle boundary in
`run_mainline_contract_browser_audit.py`:

```python
class AuditBundleError(ValueError):
    pass


REQUIRED_TURN_FILES = frozenset({
    "request.json",
    "stream.sse",
    "presentation-contract.json",
    "terminal-dom.json",
    "screenshot.png",
    "console.json",
    "network.json",
})


def validate_audit_bundle(
    turn_dir: Path,
    *,
    expected_turn_id: str,
) -> None:
    missing = REQUIRED_TURN_FILES - {
        path.name for path in turn_dir.iterdir()
    }
    if missing:
        raise AuditBundleError(
            "missing audit files: " + ", ".join(sorted(missing))
        )
    request = json.loads((turn_dir / "request.json").read_text())
    if request.get("turn_id") != expected_turn_id:
        raise AuditBundleError("request turn ID mismatch")
    contract = json.loads(
        (turn_dir / "presentation-contract.json").read_text()
    )
    dom = json.loads((turn_dir / "terminal-dom.json").read_text())
    if dom.get("request_id") != request.get("request_id"):
        raise AuditBundleError("DOM request ID mismatch")
    if dom.get("presentation_mode") != contract.get("mode"):
        raise AuditBundleError("DOM contract mode mismatch")
```

The snippet above is only the minimum boundary. The completed artifact writer
also requires: raw SSE bytes parse to exactly one typed terminal; the saved
contract equals the terminal in those bytes; request ID, mode, section order,
inline product IDs, shelf IDs, visible product IDs, presentation root count,
legacy-render count, and comparison-table count match the same turn; browser
console and network failures are empty; and the screenshot is nonempty and
captured only after the active request finishes.

`run_mainline_contract_browser_audit.py` must:

```text
open /chat, never /chat?demo=...
send the user message through the visible input
record raw SSE bytes from the browser request
save the terminal presentation contract received in that SSE
save visible DOM text, section kinds, visible product IDs, shelf IDs,
card counts, console output, and network failures
take the screenshot after terminal contract rendering completes
write all files under one turn directory
```

Its CLI is fixed by trajectory class:

```text
fixture:
  --base-url http://127.0.0.1:<port>
  --trajectory-set fixture
  --viewport desktop|mobile|all
  --output <directory>

bounded or release:
  --base-url http://127.0.0.1:<port>
  --trajectory-set bounded|release
  --viewport desktop|mobile|all
  --attempt-context <immutable-context.json>
```

`fixture` requires Playwright route fixtures and makes zero API calls.
`bounded` runs only the three trajectories in Step 5. `release` runs the seven
terminal modes required by Task 12. `--output` and `--attempt-context` are
mutually exclusive; bounded/release reject a direct `--output` override.

Assign the active assistant wrapper a stable
`data-guide-request-id=requestContext.requestId` before rendering the contract.
The audit must scope every DOM query to that wrapper, not to all historical
assistant messages on the page. Its fetch hook must call
`response.clone().arrayBuffer()`, persist those UTF-8 bytes verbatim as
`stream.sse`, then separately parse the same bytes for
`presentation-contract.json`.

The terminal DOM assertion must derive the section kinds before evaluating
visible copy:

```python
sections = tuple(
    contract["sections"]
    if isinstance(contract.get("sections"), list)
    else ()
)
contract_section_kinds = [
    section["kind"]
    for section in sections
    if isinstance(section, dict) and isinstance(section.get("kind"), str)
]


def required_public_text(
    sections: tuple[object, ...],
) -> tuple[str, ...]:
    return tuple(
        text
        for section in sections
        if isinstance(section, dict)
        for text in (
            section.get("copy_text"),
            section.get("advisor_reason"),
            *(
                item.get("display_value")
                for item in section.get("direct_facts", ())
                if isinstance(item, dict)
            ),
        )
        if isinstance(text, str) and text
    )


assert dom["legacy_message_count"] == 0
assert dom["legacy_product_card_count"] == 0
assert dom["turn_presentation_root_count"] == 1
assert dom["visible_section_kinds"] == contract_section_kinds
assert dom["shelf_product_ids"] == contract["visible_product_ids"]
assert all(
    text in dom["presentation_text"]
    for text in required_public_text(sections)
)
```

- [x] **Step 3: Add seven zero-API browser fixture trajectories**

Create deterministic contract fixtures for:

```text
explore recommendation
fit recommendation
product knowledge
comparison
image identity
image fit recommendation
multi-image comparison
```

Run them through the actual `/chat` browser reducer and renderer with
`page.route("**/api/v1/chat/stream", ...)` fulfilling the exact typed SSE
bytes for one fixture. The fixtures may replace network data only in this
zero-API test; the production browser gate in Step 5 may not.

- [x] **Step 4: Run the focused harness tests**

Run:

```bash
PYTHONPATH=. .venv/bin/pytest -q \
  tests/guide/tools/test_run_mainline_contract_browser_audit.py \
  tests/guide/runtime/test_frontend_browser_contract.py \
  tests/guide/runtime/test_frontend_presentation_stream.py \
  tests/guide/runtime/test_frontend_card_binding.py
```

Expected: PASS.

- [ ] **Step 4.5: Close all audited shared owners before another real smoke**

This step is a hard precondition for Step 5:

```text
1. Presentation provenance
   Normal image_identity output is a successful deterministic presentation,
   not fallback. Define one central mode-to-source policy used by compiler,
   public contract, telemetry, replay, fixture, and bounded gate.

2. Block-owned attribution
   content and advisor_reason validate and render attribution independently.
   Do not mutate model text by scanning Chinese markers across both blocks.

3. Recommendation equivalence
   Add real fit rows and remove expected/actual outcome fabrication.

4. Recommendation basis persistence
   Persist basis through query context, pending context, revisions, and resume.

5. Consultation ownership
   A collecting consultation may own an ambiguous confirmation, but it must
   not preempt an explicit general-knowledge question. Test both directions.

6. Clarification truth in bounded smoke
   A fit clarification passes only when the captured typed pipeline proves the
   intended fit responsibility and the approved-fact selection gap. Bounded
   and release summaries expose `invalid_clarification_count`, which must be
   zero.

7. Typed empty-image action
   Replace the hidden Chinese default prompt with an API-level typed action.
   The no-sentence-patch gate must scan the frontend boundary too.

8. Exact Task 11 change manifest
   Reconcile every intended Task 11 source, test, tool, plan, and new audit
   artifact before staging. Exclude demo.html, debug files, temporary files,
   historical audits, and recording-v1.

9. Persistent smoke circuit breaker
   Initialize smoke-attempt-ledger.json from existing bounded-smoke evidence.
   Implement the single ledger writer and shared readiness verifier in Task 11.
   Make the bounded/release browser runner reject an open circuit, consume a
   one-time authorization before its first request, and require a fresh
   immutable output directory. Task 12 later reuses the same verifier in the
   48-turn translation runner. Task 11 implements, tests, and seals all v5
   execution tooling under Step 4.6.12; Task 12 only runs those committed
   tools and may not repair them in place.

10. Block-scoped DOM truth
    Validate each rendered section against its corresponding contract section,
    including text order and occurrence count. Whole-root substring presence
    is insufficient because it can hide duplicated text or attribution shown
    beside the wrong block.

11. Machine-derived readiness
    build_task11_readiness.py derives readiness only from reviewed manifests,
    zero-API result files, fixture summaries, protected-path bytes, and ledger
    state. Hand-authored pass booleans are forbidden.
```

- [ ] **Step 4.6: Replace the orchestration trunk, then prove the production path**

This is the r5 enforcement of the r4 architecture reset. It supersedes the r3
idea of adding decision transport and a final snapshot validator around
existing flows. The reset is complete only when the legacy ingress, reverse
projections, internal rerouting, processor persistence, and proof bypasses are
deleted. A compatibility bridge beside the existing path is a failure, even if
tests pass.

#### 4.6 audit verdict

The final read-only audit found three P0 proof failures and two P1 production
architecture failures:

```text
P0-1 readiness can pass without Step 4.6 evidence:
  build_task11_readiness.py does not require the production-path summary,
  test-path audit, or network report and writes some pass fields directly.

P0-2 zero-API evidence is asserted rather than measured:
  credentials are removed, but provider_call_count=0 is literal and outbound
  DNS/socket/HTTP/SDK attempts are not blocked.

P0-3 the required proof path does not exist:
  the production-path runner, fail-closed network guard, fixture, tests, and
  evidence artifacts named by r3 are absent.

P1-1 production has multiple executable owners:
  a runtime flag can bypass UnifiedGuideFlow; provider fallback can bypass the
  compiler; typed image actions construct final understanding; UnifiedGuideFlow
  manufactures consultation decisions; image processors route or synthesize
  decisions internally.

P1-2 state is compiled twice and decision transport is unsafe:
  processors stage snapshots, the HTTP adapter parses SSE to rebuild focus,
  clarification can synthesize a decision, thread-local state crosses
  thread-pool generator advances, and staged saves are separate transactions.
```

Static test-path inventory also found at least:

```text
48 test functions that directly construct StructuredUnderstanding
49 tests that directly call route_unified_turn
13 tests that consume or construct prebuilt SSE
multiple runtime tests with the unified router disabled
```

Those tests may remain only when labeled `unit`, `layer_contract`, or
`frontend_fixture`. They cannot count as
`production_path_from_turn_meaning`, cannot satisfy readiness, and cannot
authorize a real call.

The following completed r3 repairs remain valid building blocks but do not
make Step 4.6 complete:

```text
keep:
  router consumes the compiled goal
  discriminated goal changes reconstruct and revalidate understanding
  new_task does not inherit a stale topic
  provider recommendation count requires source evidence
  collecting consultation does not inherit a stale current item
  recommendation mode basis is required in persisted recommendation slots
  focused ordinal and current product must agree
  in-memory and SQLite writes fully revalidate snapshots
  legacy state migration drops invalid recommendation slots without guessing
  image suitability uses public mode=single_product

replace:
  any final state built by a processor or public-event projector
  any route decision transported through thread-local state
  any compatibility route synthesized by a flow, processor, or adapter
```

#### 4.6.0 Final single-path audit correction

The 2026-08-23 read-only audit invalidates any claim that Steps 4.6.1-4.6.11
are complete. The implementation has one production Router call and one CAS,
but still contains five classes of compatibility bridge:

```text
1. Dispatch bridge:
   pending handling can run before the selected safety processor;
   every image turn enters the image processor first, and that processor may
   call the text processor and rewrite its StateDelta/audit events.

2. Semantic reconstruction bridge:
   text processors can recover product mentions from raw text, parse scenario
   aliases into new constraints, and convert suitability into an invented
   explore/broad_exploration/3 recommendation after routing;
   image evidence can mutate StructuredUnderstanding after compilation.

3. False lane separation:
   typed recommendation/product delta names still write the same flattened
   query_context/candidates/focused_* snapshot fields, so comparison can erase
   the dormant recommendation slot.

4. Outbound projection bridge:
   public events are projected once before CAS only for validation, discarded,
   then projected again after CAS; the adapter also rewrites IntentEvent after
   seeing ClarifyEvent and can infer responsibility from presentation mode.

5. Self-asserted evidence:
   production-path bypass/provider/network counters contain literal zeros,
   observed state edges are copied from fixture requirements, test scope and
   counts are inferred from filenames, and the Python-only network guard does
   not cover child processes.
```

These are implementation failures under the existing architecture, not
reasons to add another compatibility layer. Repair them by moving ownership to
the already named canonical stage and deleting the downstream behavior.

##### 4.6.0a 2026-08-23 anti-patch stop-work amendment

The latest inspection of the current WIP found these live production blockers.
They are not test-only migration seams:

```text
1. Source-dependent processor registry:
   the image entrypoint replaces fixed registry entries, including
   `comparison`, so request source participates in a second dispatch after the
   Router.

2. Post-execution result reconstruction:
   `_attach_image_routing_evidence`, `bind_execution_profile_owner`, and
   wrappers around `_execute_core` rebuild `ExecutionResult`, rewrite intent
   or audit events, or append image/profile lane mutations after the selected
   processor returns.

3. Post-router raw semantic parsing:
   processor-reachable code still receives `UserTurn` or
   `question_summary`, calls explicit-product/scenario parsers, and can alter
   retrieval, constraints, or state after routing.

4. Synthetic turn identity:
   request_id and turn_id are derived from session_id plus the next state
   version instead of being created once at the real HTTP ingress and carried
   unchanged.

5. Split outbound ownership:
   `chat_api_adapter` still owns pre-CAS business projection while also acting
   as the post-CAS byte adapter, and `app/guide_runtime/sse.py` retains
   alternate post-CAS encoding/terminal helpers that could reopen a second
   output path.

6. Missing mechanical prevention:
   `tools/guide_gates/check_single_path_architecture.py` does not yet exist, so
   the current architecture tests fail by import error rather than detecting
   the bridges above.
```

All six are stop-work blockers. Do not continue legacy-test migration,
production-path matrix expansion, readiness generation, evidence generation,
or Task 12 tooling until the checker exists and these capabilities are removed.
No explanation based on worktree status, migration convenience, or future
cleanup changes this order.

Execution resumes in this exact sequence:

```text
A. Gate first, tests/tools only:
   create `check_single_path_architecture.py` and its mutation tests;
   prove the gate discovers the current production roots and reports the
   current violations with stable violation codes;
   do not change production code in this phase.

B. Final contracts before behavior migration:
   define the final raw-request-free `ProcessorExecutionInput`;
   create `TurnIdentity` once at HTTP ingress from the real request/turn
   identity and carry it unchanged;
   construct one immutable processor registry once in production composition;
   if text/image comparison require distinct implementations, give them
   distinct Router-owned processor IDs instead of overriding `comparison`.

C. Remove result and semantic bridges at their owner:
   gather typed image/product/scenario evidence before routing;
   compile any downstream retrieval text into an opaque typed query before
   routing;
   make the selected processor return the complete state delta, terminal, and
   audit evidence in one `ExecutionResult`;
   delete `_attach_image_routing_evidence`,
   `bind_execution_profile_owner`, every `_execute_core` result wrapper, and
   every post-router raw-text parser.

D. Make outbound ownership one-way:
   move the sole pre-CAS business projection, byte encoding, and validation to
   a neutral application-owned encoder;
   reduce `chat_api_adapter` and the runtime HTTP layer to exact byte
   forwarding;
   delete alternate post-CAS encoders, terminal mutators, collectors, and
   business projections.

E. GREEN checkpoint:
   run the focused behavior tests and the complete architecture gate;
   proceed only when both pass and every touched capability already has its
   final owner. Repeat this checkpoint after each subsequent production slice.
```

Phase A must produce a real architectural RED, not an absent-tool RED:

```bash
PYTHONPATH=. .venv/bin/pytest -q \
  tests/guide/tools/test_single_path_architecture.py

PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/check_single_path_architecture.py \
  --repo-root "$PWD" \
  --output /tmp/task11-single-path-architecture.json
```

Expected before Phase B: the test module imports successfully and the checker
exits nonzero with the current bridge violations. An import error, empty
report, caller-authored finding, or generic `passed=false` is not an accepted
RED.

The following seams are allowed only in tests:

```text
frozen TurnMeaning provider injected at the real provider boundary
explicit initial-state setup that is declared as a bypass
direct compiler/router/processor/reducer layer-contract tests
prebuilt typed SSE used only by frontend_fixture tests
read-only observers that cannot return values or alter control flow
```

The frozen provider is the sole exception: it may claim
`production_path_from_turn_meaning`, must record that translation itself was
not exercised, and may authorize only the `TurnMeaning`-through-wire boundary.
Every other allowed seam records its bypasses and may claim only `unit`,
`layer_contract`, or `frontend_fixture`. A case that seeds state directly is a
`layer_contract` even if it enters through HTTP. Stateful production-path
evidence must start from an empty persisted session and build turn N+1 only
from turn N's committed snapshot.

Before changing production code, add RED tests for all of these failures:

```text
test_pending_safety_turn_dispatches_only_safety_processor
test_image_safety_turn_dispatches_only_safety_processor
test_image_recommendation_dispatches_directly_to_selected_processor
test_processor_cannot_call_another_processor
test_processor_cannot_accept_processor_or_execution_callable_dependency
test_only_selected_processor_execute_boundary_is_entered
test_processor_cannot_parse_raw_product_or_scenario_semantics
test_post_router_graph_has_no_raw_user_text_or_semantic_parser
test_processor_cannot_invent_recommendation_outcome
test_image_evidence_does_not_mutate_compiled_understanding
test_comparison_preserves_dormant_recommendation_slot
test_return_after_comparison_reactivates_exact_recommendation_slot
test_public_wire_envelope_is_materialized_once_before_cas
test_emitted_sse_bytes_equal_pre_cas_validated_envelope
test_adapter_cannot_rewrite_intent_or_infer_responsibility
test_snapshot_serialization_has_exact_physical_slot_keys
test_snapshot_rejects_any_extra_top_level_state_key
test_no_legacy_flat_slot_access_outside_migration
test_production_trace_rejects_unmeasured_zero_counters
test_state_edge_coverage_is_derived_from_observed_state
test_test_path_scope_is_not_inferred_from_filename
test_zero_network_guard_covers_or_rejects_child_processes
test_fixture_browser_blocks_and_counts_non_loopback_requests
test_fixture_runtime_rotates_single_use_browser_challenge
test_architecture_gate_discovers_unlisted_production_root
test_no_sentence_patch_rejects_literal_product_ids_without_rejecting_normal_id_comparison
```

Add one AST/import-graph gate:

```text
tools/guide_gates/check_single_path_architecture.py
tests/guide/tools/test_single_path_architecture.py
```

It fails when:

```text
the production HTTP roots do not all enter the one UnifiedGuideFlow boundary
compile_turn_meaning, route_unified_turn, processor-registry dispatch,
  reduce_conversation_state, final SSE encoding, or state-store CAS has any
  production call site outside its named canonical owner or has static
  call-site cardinality other than exactly one in that owner
compile_turn_meaning is bypassed or hidden behind a tuple-returning translator
a processor or any transitively reachable helper imports, constructs,
  resolves, or calls another processor; accepts another processor, processor
  factory, registry, or ExecutionResult-returning callable as a dependency; or
  imports a state store
the transitive post-router graph can access UserTurn raw text,
  question_summary, or a raw semantic parser, or uses typed provenance source
  spans in a predicate, dispatch key, retrieval query, or mutation
an adapter imports business routing/state constructors or rewrites intent
build_presentation_packet accepts an omitted responsibility
ConversationSnapshot serialization does not expose the exact independent slot
  key set, exposes a legacy flat alias/property/custom-serializer projection,
  or maps two logical lanes to one object
the production request contract exposes legacy image payload fields
the production path contains more than one public-event projection/encoding or
  any adapter-side model dump, JSON encoding, or SSE framing after CAS
```

The report uses stable machine-owned violation codes at minimum:

```text
SOURCE_DEPENDENT_PROCESSOR_REGISTRY
POST_EXECUTION_RESULT_REWRITE
POST_ROUTER_RAW_TEXT_ACCESS
SYNTHETIC_TURN_IDENTITY
ADAPTER_BUSINESS_PROJECTION
POST_CAS_SERIALIZATION_CAPABILITY
PROCESSOR_TO_PROCESSOR_REACHABILITY
PRODUCTION_TEST_SEAM_IMPORT
UNLISTED_PRODUCTION_ROOT
NONCANONICAL_OWNER_CALLSITE
```

Add negative mutation tests that independently inject one instance of every
code above. Each mutation must make the checker exit nonzero and identify the
violating path and symbol. The checker derives findings from AST/import/call
graph and production-root discovery; tests may not pass a finding list or
expected verdict into it.

This gate runs after every focused GREEN step. It is mechanical enforcement,
not a manual review checkpoint. Ordinary failures are repaired autonomously at
their owning layer; only a genuine product/architecture conflict requires user
input.

The gate owns an explicit production-root and canonical-owner manifest. It
first discovers every registered FastAPI/Starlette route and every production
composition export, then reconciles that discovered set against the manifest.
Any unlisted route or composition entrypoint that accepts Guide input, emits
Guide SSE, or reaches a Guide processor is a violation. Only after that
reconciliation does it walk the reachable import/call graph from every root.
It also computes transitive reachability from every processor `execute` root
through helpers/factories and rejects reachability to any other processor
constructor or execution boundary.
Runtime observation supplements this graph but cannot excuse a dormant
alternate branch. It wraps every concrete processor class boundary, including
instances created outside the registry, and a production trace fails unless
exactly the registry-selected instance is entered and every other processor
class remains at zero.

This section is intentionally not memory-dependent. A prohibition is not
closed merely because it is written here: it must be represented by a removed
capability in a type/interface, a RED negative test, an AST/import-graph rule,
or measured runtime evidence. If none of those mechanisms can enforce it, the
substep remains open.

#### 4.6 migration boundary

The only accepted production path is:

```text
HTTP request
-> load exactly one current ConversationSnapshot
-> translate UserTurn / typed image action to TurnMeaning
-> compile_turn_meaning exactly once
-> gather pre-routing evidence without choosing responsibility
-> route_unified_turn exactly once
-> execute exactly the selected processor with the same decision
-> receive one ExecutionResult
-> reduce typed StateDelta against the loaded snapshot
-> fully validate one final ConversationSnapshot
-> project, encode, and validate one immutable SSE byte envelope
-> perform one optimistic-CAS save
-> emit the exact already validated bytes
```

The production-path test may replace only the translation provider with a
frozen `TurnMeaning` provider. It must use the real HTTP endpoint and production
composition. It may not call the compiler, router, processor, reducer,
presentation compiler, state store, or SSE serializer directly.

Required invariants:

```text
1. Every translation or deterministic fallback produces TurnMeaning first.
2. compile_turn_meaning is the only TurnMeaning -> StructuredUnderstanding
   boundary, including exact fallback and typed image actions.
3. Facts required to choose ownership are typed pre-routing evidence; evidence
   collection may not choose or overwrite responsibility.
4. route_unified_turn runs exactly once and its exact object reaches the
   processor and ExecutionResult.
5. Processor dispatch uses only `decision.processor`.
   `decision.responsibility` is the semantic owner carried unchanged into
   result/state/presentation, and only the Router maps responsibility to a
   processor. No downstream stage reinterprets understanding.goal or raw text.
6. A processor returns facts, terminal output, and typed lane mutations; it
   does not route, save state, emit final SSE, or build a whole snapshot.
7. StateDelta and presentation are sibling projections of one ExecutionResult.
8. The reducer is the only ConversationSnapshot constructor after load.
9. An accepted business turn performs one final CAS save; a rejected/internal
   failure performs zero saves.
10. SSE serialization is one-way. No SSE or presentation object is parsed back
    into state, ownership, product bindings, or responsibility.
11. A collecting consultation forbids implicit product/image inheritance but
    may be interrupted by an admitted explicit product, image, knowledge, or
    safety task.
12. Return-to-focus requires typed authority in the latest lane slot; an
    ambiguous temporal reference clarifies and never guesses.
13. Recommendation mode and basis survive every permitted detour and return.
14. A new task cannot inherit a previous topic, product, image, batch, pending
    response, or outcome without admitted typed continuity.
15. In-memory and SQLite stores accept/reject identical payloads and identical
    expected_version types; bool is not accepted as an integer version.
16. Public responsibility, presentation mode, winner, product bindings,
    persisted active owner, and SSE terminal all describe the same decision.
17. Public image-comparison price facts either bind to the exact aligned card
    price/spec pair or remain non-public.
```

Implement all substeps below in order. Red tests precede each code change.
After each green substep, run the deletion/forbidden-symbol checks for that
substep and the complete architecture gate. Step 4.6.0a Phase A precedes every
further production edit; Phases B-D remove the current blockers before legacy
test migration or evidence work. Do not preserve or temporarily add a legacy
production path merely to keep an old direct processor test green.

#### 4.6.1 Remove alternate production ingress

Files:

```text
app/guide_runtime/app.py
app/guide_runtime/composition.py
app/guide_runtime/llm_config.py
app/guide_runtime/sse.py
app/guide/application/text_recommendation_flow.py
app/guide/application/image_recommendation_flow.py
app/guide/application/consultation_chat_flow.py
tests/guide/runtime/test_runtime_http.py
tests/guide/application/test_unified_guide_flow.py
```

Write failing tests first:

```text
test_http_text_always_enters_unified_guide_flow
test_http_image_always_enters_unified_guide_flow
test_http_consultation_always_enters_unified_guide_flow
test_production_configuration_has_no_legacy_router_switch
test_direct_processor_stream_is_not_a_production_entrypoint
test_non_stream_chat_message_route_is_absent
```

Delete `GUIDE_UNIFIED_ROUTER_ENABLED` and every production branch that calls
text, image, or consultation processors directly. HTTP composition constructs
one `UnifiedGuideFlow` and every Guide request enters it. Delete the
`/api/v1/chat/message` non-streaming endpoint and its response projection; the
typed SSE endpoint is the sole production Guide output. Remove obsolete runtime
settings, environment documentation, and tests that assert
`unified_router=false`.

Processor-local helpers may remain only as private domain operations called by
`execute()`. A public `stream()` that independently translates, plans, routes,
or persists is a second mainline and must be removed. Do not keep a legacy
branch behind a default-off flag.

Deletion gate:

```text
no GUIDE_UNIFIED_ROUTER_ENABLED production reference
no runtime call to TextRecommendationOrchestrator.stream
no runtime call to ImageRecommendationOrchestrator.stream
no runtime call to ConsultationChatFlow.stream
no registered /api/v1/chat/message route or JSON reprojection of Guide events
```

#### 4.6.2 Make every source cross the one compiler boundary

Files:

```text
app/guide/understanding/single_call_understanding.py
app/guide/understanding/typed_image_action.py
app/guide/understanding/ports.py
app/guide/intent/executable_intent_compiler.py
app/guide/application/unified_guide_flow.py
tests/guide/understanding/test_single_call_understanding.py
tests/guide/application/test_unified_guide_flow.py
tests/guide/intent/test_executable_intent_compiler.py
```

Write failing tests first:

```text
test_provider_success_compiles_returned_turn_meaning_once
test_provider_failure_builds_exact_turn_meaning_then_compiles_once
test_typed_image_action_returns_turn_meaning_not_understanding
test_production_translation_port_returns_turn_meaning
test_reverse_understanding_to_meaning_adapter_is_absent
```

The production translation port returns only the untrusted semantic proposal.
The canonical flow owns the one visible compiler call:

```python
def translate(
    ...,
) -> TurnMeaning:
    return provider_or_exact_fallback_turn_meaning(...)


# UnifiedGuideFlow
meaning = translation.translate(...)
understanding = compile_turn_meaning(
    message=turn.question_summary,
    meaning=meaning,
    context=context,
)
```

The exact fallback must first produce `TurnMeaning`; it may not return a
prebuilt final `StructuredUnderstanding`. Replace
`translate_typed_image_action()` with a function that produces only
`TurnMeaning`, then pass that value through `compile_turn_meaning`.

Delete tuple-returning translation adapters. The production-path observer is
attached at the explicit compiler call, not after a dependency has already
returned a potentially prebuilt `StructuredUnderstanding`.

Delete every `StructuredUnderstanding -> TurnMeaning` reverse adapter,
including `_meaning_from_compilation`. Do not retain it for tests. Tests that
need a frozen model boundary inject `TurnMeaning`; compiler unit tests may
construct `StructuredUnderstanding` only when the test scope is explicitly the
understanding contract itself.

Preserve the already green compiler invariants:

```text
compiled goal owns routing
goal changes reconstruct and fully validate the destination object
new_task does not inherit stale topic
provider count is source-grounded
```

#### 4.6.3 Gather routing facts before routing

Files:

```text
app/guide/application/unified_guide_flow.py
app/guide/application/image_recommendation_flow.py
app/guide/application/consultation_chat_flow.py
app/guide/intent/reference_admission.py
app/guide/intent/unified_turn_router.py
tests/guide/application/test_unified_guide_flow.py
tests/guide/application/test_image_recommendation_flow.py
tests/guide/intent/test_reference_admission.py
tests/guide/intent/test_unified_turn_router.py
```

Write failing tests first:

```text
test_image_identity_observation_exists_before_router_call
test_product_resolution_exists_before_router_call
test_collecting_consultation_authority_is_router_input
test_explicit_knowledge_question_can_interrupt_collecting_consultation
test_pre_router_evidence_cannot_set_responsibility
```

Gather only facts that the router needs:

```text
resolved product/image references
image identity observation and confirmed image products
pending clarification authority
collecting/confirmable consultation authority
admitted explicit return authority
```

Use existing typed observations and explicit router parameters. Do not create
a second decision-shaped "pre-route plan". Evidence collection is read-only:
it does not select a processor, build a presentation, mutate conversation
state, or save an image bundle. If evidence is ambiguous, represent that
ambiguity and let the router return clarification.

For image turns, observe identity before routing and reuse the exact same
observation during execution. Do not observe once for routing and again inside
the image processor. The evidence is passed beside the immutable compiled
understanding; it may not be applied with `model_copy()` to add a topic,
remove an uncertainty, or retain stale image ordinals.

All deterministic product-name and scenario parsing that can affect routing,
constraints, retrieval, or ranking also completes here. Processor code may use
only typed compiled fields and typed evidence; no processor, transitive helper,
presentation builder, or adapter receives `UserTurn`, `message`,
`question_summary`, or another raw-request carrier. Exact source spans already
validated inside typed provenance remain evidence-only and may not drive
control flow or retrieval. Retrieval text required downstream is compiled
before routing into an opaque typed query value whose module exposes no
semantic parsing operations. Turn/session/request identity travels in a
separate text-free metadata contract. No post-router reachable module may call
`find_explicit_mentions()`, `parse_scenarios()`, exact parsers, or equivalent
raw-text classifiers.

#### 4.6.4 Make the router the sole executable owner

Files:

```text
app/guide/intent/unified_turn_router.py
app/guide/intent/responsibility_matrix.py
app/guide/application/unified_guide_flow.py
app/guide/application/text_recommendation_flow.py
app/guide/application/image_recommendation_flow.py
app/guide/application/consultation_chat_flow.py
tests/guide/intent/test_unified_turn_router.py
tests/guide/application/test_unified_guide_flow.py
tests/guide/application/test_image_recommendation_flow.py
```

Write failing tests first:

```text
test_each_accepted_turn_calls_router_exactly_once
test_router_decides_collecting_consultation_without_flow_override
test_router_decides_image_identity_comparison_and_suitability
test_processor_receives_the_exact_router_decision_object
test_processor_modules_do_not_import_or_call_router
test_processor_constructor_rejects_processor_or_result_callable_dependency
test_nonselected_processors_are_never_entered
test_no_downstream_route_decision_constructor_exists
```

`route_unified_turn()` returns the final `UnifiedRouteDecision`.
`decision_for_responsibility()` remains only the central mapping used inside
the router/responsibility matrix. The Router writes both the semantic
`decision.responsibility` and the single executable `decision.processor`;
dispatch indexes only `decision.processor`. No flow or registry maps from
responsibility a second time, and no downstream code branches on raw
`TurnMeaning.operation_hint`, rewrites `StructuredUnderstanding.goal`, or
chooses a new responsibility.

`UnifiedGuideFlow` owns one explicit processor registry keyed by
`decision.processor`. It invokes exactly one registered processor. Image
observation is a pre-routing evidence service, not a parent processor:

```text
forbidden:
  UnifiedGuideFlow -> image processor -> standard/text processor
  pending reply branch -> text processor before safety dispatch

required:
  gather typed evidence -> Router -> processor_registry[decision.processor]
```

The selected processor receives a raw-request-free typed execution input
containing the admitted understanding, exact decision, current snapshot, turn
identity, and relevant typed evidence, including image observations and
pending-reply evidence. No processor contains an optional
processor/callable/factory dependency, looks up the registry, constructs
another processor, reaches one through a helper, calls another processor's
`execute()`, or wraps another processor's `ExecutionResult`. Runtime
observation instruments every concrete processor class, not merely registry
instances, and rejects any non-selected invocation.

Delete:

```text
UnifiedGuideFlow._route_for_responsibility
router-before / router-after consultation overrides
image processor route_unified_turn calls
image processor _ensure_route_decision
image processor standard_processor delegation
pending handling before processor_registry dispatch
processor or adapter decision_for_responsibility calls
clarification-to-decision synthesis
```

An unsupported or inconsistent decision fails before retrieval. The processor
may reject evidence that is insufficient for the chosen responsibility, but
its result is a typed clarification/error under the same decision; it may not
switch responsibility.

#### 4.6.5 Return one explicit ExecutionResult

Files:

```text
app/guide/application/execution_contracts.py
app/guide/application/contracts.py
app/guide/application/unified_guide_flow.py
app/guide/application/text_recommendation_flow.py
app/guide/application/image_recommendation_flow.py
app/guide/application/consultation_chat_flow.py
tests/guide/application/test_execution_contracts.py
tests/guide/application/test_unified_guide_flow.py
tests/guide/application/test_text_recommendation_flow.py
tests/guide/application/test_image_recommendation_flow.py
```

Write failing tests first:

```text
test_processor_returns_execution_result_with_same_decision
test_execution_result_has_exactly_one_typed_terminal
test_presentation_and_state_delta_share_product_bindings
test_clarification_retains_the_same_route_decision
test_processor_cannot_return_complete_conversation_snapshot
test_processor_does_not_save_or_emit_sse
```

Define frozen strict application contracts in one neutral module. Reuse the
existing public presentation and typed clarification/error payload contracts;
do not create a second SSE-specific business result:

```python
class ExecutionResult(_StrictFrozen):
    decision: UnifiedRouteDecision
    state_delta: ConversationStateDelta
    terminal: ExecutionTerminal
    audit_events: tuple[TypedAuditEvent, ...] = ()
```

`ExecutionTerminal` is a discriminated union of exactly:

```text
public presentation
typed clarification
typed error
```

`TurnIdentity` contains only `session_id`, `request_id`, and `turn_id`.
`ProcessorExecutionInput` is raw-request-free and contains `TurnIdentity`,
`StructuredUnderstanding`, `UnifiedRouteDecision`, the validated current
snapshot, and typed pre-routing evidence. Neither contract contains the raw
request or a generic metadata dictionary; source spans inside typed provenance
remain data-only and are forbidden in downstream predicates.

Each processor exposes one `execute(...) -> ExecutionResult` boundary and
receives the raw-request-free typed execution input defined above. The exact
decision object/value must appear in the result unchanged. The processor may
compile the presentation and audit facts for its assigned responsibility, but
may not receive raw user text, return a whole `ConversationSnapshot`, call a
state store, invoke the router, serialize SSE, accept another processor, or
accept an `ExecutionResult`-returning callback.

All current generator-side decision binding, staged state save, and terminal
side-channel behavior is deleted rather than wrapped. A processor may not
post-process another processor's result, append an extra lane mutation to it,
rewrite its audit intent, or return a copied `ExecutionResult`.

#### 4.6.6 Make StateDelta typed and the reducer constructive

Files:

```text
app/guide/application/execution_contracts.py
app/guide/application/conversation_state_reducer.py
app/guide/feedback/contracts.py
app/guide/feedback/focus_state.py
tests/guide/application/test_execution_contracts.py
tests/guide/application/test_conversation_state_reducer.py
tests/guide/feedback/test_conversation_state_contracts.py
tests/guide/feedback/test_focus_state.py
```

Write failing tests first:

```text
test_reducer_constructs_snapshot_from_delta_not_proposed_snapshot
test_same_lane_replace_overwrites_only_that_lane
test_cross_lane_execution_preserves_dormant_slots
test_explicit_return_reactivates_exact_authorized_slot
test_ambiguous_temporal_return_never_selects_a_slot
test_focus_candidate_ordinal_must_match_current_product
test_delta_product_bindings_must_match_route_decision
test_snapshot_serialization_has_exact_physical_slot_keys
test_snapshot_slots_round_trip_independently_in_both_stores
test_no_legacy_flat_slot_access_outside_named_migration
```

`ConversationStateDelta` contains a discriminated mutation for each bounded
lane:

```text
preserve
replace(value)
clear(reason)
```

The delta has explicit mutations for:

```text
recommendation slot (query + candidate batch)
product slot
confirmed-image slot
consultation slot
general-knowledge slot
pending clarification/reply slot
profile patch when the current processor has typed authority
```

It does not contain `session_id`, `version`, or `active_processor`; the reducer
derives those from the loaded snapshot, a text-free `TurnIdentity`, and the
canonical decision. It does not carry a chronological history.

The persisted snapshot uses the same physical slot separation:

```text
recommendation_slot: query + recommendation candidate batch
product_slot: latest single product or comparison batch
image_slot: latest confirmed image products
consultation_slot: current consultation
knowledge_slot: latest general-knowledge focus
reply_slot: pending clarification/reply
active_focus: one typed pointer to one slot
```

Aliases such as one shared `candidates` field for recommendation and product
lanes are forbidden. A comparison may replace `product_slot` but may not clear
or overwrite `recommendation_slot`. Legacy flat snapshots are converted once
at the SQLite migration boundary into the current slot schema; runtime code
does not dual-read or dual-write old and new shapes.

The persisted top-level serialization key set is exactly:

```text
session_id
version
profile_owner
session_profile
active_owner
active_focus
recommendation_slot
product_slot
image_slot
consultation_slot
knowledge_slot
reply_slot
```

No additional state-bearing or compatibility key is allowed. The snapshot
contains no legacy flat `has_image_delivery`, `query_context`, `empty_result`,
`candidates`, `focused_*`, `consultation`, `clarification`, or `pending_turn`
alias. Each nested slot is also a strict, frozen, `extra="forbid"` model with
this exact serialized shape:

```text
RecommendationSlotState:
  kind = "recommendation"
  query_context: RecommendationQueryContext
  candidates: tuple[DisplayedCandidateRef, ...]
  empty_result: bool
  focused_candidate_ordinal: int | null

ProductSlotState:
  kind = "product"
  products: tuple[DisplayedCandidateRef, ...]
  focused_product_id: ProductId | null
  focused_evidence_ids: tuple[EvidenceId, ...]

ImageSlotState:
  kind = "image"
  confirmed_products: tuple[ConfirmedImageProductRef, ...]
  focused_image_ordinal: int | null

ConsultationSlotState:
  kind = "consultation"
  state: ConsultationSubstate

KnowledgeSlotState:
  kind = "knowledge"
  question: str
  evidence_ids: tuple[EvidenceId, ...]

ReplySlotState =
  PendingClarificationSlot(kind = "clarification", value: ClarificationProgress)
  | PendingReplySlot(kind = "pending_reply", value: PendingTurn)

ActiveFocus:
  slot: recommendation | product | image | consultation | knowledge | reply
  object_id: typed identifier | null
  ordinal: bounded integer | null
```

No slot accepts `dict[str, Any]`, another lane's model, an extra compatibility
member, or an untagged union. `active_owner` is the exact router
responsibility, and `active_focus.slot` must name one present slot authorized
by `decision.focus_source`. Properties, validators, custom serializers, and
`model_dump` hooks may not reconstruct legacy aliases or hide extra nested
state. Both stores must round-trip a snapshot with all slots populated and
prove that replacing one serialized slot leaves every other serialized object
byte-equivalent. Negative tests add an unknown key inside every slot and inject
each other lane's payload under that slot; all must fail. Only the named
persistence migration may read the old flat keys.

Implement the reducer as the sole snapshot constructor:

```python
def reduce_conversation_state(
    *,
    current: ConversationSnapshot | None,
    turn_identity: TurnIdentity,
    decision: UnifiedRouteDecision,
    delta: ConversationStateDelta,
) -> ConversationSnapshot:
    ...
```

The reducer:

```text
starts from the fully validated current snapshot or an empty snapshot
applies each lane mutation once
sets active_owner from decision.responsibility
sets active_focus only from decision.focus_source and its authorized slot
sets session_id from the text-free turn identity
sets version to current.version + 1
validates route bindings against every replaced slot
preserves dormant cross-lane slots
fully reconstructs ConversationSnapshot with strict validation
validates the transition and returns it
```

A same-lane new task replaces that lane's previous slot. A cross-lane task
preserves other slots but does not reactivate them. Only an admitted explicit
return/reference may select a dormant slot. Preserve the existing legacy
migration that drops a recommendation slot with missing basis while retaining
independently valid lanes; never invent a basis.

#### 4.6.7 Persist once with one optimistic CAS

Files:

```text
app/guide/application/unified_guide_flow.py
app/guide/application/chat_api_adapter.py
app/guide/feedback/ports.py
app/guide/adapters/state/in_memory_conversation_state.py
app/guide/adapters/state/sqlite_conversation_state.py
tests/guide/application/test_chat_api_adapter.py
tests/guide/application/test_cross_worker_text_state.py
tests/guide/adapters/state/test_in_memory_conversation_state.py
tests/guide/adapters/state/test_sqlite_conversation_state.py
```

Write failing tests first:

```text
test_accepted_turn_performs_exactly_one_state_save
test_invalid_result_performs_zero_state_saves
test_second_mutation_failure_cannot_leave_partial_state
test_cas_conflict_does_not_emit_success_terminal
test_decision_transport_survives_worker_switch_without_thread_local
test_memory_and_sqlite_reject_same_invalid_snapshot_and_expected_version
test_bool_expected_version_is_rejected_by_both_backends
```

The application completes one turn in this order:

```text
validate ExecutionResult and terminal
reduce one final snapshot
project, encode, and validate the complete outbound SSE byte envelope in memory
CAS-save the final snapshot once with the loaded expected version
emit the exact already validated bytes
```

Delete `_PublicEventStateTransaction`, `threading.local()` decision binding,
staged snapshot arrays, processor state-store calls, and multi-save commit
loops. A CAS conflict fails the turn without replaying a provider call or
emitting a success terminal.

Before writing, both stores reconstruct:

```python
validated = ConversationSnapshot.model_validate(
    snapshot.model_dump(mode="python"),
    strict=True,
)
```

Both stores must apply the same strict `expected_version` contract and raise
the same public state exception classes. SQLite performs the compare and final
write in one database transaction. In-memory performs the equivalent operation
under one lock.

#### 4.6.8 Make SSE a one-way serializer

Files:

```text
app/guide/application/execution_contracts.py
app/guide/application/unified_guide_flow.py
app/guide/application/chat_api_adapter.py
app/guide/presentation/presentation_compiler.py
app/guide/presentation/public_contracts.py
app/guide/presentation/sse_events.py
tests/guide/application/test_chat_presentation_adapter.py
tests/guide/application/test_image_recommendation_flow.py
tests/guide/application/test_chat_api_adapter.py
tests/guide/runtime/test_runtime_http.py
```

Write failing production-boundary tests first:

```text
test_adapter_forwards_validated_envelope_without_business_projection
test_adapter_emits_pre_cas_bytes_without_reserializing
test_public_events_cannot_change_persisted_focus
test_clarification_event_cannot_synthesize_route_decision
test_sse_decision_equals_execution_result_decision
test_image_suitability_survives_public_http_contract
test_explore_winner_is_not_applicable_in_decision_answer_and_presentation
test_image_comparison_rejects_unaligned_public_price_spec
```

A pure wire encoder receives the validated `ExecutionResult` plus the proposed
next snapshot version, materializes `audit_events` and the one terminal in
deterministic order, encodes the final JSON/SSE frames, and validates the
complete byte envelope before the CAS. `UnifiedGuideFlow` emits that already
validated byte envelope only after the CAS succeeds. `chat_api_adapter`
forwards the stored bytes only; it has no state-store write path,
router/responsibility mapping, model dump, JSON encoding, or SSE framing path.

The pre-CAS encoded frames are retained as one immutable wire envelope. After
CAS, the HTTP layer iterates those exact byte objects; it may not call the
projector, serializer, `model_dump`, JSON encoder, or SSE framer again. A
byte-for-byte assertion covers the retained pre-CAS envelope and the HTTP
response body. No adapter may scan later events to rewrite an earlier
`IntentEvent`. Presentation responsibility is required input from
`UnifiedRouteDecision`; omission and
`responsibility_for_presentation_mode()` inference fail locally.

Delete:

```text
_focus_state_from_public_events
_PublicEventStateTransaction
bind_route_decision / has_route_decision / clear_route_decision
clarification fallback decision construction
intent-string -> active_processor projection
ProductsEvent/ImageObservationEvent/GeneralKnowledgeEvent -> state projection
```

Image suitability remains
`Responsibility.SINGLE_PRODUCT_SUITABILITY` with `mode=single_product` from the
router through terminal and DOM. Explore normalizes winner to
`not_applicable` before the result is constructed. Public image-comparison
prices are omitted unless the exact product card exposes the same aligned
price/specification and source identity.

SSE event models remain transport contracts. They cannot be imported into the
state reducer or used by a processor to decide its state mutation.

#### 4.6.9 Reclassify and migrate legacy tests

Files:

```text
tests/guide/application/
tests/guide/intent/
tests/guide/runtime/
tests/guide/tools/
tests/guide/semantic_test_port.py
tools/guide_gates/continuous_conversation_runtime.py
tools/guide_gates/run_transition_matrix.py
tools/guide_gates/unified_router_gate.py
tools/guide_gates/build_task11_readiness.py
```

Inventory every Task 11 test and label its maximum claim:

```text
unit
layer_contract
frontend_fixture
production_path_from_turn_meaning
```

Classification is per collected pytest node, not per filename. The audit
derives entrypoint and bypasses from executable instrumentation or an explicit
reviewed marker whose truth is verified against the collected test. Renaming
an empty file to `test_task11_production_path_matrix.py` must not create a
production-path claim or any case/turn/state-edge count. The sole authorizing
production-path scope starts at the frozen provider's `TurnMeaning` output,
enters through the real HTTP endpoint and production composition, and records
`translation_provider=frozen`. Direct state setup, handcrafted
`StructuredUnderstanding`, direct layer calls, and prebuilt SSE are never
eligible for that scope.

Migrate tests that claim orchestration behavior to the HTTP production-path
harness. Keep direct compiler/router/reducer/processor tests only as focused
layer tests. Keep prebuilt SSE only as frontend renderer evidence. Delete tests
for removed legacy entrypoints instead of recreating those entrypoints in
production.

`task11-test-path-audit.json` records for every selected test:

```text
claimed scope
real entrypoint
layers executed
layers bypassed
semantic injection type
fixture dependencies
case / trajectory / turn / state-edge counts
```

The audit fails if a handcrafted understanding, direct router, direct
processor, direct reducer, directly seeded state, or prebuilt SSE test claims
`production_path_from_turn_meaning`. Existing green counts are historical
until this classification is generated.

#### 4.6.10 Build the zero-provider production-path matrix

Files:

```text
tools/guide_gates/run_task11_production_path_matrix.py
tests/guide/tools/test_task11_production_path_matrix.py
tests/fixtures/guide/intent/task11_production_path_matrix_v1.jsonl
```

Write failing tests first:

```text
test_matrix_rejects_structured_understanding_injection
test_matrix_rejects_direct_router_bypass
test_matrix_covers_all_expected_and_required_state_edges
test_matrix_runs_all_nine_bounded_turns_without_provider_calls
test_matrix_rejects_legacy_production_entrypoint
test_matrix_rejects_multiple_compiler_calls_per_turn
test_matrix_rejects_multiple_router_calls_per_turn
test_matrix_rejects_missing_or_multiple_execution_results
test_matrix_rejects_missing_or_multiple_reducer_calls
test_matrix_rejects_missing_or_multiple_state_save_per_accepted_turn
test_matrix_rejects_event_to_state_projection
```

The production-path runner injects reviewed `TurnMeaning` values at the
configured provider boundary and invokes the real HTTP endpoint. It imports
and calls no private compiler, router, processor, presentation, state, or SSE
function directly. Its assertions use only HTTP output, persisted snapshots,
and the declared expected state edges.

Generate pairwise state coverage for at least:

```text
active owner:
  none | recommendation | product_knowledge | consultation |
  general_knowledge | image_identity | clarification | safety_escalation

reply state:
  not awaiting | collecting consultation | confirmable consultation |
  pending clarification

preserved authority:
  none | product | candidate batch | one confirmed image |
  multiple confirmed images | product plus active consultation

current semantic act:
  observation answer | ambiguous continuation | explicit product question |
  explicit image question | explicit general-knowledge question |
  recommendation revision | explicit return | safety escalation

reference source:
  none | explicit current item | candidate ordinal | image ordinal |
  current batch | ambiguous reference
```

The semantic partition executes all 128 reviewed frozen `TurnMeaning` rows.
The state partition executes generated multi-turn trajectories, including the
exact bounded trajectories. State for turn N+1 must be loaded only from turn
N's reducer-built persisted snapshot, never from a test-side snapshot patch or
public event.

Keep the 128-row matrix, but label it only as `expected_contract`. Add
`task11-production-path-summary.json` as separate actual-execution evidence:

```json
{
  "schema_version": "guide-task11-production-path-summary-v1",
  "passed": true,
  "expected_contract_case_count": 128,
  "actual_equivalence_case_count": 128,
  "actual_equivalence_failure_count": 0,
  "trajectory_count": 12,
  "stateful_turn_count": 48,
  "turn_count": 176,
  "state_edge_count": 40,
  "required_state_edge_count": 40,
  "bounded_turn_count": 9,
  "bounded_failure_count": 0,
  "translation_injection_count": 176,
  "compiler_bypass_count": 0,
  "compiler_call_count_violation_count": 0,
  "structured_understanding_injection_count": 0,
  "direct_router_bypass_count": 0,
  "legacy_entrypoint_count": 0,
  "router_call_count_violation_count": 0,
  "decision_identity_violation_count": 0,
  "selected_processor_invocation_count_violation_count": 0,
  "nonselected_processor_invocation_count": 0,
  "execution_result_count_violation_count": 0,
  "reducer_call_count_violation_count": 0,
  "processor_state_write_count": 0,
  "event_state_projection_count": 0,
  "state_save_count_violation_count": 0,
  "terminal_contract_failure_count": 0,
  "state_transition_failure_count": 0,
  "outbound_network_attempt_count": 0,
  "provider_call_count": 0
}
```

`translation_injection_count` counts the frozen `TurnMeaning` values supplied
at the provider boundary and must equal `turn_count`.
Every executed row records a per-turn trace with compiler count, router count,
decision digest at route/selected-processor/result/SSE, selected processor
identity, invocation count for every registered processor, reducer count,
state-save count, loaded version, and committed version. Accepted routed turns
require exactly one compiler call, one router call, one selected processor
invocation, zero non-selected processor invocations, one `ExecutionResult`,
one reducer call, and one save. Pre-decision rejection or internal failure
requires zero saves. All bypass, alternate-entry, decision mismatch,
non-selected processor, processor-write, event-projection, and multi-save
counters must be zero.

Collect these counts through a request-scoped, read-only observer wired at the
real production composition boundary. Its default implementation is a no-op;
the proof implementation may record boundary observations but cannot return a
decision, mutate state, replace a dependency, or alter control flow. The runner
must not infer counts from expected rows or hard-code them in its summary.
Observer callbacks placed after a dependency returns do not prove that the
dependency executed its internal compiler/router boundary.

`required_state_edges` remains reviewed expected input. Each trace separately
computes `observed_state_edges` from the actual loaded state, current admitted
meaning/evidence, selected processor, and committed state. Coverage is the
intersection of required and observed edges; copying
`case.required_state_edges` into the trace is forbidden.

#### 4.6.11 Enforce real zero-network evidence and fail-closed readiness

Files:

```text
tools/guide_gates/zero_api_network_guard.py
tools/guide_gates/build_task11_readiness.py
tools/guide_gates/check_single_path_architecture.py
tools/guide_gates/run_zero_api_runtime.py
tools/guide_gates/run_bound_runtime.py
tools/guide_gates/run_task11_independent_audit.py
tests/guide/tools/test_zero_api_network_guard.py
tests/guide/tools/test_build_task11_readiness.py
tests/guide/tools/test_single_path_architecture.py
tests/guide/tools/test_run_zero_api_runtime.py
tests/guide/tools/test_run_bound_runtime.py
tests/guide/tools/test_run_task11_independent_audit.py
```

Write failing tests first:

```text
test_zero_api_guard_rejects_non_loopback_connection
test_zero_api_guard_counts_provider_boundary_attempt
test_readiness_rejects_unmeasured_provider_count
test_readiness_rejects_missing_production_path_summary
test_readiness_rejects_missing_test_path_audit
test_readiness_rejects_hard_coded_pass_field
test_readiness_rejects_unprotected_fixture_dependency
test_fixture_browser_rejects_non_loopback_request
test_fixture_browser_rejects_reused_health_challenge
test_manifest_records_and_verifies_staged_deletions
test_release_readiness_binds_complete_execution_tree
test_release_readiness_rejects_untracked_execution_file
test_independent_audit_derives_all_reviewed_hashes_without_caller_verdict
test_independent_audit_rejects_missing_scope_or_failed_mechanical_check
test_independent_audit_mutation_corpus_catches_each_primary_gate_omission
```

The zero-API runner must install a fail-closed network guard before imports
that can construct provider clients. Loopback traffic for the local browser
runtime is allowed; every non-loopback DNS, socket, HTTP, or SDK connection
attempt fails the run and increments `outbound_network_attempt_count`.
`provider_call_count` must come from an instrumented provider boundary, never
from a literal summary value. Add a negative test that deliberately attempts
one outbound call and proves the gate fails.

The isolation boundary covers child processes. Either run the complete command
under an OS-level deny-network sandbox or reject process creation while the
guard is active. A parent-process monkey patch with an unguarded Python, Node,
curl, or multiprocessing child is not zero-network evidence.

The fixture browser process is part of the same zero-network claim. Because
Chromium must be spawned, the fixture browser runner executes itself and all
Chromium descendants under an OS-level loopback-only sandbox whose
process-tree audit reports attempted and denied DNS, TCP, UDP, QUIC, and
process-spawn escape operations. Playwright/CDP request logs are a second,
reconciled signal, not the source of the process-level zero. If the platform
cannot both enforce the policy and report attempted process-tree egress, the
fixture browser gate fails closed; an application-process socket patch or an
empty browser console/network-error list is insufficient. Each desktop/mobile
invocation obtains a fresh runtime health challenge, atomically consumes it,
and records the challenge digest, sandbox audit digest,
`process_tree_non_loopback_attempt_count`, and
`browser_observed_non_loopback_attempt_count` in its summary. Both counts must
be zero.

Add the continuous-conversation runtime, gate, mechanical-truth,
transition-matrix, unified-router, and fixture-validation tests to the Task 11
manifest. Their evidence must report separate trajectory, turn, state-edge,
and transition counts; one aggregate pytest count is not sufficient.
Every JSONL, image, snapshot, or other fixture read by those gates must also
be listed in the candidate manifest and protected payload. The test-path audit
must fail when a selected test has an unprotected fixture dependency.

`task11-test-path-audit.json` must inventory every Task 11 proof with:

```text
gate name
claimed scope
real production entrypoint used
layers actually executed
layers intentionally bypassed
test files
fixture files
case / trajectory / turn / state-edge counts
```

It must fail if an expected-contract, direct-router, handcrafted-understanding,
directly seeded state, or prebuilt-SSE gate claims
`production_path_from_turn_meaning` coverage.
The audit is generated from the Task 11 Files block before the candidate
manifest. `prepare-manifest` then imports every discovered fixture dependency
into a distinct `fixture_paths` list and the protected payload. Tests that read
historical output under an excluded audit directory are not eligible proof;
move the deterministic input to `tests/fixtures/guide/` or remove that test
from the Task 11 gate.

Specifically, migrate the deterministic rows currently consumed from
`docs/audits/semantic-turn-meaning/fixture_review_v1.jsonl` into
`tests/fixtures/guide/intent/turn_meaning_gate_review_v1.jsonl`, update the
test to read the new fixture, and restore the historical audit artifact to its
pre-Task-11 bytes. Historical audit output is neither a test input nor a Task
11 staged change.

The seven desktop/mobile SSE fixtures remain valid frontend-only evidence.
They must never satisfy the production-path matrix requirement.

Before another paid smoke, all bounded trajectories must complete once through
the zero-provider production-path harness. Paid smoke remains first-failure
and fail-fast, but it may not be used to discover deterministic cross-state
failures that this matrix can exercise locally.

Minimum production-path coverage is fail-closed:

```text
expected_contract_case_count = 128
actual_equivalence_case_count = 128
actual_equivalence_failure_count = 0
trajectory_count >= 12
stateful_turn_count >= 48
turn_count = actual_equivalence_case_count + stateful_turn_count
required_state_edge_count >= 40
state_edge_count = required_state_edge_count
bounded_turn_count = 9
bounded_failure_count = 0
```

The checked-in fixture declares the required valid state edges. The runner
must reject duplicate IDs, missing required edges, caller-supplied pass flags,
or a requirement set below these minimums.

Run all affected zero-API tests, the production-path matrix, and the network
guard in one clean local pass, then rerun the seven fixture trajectories on
desktop and mobile. If any Step 4.5 or 4.6 item is open, Step 5 is forbidden.

Before bounded smoke, the epoch-owned `task11-candidate-manifest.json`
contains:

```text
source_paths
test_paths
tool_paths
plan_paths
fixture_paths
deleted_paths
deleted_base_blob_sha256_by_path
mutable_evidence_paths
excluded_paths
protected_paths
change_paths
candidate_payload_sha256
protected_payload_sha256
```

Every intended existing code, plan, and transitive fixture path appears
exactly once in its typed category. `deleted_paths` is a disjoint tombstone
set: each path must be absent from the worktree, present as a tracked blob at
`candidate_head`, and bound to that blob's SHA-256 in
`deleted_base_blob_sha256_by_path`. `change_paths` is the exact union of
existing intended paths and `deleted_paths`; staged deletion status is checked
later against this set.
`protected_paths` must equal the exact union of `source_paths`, `test_paths`,
`tool_paths`, `plan_paths`, and `fixture_paths`; omission is forbidden. The
candidate manifest contains no generated artifact path and has no staging
precondition. `mutable_evidence_paths` contains only
`smoke-attempt-ledger.json`; it is excluded from payload hashes because the
single locked ledger writer advances it. Readiness records an immutable
`ledger_anchor_revision` and `ledger_anchor_hash`; later verifiers require the
current hash chain to extend that anchor, not equal it. Each attempt context
binds the exact post-allocation revision/hash, and each change manifest binds
the exact final revision/hash it stages.

`task11-candidate-readiness.json` in the same immutable repair epoch is the
bounded-smoke machine gate. It contains:

```text
plan_revision
candidate_head
candidate_payload_sha256
protected_payload_sha256
step_0_passed
step_0_5_passed
step_4_5_passed
step_4_6_passed
affected_zero_api_passed
single_path_architecture_passed
production_path_matrix_passed
desktop_fixture_passed
mobile_fixture_passed
invalid_clarification_count
outbound_network_attempt_count
runtime_process_tree_non_loopback_attempt_count
fixture_browser_non_loopback_attempt_count
fixture_process_tree_non_loopback_attempt_count
ledger_anchor_revision
ledger_anchor_hash
circuit_state
evidence_files
evidence_sha256
```

`build_task11_readiness.py` accepts no caller-supplied pass booleans. It reads
the candidate manifest and these exact generated files:

```text
task11-semantic-matrix-summary.json
task11-zero-api-summary.json
task11-zero-api-network.json
task11-zero-api-runtime-network.json
task11-test-path-audit.json
task11-single-path-architecture.json
task11-production-path-summary.json
task11-independent-audit.json
fixture-browser-desktop/summary.json
fixture-browser-mobile/summary.json
```

It derives every pass field from those files, records each evidence path and
SHA-256, and refuses missing, duplicate, stale, manually summarized, or failing
evidence. The independent audit must record the exact SHA-256 of the candidate
manifest and all pre-audit summaries it reviewed; an audit that omits or
mismatches any reviewed evidence hash is rejected. Readiness requires
`step_4_6_passed=true`, `single_path_architecture_passed=true`,
`production_path_matrix_passed=true`,
`compiler_bypass_count=0`,
`compiler_call_count_violation_count=0`,
`structured_understanding_injection_count=0`,
`direct_router_bypass_count=0`,
`legacy_entrypoint_count=0`,
`router_call_count_violation_count=0`,
`decision_identity_violation_count=0`,
`execution_result_count_violation_count=0`,
`reducer_call_count_violation_count=0`,
`processor_state_write_count=0`,
`event_state_projection_count=0`,
`state_save_count_violation_count=0`,
`outbound_network_attempt_count=0`,
`runtime_process_tree_non_loopback_attempt_count=0`,
`fixture_browser_non_loopback_attempt_count=0`,
`fixture_process_tree_non_loopback_attempt_count=0`, and a measured
`provider_call_count=0`.

#### 4.6.12 Prebuild and freeze all Task 12 execution tools

Task 12 performs release execution only. It may not modify a Task 11 protected
source, test, tool, plan, or fixture before its real calls. Therefore Task 11
must finish, test, and commit all of these release tools and deterministic
inputs:

```text
tests/fixtures/guide/final_release/real_translation_12x4_v5.jsonl
tools/guide_gates/run_final_real_translation.py
tests/guide/tools/test_final_real_translation.py
tools/guide_gates/replay_final_real_backend.py
tests/guide/tools/test_replay_final_real_backend.py
tools/guide_gates/run_final_release_gate.py
tests/guide/tools/test_final_release_gate.py
tools/guide_gates/record_manual_screenshot_review.py
tests/guide/tools/test_record_manual_screenshot_review.py
```

Write RED tests first for:

```text
v5 translation truth requires exact recommendation_mode and basis
backend replay rejects anything other than all 48 captured meanings
release aggregation rejects every nonzero mainline failure counter
manual screenshot review requires exactly fourteen unique viewport/mode rows
manual screenshot review rejects artifact/context/hash mismatches
create-seal binds the parent evidence commit and exact release context
verify-seal rejects wrong ancestry, dirty protected paths, or plan/hash drift
release evidence manifest is derived from context indexes and exact hashes
release evidence staging rejects missing, extra, or wrong-status paths
post-real closure verifier permits only declared plan/evidence transitions
seal-commit rejects null, unknown, non-ancestor, wrong-manifest, existing
  output, or protected-path-drifted task11_commit
```

Create the v5 fixture from v4 without changing user text. Extend
`FinalTranslationTurn` and row evaluation with exact expected recommendation
mode and basis. Implement backend replay with an injected captured-meaning port
and zero provider calls. Implement the mainline seven-counter aggregate,
strict fourteen-row manual screenshot recorder, and `create-seal` /
`verify-seal` commands. These tests use only local fixtures and temporary
repositories. `seal-commit` also inventories every tracked or non-ignored
untracked file under `app/`, `tools/`, and `tests/`, plus both release plans,
and stores one `release_execution_tree_sha256`. Its verifier rejects any
addition, deletion, or byte drift in that complete inventory. The release
gate's `build-evidence-manifest` and `verify-evidence-staging` subcommands are
also complete here. Task 11 makes no Task 12 real call.

The no-sentence-patch gate is AST-based, not substring-based. It rejects
catalog-ID literals in control-flow comparisons, membership tests, dispatch
tables, or raw-text regex/literal branches, and rejects output-sentence
replacement branches. It allows ordinary identifier-to-identifier binding
checks such as `item.product_id == product_id`. Parameterized positive and
negative tests cover equality in both operand orders, membership, numeric and
string literals, aliases, comprehensions, and helper calls.

Run:

```bash
PYTHONPATH=. .venv/bin/pytest -q \
  tests/guide/tools/test_final_real_translation.py \
  tests/guide/tools/test_replay_final_real_backend.py \
  tests/guide/tools/test_final_release_gate.py \
  tests/guide/tools/test_record_manual_screenshot_review.py \
  tests/guide/tools/test_build_task11_readiness.py \
  tests/guide/tools/test_no_sentence_patch.py
```

Expected: PASS before repair-epoch-08 is generated. Any Task 12 source or tool
change after the Task 11 commit invalidates the seal and requires a new
Task 11 revision; Task 12 may only execute these committed tools.

#### 4.6.13 Rebuild all authority as repair-epoch-08

No r1-r4 readiness, root-level readiness, earlier repair epoch, aggregate
pytest count, or frontend-only fixture result can authorize the next smoke.
After 4.6.0-4.6.12 are green, create a new immutable
`repair-epoch-08/` evidence directory. This epoch is reserved by this plan.
Every epoch-artifact writer rejects an existing target file. The separately
declared append-only attempt ledger changes only through its locked writer. An
interrupted run may continue only by generating missing artifacts after
revalidating all existing hashes; it may not overwrite them. Once an attempt
context references this epoch, any repair requires a new plan revision and a
newly named epoch.

Before generating evidence, run a deletion audit that fails on any production
reference to:

```text
GUIDE_UNIFIED_ROUTER_ENABLED
_meaning_from_compilation
_route_for_responsibility
_ensure_route_decision
_PublicEventStateTransaction
_focus_state_from_public_events
_attach_image_routing_evidence
bind_execution_profile_owner
thread-local route/decision transport
processor route_unified_turn calls
processor conversation-state save calls
adapter decision_for_responsibility calls
source-dependent processor-registry replacement
session/version-derived request_id or turn_id
post-CAS SSE encoding or terminal mutation
```

The same deletion audit fails until these compatibility surfaces are gone:

```text
ChatStreamRequest.image_results / image_context / images
ChatOwner / classify_chat_owner
processor optional standard_processor delegation
tuple-returning translation adapter
understand_text and ParallelUnderstanding production-module test helpers
GuideOrchestrator legacy protocol
consultation_planning dead module
legacy CopywriterDraft summary_copy/product_copy/closing_copy shape
legacy consultation observation union outside a one-way state migration
unreferenced unified_router_* JSONL and manifest fixtures
```

Historical state compatibility is permitted only in a named
`migrate_legacy_*` adapter that outputs the current strict slot schema. It may
not leak legacy fields into current application/domain contracts.

Generate the architecture report before any other epoch evidence:

```bash
PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/check_single_path_architecture.py \
  --repo-root "$PWD" \
  --output docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-single-path-architecture.json
```

It must be derived from the current AST/import graph and runtime boundary
probes, contain no caller-supplied pass fields, list every inspected module and
forbidden edge, and finish with zero production bridge violations.

Then run focused red/green tests for each substep, the complete affected
zero-API suite, both state backends, the HTTP production-path matrix, and the
desktop/mobile frontend fixtures. A broad legacy suite may be reported
separately, but failures in obsolete direct-mainline tests must be resolved by
deleting or reclassifying those tests, never by restoring the old production
path.

Generate the repair-epoch-08 manifest and pre-audit machine evidence:

```bash
PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/build_task11_readiness.py audit-test-paths \
  --plan docs/superpowers/plans/2026-08-21-guide-mainline-contract-closure.md \
  --output docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-test-path-audit.json

PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/build_task11_readiness.py prepare-manifest \
  --plan docs/superpowers/plans/2026-08-21-guide-mainline-contract-closure.md \
  --test-path-audit docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-test-path-audit.json \
  --manifest docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-candidate-manifest.json

PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/run_task11_production_path_matrix.py \
  --manifest docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-candidate-manifest.json \
  --cases tests/fixtures/guide/intent/task11_production_path_matrix_v1.jsonl \
  --output docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-production-path-summary.json

PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/build_task11_readiness.py prepare-evidence \
  --manifest docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-candidate-manifest.json \
  --semantic-summary-output docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-semantic-matrix-summary.json \
  --zero-api-summary-output docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-zero-api-summary.json \
  --network-report-output docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-zero-api-network.json \
  --single-path-architecture docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-single-path-architecture.json \
  --test-path-audit docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-test-path-audit.json \
  --production-path-summary docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-production-path-summary.json
```

`prepare-evidence` must run pytest with
`-p tools.guide_gates.zero_api_network_guard`. The plugin loads before test
collection, denies non-loopback DNS/socket/HTTP/SDK calls, instruments the
provider request boundary, and atomically writes the network report consumed
by `task11-zero-api-summary.json`. The readiness and independent audit bind
both files by SHA-256. Missing guard activation, missing report, or a
caller-authored provider count fails the command.

Run the fixture browser gate separately against the zero-API local runtime:

```bash
# Dedicated terminal; this wrapper installs the same network/process guard
# before importing the application and writes its verified identity file.
PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/run_zero_api_runtime.py \
  --manifest docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-candidate-manifest.json \
  --host 127.0.0.1 \
  --port 8820 \
  --state-dir /tmp/xiaoro-task11-r5-fixture-state \
  --ready-file /tmp/xiaoro-task11-r5-fixture-runtime.json \
  --network-report docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-zero-api-runtime-network.json

# Separate terminal after the ready file validates the candidate manifest,
# code revision, protected payload, process identity, and runtime nonce. Each
# invocation obtains and consumes a fresh challenge. Fixture evidence precedes
# candidate readiness and therefore cannot contain a readiness hash.
PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/run_mainline_contract_browser_audit.py \
  --base-url http://127.0.0.1:8820 \
  --runtime-identity /tmp/xiaoro-task11-r5-fixture-runtime.json \
  --trajectory-set fixture \
  --viewport desktop \
  --output docs/audits/final-release/mainline-contract-closure/repair-epoch-08/fixture-browser-desktop

PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/run_mainline_contract_browser_audit.py \
  --base-url http://127.0.0.1:8820 \
  --runtime-identity /tmp/xiaoro-task11-r5-fixture-runtime.json \
  --trajectory-set fixture \
  --viewport mobile \
  --output docs/audits/final-release/mainline-contract-closure/repair-epoch-08/fixture-browser-mobile
```

Stop the fixture runtime after both browser invocations. The runtime wrapper
must then atomically finalize `task11-zero-api-runtime-network.json` from its
own OS-level process-tree audit. It records attempted and denied DNS, TCP, UDP,
QUIC, provider-boundary, and child-process escape operations for the runtime
PID tree. Missing shutdown finalization, an unaudited descendant, or any
non-loopback attempt fails the evidence.

The two Task 11 `Generate` directory actions cover every per-turn
`request.json`, raw `stream.sse`, presentation contract, DOM snapshot,
screenshot, console log, network log, sandbox audit, and summary. Each summary
is an exclusive machine index of all other files below its directory with
SHA-256; it never attempts to hash itself. Readiness and the change manifest
hash the summary file from outside that directory index. The change-manifest
writer expands those indexes to explicit staged paths and rejects an unindexed
file or a directory-only staging entry.

Each fixture summary must include its runtime-identity digest, consumed
challenge digest, OS sandbox identity/audit digest, browser request count,
process-tree non-loopback-attempt count, and browser-observed non-loopback
attempt count. The process-tree count is derived from the sandbox/kernel audit;
the browser count is derived independently from raw Playwright/CDP request
logs. Neither may be copied from expected fixtures.

Only after those artifacts exist, run a second, mechanically independent audit
implementation. It shares no policy tables, AST helpers, summary parser, or
pass/fail functions with `check_single_path_architecture.py`,
`build_task11_readiness.py`, or the production-path runner. Its mutation corpus
deletes or corrupts each required input and injects one example of every
forbidden bridge, bypass, stale hash, unmeasured counter, slot alias, extra
production root, and post-CAS encoder. Every mutation must be detected.

The audit derives its scope and verdict itself. It accepts no finding list,
reviewer identity, pass boolean, expected hash, or caller-authored count. It
inspects the production diff, semantic and zero-API summaries, single-path
architecture report, forbidden-symbol deletion results, test-path claims,
network reports, per-turn production traces, emitted-byte identity, both state
backends, and both fixture browser directories. It computes the manifest,
diff, and every reviewed evidence SHA-256, then exclusively creates the
epoch-owned audit:

```bash
PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/run_task11_independent_audit.py \
  --repo-root "$PWD" \
  --manifest docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-candidate-manifest.json \
  --semantic-summary docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-semantic-matrix-summary.json \
  --zero-api-summary docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-zero-api-summary.json \
  --single-path-architecture docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-single-path-architecture.json \
  --test-path-audit docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-test-path-audit.json \
  --network-report docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-zero-api-network.json \
  --runtime-network-report docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-zero-api-runtime-network.json \
  --production-path-summary docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-production-path-summary.json \
  --desktop-summary docs/audits/final-release/mainline-contract-closure/repair-epoch-08/fixture-browser-desktop/summary.json \
  --mobile-summary docs/audits/final-release/mainline-contract-closure/repair-epoch-08/fixture-browser-mobile/summary.json \
  --output docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-independent-audit.json
```

After this machine audit passes, a fresh read-only reviewer examines the same
hash-bound bundle for design blind spots. That review is a governance stop:
any P0/P1 finding reopens Task 11. It is deliberately not accepted as a JSON
authorization input because repository code cannot authenticate reviewer
independence; only the independently implemented mechanical report above is
consumed by readiness.

Then seal readiness:

```bash
PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/build_task11_readiness.py seal-readiness \
  --manifest docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-candidate-manifest.json \
  --readiness docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-candidate-readiness.json \
  --semantic-summary docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-semantic-matrix-summary.json \
  --zero-api-summary docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-zero-api-summary.json \
  --network-report docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-zero-api-network.json \
  --runtime-network-report docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-zero-api-runtime-network.json \
  --single-path-architecture docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-single-path-architecture.json \
  --test-path-audit docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-test-path-audit.json \
  --production-path-summary docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-production-path-summary.json \
  --independent-audit docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-independent-audit.json \
  --desktop-summary docs/audits/final-release/mainline-contract-closure/repair-epoch-08/fixture-browser-desktop/summary.json \
  --mobile-summary docs/audits/final-release/mainline-contract-closure/repair-epoch-08/fixture-browser-mobile/summary.json \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json
```

`audit-test-paths` parses the Task 11 Files block and discovers transitive
fixtures. The parser is action-aware: `Delete` rows become tombstones and are
never collected as tests, while future `Create` rows must exist by the time
the audit runs. `prepare-manifest` rejects any relevant changed or untracked
path or fixture dependency missing from the protected union, deletion
tombstones, mutable-ledger declaration, or generated-evidence declaration.
`prepare-evidence`
accepts the immutable manifest and already generated architecture, test-path,
and production-path summaries, then runs only the reviewed network-guarded
zero-API commands. It cannot create, overwrite, or accept an
independent-audit or readiness path.
`seal-readiness` runs no tests and accepts no pass/fail flags; it only verifies
and binds the already generated evidence plus ledger state.

Once an authorization has been allocated, its readiness and every referenced
evidence file are immutable. A repair after a failed attempt must generate a
new evidence set under a new `repair-epoch-XX/` directory and authorize from
that new readiness path. Never overwrite files referenced by an existing
attempt context.

Both payload hashes use one canonical algorithm over sorted repository-relative
paths and raw file bytes:

```text
sha256(
  for each path:
    utf8_byte_length(path) + ":" + path
    + raw_byte_length(content) + ":" + content
)
```

`candidate_payload_sha256` covers every existing path in `source_paths`,
`test_paths`, `tool_paths`, `plan_paths`, and `fixture_paths`, whether tracked
or untracked. The manifest digest additionally binds the sorted deletion
tombstones and their `candidate_head` blob hashes. A deleted path is validated
as absent rather than read as a current file. Symlinks, unexpected missing
paths, paths outside the repository, and files present in `excluded_paths` are
rejected. Git diff output, mtimes, generated audit artifacts, and the mutable
ledger are never candidate-payload inputs.

Before bounded smoke, the runner verifies `candidate_head == HEAD` and
recomputes both payload hashes from actual bytes.

Before sending its first request,
`run_mainline_contract_browser_audit.py --trajectory-set bounded` calls the
shared verifier. The verifier ignores stored pass booleans as authority:
it re-derives a complete readiness object from the manifest, raw summary
files, and current immutable bytes, then requires byte-for-byte equality with
the saved readiness for those immutable fields. The mutable ledger is checked
separately: its append-only hash chain must extend the sealed anchor, the
context's allocation revision/hash must exist exactly once in that chain, and
no illegal transition may occur. The verifier checks
`invalid_clarification_count == 0`, verifies the circuit is closed, and
atomically consumes the matching ledger attempt allocation and one-time
authorization. Missing, stale, mismatched, edited, forked, or already-consumed
evidence exits before any API request.

Step 4.6 is complete only when:

```text
all 4.6.0-4.6.13 tests and deletion gates pass
the AST/import-graph gate reports zero production bridge violations
all anti-patch violation codes in Step 4.6.0a have zero findings
no production result wrapper, source-dependent registry, synthetic identity,
  post-router raw parser, adapter business projection, or post-CAS encoder
  remains reachable or dormant
every test-only migration seam is physically under tests/, absent from
  production imports/composition, and excluded from authorizing evidence
the production path begins only at HTTP plus frozen TurnMeaning provider
every matrix row records one compiler, one router, one selected processor,
  one result, one reducer, and one state save for an accepted turn;
  pre-decision failures record zero
all bypass and duplicate-owner counters are zero
the network guard reports zero attempted non-loopback calls
provider_call_count is measured zero
desktop and mobile frontend fixture gates pass as frontend-only evidence
the independent audit has no P0/P1 finding
repair-epoch-08 readiness is sealed from raw hashed evidence
```

After bounded smoke passes, Step 6 creates the epoch-owned
`task11-change-manifest.json`. This separate post-smoke manifest contains the
exact `change_paths` including deletion tombstones, approved bounded artifacts,
candidate manifest, candidate readiness, final ledger revision/hash, and
`staged_diff_sha256`. It alone has staging requirements; changing it cannot
invalidate the completed bounded-smoke readiness.

Its `approved_change_paths` is the exact union of candidate `change_paths`,
enumerated epoch evidence, the successful bounded-attempt files, the candidate
manifest/readiness, and the ledger. Wildcard declarations are resolved to
explicit paths before the draft is written. The finalizer compares staged
name/status rows, not names alone, so a required deletion cannot be replaced
by a recreated empty file.

- [ ] **Step 5: Run one bounded real smoke only after Steps 0-4.6 pass**

Run exactly these three trajectories against production-equivalent configuration:

```text
text:
  "给我推荐一款 900 到 1100 元的精华，我是油敏肌，换季容易泛红"
  -> "第二款的质地适合什么肤质？" is not used here because fit returns
     one item

text multi-turn:
  "给我推荐 900 到 1100 元的精华"
  -> "第二款的质地适合什么肤质？"
  -> "我现在有点换季泛红，T 区出油，我可能是什么肤质？"
  -> "确认"
  -> "回到刚才的推荐，第一款和第二款哪个更适合我的肤质？"

image:
  verified product-38 index control image
  -> "给我找两款相似的，我最近换季泛红，T 区出油。"
  -> "图片里的 B5 和第一款哪个更适合我的肤质？"
```

Allocate the immutable attempt context first:

```bash
AUTHORIZATION_ID="$(
  PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/attempt_ledger.py authorize \
  --phase bounded \
  --readiness docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-candidate-readiness.json \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json \
  --independent-audit docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-independent-audit.json
)"
test -n "$AUTHORIZATION_ID"
PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/attempt_ledger.py allocate \
  --phase bounded \
  --authorization-id "$AUTHORIZATION_ID" \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json \
  --readiness docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-candidate-readiness.json \
  --output-root docs/audits/final-release/mainline-contract-closure \
  > /tmp/xiaoro-task11-r5-bounded-context.path
test -s /tmp/xiaoro-task11-r5-bounded-context.path
```

Start the runtime in a dedicated terminal with that exact context:

```bash
ATTEMPT_CONTEXT="$(cat /tmp/xiaoro-task11-r5-bounded-context.path)"
test -n "$ATTEMPT_CONTEXT"
GUIDE_LLM_API_KEY="$(cat /Users/bytedance/Desktop/deepseek-key.txt)" \
GUIDE_LLM_BASE_URL=https://api.deepseek.com \
GUIDE_LLM_MODEL=deepseek-v4-pro \
GUIDE_LLM_FORMAT_REPAIR_ATTEMPTS=0 \
GUIDE_COPY_LLM_API_KEY="$(cat /Users/bytedance/Desktop/deepseek-key.txt)" \
GUIDE_COPY_LLM_BASE_URL=https://api.deepseek.com \
GUIDE_COPY_LLM_MODEL=deepseek-v4-pro \
PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/run_bound_runtime.py \
  --attempt-context "$ATTEMPT_CONTEXT" \
  --host 127.0.0.1 \
  --port 8821 \
  --state-dir /tmp/xiaoro-mainline-bounded-state
```

Then run the browser audit. It verifies the runtime identity against the same
attempt context before consuming authorization or sending the first business
request:

```bash
ATTEMPT_CONTEXT="$(cat /tmp/xiaoro-task11-r5-bounded-context.path)"
test -n "$ATTEMPT_CONTEXT"
PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/run_mainline_contract_browser_audit.py \
  --base-url http://127.0.0.1:8821 \
  --trajectory-set bounded \
  --viewport desktop \
  --attempt-context "$ATTEMPT_CONTEXT"
```

Stop immediately if any turn has fallback, missing contract, invalid
clarification truth, bad DOM audit, or image identity mismatch. Save the
evidence bundle and return to the
earliest failing owner; do not alter Prompt or make another real call. Apply
the circuit breaker in Section 0.8. A repeated failure at the same owner ends
the smoke session. Local proof and independent audit permit only the one-time
authorized attempt described above; another same-owner failure locks the plan
revision.

- [ ] **Step 6: Commit**

Resolve the unique successful bounded context and generate the separate
post-smoke manifest:

```bash
ATTEMPT_CONTEXT="$(
  PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/attempt_ledger.py latest \
  --phase bounded \
  --result passed \
  --readiness docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-candidate-readiness.json \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json
)"
test -n "$ATTEMPT_CONTEXT"
PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/build_task11_readiness.py build-change-manifest \
  --candidate-manifest docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-candidate-manifest.json \
  --candidate-readiness docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-candidate-readiness.json \
  --attempt-context "$ATTEMPT_CONTEXT" \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json \
  --output /tmp/xiaoro-task11-r5-change-manifest-draft.json
```

Before staging:

```text
1. Remove unapproved transient `.dbg`, `.tmp-*`, debug-note, screenshot, and
   superseded generated-audit paths after confirming none is required
   evidence. Restore tracked historical audit outputs to their pre-Task-11
   bytes after moving any deterministic test input into `tests/fixtures/`.
2. Add every intended non-manifest file and deletion by exact path.
3. Compare staged name/status rows with the draft's exact
   `approved_change_paths`; every tombstone must have status `D`.
4. Run the exact command below. The tool validates the immutable candidate
   evidence plus the untracked draft, requires the exact approved staged path
   and deletion-status set, computes
   `staged_diff_sha256` over
   `git diff --cached --binary -- <approved paths>` while explicitly excluding
   task11-change-manifest.json from the hash input, and exclusively creates the
   final epoch-owned manifest. In-place draft mutation, caller-supplied hashes,
   and direct manifest edits are forbidden.
5. Stage the finalized manifest by its exact path.
6. Recheck that `git diff --cached --name-only` equals the approved path set
   plus the manifest itself.
7. Reject the commit if any intended Task 11 source or deletion remains
   unstaged.
8. Reject the commit if demo.html, recording-v1, .dbg, .tmp-*, debug notes,
   screenshots outside the approved bundle, or historical audits are staged.
9. Require `git status --short` to contain no unapproved untracked or modified
   residue; excluding debris from the commit is not repository cleanup.
10. Review the staged diff, not only the worktree diff.
```

```bash
PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/build_task11_readiness.py finalize-change-manifest \
  --draft /tmp/xiaoro-task11-r5-change-manifest-draft.json \
  --candidate-manifest docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-candidate-manifest.json \
  --candidate-readiness docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-candidate-readiness.json \
  --output docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-change-manifest.json
```

The former three-file `git add` command is intentionally removed because it
would omit semantic, state, provenance, attribution, and gate changes. Write
the final exact-path staging command only after Steps 4.5 and 4.6 stabilize the
manifest. Directory-level staging remains forbidden.

Commit only after the bounded smoke passes:

```bash
git commit -m "test(guide): bind real SSE contracts to browser evidence"
```

### Task 12: Run final release gates once, only after bounded smoke is clean

**Status:** Blocked. Do not begin Task 12 until the immutable Task 11 readiness,
successful bounded attempt, final change manifest, and exact Task 11 commit all
exist and validate. This machine precondition, not a deferred checkbox edit,
defines Task 11 completion for entry into Task 12.

**Files:**
- Modify: `docs/superpowers/plans/2026-08-20-final-guide-release-closure.md`
- Modify: `docs/superpowers/plans/2026-08-21-guide-mainline-contract-closure.md`
- Modify: `docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/task11-release-readiness.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/release-evidence-manifest.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/release-seal.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/release-attempt-*/focused.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/release-attempt-*/real-translation/`
- Generate: `docs/audits/final-release/mainline-contract-closure/release-attempt-*/real-backend/`
- Generate: `docs/audits/final-release/mainline-contract-closure/release-attempt-*/mainline-browser/`
- Generate: `docs/audits/final-release/mainline-contract-closure/release-attempt-*/browser-desktop/`
- Generate: `docs/audits/final-release/mainline-contract-closure/release-attempt-*/browser-mobile/`
- Generate: `docs/audits/final-release/mainline-contract-closure/release-attempt-*/manual-screenshot-review.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/release-attempt-*/release-summary.json`

The two overlapping Task 11 paths are intentional and non-ambiguous:
`smoke-attempt-ledger.json` is the declared append-only mutable evidence path,
and this plan is not edited until all Task 12 real-call phases finish. Every
source, test, tool, and fixture used by Task 12 was frozen in Task 11.

- [ ] **Step 1: Seal and verify the exact Task 11 commit**

Task 12 executes the already committed release tools from Step 4.6.12; it does
not add or modify source, tests, tools, or fixtures before real calls. Create
the release readiness exactly once. Manual JSON editing is forbidden:

```bash
PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/build_task11_readiness.py seal-commit \
  --manifest docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-change-manifest.json \
  --candidate-readiness docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-candidate-readiness.json \
  --release-readiness docs/audits/final-release/mainline-contract-closure/task11-release-readiness.json \
  --task11-commit "$(git rev-parse HEAD)"
```

The command revalidates the manifest and protected payload before exclusively
creating the readiness file and rejects an existing target. The Task 11
zero-API suite has already proved that it rejects a null, unknown,
non-ancestor, wrong-manifest, or protected-path-drifted `task11_commit`;
Task 12 only executes the sealed command.

`task11-release-readiness.json` is derived from the committed
`task11-change-manifest.json` and the exact bytes stored in `task11_commit`.
It does not reuse the pre-smoke candidate payload hash. It records the final
Task 11 protected path set and protected payload hash. It also inventories all
tracked and non-ignored untracked regular files under `app/`, `tools/`, and
`tests/`, plus both release plans, and records one
`release_execution_tree_sha256`. Before every Task 12 real call, the shared
verifier requires `task11_commit` to equal `HEAD`, the current bytes of every
protected path to match, and the complete execution-tree inventory and hash to
match. Unknown files under those roots fail even when they were absent from the
Task 11 manifest. Any source, test, tool, fixture, or plan edit before the
real-call phases invalidates the seal and returns work to Task 11 under a new
plan revision.

- [ ] **Step 2: Reverify the committed zero-API release tools**

Run:

```bash
git diff --check
PYTHONPATH=. .venv/bin/python -m compileall -q app tools tests
PYTHONPATH=. .venv/bin/pytest -q \
  tests/guide/presentation \
  tests/guide/application/test_text_presentation_integration.py \
  tests/guide/application/test_image_recommendation_flow.py \
  tests/guide/runtime/test_frontend_presentation_stream.py \
  tests/guide/runtime/test_frontend_card_binding.py \
  tests/guide/tools/test_run_mainline_contract_browser_audit.py \
  tests/guide/tools/test_no_sentence_patch.py \
  tests/guide/tools/test_final_real_translation.py \
  tests/guide/tools/test_replay_final_real_backend.py \
  tests/guide/tools/test_final_release_gate.py \
  tests/guide/tools/test_record_manual_screenshot_review.py

PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/build_task11_readiness.py verify-release-readiness \
  --readiness docs/audits/final-release/mainline-contract-closure/task11-release-readiness.json \
  --require-head "$(git rev-parse HEAD)"
```

Expected: PASS. The final command mechanically proves the test run made no
tracked or non-ignored execution-tree change. A test/tool failure or tree drift
returns to Task 11; Task 12 may not repair committed execution tooling in
place. Every Task 12 runner in Steps 3-8 invokes this `phase-execution`
verifier before doing work. It requires `HEAD == task11_commit` and exact
execution-tree bytes.

- [ ] **Step 3: Generate the zero-API focused summary**

```bash
AUTHORIZATION_ID="$(
  PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/attempt_ledger.py authorize \
  --phase translation \
  --readiness docs/audits/final-release/mainline-contract-closure/task11-release-readiness.json \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json \
  --independent-audit docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-independent-audit.json
)"
test -n "$AUTHORIZATION_ID"
ATTEMPT_CONTEXT="$(
  PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/attempt_ledger.py allocate \
  --phase translation \
  --authorization-id "$AUTHORIZATION_ID" \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json \
  --readiness docs/audits/final-release/mainline-contract-closure/task11-release-readiness.json \
  --output-root docs/audits/final-release/mainline-contract-closure
)"
test -n "$ATTEMPT_CONTEXT"

MATRIX_PARENT="$(mktemp -d /tmp/xiaoro-mainline-matrix.XXXXXX)"
MATRIX_DIR="$MATRIX_PARENT/matrix"
PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/build_responsibility_matrix.py \
  --output-dir "$MATRIX_DIR"

PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/run_final_release_gate.py \
  --responsibility-matrix "$MATRIX_DIR" \
  --attempt-context "$ATTEMPT_CONTEXT" \
  --phase focused
```

Expected: `passed=true`, with zero legal-row, binding, processor,
presentation, and forbidden-public-text failures. Only the translation phase
is authorized at this point; no browser authorization exists.

- [ ] **Step 4: Run one new 48-turn DeepSeek translation gate**

Only after the bounded smoke artifacts have:

```text
0 fallback turns
0 contract violations
0 DOM violations
0 wrong product bindings
0 unaligned public price/spec pairs
0 invalid clarifications
```

Run exactly one new real batch:

```bash
ATTEMPT_CONTEXT="$(
  PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/attempt_ledger.py current \
  --phase translation \
  --readiness docs/audits/final-release/mainline-contract-closure/task11-release-readiness.json \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json
)"
test -n "$ATTEMPT_CONTEXT"
PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/run_final_real_translation.py \
  --cases tests/fixtures/guide/final_release/real_translation_12x4_v5.jsonl \
  --attempt-context "$ATTEMPT_CONTEXT" \
  --phase translation \
  --key-path /Users/bytedance/Desktop/deepseek-key.txt \
  --model deepseek-v4-pro
```

If any serious failure occurs, stop this batch, record its earliest failure
owner and evidence directory in the persistent ledger, and stop Task 12. Do
not start another 48-turn batch under the same plan revision. Return to the
earliest shared owner, establish the local reproduction and focused regression,
and request user review as required by Section 0.8. Only an approved new plan
revision may allocate a new release attempt and unseen 48-turn batch.

- [ ] **Step 5: Replay the same real meanings through the full backend**

`replay_final_real_backend.py` resolves the successful 48-row translation
result and backend output directory from the immutable attempt context,
injects each captured `TurnMeaning` into the real orchestrator with the sealed
trajectory context, and records the full typed SSE. It makes zero provider
calls and disables the Copywriter only for this replay. It must assert:

```text
48 / 48 completed turns
one PresentationContractEvent per non-clarification terminal turn
zero MessageEvent public bodies
zero wrong responsibility, binding, product, price/spec, or section order
zero raw/internal language leaks
```

Run:

```bash
ATTEMPT_CONTEXT="$(
  PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/attempt_ledger.py latest \
  --phase translation \
  --result passed \
  --readiness docs/audits/final-release/mainline-contract-closure/task11-release-readiness.json \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json
)"
test -n "$ATTEMPT_CONTEXT"
PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/replay_final_real_backend.py \
  --cases tests/fixtures/guide/final_release/real_translation_12x4_v5.jsonl \
  --attempt-context "$ATTEMPT_CONTEXT" \
  --phase backend
```

- [ ] **Step 6: Run desktop and mobile production browser trajectories**

Run:

```bash
PARENT_CONTEXT="$(
  PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/attempt_ledger.py latest \
  --phase translation \
  --result passed \
  --readiness docs/audits/final-release/mainline-contract-closure/task11-release-readiness.json \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json
)"
test -n "$PARENT_CONTEXT"
AUTHORIZATION_ID="$(
  PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/attempt_ledger.py authorize \
  --phase browser \
  --readiness docs/audits/final-release/mainline-contract-closure/task11-release-readiness.json \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json \
  --independent-audit docs/audits/final-release/mainline-contract-closure/repair-epoch-08/task11-independent-audit.json
)"
test -n "$AUTHORIZATION_ID"
PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/attempt_ledger.py allocate-child \
  --phase browser \
  --authorization-id "$AUTHORIZATION_ID" \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json \
  --readiness docs/audits/final-release/mainline-contract-closure/task11-release-readiness.json \
  --output-root docs/audits/final-release/mainline-contract-closure \
  --parent-context "$PARENT_CONTEXT" \
  --require-summary-phase backend \
  --require-summary-result passed \
  > /tmp/xiaoro-task12-r5-browser-context.path
test -s /tmp/xiaoro-task12-r5-browser-context.path
```

Restart the production-equivalent runtime and bind it to the browser attempt
context; reusing the earlier bounded server is forbidden:

```bash
BROWSER_CONTEXT="$(cat /tmp/xiaoro-task12-r5-browser-context.path)"
test -n "$BROWSER_CONTEXT"
GUIDE_LLM_API_KEY="$(cat /Users/bytedance/Desktop/deepseek-key.txt)" \
GUIDE_LLM_BASE_URL=https://api.deepseek.com \
GUIDE_LLM_MODEL=deepseek-v4-pro \
GUIDE_LLM_FORMAT_REPAIR_ATTEMPTS=0 \
GUIDE_COPY_LLM_API_KEY="$(cat /Users/bytedance/Desktop/deepseek-key.txt)" \
GUIDE_COPY_LLM_BASE_URL=https://api.deepseek.com \
GUIDE_COPY_LLM_MODEL=deepseek-v4-pro \
PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/run_bound_runtime.py \
  --attempt-context "$BROWSER_CONTEXT" \
  --host 127.0.0.1 \
  --port 8821 \
  --state-dir /tmp/xiaoro-mainline-release-state
```

Run the browser audit only after its health probe matches the attempt-bound
runtime identity:

```bash
BROWSER_CONTEXT="$(cat /tmp/xiaoro-task12-r5-browser-context.path)"
test -n "$BROWSER_CONTEXT"
PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/run_mainline_contract_browser_audit.py \
  --base-url http://127.0.0.1:8821 \
  --trajectory-set release \
  --viewport all \
  --attempt-context "$BROWSER_CONTEXT"
```

Expected: every terminal turn has a valid artifact directory described in
Section 0.6. `--viewport all` creates `browser-desktop/` and
`browser-mobile/` turn directories plus the context-owned
`mainline-browser/summary.json`.

The summary is the exclusive artifact index for every other file in all three
generated directories. It does not hash itself; the release evidence manifest
hashes the summary externally. The summary records every other
repository-relative file path and SHA-256, rejects
duplicate/missing/unindexed files, and is the sole source used by
`build-evidence-manifest`; a recursive directory listing may validate that
there are no extras but may not add paths to the manifest.

The browser audit writes `summary.json` with these integer counters calculated
from its per-turn contract, DOM, and raw SSE artifacts:

```json
{
  "passed": true,
  "turn_count": 0,
  "serious_failure_count": 0,
  "frontend_contract_violation_count": 0,
  "wrong_binding_count": 0,
  "unaligned_price_specification_count": 0,
  "copywriter_fallback_count": 0,
  "invalid_clarification_count": 0
}
```

- [ ] **Step 7: Manually inspect terminal screenshots**

Inspect one terminal screenshot for each of these modes on desktop and mobile:

```text
explore recommendation
fit recommendation
product knowledge
comparison
image identity
image fit recommendation
image comparison
```

Reject release for overlap, duplicate answer text, repeated card surfaces,
missing Winner, raw internal language, wrong price/spec pair, or a card field
not present in its presentation contract.

Record the review with:

```bash
ATTEMPT_CONTEXT="$(
  PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/attempt_ledger.py latest \
  --phase browser \
  --result passed \
  --readiness docs/audits/final-release/mainline-contract-closure/task11-release-readiness.json \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json
)"
test -n "$ATTEMPT_CONTEXT"
PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/record_manual_screenshot_review.py \
  --attempt-context "$ATTEMPT_CONTEXT"
```

The output contains exactly fourteen unique `(viewport, mode)` rows. Each row
records screenshot SHA-256, presentation-contract SHA-256, reviewer ID,
reviewed-at time, verdict, and controlled issue codes. The tool verifies every
referenced artifact belongs to the same attempt context. Unknown, duplicate,
missing, or failed rows make the review fail closed.

- [ ] **Step 8: Aggregate the mainline release result**

A release passes only when the existing focused, translation, and backend
thresholds pass, the mainline summary has all seven counters above at zero
except `turn_count`, which must be at least fourteen, and the context-owned
manual screenshot review has:

```text
manual_screenshot_review_count = 14
manual_screenshot_failure_count = 0
```

Run:

```bash
ATTEMPT_CONTEXT="$(
  PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/attempt_ledger.py latest \
  --phase browser \
  --result passed \
  --readiness docs/audits/final-release/mainline-contract-closure/task11-release-readiness.json \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json
)"
test -n "$ATTEMPT_CONTEXT"
PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/run_final_release_gate.py \
  --attempt-context "$ATTEMPT_CONTEXT" \
  --phase aggregate
```

- [ ] **Step 9: Update both final plans and commit release evidence**

Append a dated closure note to
`docs/superpowers/plans/2026-08-20-final-guide-release-closure.md` recording:

```text
recording-v1 frozen
mainline contract plan completed
Task 11 commit
real batch location
browser artifact location
release-summary path and SHA-256
manual-screenshot-review path and SHA-256
serious failure count
go/no-go decision
```

Prepare the release evidence commit first. In that commit, update this current
plan to:

```text
mark Task 11 complete
mark Task 12 Steps 1-8 complete
leave Task 12 Step 9 open
set Release status to READY_TO_SEAL
set Task 11 status to completed
record the exact attempt-context path
record the release-summary path and SHA-256
record the Task 11 commit
```

From this point onward, closure commands use a separate
`post-real-closure` verifier, never the pre-call `phase-execution` verifier.
It requires every Task 12 phase through Step 8 to be terminal and passed,
requires all Task 11 source/test/tool/fixture bytes to remain unchanged, and
permits only the exact two plan edits, append-only ledger advance, sealed
readiness, context-indexed evidence, and manifest/seal outputs declared in the
Task 12 Files block. Before the evidence commit it requires
`HEAD == task11_commit`; after that commit, `create-seal` requires the evidence
commit's parent to equal `task11_commit` and its diff to equal the verified
release manifest. After the seal commit, `verify-seal` requires `HEAD^` to be
that evidence commit and the final commit diff to contain exactly the two plans
and `release-seal.json`.

Commit only after the context-owned `release-summary.json` has:

```json
{
  "passed": true,
  "serious_failure_count": 0,
  "frontend_contract_violation_count": 0,
  "wrong_binding_count": 0,
  "unaligned_price_specification_count": 0,
  "copywriter_fallback_count": 0,
  "invalid_clarification_count": 0,
  "manual_screenshot_review_count": 14,
  "manual_screenshot_failure_count": 0
}
```

Resolve the successful context again, then exclusively create the release
evidence manifest from machine-owned indexes:

```bash
ATTEMPT_CONTEXT="$(
  PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/attempt_ledger.py latest \
  --phase browser \
  --result passed \
  --readiness docs/audits/final-release/mainline-contract-closure/task11-release-readiness.json \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json
)"
test -n "$ATTEMPT_CONTEXT"
PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/run_final_release_gate.py build-evidence-manifest \
  --attempt-context "$ATTEMPT_CONTEXT" \
  --readiness docs/audits/final-release/mainline-contract-closure/task11-release-readiness.json \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json \
  --plan docs/superpowers/plans/2026-08-20-final-guide-release-closure.md \
  --plan docs/superpowers/plans/2026-08-21-guide-mainline-contract-closure.md \
  --output docs/audits/final-release/mainline-contract-closure/release-evidence-manifest.json
```

The writer derives paths from the immutable attempt context and each
phase-owned artifact index; it does not trust a recursive caller-supplied file
list. The manifest records the Task 11 release-readiness hash, Task 11 commit,
attempt-context hash, final ledger revision/hash, both plan hashes, every
artifact path/hash, exact staged name/status rows, and a payload hash that
excludes only the manifest itself. It rejects an existing output, an unknown
file in the context directory, a missing indexed artifact, and any
pre-real-call source/test/tool/fixture delta.

Review the manifest against `git status --short`, then let the prebuilt tool
stage exactly its enumerated paths and verify the index:

```bash
PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/run_final_release_gate.py stage-evidence \
  --manifest docs/audits/final-release/mainline-contract-closure/release-evidence-manifest.json

PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/run_final_release_gate.py verify-evidence-staging \
  --manifest docs/audits/final-release/mainline-contract-closure/release-evidence-manifest.json
```

The staged set includes
`docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json`
and the manifest itself. Directory scans, directory-level `git add`, wildcard
staging, and `find ... | xargs git add` are forbidden.

After reviewing the staged diff:

```bash
git commit -m "test(guide): pass mainline contract release gate"
```

That evidence commit is not yet an official READY state. Capture its hash and
create a seal bound to the successful release context:

```bash
EVIDENCE_COMMIT="$(git rev-parse HEAD)"
ATTEMPT_CONTEXT="$(
  PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/attempt_ledger.py latest \
  --phase browser \
  --result passed \
  --readiness docs/audits/final-release/mainline-contract-closure/task11-release-readiness.json \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json
)"
test -n "$ATTEMPT_CONTEXT"
PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/run_final_release_gate.py create-seal \
  --attempt-context "$ATTEMPT_CONTEXT" \
  --evidence-commit "$EVIDENCE_COMMIT" \
  --manual-screenshot-review-from-context \
  --output docs/audits/final-release/mainline-contract-closure/release-seal.json
```

Then update both plans in one exact staged change:

```text
mark Task 12 Step 9 complete
strike the completed Task 11 and Task 12 headings
set Task 11 status to completed
set Task 12 status to completed
set Release status to READY
record the evidence commit SHA
record the release-summary path and SHA-256
record the manual-screenshot-review path and SHA-256
record the release-seal path and SHA-256
```

Stage only the two plans and `release-seal.json`, review the staged diff, and
create the seal commit:

```bash
git commit -m "chore(guide): seal mainline release"
```

After the commit, run a read-only verification:

```bash
PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/run_final_release_gate.py verify-seal \
  --seal docs/audits/final-release/mainline-contract-closure/release-seal.json \
  --head "$(git rev-parse HEAD)" \
  --expected-evidence-commit "$(git rev-parse HEAD^)"
```

The verifier requires the seal to reference the parent evidence commit, the
committed current plan at `HEAD` to say `Release status: READY`, and both plans
to contain the same evidence commit and release summary hashes. A dirty
worktree claiming READY is never release evidence.

## 3. Plan Self-Review

### 3.1 Coverage

| Requirement | Task |
| --- | --- |
| Freeze recording demo | Task 1 |
| Explore vs fit recommendation | Task 2 |
| One public presentation owner | Task 3 |
| Price/spec/name binding | Task 4 |
| A/B cabinet public projection | Tasks 5-6 |
| Card-below-detail field selection | Task 5 |
| User-owned comparison dimensions and optional price | Task 7 |
| Image OCR/vector/fusion root-cause trace | Task 8 |
| Image candidate ownership and fit winner | Tasks 2 and 8 |
| Tag/fact-ID model gate | Task 9 |
| Semantic equivalence matrix | Task 10 |
| One production ingress and one compiler boundary | Task 11 Steps 4.6.1-4.6.2 |
| One router and one executable decision | Task 11 Steps 4.6.3-4.6.4 |
| ExecutionResult plus typed StateDelta | Task 11 Steps 4.6.5-4.6.6 |
| One reducer and one atomic CAS save | Task 11 Step 4.6.7 |
| One-way SSE serialization | Task 11 Step 4.6.8 |
| Test claim classification | Task 11 Step 4.6.9 |
| No production migration bridge at any intermediate GREEN | Section 0.5 Rules 37-45 and Task 11 Step 4.6.0a |
| Test-only migration seam physical isolation | Section 0.5 Rules 33 and 38; Task 11 Steps 4.6.0a and 4.6.9 |
| Architecture gate before production migration and after every GREEN | Section 0.5 Rule 44 and Task 11 Step 4.6.0a |
| Expected-vs-actual production-path and cross-state coverage | Task 11 Step 4.6 |
| Measured zero-network proof and fail-closed readiness | Task 11 Steps 4.6.10-4.6.13 |
| Raw SSE + contract + DOM + screenshot audit | Tasks 11-12 |
| No uncontrolled API spend | Sections 0.5, Task 11, Task 12 |
| Smoke-loop circuit breaker | Section 0.8, Tasks 11-12 |
| Clarification truth counter | Tasks 11-12 |
| Exact change and evidence manifests | Tasks 11-12 |

### 3.2 Explicitly excluded shortcuts

```text
Prompt-only retries
product-ID branches
raw sentence keyword branches
output-sentence hard-coded replacements
parallel compatibility bridges
temporary or uncommitted production migration bridges
source-dependent processor-registry replacement
post-`_execute_core` result wrappers
post-router raw semantic parsing
session/version-fabricated request or turn identity
production imports of test-only migration seams
legacy production router switches
reverse StructuredUnderstanding-to-TurnMeaning projection
processor- or adapter-synthesized route decisions
thread-local decision transport
SSE-to-state projection
processor state persistence or staged multi-save commits
failure-owner relabeling without independent review
repeated real batches under one plan revision
directory scans or wildcard staging
lowering image thresholds without trace evidence
full regression before focused proofs
claiming demo success as production success
```

### 3.3 Execution order

Run tasks in this exact order:

```text
1 -> 3 -> 4 -> 5 -> 6 -> 2 -> 7 -> 8 -> 9 -> 10 -> 11 -> 12
```

The order deliberately closes the single-render owner, price/spec binding, and
fact projection before adding `fit` behavior. Task 11 may not run production
calls until Tasks 1-10 focused tests are green and Steps 0, 0.5, 4.5, and all
of 4.6 are closed with repair-epoch-08 evidence. No Task 12 step may begin
until Task 11 bounded smoke is clean and its exact commit exists.
