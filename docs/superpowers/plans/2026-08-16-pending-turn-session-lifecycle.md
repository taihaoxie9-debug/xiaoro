# Pending Turn And Session Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a complete fail-closed Canonical product alias registry,
resume unfinished budget clarifications from durable structured state, and
make browser session deletion remove the matching backend short-term state.

**Architecture:** Discover and review aliases from the current evidence
manifest, Canonical names, and legacy candidates before publishing exact,
variant, or always-clarify runtime bindings. Then add a typed pending-turn
payload to the existing conversation snapshot and resolve it before generic
semantic routing. Reuse SQLite CAS and terminal-event commit semantics, then
add an owner-checked deletion endpoint consumed transactionally by the
browser.

**Tech Stack:** Python 3.11, Pydantic v2, FastAPI, SQLite WAL/CAS, vanilla JavaScript, typed SSE, pytest, Playwright.

---

## File Responsibility Map

- `app/guide/feedback/contracts.py`
  - pending-turn strict contracts and snapshot invariant.
- `app/guide/feedback/ports.py`
  - state deletion port and transition validation.
- `app/guide/application/pending_turn.py`
  - pure construction and deterministic reply classification.
- `app/guide/application/text_recommendation_flow.py`
  - pending resolution before normal understanding and recommendation resume.
- `app/guide/presentation/sse_events.py`
  - internal typed pending payload on clarification events.
- `app/guide/application/chat_api_adapter.py`
  - stage pending state only after public event validation.
- `app/guide/adapters/state/in_memory_conversation_state.py`
  - owner-checked in-memory deletion.
- `app/guide/adapters/state/sqlite_conversation_state.py`
  - owner-checked durable deletion.
- `app/guide_runtime/app.py`
  - trusted session deletion endpoint.
- `app/static/chat.html`
  - await backend deletion before deleting local history.
- focused contract, application, cross-worker, HTTP, and frontend tests.

## Task 0: Audit And Publish All Known Product Aliases

**Files:**
- Create: `tools/guide_data/audit_product_aliases.py`
- Create: `tests/guide/tools/test_audit_product_aliases.py`
- Create: `data/canonical/product_alias_reviews_v1.jsonl`
- Create: `docs/audits/semantic-transitions/product_alias_audit_v1.json`
- Modify: `app/guide/retrieval/controlled_product_aliases.py`
- Modify: `app/guide/retrieval/product_name_resolver.py`
- Modify: `data/canonical/controlled_product_aliases_v1.jsonl`
- Modify: `data/canonical/controlled_product_aliases_v1_manifest.json`
- Modify: `tests/guide/retrieval/test_controlled_product_aliases.py`
- Modify: `app/guide_runtime/composition.py`
- Modify: `tests/guide/runtime/test_composition.py`

- [ ] **Step 1: Write failing discovery and coverage tests**

Require the audit to discover identity candidates from:

```text
current accepted ProductEvidence nickname/name relations
Canonical names with nickname-like identity surfaces
the three legacy alias dictionaries as review-only candidates
```

Every normalized candidate must have exactly one reviewed disposition:

```text
approved_exact_product
approved_exact_variant
ambiguous_family
marketing_phrase
ingredient_nickname
unavailable_product
unresolved_candidate
```

The test must fail for an unreviewed accepted evidence nickname.

- [ ] **Step 2: Write failing identity-policy tests**

Cover:

```text
神仙水 / 健康水 / 樱花水 / 前男友面膜
兰蔻小白管 / 三色遮瑕 / 菁纯精华气垫
CPB长管隔离 / 夜胶原霜 / 传奇洁颜霜
小黑瓶 and 小棕瓶 version/product boundaries
B5 / 菁纯 / 粉水 / 琥珀 multi-SKU clarification
Urban Decay exact variant aliases with variant_scope
油皮救星 / 冰川蛋白 / 律波肽 excluded from identity
legacy aliases whose products are absent remain unavailable/unresolved
```

- [ ] **Step 3: Verify RED**

Run:

```bash
.venv/bin/python -m pytest \
  tests/guide/tools/test_audit_product_aliases.py \
  tests/guide/retrieval/test_controlled_product_aliases.py -q
```

Expected: missing audit tool and unsupported alias identity policies.

- [ ] **Step 4: Implement the strict audit contracts**

The audit row records alias, discovery sources, candidate product IDs,
evidence IDs, identity scope, reviewed disposition, optional variant scope,
and rationale. Validate all IDs and exact-variant evidence against the
current manifest-bound assets.

- [ ] **Step 5: Publish the reviewed runtime subset**

Only exact product, exact variant, and ambiguous family rows may enter
`controlled_product_aliases_v1.jsonl`. Regenerate the SHA256 and record
count. Never copy the legacy dictionary directly.

- [ ] **Step 6: Implement fail-closed runtime policies**

Exact product aliases resolve one Canonical ID. Exact variant aliases retain
their reviewed scope. Ambiguous family aliases are recognized but return
`ambiguous_reference`. Longest surface still wins.

- [ ] **Step 7: Wire production composition**

Load the manifest-bound registry in `build_runtime_orchestrator`; no
production path may construct the resolver without it.

- [ ] **Step 8: Verify GREEN**

Run audit, resolver, composition, application, and HTTP/SSE integration
tests. Save the machine-readable audit report with counts by disposition and
all unresolved candidates.

## Task 1: Add The Strict Pending-Turn Contract

**Files:**
- Modify: `app/guide/feedback/contracts.py`
- Modify: `app/guide/feedback/ports.py`
- Test: `tests/guide/feedback/test_conversation_state_contracts.py`

- [ ] **Step 1: Write failing contract tests**

Add tests proving:

```python
pending = PendingTurn(
    kind="clarification",
    gap=ClarificationCode.BUDGET,
    attempts=1,
    source_conversation_version=0,
    source_message="干敏肌想要抗初老精华，预算1000左右",
    expected_response="confirm_or_correct",
    resume_mode="recommendation",
    resume_context=PendingRecommendationContext(
        category="serum",
        skin="dry",
        efficacy="anti_aging",
    ),
    proposed_budget=PendingBudgetRange(
        minimum=Decimal("900"),
        maximum=Decimal("1100"),
    ),
)
```

Reject mismatched gap/payload combinations, invalid ranges, attempts above
two, and snapshots that carry candidates without `query_context`.

- [ ] **Step 2: Verify RED**

Run:

```bash
.venv/bin/python -m pytest \
  tests/guide/feedback/test_conversation_state_contracts.py -q
```

Expected: import failure for the pending-turn contracts.

- [ ] **Step 3: Implement strict frozen contracts**

Add:

```python
class PendingBudgetRange(_StrictContract):
    minimum: Decimal
    maximum: Decimal

class PendingRecommendationContext(_StrictContract):
    category: RecommendationCategory
    skin: RecommendationSkin | None = None
    efficacy: RecommendationEfficacy | None = None
    exclusions: tuple[StoredExclusion, ...] = ()
    inclusions: tuple[StoredExclusion, ...] = ()
    facets: tuple[StoredFacet, ...] = ()
    concepts: tuple[StoredConcept, ...] = ()
    safety_sensitive: bool = False

class PendingTurn(_StrictContract):
    kind: Literal["clarification"] = "clarification"
    gap: ClarificationCode
    attempts: int = Field(ge=1, le=2)
    source_conversation_version: int = Field(ge=0)
    source_message: str = Field(min_length=1, max_length=4000)
    expected_response: Literal["confirm_or_correct", "supply_value"]
    resume_mode: Literal["recommendation"]
    resume_context: PendingRecommendationContext
    proposed_budget: PendingBudgetRange | None = None
```

Replace `ConversationSnapshot.clarification` with
`pending_turn: PendingTurn | None`. Keep a read-only compatibility property
only if existing tests require one during migration.

- [ ] **Step 4: Update transition validation**

Validate immutable source data, monotonic attempts, and clearing only on a
successful replacement or explicit cancellation.

- [ ] **Step 5: Verify GREEN**

Run the contract and in-memory/SQLite state tests.

## Task 2: Build And Resolve Pending Budget Turns

**Files:**
- Create: `app/guide/application/pending_turn.py`
- Modify: `app/guide/application/text_recommendation_flow.py`
- Modify: `app/guide/presentation/sse_events.py`
- Modify: `app/guide/application/chat_api_adapter.py`
- Test: `tests/guide/application/test_text_recommendation_flow.py`
- Test: `tests/guide/application/test_chat_api_adapter.py`

- [ ] **Step 1: Write the failing screenshot-path test**

Exercise public events:

```text
turn 1: 干敏肌想要抗初老精华，预算1000左右
turn 2: 是的
```

Assert turn 1 persists a budget pending turn with `900-1100`, and turn 2
emits recommendation products without a second goal clarification.

- [ ] **Step 2: Add failing reply-matrix tests**

Cover:

```text
是的 / 对 / 没错
不是
改成800到1000
是的，而且不要酒精
改看防晒吧
差不多吧
```

Assert accept, reject, correct, supplement, cancel-and-restart, and preserve
outcomes respectively.

- [ ] **Step 3: Verify RED**

Run only the new node IDs. Expected: `是的` returns GOAL clarification.

- [ ] **Step 4: Implement the pure state machine**

Expose:

```python
PendingReplyKind = Literal[
    "affirm",
    "reject",
    "correct",
    "supplement",
    "replace_task",
    "ambiguous",
]

def build_pending_turn(...) -> PendingTurn | None: ...
def classify_pending_reply(...) -> PendingReply: ...
def resume_pending_recommendation(...) -> TaskPlan: ...
```

Use exact parsers for corrections and supplements. Phrase matching is only
allowed for bounded short affirmation/rejection.

- [ ] **Step 5: Attach pending data to clarification events**

Add an internal optional pending payload to `ClarifyData`. The public adapter
must keep it out of the browser message body while preserving it as typed
delivery metadata for `_stage_clarification`.

- [ ] **Step 6: Resolve pending before generic understanding**

At `_stream_locked`, after version/owner validation and before follow-up
parsing:

```python
if snapshot is not None and snapshot.pending_turn is not None:
    resolution = resolve_pending_turn(...)
    if resolution.handled:
        yield from ...
        return
```

- [ ] **Step 7: Verify GREEN**

Run application and adapter suites.

## Task 3: Prove Durable Multi-Worker Isolation

**Files:**
- Modify: `tests/guide/application/test_cross_worker_text_state.py`
- Modify: `tests/guide/adapters/state/test_sqlite_conversation_state.py`

- [ ] **Step 1: Write failing restart and isolation tests**

Prove:

- worker A asks the budget clarification;
- worker B accepts it and resumes;
- session B cannot resolve session A's pending turn;
- stale version cannot consume the pending turn;
- replay after success cannot consume it twice.

- [ ] **Step 2: Verify RED**

Run the new cross-worker nodes and confirm the pending data is currently
missing.

- [ ] **Step 3: Complete SQLite round-trip support**

The snapshot JSON already serializes nested Pydantic data. Update schema
version/migration only if the strict schema validator requires it; never
rewrite unrelated state files.

- [ ] **Step 4: Verify GREEN**

Run all conversation state and cross-worker tests.

## Task 4: Add Owner-Checked Session Deletion

**Files:**
- Modify: `app/guide/feedback/ports.py`
- Modify: `app/guide/adapters/state/in_memory_conversation_state.py`
- Modify: `app/guide/adapters/state/sqlite_conversation_state.py`
- Modify: `app/guide/application/chat_api_adapter.py`
- Modify: `app/guide_runtime/app.py`
- Test: `tests/guide/adapters/state/test_in_memory_conversation_state.py`
- Test: `tests/guide/adapters/state/test_sqlite_conversation_state.py`
- Test: `tests/guide/runtime/test_runtime_http.py`

- [ ] **Step 1: Write failing deletion tests**

Assert:

```text
matching owner -> 204 and state absent
missing session -> 204
wrong owner -> 404 and state preserved
pending turn -> removed with the session
long-term profile -> preserved
```

- [ ] **Step 2: Verify RED**

Run the new tests. Expected: missing `delete` method and HTTP 405/404.

- [ ] **Step 3: Implement state-port deletion**

Use an owner-scoped atomic delete. SQLite must check owner columns and delete
inside `BEGIN IMMEDIATE`; it must not load-then-delete outside one
transaction.

- [ ] **Step 4: Add the runtime endpoint**

Add:

```text
DELETE /api/v1/chat/sessions/{session_id}
```

Derive the trusted actor from the request cookie/account, call the
conversation-state delete port, and return 204 for both owned and absent
sessions without revealing foreign-session existence.

- [ ] **Step 5: Verify GREEN**

Run state and HTTP suites.

## Task 5: Make Browser Deletion Transactional

**Files:**
- Modify: `app/static/chat.html`
- Modify: `tests/guide/runtime/test_frontend_scope.py`
- Modify: `tests/guide/runtime/test_frontend_presentation_history.py`

- [ ] **Step 1: Write failing frontend contract tests**

Require `deleteSession` to:

1. abort an active request;
2. call the backend DELETE endpoint;
3. remove local history/version/feedback only after a 204 response;
4. preserve local history and show an error on failure.

- [ ] **Step 2: Verify RED**

Run the focused frontend tests. Expected: no DELETE fetch exists.

- [ ] **Step 3: Implement async deletion**

Convert `deleteSession` to `async`, await:

```javascript
fetch(
  `/api/v1/chat/sessions/${encodeURIComponent(sessionId)}`,
  {method: 'DELETE'}
)
```

Only then remove local state.

- [ ] **Step 4: Verify GREEN**

Run the frontend history/scope tests.

## Task 6: Closure Gates

**Files:**
- Create: `docs/audits/semantic-transitions/pending-turn-closure.md`

- [ ] **Step 1: Run focused suites**

```bash
.venv/bin/python -m pytest \
  tests/guide/feedback/test_conversation_state_contracts.py \
  tests/guide/adapters/state/test_in_memory_conversation_state.py \
  tests/guide/adapters/state/test_sqlite_conversation_state.py \
  tests/guide/application/test_chat_api_adapter.py \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/application/test_cross_worker_text_state.py \
  tests/guide/runtime/test_runtime_http.py \
  tests/guide/runtime/test_frontend_scope.py \
  tests/guide/runtime/test_frontend_presentation_history.py \
  -q
```

- [ ] **Step 2: Run full pytest**

```bash
.venv/bin/python -m pytest -q
```

- [ ] **Step 3: Run real browser paths**

Verify:

- screenshot path completes after `是的`;
- correction and topic replacement work;
- two browser sessions remain isolated;
- deleting a session removes its backend snapshot;
- no console or network errors.

- [ ] **Step 4: Write closure evidence**

Record exact test counts, browser transcript, SQLite absence after deletion,
and the explicit statement that long-term profile behavior was not changed.
