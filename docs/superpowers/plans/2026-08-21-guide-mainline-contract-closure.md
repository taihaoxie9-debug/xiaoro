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

Plan revision: 2026-08-29-practical-release-r3
Task 11 evidence epoch: repair-epoch-62

---

## Current Execution Status (2026-08-29)

```text
Tasks 1-10: completed and committed
Task 11: PRODUCT_FROZEN; the legacy cryptographic seal workflow remains
  TERMINAL_NO_GO at r47, while the user has explicitly retired that workflow
  as a delivery requirement
Task 12: DEMO_HANDOFF_READY
Release status: DEMO_GO / STRICT_PRODUCTION_NO_GO
Historical practical-release-r2 terminal:
  the repair changed only shared recommendation, responsibility, revision,
  knowledge/assessment, and fixture-schema owners
  no production sentence, case-ID, fixture-path, product-ID, frontend,
  timeout, router, dispatcher, or compatibility-bridge branch was added
  category-level RED captured seven failures; GREEN passed all seven
  the final focused regression passed 677 tests, including the
  no-sentence-patch gate
  the real semantic canary behaviorally validated all eight families
  the one authorized post-repair DeepSeek batch completed all 48 calls and
  passed 42 turns; 47 were schema-valid, source-grounded, binding-valid, and
  task-plan-valid
  four failures are fixture contract mismatches:
    cmp-003-base-finish
    img-001-find-similar-first
    img-002-find-similar-second
    translation-09-image-identity
  two failures remain release risks:
    img-011-budget-similar selected bounded_exploration instead of
      similar_alternatives
    rec-008-paraphrase-base returned invalid JSON
  the pre-repair 21/48 backend replay is superseded diagnostic evidence, not a
  post-repair product score
  post-repair backend, browser, and screenshot phases were not run because
  48/48 translation was already impossible
  no retry, r48/r49, or release seal was authorized by r2
  practical report:
    docs/audits/final-release/mainline-contract-closure/
    practical-release-attempt-01/practical-release-report.json
  practical report SHA-256:
    58344e1f913a4275bb5992a43f7c4e440f3dd51864b2ce49b4fbe7e9b99f45bc
Current practical-release-r3 scope:
  the user explicitly authorized one final shared-owner repair after r2
  preserve practical-release-attempt-01 as immutable historical evidence
  enforce image_similarity + explore -> similar_alternatives at the typed
    semantic contract and strict provider schema while retaining image fit
  derive v5 recommendation and continuity expectations from embedded typed
    operation/context authority without case-ID matching
  retain fail-closed malformed JSON behavior with exactly one provider request
    per turn; do not add local JSON repair or an internal retry
  run category-level RED/GREEN, one bounded semantic canary, and exactly one
    new 48-turn batch under practical-release-attempt-02
  the batch passed 48/48 with exactly 48 provider calls and zero retries
  the user authorized one backend-owner repair after runtime evidence proved
    two replay-evaluator defects and one selected-image binding defect
  preserve the successful translation evidence; it was not rerun
  the final zero-provider backend replay passed 48/48 with zero network,
    provider, binding, presentation, or frontend-contract failures
  browser validation exposed and closed one existing public-contract defect:
    explore normalized the presentation winner but not decision/answer
  the fix was made at the shared backend public-outcome owner; the frontend
    remained unchanged, 180 affected tests and 137 browser-tool tests passed,
    and the current backend replay remained 48/48
  the next browser run reached one passing desktop view, then DeepSeek
    copywriter invalid_output caused a forbidden fallback
  after correcting the stale fit test phrase to explicitly request the
    single best-fit product, the next browser run returned an unexpected goal
    clarification for a clear three-option recommendation
  the required fourteen browser views and screenshot rows therefore did not
    complete; repeated provider sampling to obtain a green run is forbidden
  practical-release-attempt-02 is terminal NO_GO; no r4 repair or legacy
    release seal is authorized
  practical report:
    docs/audits/final-release/mainline-contract-closure/
    practical-release-attempt-02/practical-release-report.json
Demo delivery decision:
  the user explicitly accepted a controlled demonstration build instead of
    continuing the zero-degradation provider-stability loop
  deterministic copywriter fallback and recoverable model clarification are
    accepted Demo degradations
  wrong binding, state corruption, unsafe output, internal errors, and broken
    rendering remain Demo stop conditions
  debug instrumentation and temporary debug artifacts were removed after the
    user ended the stability-debugging phase
  final deterministic post-cleanup regression passed 242 tests
  demo handoff:
    docs/audits/final-release/mainline-contract-closure/
    practical-release-attempt-02/demo-release-handoff.md
Current r47 unattended-recovery checkpoint:
  attempt-11 was append-only reclassified at ledger revision 52 from
  browser_audit/TimeoutError to
  runtime_gate/runtime_version_sync_authority_check_timeout
  r47 architecture reported zero bridge violations and its 128-case,
  177-turn production-path matrix passed with every bypass counter at zero
  r47 zero-API then passed 6927 of 6928 tests; the sole failure was
  test_runtime_gate_repair_accepts_current_descendant_candidate because the
  historical attempt-10 validator did not admit the two explicit r47
  replacement lifecycle nodes as descendants of its retired node names
  network/process guarding remained active with zero provider calls, zero
  outbound attempts, and zero process-creation attempts
  r47 zero-API summary SHA-256 is
  1b91009b436287fbdd010b8ba90da9b943c702d56969fc81137ddb00772fa67e
  the r47 authority rebuild failure triggers the finite NO_GO rule in
  Section 4.6.12p; bounded-smoke-attempt-12 and Task 12 were not run
  333 high-signal product/architecture tests pass
  callable-alias and complete-ancestor walker repairs are focused GREEN
  the two deterministic evidence-tool REDs and the approved final contract
  cleanup now have focused GREEN:
    checkpoint-v2 historical authorization receipt backfill
    post-link runtime-key revalidation and readiness rollback
    CopywriterDraft is sections-only and ConsultationObservation is
    dynamic-only, with legacy rows converted only at persistence migration
  the fixed five-module regression passes 640 tests; copywriter/consultation
  regressions, compileall, and git diff --check also pass
  the checklist-bounded read-only review is complete; its one same-scope copy
  gate omission is closed with 15 focused tests passing
  r42 repair-epoch-62 reached zero-API twice; both captures passed 6909 of
  6910 tests and exposed one test-harness defect: the test ignored an immediate
  worker error from its stale fake-readiness seam, waited 10 seconds, and then
  misreported the result as missing runtime identity; its wait budget was also
  shorter than the runtime's declared 30-second startup budget
  both failed captures remain immutable recovery history; r43 rebuilt the
  canonical repair-epoch-62 after correcting that test-only error propagation,
  seam isolation, and deadline
  r43 then passed 6910 zero-API tests, the runtime/browser evidence, and the
  independent audit; readiness correctly rejected a Task 12 execution-file
  inventory mismatch because the independent audit included
  run_zero_api_runtime.py while readiness omitted it
  the complete r43 evidence bundle is immutable under
  attempt-03-readiness-failed; r44 adds that missing readiness inventory member
  and an exact cross-implementation inventory regression before rebuilding
  r44 readiness sealed and bounded-smoke-attempt-10 was consumed, but no
  business turn ran: the fixed /tmp state directory first caused a preflight
  refusal, then the loaded /chat shell exceeded Playwright's 30-second
  navigation timeout because every shell/static request acquired the complete
  business authority lease
  failure recording exposed a second same-boundary contradiction:
  attempt allocation fixed evidence_directory to the attempt root while
  completion tried to narrow it to the browser failure subdirectory, which
  the snapshot immutability check rejected
  r45 keeps proof capability checks on every non-control HTTP request, limits
  the expensive request authority lease to /api business paths, permits the
  targeted attempt_completed transition to bind its immutable failure
  subdirectory, and adds exact RED/GREEN coverage for both behaviors
  r44 readiness and attempt-10 remain immutable failure history; r45 must
  reclassify that no-turn environment failure, rebuild the same final
  repair-epoch-62 authority, and run one new bounded attempt
  r45 then passed 6920 zero-API tests and the production-path matrix, but its
  first zero-API fixture runtime exited before identity publication because
  the sandbox-child verifier still hard-coded the unsuffixed manifest path
  after the parent had accepted the revision-qualified r45 path
  r46 reuses the readiness manifest-path validator at that child boundary;
  the failed r45 artifacts remain immutable non-authorizing history and no
  browser turn or provider call occurred
  r46 then passed 6921 zero-API tests, the production-path matrix, fixture
  desktop/mobile browser gates, independent audit, and readiness sealing
  bounded-smoke-attempt-11 consumed its authorization but timed out before the
  first completed business turn: the browser's 5-second conversation-version
  request was forced through a measured 26-29 second full authority recheck
  no provider reservation, remote provider socket, or conversation write
  occurred; this is a second runtime_gate failure after attempt-10
  the same-owner circuit breaker ended r46 as NO_GO; that immutable result is
  preserved, but the user explicitly approved one r47 architecture repair
  that moves complete readiness verification to startup, keeps only a
  lightweight request authority check, and separates request quiescence from
  the ledger lock
  no r48, additional Task 11 epoch, or open-ended governance loop is authorized
Latest r9 focused repair verification:
  bounded-smoke-attempt-09 completed seven turns, then failed closed on
  bounded-image-context-t2 with GUIDE_INTERNAL_ERROR before any second state
  save
  deterministic local HTTP replay identified the earliest shared owner as
  planning/state: persisted confirmed-image evidence was not supplied to
  plan_task, so pre-routing scenario_inputs remained absent after the Router
  correctly selected recommendation
  the owner repair supplies persisted confirmed-image IDs only to the existing
  pre-routing plan_task boundary for admitted image_similarity turns; no
  processor fallback, post-router reconstruction, prompt patch, or product
  special case was added
  the protected production matrix now uses the exact bounded browser t2/t3
  messages instead of expanded product-name variants
  compiler reference merging now preserves validated source-span order, so
  "图片里的 B5 和第一款" binds product IDs (38, 91)
  focused compiler/router/enricher/production-path verification passed 131
  tests; the exact image t1 -> t2 -> t3 trajectory commits versions 1, 2, 3
Historical repair-epoch-56 implementation checkpoint:
  fit parent/child admission now requires one source-bound result-count
  evidence for every fit basis; adapter and compiler reuse the same admission
  helper, with focused semantic/adapter/compiler/router regression at 185
  passed
  SSE session-lock acquisition now uses non-blocking try_enter plus cancellable
  async retry; collision waiters no longer occupy acquisition workers, and
  cancellation no longer waits for a blocked flock; test_sse.py is 14 passed
  independent bounded audit now binds the canonical browser trajectory
  expected processor and typed recommendation mode to the production matrix,
  not only to matching user messages
  no-sentence AST gate now follows newly added Python source aliases into
 存续 sinks and keeps JavaScript aliases lexical by function scope, including
  array destructuring; focused gate is 40 passed
  the fixture browser now uploads one, one, and two real protected image
  inputs for image identity, image fit, and multi-image comparison before
  sending the intercepted fixture stream; the captured chat request must carry
  the runtime-issued image bundle ID, version, and owner token
  fixture routing now lets unmocked loopback multipart requests continue
  natively; only chat SSE and feedback-target responses are intercepted, so
  image-bundle uploads retain their multipart body
  fixture Chromium startup now disables QUIC and async DNS/HTTPS-SVCB
  resolution; standard Chromium's fixed IPv6 reachability probe is
  independently reconciled only when the kernel denial and netlog target
  both match the exact known probe, while unknown egress still fails closed
  repair-epoch-37 zero-API evidence measured 6650 passing tests with zero
  provider calls, zero outbound attempts, and zero process-creation attempts;
  its desktop fixture captured all eight turn bundles but correctly failed
  closed because Chromium still emitted a Google IPv6 reachability probe to
  [2001:4860:4860::8888]:443, which macOS compressed into a duplicate
  Seatbelt denial report; its runtime wrapper hit the same malformed-denial
  boundary, so epoch-37 has no readiness or authorization
  repair-epoch-38 repeated the full local proof and measured 6650 passing
  tests, but the standard Chromium fixture still emitted the fixed IPv6
  reachability probe; its desktop and runtime evidence correctly failed
  closed before independent audit, so epoch-38 has no readiness or
  authorization
  the new evidence rule records only this exact kernel-denied environmental
  probe separately and leaves the actual browser/process non-loopback counts
  at zero; no URL, provider call, or unknown target is admitted
  these are unsealed worktree repairs only; no readiness, candidate manifest,
  bounded authorization, real provider call, or Task 11 commit has been
  produced from them
  repair-epoch-39 generated architecture, test-path, candidate, production,
  and semantic evidence, then its single zero-API run measured 6649 passed and
  3 failed with provider/network/process counters all zero; the failures were
  an unregistered post-evidence browser Seatbelt regression node in the
  immutable focused JUnit inventory, so epoch-39 is permanently
  non-authorizing and has no readiness or authorization
  the next repair-epoch-40 closes that proof-tool inventory defect before
  rebuilding authority
  repair-epoch-40 completed the 6653-test zero-API run with zero provider,
  network, and process-creation attempts, but its desktop fixture completed
  all eight browser bundles and failed closed only at Seatbelt finalization:
  the drain canary returned denied and emitted its drain marker before the
  live kernel logger delivered the exact drain PID/port denial, so the
  immutable raw evidence could not prove the required delivery barrier;
  epoch-40 is permanently non-authorizing
  repair-epoch-41 passed the 6654-test zero-API run and its desktop fixture
  observed the exact drain denial barrier, but finalization rejected one
  duplicate-only Chromium denial even though netlog contained only the fixed
  known IPv6 probe target; epoch-41 is permanently non-authorizing
  repair-epoch-42 passed its architecture, test-path, candidate,
  production-path, semantic, and 6655-test zero-API evidence with zero
  provider, network, and process-creation attempts; both desktop and mobile
  fixture-browser runs also passed with complete eight-turn bundles and zero
  browser/process non-loopback attempts
  repair-epoch-42 then failed closed during runtime Seatbelt finalization
  because the live `log stream` capture omitted at least one required
  non-terminal marker even though the persistent unified log later contained
  every nonce-bound marker exactly once in the required order; no runtime
  network report, independent audit, readiness, or authorization exists, so
  epoch-42 is permanently non-authorizing
  repair-epoch-43 retained strict exact-once parsing and added a general
  delivery barrier; its architecture, test-path, candidate, production-path,
  semantic, and zero-API evidence passed, but runtime preflight failed before
  application startup because the live stream omitted both short-lived child
  markers while the persistent unified log later showed both had been emitted
  exactly once; no runtime/browser evidence, independent audit, readiness, or
  authorization exists, so epoch-43 is permanently non-authorizing
  repair-epoch-44 completed the 6659-test zero-API run with zero provider,
  network, and process-creation attempts, and its desktop fixture completed
  all eight browser bundles with zero browser/process non-loopback attempts;
  the mobile fixture also completed all eight page bundles, then failed closed
  because its drain canary marker came from the short-lived canary process and
  the corresponding kernel denial was not delivered to the live log stream;
  the runtime wrapper was stopped without a final network report after that
  failure, so epoch-44 is permanently non-authorizing
  repair-epoch-45 extended the already proven runtime parent-owned marker
  protocol to the fixture browser wrapper: the long-lived parent emits and
  observes phase markers, releases the sandbox child and drain canary through
  explicit stdin gates, derives canary PIDs from exact kernel denials, and
  emits PID-bound observation markers; its focused tests and architecture,
  test-path, candidate, and production-path artifacts passed, but a post-freeze
  review found that runtime drain cleanup still depended on root-process
  liveness, the independent marker-owner AST check was not transitive through
  helpers, and a known Chromium probe denial was not constrained to the
  browser BEGIN/END interval; its zero-API run was interrupted before output,
  so epoch-45 is permanently non-authorizing
  repair-epoch-46 closed all three lifecycle-proof gaps: both wrappers kill
  non-quiescent process groups even after the root exits, independent marker
  ownership follows the local call graph from every short-lived canary entry,
  and producer plus independent parsers require every accepted Chromium probe
  denial to occur before browser END
  repair-epoch-46 passed architecture, test-path, candidate, production-path,
  and its 6671-test zero-API run with zero provider, network, and process
  attempts; its desktop fixture completed all eight page bundles, then
  correctly rejected a Chromium probe denial delivered after browser END,
  proving that END-before-drain still did not establish a same-source delivery
  barrier; runtime finalization was stopped after that failure, so epoch-46 is
  permanently non-authorizing
  repair-epoch-47 moves the post-exit drain canary and its exact kernel denial
  before the parent-owned browser END marker; END and DRAIN are emitted only
  after that same-source barrier, so accepted browser probe denials must be
  inside BEGIN/END without fixed sleeps or late `log show` reconstruction
  repair-epoch-47 passed architecture, test-path, candidate, production-path,
  its 6671-test zero-API run, and all eight desktop plus eight mobile browser
  fixtures with zero provider, network, process, DOM, or contract failures;
  the executor terminal then terminated the outer runtime wrapper instead of
  invoking the authenticated loopback shutdown endpoint, so the child stopped
  later but no parent-owned live-log finalization or runtime network report
  could be reconstructed; epoch-47 is permanently non-authorizing
  repair-epoch-48 keeps the identical production and proof-tool implementation
  and corrects only execution control: the authenticated loopback shutdown
  endpoint must stop the child while the outer wrapper remains attached
  repair-epoch-48 passed architecture, test-path, candidate, production-path,
  its 6671-test zero-API run, and all eight desktop plus eight mobile browser
  fixtures; authenticated shutdown kept the parent wrapper attached, but the
  strict runtime parser rejected one nonce-bound kernel event as malformed
  before producing a runtime report; an exact zero-provider diagnostic replay
  of the same runtime and sixteen fixtures then captured only the three
  required canary denials and passed the unchanged strict parser
  repair-epoch-48 remains permanently non-authorizing; repair-epoch-49 permits
  one same-byte evidence rebuild without a parser relaxation, and a repeated
  malformed runtime event is an external-environment blocker rather than a
  reason to add another macOS log-shape exception
  repair-epoch-49 passed architecture, test-path, candidate, production-path,
  its 6671-test zero-API run, strict runtime finalization, both eight-turn
  fixture-browser runs, and the then-current independent audit; two fresh
  reviewers then reproduced a P1 provenance gap: the runtime report and both
  browser summaries could have their runtime-identity digest replaced
  together, while the desktop/mobile challenge digests could be replaced with
  arbitrary distinct values, because the verified identity and consumed
  challenge originals were not persisted and independently rehashed
  repair-epoch-49 is therefore permanently non-authorizing and has no
  readiness, bounded authorization, provider call, or Task 11 commit
  repair-epoch-50 must persist the canonical runtime identity and each
  consumed challenge as epoch-owned indexed artifacts; readiness and the
  mechanically independent audit must separately parse and rederive every
  identity/challenge digest, candidate/plan/code/protected-payload binding,
  loopback host/port binding, and challenge uniqueness before readiness can
  seal
  provenance RED: the runtime report omitted consumed challenge digests, and
  both validators accepted coordinated replacement of all declared identity
  and challenge digests; the three focused regressions failed for those exact
  reasons before implementation
  provenance GREEN: the runtime records its ordered consumed-challenge digest
  list, each browser bundle indexes canonical identity/challenge originals,
  and readiness plus independent audit separately rederive the full binding;
  all 428 tests across the four affected governance modules pass
  repair-epoch-50 passed architecture, test-path, candidate, production-path,
  and its 6675-test zero-API run with zero provider, network, and process
  attempts; all eight desktop pages then completed, but the fixture child
  failed during summary assembly because one obsolete
  `report.update(runtime_proof)` dict call remained after `runtime_proof`
  became a typed provenance object
  repair-epoch-50 is permanently non-authorizing; its authenticated runtime
  shutdown and parent-owned Seatbelt finalization completed, but it has no
  valid desktop summary, mobile run, independent audit, readiness,
  authorization, provider call, or Task 11 commit
  the stale typed-proof merge was reproduced by a focused RED source-contract
  test and removed; the RED plus provenance persistence tests and historical
  reclassification guard then passed together before repair-epoch-51 preflight
  repair-epoch-51 passed architecture, test-path, candidate, production-path,
  its 6676-test zero-API run, strict runtime finalization, both eight-turn
  browser fixtures, and the independent mechanical audit; readiness dry-run
  then failed closed because its Task 12 execution inventory omitted
  `tools/guide_gates/runtime_auth.py`, which the independent audit correctly
  included
  repair-epoch-51 is permanently non-authorizing and has no readiness,
  bounded authorization, provider call, or Task 11 commit; repair-epoch-52
  must make both independently maintained Task 12 execution inventories exact
  the missing `runtime_auth.py` inventory member was reproduced by a focused
  RED and added to readiness's independently maintained exact set; the RED,
  readiness derivation, historical reclassification guard, and independent
  Task 12 inventory test then passed together
  repair-epoch-52 passed architecture, test-path, candidate manifest,
  production-path, its 6677-test zero-API run, strict runtime finalization,
  both eight-turn browser fixtures, the independent mechanical audit, and a
  side-effect-free readiness dry-run; no provider or non-loopback attempt
  occurred
  the required fresh governance reviewer then reproduced a stronger P1:
  replacing both persisted identities, both consumed challenges, the runtime
  report, both browser summaries and indexes, and the regenerated independent
  audit with one internally consistent unkeyed bundle still passed; the
  earlier regression changed only declared digests and did not exercise this
  complete forgery
  repair-epoch-52 is therefore permanently non-authorizing and has no sealed
  readiness, bounded authorization, provider call, or Task 11 commit
  repair-epoch-53 must anchor one ephemeral Ed25519 public key in the frozen
  candidate manifest before runtime execution; its matching private key may
  exist only in a mode-0600 temporary file until the runtime loads it, verifies
  the public-key match, and immediately unlinks it before serving
  the runtime must sign its canonical identity and every issued/consumed
  challenge under separate domains; browser verification, readiness, and the
  mechanically independent audit must reject a fully recomputed identity,
  challenge, summary, runtime-report, and audit bundle unless every signature
  verifies under the manifest-anchored public key
  signed-provenance RED: both readiness and independent audit accepted a
  complete replacement bundle containing rewritten canonical identity and
  challenge originals, updated browser indexes, an updated runtime report,
  and regenerated top-level evidence hashes
  signed-provenance GREEN: the candidate manifest freezes one Ed25519 public
  key, its repository-external mode-0600 private key is consumed before the
  fixture runtime serves, identity/challenge/runtime-report payloads use
  separate signature domains, and both independent verifiers reject a
  complete bundle re-signed under an attacker-controlled key; all 431 tests
  across the four affected governance modules pass
  repair-epoch-53 preflight reports zero architecture violations, 6678
  classified test nodes, zero invalid production-path claims, and zero
  unprotected fixture dependencies
  repair-epoch-53 then passed the 6678-test zero-API run, production matrix,
  signed runtime finalization, both eight-turn browser fixtures, independent
  mechanical audit, and readiness dry-run without any provider or non-loopback
  attempt
  its fresh governance reviewer found one P1: consumers accepted any sibling
  manifest under the correct epoch directory, so an attacker could substitute
  a new manifest public key and regenerate a completely self-consistent signed
  bundle without changing the separately reviewed canonical manifest
  the same review found one P2: child and parent runtime reports shared one
  signature domain even though their schemas currently prevented substitution
  repair-epoch-53 is permanently non-authorizing and has no sealed readiness,
  bounded authorization, provider call, or Task 11 commit
  repair-epoch-54 closed the reviewed-manifest trust-root gaps, passed the
  6708-test zero-API suite, the 177-request production-path matrix, and both
  eight-turn fixture-browser runs with zero provider or non-loopback attempts;
  authenticated shutdown then failed closed because the parent live unified-log
  stream did not deliver the final nonce-bound Seatbelt drain-canary denial
  before finalization
  no runtime network report, independent audit, readiness, authorization,
  provider call, or Task 11 commit exists for repair-epoch-54; its candidate
  and completed evidence remain immutable and permanently non-authorizing
  repair-epoch-55 was a same-code evidence rebuild under a fresh manifest key
  and reviewed digest; it passed architecture, test-path, the 177-request
  production matrix, the 6708-test zero-API suite, signed runtime
  finalization, both eight-turn browser fixtures, and independent mechanical
  audit with zero provider or non-loopback attempts
  its fresh governance reviewer then reproduced one P1: protected-payload
  hashing in readiness and the independently implemented audit rejected only
  a leaf symlink before reopening by pathname, so an ancestor-directory
  symlink or concurrent path replacement could redirect a protected read
  outside the reviewed repository tree
  repair-epoch-55 is permanently non-authorizing and has no readiness,
  authorization, provider call, or Task 11 commit; all generated evidence and
  the external reviewer SHA remain immutable historical artifacts
  repair-epoch-56 must read every protected source/test/tool/plan/fixture path
  by descriptor walk from the trusted repository root with `O_NOFOLLOW`,
  bind the opened regular-file identity to the named path, and revalidate the
  complete protected payload immediately before exclusive readiness
  publication
  readiness and independent audit must retain independently implemented
  protected-path readers and tests; sharing the manifest reader or one policy
  helper across both verifiers is forbidden
  protected-path RED reproduced three failures: readiness and independent
  audit both accepted an ancestor-directory symlink, and readiness published
  after only one payload validation
  protected-path GREEN uses descriptor-walk reads in both independent
  implementations, repeats the full payload hash before readiness publication,
  and passes the four focused behavior/inventory tests plus all 328
  readiness/runtime/independent-audit module tests
  repair-epoch-56 must require the canonical manifest filename/path and the
  reviewer-recorded expected manifest SHA-256 at every evidence consumer; it
  must also use distinct child-report and parent-report signature domains
  the canonical manifest path is never followed through a symlink; after
  prepare-manifest, a fresh read-only reviewer records its raw SHA-256 once
  as TASK11_EXPECTED_MANIFEST_SHA256, and production matrix, prepare-evidence,
  runtime, fixture browser, independent audit, and readiness sealing must all
  receive that exact external value rather than deriving trust from the
  manifest currently presented to them
  build-change-manifest and finalize-change-manifest also require that exact
  external value; they may not recover it from candidate readiness
  after the secure single read validates the manifest, every recorded
  candidate-manifest digest reuses the reviewed value rather than reopening
  the path, and the sandboxed runtime child applies the same ancestor/leaf
  symlink rejection before accepting the parent-attested bytes
  repair-epoch-56 then passed architecture, test-path audit, the 177-request
  production matrix, the 6711-test zero-API suite, signed runtime
  finalization, both eight-turn fixture-browser runs, and the independent
  mechanical audit with zero provider or non-loopback attempts
  its required fresh manifest-scoped governance review found zero P0, 17 P1,
  and four P2 root causes after cross-group validation; the P1 findings cover
  enriched-task loss during comparison finalization, image ordinal loss after
  product deduplication, cancellation and blocking defects in session locks,
  two legacy migration defects, process-local provider quotas, multi-worker
  OpenCLIP memory ownership, four readiness/ledger trust-boundary defects, a
  public query-controlled fixture transport, fixture schema drift, an image
  selection/send race, a missing presentation-winner binding, and a bounded
  profile trajectory that never confirms a profile
  repair-epoch-56 is permanently non-authorizing and has no readiness,
  authorization, bounded attempt, provider call, change manifest, or Task 11
  commit; its machine evidence and reviewer digest remain immutable history
  r36 must first classify these findings into the declared problem classes,
  close each class through its typed owner boundary, and observe alternate
  entries before declaring the class green; it may not close P1s one by one
  through sentence/product/fixture special cases. It must also close the four
  P2 findings before the next freeze to avoid carrying known robustness debt
  r36 semantic RED/GREEN must prove comparison preserves the exact enriched
  TaskPlan, recovered product bindings retain typed source order, every
  confirmed upload retains its original image ordinal and source identity,
  and the bounded profile trajectory reaches a real confirmed profile before
  the comparison turn
  r36 state/runtime RED/GREEN must prove cancellation-safe lock acquisition,
  one non-blocking async session-lock path for every HTTP operation, migration
  tombstones for discarded legacy rows, dormant product-focus preservation,
  fail-closed partial provider configuration, process-shared persistent daily
  provider limits, a single capacity-managed OpenCLIP model owner in the
  declared production deployment, and a bounded provider response body
  r36 proof RED/GREEN must anchor one repository descriptor for the complete
  protected-payload walk, require exact canonical evidence and ledger paths,
  bind parsed evidence to the exact bytes hashed, and make every post-anchor
  ledger state mechanically derivable without allowing historical deletion
  r36 frontend RED/GREEN must remove query-controlled fixture transport from
  `/chat`, validate any remaining demo data against production contracts,
  await image reads before turn submission, bind presentation winner identity
  to decision/answer/card identity, and remove winner language from explore
  demo copy
Latest complete zero-API evidence: 6711 passed in repair-epoch-56 with zero
  provider calls, zero non-loopback attempts, and zero process-creation
  attempts; it is immutable historical evidence only because the post-freeze
  governance review found the r36 blocking defects before readiness
All existing Task 11 readiness artifacts: historical and non-authorizing
Next authoritative candidate evidence: repair-epoch-62 after the complete r42
  single-path enforcement; repair-epoch-07, repair-epoch-08, and
  repair-epoch-09 remain immutable historical evidence. Repair-epoch-10 is
  also immutable historical evidence because its manifest preceded the
  persisted-image evidence, strict public-SSE replay, and hardened fixture
  corrections discovered by the captured full-suite rerun. Repair-epoch-11
  is immutable historical evidence because the independent audit correctly
  stopped before output when its own fixture-inventory check conflated
  per-test fixture references with the complete protected plan-level fixture
  set; its candidate manifest is stale after the audited checker repair.
  Repair-epoch-12 completed 6199 tests, the production/semantic matrices,
  zero-API network proof, both fixture-browser runs, and its independent
  mechanical audit, but a subsequent fresh governance review found 15 P1
  contract/proof gaps and one P2 test-scope issue. Source and proof-tool repairs
  therefore made epoch-12 stale before readiness sealing; no authorization was
  allocated from it. Repair-epoch-13 contains only the architecture and
  test-path pre-manifest outputs; candidate-manifest creation correctly
  rejected five intended but undeclared paths, so epoch-13 is stale,
  non-authorizing, and has no manifest, readiness, or attempt context.
  Repair-epoch-14 completed the architecture, test-path, manifest,
  production-path, semantic, and zero-API proofs. Its first desktop fixture
  run then failed closed on a fixture-only feedback-target 404. The fixture
  route repair made epoch-14 stale; it has no readiness or attempt context.
  Repair-epoch-15 completed the local proof and mechanical independent audit,
  but the required fresh governance review found concrete-processor-entry,
  observed-state-coverage, runtime-layer-source, and readiness-derivation
  defects. The subsequent source and proof-tool repair made epoch-15 stale;
  it has no sealed readiness or allocated attempt context. Repair-epoch-16
  completed the local proof and mechanical independent audit, but the required
  fresh governance review found four remaining defects: the zero-API pytest
  guard did not cover child processes, readiness did not rehash browser bundle
  artifacts, imported fixture constants were missing from per-node test-path
  evidence, and pre-routing product resolution still touched the text
  processor. The subsequent source and proof-tool repair made epoch-16 stale;
  it has no sealed readiness or allocated attempt context. Repair-epoch-17
  completed the local proof and mechanical independent audit, but the required
  fresh governance review found two P0 seal defects and one P1 path-governance
  defect: commit sealing trusted caller-authored readiness fields, nested
  browser artifacts were not commit-bound, and the modified publicly served
  app/static/demo.html was excluded from candidate governance. The subsequent
  proof-tool and plan repair made epoch-17 stale; it has no sealed readiness or
  allocated attempt context. Repair-epoch-18 then completed the full local
  proof and mechanical audit, but its fresh governance review found two further
  P0 seal defects and one P1 exclusion defect: a hand-authored change draft
  could omit bounded-attempt evidence, a hand-authored release-readiness file
  could bypass candidate-readiness derivation, and wildcard exclusions could
  cover production roots. The subsequent proof-tool repair made epoch-18
  stale; it has no sealed readiness or allocated attempt context.
  Repair-epoch-19 completed the full local proof and mechanical audit, but its
  fresh governance review found two P1 closure defects: authorization confused
  the evidence-directory epoch with the ledger-owned retry sequence, and
  image-bearing requests selected a parallel `stream_image` orchestration path
  that omitted product and pending-reply evidence. It also found two P2
  hardening gaps: the presentation compiler re-derived public mode, and the
  publicly served demo fixture was not transitively protected. The subsequent
  source, proof-tool, and plan repairs made epoch-19 stale; it has no sealed
  readiness or allocated attempt context. Repair-epoch-20 reached the full
  zero-API suite, where 6349 tests passed and two continuous image trajectories
  failed because duplicate image/text identity evidence gave the route
  `explicit_product` rather than reducer-required `confirmed_image` authority.
  The router-owner repair made epoch-20 stale; it has no sealed readiness or
  allocated attempt context. Repair-epoch-21 completed 6353 zero-API tests,
  the production/semantic matrices, desktop/mobile fixture runs, kernel
  network proof, and the mechanical independent audit. Its required fresh
  governance review then found proof and ownership gaps: recovered explicit
  product evidence was omitted at routing, mixed text-plus-image ingress was
  absent from the production matrix, the production gate declared no executed
  layers, the reducer could synthesize single-product display state, readiness
  under-validated the independent audit, repair-epoch path identity was not
  enforced, reclassification could erase an earlier owner count, and the
  independent browser audit reused production canonical-card builders. The
  repair makes epoch-21 stale; it has no sealed readiness or allocated attempt
  context. Repair-epoch-22 then produced architecture, test-path, candidate,
  production-path, semantic, and kernel zero-API artifacts, but its zero-API
  suite recorded 6367 passing tests and 12 failures from stale test scaffolds:
  an old product-resolution collector return type, an old public-envelope
  monkeypatch target, and non-epoch temporary runtime manifests. The sandbox
  report still recorded zero provider, network, and process-creation attempts.
  Those test corrections invalidate its candidate payload; epoch-22 has no
  readiness, fixture runtime, independent audit, or attempt context and is
  permanently non-authorizing. Repair-epoch-23 then reproduced the complete
  local pre-browser sequence through zero-API, where 6378 tests passed and
  one backend replay test found non-deterministic public SSE bytes from
  `frozenset` evidence-use serialization. The serializer repair makes its
  candidate payload stale; epoch-23 has no readiness, fixture runtime,
  independent audit, or attempt context and is permanently non-authorizing.
  Repair-epoch-24 completed only the architecture and test-path pre-manifest
  gates; candidate-manifest creation then rejected the serializer source file
  because it was absent from Task 11 Files. It has no candidate manifest,
  zero-API evidence, readiness, fixture runtime, independent audit, or
  attempt context and is permanently non-authorizing. Repair-epoch-25
  completed the full local proof: 6379 zero-API tests, 176 production-path
  turns, 40/40 state edges, desktop/mobile fixture browser evidence,
  independent mechanical audit, fresh governance, and sealed readiness.
  Its only bounded authorization was consumed by bounded-smoke-attempt-08.
  That attempt returned one valid typed fit clarification, then failed because
  the frontend unconditionally requested a feedback target for a zero-card
  terminal; the production endpoint correctly returned 404 and the browser
  console gate failed closed. Epoch-25 and attempt-08 remain immutable.
  Repair-epoch-26 preserved the machine-derived attempt-08 reclassification
  closure and produced architecture, test-path, candidate, production-path,
  and semantic evidence. Its zero-API suite then recorded 6385 passes and one
  exact-byte backend replay failure: nested
  `SelectionProjection.capabilities` still serialized from a `frozenset` in
  process-dependent order. The canonical serializer repair makes epoch-26's
  candidate payload stale. It has no runtime browser evidence, independent
  candidate audit, readiness, or attempt context and is permanently
  non-authorizing; its attempt-08 repair artifacts remain ledger-bound history.
  Repair-epoch-27 completed the r6 local proof after the zero-card
  clarification and deterministic serializer repairs: 6407 zero-API tests,
  176 production-path turns, desktop/mobile fixture browser evidence including
  one typed zero-card clarification per viewport, runtime network proof, and
  mechanical independent audit all passed. The subsequent fresh governance
  review confirmed one P1 evidence-integrity defect: the attempt-08 failure
  reclassification audit accepted counter-only JUnit XML and a string-matching
  patch that could be hand-forged. The checker repair binds exact testcase
  identity, real RED/GREEN outcomes, focused node inventory, current candidate
  bytes, and a reverse-applicable patch. That protected tool/test repair makes
  repair-epoch-27 stale before readiness sealing. It has no readiness or
  attempt context and is permanently non-authorizing. Repair-epoch-28 completed
  the rebuilt r6 local proof: single-path architecture, 6415 zero-API tests,
  176 accepted production-path turns, desktop/mobile fixture browser evidence,
  runtime network proof, and mechanical independent audit all passed. Its
  required fresh governance review then confirmed a P1 proof gap: the
  production-path matrix did not include a stale-version request rejected at the
  real HTTP boundary before TurnMeaning translation, compile, route, processor,
  reducer, or state save. The protected matrix fixture, production runner,
  readiness verifier, and independent audit repair make repair-epoch-28 stale
  before readiness sealing. It has no readiness or attempt context and is
  permanently non-authorizing.
  Repair-epoch-29 completed the rebuilt r6 local proof: single-path
  architecture, 6419 zero-API tests, 177 production-path turns including one
  stale-version pre-decision rejection, desktop/mobile fixture evidence,
  runtime network proof, independent audit, fresh governance, and sealed
  readiness all passed. Its one bounded authorization was consumed by
  bounded-smoke-attempt-09. That attempt completed the fit turn, all five text
  context turns, and image identity, then failed closed on
  bounded-image-context-t2 with GUIDE_INTERNAL_ERROR. Local runtime evidence
  proved the earliest shared owner was planning/state rather than SSE:
  plan_task omitted the persisted confirmed-image binding, the provisional
  task remained clarify during pre-routing enrichment, scenario_inputs was
  absent, and the selected recommendation processor rejected that incomplete
  typed input before reducer or CAS. The same investigation found that the
  protected matrix had expanded the bounded image t2/t3 text with product
  names and therefore did not exercise the exact browser path. Source, compiler
  ordering, fixture, test, proof-tool, and plan repairs make repair-epoch-29
  stale and permanently non-authorizing. Attempt-09 and all of its raw evidence
  remain immutable ledger-bound history.
Latest bounded real smoke: bounded-smoke-attempt-09 failed on
  bounded-image-context-t2. Its first seven completed turns are preserved.
  The public observation point was `sse_contract`, but deterministic local
  evidence reclassifies the earliest owner to `planning_state`, specifically
  missing persisted-image scenario inputs before routing. No further r6 real
  call is allowed from repair-epoch-29.
Current revision: r47 is explicitly approved after the r46 bounded run exposed
  request-time repetition of startup readiness work recorded in Section
  4.6.12p. It preserves the bounded evidence-attempt design, signed runtime
  capability, one authoritative ledger, and one production request path. It
  adds no third runtime key, timeout extension, API bypass, or unbounded retry.
  The
  128-row summary records the
  actual zero image-fit rows without rewriting source text; image-fit remains
  mandatory in the independent production-equivalent browser fixtures. r9 also
  includes the planning-state owner repair, exact
  bounded trajectory binding, source-ordered reference merge, attempt-09
  reclassification, complete repair-epoch-57 rebuild, terminal-evidence
  fixture contract closure, fully unattended
  execution through Task 12, and the pre-launch review boundary in Section
  0.9. The prior repair-epoch-30 candidate payload
  `a4647934cdb0688fda77216679884e470f43b461f6b1266fa1446a3b9b46d015`
  is immutable non-authorizing history because the screenshot/replay fixture
  contract was corrected afterward. Repair-epoch-31 is also immutable
  non-authorizing history because its runtime child report was valid but the
  parent wrapper was interrupted before final report sealing, leaving its
  browser evidence bound to an unsealed runtime identity. The current
  worktree is not a candidate. Repair-epoch-32 is also immutable
  non-authorizing history because the independent audit tool required a
  source-bound plan revision after its protected-code repair, invalidating
  the earlier candidate payload before audit completion. Repair-epoch-33 is
  also immutable non-authorizing history because this efficiency protocol was
  added to the plan before its evidence could be sealed, changing the plan
  hash. Repair-epoch-34 completed the architecture, test-path, candidate,
  production-path, 6645-test zero-API, runtime network, and desktop/mobile
  browser producer stages. Its independent audit correctly rejected the
  image-identity bundle because the fixture runner had never uploaded an image
  through the visible browser input, while its unit helper had fabricated
  image-bundle request fields. The protected fixture runner, regression test,
  and plan repair make epoch-34 stale before readiness; it has no independent
  audit, readiness, authorization, or attempt context and is permanently
  non-authorizing. Repair-epoch-35 completed the architecture, test-path,
  candidate, production-path, and 6648-test zero-API stages. Its first
  image-bearing fixture browser turn failed before the fixture SSE terminal:
  the fixture route proxied the real multipart image-bundle upload through
  `route.fetch()`, which changed the upload into a 400 "invalid image upload"
  request. The application upload path itself returned 201 under a native
  browser continuation. The fixture-route repair changes only the unmocked
  loopback default to `route.continue_()` while retaining explicit fixture
  SSE and feedback-target interception. Epoch-35 has no independent audit,
  readiness, authorization, or attempt context and is permanently
  non-authorizing. Repair-epoch-36 then passed its architecture,
  test-path, candidate, production-path, and 6648-test zero-API stages and
  reached the real image browser fixture. Its browser requests were all
  loopback and the image upload path progressed, but Chromium emitted
  internal Google IPv6 DNS-over-HTTPS attempts to
  `[2001:4860:4860::8888]:443`; the kernel correctly denied them and the
  Seatbelt parser correctly rejected the extra malformed/duplicate denial
  evidence. The browser startup flag repair and regression test make
  epoch-36 stale before independent audit; it has no readiness,
  authorization, or attempt context and is permanently non-authorizing.
  Repair-epoch-49 later completed the same local and browser evidence stages
  but is permanently non-authorizing because its identity/challenge
  provenance was not independently bound to persisted originals. The current
  worktree is not a candidate. Repair-epoch-57 later completed all declared
  machine evidence and its independent mechanical audit, but the mandatory
  fresh governance review found four P1 defects and one P2 defect: optional
  Router re-planning plus duplicate image-product collapse, unbounded image
  inference waiting inside the SSE iteration pool, Task 12 process-local
  provider quota accounting, path-raceable ledger I/O plus a missing state
  checkpoint, and publicly served legacy fixture transport. It has no
  readiness, authorization, bounded attempt, change manifest, or Task 11
  commit and is permanently non-authorizing. Repair-epoch-58 then passed the
  6814-test sandboxed zero-API run, the 177-turn production-path matrix, and
  both eight-turn desktop/mobile fixture-browser runs with zero provider or
  non-loopback attempts. Its authenticated shutdown completed, but the parent
  strict parser rejected one nonce-bound live Seatbelt denial as malformed
  before it could publish the runtime network report. The one-time private key
  was already consumed, so repair-epoch-58 has no independent audit,
  readiness, authorization, bounded attempt, change manifest, or Task 11
  commit and is permanently non-authorizing. Persistent unified logs are
  diagnostic only and may not reconstruct the missing live raw evidence.
  Repair-epoch-59 froze an r38 same-code candidate and passed architecture
  plus test-path audit, but it was intentionally abandoned before its
  production-path output completed when the user approved the bounded
  evidence-attempt redesign. It has no zero-API, runtime, readiness,
  authorization, bounded attempt, change manifest, or Task 11 commit and is
  permanently non-authorizing. Repair-epoch-61 later completed architecture,
  test-path, production-path, zero-API, runtime/browser, and independent audit
  evidence, but its fresh governance review found seven P1 authority defects;
  it is also permanently non-authorizing. Only a newly sealed
  repair-epoch-62 readiness
  may authorize another call.
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

The isolated Task 11 worktree reuses the repository-owned virtual
environment at this exact interpreter path:

```text
/Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python
```

Every command in this plan invokes that interpreter directly. The worktree
must not create a local `.venv` symlink or copy, and environment files are not
candidate inputs.

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

An authorized current-image comparison may contain four images because the
image upload and `ThreeToFourImageCompareGate` contracts already expose that
bounded mode. This does not raise the ordinary text/product comparison limit
above three.
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
    revision, protected-payload hash, process identity, and runtime nonce. The
    candidate manifest first freezes one ephemeral Ed25519 public key; its
    matching private key is written only to a repository-external mode-0600
    file, loaded into runtime memory, and unlinked before the listener serves.
    The runtime signs its canonical identity, every health challenge, its
    child report, and the final parent-composed report under distinct domains.
    Each browser invocation obtains and atomically consumes its own fresh
    signed challenge from that runtime. The verified canonical
    runtime-identity bytes and complete consumed challenge payload are
    immutable epoch-owned browser artifacts and must appear in that browser
    summary's exhaustive artifact index. Readiness and the independent audit
    each parse those originals, verify the signatures independently against
    the manifest public key, and recompute the identity file digest,
    self-digest, candidate manifest/plan/code/protected-payload binding,
    loopback host/port binding, challenge digest, runtime-identity link, and
    desktop/mobile challenge uniqueness. Matching caller-declared 64-hex
    strings are never provenance. A bounded/release launcher must first bind
    the exact loopback listen socket, generate an ephemeral Ed25519 key in
    memory, and append one ledger registration binding its public key, identity
    digest, attempt/context/readiness/allocation anchors, host, and port. An
    unregistered runtime rejects control and business requests. The locked
    ledger writer sends a fresh verifier nonce to that listener, verifies the
    signed proof against the ledger-registered public key, and atomically binds
    the complete proof and attestation digest to `authorization_consumed`.
    Every business request holds a shared ledger authority lease through the
    ASGI response; completion takes the exclusive lock. Startup failure aborts
    the registration and removes only the matching identity inode. Browser
    summaries, attempt completion, and the final change manifest must match the
    signed proof digest. A caller-supplied 64-hex value, self-declared public
    key, or consumed proof cannot authorize another invocation.
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
46. No path under `app/`, `tools/`, or `tests/` may be exempted from candidate
    governance. A modified publicly served page or frozen runtime asset must be
    declared and protected or restored before evidence generation; an exclusion
    pattern is not a substitute for review.
47. HTTP ingress and every internal runtime harness call one
    `UnifiedGuideFlow.stream` entrypoint for text and image-bearing turns.
    Image presence may activate only a typed pre-routing evidence collector; it
    may not select a second orchestration method or omit product/pending-reply
    evidence.
48. `UnifiedRouteDecision.presentation_mode` is passed explicitly into
    presentation compilation. The compiler may validate it but may not recreate
    it from responsibility.
49. Independent-audit `repair_epoch` names the immutable evidence directory
    only. Retry owner, retry sequence, and repair evidence are derived solely
    from the verified append-only ledger and its failure-reclassification
    chain; an audit JSON may not author those ledger facts.
50. Catalog-backed explicit product mentions recovered before routing are
    first-class current-turn evidence. They may not be discarded merely
    because the provider omitted the same mention.
51. The zero-provider production matrix must include a nonempty text request
    carrying a current image bundle and exercise image, explicit-product, and
    pending-reply evidence through the one HTTP entrypoint.
52. The production-path test inventory records the nonempty ordered runtime
    layers measured by the production summary. An empty `layers_executed`
    declaration is invalid.
53. A processor-owned product-lane replacement carries complete typed
    `DisplayedCandidateRef` state. The reducer may select or preserve supplied
    values but may not fabricate skin-match or efficacy fields.
54. Candidate manifest, independent audit, readiness, and all evidence inputs
    must agree with the plan-declared repair epoch and its exact directory.
    Readiness validates the complete zero-finding audit contract, not only its
    top-level pass flag and selected hashes.
55. Independent browser canonical-card validation parses the protected
    catalog, display-binding, image, category, and alias assets itself. It may
    reuse only the application-owned `project_frontend_product` projection,
    not production catalog builders, card builders, or skin-match logic.
56. Failure reclassification is append-only provenance. Every historical and
    corrected owner remains counted for circuit-breaker purposes; relabeling
    may not decrement or erase an owner's failure count.
```

These prohibitions remain active after the corresponding task is marked
complete. A green test that encodes a prohibited shortcut is not release
evidence.

### 0.5a Problem-Class Governance And Repair Protocol

Governance repairs are organized by **problem class**, not by the individual
symptom, sentence, product, fixture, endpoint, or failing test that first
exposed the defect. A single observed failure is evidence of a possible class
violation; it is never the complete repair scope.

For every new P0/P1/P2 finding, the executor must complete this sequence before
writing production code:

```text
1. classify the finding into an existing problem class, or define one new
   class with a precise boundary;
2. identify the violated invariant and its sole owning layer;
3. enumerate every production entry, state backend, renderer, tool, and test
   seam that can exercise the class;
4. write a class-level RED corpus covering the observed case plus at least
   one alternate entry, boundary value, ordering/concurrency variant, and
   forged or stale input where applicable;
5. repair the owning contract once, so all enumerated paths consume the same
   invariant;
6. run the class-level GREEN corpus and the affected module suites;
7. run an independent class audit that searches for the forbidden shape, not
   only the original example;
8. record the class closure and residual risk before the next evidence epoch.
```

The current Task 11 problem classes are:

```text
task-authority:
  one enriched TaskPlan is authoritative; downstream routing may revalidate
  route-owned fields but may not re-plan or reconstruct semantic state

source-identity:
  uploaded images, product mentions, source spans, ordinals, and typed
  bindings retain identity through routing, reduction, persistence, and render;
  deduplication is a separate projection

session-serialization:
  every HTTP operation for a session uses one cancellable non-blocking lock
  protocol; cancellation, cross-worker access, migration, and CAS preserve
  ownership and generation barriers

provider-capacity:
  configuration, provider quota, response size, worker topology, and model
  ownership fail closed under partial config, restart, concurrency, and
  deployment capacity

evidence-authority:
  manifest, evidence files, repository root, ledger, signatures, and history
  are bound to canonical bytes and cannot be copied, forked, replaced, or
  historically rewritten

public-contract:
  production pages consume only production typed SSE; frontend terminal,
  presentation, decision, answer, card, image, and winner identities agree
  across every public event
```

The repair-epoch-56 governance findings are classified as follows before any
new production repair is accepted:

```text
task-authority:
  comparison finalization discards the enriched pre-routing TaskPlan;
  bounded profile trajectory does not actually confirm the profile;

source-identity:
  confirmed-image projection rewrites upload ordinals after product
  deduplication; recovered product mentions lose typed source order; tests
  that manually inject mention spans or expect collapsed duplicate images are
  invalid class coverage;

session-serialization:
  late cancellation can leak an acquired session lock; blocking HTTP
  operations can exhaust the request worker pool; legacy migration can delete
  a session without a durable tombstone; dormant product focus can be lost
  during migration;

provider-capacity:
  partial configuration is indistinguishable from intentional disablement;
  daily quotas are process-local; health probes can load one large OpenCLIP
  model per worker; provider response bodies lack a pre-parse byte ceiling;

evidence-authority:
  protected hashing does not retain one root descriptor for the complete walk;
  readiness accepts noncanonical evidence paths; a forked ledger can reuse an
  anchor; historical failures can be removed and a new tip recomputed;

public-contract:
  a public query parameter can select fixture transport; fixture payloads do
  not fully satisfy the production presentation contract; image selection can
  race submission; terminal validation does not bind presentation winner to
  decision identity; explore copy can contain selected-winner language.
```

The class matrix is the authority for r36 scope. A later occurrence in one of
these classes extends its RED/GREEN corpus and does not create a seventh
symptom-specific repair track. A finding may be downgraded or rejected only
after the class-level alternate-entry and independent-audit evidence proves
that its invariant is already enforced.

No repair may be declared complete because one named test passes. A class is
closed only when its invariant is enforced at the owning boundary and its
alternate-entry corpus and independent class audit pass. If a later audit
finds another symptom in an already-known class, extend that class corpus and
repair the owner; do not open a symptom-specific branch or start a new
parallel bridge.

Expensive zero-API, browser, evidence, readiness, and real-call phases are
forbidden while any class has an open RED, an unverified GREEN, or an open
independent class audit. This ordering prevents a complete evidence epoch from
being spent before the governing problem class is understood.

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
3. Do not stage debug notes, temporary screenshots, `.dbg/`, `.tmp-*`, or
   historical audit output in that checkpoint. Any modified publicly served
   `app/static/` asset must be declared and protected by its task manifest.
4. Before every later commit, inspect `git diff -- <exact task files>`.
5. Every `git add` uses exact files. Directory-level staging such as
   `git add app/guide/presentation` or `git add tests/guide` is forbidden.
6. Never revert, stash, or overwrite unrelated dirty files.
```

The current branch is already isolated from `main`; do not create a clean
worktree that would silently drop this WIP baseline.

The executor must autonomously diagnose, repair, test, independently audit,
revise this plan when mechanically required, and continue through every
pre-launch implementation, evidence, tooling, and release-validation step
without pausing for user review. A genuine external blocker may halt execution,
but it is not an intermediate audit checkpoint.

### 0.8 Smoke-loop circuit breaker

Every real-model or production-equivalent smoke run follows this stop rule:

```text
1. Stop at the first serious failure and preserve its complete evidence bundle.
2. Classify the earliest failing owner:
   translation -> admission -> planning/state -> retrieval/identity ->
   fact projection -> copy/attribution -> presentation provenance ->
   SSE contract -> DOM rendering.
3. If the same owner fails twice anywhere in the persistent attempt ledger,
   freeze all further real calls and produce the final no-go report. The
   failures need not be consecutive and reopening an agent session does not
   reset the count.
4. Before another real call, require all four:
   a deterministic local reproduction,
   a focused regression test that failed before the repair,
   a repair in the earliest shared owner rather than the observed sentence,
   and an independent read-only audit of the resulting diff.
5. Run focused zero-API tests and the desktop/mobile fixture browser gate.
6. Make exactly one newly authorized real-call phase. The phase is explicitly
   one of: Task 11 bounded browser smoke, Task 12 48-turn translation, or
   Task 12 release browser audit.
7. Under the final r43 boundary, the first serious bounded or release-phase
   failure is preserved and classified automatically. A transient
   provider/browser/capture failure may consume only the already bounded retry
   allowed by its phase. A reproducible product-path failure must receive one
   deterministic local reproduction, one focused failing regression, and the
   smallest earliest-owner repair before the affected evidence is rebuilt.
8. Preserve every failed attempt. Do not wait for an interactive approval
   checkpoint. A second failure at the same owner, an ambiguous legal next
   action, exhausted credentials/provider availability, or a defect that
   cannot be repaired inside the declared architecture ends the workflow with
   a final no-go report. No sentence, product, fixture, or screenshot-specific
   patch can create another retry.
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
attempt directory. Historical failures remain in the ledger forever; a new
mechanically recorded plan revision authorized by Section 0.9 starts a new
count without deleting history.

After the local reproduction, focused regression, shared-owner repair, and
independent audit required by Step 4 exist, a reviewer may issue one
`retry_authorization_id` for one owner, one `repair_epoch`, and one
`plan_revision`. The runner consumes that authorization before its first
request. It cannot be reused. If the authorized attempt fails at the same
owner, the circuit is permanently open for that plan revision. Only a new
revision satisfying Section 0.9 may allocate another authorization.

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
  --expected-manifest-sha256 <reviewer-recorded-sha256>
```

The command derives `first_failure_owner`, `repair_epoch`, and `plan_revision`
from the ledger and readiness; callers cannot supply or override them. It
verifies the repair evidence and independent audit hashes recorded in
readiness, writes one allocated authorization, and prints its ID. `allocate`
and `allocate-child` require that exact ID and reject phase, plan revision,
repair epoch, owner, or readiness mismatches.

Authorization snapshots the exact readiness and independent-audit bytes that
were verified, rechecks both snapshots after taking the ledger lock, and stores
only hashes of those same verified bytes. A file replacement between
verification and authorization fails closed; the writer may not combine an
old verifier result with a new file hash. At most one allocated or consumed
authorization may exist across all real-call phases for a plan revision.

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
current_phase
parent_attempt_id
phase_attempt_ids
phase_authorization_ids
output_directory
readiness_path
ledger_path
allocated_ledger_revision
allocated_ledger_hash
required_parent_summary (child contexts only: phase + result + path + SHA-256)
```

The tool rejects an existing context path or output directory. Reading a
context requires the current ledger revision to be at least the allocation
revision, then revalidates the referenced immutable attempt record instead of
requiring revision equality after later legal transitions. `allocate` and
`allocate-child` print the newly created unique context path to stdout.
`current_phase` is the sole tail-phase authority; no reader may infer the
current phase from JSON object key order. `allocate-child` requires the parent
context to be a passed translation attempt and binds the required passed
backend summary by path and SHA-256 before allocating a browser attempt.
Both consumption and completion re-read the immutable context while holding
the ledger lock and rerun its content hash, attempt-record hash, allocation
revision/hash, readiness path/hash, and phase-authorization binding checks
before any state transition. Context tampering after consumption cannot be
recorded as a passed or failed completion.
`current` prints a context only when exactly one matching,
nonterminal context exists for the requested phase and plan revision;
otherwise it fails. `current` and `latest` both require `--readiness`; they
derive the plan revision from that file and never search across plan
revisions. `latest --result X` inspects the newest matching context and asserts
that its result is `X`; it never searches backward for an older context with
the requested result.

### 0.9 Unattended execution authorization

The user's 2026-08-26 instruction authorizes uninterrupted execution of the
specified Task 11 and Task 12 workflow through the final pre-launch boundary.
There is no intermediate user-review checkpoint. This does not weaken any
machine gate, evidence requirement, circuit breaker, or fail-fast rule.

The executor must autonomously continue through:

```text
local reproduction and RED/GREEN repair
debug instrumentation cleanup after machine post-fix proof
attempt failure reclassification and append-only ledger update
the final repair-epoch-62 evidence construction
zero-API, network, browser, independent-audit, and bounded-governance checks
readiness sealing
one ledger-authorized real execution for each already defined plan phase
Task 11 change-manifest construction, exact staging, verification, and commit
Task 12 execution after the committed Task 11 machine precondition passes
one checklist-bounded review defined by Section 4.6.12i
```

Every real phase still requires its own fresh readiness, independent audit,
and one-time authorization created and consumed by `attempt_ledger.py`.
Standing user authorization permits the executor to invoke that writer without
another chat confirmation only for the exact bounded, translation, and browser
phases already defined in this plan. It permits the finite automatic
classification and earliest-owner recovery in Sections 0.8 and 4.6.12k, but
no expanded trajectory, unplanned provider, budget increase, sentence/product
special case, second failure at the same owner, or parallel production path.

Before the final pre-launch go/no-go review, the executor pauses only when:

```text
credentials or an external provider/environment remain unavailable
the machine verifier cannot establish an unambiguous next legal action
```

The two named local REDs in Section 4.6.12i, evidence generation, debug
cleanup, successful independent audit, readiness sealing, successful phase
transitions, and the finite recovery in Section 4.6.12k are not conversational
stops. A later in-scope P0/P1 or serious real-phase failure is recorded
immediately, then either repaired once at the earliest owner and fully
revalidated or closed as a final no-go under the circuit breaker. After all
Task 12 machine gates and screenshot review pass, the executor stops once for
the user's final pre-launch review before any external deployment or
publication action.

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
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -m compileall -q app tools tests
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -m pytest -q \
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

Confirm debug notes, `.dbg/`, `.tmp-*`, screenshots, and historical audit
directories remain unstaged. A modified `app/static/demo.html` is not residue:
because `/demo` serves it, Task 11 must declare, test, and protect it.

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
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -m pytest -q \
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
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -m pytest -q \
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
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -m pytest -q \
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
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -m pytest -q \
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
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -m pytest -q \
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
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -m pytest -q \
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
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -m pytest -q \
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
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -m pytest -q \
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
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -m pytest -q \
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
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -m pytest -q \
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
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -m pytest -q \
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
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -m pytest -q \
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
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -m pytest -q \
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
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -m pytest -q \
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
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -m pytest -q \
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
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -m pytest -q \
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
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -m pytest -q \
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
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -m pytest -q \
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

**Status:** `TERMINAL_NO_GO`. The base strict turn-meaning contract,
request-scoped browser bundle, and zero-API fixtures exist, but the current
worktree has multiple production ownership paths and a second state projection
in the HTTP adapter. The amendment is approved and production execution follows
the exact Step 4.6.0a sequence. Step 4.6 is one indivisible architecture migration;
partially completed substeps do not reopen smoke. Real calls remain forbidden
until the complete local r5 proof is sealed.

**Files:**
- Create: `tools/guide_gates/run_mainline_contract_browser_audit.py`
- Create: `tests/guide/tools/test_run_mainline_contract_browser_audit.py`
- Modify: `data/canonical/core_products_v1_manifest.json`
- Modify: `data/canonical/core_products_v1.jsonl`
- Modify: `data/canonical/seed_product_images_v1_manifest.json`
- Modify: `data/canonical/seed_product_images_v1.jsonl`
- Modify: `data/canonical/controlled_product_aliases_v1_manifest.json`
- Modify: `data/canonical/controlled_product_aliases_v1.jsonl`
- Modify: `data/guide_category_facts/category_facts_v1_manifest.json`
- Modify: `data/guide_category_facts/category_facts_v1.9e037e77a4f7dbf3c5eb67f18850ff70fa33748131c19f3c7f3ceaa023f859bb.jsonl`
- Modify: `data/guide_product_display_bindings/v1/product_display_bindings_v1_manifest.json`
- Modify: `data/guide_product_display_bindings/v1/product_display_bindings_v1.1c4c8b655862cace29f62d9e7e14abf111668434572dbd8ddb902c8bf5b45d31.jsonl`
- Modify: `data/guide_selection_concepts/v2/selection_concepts_v1_manifest.json`
- Modify: `data/guide_selection_concepts/v2/selection_concepts_v1.0642ea8067325c7f3aed8ffbb884d5415ff42c9163b634def913f5de2a24e4d5.jsonl`
- Modify: `data/guide_merchant_claims/merchant_claims_v1_manifest.json`
- Modify: `data/guide_merchant_claims/merchant_claims_v1.8b90f33d45368c269076d96a8b0ca76fd1c5fcac988fd96cc93937da7d4207fd.jsonl`
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
- Modify: `app/guide/feedback/delivery.py`
- Modify: `app/guide/feedback/focus_state.py`
- Modify: `app/guide/feedback/ports.py`
- Modify: `app/guide/adapters/state/in_memory_conversation_state.py`
- Modify: `app/guide/adapters/state/sqlite_conversation_state.py`
- Modify: `app/guide/adapters/state/trusted_sqlite_storage.py`
- Modify: `app/guide/application/contracts.py`
- Delete: `app/guide/application/orchestrator.py`
- Create: `app/guide/application/consultation_contracts.py`
- Create: `app/guide/application/execution_contracts.py`
- Create: `app/guide/application/product_resolution.py`
- Create: `app/guide/application/session_profile_resolution.py`
- Create: `app/guide/application/task_plan_enrichment.py`
- Delete: `app/guide/application/consultation_collection.py`
- Delete: `app/guide/application/consultation_coordinator.py`
- Delete: `app/guide/application/consultation_assessment.py`
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
- Modify: `app/guide/decision/recommendation.py`
- Modify: `app/guide/presentation/card_display.py`
- Modify: `app/guide/presentation/comparison_planning.py`
- Modify: `app/guide/presentation/contracts.py`
- Modify: `app/guide/presentation/copywriter_contracts.py`
- Modify: `app/guide/presentation/copywriter_prompt.py`
- Modify: `app/guide/presentation/copywriter_references.py`
- Modify: `app/guide/presentation/copywriter_validation.py`
- Modify: `app/guide/presentation/presentation_compiler.py`
- Modify: `app/guide/presentation/presentation_packet.py`
- Modify: `app/guide/presentation/public_contracts.py`
- Modify: `app/guide/presentation/sse_events.py`
- Modify: `app/guide/retrieval/product_evidence_assets.py`
- Modify: `app/guide/retrieval/product_evidence_retrieval.py`
- Modify: `app/guide/retrieval/product_name_resolver.py`
- Modify: `app/guide/adapters/image/inference_limiter.py`
- Modify: `app/guide/adapters/llm/presentation_copywriter_adapter.py`
- Modify: `app/guide/adapters/llm/provider_common.py`
- Modify: `app/guide/adapters/llm/deepseek_turn_meaning.py`
- Modify: `app/guide/adapters/llm/deepseek_presentation_copywriter.py`
- Modify: `app/guide/adapters/llm/siliconflow_presentation_copywriter.py`
- Modify: `app/guide/adapters/llm/siliconflow_turn_meaning.py`
- Modify: `app/guide/understanding/semantic_equivalence.py`
- Modify: `app/guide/understanding/consultation_contracts.py`
- Modify: `app/guide/feedback/consultation_state.py`
- Modify: `app/guide/presentation/copy_evidence_validation.py`
- Modify: `app/guide/presentation/copywriter_fallback.py`
- Modify: `app/guide_runtime/composition.py`
- Modify: `app/guide_runtime/contracts.py`
- Modify: `app/guide_runtime/copywriter_config.py`
- Modify: `app/guide_runtime/app.py`
- Modify: `app/guide_runtime/llm_config.py`
- Modify: `app/guide_runtime/sse.py`
- Modify: `docker-compose.prod.yml`
- Modify: `tools/guide_data/build_copy_gate_v3_production.py`
- Modify: `tools/guide_data/promote_approved_category_facts.py`
- Modify: `tools/guide_gates/build_responsibility_matrix.py`
- Modify: `tools/guide_gates/build_semantic_equivalence_matrix.py`
- Modify: `tools/guide_gates/presentation_copy_gate.py`
- Modify: `tools/guide_gates/replay_presentation_copy_contract.py`
- Modify: `tools/guide_gates/frontend_presentation_browser_audit.py`
- Modify: `tools/guide_gates/run_real_continuous_conversation_browser_audit.py`
- Modify: `tools/guide_gates/turn_meaning_gate.py`
- Modify: `tools/guide_gates/continuous_conversation_fixture.py`
- Modify: `tools/guide_gates/continuous_conversation_blind_fixture.py`
- Modify: `tools/guide_gates/continuous_conversation_pool.py`
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
- Create: `tools/guide_gates/runtime_auth.py`
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
- Modify: `requirements-guide-runtime.txt`
- Modify: `tests/guide/tools/test_semantic_equivalence_matrix.py`
- Modify: `tests/guide/tools/test_turn_meaning_gate.py`
- Create: `tests/guide/tools/test_attempt_ledger.py`
- Create: `tests/guide/tools/test_build_task11_readiness.py`
- Create: `tests/guide/tools/test_single_path_architecture.py`
- Create: `tests/guide/tools/test_private_api_key.py`
- Create: `tests/guide/tools/test_run_bound_runtime.py`
- Create: `tests/guide/tools/test_run_task11_independent_audit.py`
- Create: `tests/guide/tools/test_historical_repair_patch.py`
- Modify: `tests/guide/tools/test_continuous_conversation_blind_fixture.py`
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
- Create: `tests/guide/tools/test_task11_bounded_expectation_binding.py`
- Create: `tests/guide/tools/test_run_zero_api_runtime.py`
- Create: `tests/guide/tools/test_zero_api_network_guard.py`
- Modify: `tests/guide/tools/test_build_responsibility_matrix.py`
- Modify: `tests/guide/tools/test_audit_product_aliases.py`
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
- Create: `tests/guide/application/test_pre_routing_task_plan_enricher.py`
- Create: `tests/guide/application/test_product_resolution.py`
- Delete: `tests/guide/application/test_consultation_collection.py`
- Delete: `tests/guide/application/test_consultation_coordinator.py`
- Delete: `tests/guide/application/test_consultation_lifecycle.py`
- Modify: `tests/guide/application/test_cross_worker_text_state.py`
- Delete: `tests/guide/application/test_image_presentation_integration.py`
- Modify: `tests/guide/application/test_image_recommendation_flow.py`
- Modify: `tests/guide/application/test_pending_turn.py`
- Modify: `tests/guide/application/test_product_evidence_answer.py`
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
- Modify: `tests/guide/adapters/image/test_inference_limiter.py`
- Modify: `tests/guide/feedback/test_conversation_state_contracts.py`
- Modify: `tests/guide/feedback/test_feedback_delivery.py`
- Modify: `tests/guide/feedback/test_focus_state.py`
- Modify: `tests/guide/presentation/test_copy_evidence_validation.py`
- Modify: `tests/guide/presentation/test_card_display_contracts.py`
- Modify: `tests/guide/presentation/test_copywriter_contracts.py`
- Modify: `tests/guide/presentation/test_copywriter_fallback.py`
- Modify: `tests/guide/presentation/test_followup_response.py`
- Modify: `tests/guide/presentation/test_presentation_compiler.py`
- Modify: `tests/guide/presentation/test_presentation_packet.py`
- Modify: `tests/guide/presentation/test_presentation_sse_contracts.py`
- Modify: `tests/guide/presentation/test_budget_revision_response.py`
- Modify: `tests/guide/presentation/test_copywriter_validation.py`
- Modify: `tests/guide/presentation/test_copywriter_prompt.py`
- Modify: `tests/guide/presentation/test_copywriter_section_contract.py`
- Modify: `tests/guide/presentation/test_skin_revision_response.py`
- Modify: `tests/guide/retrieval/test_card_specification.py`
- Modify: `tests/guide/retrieval/test_product_evidence_retrieval.py`
- Modify: `tests/guide/retrieval/test_product_name_resolver.py`
- Delete: `tests/guide/runtime/test_backend_handoff_matrix.py`
- Modify: `tests/guide/runtime/test_composition.py`
- Modify: `tests/guide/runtime/test_composition_copywriter.py`
- Modify: `tests/guide/runtime/test_composition_understanding.py`
- Modify: `tests/guide/runtime/test_consultation_vertical_composition.py`
- Modify: `tests/guide/runtime/test_copywriter_config.py`
- Delete: `tests/guide/runtime/test_feedback_runtime_http.py`
- Modify: `tests/guide/runtime/test_frontend_presentation_stream.py`
- Modify: `tests/guide/runtime/test_frontend_card_binding.py`
- Modify: `tests/guide/runtime/test_frontend_scope.py`
- Modify: `tests/guide/runtime/test_image_upload_request_limits.py`
- Modify: `tests/guide/runtime/test_image_runtime.py`
- Modify: `tests/guide/runtime/test_llm_config.py`
- Delete: `tests/guide/runtime/test_presentation_runtime_http.py`
- Modify: `tests/guide/runtime/test_product_evidence_real_matrix.py`
- Modify: `tests/guide/runtime/test_runtime_http.py`
- Create: `tests/guide/runtime/test_r36_frontend_boundary.py`
- Create: `tests/guide/runtime/test_runtime_provider.py`
- Modify: `tests/guide/semantic_test_port.py`
- Modify: `tests/guide/tools/test_no_sentence_patch.py`
- Modify: `tests/guide/tools/test_presentation_copy_gate.py`
- Modify: `tests/guide/tools/test_replay_presentation_copy_contract.py`
- Modify: `tests/guide/tools/test_recovery_is_non_promoting.py`
- Modify: `tests/guide/tools/test_trace_image_identity_pipeline.py`
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
- Modify: `app/static/demo.html`
- Modify: `app/static/guide-demo-fixture.js`
- Modify: `app/static/guide-presentation.js`
- Create: `app/static/vendor/feather.min.js`
- Create: `tests/fixtures/guide/intent/task11_production_path_matrix_v1.jsonl`
- Create: `tests/fixtures/guide/intent/turn_meaning_gate_review_v1.jsonl`
- Create: `tests/fixtures/guide/final_release/real_translation_12x4_v5.jsonl`
- Create: `tests/fixtures/guide/aliases/legacy_product_alias_maps.py`
- Modify: `tests/fixtures/guide/responsibility_matrix/summary.json`
- Modify: `tests/fixtures/guide/responsibility_matrix/truth.jsonl`
- Modify: `tests/fixtures/guide/conversation/continuous_20x5_v1.jsonl`
- Modify: `tests/fixtures/guide/conversation/continuous_20x5_v1_manifest.json`
- Modify: `tests/fixtures/guide/conversation/continuous_blind_a_20x5_v1.jsonl`
- Modify: `tests/fixtures/guide/conversation/continuous_blind_a_20x5_v1_manifest.json`
- Modify: `tests/fixtures/guide/conversation/continuous_blind_a_20x5_v2.jsonl`
- Modify: `tests/fixtures/guide/conversation/continuous_blind_a_20x5_v2_manifest.json`
- Modify: `tests/fixtures/guide/conversation/continuous_blind_b_20x5_v1.jsonl`
- Modify: `tests/fixtures/guide/conversation/continuous_blind_b_20x5_v1_manifest.json`
- Modify: `tests/fixtures/guide/conversation/continuous_blind_b_20x5_v2.jsonl`
- Modify: `tests/fixtures/guide/conversation/continuous_blind_b_20x5_v2_manifest.json`
- Modify: `tests/fixtures/guide/conversation/continuous_blind_b_replacement_20x5_v2.jsonl`
- Modify: `tests/fixtures/guide/conversation/continuous_blind_b_replacement_20x5_v2_manifest.json`
- Modify: `tests/fixtures/guide/conversation/continuous_blind_c_20x5_v1.jsonl`
- Modify: `tests/fixtures/guide/conversation/continuous_blind_c_20x5_v1_manifest.json`
- Modify: `tests/fixtures/guide/conversation/continuous_blind_pool_v1.jsonl`
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
- Generate: `docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger-checkpoint-authority.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger-authorization-*.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-57/task11-candidate-manifest.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-57/task11-candidate-readiness.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-57/task11-change-manifest.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-57/task11-semantic-matrix-summary.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-57/task11-zero-api-summary.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-57/task11-independent-audit.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-57/task11-test-path-audit.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-57/task11-production-path-summary.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-57/task11-zero-api-network.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-57/task11-zero-api-runtime-network.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-57/task11-single-path-architecture.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-57/fixture-browser-desktop/`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-57/fixture-browser-mobile/`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-60/task11-candidate-manifest.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-60/task11-candidate-readiness.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-60/task11-change-manifest.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-60/task11-semantic-matrix-summary.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-60/task11-zero-api-summary.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-60/task11-independent-audit.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-60/task11-test-path-audit.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-60/task11-production-path-summary.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-60/task11-zero-api-network.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-60/runtime-browser-evidence/task11-zero-api-runtime-network.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-60/task11-single-path-architecture.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-60/runtime-browser-evidence/fixture-browser-desktop/`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-60/runtime-browser-evidence/fixture-browser-mobile/`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-candidate-manifest.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-candidate-readiness.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-change-manifest.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-semantic-matrix-summary.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-zero-api-summary.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-independent-audit.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-test-path-audit.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-production-path-summary.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-zero-api-network.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/runtime-browser-evidence/task11-zero-api-runtime-network.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-single-path-architecture.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/runtime-browser-evidence/fixture-browser-desktop/`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/runtime-browser-evidence/fixture-browser-mobile/`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/attempt-10-pre-fix-reproduction.xml`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/attempt-10-post-fix-verification.xml`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/attempt-10-focused-zero-api.xml`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/attempt-10-runtime-gate-repair.patch`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/attempt-10-failure-reclassification-audit.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/attempt-11-pre-fix-reproduction.xml`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/attempt-11-post-fix-verification.xml`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/attempt-11-focused-zero-api.xml`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/attempt-11-runtime-gate-repair.patch`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/attempt-11-failure-reclassification-audit.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-candidate-manifest-r45.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-candidate-readiness-r45.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-semantic-matrix-summary-r45.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-zero-api-summary-r45.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-independent-audit-r45.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-test-path-audit-r45.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-production-path-summary-r45.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-zero-api-network-r45.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-single-path-architecture-r45.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/runtime-browser-evidence-r45/task11-zero-api-runtime-network.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/runtime-browser-evidence-r45/fixture-browser-desktop/`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/runtime-browser-evidence-r45/fixture-browser-mobile/`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-candidate-manifest-r47.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-candidate-readiness-r47.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-semantic-matrix-summary-r47.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-zero-api-summary-r47.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-independent-audit-r47.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-test-path-audit-r47.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-production-path-summary-r47.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-zero-api-network-r47.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-single-path-architecture-r47.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/runtime-browser-evidence-r47/task11-zero-api-runtime-network.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/runtime-browser-evidence-r47/fixture-browser-desktop/`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-62/runtime-browser-evidence-r47/fixture-browser-mobile/`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-26/attempt-08-pre-fix-reproduction.xml`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-26/attempt-08-post-fix-verification.xml`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-26/attempt-08-focused-zero-api.xml`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-26/attempt-08-frontend-delivery-repair.patch`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-26/attempt-08-failure-reclassification-audit.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-34/attempt-09-pre-fix-reproduction.xml`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-34/attempt-09-post-fix-verification.xml`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-34/attempt-09-focused-zero-api.xml`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-34/attempt-09-planning-state-repair.patch`
- Generate: `docs/audits/final-release/mainline-contract-closure/repair-epoch-34/attempt-09-failure-reclassification-audit.json`
- Generate: `docs/audits/final-release/mainline-contract-closure/bounded-smoke-attempt-*/`
- Modify: `app/guide/adapters/image/openclip_adapter.py`
- Modify: `app/guide/application/consultation_confirmation.py`
- Modify: `app/guide/application/dynamic_consultation.py`
- Modify: `app/guide/application/general_knowledge_answer.py`
- Modify: `app/guide/application/multi_image_compare_gate.py`
- Modify: `app/guide/application/product_evidence_answer.py`
- Create: `app/guide/application/public_event_envelope.py`
- Modify: `app/guide/decision/followup.py`
- Modify: `app/guide/feedback/profile_policy.py`
- Modify: `app/guide/intent/followup_planning.py`
- Modify: `app/guide/presentation/followup_response.py`
- Modify: `app/guide/retrieval/general_knowledge_contracts.py`
- Modify: `app/guide/retrieval/general_knowledge_retrieval.py`
- Modify: `app/guide_runtime/image_runtime.py`
- Modify: `tests/fixtures/guide/intent/semantic_intent_ab_v2.jsonl`
- Modify: `tests/guide/adapters/image/test_openclip_encoder_behavior.py`
- Modify: `tests/guide/application/test_consultation_confirmation.py`
- Modify: `tests/guide/application/test_general_knowledge_answer.py`
- Modify: `tests/guide/application/test_multi_image_compare_gate.py`
- Modify: `tests/guide/data/test_build_post_promotion_readiness.py`
- Modify: `tests/guide/feedback/test_profile_authority.py`
- Create: `tests/guide/intent/test_image_processor_routing.py`
- Modify: `tests/guide/intent/test_responsibility_matrix.py`
- Create: `tests/guide/presentation/__init__.py`
- Modify: `tests/guide/retrieval/test_general_knowledge_contracts.py`
- Modify: `tests/guide/retrieval/test_general_knowledge_retrieval.py`
- Modify: `tests/guide/retrieval/test_product_evidence_assets.py`
- Modify: `tests/guide/runtime/test_feedback_frontend.py`
- Modify: `tests/guide/runtime/test_sse.py`
- Modify: `tests/guide/test_public_contracts.py`
- Modify: `tests/guide/tools/test_continuous_conversation_fixture.py`
- Modify: `tests/guide/tools/test_intent_model_ab.py`

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

The 128-row matrix must contain both `explore` and `fit` rows. Its sixteen
source-preserved image rows are image-similarity requests and therefore report
`image_fit_count=0`; they must not be rewritten or relabeled to fabricate
image-fit coverage. Image-fit is instead mandatory in the independent
production-equivalent `fixture-image-fit-recommendation` desktop/mobile browser
trajectory and in the later release browser audit. The actual
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
source-preserved semantic image fit row count = 0
production-equivalent browser image fit handoff count > 0
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
captured only after the active request finishes. Each user turn must add
exactly one SSE capture; duplicate successful requests fail closed.

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
Every image-bearing fixture must first upload its protected image asset through
the visible `#imageInput` control. Its captured chat request must contain the
runtime-issued `image_bundle_id`, `image_bundle_version`, and
`image_bundle_token`; a text-only request paired with an image-shaped fixture
SSE is invalid evidence.

- [x] **Step 4: Run the focused harness tests**

Run:

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -m pytest -q \
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
   artifact before staging. Include every modified publicly served static asset,
   including demo.html. Exclude only debug files, temporary files, historical
   audits, and unchanged recording-v1 files.

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
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -m pytest -q \
  tests/guide/tools/test_single_path_architecture.py

PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
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

For every non-production node, the audit derives scope from the test
function's executable AST, reachable local helpers, referenced imports, and
literal fixture/runtime boundary signals. It records distinct metadata for
`unit`, `layer_contract`, and `frontend_fixture`; assigning every
non-production node to a catch-all `layer_contract` scope is invalid and the
independent audit must reject it.

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

Canonical-call cardinality counts only executable, unshadowed bindings. Calls
in constant-dead branches or after unconditional `return`, `raise`, `break`,
or `continue`, plus direct or conditional module/local rebinding, cannot
satisfy the one-call requirement. Constant-dead evaluation includes literal
comparisons such as `if 1 == 0` and an unshadowed
`typing.TYPE_CHECKING` binding; neither may hide the only canonical call.

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

Image bundle authorization belongs exclusively to the pre-routing evidence
collector. The collector validates the request-owned bundle token once and
passes only the frozen authorized `ImageBundle`, payloads, observations, and
anchor topic forward. `ImageRoutingEvidence` contains no owner token or other
credential. No Processor or Processor-reachable helper may accept an
`ImageBundleService`, bundle authorization Protocol/port, authorizer, or
request credential, and no post-Router code may authorize the bundle again.
The architecture checker must reject both direct service injection and an
aliased/delegated authorization capability. Request-side owner-token fields
are excluded from default serialization and representation. The internal
`UserTurn` contract may reveal its token only under an explicit
credential-bearing serialization context required for a controlled
round-trip.

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

The named production-path pytest node must contain one reachable, unshadowed
call to `run_production_path_matrix(...)` with the complete runtime inputs and
must assert the returned summary passed. Collection of the expected node ID
alone is not execution evidence; replacing the body with `pass`, moving the
call into a statically dead branch, or rebinding the runner must make
`audit-test-paths` fail.

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

The production-path summary also records the SHA-256 of the exact candidate
manifest, protected payload, and matrix JSONL consumed by the run. Readiness
and the independent audit recompute all three bindings. A green summary from
another candidate or fixture is invalid even when every internal count is
otherwise valid.

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
test_fixture_browser_persists_identity_and_consumed_challenge_originals
test_readiness_rejects_jointly_forged_identity_and_challenge_digests
test_independent_audit_rejects_jointly_forged_identity_and_challenge_digests
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

The macOS fixture sandbox audit uses a fresh 64-hex measurement nonce in the
effective Seatbelt profile's `with telemetry` and `with message` modifiers.
An unsandboxed parent starts `log stream --style ndjson --unreliable`, proves
collector readiness with an exact nonce marker, and preserves the raw bytes as
`seatbelt.raw.ndjson`. Before runtime identity/challenge consumption, the
sandboxed process runs one direct-child and one descendant native network
canary on distinct TEST-NET ports. Both must fail and appear as nonce-bound
kernel `Sandbox.kext` `network-outbound` denials. Any missing canary, malformed
or lost log event, logger failure, additional nonce-bound denial, raw-log hash
drift, or mismatch with Chromium/Playwright telemetry fails closed.
The sandbox root starts a new process group. After its direct child exits, the
parent must prove that group quiescent before stopping the log collector, run a
third deny-network drain canary under the identical sandbox profile, and
observe the exact drain marker and denial before emitting browser END. The raw
order is `READY < BEGIN < direct denial < descendant denial < PID-bound direct
marker < PID-bound descendant marker < browser probe denials, if any < drain
marker < drain denial < END < DRAIN`. A surviving descendant, missing drain
denial, out-of-window probe denial, or caller-authored quiescence value
invalidates the fixture run.

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
runtime-browser-evidence/task11-zero-api-runtime-network.json
task11-test-path-audit.json
task11-single-path-architecture.json
task11-production-path-summary.json
task11-independent-audit.json
runtime-browser-evidence/fixture-browser-desktop/summary.json
runtime-browser-evidence/fixture-browser-mobile/summary.json
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
tools/guide_gates/build_responsibility_matrix.py
tests/guide/tools/test_build_responsibility_matrix.py
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
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -m pytest -q \
  tests/guide/tools/test_final_real_translation.py \
  tests/guide/tools/test_replay_final_real_backend.py \
  tests/guide/tools/test_final_release_gate.py \
  tests/guide/tools/test_record_manual_screenshot_review.py \
  tests/guide/tools/test_build_task11_readiness.py \
  tests/guide/tools/test_no_sentence_patch.py
```

Expected: PASS before repair-epoch-58 is generated. Any Task 12 source or tool
change after the Task 11 commit invalidates the seal and requires a new
Task 11 revision; Task 12 may only execute these committed tools.

#### 4.6.12a Close bounded-smoke-attempt-08 without another real call

Preserve repair-epoch-25 and bounded-smoke-attempt-08 byte-for-byte. The
attempt's backend stream is a valid typed fit clarification with no cards. The
earliest failure is `dom_rendering`: after the verified terminal, `chat.html`
requested `/feedback-target` even though the validated terminal product list
was empty. The endpoint correctly returned 404 and the browser console gate
failed closed.

The shared-owner repair is limited to:

```text
validated inlineProducts is empty
-> do not request a feedback target

validated inlineProducts is non-empty and no target arrived in the stream
-> request the target after verified EOF and before local commit
```

Do not change the planner, typed clarification, provider prompt, endpoint 404,
console policy, or browser audit severity. Add the zero-card clarification to
the deterministic fixture browser set so desktop and mobile each execute eight
turns. Its fixture feedback-target route must return the production-equivalent
404; any accidental request therefore reproduces the original console failure.
Readiness and the independent audit must both require the same ordered
eight-turn inventory and independently validate the clarification SSE and DOM.

Archive one pre-fix failing JUnit report, one post-fix passing report, the
focused zero-API report, and the exact repair patch under repair-epoch-26.
`run_task11_independent_audit.py audit-failure-reclassification` must derive
the attempt context, original readiness, raw seven-file failure bundle,
previous ledger owner/code, repair file hashes, and new owner/code without
accepting caller-authored hashes or verdict fields. It must reject
counter-only or testcase-free JUnit XML, require the exact RED regression node
to fail with the zero-card feedback-target eligibility assertion, require the
same node to pass in GREEN evidence, require the focused evidence to contain
the reviewed node inventory, and require the repair patch to reverse-apply to
the current candidate before reproducing the RED/GREEN transition in a
temporary candidate copy. It exclusively writes
`attempt-08-failure-reclassification-audit.json`; then only
`attempt_ledger.py reclassify` may append the ledger revision.

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/run_task11_independent_audit.py \
  audit-failure-reclassification \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json \
  --attempt-id bounded-smoke-attempt-08 \
  --repair-root docs/audits/final-release/mainline-contract-closure/repair-epoch-26 \
  --output docs/audits/final-release/mainline-contract-closure/repair-epoch-26/attempt-08-failure-reclassification-audit.json

PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/attempt_ledger.py reclassify \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json \
  --attempt-id bounded-smoke-attempt-08 \
  --independent-audit docs/audits/final-release/mainline-contract-closure/repair-epoch-26/attempt-08-failure-reclassification-audit.json
```

Attempt-07 and attempt-08 then both count against `dom_rendering` under r5, so
r5 remains permanently open. The user reviewed that condition and approved r6
through Goal continuation on 2026-08-25. The first authorization in r6 must
inherit the latest verified repair closure from the append-only ledger while
starting r6's owner-local retry sequence at zero; changing the plan revision
must not erase repair provenance. This behavior requires a focused RED/GREEN
ledger test before repair-epoch-58 is built.

#### 4.6.12b Close bounded-smoke-attempt-09 without another real call

Preserve repair-epoch-29 and bounded-smoke-attempt-09 byte-for-byte.
Attempt-09 completed seven turns and failed on bounded-image-context-t2 with
public `GUIDE_INTERNAL_ERROR`; the loaded and committed conversation versions
both remained 1. The public observation owner is `sse_contract`, but the
earliest shared owner derived from deterministic local runtime evidence is
`planning_state`:

```text
persisted confirmed-image slot was omitted from plan_task product IDs
-> plan_task returned a provisional clarification task
-> pre-routing enrichment correctly omitted recommendation scenario_inputs
-> Router correctly resolved the persisted image and selected recommendation
-> selected processor rejected the incomplete typed execution input
-> no ExecutionResult, reducer call, CAS, or success envelope occurred
```

The owner repair is limited to supplying persisted confirmed-image product IDs
to the existing pre-routing `plan_task` call when the admitted goal is
`image_similarity` and current-turn product IDs are absent. The processor
continues to require scenario_inputs and receives no fallback, raw text, state
store, router, or secondary planning capability.

The same repair closes two proof gaps exposed by the real attempt:

```text
the protected production matrix must use the exact bounded browser t2/t3 text
instead of expanded product-name variants
exact and semantic references must be merged in validated source-span order
so "图片里的 B5 和第一款" binds (38, 91), not (91, 38)
```

Readiness and the independent audit must compare the ordered nine matrix
bounded messages with the ordered browser `BOUNDED_TRAJECTORIES` messages.
Mutating either side alone must fail. A valid allowed fit clarification must
also produce zero bounded serious-failure, wrong-binding, and
invalid-clarification counters; release-only counters may not make a valid
bounded turn self-contradictory.

Archive one pre-fix failing JUnit report, one post-fix passing report, the
focused zero-API report, and the exact repair patch under repair-epoch-34.
Generalize the existing failure-reclassification audit only as needed to bind
attempt-09's immutable context, raw evidence bundle, exact RED/GREEN node
inventory, current candidate bytes, and reverse-applicable patch. It must
derive `planning_state` and the failure code from those artifacts; caller
owner labels and pass booleans remain forbidden. Only
`attempt_ledger.py reclassify` may append the corrected ledger revision.

The user's 2026-08-26 unattended authorization in Section 0.9 approves the
complete local repair, cleanup, repair-epoch-58 rebuild, and exactly one next
r9 bounded phase after all machine gates pass. It does not authorize a second
request after any serious failure.

#### 4.6.12c Close repair-epoch-56 governance findings before rebuilding

Preserve repair-epoch-56, its reviewer digest, and the external governance
report byte-for-byte. It passed all machine evidence but the mandatory fresh
governance stop found blocking defects, so it has no readiness and can never
authorize a bounded attempt.

Implement the r37 repair in five problem-class governance tracks. The five
tracks map to the `task-authority`, `source-identity`,
`session-serialization`, `provider-capacity`, `evidence-authority`, and
`public-contract` classes above; the first two are intentionally combined
because they share the typed turn/image evidence boundary. Every production
change starts only after the class invariant, alternate-entry RED corpus, and
sole owner are recorded. No change may target only the symptom that exposed
the class. No compatibility bridge, second router, processor fallback,
test-only production switch, or sentence/product special case is allowed.

Semantic and identity track:

```text
test_comparison_finalization_preserves_pre_routing_task
test_recovered_explicit_binding_preserves_source_order
test_confirmed_images_preserve_every_original_upload_ordinal
test_duplicate_product_images_remain_independently_referenceable
test_bounded_profile_trajectory_confirms_and_reuses_profile
```

The Router may update only route-owned TaskPlan fields with
`revalidate_task_plan`; it may not call `plan_task` again after the pre-routing
task has been enriched. Product-resolution evidence must carry typed source
spans for recovered explicit bindings so the Router orders all bindings
without reading raw text. Image routing/state evidence must retain one source
identity per upload and the original upload ordinal. Product deduplication is
a separate display/decision projection and may not mutate source-image
identity.

State and lock track:

```text
test_cancelled_lock_acquire_releases_late_success
test_http_session_waiters_do_not_exhaust_shared_threadpool
test_v1_migration_tombstones_discarded_session
test_v1_migration_preserves_dormant_product_focus
```

All async HTTP session operations use one cancellable non-blocking acquisition
context. The acquisition result remains owned until either recorded or
released under cancellation. Blocking `__enter__` is forbidden from request
handlers. Schema migration creates the tombstone table before deleting an
irrecoverable row and records the old generation and owner atomically. Legacy
candidate evidence creates a dormant product slot whenever
`current_product_id` has one exact retained match, independent of the active
lane.

Runtime/provider track:

```text
test_partial_turn_meaning_configuration_fails_closed
test_partial_copywriter_configuration_fails_closed
test_provider_quota_is_shared_across_processes_and_restarts
test_production_deployment_has_one_capacity_managed_image_model_owner
test_provider_response_body_limit_fails_closed
```

An entirely absent provider remains the documented deterministic local mode;
a one-sided key/model configuration is invalid. Daily call and cost
reservations use one atomic persistent store per provider/day shared by all
workers and surviving worker restarts. The declared production deployment may
have only one OpenCLIP model-owning process unless a separately capacity-tested
inference service is introduced. Provider response bytes are bounded before
JSON parsing.

Proof and authorization track:

```text
test_payload_hash_rejects_repository_root_replacement
test_independent_payload_hash_rejects_repository_root_replacement
test_readiness_rejects_noncanonical_epoch_evidence
test_readiness_hashes_the_same_evidence_bytes_it_parses
test_authorization_rejects_forked_ledger_path
test_ledger_rejects_recomputed_tip_after_historical_state_deletion
```

Each payload verifier opens one trusted repository-root descriptor for the
complete sorted walk and rejects a changed visible root before accepting the
hash. Readiness derives exact evidence paths from the canonical manifest epoch
and parses/hashes each file from one secure read. Candidate readiness records
the canonical manifest-declared ledger path; every ledger operation requires
that exact path. A new append-only checkpoint establishes a complete state
snapshot, and every later revision carries enough authenticated state/delta
material for replay to prove that historical attempts and authorizations were
not removed or rewritten.

Frontend and browser-contract track:

```text
test_chat_query_cannot_enable_fixture_transport
test_demo_contracts_validate_as_public_presentation_contracts
test_send_waits_for_pending_image_reads
test_terminal_rejects_presentation_winner_mismatch
test_explore_demo_copy_contains_no_selected_winner_language
```

`/chat` always uses the production HTTP/image/version/feedback paths. Fixture
transport is owned only by the browser harness outside the shipped page; the
standalone `/demo` may remain but all of its data must validate against the
production public contract. A send waits for pending image reads before
snapshotting the turn. Terminal validation binds presentation responsibility,
mode, visible products, winner status, and selected product to the same
answer/decision/card identity.

Run class-level RED, capture the exact expected failures, implement the owner
repair once, then run class-level GREEN, affected module suites, and the
independent class audit. Do not create repair-epoch-58 until every problem
class is closed; a green result for one named case or one named test is not
enough.

#### 4.6.12d Close repair-epoch-57 fresh-governance findings

Repair-epoch-57 is immutable, permanently non-authorizing evidence. Its
mechanical audit passed, but the fresh read-only governance review found four
P1 defects and one P2 defect. r37 extends the existing classes rather than
opening symptom-specific repair tracks:

```text
task-authority + source-identity:
  route_unified_turn requires the exact pre-routing TaskPlan and has no
  task_plan=None fallback; image source bindings preserve upload cardinality
  even when two sources resolve to one product, while TaskPlan product_ids
  remains a separate unique product projection

session-serialization:
  image inference admission cannot wait without a finite bound while occupying
  an SSE iteration worker; exhausted image capacity fails closed quickly enough
  for cancellation to release the held session lock

provider-capacity:
  Task 12 translation uses the same canonical process-shared SQLite
  provider/day quota owner as production; no real-call tool may silently create
  a process-local DailyUsageLimiter

evidence-authority:
  every ledger read, temporary write, atomic replace, recovery, and directory
  fsync stays beneath one descriptor-walked, inode-bound parent; the legacy
  revision-39 ledger is checkpointed only through checkpoint-v2 before
  readiness and all later operations require the path-bound state snapshot

public-contract:
  no runtime route publicly serves fixture SSE transport; retained offline
  fixtures emit only events admitted by the production public envelope
```

The class-level RED corpus must cover the observed case plus:

```text
missing pre-routing TaskPlan and duplicate image source identities
capacity exhaustion, bounded timeout, cancellation, and an unrelated stream
Task 12 adapter construction, restart/shared-store identity, and quota failure
ancestor replacement during ledger read, write, recovery, and checkpoint
both current and recording fixture URLs plus forbidden legacy event scanning
```

Do not mutate the canonical revision-39 ledger until these class repairs and
their independent forbidden-shape audit are green. After that, execute exactly
one hash-bound `checkpoint-v2` transition on the canonical ledger, then build
repair-epoch-58 from the changed protected payload. No repair-epoch-57 artifact
may be reused as an authorizing artifact.

#### 4.6.12e Close repair-epoch-58 runtime evidence failure

Repair-epoch-58 is immutable and permanently non-authorizing. It passed:

```text
single-path architecture: 341 inspected modules, zero violations
test-path audit: 6814 classified nodes, one production-path gate, zero invalid
  claims, missing fixtures, or unprotected fixtures
production-path matrix: 177 turns, 40/40 state edges, 9/9 bounded turns,
  zero bypass, duplicate-owner, provider, or network failures
sandboxed zero-API: 6814 passed with zero provider, non-loopback, or
  unisolated process-creation attempts
desktop fixture browser: 8/8 turns, zero non-loopback attempts
mobile fixture browser: 8/8 turns, zero non-loopback attempts
```

After authenticated shutdown, the parent runtime wrapper failed closed while
parsing one nonce-bound live `Sandbox.kext` event:

```text
ZeroApiRuntimeError: runtime Seatbelt denial event is malformed
```

No canonical runtime network report was published. The manifest-bound private
key had already been consumed and unlinked, so the epoch cannot be resumed or
authorized. Persistent unified-log output is diagnostic only and must not be
used to reconstruct, replace, or authorize the missing live evidence.

r38 permits exactly one same-code evidence rebuild under repair-epoch-59 with
a fresh manifest key and fresh reviewer-recorded manifest digest. The strict
Seatbelt parser, network policy, production source, tests, and proof tools are
unchanged. A repeated malformed runtime denial under repair-epoch-59 is an
external-environment blocker: stop before independent audit, ledger checkpoint,
readiness, authorization, or provider use. Do not add a parser exception or
retry again under another epoch without a reproducible raw event and a
class-level evidence-authority repair.

#### 4.6.12f Bound environment evidence attempts independently

The r39 repair separates candidate validity from transient runtime evidence.
One candidate manifest contains exactly two ordered, distinct fixture-runtime
public keys. `prepare-manifest` writes the matching private keys to two
repository-external mode-0600 files. Each runtime invocation consumes and
unlinks exactly one matching private-key file before serving.

Runtime/browser evidence is first written below a repository-external staging
directory for `attempt-01` or `attempt-02`. A failed or interrupted attempt
cannot overwrite canonical epoch evidence and cannot consume more than its one
precommitted key. A successful attempt is promoted byte-for-byte into the
canonical epoch paths only after its signed runtime report and both browser
summaries pass validation. Any unused private key is then destroyed before
independent audit or readiness.

The retry boundary is:

```text
candidate bytes change before the r43 freeze:
  update the r43 candidate and build the still-unused repair-epoch-62 once

candidate bytes change after the r43 freeze:
  archive the failed non-authorizing candidate, apply the single
  earliest-owner repair in Section 4.6.12k, increment the plan revision, and
  rebuild the canonical repair-epoch-62 without creating a replacement epoch

command interruption or environment-only runtime capture failure:
  same candidate + next precommitted runtime key + runtime/browser only

same environment failure twice:
  final no-go as external-environment blocker; no third key and no new epoch

P0/P1 production or proof invariant failure before the r43 freeze:
  apply the one deterministic earliest-owner repair in Section 4.6.12k

P0/P1 production or proof invariant failure after the r43 freeze:
  preserve the failed evidence and apply Section 4.6.12k automatically
  a second failure at the same owner is final no-go
```

The strict Seatbelt parser remains unchanged. A retry may never reinterpret,
drop, normalize, or reconstruct failed live kernel evidence. Deterministic
architecture, test-path, production-path, semantic, and zero-API evidence is
reused only when its exact candidate manifest and protected payload remain
unchanged.

Required RED/GREEN coverage:

```text
candidate manifest emits exactly two distinct runtime public keys
each private key is external, mode-0600, manifest-bound, and one-time
runtime accepts either precommitted key and rejects every third key
one consumed key cannot consume or invalidate the other key
successful runtime/browser staging promotion is exclusive and byte-identical
failed or interrupted staging cannot occupy canonical evidence paths
readiness and independent audit reject a runtime key outside the two-key set
readiness rejects any surviving unused private-key file before sealing
```

#### 4.6.12g Close repair-epoch-60 fresh-governance findings

Repair-epoch-60 is immutable and permanently non-authorizing. It passed the
341-module single-path architecture gate, the 6825-node test-path audit, the
177-turn production-path matrix, the 6825-test sandboxed zero-API run, the
second and final precommitted runtime/browser attempt, and the independent
mechanical audit. The first runtime/browser attempt was interrupted before
parent finalization and produced no canonical runtime report; the second key
completed with zero provider, non-loopback, process-escape, or logger-loss
events, and its bundle was atomically promoted.

The post-evidence fresh governance review then found two P1
evidence-authority defects:

```text
readiness-authority:
  the CLI still exposed derive as a second canonical readiness writer, so it
  could bypass the runtime-private-key destruction precondition enforced by
  seal-readiness

runtime-key-lifecycle:
  promotion destroyed the unused retry key before the no-replace rename
  commit point, so a failed rename could consume attempt-02 authority even
  though no canonical bundle had been published
```

The r40 owner-boundary repair is:

```text
derive_candidate_readiness:
  pure derivation only; any output_path is rejected

seal_candidate_readiness:
  the only canonical readiness writer; validates canonical output path,
  requires both runtime private-key files absent, revalidates the protected
  payload, then writes exclusively

CLI:
  remove derive; retain only seal-readiness for readiness publication

runtime/browser promotion:
  validate and copy staging, atomically rename with no-replace as the commit
  point, then destroy any unused key; a pre-commit rename failure preserves
  the retry key, while a post-commit cleanup interruption is resumed only
  after byte-identical canonical-bundle validation
```

Required class-level RED/GREEN coverage:

```text
derive cannot publish a readiness file
the CLI exposes no derive subcommand
seal-readiness rejects any surviving runtime private key
rename failure leaves canonical absent and preserves the unused retry key
post-commit key-cleanup interruption resumes without rerunning runtime
```

Because source, test, and normative-plan bytes changed after the
repair-epoch-60 manifest was sealed, none of its otherwise passing evidence
may authorize a smoke. Rebuild all authority under r40/repair-epoch-61.

#### 4.6.12h Close repair-epoch-61 fresh-governance findings

Repair-epoch-61 is immutable and permanently non-authorizing. It passed:

```text
single-path architecture: 341 inspected modules, zero violations
test-path audit: 6827 classified nodes and zero invalid claims
production-path matrix: 177 turns, 40/40 state edges, 9/9 bounded turns
sandboxed zero-API: 6827 passed with zero provider/network/process attempts
runtime/browser attempt-01: desktop 8/8, mobile 8/8, 62 Seatbelt events,
  zero logger loss and zero provider/network/process escape
independent mechanical audit: 15/15 checks, zero findings
```

The required post-evidence fresh governance review and two independent
cross-validators then confirmed seven P1 defects in two existing problem
classes:

```text
evidence-authority:
  checkpoint-v2 trusts a caller-computed digest of the current legacy ledger,
  so rewritten pre-checkpoint history can be rehashed and legitimized
  the manifest does not bind the external private-key paths, so promotion or
  readiness can check a caller-selected absent path while real keys survive
  manifest consumers infer a repository root from copied protected files
  instead of binding the actual Git worktree root
  runtime key consumption closes the validated inode before a separate
  pathname unlink, allowing rename/replacement to preserve signing authority
  the append-only ledger opens its repository-external flock file by pathname,
  so lock-file replacement can give concurrent consumers different inodes
  checkpoint-v2 blocks replay only through readiness in the current epoch, so
  restoring precheckpoint ledger bytes and supplying a new epoch manifest can
  erase the prior checkpoint and all later append-only history
  deleting that checkpoint sidecar before the replay has the same effect unless
  historical published readiness anchors are independently checked
  authorization accepts a ledger rolled back to the readiness anchor and
  deterministically reissues the erased authorization; moving the old attempt
  directory then permits a second allocation
  deleting a per-authorization receipt has the same effect unless persisted
  attempt contexts independently prove that authorization already existed
  unused-key cleanup truncates before unlink, but a process interruption
  between those operations leaves a zero-byte key path that later cleanup
  rejects as malformed and can permanently block promotion/readiness
  accepting any zero-byte replacement as cleanup residue lets a live private
  key be moved aside while a fabricated empty canonical path is accepted

task-authority + source-identity + public-contract:
  the selected processor feeds ResolvedProductBinding.source_text back into
  evidence retrieval identity/scoring
  the selected processor reconstructs public IntentEvent mode after routing,
  including by parsing image_ordinal source-text prefixes
  the reducer parses the same source-text prefix to authorize image mutation
```

The r41 owner-boundary repair is:

```text
manifest trust root:
  bind the canonical Git worktree root, both canonical external runtime-key
  paths, and the exact pre-checkpoint ledger bytes/revision/tip in the reviewed
  candidate manifest

ledger checkpoint:
  readiness accepts checkpoint-v2 only when its source digest and snapshot
  match the manifest-pinned pre-checkpoint ledger; a caller-computed digest
  alone is never authority
  before mutating the ledger, checkpoint-v2 exclusively writes one canonical,
  epoch-independent checkpoint authority beside the ledger, binding the exact
  pre/post anchors plus the originating manifest and readiness path
  an interruption before readiness may resume the same deterministic
  checkpoint; once the originating readiness exists, any return to the bound
  precheckpoint state is a rollback and fails closed across every later epoch
  all canonical historical readiness anchors are checked as a second immutable
  witness, so deleting the checkpoint sidecar does not restore replay authority
  readiness independently validates the authority before sealing
authorization durability:
  every successfully persisted authorization gets one canonical immutable
  receipt beside the ledger, binding only the authorization's immutable
  projection plus the exact authorization_created revision; later allocation
  and consumption state changes must not invalidate that receipt
  allocation revalidates the complete receipt set and persisted-context
  witnesses under the same ledger lock before it may consume an
  authorization; exact pre-commit orphan cleanup precedes the context
  revalidation so a legitimate interrupted allocation remains resumable
  every later authorization first compares the complete ledger authorization
  ID set with the complete receipt ID set; only its own deterministic
  post-ledger/pre-receipt interruption may be missing and recovered, while any
  missing older receipt fails closed
  an interruption after ledger commit but before receipt publication may only
  publish the receipt for that existing authorization; a receipt missing from
  ledger history is rollback, regardless of attempt-directory location
  allocation publishes a canonical immutable attempt-context witness beside
  the ledger after committing the allocation; a pre-commit process exit leaves
  no witness and may discard only its exact uncommitted context, while a
  post-commit process exit resumes from the ledger and publishes the missing
  witness without allocating a second attempt
  moving the evidence directory cannot move or erase this second witness, so
  deleting a receipt cannot make an allocated authorization disappear; unlike
  unrelated historical context files, a canonical witness with a foreign
  ledger identity fails closed
  if both sidecars are removed, all canonical-repository attempt contexts are
  still scanned as the final local witness; simultaneous deletion of ledger
  history, both sidecars, and every canonical-repository context is an
  out-of-process destruction of all local authority and requires an external
  trusted store rather than another repository sidecar
  checkpoint authority, authorization receipt, and context witness publication
  all use one descriptor-bound protocol: write and fsync a recoverable
  temporary file, commit with a no-replace link, fsync the parent, then remove
  the temporary name; a canonical strict-prefix residue from the former direct
  writer or an interrupted temporary write may resume only to the exact
  expected canonical bytes, while any non-prefix or replacement fails closed
ledger lock lifecycle:
  retain the repository-external lock, but anchor it at the first ancestor of
  the temporary tree that the current user cannot rename, then open the private
  lock directory and per-ledger file through held descriptors
  lock that stable ancestor before opening the per-ledger lock, require
  O_NOFOLLOW, owner-only mode, one link, and opened-vs-named inode equality,
  and revalidate all bindings before and after every ledger critical section
  lock setup/validation errors fail closed, while exceptions raised by the
  protected ledger operation retain their original type and rollback contract

runtime key lifecycle:
  caller path arguments, if retained for CLI ergonomics, must exactly match
  that binding
  key consumption keeps a descriptor-bound parent and opened inode through
  unlink, fsyncs the parent, and fails closed on any path/inode replacement
  unused-key cleanup first creates a same-inode tombstone while retaining the
  complete validated key bytes, unlinks the canonical name, writes a
  private-key-signed destruction receipt bound to manifest/slot/path/inode/key
  digest, then unlinks the tombstone and truncates only the now-unlinked inode
  an interrupted cleanup resumes only from a still-valid full key/tombstone or
  that signed destruction receipt; an empty or self-named tombstone is never
  accepted as proof of destruction
  readiness rechecks both bound paths and the signed receipt for every unused
  key immediately before exclusive publication; path absence alone is never
  accepted as proof of unused-key destruction
  readiness writes only to a descriptor-bound recoverable pending inode,
  accepts only an exact canonical prefix on resume, revalidates the protected
  payload after the final runtime-key check, and commits with a no-replace
  hard link so an interrupted write can never leave a partial canonical file

typed binding authority:
  ResolvedProductBinding carries a closed source kind, optional source ordinal,
  and typed canonical identity name separately from human source_text
  Router uses only the typed source fields and emits the final public intent
  mode as part of UnifiedRouteDecision
  processors consume typed canonical identity/public intent fields unchanged;
  reducer validates image mutation from typed binding source fields only
```

Required class-level RED/GREEN coverage:

```text
checkpoint-v2 rejects a caller-rehashed legacy ledger that differs from the
  manifest-pinned pre-checkpoint bytes
checkpoint-v2 rejects precheckpoint replay through a different epoch manifest,
  while an interrupted pre-readiness checkpoint resumes without rewriting the
  canonical authority
checkpoint replay still fails if the canonical authority was deleted while a
  published historical readiness anchor survives
ledger rollback cannot reissue authorization even if the prior attempt
  directory is moved, and interruption between authorization ledger commit and
  receipt publication resumes without appending a duplicate authorization
authorization rollback still fails if its receipt is deleted while the
  original attempt directory is moved outside ledger authority, because the
  canonical attempt-context witness remains beside the ledger
authorization rollback still fails after both sidecars are deleted when the
  immutable attempt context remains anywhere under the canonical repository
authorization receipt remains valid after legal allocation/consumption
  mutations because its digest binds only immutable authorization fields
partial checkpoint-authority and authorization-receipt writes recover through
  the shared temporary/no-replace protocol; non-prefix forged content fails
  closed
allocation resumes both pre-ledger and post-ledger process interruption
  without duplicating an attempt or leaving a permanent witness wedge
unused-key cleanup resumes after canonical unlink from a full tombstone plus
  signed destruction receipt, while empty tombstones, unbound empty files,
  replacement paths, and parent attacks fail closed
readiness rejects absent unused key paths without the matching signed
  destruction receipt
the independent audit rejects semantic weakening of the immutable
  authorization field set, strict-prefix sidecar recovery, nonempty-key guard,
  real fstat-derived key inode, signed destruction receipt, and
  unlink-before-truncate ordering even when all expected helper names remain
the independent audit rejects missing allocation-time receipt/context
  revalidation, non-atomic readiness publication, missing final protected
  payload validation, and marker calls hidden behind dead, terminated,
  nested, shadowed, statically empty iteration code, or direct local callable
  aliases; alias targets are resolved at the executable call site before
  marker call-graph traversal
the architecture gate resolves direct local callable aliases before traversing
  processor reachability, so assigning another processor helper to a local
  name cannot hide processor-to-processor delegation
manifest validation rejects a nested copied repository root
promotion and readiness reject an alternate private-key base path
readiness rejects a key recreated after initial derivation but before publish
runtime key consumption rejects pathname replacement and leaves no accepted
  runtime identity
ledger lock pathname, symlink, or temporary-root replacement cannot split one
  critical section, and the independent audit rejects removal of stable-anchor,
  descriptor-bound, or O_NOFOLLOW lock enforcement
simulated ledger commit/interruption errors remain visible to their existing
  rollback and retry owners instead of being reclassified as lock failures
equivalent source_text values cannot change evidence retrieval identity
public IntentEvent mode equals the router-owned typed field
reducer image authority ignores source_text and requires typed image origin
alternate explicit, candidate-ordinal, current-item, persisted-image, and
  mixed image/product entries retain the same typed invariants
```

Because test and normative-plan bytes change for this recovery, neither
repair-epoch-61 nor the archived r42 captures may authorize a smoke. Rebuild
all authority once under r43/repair-epoch-62.

#### 4.6.12i Finite Task 11 closure boundary

The 2026-08-28 release-entry audit confirmed that the Guide product path is
functionally stable while Task 11 remains blocked by two deterministic
evidence-tool REDs:

```text
test_checkpoint_backfills_legacy_authorization_receipts
test_readiness_rechecks_runtime_keys_after_publication_link
```

The same audit re-ran 333 high-signal product and architecture tests:

```text
task11 production-path matrix: 52 passed
single-path architecture: 129 passed
UnifiedGuideFlow: 49 passed
HTTP/SSE/frontend boundaries: 103 passed
```

The local/module callable-alias checks and both complete-ancestor
protected-payload walkers are already GREEN. Complete only the following
owner-boundary work before rebuilding evidence:

**Files:**
- Modify: `tools/guide_gates/attempt_ledger.py`
- Modify: `tools/guide_gates/build_task11_readiness.py`
- Test: `tests/guide/tools/test_attempt_ledger.py`
- Test: `tests/guide/tools/test_build_task11_readiness.py`

```text
ledger checkpoint owner:
  checkpoint-v2 deterministically publishes receipts for every authorization
  already present in the manifest-pinned pre-checkpoint ledger
  an authorization with its original authorization_created revision binds
  that revision; older authorizations bind the one state_checkpoint revision
  whose immutable snapshot proves they already existed
  receipt publication precedes the ledger commit so interruption remains
  retryable against the same deterministic checkpoint bytes

readiness publication owner:
  revalidate both manifest-bound runtime-key paths and required destruction
  receipts after the no-replace readiness link
  if that post-link validation fails, unlink and fsync the just-published
  readiness name while retaining the recoverable pending inode
```

The user explicitly approved one final extension of this fixed boundary on
2026-08-28. Close exactly these three already-declared in-scope findings:

```text
readiness recovery:
  when an interrupted prior run left canonical and pending names linked to the
  same inode, a failed publication-authority recheck removes and fsyncs the
  canonical name while retaining pending for deterministic recovery

copywriter contract:
  CopywriterDraft accepts only the typed sections tuple
  remove summary_copy/product_copy/closing_copy from production contracts,
  provider shape admission, validation, evidence validation, and compilation
  migrate or delete tests for the retired production shape; no compatibility
  property or adapter may remain under app/

consultation contract:
  ConsultationObservation accepts only dynamic observation identity,
  dimension, state, source text, and typed qualifiers
  remove code/answer branching from production assessment/state transitions
  convert historical code/answer rows only inside
  migrate_legacy_conversation_snapshot_payload before strict validation
```

No fourth product finding may be added to r43, no additional governance review is
authorized after these three focused GREENs, and repair-epoch-62 remains the
only permitted evidence epoch.

#### 4.6.12j User-authorized unattended recovery

On 2026-08-28 the user explicitly removed interactive approval checkpoints
for the remaining release workflow. The agent must continue autonomously under
this fixed policy:

```text
known test-harness mismatch:
  test_bound_runtime_registers_and_consumes_real_http_proof waited 10 seconds
  while BOUND_STARTUP_TIMEOUT_SECONDS is 30
  both r42 zero-API captures reached 6909 passed / 1 failed with zero provider,
  outbound-network, and process-creation violations
  the ledger remained allocated with no runtime registration, proving the
  failure occurred before runtime registration rather than in product traffic
  focused rerun with worker errors exposed proved the runtime thread had
  already exited on readiness evidence drift: the test's intentionally fake
  readiness fixture was not isolated from the newer canonical binding check
  the old polling loop ignored that worker error and converted it into the
  misleading ten-second identity assertion

one authorized recovery:
  archive the complete failed r42 repair-epoch-62 bytes without rewriting them
  scope the fake readiness seam to this runtime HTTP-proof test
  stop polling immediately when the worker reports an error and include that
  error in the assertion
  align the test deadline to
  BOUND_STARTUP_TIMEOUT_SECONDS + 15 seconds
  rebuild the canonical repair-epoch-62 once under r43
  repair-epoch-63 remains forbidden

unattended decision policy:
  deterministic test-harness or environment failures are classified from raw
  evidence and handled by the smallest owner-boundary recovery without asking
  the user
  existing attempt limits remain binding; no infinite retry loop is allowed
  a reproducible product-path P0/P1 fails closed and produces a final no-go
  report rather than waiting indefinitely for an interactive reply
  no compatibility bridge, second dispatcher, sentence/product special case,
  or expanded threat model may be introduced
```

This recovery changes test, plan, and manifest bytes but not production
runtime behavior. The r42 failed captures are diagnostic history only and
cannot authorize readiness. The r43 canonical artifacts must all bind the new
manifest and pass their normal validators.

This revision adopts a finite release threat model:

```text
trusted boundary:
  the canonical worktree, current macOS account, CI runner, provider
  credentials, and release operator are trusted during one bounded command

release blockers:
  reproducible product-path defects; deterministic corruption, rollback,
  stale-byte, symlink, path-replacement, crash-recovery, or authorization
  failures exercised by the committed test/mutation corpus; missing required
  evidence; real smoke or browser failures

follow-up hardening, not a Task 11 epoch trigger:
  a newly imagined same-UID malicious process that can arbitrarily rewrite
  files or directories between individual syscalls but has no reproduction in
  the supported release workflow and does not defeat a committed verifier
```

After the two named REDs and the existing affected suites are GREEN, perform
one checklist-bounded read-only review. That review may verify only:

```text
the two named REDs and their owner-boundary implementations
the already enumerated r41 findings in Section 4.6.12h
the unique production chain and forbidden bridge inventory
the exact Task 11 entry artifacts required by Section 4.6.13
```

It may not expand Task 11 with a new hypothetical local-adversary model.
An in-scope reproducible P0/P1 still stops release. An out-of-scope hardening
idea is recorded for post-release work and does not create another evidence
epoch. `repair-epoch-62` is the final Task 11 evidence epoch; there is no
`repair-epoch-63`.

Run the exact closure checks before any epoch output:

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -m pytest -q \
  tests/guide/tools/test_attempt_ledger.py::test_checkpoint_backfills_legacy_authorization_receipts \
  tests/guide/tools/test_build_task11_readiness.py::test_readiness_rechecks_runtime_keys_after_publication_link

PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -m pytest -q \
  tests/guide/tools/test_attempt_ledger.py \
  tests/guide/tools/test_build_task11_readiness.py \
  tests/guide/tools/test_run_zero_api_runtime.py \
  tests/guide/tools/test_run_task11_independent_audit.py \
  tests/guide/tools/test_single_path_architecture.py

/Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -m compileall -q \
  app tools tests
git diff --check
```

Expected: both named closure tests pass, every affected module passes with no
failure or error, compilation succeeds, and `git diff --check` is empty.

#### 4.6.12k Approved frontend baseline and unattended remediation

The user reconfirmed on 2026-08-29 that the previously aligned frontend format
is the approved release baseline. Screenshot review is regression evidence,
not authorization to redesign the UI.

```text
approved frontend baseline:
  app/static/chat.html
  app/static/guide-presentation.js
  app/static/guide-demo-fixture.js
  app/guide/presentation/public_contracts.py
  app/guide/presentation/sse_events.py

baseline rule:
  preserve the existing public contract, markup ownership, information order,
  layout, component structure, copy style, spacing, colors, and interaction
  format unless a reproducible release-blocking defect proves that its earliest
  owner is one of these files
  screenshot review may not become a visual refresh, cleanup refactor, or
  component rewrite

capture/environment classification:
  a browser crash, incomplete page load, font/load race, missing capture, or
  screenshot-tool failure does not authorize a frontend edit
  revalidate runtime health, console, network, DOM readiness, and artifact
  binding, then rerun only the bounded capture allowed by the current phase

reproducible frontend defect:
  inspect the screenshot, DOM geometry, browser console, request/network log,
  raw SSE, PublicPresentationContract, and rendered contract binding
  repair only the earliest owner with a focused failing regression
  preserve the approved visual and data-contract format
  do not opportunistically change copy, palette, spacing, layout, card
  structure, or unrelated frontend behavior

automatic release remediation:
  translation, backend, browser, or screenshot failures are classified and
  handled without an interactive approval checkpoint
  transient external failures use only the phase's existing bounded retry
  a reproducible product defect receives one smallest owner-boundary repair,
  focused GREEN, affected regression, and complete revalidation
  any source, test, tool, fixture, or plan byte change invalidates downstream
  evidence and automatically returns execution to the earliest affected gate
  failed evidence remains immutable and is archived before canonical evidence
  is rebuilt under the current final repair-epoch-62 name and a monotonic plan
  revision; repair-epoch-63 remains forbidden
  a second failure at the same owner, an exhausted external dependency, or an
  unrepairable architecture violation produces the final no-go report
```

This section supersedes older language that required the executor to stop and
wait for a user decision after the first serious bounded, translation, backend,
browser, or screenshot failure. It does not weaken the one-production-path
rules, attempt ledger, immutable failure evidence, machine gates, or final
external-deployment approval boundary.

#### 4.6.12l Close r43 Task 12 execution-inventory parity

The r43 candidate passed 6910 zero-API tests, runtime/browser evidence, and the
independent audit. Candidate readiness then failed closed because the two
independent Task 12 inventories disagreed:

```text
independent audit:
  includes tools/guide_gates/run_zero_api_runtime.py

readiness:
  omitted tools/guide_gates/run_zero_api_runtime.py
```

The complete r43 bundle and failed readiness stderr are preserved under
`repair-epoch-62/attempt-03-readiness-failed/`. The r44 repair is bounded to:

```text
add run_zero_api_runtime.py to readiness._TASK12_EXECUTION_PATHS
add a focused regression for that exact required member
add a class-level regression requiring the independently maintained readiness
  and independent-audit Task 12 execution inventories to be identical
register those two newly added regression nodes in
  RECLASSIFICATION_POST_EVIDENCE_NODES so immutable attempt-08 JUnit evidence
  is compared only against the node inventory that existed when it was written
do not change runtime, product behavior, frontend files, or evidence schemas
```

The focused missing-member test must fail before implementation and both
inventory tests must pass afterward. Then rerun the affected readiness and
independent-audit modules before rebuilding the canonical repair-epoch-62 under
r44. No separate repair epoch is created.

#### 4.6.12m Close r44 bounded runtime shell-startup failure

r44 sealed candidate readiness and allocated bounded-smoke-attempt-10. The
first runtime launch failed before registration because the fixed
`/tmp/xiaoro-mainline-bounded-state` directory remained from an earlier local
run. The directory was archived without changing repository bytes and the
same unconsumed attempt was restarted. Runtime identity and signed proof then
validated and the attempt was consumed, but no business turn ran:

```text
browser:
  Page.goto("/chat") timed out after 30 seconds
  turn_count = 0
  no turn bundle or provider response exists

runtime gate:
  every non-control HTTP request, including /chat and /static/*, entered
  runtime_request_authority_lease
  that lease revalidated the complete readiness and held the ledger lock
  across the request
  shell and blocking script loads therefore consumed the navigation budget

failure completion:
  allocation bound evidence_directory to the attempt root
  complete_attempt attempted to narrow it to browser-desktop
  snapshot validation treated that legitimate terminal transition as a
  historical immutable-field rewrite
```

The r45 repair is limited to the two responsible gate boundaries:

```text
runtime proof gate:
  keep registration and signed proof capability checks on every non-control
  HTTP request
  acquire the expensive attempt authority lease only for /api business paths
  /chat and /static/* may render only after proof capability validation but
  never hold or re-enter the business ledger lease

attempt ledger:
  evidence_directory may transition only with the operation-target attempt
  during attempt_completed
  revision-chain target identity, terminal-evidence hashing, and all other
  immutable allocation fields remain enforced
```

Add one RED/GREEN regression for each invariant, register both nodes as
post-evidence tests for immutable attempt-08 evidence, preserve attempt-10 and
its four-file no-turn failure bundle, and derive one signed
failure-reclassification audit mapping:

```text
browser_audit / TimeoutError
-> runtime_gate / runtime_shell_authority_lease_timeout
```

The reclassification must verify the attempt context, readiness, runtime
identity/proof, zero-turn browser summary, exact timeout artifact, terminal
evidence index, two-node RED/GREEN JUnit reports, focused affected-suite
JUnit report, and reverse-applicable two-tool repair patch. It then updates
the ledger only through `attempt_ledger.py reclassify`. Archive the r44
canonical evidence and readiness without moving or overwriting any path
referenced by attempt-10. Rebuild r45 in the same `repair-epoch-62/` with
the exact `-r45` suffix on candidate, summary, audit, and readiness JSON names
and with `runtime-browser-evidence-r45/` as its browser evidence directory.
Only a suffix equal to the manifest's `plan_revision` tail is valid; arbitrary
sibling names remain forbidden. `repair-epoch-63` remains forbidden.

#### 4.6.12n Close r45 sandbox-child manifest-path mismatch

r45 passed the 6920-test zero-API suite and production-path matrix. Its first
fixture-runtime attempt exited before runtime identity publication, browser
startup, or any provider call. The parent wrapper accepted
`task11-candidate-manifest-r45.json`, but
`_load_parent_attested_candidate_manifest` in the sandbox child still required
the unsuffixed `task11-candidate-manifest.json` path and reported
`protected payload drift`.

The r46 repair is limited to the runtime gate:

```text
reuse build_task11_readiness._candidate_manifest_path_is_valid at the
  parent-attested sandbox-child boundary
require repair_epoch to remain an exact integer
retain all parent manifest digest, candidate HEAD, protected payload, path,
  symlink, and canonical payload checks
add one RED/GREEN regression proving that only a suffix matching the
  manifest plan_revision is accepted by the child verifier
```

The failed r45 architecture, test-path, manifest, production-path, semantic,
zero-API, and network evidence remains immutable non-authorizing history.
Destroy both r45 fixture private keys; no r45 retry is permitted after a
protected source/test/plan change. Rebuild the final repair-epoch-62 authority
with the exact `-r46` suffix and `runtime-browser-evidence-r46/`. No new repair
epoch, compatibility bridge, business-path change, or frontend change is
authorized.

#### 4.6.12o Terminal NO-GO after bounded-smoke-attempt-11

r46 completed the final local authority rebuild:

```text
single-path architecture: passed, 0 violations
production-path matrix: passed, 177 turns, 40/40 required state edges
zero-API: passed, 6921 tests, 0 provider/network/process attempts
desktop fixture: passed, 8 turns
mobile fixture: passed, 8 turns
independent audit: passed, 0 P0/P1 findings
candidate readiness SHA-256:
  84cbdc88452f2fc25a74c6f6efce725f901b92e7d3f3ab4ee73c9bbb11c0085f
```

`bounded-smoke-attempt-11` then consumed its one-time authorization and failed
before its first completed turn:

```text
runner failure:
  Page.wait_for_function: Timeout 120000ms exceeded.
turn_count: 0
provider quota reservations: 0
provider remote sockets: 0
conversation rows: 0
attempt context SHA-256:
  28638b2509323101c83ac3e75b04ce3c6779d0578c2e69c410220cb636b2ba75
runner failure SHA-256:
  b52790ec1dc555d788dd50ab9a9aee9f69a154c70a2e9bd98eee29231b3661f5
```

Deterministic timing and source-order evidence identifies the earliest owner:

```text
the frontend first calls synchronizeConversationVersion
that request has a fixed 5-second timeout
the runtime proof middleware classifies every /api/* request as business
the same readiness verification took 26.204 seconds
the complete failed-attempt authority lease took 29.188 seconds
the version request therefore aborts before the chat POST/provider boundary
```

This is the second bounded failure owned by `runtime_gate` after attempt-10.
Section 4.6.12k requires the same-owner circuit breaker to stop further repair.
No r47 candidate, third runtime-gate patch, Task 11 commit, Task 12 execution,
release evidence commit, or release seal is authorized. The final deployment
decision is `NO_GO`.

#### 4.6.12p Reopen runtime gate with startup-bound authority

The r46 `NO_GO`, attempt-11 context, runtime identity, browser summary, runner
failure, terminal evidence index, and ledger revisions remain immutable
history. After reviewing the deterministic no-turn evidence, the user
explicitly approved one r47 architecture repair. This approval supersedes only
the final sentence of Section 4.6.12o for the new revision; it does not rewrite
the failed attempt or permit another repair epoch, timeout increase, frontend
change, API exemption, compatibility bridge, or parallel request path.

The repaired authority lifecycle is exactly:

```text
runtime startup / registration:
  verify complete Task 11 readiness and protected evidence once
  bind context SHA-256, readiness SHA-256, allocation revision/hash,
  runtime registration, public key, identity, and signed proof

each proof-capable /api request:
  acquire the attempt-scoped request-lifecycle shared barrier
  read the immutable attempt context and readiness summary
  hold the shared ledger lock only while validating the relevant attempt,
  consumed authorization, registration/attestation identity, and hash-chain
  release the shared ledger lock before calling FastAPI or entering SSE
  keep only the independent lifecycle barrier until the ASGI request and
  shielded stream cleanup have returned

attempt completion:
  perform the complete terminal readiness/evidence verification
  acquire the request-lifecycle barrier exclusively
  wait for every admitted request and shielded SSE cleanup to finish
  perform the one append-only terminal ledger transition
```

The request-time authority path must not call `_verify_current_readiness`,
`verify_task11_readiness`, `_capture_readiness_binding`, the zero-API suite, or
any provider. It may hash only the bounded context/readiness/identity inputs
and inspect the one relevant consumed attempt under the existing shared ledger
lock. The independent lifecycle barrier is keyed by the canonical attempt
context path, stored outside candidate and terminal evidence, contains no
authority state, and cannot authorize a request by itself.

The `_ProofGatedApplication` has one business authority path. `/chat` and
`/static/*` retain signed proof-capability validation without attempt
authority. Every `/api` request, including
`/api/v1/chat/sessions/{session_id}/version`, must pass the same lightweight
attempt authority check. There is no `/version` special case. The approved
frontend 5-second bound remains unchanged. The test must prove the version
request reaches the application while a deliberately failing complete
readiness verifier is installed, and the application must be able to acquire
the ledger exclusively, proving no ledger lock crosses the ASGI boundary.

Implement with TDD in this fixed order:

```text
RED 1:
  test_runtime_request_authority_does_not_reverify_complete_readiness
RED 2:
  test_runtime_releases_ledger_lock_before_entering_application
RED 3:
  test_runtime_version_check_uses_lightweight_authority_check
RED 4:
  test_completion_waits_for_request_lifecycle_cleanup
RED 5:
  test_reclassify_accepts_indexed_runner_startup_evidence
RED 6:
  test_authorization_validates_repair_before_exclusive_ledger_lock
GREEN:
  replace runtime_request_authority_lease with one lightweight validator
  add one attempt-scoped request-lifecycle shared/exclusive barrier
  inject those two responsibilities into the existing proof gate
  make complete_attempt cross the exclusive barrier before terminal mutation
  run live repair regression validation before taking the ledger write lock,
  then require the same ledger revision and repair hashes under that lock
REGRESSION:
  shell/static still never take business authority
  every /api request still requires proof capability and consumed attempt
  startup still performs complete readiness verification
  cancellation still runs shielded SSE cleanup before completion can proceed
```

No production application, processor, router, reducer, state adapter,
presentation compiler, frontend file, timeout, prompt, fixture sentence, or
product ID may change for this repair.

Before r47 authorization, derive and append one auditable attempt-11
reclassification:

```text
browser_audit / TimeoutError
-> runtime_gate / runtime_version_sync_authority_check_timeout
```

The reclassification must bind the existing attempt context, r46 readiness,
runtime identity/attestation, browser summary, runner failure, zero completed
turns, zero provider reservation/socket records, zero conversation rows, the
measured source-order/timing reproduction, exact RED/GREEN JUnit nodes, the
focused affected-suite JUnit report, and a reverse-applicable repair patch.
Only then may r47 readiness authorize `bounded-smoke-attempt-12`.

The r47 candidate uses only these new revision-qualified outputs:

```text
task11-candidate-manifest-r47.json
task11-candidate-readiness-r47.json
task11-semantic-matrix-summary-r47.json
task11-zero-api-summary-r47.json
task11-independent-audit-r47.json
task11-test-path-audit-r47.json
task11-production-path-summary-r47.json
task11-zero-api-network-r47.json
task11-single-path-architecture-r47.json
runtime-browser-evidence-r47/
```

The first four-node attempt-11 reclassification proof was rejected before any
ledger write because its validator started ledger-using pytest children while
holding the global ledger lock. The second focused capture found the resulting
circuit-error precedence and static-audit expectation regressions. Preserve
both non-authorizing runs under
`attempt-11-reclassification-attempt-01-lock-timeout/` and
`attempt-11-reclassification-attempt-02-focused-failed/`; never reuse either
as repair authority.

The third focused capture passed all 639 tests, but the validator still
declared only the earlier four regression nodes and therefore rejected the
six-node RED/GREEN inventory before any ledger write. Preserve that
non-authorizing run under
`attempt-11-reclassification-attempt-03-inventory-mismatch/`. The canonical
attempt-11 evidence is the later same-source six-node RED/GREEN capture plus
the 639-test focused report; none of the three rejected runs may authorize
reclassification or r47 readiness.

The r45/r46 files and both attempt-10/attempt-11 trees are historical inputs
only and must not be overwritten. A failure of the six focused invariants,
the r47 authority rebuild, or bounded-smoke-attempt-12 ends this reopened
cycle as `NO_GO`. A clean attempt-12 proceeds directly to the existing Task 11
commit and Task 12 release sequence without another review stop.

The r47 authority rebuild reached the complete zero-API suite and terminated
with one failure after 6927 passes:

```text
tests/guide/tools/test_historical_repair_patch.py::
  test_runtime_gate_repair_accepts_current_descendant_candidate
Task11IndependentAuditError:
  runtime-gate focused JUnit node inventory is invalid
```

The candidate manifest SHA-256 is
`68eb96a607a6a760094770f9baf1c3c05cb887f235f55dfa54147150f1ffe812`.
The immutable failed zero-API summary SHA-256 is
`1b91009b436287fbdd010b8ba90da9b943c702d56969fc81137ddb00772fa67e`;
its network report SHA-256 is
`8292f45985f23076af9499d5ae00833e15f06933f7d44013f5eaee34c7c98aad`
and records zero provider, outbound-network, and process-creation attempts.
The historical attempt-10 focused evidence names two tests retired by the r47
lifecycle replacement, while the validator requires every historical node to
remain literally present. Fixing that validator or adding an explicit
retired-node-to-replacement binding would change protected authority code
after the frozen r47 manifest. This section's finite rule therefore ends r47
as `NO_GO`; no r48 manifest, bounded-smoke-attempt-12, Task 11 commit, Task 12
execution, or release seal is authorized.

#### 4.6.12q Retire the legacy seal and run practical release validation

After the r47 terminal result, the user explicitly chose practical delivery
validation instead of another Task 11 evidence revision. This decision does
not rewrite r47, mark its readiness as passed, mutate its failed evidence, or
authorize the old release seal. It retires the cryptographic seal workflow as
a delivery requirement and authorizes one non-ledger practical release
attempt.

The product and frontend are frozen. Practical execution may not modify
`app/`, production fixtures, prompts, product data, or frontend assets. It may
not add a router, compatibility bridge, alternate application entrypoint,
sentence/product special case, timeout increase, or synthetic Task 11
readiness. It reuses the existing translation, backend replay, ASGI runtime,
and release browser execution cores.

Preserve the append-only ledger and every ledger-referenced file in place.
Cleanup is limited to unreferenced `/tmp` keys/state, incomplete staging
outputs, and non-authorizing candidate artifacts that are moved intact into a
named archive. No historical evidence byte may be edited.

Write the single attempt beneath:

```text
docs/audits/final-release/mainline-contract-closure/
  practical-release-attempt-01/
```

The attempt runs, in order:

```text
focused zero-provider tests
canonical v5 48-turn DeepSeek translation
zero-provider replay of those exact 48 captured meanings
normal Guide ASGI runtime
seven release modes on desktop and mobile
fourteen-row screenshot review
practical-release-report.json
```

`GO` requires 48/48 translation turns, a passing backend replay with zero
network attempts, fourteen passing browser turns with every release counter at
zero, and fourteen passing screenshot rows. A reproducible product/frontend
failure is `NO_GO`. A provider or local environment failure is `BLOCKED`.
Neither result opens r48/r49 or returns to the legacy Task 11 evidence loop.
No `release-seal.json` is produced by this practical workflow.

The single practical attempt is terminal `NO_GO`. Focused verification passed
636 tests, but the real translation batch passed only 36 of 48 turns. The
follow-on zero-provider HTTP replay passed 21 of 48 turns and emitted fifteen
`start` plus `GUIDE_INTERNAL_ERROR` terminal streams. Because those upstream
failures make `GO` impossible, the browser and screenshot phases were not run.
The terminal report is:

```text
docs/audits/final-release/mainline-contract-closure/
  practical-release-attempt-01/practical-release-report.json
```

Its SHA-256 is
`f6498b07bb93fa7edb512de76fb2a23caddfb7c6df7f8cdd584e3c18742e07f9`.

#### 4.6.12r One shared-owner semantic repair

The user reviewed the practical attempt and approved one root-cause semantic
repair. This does not reopen Task 11 or the retired release seal. The r1
results remain immutable diagnostic evidence.

The repair must address categories, not examples:

```text
final fixture sync:
  derive embedded gate cases from the current canonical gate fixture and
  current RecommendationQueryContext schema

recommendation outcome:
  explicit numeric bounds -> explore / bounded_exploration
  generic singular product wording alone -> explore / broad_exploration
  fit still requires explicit best-fit selection plus usable constraints

responsibility:
  bound-product factual follow-up -> product_knowledge
  safety escalation may strengthen consultation
  final route responsibility, not fixture family wording, is authoritative

revision:
  require revision evidence only for declared typed state transitions
  complete topic replacement with continuity=new_task is sufficient without
  an unrelated constraint-change atom

knowledge versus assessment:
  general mechanism/explanation question -> knowledge
  current first-person symptom judgment -> assessment/consultation
```

Required RED/GREEN coverage must use new category-level synthetic messages,
not the six failed fixture sentences. No production rule or test may branch on
their case IDs, exact text, product IDs, or fixture path. The approved file
boundary is:

```text
app/guide/adapters/llm/turn_meaning_prompt.py
app/guide/understanding/semantic_equivalence.py
tools/guide_gates/run_final_real_translation.py
tests/guide/adapters/test_turn_meaning_prompt.py
tests/guide/understanding/test_semantic_equivalence.py
tests/guide/tools/test_final_real_translation.py
tests/fixtures/guide/final_release/real_translation_12x4_v5.jsonl
```

First run focused deterministic RED/GREEN tests. Then run one real canary
containing the six affected semantic families, followed only on success by one
complete 48-turn batch. The complete batch must be replayed through the backend
before the fourteen browser views. Any remaining reproducible semantic,
binding, backend, or frontend failure ends practical release as `NO_GO`; no
additional revision or Task 11 loop is authorized.

The authorized sequence is complete:

```text
category RED: 7 failed as expected
category GREEN: 7 passed
focused regression: 677 passed
real canary: 8/8 behaviorally validated
single complete DeepSeek batch: 42/48 strict pass
fixture contract mismatches: 4
remaining product/model risks: 2
post-repair backend replay: not run
browser and screenshot review: not run
decision: NO_GO
```

The four fixture mismatches are preserved rather than converted into
production exceptions. The two remaining risks are one image-similarity basis
error and one invalid provider JSON output. The practical repair authority is
exhausted; do not rerun the provider, patch the six cases, reopen Task 11, or
start another practical revision.

#### 4.6.12s Authorized final semantic closure

The user explicitly reopened only the practical semantic closure on
2026-08-29. This does not reopen Task 11, the retired seal, or any runtime
architecture work. Preserve `practical-release-attempt-01/` unchanged and use
`practical-release-attempt-02/` for all new evidence.

The chosen design is:

```text
image similarity:
  operation_hint=image_similarity with recommendation_mode=explore owns
  recommendation_mode_basis=similar_alternatives
  a budget remains a separate budget constraint
  an explicit single-best request with usable fit constraints may remain fit

provider format:
  malformed JSON remains a typed invalid_output
  exactly one provider request per turn
  no local JSON repair and no hidden provider retry
  the new 48-turn batch is the only retry of the r2 transient failure

fixture truth:
  derive recommendation outcome from the embedded allowed operation
  derive continue eligibility from typed current batch/image authority
  never join expectation truth by reused case ID
```

**Files:**

```text
app/guide/understanding/turn_meaning_contracts.py
app/guide/adapters/llm/deepseek_turn_meaning.py
app/guide/adapters/llm/turn_meaning_prompt.py
tools/guide_gates/run_final_real_translation.py
tests/guide/understanding/test_turn_meaning_contracts.py
tests/guide/adapters/test_deepseek_turn_meaning.py
tests/guide/adapters/test_turn_meaning_prompt.py
tests/guide/tools/test_final_real_translation.py
tests/fixtures/guide/final_release/real_translation_12x4_v5.jsonl
docs/superpowers/specs/2026-08-29-practical-release-closure-design.md
docs/audits/final-release/mainline-contract-closure/
  practical-release-attempt-02/
```

- [x] **Step 1: RED the operation-owned image basis**

Add category-level tests using new synthetic messages:

```python
def test_image_similarity_budget_requires_similar_alternatives() -> None:
    payload = _valid_turn_meaning_payload(
        operation_hint="image_similarity",
        recommendation_mode="explore",
        recommendation_mode_basis={
            "basis": "bounded_exploration",
            "source_text": "预算六百内",
        },
        budget_candidates=[{
            "raw_text": "预算六百内",
            "relation": "maximum",
            "minimum": None,
            "maximum": "600",
        }],
    )
    with pytest.raises(ValueError, match="image similarity"):
        TurnMeaning.model_validate(payload, strict=True)


def test_strict_tool_schema_scopes_image_similarity_basis() -> None:
    schema = _strict_turn_meaning_schema()
    image_variant = next(
        item for item in schema["anyOf"]
        if item["properties"]["operation_hint"].get("enum")
        == ["image_similarity"]
    )
    assert image_variant["properties"]["recommendation_mode"] == {
        "type": "string",
        "enum": ["explore"],
    }
    assert image_variant["properties"]["recommendation_mode_basis"][
        "properties"
    ]["basis"]["enum"] == ["similar_alternatives"]
```

Run:

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -m pytest -q \
  tests/guide/understanding/test_turn_meaning_contracts.py \
  tests/guide/adapters/test_deepseek_turn_meaning.py \
  -k 'image_similarity_budget or strict_tool_schema_scopes'
```

Expected: both tests fail because the current cross-field contract and strict
tool schema allow `bounded_exploration` for image similarity.

- [x] **Step 2: RED fixture truth derivation**

Add tests that build synthetic final turns without naming any existing case:

```python
def test_embedded_identity_operation_forbids_recommendation_outcome() -> None:
    expected = derive_final_turn_expectations(
        _synthetic_final_turn(
            operation_hints=("image_identity",),
            expected_objects=("image:1",),
            conversation_version=2,
        )
    )
    assert expected.recommendation_mode is None
    assert expected.recommendation_mode_basis is None


def test_bound_context_allows_continue_without_case_identity() -> None:
    expected = derive_final_turn_expectations(
        _synthetic_final_turn(
            operation_hints=("comparison",),
            expected_objects=("candidate_batch",),
            conversation_version=2,
        )
    )
    assert "continue" in expected.allowed_continuity_hints
```

Run:

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -m pytest -q \
  tests/guide/tools/test_final_real_translation.py \
  -k 'embedded_identity_operation or bound_context_allows_continue'
```

Expected: fail because final expectation derivation does not yet exist.

- [x] **Step 3: GREEN the shared contracts**

Implement only:

```text
TurnMeaning validator:
  explore image_similarity accepts only similar_alternatives
  source-grounded image fit remains valid

DeepSeek strict schema:
  separate image_similarity from generic explore
  bind its operation, mode, and basis in one schema branch

Prompt:
  state that image_similarity owns similar_alternatives even when budget,
  texture, skin, or scenario constraints coexist
```

Do not normalize malformed JSON, add retries, inspect raw sentences, or
special-case a fixture identifier.

Run the Step 1 command. Expected: PASS.

- [x] **Step 4: GREEN and regenerate fixture truth**

Implement `derive_final_turn_expectations()` from the embedded
`allowed_operation_hints`, expected binding objects, typed context, and
required budget. Use it to validate and mechanically synchronize v5. Replace
the case-ID join in
`test_v5_recommendation_truth_matches_current_gate_contract` with embedded
contract assertions.

Run:

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -m pytest -q \
  tests/guide/tools/test_final_real_translation.py \
  tests/guide/tools/test_turn_meaning_gate.py
```

Expected: PASS, with identity turns carrying no recommendation outcome and
context-bound comparison/image turns admitting `continue`.

- [x] **Step 5: Run affected GREEN and anti-patch gates**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -m pytest -q \
  tests/guide/adapters/test_turn_meaning_prompt.py \
  tests/guide/adapters/test_deepseek_turn_meaning.py \
  tests/guide/understanding/test_turn_meaning_contracts.py \
  tests/guide/understanding/test_semantic_equivalence.py \
  tests/guide/tools/test_turn_meaning_gate.py \
  tests/guide/tools/test_final_real_translation.py \
  tests/guide/tools/test_no_sentence_patch.py
```

Expected: PASS with zero sentence, case-ID, product-ID, or alternate-path
findings.

- [x] **Step 6: Run one bounded real canary**

Use unseen wording for image similarity with a numeric budget, image identity
with current image context, and comparison with a current candidate batch.
Each turn gets exactly one provider request. The canary must pass strict schema,
source grounding, operation, recommendation outcome, binding, and continuity.

- [x] **Step 7: Run exactly one complete 48-turn batch**

Run the canonical v5 fixture once into:

```text
docs/audits/final-release/mainline-contract-closure/
  practical-release-attempt-02/real-translation/
```

Require:

```text
turn_count = 48
provider_call_count = 48
passed_turn_count = 48
schema_valid_count = 48
source_grounded_count = 48
binding_passed_count = 48
task_plan_passed_count = 48
recommendation_mode_passed_count = 48
```

Any failure ends r3 as `NO_GO`; do not repair or rerun.

- [x] **Step 8: Finish backend and browser validation only after 48/48**

Replay the exact 48 captured meanings with zero provider calls. Only if that
passes, run the seven release modes on desktop and mobile and record fourteen
screenshot rows. `GO` requires every backend, browser, and screenshot counter
to pass. Otherwise write the terminal `NO_GO` report without another repair.

#### 4.6.12t Authorized backend owner repair

The r3 translation evidence passed 48/48 with exactly 48 provider calls.
The first zero-provider backend replay remained 21/48. Runtime instrumentation
proved three bounded owners, and the user authorized option A to repair them:

```text
replay candidate materialization:
  choose deterministic canonical candidate IDs compatible with the sealed
  active topic; never slice the globally sorted catalog

replay responsibility:
  derive expected final responsibility from the shared semantic outcome
  contract; translation-time TaskPlan.mode is not final route authority

selected image binding:
  use admitted image-ordinal references to narrow current image products
  before planning and routing
  preserve all confirmed images in image-lane state
  image-identity presentation uses only router-selected product bindings
  provisional clarification does not infer a category from every uploaded
  image before the router can issue its typed clarification
```

Required RED/GREEN tests:

```text
test_replay_candidates_match_the_sealed_active_topic
test_replay_responsibility_ignores_provisional_translation_task_mode
test_current_image_selection_follows_typed_ordinals
test_image_identity_presents_only_router_selected_products
test_clarification_skips_unneeded_mixed_image_category_inference
```

Run:

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -m pytest -q \
  tests/guide/tools/test_replay_final_real_backend.py \
  tests/guide/application/test_unified_guide_flow.py \
  tests/guide/application/test_image_recommendation_flow.py \
  tests/guide/application/test_pre_routing_task_plan_enricher.py \
  tests/guide/application/test_execution_contracts.py
```

Then clear the debug log, run the same deterministic reproductions with
`runId=post-fix`, and compare the pre-fix and post-fix evidence. Only after
that proof may the zero-provider 48-row backend replay be regenerated.
Translation evidence is immutable and must not be rerun.

#### 4.6.12u Terminal practical browser result

The current zero-provider backend replay passed 48/48 after the backend owner
repair. Browser validation then found one deterministic cross-event defect:
an explore recommendation emitted `SELECTED` or
`INSUFFICIENT_FOR_WINNER` through `decision_process` and `answer_contract`
while its `presentation_contract` correctly forbade a unique winner. The
shared backend public-outcome projection now emits `NOT_APPLICABLE` in all
three public contracts, and the complete pre-CAS envelope rejects future
explore-winner divergence. No frontend file was changed.

The affected regression passed 180 tests, the browser-tool regression passed
137 tests, and the current zero-provider backend replay remained 48/48.
However, the normal Guide runtime browser phase did not pass:

```text
browser run 1:
  deterministic explore-winner contract drift exposed and root-fixed

browser run 2:
  first desktop release view passed
  fit view used fallback because the copywriter returned invalid_output

browser run 3:
  the clear three-option recommendation returned a typed goal clarification
  instead of recommendation
```

The old fit release phrase also conflicted with the current semantic rule that
a generic singular request is exploration unless it explicitly asks for the
best fit. The fixture now says `一款最适合...`; this changes only the audit
input and does not change product semantics.

The release browser requirement is 14/14 with zero fallback and zero invalid
clarification. It was not met, so no fourteen-row screenshot review was
created. Repeated provider sampling to obtain a passing run would hide the
measured instability. Practical attempt 02 is terminal `NO_GO`; its report is:

```text
docs/audits/final-release/mainline-contract-closure/
  practical-release-attempt-02/practical-release-report.json
```

#### 4.6.12v Controlled Demo delivery

The user explicitly changed the delivery target from a zero-degradation
production release to a controlled demonstration. This does not rewrite the
strict `NO_GO` report or claim that the failed 14/14 browser gate passed.

The Demo decision is `GO` because the product capabilities are connected, the
real semantic batch passed 48/48, the current backend replay passed 48/48, and
the post-cleanup deterministic regression passed 242 tests. Copywriter
fallback and a recoverable over-clarification are accepted Demo degradations.
Wrong binding, state corruption, unsafe output, internal errors, and broken
rendering remain stop conditions.

The handoff is:

```text
docs/audits/final-release/mainline-contract-closure/
  practical-release-attempt-02/demo-release-handoff.md
```

#### 4.6.13 Rebuild all authority as repair-epoch-62

No r1-r6 readiness, root-level readiness, repair-epoch-29 or earlier evidence,
aggregate pytest count, or frontend-only fixture result can authorize the next
smoke.
After 4.6.0-4.6.12p are green, create a new immutable
   `repair-epoch-62/` evidence directory. This epoch is reserved by this plan.
Every epoch-artifact writer rejects an existing target file. The separately
declared append-only attempt ledger changes only through its locked writer. An
interrupted run may continue only by generating missing artifacts after
revalidating all existing hashes; it may not overwrite them. Once an attempt
context references this epoch, an in-scope defect follows the finite automatic
recovery in Section 4.6.12k; it never silently creates another epoch or waits
at an intermediate conversational checkpoint.

#### 4.6.13a Evidence rebuild efficiency protocol

The expensive zero-API suite is an authorizing measurement, not a discovery
tool. Do not start it until the following cheap preflight is green:

```text
plan revision is parsed from the declared plan path
Task 11 epoch matches the evidence directory
candidate manifest can be generated exclusively
all evidence output paths are absent or already hash-valid
semantic, network, runtime, browser, and independent-audit schemas are
  mutually compatible
independent audit imports and validates the current plan revision
no protected source, plan, or audit-tool change is pending
```

After the preflight, freeze the source tree, plan, and proof tools for the
entire epoch. The execution order is fixed:

```text
architecture + test-path audit
-> candidate manifest
-> production-path matrix
-> one zero-API prepare-evidence run
-> one zero-API runtime plus desktop/mobile browser run
-> independent audit
-> governance review
-> readiness seal
```

An interrupted run may resume only by revalidating every existing artifact
hash and generating missing artifacts. No existing artifact may be overwritten.
If an in-scope reproducible P0/P1 from the finite boundary in Section 4.6.12i
is found after the candidate is frozen, preserve and archive the failed
candidate as non-authorizing, apply the one earliest-owner recovery authorized
by Section 4.6.12k, increment the plan revision, and restart from the earliest
affected gate under the same final repair-epoch-62 name. A second failure at
the same owner produces final no-go. Do not open another epoch, rerun against a
moving candidate, or expand the threat model. Plan, source, and audit-tool
changes are prohibited between zero-API execution and readiness sealing.

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
UnifiedGuideFlow.stream_image or any caller of stream_image
presentation-compiler decision_for_responsibility calls
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
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/check_single_path_architecture.py \
  --repo-root "$PWD" \
  --output docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-single-path-architecture-r47.json
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

Generate the repair-epoch-62 manifest and pre-audit machine evidence:

```bash
test ! -e /tmp/xiaoro-task11-r47-fixture-runtime-private-key.json
test ! -e /tmp/xiaoro-task11-r47-fixture-runtime-private-key.retry-2.json

PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/build_task11_readiness.py audit-test-paths \
  --plan docs/superpowers/plans/2026-08-21-guide-mainline-contract-closure.md \
  --output docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-test-path-audit-r47.json

PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/build_task11_readiness.py prepare-manifest \
  --plan docs/superpowers/plans/2026-08-21-guide-mainline-contract-closure.md \
  --test-path-audit docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-test-path-audit-r47.json \
  --fixture-runtime-private-key /tmp/xiaoro-task11-r47-fixture-runtime-private-key.json \
  --manifest docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-candidate-manifest-r47.json

# A fresh read-only reviewer records the printed digest. Do not replace this
# step with a per-consumer digest recomputation.
shasum -a 256 \
  docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-candidate-manifest-r47.json
export TASK11_EXPECTED_MANIFEST_SHA256="<reviewer-recorded-64-hex-digest>"
test "${#TASK11_EXPECTED_MANIFEST_SHA256}" -eq 64
test "$TASK11_EXPECTED_MANIFEST_SHA256" = "$(
  shasum -a 256 \
    docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-candidate-manifest-r47.json \
    | awk '{print $1}'
)"
test ! -e /tmp/xiaoro-task11-r47-reviewed-manifest.sha256
(
  umask 077
  set -o noclobber
  printf '%s\n' "$TASK11_EXPECTED_MANIFEST_SHA256" \
    > /tmp/xiaoro-task11-r47-reviewed-manifest.sha256
)

PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/run_task11_production_path_matrix.py \
  --manifest docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-candidate-manifest-r47.json \
  --expected-manifest-sha256 "$TASK11_EXPECTED_MANIFEST_SHA256" \
  --cases tests/fixtures/guide/intent/task11_production_path_matrix_v1.jsonl \
  --output docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-production-path-summary-r47.json

PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/build_task11_readiness.py prepare-evidence \
  --manifest docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-candidate-manifest-r47.json \
  --expected-manifest-sha256 "$TASK11_EXPECTED_MANIFEST_SHA256" \
  --semantic-summary-output docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-semantic-matrix-summary-r47.json \
  --zero-api-summary-output docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-zero-api-summary-r47.json \
  --network-report-output docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-zero-api-network-r47.json \
  --single-path-architecture docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-single-path-architecture-r47.json \
  --test-path-audit docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-test-path-audit-r47.json \
  --production-path-summary docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-production-path-summary-r47.json
```

`prepare-evidence` must run pytest with
`-p tools.guide_gates.zero_api_network_guard` inside the exact
`sandbox-exec` loopback-only profile. The plugin loads before test collection,
denies non-loopback DNS/socket/HTTP/SDK calls, instruments the provider request
boundary, and verifies with `sandbox_check` that the kernel policy is active
before allowing any subprocess, multiprocessing, fork, exec, spawn, or system
call. Outside that verified kernel policy, every process-creation API fails
closed. The plugin atomically writes the network and process-guard report
consumed by `task11-zero-api-summary.json`. Readiness and independent audit bind
both files by SHA-256 and require the exact kernel-inherited child policy,
zero provider calls, zero Python-layer network attempts, and zero unisolated
process-creation attempts.

Each authorizing pytest node records only the fixture paths reachable from that
node, including imported module constants such as `DEFAULT_CASES_PATH`. The
production-path node must independently resolve and bind exactly
`tests/fixtures/guide/intent/task11_production_path_matrix_v1.jsonl`; file-wide
literal scanning is not sufficient.

`task11-semantic-matrix-summary.json` is not trusted merely because it has a
passing flag, plausible counts, or a reviewed file hash. Its `cases_sha256`
must equal the current protected
`tests/fixtures/guide/intent/turn_meaning_gate_v1.jsonl`. Readiness must
rebuild the expected summary from that fixture before accepting it, and the
independent audit must separately parse the JSONL and recompute the exact
case/mode/basis counts without sharing the readiness summary builder. A
caller-authored summary with the correct fixture hash but altered plausible
counts must fail both verifiers.

Run the fixture browser gate separately against the zero-API local runtime:

```bash
# Dedicated terminal; this wrapper installs the same network/process guard
# before importing the application and writes its verified identity file.
TASK11_EXPECTED_MANIFEST_SHA256="$(
  cat /tmp/xiaoro-task11-r47-reviewed-manifest.sha256
)"
TASK11_RUNTIME_ATTEMPT_ROOT=\
/tmp/xiaoro-task11-r47-runtime-browser/attempt-01
TASK11_RUNTIME_PRIVATE_KEY=\
/tmp/xiaoro-task11-r47-fixture-runtime-private-key.json
TASK11_RUNTIME_READY=\
/tmp/xiaoro-task11-r47-runtime-browser/attempt-01-runtime.json
TASK11_RUNTIME_STATE=\
/tmp/xiaoro-task11-r47-runtime-browser/attempt-01-state
test ! -e "$TASK11_RUNTIME_ATTEMPT_ROOT"
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/run_zero_api_runtime.py \
  --manifest docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-candidate-manifest-r47.json \
  --expected-manifest-sha256 "$TASK11_EXPECTED_MANIFEST_SHA256" \
  --runtime-signing-private-key "$TASK11_RUNTIME_PRIVATE_KEY" \
  --host 127.0.0.1 \
  --port 8820 \
  --state-dir "$TASK11_RUNTIME_STATE" \
  --ready-file "$TASK11_RUNTIME_READY" \
  --network-report "$TASK11_RUNTIME_ATTEMPT_ROOT/task11-zero-api-runtime-network.json"

test ! -e "$TASK11_RUNTIME_PRIVATE_KEY"

# Separate terminal after the ready file validates the candidate manifest,
# code revision, protected payload, process identity, and runtime nonce. Each
# invocation obtains and consumes a fresh challenge. Fixture evidence precedes
# candidate readiness and therefore cannot contain a readiness hash.
TASK11_EXPECTED_MANIFEST_SHA256="$(
  cat /tmp/xiaoro-task11-r47-reviewed-manifest.sha256
)"
TASK11_RUNTIME_ATTEMPT_ROOT=\
/tmp/xiaoro-task11-r47-runtime-browser/attempt-01
TASK11_RUNTIME_READY=\
/tmp/xiaoro-task11-r47-runtime-browser/attempt-01-runtime.json
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/run_mainline_contract_browser_audit.py \
  --base-url http://127.0.0.1:8820 \
  --runtime-identity "$TASK11_RUNTIME_READY" \
  --expected-manifest-sha256 "$TASK11_EXPECTED_MANIFEST_SHA256" \
  --trajectory-set fixture \
  --viewport desktop \
  --output "$TASK11_RUNTIME_ATTEMPT_ROOT/fixture-browser-desktop"

PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/run_mainline_contract_browser_audit.py \
  --base-url http://127.0.0.1:8820 \
  --runtime-identity "$TASK11_RUNTIME_READY" \
  --expected-manifest-sha256 "$TASK11_EXPECTED_MANIFEST_SHA256" \
  --trajectory-set fixture \
  --viewport mobile \
  --output "$TASK11_RUNTIME_ATTEMPT_ROOT/fixture-browser-mobile"

export TASK11_EXPECTED_MANIFEST_SHA256 TASK11_RUNTIME_READY
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -c \
  'import os; from tools.guide_gates.run_mainline_contract_browser_audit import shutdown_zero_api_runtime; shutdown_zero_api_runtime(base_url="http://127.0.0.1:8820", runtime_identity_path=os.environ["TASK11_RUNTIME_READY"], expected_manifest_sha256=os.environ["TASK11_EXPECTED_MANIFEST_SHA256"])'
```

The authenticated shutdown above is the only valid fixture-runtime stop. Do
not send a terminal signal or terminate only the child process. After the
shutdown acknowledgement, the runtime wrapper must atomically finalize the staged
`task11-zero-api-runtime-network.json` from its own OS-level process-tree
audit. It records attempted and denied DNS, TCP, UDP, QUIC, provider-boundary,
and child-process escape operations for the runtime PID tree. Missing shutdown
finalization, an unaudited descendant, or any non-loopback attempt fails the
evidence.

Only after the staged runtime report and both browser summaries are complete,
promote the whole bundle with one no-replace directory rename:

```bash
TASK11_EXPECTED_MANIFEST_SHA256="$(
  cat /tmp/xiaoro-task11-r47-reviewed-manifest.sha256
)"
TASK11_RUNTIME_ATTEMPT_ROOT=\
/tmp/xiaoro-task11-r47-runtime-browser/attempt-01
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/build_task11_readiness.py \
  promote-runtime-browser-evidence \
  --repo-root "$PWD" \
  --manifest docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-candidate-manifest-r47.json \
  --expected-manifest-sha256 "$TASK11_EXPECTED_MANIFEST_SHA256" \
  --attempt-root "$TASK11_RUNTIME_ATTEMPT_ROOT" \
  --fixture-runtime-private-key /tmp/xiaoro-task11-r47-fixture-runtime-private-key.json

test -d docs/audits/final-release/mainline-contract-closure/repair-epoch-62/runtime-browser-evidence-r47
test ! -e /tmp/xiaoro-task11-r47-fixture-runtime-private-key.json
test ! -e /tmp/xiaoro-task11-r47-fixture-runtime-private-key.retry-2.json
```

If `attempt-01` ends in an environment-only failure before promotion, retain
its staging directory as diagnostics and rerun only this runtime/browser
section with `attempt-02`,
`/tmp/xiaoro-task11-r47-fixture-runtime-private-key.retry-2.json`, a fresh
ready file, and a fresh state directory. Do not rebuild architecture,
test-path, production-path, semantic, or zero-API evidence. If `attempt-02`
also fails, stop as an external-environment blocker. There is no third key,
third attempt, new plan revision, or new evidence epoch for that candidate.

The wrapper uses two sandbox stages. A short preflight stage permits only the
fixed direct-child and descendant network canaries and proves inherited
network denial. The actual runtime then starts in its own process session/group
under the same loopback-only policy plus OS-level `deny process-fork`; it
cannot create a descendant that escapes the observed process group. The parent
binds the runtime BEGIN/END markers to the exact `Popen` PID and observed PGID,
enforces a finite runtime timeout, and requires the group to disappear after
root exit.

After the runtime group is quiescent, the wrapper runs a third nonce-bound
network canary in a fresh sandbox and waits for that later `Sandbox.kext`
denial before emitting one `XIAORO_RUNTIME_SEATBELT_DRAIN` marker. The raw
event order must prove `READY < CANARY_BEGIN < direct-child kernel denial <
descendant kernel denial < direct-child observed marker < descendant observed
marker < CANARY_END < runtime BEGIN < runtime END < drain canary < drain
kernel denial < DRAIN`. The long-lived parent is the sole marker emitter. It
must observe `CANARY_BEGIN` before releasing the preflight process through its
stdin gate, derive each child PID from the exact fixed-port kernel denial,
emit the two PID-bound observed markers, and observe all three closing markers
before starting the runtime. The drain process is also held behind an stdin
gate until the parent has emitted and observed its exact PID-bound marker.

This same-kernel-source drain canary is the delivery barrier for earlier
runtime denials; a user-space marker alone is not accepted as a kernel flush.
A fixed sleep, a marker emitted by a short-lived child, root-process exit
alone, an unbound PID/PGID, a caller-authored zero, a missing or duplicate
marker, fewer than three expected canary denials, or a non-quiescent process
group fails closed. The final strict parser still requires every non-readiness
marker exactly once. Readiness and the independent audit each reparse the raw
NDJSON and verify these conditions without importing the runtime report
builder. A later persistent `log show` result may diagnose a failed live
capture but may never fill, replace, or authorize its raw evidence.

The two Task 11 `Generate` directory actions cover the canonical
`runtime-identity.json`, the invocation-specific
`consumed-runtime-health-challenge.json`, every per-turn `request.json`, raw
`stream.sse`, presentation contract, DOM snapshot, screenshot, console log,
network log, sandbox audit, and summary. Each summary is an exclusive machine
index of all other files below its directory with SHA-256; it never attempts
to hash itself. Readiness and the change manifest hash the summary file from
outside that directory index. The change-manifest writer expands those indexes
to explicit staged paths and rejects an unindexed file or a directory-only
staging entry.

Each fixture summary must include its runtime-identity digest, consumed
challenge digest, OS sandbox identity/audit digest, browser request count,
process-tree non-loopback-attempt count, and browser-observed non-loopback
attempt count. The process-tree count is derived from the sandbox/kernel audit;
the browser count is derived independently from raw Playwright/CDP request
logs. Neither may be copied from expected fixtures. The summary digests must
be recomputed from the two indexed originals, and the challenge original must
name the same recomputed runtime identity. Desktop and mobile must carry
byte-identical runtime-identity originals and different valid consumed
challenges.

Every browser bundle that carries product cards is revalidated against the
locked canonical product, reviewed display-binding, and seed-image assets.
The raw SSE `cards` and `products` payloads must agree with canonical
category profile/facts, `display_name`/`name`, brand, category, price,
specification/alignment, image URL/hash, detail URL, platform, warnings, and
every other static public card field for the same product ID. The frontend
`products` row must also equal the complete deterministic projection of its
typed `cards` row, including description, efficacy match, matched efficacies,
skin label, and warnings. Production encoding and browser validation must call
the same application-owned projection function; the audit tool may not carry a
second copied field projection. End-to-end agreement between a forged SSE
payload and forged DOM is not sufficient.

Every emitted `variant_scope` must belong to the locked controlled-alias
registry for that product. Dynamic `skin_match` is not copied back into an
expected card: the browser audit first compares only canonical static fields,
then requires the dynamic state to be one the decision-layer skin matcher can
produce from that product's canonical decision facts. Every browser audit
tool, including historical frontend matrix tools still present in the
repository, must reuse the application-owned frontend product projection.

The production runtime may not mount the whole `app/static/` tree at
`/static`. Raw HTML such as `/static/chat.html` bypasses the `/chat`
runtime-scope injection and reactivates legacy client behavior. Only explicit
non-HTML runtime assets and narrowly mounted image/vendor directories may be
public. The architecture checker and HTTP tests must reject reintroduction of
a `/static` root mount.

Only after those artifacts exist, run a second, mechanically independent audit
implementation. It shares no policy tables, AST helpers, summary parser, or
pass/fail functions with `check_single_path_architecture.py`,
`build_task11_readiness.py`, or the production-path runner. Its mutation corpus
deletes or corrupts each required input and injects one example of every
forbidden bridge, bypass, stale hash, unmeasured counter, slot alias, extra
production root, and post-CAS encoder. Every mutation must be detected.
Every required call proved by this audit must be reachable and unshadowed.
A call under `if False`, a statically false literal comparison, a direct or
qualified unshadowed `typing.TYPE_CHECKING` branch, after an unconditional
terminator, or after a branch that provably terminates on every reachable path
cannot satisfy the audit merely because it is present in the AST. Exception
targets and structural-pattern capture names count as shadowing bindings.
The bounded-attempt completion verifier is stricter than ordinary reachability:
its browser-evidence replay call must be an unconditional direct statement in
the top-level `try` body and must receive exactly
`Path(str(output_directory))`.

The audit derives its scope and verdict itself. Its only external trust input
is the reviewer-recorded canonical candidate-manifest SHA-256; it accepts no
finding list, reviewer identity, pass boolean, expected evidence-result hash,
or caller-authored count. It inspects the production diff, semantic and
zero-API summaries, single-path architecture report, forbidden-symbol deletion
results, test-path claims, network reports, per-turn production traces,
emitted-byte identity, both state backends, and both fixture browser
directories. It computes the diff and every reviewed evidence SHA-256, then
exclusively creates the epoch-owned audit:

The independent audit must recollect every declared pytest node from the
protected test files, compare the exact node inventory, and prove the sole
production-path test contains one reachable unshadowed call to the canonical
matrix runner. It must reconstruct the zero-API command list and compare the
measured passed count with that collected inventory. It must also parse the
protected production-matrix JSONL and compare every ordered trace identity,
trajectory, partition, bounded marker, expected state edge, processor, intent,
card IDs, and required coverage edges with the corresponding case.

Browser evidence is independently derived from raw files rather than trusted
from producer summary counters. The audit parses strict SSE lifecycle, DOM
section/ID ownership, valid viewport-sized PNG structure, raw browser request
records, and Chromium netlog targets. It rebuilds canonical cards from the
candidate-root catalog/display/image/category/alias assets, constrains dynamic
skin and efficacy states, and invokes only the application-owned
`project_frontend_product` for exact frontend projection equality. Reindexed
forged DOM, canonical card, frontend projection, screenshot, request log, or
netlog evidence must fail.

```bash
TASK11_EXPECTED_MANIFEST_SHA256="$(
  cat /tmp/xiaoro-task11-r47-reviewed-manifest.sha256
)"
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/run_task11_independent_audit.py \
  --repo-root "$PWD" \
  --manifest docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-candidate-manifest-r47.json \
  --expected-manifest-sha256 "$TASK11_EXPECTED_MANIFEST_SHA256" \
  --semantic-summary docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-semantic-matrix-summary-r47.json \
  --zero-api-summary docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-zero-api-summary-r47.json \
  --single-path-architecture docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-single-path-architecture-r47.json \
  --test-path-audit docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-test-path-audit-r47.json \
  --network-report docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-zero-api-network-r47.json \
  --runtime-network-report docs/audits/final-release/mainline-contract-closure/repair-epoch-62/runtime-browser-evidence-r47/task11-zero-api-runtime-network.json \
  --production-path-summary docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-production-path-summary-r47.json \
  --desktop-summary docs/audits/final-release/mainline-contract-closure/repair-epoch-62/runtime-browser-evidence-r47/fixture-browser-desktop/summary.json \
  --mobile-summary docs/audits/final-release/mainline-contract-closure/repair-epoch-62/runtime-browser-evidence-r47/fixture-browser-mobile/summary.json \
  --output docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-independent-audit-r47.json
```

After this machine audit passes, one checklist-bounded read-only review
examines the same hash-bound bundle against the exact scope in Section
4.6.12i. A confirmed in-scope P0/P1 follows the finite automatic recovery in
Section 4.6.12k and a second failure at the same owner produces final no-go.
The review must not add a new threat model or recursively audit the audit
mechanism. It is deliberately not accepted as a JSON authorization input
because repository code cannot authenticate reviewer independence; only the
independently implemented mechanical report above is consumed by readiness.

Before sealing readiness, migrate the canonical ledger exactly once through
its locked writer. Do not hand-edit, copy, replace, or re-sign the ledger:

```bash
TASK11_LEDGER=docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json
TASK11_EXPECTED_MANIFEST_SHA256="$(
  cat /tmp/xiaoro-task11-r47-reviewed-manifest.sha256
)"
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/attempt_ledger.py checkpoint-v2 \
  --ledger "$TASK11_LEDGER" \
  --manifest docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-candidate-manifest-r47.json \
  --expected-manifest-sha256 "$TASK11_EXPECTED_MANIFEST_SHA256"
```

Then seal readiness:

```bash
TASK11_EXPECTED_MANIFEST_SHA256="$(
  cat /tmp/xiaoro-task11-r47-reviewed-manifest.sha256
)"
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/build_task11_readiness.py seal-readiness \
  --manifest docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-candidate-manifest-r47.json \
  --expected-manifest-sha256 "$TASK11_EXPECTED_MANIFEST_SHA256" \
  --readiness docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-candidate-readiness-r47.json \
  --semantic-summary docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-semantic-matrix-summary-r47.json \
  --zero-api-summary docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-zero-api-summary-r47.json \
  --network-report docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-zero-api-network-r47.json \
  --runtime-network-report docs/audits/final-release/mainline-contract-closure/repair-epoch-62/runtime-browser-evidence-r47/task11-zero-api-runtime-network.json \
  --single-path-architecture docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-single-path-architecture-r47.json \
  --test-path-audit docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-test-path-audit-r47.json \
  --production-path-summary docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-production-path-summary-r47.json \
  --independent-audit docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-independent-audit-r47.json \
  --desktop-summary docs/audits/final-release/mainline-contract-closure/repair-epoch-62/runtime-browser-evidence-r47/fixture-browser-desktop/summary.json \
  --mobile-summary docs/audits/final-release/mainline-contract-closure/repair-epoch-62/runtime-browser-evidence-r47/fixture-browser-mobile/summary.json \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json \
  --fixture-runtime-private-key /tmp/xiaoro-task11-r47-fixture-runtime-private-key.json
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
and binds the already generated evidence plus ledger state. Before sealing, it
re-enumerates both browser fixture directories and recomputes the exact
`artifact_sha256_by_path` map. Missing, extra, symlinked, or hash-drifted root
network/Seatbelt artifacts or per-turn request/SSE/contract/DOM/screenshot/
console/network/sandbox artifacts fail closed.

No exact or wildcard `excluded_paths` entry may cover any path under `app/`,
`tools/`, or `tests/`. Every existing local `/static/...` script or stylesheet
referenced by a protected HTML page must itself be in the protected payload.
`build-change-manifest` expands both browser fixture indexes to their explicit
repository-relative child paths and binds the exact passed bounded attempt
context. `finalize-change-manifest` re-runs the complete readiness verifier,
bounded-browser replay, ledger result, runtime attestation, and both artifact
enumerations, then requires the approved staged set to equal the
machine-derived set. After the Task 11 commit, `seal-commit` repeats those checks
while binding the candidate manifest to the commit parent, then verifies every
browser child as an identical blob in the Task 11 commit.
`verify-release-readiness` re-derives the committed candidate readiness and
compares every inherited completion field. Stored readiness booleans, a
top-level summary hash, a hand-authored draft/release file, or caller-authored
approved paths are not authorization.

The independent audit's top-level `repair_epoch` is evidence provenance, not a
smoke retry counter. `attempt_ledger authorize` derives the retry owner,
per-owner retry sequence, and repair evidence only from the already validated
ledger failure/reclassification history. A failed attempt without a complete,
hash-verified reclassification closure cannot authorize another attempt.

Once an authorization has been allocated, its readiness and every referenced
evidence file are immutable. A repair after a failed attempt must archive the
complete failed evidence set and generate a new canonical evidence set under
the same final `repair-epoch-62/` name with a monotonic plan revision, as
authorized by Section 4.6.12k. It must authorize only from that new readiness
path. Never overwrite files referenced by an existing attempt context.

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

Every protected-path payload read must start from one opened canonical
repository-root directory descriptor and walk each relative component with
`openat`/`dir_fd` plus `O_NOFOLLOW`. The reader must reject an ancestor or
leaf symlink, non-regular leaf, owner mismatch, link count other than one,
path escape, and any opened-vs-named inode/size/mtime drift. Hashing uses only
bytes read from that verified leaf descriptor. Readiness and independent audit
must implement this rule independently. Required RED/GREEN coverage includes:

```text
test_canonical_payload_rejects_symlinked_ancestor
test_independent_payload_hash_rejects_symlinked_ancestor
test_readiness_revalidates_protected_payload_before_publish
```

Immediately before exclusively publishing candidate readiness, readiness must
recompute the complete protected payload through the secure descriptor walk
and require it to equal the frozen manifest hash. This final check is in
addition to the initial manifest validation; it closes the validation-to-seal
window rather than assuming the working tree stayed unchanged.

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
repair-epoch-62 readiness is sealed from raw hashed evidence
```

After bounded smoke passes, Step 6 creates the epoch-owned
`task11-change-manifest.json`. This separate post-smoke manifest contains the
exact `change_paths` including deletion tombstones, approved bounded artifacts,
candidate manifest, candidate readiness, final ledger revision/hash, and
`staged_diff_sha256`. It alone has staging requirements; changing it cannot
invalidate the completed bounded-smoke readiness.

Before a bounded attempt can transition from `consumed` to `passed`, the
ledger writer independently replays the fixed three-trajectory/nine-turn
browser evidence, validates every turn bundle and bounded contract, verifies
the ledger-registered runtime identity and Ed25519 proof, verifies that the
`authorization_consumed` revision hash binds the exact runtime attestation,
and compares an exhaustive artifact hash index. `build-change-manifest`
repeats both the browser replay and attestation-chain validation; a
caller-authored summary containing only `passed=true`, `turn_count=9`, an
arbitrary 64-hex digest, or an unregistered self-signed key cannot authorize a
commit.

Its `approved_change_paths` is the exact union of candidate `change_paths`,
enumerated epoch evidence including every browser-index child, the successful
bounded-attempt files, the candidate manifest/readiness, and the ledger.
Wildcard declarations are resolved to explicit paths before the draft is
written. The finalizer compares staged name/status rows, not names alone, so a
required deletion cannot be replaced by a recreated empty file.

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
TASK11_EXPECTED_MANIFEST_SHA256="$(
  cat /tmp/xiaoro-task11-r47-reviewed-manifest.sha256
)"
AUTHORIZATION_ID="$(
  PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/attempt_ledger.py authorize \
  --phase bounded \
  --readiness docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-candidate-readiness-r47.json \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json \
  --independent-audit docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-independent-audit-r47.json \
  --expected-manifest-sha256 "$TASK11_EXPECTED_MANIFEST_SHA256"
)"
test -n "$AUTHORIZATION_ID"
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/attempt_ledger.py allocate \
  --phase bounded \
  --authorization-id "$AUTHORIZATION_ID" \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json \
  --readiness docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-candidate-readiness-r47.json \
  --output-root docs/audits/final-release/mainline-contract-closure \
  > /tmp/xiaoro-task11-r47-bounded-context.path
test -s /tmp/xiaoro-task11-r47-bounded-context.path
```

Start the runtime in a dedicated terminal with that exact context:

```bash
ATTEMPT_CONTEXT="$(cat /tmp/xiaoro-task11-r47-bounded-context.path)"
test -n "$ATTEMPT_CONTEXT"
GUIDE_LLM_API_KEY="$(cat /Users/bytedance/Desktop/deepseek-key.txt)" \
GUIDE_LLM_BASE_URL=https://api.deepseek.com \
GUIDE_LLM_MODEL=deepseek-v4-pro \
GUIDE_LLM_FORMAT_REPAIR_ATTEMPTS=0 \
GUIDE_COPY_LLM_API_KEY="$(cat /Users/bytedance/Desktop/deepseek-key.txt)" \
GUIDE_COPY_LLM_BASE_URL=https://api.deepseek.com \
GUIDE_COPY_LLM_MODEL=deepseek-v4-pro \
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
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
ATTEMPT_CONTEXT="$(cat /tmp/xiaoro-task11-r47-bounded-context.path)"
test -n "$ATTEMPT_CONTEXT"
TASK11_EXPECTED_MANIFEST_SHA256="$(
  cat /tmp/xiaoro-task11-r47-reviewed-manifest.sha256
)"
test "${#TASK11_EXPECTED_MANIFEST_SHA256}" -eq 64
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/run_mainline_contract_browser_audit.py \
  --base-url http://127.0.0.1:8821 \
  --expected-manifest-sha256 "$TASK11_EXPECTED_MANIFEST_SHA256" \
  --trajectory-set bounded \
  --viewport desktop \
  --attempt-context "$ATTEMPT_CONTEXT"
```

Stop the active attempt immediately if any turn has fallback, missing contract,
invalid clarification truth, bad DOM audit, or image identity mismatch. Save
the evidence bundle, record the earliest failing owner, and apply Section
4.6.12k automatically. Do not alter Prompt, create another Task 11 epoch, or
retry without deterministic reproduction, a focused failing regression, the
smallest earliest-owner repair, rebuilt authority, and a fresh one-time
authorization. A second failure at the same owner produces final no-go.

- [ ] **Step 6: Commit**

Resolve the unique successful bounded context and generate the separate
post-smoke manifest:

```bash
ATTEMPT_CONTEXT="$(
  PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/attempt_ledger.py latest \
  --phase bounded \
  --result passed \
  --readiness docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-candidate-readiness-r47.json \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json
)"
test -n "$ATTEMPT_CONTEXT"
TASK11_EXPECTED_MANIFEST_SHA256="$(
  cat /tmp/xiaoro-task11-r47-reviewed-manifest.sha256
)"
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/build_task11_readiness.py build-change-manifest \
  --candidate-manifest docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-candidate-manifest-r47.json \
  --candidate-readiness docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-candidate-readiness-r47.json \
  --expected-manifest-sha256 "$TASK11_EXPECTED_MANIFEST_SHA256" \
  --attempt-context "$ATTEMPT_CONTEXT" \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json \
  --output /tmp/xiaoro-task11-r47-change-manifest-draft.json
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
8. Reject the commit if any undeclared `app/static/` path, recording-v1 drift,
   `.dbg`, `.tmp-*`, debug notes, screenshots outside the approved bundle, or
   historical audits are staged. The declared modified `app/static/demo.html`
   must be present in the approved path set.
9. Require `git status --short` to contain no unapproved untracked or modified
   residue; excluding debris from the commit is not repository cleanup.
10. Review the staged diff, not only the worktree diff.
```

```bash
TASK11_EXPECTED_MANIFEST_SHA256="$(
  cat /tmp/xiaoro-task11-r47-reviewed-manifest.sha256
)"
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/build_task11_readiness.py finalize-change-manifest \
  --draft /tmp/xiaoro-task11-r47-change-manifest-draft.json \
  --candidate-manifest docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-candidate-manifest-r47.json \
  --candidate-readiness docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-candidate-readiness-r47.json \
  --expected-manifest-sha256 "$TASK11_EXPECTED_MANIFEST_SHA256" \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json \
  --output docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-change-manifest.json
```

The former three-file `git add` command is intentionally removed because it
would omit semantic, state, provenance, attribution, and gate changes. Write
the final exact-path staging command only after Steps 4.5 and 4.6 stabilize the
manifest. Directory-level staging remains forbidden.

Commit only after the bounded smoke passes:

```bash
git commit -m "test(guide): bind real SSE contracts to browser evidence"
```

### Task 12: Run practical final release validation once

**Status:** `BACKEND_SHARED_REPAIR_AUTHORIZED`. The r3 translation batch passed
48/48 and is immutable. Section 4.6.12t authorizes the bounded backend-owner
repair before replay and browser validation continue. The formal cryptographic
workflow below remains historical reference and must not be represented as
passed or used to create a release seal.

Task 12 is a finite functional-release validation, not an unbounded security
or capacity-certification program. Its go/no-go decision requires the declared
48-turn real translation batch, deterministic backend replay, desktop/mobile
release browser trajectories, and manual screenshot review to pass. The
translation report must record finite per-turn latency and aggregate p95
latency; the release summary records those observed values without inventing
an infrastructure SLO. Throughput, sustained load, autoscaling, and hostile
same-UID filesystem/process behavior are explicitly post-release operational
hardening and may not reopen Task 11 or create another evidence epoch.

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
TASK11_EXPECTED_MANIFEST_SHA256="$(
  cat /tmp/xiaoro-task11-r47-reviewed-manifest.sha256
)"
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/build_task11_readiness.py seal-commit \
  --manifest docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-change-manifest.json \
  --candidate-readiness docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-candidate-readiness-r47.json \
  --release-readiness docs/audits/final-release/mainline-contract-closure/task11-release-readiness.json \
  --task11-commit "$(git rev-parse HEAD)" \
  --expected-manifest-sha256 "$TASK11_EXPECTED_MANIFEST_SHA256"
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
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -m compileall -q app tools tests
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python -m pytest -q \
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

TASK11_EXPECTED_MANIFEST_SHA256="$(
  cat /tmp/xiaoro-task11-r47-reviewed-manifest.sha256
)"
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/build_task11_readiness.py verify-release-readiness \
  --readiness docs/audits/final-release/mainline-contract-closure/task11-release-readiness.json \
  --require-head "$(git rev-parse HEAD)" \
  --expected-manifest-sha256 "$TASK11_EXPECTED_MANIFEST_SHA256"
```

Expected: PASS. The final command mechanically proves the test run made no
tracked or non-ignored execution-tree change. A test/tool failure or tree drift
returns automatically to the earliest affected Task 11 gate under Section
4.6.12k; Task 12 may not repair committed execution tooling in place or keep
using the invalidated seal. Every Task 12 runner in Steps 3-8 invokes this
`phase-execution` verifier before doing work. It requires
`HEAD == task11_commit` and exact execution-tree bytes.

- [ ] **Step 3: Generate the zero-API focused summary**

```bash
TASK11_EXPECTED_MANIFEST_SHA256="$(
  cat /tmp/xiaoro-task11-r47-reviewed-manifest.sha256
)"
AUTHORIZATION_ID="$(
  PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/attempt_ledger.py authorize \
  --phase translation \
  --readiness docs/audits/final-release/mainline-contract-closure/task11-release-readiness.json \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json \
  --independent-audit docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-independent-audit-r47.json \
  --expected-manifest-sha256 "$TASK11_EXPECTED_MANIFEST_SHA256"
)"
test -n "$AUTHORIZATION_ID"
ATTEMPT_CONTEXT="$(
  PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
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
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/build_responsibility_matrix.py \
  --output-dir "$MATRIX_DIR"

PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
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
  PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/attempt_ledger.py current \
  --phase translation \
  --readiness docs/audits/final-release/mainline-contract-closure/task11-release-readiness.json \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json
)"
test -n "$ATTEMPT_CONTEXT"
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/run_final_real_translation.py \
  --cases tests/fixtures/guide/final_release/real_translation_12x4_v5.jsonl \
  --attempt-context "$ATTEMPT_CONTEXT" \
  --phase translation \
  --key-path /Users/bytedance/Desktop/deepseek-key.txt \
  --model deepseek-v4-pro \
  --state-dir /tmp/xiaoro-mainline-release-state
```

If any serious failure occurs, stop this batch and record its earliest failure
owner and evidence directory in the persistent ledger. Then apply Section
4.6.12k automatically: classify transient provider/environment failure versus
a reproducible product-path defect; use only the bounded retry or single
earliest-owner repair allowed there; invalidate and rebuild all affected
readiness/evidence before another real batch. Do not wait for user approval.
A second failure at the same owner or exhausted external dependency produces
the final no-go report.

- [ ] **Step 5: Replay the same real meanings through the full backend**

`replay_final_real_backend.py` resolves the successful 48-row translation
result and backend output directory from the immutable attempt context,
injects each captured `TurnMeaning` into the real orchestrator with the sealed
trajectory context, and records the full typed SSE. It makes zero provider
calls and disables the Copywriter only for this replay. It must assert:

The v5 translation fixture is a twelve-sheet, forty-eight-case semantic
coverage set. Its per-turn contexts are independently sealed inputs and are
not a claim that the four rows in each sheet are natural consecutive state
transitions. Backend evidence must therefore declare
`context_replay_mode=sealed_case_context` and
`stateful_transition_count=0`; it materializes a fresh exact context for each
HTTP turn. Stateful transition authority remains the Task 11 production-path
matrix and the bounded/release browser trajectories, where turn N+1 consumes
only turn N's committed snapshot. The backend replay must not report its sheet
count as stateful trajectory coverage.

Every image-bearing v5 row binds an ordered `image_product_ids` tuple whose
length equals the sealed `image_count`. Replay resolves those exact canonical
seed assets and records their actual SHA-256 values in the per-turn trace; it
must never select the first N assets implicitly. Every per-turn trace also
binds a repository-relative raw SSE path and SHA-256. The browser-child
allocator reparses every raw event through the typed SSE union, re-derives
terminal responsibility and visible product IDs, and rejects any missing,
extra, unindexed, hash-drifted, event-sequence-drifted, or payload-invalid
artifact. The canonical product and seed-image JSONL/manifest inputs used by
replay are protected by the Task 11 candidate payload and the committed
release-execution inventory.

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
  PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/attempt_ledger.py latest \
  --phase translation \
  --result passed \
  --readiness docs/audits/final-release/mainline-contract-closure/task11-release-readiness.json \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json
)"
test -n "$ATTEMPT_CONTEXT"
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/replay_final_real_backend.py \
  --cases tests/fixtures/guide/final_release/real_translation_12x4_v5.jsonl \
  --attempt-context "$ATTEMPT_CONTEXT" \
  --phase backend
```

- [ ] **Step 6: Run desktop and mobile production browser trajectories**

Run:

```bash
PARENT_CONTEXT="$(
  PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/attempt_ledger.py latest \
  --phase translation \
  --result passed \
  --readiness docs/audits/final-release/mainline-contract-closure/task11-release-readiness.json \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json
)"
test -n "$PARENT_CONTEXT"
TASK11_EXPECTED_MANIFEST_SHA256="$(
  cat /tmp/xiaoro-task11-r47-reviewed-manifest.sha256
)"
AUTHORIZATION_ID="$(
  PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/attempt_ledger.py authorize \
  --phase browser \
  --readiness docs/audits/final-release/mainline-contract-closure/task11-release-readiness.json \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json \
  --independent-audit docs/audits/final-release/mainline-contract-closure/repair-epoch-62/task11-independent-audit-r47.json \
  --expected-manifest-sha256 "$TASK11_EXPECTED_MANIFEST_SHA256"
)"
test -n "$AUTHORIZATION_ID"
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
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
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
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
TASK11_EXPECTED_MANIFEST_SHA256="$(
  cat /tmp/xiaoro-task11-r47-reviewed-manifest.sha256
)"
test "${#TASK11_EXPECTED_MANIFEST_SHA256}" -eq 64
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/run_mainline_contract_browser_audit.py \
  --base-url http://127.0.0.1:8821 \
  --expected-manifest-sha256 "$TASK11_EXPECTED_MANIFEST_SHA256" \
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

Treat the approved frontend files and format in Section 4.6.12k as frozen.
First classify any bad or missing screenshot using runtime health, browser
console/network evidence, DOM geometry, raw SSE, and contract binding. A
capture/load/browser failure is rerun without frontend edits. Only a
reproducible DOM, contract-binding, or rendering defect permits one focused
earliest-owner repair that preserves the existing layout and visual format.
The executor performs this classification, repair, and affected-gate rebuild
without waiting for user approval.

Record the review with:

```bash
ATTEMPT_CONTEXT="$(
  PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/attempt_ledger.py latest \
  --phase browser \
  --result passed \
  --readiness docs/audits/final-release/mainline-contract-closure/task11-release-readiness.json \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json
)"
test -n "$ATTEMPT_CONTEXT"
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
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
  PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/attempt_ledger.py latest \
  --phase browser \
  --result passed \
  --readiness docs/audits/final-release/mainline-contract-closure/task11-release-readiness.json \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json
)"
test -n "$ATTEMPT_CONTEXT"
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
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
  PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/attempt_ledger.py latest \
  --phase browser \
  --result passed \
  --readiness docs/audits/final-release/mainline-contract-closure/task11-release-readiness.json \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json
)"
test -n "$ATTEMPT_CONTEXT"
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
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
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/run_final_release_gate.py stage-evidence \
  --manifest docs/audits/final-release/mainline-contract-closure/release-evidence-manifest.json

PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
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
  PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/attempt_ledger.py latest \
  --phase browser \
  --result passed \
  --readiness docs/audits/final-release/mainline-contract-closure/task11-release-readiness.json \
  --ledger docs/audits/final-release/mainline-contract-closure/smoke-attempt-ledger.json
)"
test -n "$ATTEMPT_CONTEXT"
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
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
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
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
of 4.6 are closed with repair-epoch-62 evidence. No Task 12 step may begin
until Task 11 bounded smoke is clean and its exact commit exists.
