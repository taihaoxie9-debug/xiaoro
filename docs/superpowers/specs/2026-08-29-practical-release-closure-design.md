# Practical Release Closure Design

## Goal

Validate the frozen XiaoRo Guide product as a deployable demonstration without
continuing the superseded cryptographic release-seal governance loop.

## Scope

- Freeze the approved frontend and every product path outside the three shared
  semantic owners named below.
- Preserve the append-only attempt ledger and every ledger-referenced artifact.
- Treat r42-r47 candidate and failed evidence as historical, non-authorizing
  records.
- Remove only unreferenced temporary keys, state directories, and incomplete
  staging outputs.
- Run one practical release attempt under
  `docs/audits/final-release/mainline-contract-closure/practical-release-attempt-01/`.

## Approved Semantic Repair

The first practical attempt showed that the v5 fixture, semantic evaluator,
and prompt no longer share one current contract. The repair is limited to:

1. Derive final translation cases from the current canonical gate case and
   current state schema. Do not hand-patch individual JSONL rows.
2. Make recommendation-mode rules general: explicit numeric bounds produce
   bounded exploration; a generic singular noun does not by itself claim a
   best-fit request.
3. Derive responsibility from the final typed route contract. A bound-product
   factual follow-up may be product knowledge, and a safety escalation is a
   valid strengthening of consultation.
4. Require revision evidence only when a typed state transition is expected.
   A complete topic replacement represented as a new task does not need an
   unrelated constraint-change atom.
5. Clarify the Prompt boundary between a general mechanism question and a
   request to assess the user's current symptoms.

No rule may inspect a sentence, case ID, fixture path, product ID, or expected
answer. Each rule requires category-level regression tests before production
or fixture generation changes.

## Execution

The practical attempt reuses existing execution cores:

1. Run focused product, presentation, runtime, and browser tests with provider
   keys absent.
2. Run the canonical 48-turn v5 fixture through
   `run_final_translation_gate` and the production DeepSeek adapter.
3. Replay the exact captured `TurnMeaning` rows through the existing Guide HTTP
   backend replay core with provider keys disabled.
4. Start the normal production Guide ASGI application and run
   `run_release_browser_audit` for all seven modes on desktop and mobile.
5. Inspect and hash exactly fourteen terminal screenshots.

No practical step may add a router, compatibility bridge, product-specific
branch, sentence-specific prompt patch, frontend change, timeout increase, or
alternate business request path. A category-level prompt clarification is
allowed only when the same invariant is enforced by the typed contract.

## Evidence

The attempt records:

- focused test output;
- 48-turn translation `results.jsonl`, `summary.json`, and `SHA256SUMS`;
- backend replay traces, raw SSE, summary, and checksums;
- desktop/mobile request, SSE, contract, DOM, screenshot, console, and network
  bundles;
- one fourteen-row screenshot review;
- one practical release report containing hashes and the final GO/NO-GO.

These files are practical delivery evidence. They are not a replacement or
forgery of the abandoned `release-seal.json` contract.

## Decision Rule

After the approved semantic repair, `GO` requires:

- focused tests pass;
- the six affected semantic families pass one bounded real canary;
- all 48 translation turns pass;
- backend replay has zero contract, binding, state, and network failures;
- all fourteen browser turns pass with zero release counters;
- all fourteen screenshots pass visual review.

Any reproducible product or frontend failure is `NO_GO`. Provider or local
environment failure is reported separately as `BLOCKED`. This is one
shared-owner repair followed by one canary and one complete release run; it
does not reopen Task 11 or create an automatic revision loop.

## Authorized Final Repair

The user authorized one final shared-owner repair after the r2 batch completed
42 of 48 strict translation turns. This authorization does not permit
case-specific behavior or another governance loop.

### Chosen approach

1. Make the source semantic contract require
   `image_similarity + explore -> similar_alternatives`. A budget remains an
   independent constraint and cannot replace the operation-owned explore
   basis. An explicit single-best image request with usable fit constraints
   may still use `fit` with a fit-scoped basis.
2. Derive final fixture recommendation outcomes from each embedded case's
   allowed operation and derive continuity allowances from typed context
   authority. Do not copy expectation fields by reused case ID.
3. Keep malformed provider JSON fail-closed. Do not add a JSON repair parser,
   hidden semantic fallback, or per-turn provider retry. The newly authorized
   complete batch is the only retry of the prior transient provider failure.

### Rejected approaches

- Local JSON text repair was rejected because it would create an untyped
  interpretation path beside strict schema admission.
- An automatic second provider call per turn was rejected because it would
  weaken the existing single-request contract and make call accounting
  nondeterministic.
- Relaxing the image-basis or continuity evaluator was rejected because it
  would hide real contract contradictions instead of correcting their owner.

### Verification

Use TDD in this order:

1. RED: an explore image-similarity turn with a numeric budget cannot validate
   with `bounded_exploration`, while a source-grounded image fit remains valid.
2. RED: strict DeepSeek tool schema has a distinct image-similarity branch
   that permits only `similar_alternatives`.
3. RED: final fixture synchronization derives identity turns with no
   recommendation outcome and admits `continue` when typed current batch or
   image authority exists.
4. GREEN: implement the minimum contract, strict-schema, and fixture
   derivation changes.
5. Run the affected adapter, contract, fixture, semantic-equivalence, and
   no-sentence-patch suites.
6. Run one fresh semantic canary and exactly one complete 48-turn batch.
7. Continue to backend replay and fourteen browser/screenshot views only if
   translation is 48/48.

Any remaining product, schema, provider, backend, or browser failure produces
the final `NO_GO`. No additional repair revision is authorized.

## Authorized Backend Repair

After translation reached 48/48, the user authorized one bounded repair of the
backend replay findings. Runtime evidence separated one product defect from
two replay-evaluator defects:

1. Replay candidate snapshots used the first global catalog IDs instead of
   category-compatible IDs.
2. Replay expected responsibility used the provisional translation task mode
   instead of the final semantic responsibility.
3. Current multi-image evidence was not narrowed to the image ordinals
   referenced by the admitted turn before planning, and image identity
   presentation used every confirmed image instead of the router-selected
   bindings.

The repair keeps one production route. It selects current image products by
typed `image_ordinal` references before planning, preserves the full confirmed
image set in state, and renders identity cards only for the router-selected
product bindings. Replay chooses deterministic category-compatible candidates
and derives expected responsibility from the shared semantic outcome contract.

No raw-message parsing, product-ID special case, alternate processor, frontend
change, provider call, or rerun of the successful 48-turn translation batch is
allowed. RED/GREEN tests and post-fix debug logs must prove the three owner
repairs before the backend replay is regenerated.

## Terminal Result

Practical attempt 02 is `NO_GO`.

- The real DeepSeek translation batch passed 48/48.
- The current zero-provider backend replay passed 48/48.
- Browser validation found and closed one deterministic backend public-contract
  defect: explore recommendations now emit `NOT_APPLICABLE` consistently in
  decision, answer, and presentation events.
- The frontend was not changed.
- A later browser run observed copywriter `invalid_output` and fallback.
- A subsequent run emitted a goal clarification for a clear three-option
  recommendation.
- The required 14/14 browser run and fourteen-row screenshot review therefore
  did not complete.

Do not rerun the provider merely to sample a passing outcome. The terminal
evidence is recorded in
`practical-release-attempt-02/practical-release-report.json`.

## Controlled Demo Decision

The user accepted the current candidate for a controlled demonstration. This
creates a separate `DEMO_GO` result without changing the strict production
`NO_GO` result.

For Demo use, deterministic copywriter fallback and a recoverable
over-clarification are accepted degradations. Wrong product binding, state
corruption, unsafe output, internal errors, and broken rendering remain hard
failures. No further provider-stability repair loop is authorized.
