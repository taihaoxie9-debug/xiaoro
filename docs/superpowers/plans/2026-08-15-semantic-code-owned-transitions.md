# Semantic Code-Owned Transitions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking. The user explicitly forbids
> sub-agents; the main agent executes and reviews every step.

**Goal:** Make the model a source-bound semantic translator only and make
deterministic code the sole owner of add/retain/replace/remove constraint
transitions.

**Architecture:** Remove model-facing `acts`, ground references and values to
the current message, and add a pure transition reducer over the stored
`RecommendationQueryContext`. Reuse the existing exact parsers, TaskPlan,
safety gates, and ranking engine; do not add a second intent or recommendation
pipeline.

**Tech Stack:** Python 3.11, Pydantic v2 strict/frozen contracts, pytest,
SQLite-backed conversation state, existing DeepSeek single/two-stage adapters.

---

## 0. Execution Rules

**Repository:** `/Users/bytedance/Desktop/xiaoro-fresh`

**Branch:** `rebuild`

**Worktree:** Use the existing dirty rebuild worktree. Preserve all unrelated
changes. Do not reset, clean, or create a replacement worktree.

**Boundaries:**

- no sub-agents;
- no frontend rendering changes;
- no imports from `app.services`;
- no prompt-only case patches;
- no second model reviewer;
- no global phrase dictionary;
- no push or deploy.

**Long-running commands:** Start one process and poll its session every
30 seconds until exit. No output is not evidence of a hang. Do not launch a
duplicate pytest or model-gate process while the first process is alive.

**Repeated-failure audit:** After two consecutive failures at the same layer,
stop editing. Record:

```text
earliest failing layer
contract that owns the behavior
why the previous fix did not address the class
whether one component owns more than one responsibility
general fix selected
alternatives rejected
```

Then implement the general fix. Do not add a third phrase-specific patch.

**TDD:** Every production change starts from a focused failing test whose
failure reason is observed before implementation.

**Git:** The worktree already contains uncommitted implementation from prior
approved goals, including changes in files this plan must edit. Do not stage or
commit implementation files during this Goal. Record tested checkpoints in the
plan and closure report. Only the new plan documents may be committed before
execution.

## 1. File and Ownership Map

Create:

- `app/guide/intent/constraint_transitions.py`
  Pure state-diff and transition application.
- `tests/guide/intent/test_constraint_transitions.py`
  Table-driven transition invariants.
- `tests/fixtures/guide/intent/transition_metamorphic_v1.jsonl`
  Frozen behavior-equivalence cases.
- `docs/audits/semantic-transitions/architecture_checkpoint.md`
  Midpoint ownership audit.
- `docs/audits/semantic-transitions/closure_report.md`
  Final implementation and production-gap report.

Modify:

- `app/guide/understanding/semantic_contracts.py`
  Remove `SemanticAct*`; source-bind semantic references.
- `app/guide/understanding/semantic_detail_contracts.py`
  Remove `acts`; bump detail schema versions.
- `app/guide/understanding/two_stage_semantic.py`
  Compose the smaller detail contract.
- `app/guide/adapters/llm/intent_prompt.py`
  Remove state-mutation output instructions.
- `app/guide/adapters/llm/intent_detail_prompt.py`
  Request only source-bound meaning.
- `app/guide/intent/signal_merger.py`
  Remove semantic-act merge; validate reference spans.
- `app/guide/understanding/contracts.py`
  Add typed transition trace contracts only if they are public downstream.
- `app/guide/application/query_context.py`
  Provide deterministic slot identity helpers.
- `app/guide/application/text_recommendation_flow.py`
  Apply reducer output before planning/execution.
- `tools/guide_gates/intent_model_ab.py`
  Evaluate final transitions rather than raw acts.
- `tools/guide_gates/run_real_two_stage_intent_ab.py`
  Normalize the new schema and report unauthorized transitions.

Primary tests:

- `tests/guide/understanding/test_semantic_intent_contracts.py`
- `tests/guide/understanding/test_semantic_detail_contracts.py`
- `tests/guide/understanding/test_two_stage_semantic.py`
- `tests/guide/intent/test_signal_merger.py`
- `tests/guide/intent/test_constraint_transitions.py`
- `tests/guide/application/test_query_context.py`
- `tests/guide/application/test_text_recommendation_flow.py`
- `tests/guide/tools/test_run_real_two_stage_intent_ab.py`

## Task 1: Freeze the Current Unsafe and Redundant Outcomes

**Files:**

- Modify: `tests/guide/understanding/test_semantic_intent_contracts.py`
- Modify: `tests/guide/intent/test_signal_merger.py`
- Modify: `tests/guide/application/test_text_recommendation_flow.py`
- Create: `tests/fixtures/guide/intent/transition_metamorphic_v1.jsonl`

- [ ] **Step 1: Add a contract RED test that forbids model mutations**

Add:

```python
def test_semantic_contract_has_no_model_owned_constraint_mutations() -> None:
    fields = SemanticIntentProposal.model_fields

    assert "acts" not in fields
    assert not hasattr(semantic_contracts, "SemanticAct")
    assert not hasattr(semantic_contracts, "SemanticActKind")
    assert not hasattr(semantic_contracts, "SemanticActTarget")
```

- [ ] **Step 2: Run the contract test and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/understanding/test_semantic_intent_contracts.py::test_semantic_contract_has_no_model_owned_constraint_mutations
```

Expected: FAIL because `acts` and `SemanticAct*` still exist.

- [ ] **Step 3: Add state-outcome RED cases**

Freeze these outcomes in `transition_metamorphic_v1.jsonl`:

```json
{"case_id":"retain-alcohol-change-budget","message":"预算改成三百以内，而且还是不要含酒精的呢","before":{"category":"sunscreen","budget_maximum":"500","exclusions":["酒精"]},"expected":{"budget_maximum":"300","exclusions":["酒精"],"operations":[["budget","replace"],["ingredient_exclusion:酒精","retain"]]}}
{"case_id":"unmentioned-exclusion-survives","message":"预算改成三百以内","before":{"category":"sunscreen","budget_maximum":"500","exclusions":["酒精"]},"expected":{"budget_maximum":"300","exclusions":["酒精"],"operations":[["budget","replace"]]}}
{"case_id":"repeat-is-idempotent","message":"还是不要含酒精","before":{"category":"serum","exclusions":["酒精"]},"expected":{"exclusions":["酒精"],"operations":[["ingredient_exclusion:酒精","retain"]]}}
{"case_id":"fresh-does-not-inherit","message":"推荐一款面霜","before":{"category":"sunscreen","budget_maximum":"300","exclusions":["酒精"]},"expected":{"category":"skincare","budget_maximum":null,"exclusions":[]}}
```

- [ ] **Step 4: Add a RED application test**

Create a test that stores a sunscreen query with budget 500 and alcohol
exclusion, sends the budget-retention message, and asserts:

```python
assert after.query_context.budget_maximum == Decimal("300")
assert after.query_context.exclusions == ("酒精",)
assert after.query_context == expected_context
```

Also assert no second semantic call is made.

- [ ] **Step 5: Run focused tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/understanding/test_semantic_intent_contracts.py \
  tests/guide/intent/test_signal_merger.py \
  tests/guide/application/test_text_recommendation_flow.py
```

Expected: new contract and transition tests fail for the missing design.

## Task 2: Remove Model-Owned Acts

**Files:**

- Modify: `app/guide/understanding/semantic_contracts.py`
- Modify: `app/guide/understanding/semantic_detail_contracts.py`
- Modify: `app/guide/understanding/two_stage_semantic.py`
- Modify: `app/guide/adapters/llm/intent_prompt.py`
- Modify: `app/guide/adapters/llm/intent_detail_prompt.py`
- Modify: `tests/guide/adapters/test_intent_prompt.py`
- Modify: `tests/guide/adapters/test_intent_detail_prompt.py`

- [ ] **Step 1: Delete model-facing act types and fields**

Remove:

```python
class SemanticActKind(...)
class SemanticActTarget(...)
class SemanticAct(...)
acts: tuple[SemanticAct, ...]
```

Remove `drop_unknown_add_preference_targets`. Increment:

```text
guide-semantic-intent-v6 -> guide-semantic-intent-v7
guide-detail-recommendation-v4 -> guide-detail-recommendation-v5
guide-detail-followup-v4 -> guide-detail-followup-v5
```

- [ ] **Step 2: Remove act composition**

In `compose_semantic_proposal`, construct the new proposal without `acts`.
Remove `acts` from detail uniqueness validation.

- [ ] **Step 3: Simplify prompts**

Delete the act enum, target, admission table, retain/revise/withdraw, and
`add_preference` instructions. Keep:

```text
Translate only current-message meaning.
Every mutable candidate must quote exact raw_text and offsets.
Do not decide whether stored state is added, retained, replaced, or removed.
```

Do not add phrase examples for the known failing cases.

- [ ] **Step 4: Update adapter tests**

Assert:

```python
assert "revise_constraint" not in system
assert "withdraw_constraint" not in system
assert "add_preference" not in system
assert "raw_text" in system
assert "start" in system
assert "end" in system
```

- [ ] **Step 5: Run contract and adapter tests**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/understanding/test_semantic_intent_contracts.py \
  tests/guide/understanding/test_semantic_detail_contracts.py \
  tests/guide/understanding/test_two_stage_semantic.py \
  tests/guide/adapters/test_intent_prompt.py \
  tests/guide/adapters/test_intent_detail_prompt.py
```

Expected: PASS.

- [ ] **Step 6: Record the tested checkpoint**

Record the exact focused command, pass count, and current diff paths in the
plan status. Do not stage or commit shared dirty implementation files.

## Task 3: Source-Bind and Validate References

**Files:**

- Modify: `app/guide/understanding/semantic_contracts.py`
- Modify: `app/guide/intent/signal_merger.py`
- Modify: `tests/guide/intent/test_signal_merger.py`
- Modify: `tests/guide/understanding/test_semantic_detail_contracts.py`

- [ ] **Step 1: Write RED span tests**

Add tests for:

```text
exact image ordinal beats semantic clarification
wrong unique offset is rebound
wrong repeated raw text fails closed
candidate ordinal above visible count fails closed
current_item requires focused candidate
image_ordinal requires existing image
```

Use the desired contract:

```python
SemanticReference(
    kind="image_ordinal",
    ordinal=1,
    raw_text="第一张",
    start=0,
    end=3,
)
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/intent/test_signal_merger.py \
  tests/guide/understanding/test_semantic_detail_contracts.py
```

Expected: constructor or merge assertions fail because references are not
source bound.

- [ ] **Step 3: Extend the strict reference contract**

Add:

```python
class SemanticReference(_StrictModel):
    kind: ReferenceKind
    ordinal: int | None
    raw_text: str = Field(min_length=1, max_length=64)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
```

Validate ordinal shape in the model and current-message/context binding in the
merger.

- [ ] **Step 4: Implement one shared span rebind helper**

Reuse the same unique-exact-text policy used for product mentions and
preference candidates. Do not add a reference phrase vocabulary.

- [ ] **Step 5: Make exact resolved references veto stale clarification**

When exact code has one valid reference and typed context confirms it exists,
normalize a model `clarification(reference)` to the executable exact goal only
for protocol-closed messages. Open suffixes still require semantic meaning.

- [ ] **Step 6: Run focused tests**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/understanding \
  tests/guide/intent/test_signal_merger.py
```

Expected: PASS.

## Task 4: Implement the Pure Constraint Transition Reducer

**Files:**

- Create: `app/guide/intent/constraint_transitions.py`
- Create: `tests/guide/intent/test_constraint_transitions.py`
- Modify: `app/guide/intent/contracts.py`
- Modify: `app/guide/application/query_context.py`
- Modify: `app/guide/understanding/contracts.py`
- Modify: `app/guide/understanding/exact_parsing.py`
- Create: `tests/guide/understanding/test_exact_parsing.py`

- [ ] **Step 1: Write the complete table-driven RED suite**

Define tests around:

```python
result = reduce_constraint_state(
    previous=context,
    current_constraints=current,
    revision_confirmations=proofs,
    goal=goal,
)
```

Cover every slot:

```text
category
budget
skin
efficacy
ingredient exclusion
ingredient inclusion
facet(field_key, value)
```

Cover add, retain, replace, remove, unmentioned retention, duplicate
idempotence, conflicting current values, missing proof, and fresh-request
noninheritance.

- [ ] **Step 2: Run reducer tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/intent/test_constraint_transitions.py
```

Expected: import failure for the missing reducer.

- [ ] **Step 3: Add strict transition contracts**

Implement:

```python
class ConstraintTransition(_StrictContract):
    target: str
    operation: Literal["add", "retain", "replace", "remove"]
    before: TaskConstraint | None
    after: TaskConstraint | None
    source_span: SourceSpan
    authority: Literal["exact", "validated_semantic"]


class ConstraintTransitionResult(_StrictContract):
    constraints: tuple[TaskConstraint, ...]
    transitions: tuple[ConstraintTransition, ...]
    issues: tuple[UnderstandingIssue, ...]
```

Require deterministic constraint and transition ordering.

- [ ] **Step 4: Enrich exact proof for multi-valued targets**

Extend `ExactRevisionConfirmation` with:

```python
affected_value: str | None = None
```

Exact parsing must populate a normalized value when a revision or withdrawal
targets one ingredient exclusion, inclusion, or facet value. Target-kind-only
proof remains legal for single-valued slots but cannot authorize removal of a
multi-valued slot. Add RED tests before the parser change.

- [ ] **Step 5: Implement canonical slot identities**

Use:

```text
category
budget
skin
efficacy
exclusion:<casefold value>
inclusion:<casefold value>
facet:<field_key>:<casefold value>
```

Do not collapse distinct facet values.

- [ ] **Step 6: Implement reducer invariants**

The reducer:

- preserves unmentioned constraints in follow-up/revision mode;
- starts empty for a fresh recommendation;
- treats equal values as retain;
- requires exact proof for single-slot replacement and any removal;
- forbids target-kind-only deletion of multi-valued constraints;
- cannot weaken a safety-sensitive constraint from a semantic candidate;
- returns an issue rather than guessing on conflicts.

- [ ] **Step 7: Run reducer and query-context tests**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/intent/test_constraint_transitions.py \
  tests/guide/application/test_query_context.py \
  tests/guide/understanding/test_exact_parsing.py
```

Expected: PASS.

- [ ] **Step 8: Record the tested reducer checkpoint**

Record reducer and QueryContext pass counts and diff paths. Do not stage or
commit implementation files.

## Task 5: Integrate Transitions into the Text Runtime

**Files:**

- Modify: `app/guide/application/text_recommendation_flow.py`
- Modify: `app/guide/intent/task_planning.py`
- Modify: `app/guide/intent/signal_merger.py`
- Modify: `tests/guide/application/test_text_recommendation_flow.py`
- Modify: `tests/guide/intent/test_task_planning.py`

- [ ] **Step 1: Add RED end-to-end cases**

Freeze:

```text
budget replace + alcohol retain
skin replace + budget retain
category replace does not inherit old facets
one exclusion added without deleting old exclusion
explicit exclusion removal removes only named value
soft preference repetition stays one facet
fresh request does not inherit old query
serious safety condition cannot become soft
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/intent/test_task_planning.py
```

Expected: new state-outcome assertions fail.

- [ ] **Step 3: Remove `_merge_semantic_acts`**

Delete semantic-act summaries, confirmation matching, and act-derived issues
from `signal_merger.py`. Keep exact revision confirmations as reducer input.

- [ ] **Step 4: Apply transition result before recommendation**

In text flow:

1. load the previous query context;
2. understand current-turn meaning;
3. compile current-turn constraints;
4. reduce previous plus current state;
5. clarify on transition issues;
6. decide recommendation with the reduced constraints;
7. persist the reduced context.

Do not add another model call.

- [ ] **Step 5: Keep existing closed fast paths behavior-identical**

Adapt `parse_followup`, `parse_budget_revision`, and `parse_skin_revision`
outputs to the same transition semantics. Their public SSE behavior and CAS
versioning remain unchanged.

- [ ] **Step 6: Run application and state regressions**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/application/test_cross_worker_text_state.py \
  tests/guide/runtime/test_composition.py \
  tests/guide/runtime/test_runtime_http.py
```

Expected: PASS.

## Task 6: Replace Raw-Act Model Gates with Final-State Gates

**Files:**

- Modify: `tools/guide_gates/intent_model_ab.py`
- Modify: `tools/guide_gates/run_real_two_stage_intent_ab.py`
- Modify: `tests/guide/tools/test_run_real_two_stage_intent_ab.py`
- Modify: `tests/guide/tools/test_guide_pipeline_evaluator.py`
- Modify: `tests/fixtures/guide/intent/semantic_intent_ab_v2.jsonl`
- Modify: `tests/fixtures/guide/intent/two_stage_smoke_v1.jsonl`

- [ ] **Step 1: Write RED evaluator tests**

Add a summary field:

```python
unauthorized_constraint_transition_count: int
```

Assert the gate catches:

```text
unmentioned field changed
retained value labeled as replace and actually replaced
hard constraint removed without proof
fresh request inherited stale context
wrong product selected
invalid output reached TaskPlan
```

- [ ] **Step 2: Run evaluator tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/tools/test_run_real_two_stage_intent_ab.py \
  tests/guide/tools/test_guide_pipeline_evaluator.py
```

Expected: missing-field or assertion failures.

- [ ] **Step 3: Update normalized rows and summaries**

Remove raw-act correctness as a hard gate. Record expected and actual final
transitions and TaskPlan state. Preserve route, detail, reference, safety,
product-selection, invalid-output, and latency metrics.

- [ ] **Step 4: Migrate fixtures without weakening user outcomes**

Remove only raw `acts` expectations. Add:

```json
"expected_state": {
  "preserved": ["ingredient_exclusion"],
  "replaced": ["budget"],
  "removed": []
}
```

Do not change expected goal, topic, references, safety, products, or final
constraints to accommodate current model output.

- [ ] **Step 5: Run gate unit tests**

Run:

```bash
.venv/bin/python -m pytest -q tests/guide/tools
```

Expected: PASS.

## Task 7: Midpoint Architecture Audit

**Files:**

- Create: `docs/audits/semantic-transitions/architecture_checkpoint.md`

- [ ] **Step 1: Record ownership after integration**

The report must answer:

```text
Does the model output any stored-state operation?
Can any unmentioned constraint change?
Can semantic output weaken exact safety?
Are preferences represented twice?
Do closed operations share one reducer?
Did a second intent/recommendation path appear?
Which exact parsers remain field-specific, and why?
```

- [ ] **Step 2: Inspect runtime imports and consumers**

Run:

```bash
rg -n "SemanticAct|revise_constraint|withdraw_constraint|add_preference" \
  app/guide app/guide_runtime
rg -n "reduce_constraint_state" app/guide
```

Expected: no model-facing act contract; one code-owned reducer.

- [ ] **Step 3: Fix ownership defects with TDD**

If the audit finds duplicated transition logic or model authority, first add a
failing ownership/behavior test, then remove the duplication. Do not document
known architectural violations as accepted debt.

- [ ] **Step 4: Record the integrated semantic checkpoint**

Record the architecture audit path, focused pass counts, and complete changed
path list. Confirm `git diff --cached --name-only` is empty; do not stage or
commit implementation in the shared dirty worktree.

## Task 8: Local and Official Semantic Gates

**Files:**

- Create: `docs/audits/semantic-transitions/closure_report.md`

- [ ] **Step 1: Run focused understanding and intent**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/understanding \
  tests/guide/intent \
  tests/guide/application/test_query_context.py \
  tests/guide/application/test_text_recommendation_flow.py
```

Expected: PASS.

- [ ] **Step 2: Run Guide full and runtime**

Start each command once and poll until exit:

```bash
.venv/bin/python -m pytest -q tests/guide
.venv/bin/python -m pytest -q tests/guide/runtime
```

Expected: PASS.

- [ ] **Step 3: Run static gates**

```bash
.venv/bin/python -m compileall -q app tools
.venv/bin/python -m pytest -q \
  tests/guide/test_architecture_boundaries.py \
  tests/guide/runtime/test_import_boundary.py
git diff --check
```

Expected: PASS.

- [ ] **Step 4: Run three official model gates**

Run sequentially and poll each process:

```bash
.venv/bin/python -m tools.guide_gates.run_official_deepseek_smoke \
  --output-dir /private/tmp/xiaoro-semantic-transitions-run-1
.venv/bin/python -m tools.guide_gates.run_official_deepseek_smoke \
  --output-dir /private/tmp/xiaoro-semantic-transitions-run-2
.venv/bin/python -m tools.guide_gates.run_official_deepseek_smoke \
  --output-dir /private/tmp/xiaoro-semantic-transitions-run-3
```

Do not run them in parallel. Record summary hashes and every hard-gate metric.

- [ ] **Step 5: Write semantic closure report**

Include:

- schema versions;
- removed model responsibilities;
- transition invariants;
- local test results;
- three real-model results;
- architecture checkpoint findings;
- selected lane or `NO-GO`;
- remaining production risks.

Do not claim GO when any official hard gate is red.
