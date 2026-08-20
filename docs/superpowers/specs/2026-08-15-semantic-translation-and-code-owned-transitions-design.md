# Semantic Translation and Code-Owned State Transitions Design

**Date:** 2026-08-15

**Repository:** `/Users/bytedance/Desktop/xiaoro-fresh`

**Branch:** `rebuild`

**Status:** Proposed for implementation

## 1. Decision

The model remains a one-call natural-language translator. It may identify:

- the conversational goal and topic;
- referenced candidates, images, products, or prior context;
- source-bound budget, preference, safety, and product-mention candidates;
- unrestricted question meaning used for product-scoped evidence retrieval.

The model must not decide whether a stored constraint is added, retained,
replaced, or removed. Those state transitions belong to deterministic code.

The runtime will not add:

- a second model call that judges the first model;
- a second recommendation engine;
- a global phrase dictionary intended to enumerate user language;
- prompt examples for every observed failure;
- model-owned product facts, scores, hard filters, or safety decisions.

The implementation changes the authority boundary, not the data layer or
ranking formulas.

## 2. Why This Phase Exists

The evidence and ranking backend is already closed:

```text
accepted ProductEvidence reviewed = 1,079
deduplicated SelectionFact rows = 2,336
full Guide regression = 7,365 passed
hard-constraint override in official gates = 0
```

Three official model gates still selected no production lane. The failures are
not caused by missing product facts or a broken ranker. They occur before
decision execution, in semantic route/detail translation.

The current semantic contract asks the model to emit both:

1. what the current message says, such as a budget or preference candidate;
2. what operation should be applied to stored state, such as
   `revise_constraint` or `add_preference`.

Those responsibilities overlap. The same meaning can appear in
`preference_candidates` and `acts`, and the model must distinguish subtle
transaction semantics such as "retain" versus "revise".

### 2.1 Real failure: retention mislabeled as revision

Input:

```text
预算改成三百以内，而且还是不要含酒精的呢
```

Typed context says budget and ingredient exclusion are already active.

Expected:

```text
budget: replace with maximum 300
ingredient exclusion: retain existing value
```

The single-stage control returned:

```json
{
  "acts": [
    {"kind": "revise_constraint", "target": "budget"},
    {
      "kind": "revise_constraint",
      "target": "ingredient_exclusion"
    }
  ]
}
```

The model found both meanings but mislabeled the restated alcohol condition as
a mutation. Existing exact proof prevented a hard-constraint override, so the
final TaskPlan was not corrupted. The redundant model field still failed the
semantic gate and increased contract complexity.

### 2.2 Real failure: resolved reference paired with clarification

Input:

```text
第一张呢
```

Typed context says one image is available. The model returned the correct
`image_ordinal=1` reference but classified the goal as clarification. The
output is internally inconsistent: the target is resolved, yet the route asks
the user to identify it again.

### 2.3 Real failure: one meaning emitted through two channels

Input:

```text
想找不含酒精的修护精华
```

The model emitted both:

```text
preference candidate: ingredient_exclusion / 不含酒精
act: add_preference / ingredient_exclusion
```

The candidate already carries the source-bound meaning. The act adds no
executable information and creates a second place that can disagree.

## 3. Design Alternatives

### 3.1 Prompt-only correction

Keep the existing schema and add more instructions and examples for
"retain", "revise", "withdraw", and "add".

Rejected because human phrasing is open-ended, the model still owns a
deterministic state decision, and each new example makes the prompt longer
without removing the duplicated responsibility.

### 3.2 Second model as reviewer

Call another model to compare the first output with the message and context.

Rejected because it doubles inference work, introduces disagreement between
two probabilistic components, and still does not create a deterministic
authority for stored state.

### 3.3 Translation-first contract with code-owned transitions

Keep one semantic call, remove model-owned constraint mutation acts, bind
translated values to current-message spans, and compute state changes from
typed current state plus current-turn meaning.

Selected because it removes the ambiguous responsibility instead of trying to
prompt around it. It also reuses the existing exact parsers, QueryContext,
TaskPlan contracts, safety gates, and ranking path.

## 4. Authority Boundaries

### 4.1 Model authority

The model may propose open semantic meaning:

```text
goal
topic
references
product mentions
budget candidates
preference candidates
observations
question meaning
safety severity
```

Every value that can influence a constraint must either:

- carry a current-message source span and exact raw text; or
- be independently confirmed by the exact lane.

The model cannot emit:

```text
revise_constraint
withdraw_constraint
add_preference
```

Non-executable model acts are not retained as audit decoration.

### 4.2 Exact-lane authority

Exact code remains authoritative for:

- numeric budget bounds and direction;
- explicit revision or withdrawal markers;
- absolute ingredient inclusion and exclusion;
- closed ordinal and image references;
- category negation and closed category transitions;
- source-span validation.

Exact parsing does not attempt to enumerate all open preferences. It proves
only closed operations for which deterministic parsing is appropriate.

### 4.3 State-transition authority

Code compares:

```text
stored RecommendationQueryContext
+ validated current-turn constraints and preferences
+ exact revision/withdrawal proof
```

It returns a new immutable constraint set and an auditable transition list.
The model never receives stored values and never computes the diff.

### 4.4 Decision authority

Existing code remains the sole owner of:

- hard filtering;
- safety gates;
- soft-ranking weights;
- duplicate scoring;
- product selection;
- final TaskPlan execution.

## 5. Semantic Contract

### 5.1 Remove overlapping acts

`SemanticIntentProposal`, `RecommendationDetails`, and `FollowupDetails` stop
carrying `acts`.

The following model-facing types are removed:

```text
SemanticAct
SemanticActKind
SemanticActTarget
```

Existing `semantic_proposals` strings that only record act summaries are
removed from public behavior or replaced by code-generated transition traces.

This is a schema version change. Old model responses containing `acts` are
rejected by `extra="forbid"` and cannot silently enter the new path.

### 5.2 Keep source-bound meaning candidates

The existing candidates remain:

```text
SemanticNumberCandidate
SemanticPreferenceCandidate
SemanticProductMention
```

Their `raw_text`, `start`, and `end` fields are rebound to the current message
before use. Wrong offsets may be corrected only when the raw text occurs
exactly once. Repeated ambiguous text fails closed.

### 5.3 Ground semantic references

Semantic references gain source binding:

```python
class SemanticReference:
    kind: ReferenceKind
    ordinal: int | None
    raw_text: str
    start: int
    end: int
```

Code validates:

- the raw text matches the current message;
- an ordinal is within the typed visible candidate or image count;
- `current_item` requires one focused item;
- `current_batch` requires a nonempty visible batch;
- a semantic reference cannot override a conflicting exact reference.

The internal `ReferenceDraft` remains the normalized downstream contract.

### 5.4 Keep open values lossless

The model may translate an open description into a known ranking field, but
the source phrase remains available in the candidate and audit trace.

For example:

```text
raw_text = "像刚洗完床单又晒过太阳"
field = fragrance_description
normalized value = the source-bound semantic phrase
```

The operation vocabulary is closed; preference values are not compressed into
a global fixed dictionary.

## 6. Code-Owned Constraint Transitions

### 6.1 Transition contract

A pure transition resolver produces:

```python
class ConstraintTransition:
    target: ConstraintTarget
    operation: Literal["add", "retain", "replace", "remove"]
    before: TaskConstraint | None
    after: TaskConstraint | None
    source_span: SourceSpan
    authority: Literal["exact", "validated_semantic"]
```

The resolver accepts the previous `RecommendationQueryContext`, validated
current-turn drafts, exact revision confirmations, and the resolved
conversation goal.

It does not call a model, catalog, retriever, or ranker.

### 6.2 General rules

The reducer enforces these invariants:

1. A constraint not mentioned in the current turn remains unchanged during a
   follow-up or revision.
2. A current value equal to the stored value produces `retain`, not `replace`.
3. A different value for a single-valued slot requires exact revision proof
   before producing `replace`.
4. Removing a stored value requires exact withdrawal proof.
5. A new value with no stored value produces `add`.
6. Repeating the same value is idempotent and cannot create duplicates.
7. One source span cannot authorize unrelated targets.
8. Conflicting current-turn values fail closed with a typed clarification.
9. A fresh recommendation does not inherit a previous query merely because a
   snapshot exists.
10. Safety-sensitive constraints cannot be weakened by a semantic candidate.

### 6.3 Slot behavior

Single-valued slots:

```text
category
budget
skin
efficacy
```

Multi-valued slots:

```text
ingredient exclusions
ingredient inclusions
soft facets keyed by (field_key, normalized value)
```

For multi-valued slots, an exact withdrawal must identify the value or the
request must clarify. A target-kind-only withdrawal cannot erase every stored
value. The exact proof must therefore carry the normalized affected value, or
carry a source span from which exact code deterministically reconstructs that
value. A model-proposed value cannot complete an incomplete withdrawal proof.

### 6.4 Existing closed operations

The current code-owned parsers remain the starting point:

```text
parse_followup
parse_budget_revision
parse_skin_revision
parse_exact_revision_confirmations
```

Their outputs are adapted to the common transition contract. They are not
replaced by model fields.

The existing application fast paths may remain while behavior is migrated,
but the final transition semantics must be shared and tested once.

## 7. End-to-End Data Flow

```text
user message
  -> exact parsing and one semantic call in parallel
  -> strict semantic schema validation
  -> source-span and typed-context validation
  -> signal merger creates current-turn meaning
  -> code-owned constraint transition resolver
  -> TaskPlan compiler
  -> hard filter
  -> one-slot weighted soft rank
  -> typed decision/evidence payload
```

There is no semantic judge call after the translator.

If the semantic provider is unavailable:

- a protocol-closed exact operation may continue with exact proof;
- open semantic work fails closed with typed clarification;
- the runtime never falls back to the legacy agent.

## 8. Error Containment

Perfect language understanding is not a release requirement. Bounded failure
is.

### 8.1 Ordinary preference failure

If an open ordinary preference cannot be translated or validated, drop only
that soft dimension. Keep recall wide and preserve all hard constraints.

### 8.2 Reference failure

If a reference does not exist in typed context or has conflicting authorities,
clarify the reference. Do not select a guessed product.

If exact code resolves the only valid reference, a stale semantic
clarification cannot override it.

### 8.3 State-transition failure

If a proposed current value lacks source binding, conflicts with exact code,
or lacks the required revision proof:

- do not mutate stored state;
- preserve the previous query;
- return a typed clarification only when execution depends on the unresolved
  transition.

### 8.4 Safety failure

Allergy, pregnancy, active damage, adverse reaction, absolute inclusion or
exclusion, and unknown severity remain strict.

Merchant-positive safety evidence cannot satisfy a hard condition. An
unverified safety condition fails closed rather than silently becoming a soft
preference.

## 9. Testing Strategy

### 9.1 Contract tests

Freeze that model schemas:

- contain no state-mutation acts;
- reject legacy `acts`;
- require source-bound candidates;
- reject or safely rebind invalid spans;
- preserve open preference text.

### 9.2 Reducer tests

Use table-driven tests for every slot:

```text
absent -> value = add
same -> same = retain
old -> different with proof = replace
old -> different without proof = preserve + clarify
old -> explicit withdrawal = remove
old -> unmentioned = retain
duplicate -> same = one value
```

### 9.3 Metamorphic tests

Test behavioral invariants instead of enumerating phrases:

- clause reordering does not change the final constraint state;
- adding a retention phrase does not create a mutation;
- adding unrelated words cannot mutate another field;
- repeating a condition is idempotent;
- one-field revision changes only that field;
- a negation applies only to its source-bound target;
- an unavailable ordinal never binds a product;
- equivalent paraphrases produce the same TaskPlan;
- serious safety paraphrases never enter the weak soft path.

These tests run offline. Production still performs one semantic call.

### 9.4 Real-model gates

The frozen smoke and full fixtures keep their user-visible expectations.
Raw model `acts` expectations are replaced by stronger final-state assertions:

```text
expected TaskPlan
expected ConstraintTransition set
expected preserved constraints
expected references
expected safety disposition
```

This is not a weakened gate. It removes a non-executable model field and adds
checks at the actual authority boundary.

Before frontend work, run the official broad gate three independent times.
All three runs must satisfy:

```text
selected_lane is the same non-null lane
hard_constraint_override_count = 0
unauthorized_constraint_transition_count = 0
invalid_output_task_plan_invocation_count = 0
wrong_product_selection_count = 0
unsafe_task_plan_mismatch_count = 0
```

Route/detail quality thresholds remain enforced by the existing gate. Fixture
expectations cannot be edited merely to make a model pass.

## 10. Migration and Compatibility

This is an intentional internal schema break:

- increment semantic intent and affected detail schema versions;
- update both single-stage control and two-stage prompt adapters;
- update gate normalization for the new contract;
- reject cached responses from old schema versions;
- preserve public SSE, TaskPlan, SelectionSlotData, product evidence, and
  ranking contracts unless a code-owned transition trace is explicitly added.

No production traffic is currently bound to a selected lane, so dual-reading
old and new model schemas is unnecessary.

## 11. Scope

### In scope

- remove model-owned state mutation acts;
- ground semantic references and mutable candidates;
- compute deterministic add/retain/replace/remove transitions;
- preserve prior constraints through validated follow-ups;
- replace raw-act gate checks with final-state transition checks;
- close recommendation, comparison, suitability, and simple follow-up model
  gates;
- rerun local and official backend gates.

### Out of scope

- new product data or image crawling;
- changes to SelectionFact weights or evidence permissions;
- a new recommendation engine;
- frontend rendering;
- push, deploy, or production traffic selection before all gates pass;
- a second model reviewer;
- a global phrase vocabulary.

## 12. Acceptance and Stop Boundary

The backend phase is complete when:

1. Model-facing schemas no longer contain constraint mutation acts.
2. Every executable state change is derived by code from current state,
   current-turn values, and source-bound proof.
3. Unmentioned and restated constraints remain unchanged.
4. Serious safety requirements cannot be weakened.
5. Recommendation, comparison, suitability, current-item, ordinal, budget,
   skin, category, efficacy, inclusion, exclusion, and soft-facet behavior
   pass focused and full local tests.
6. Three official real-model broad gates select the same non-null lane with
   zero unsafe state or product-selection violations.
7. A closure report records the final schema versions, test counts, official
   gate artifacts, and remaining risks.

Execution stops after the backend handoff contract is green and before
frontend rendering. No push or deploy occurs in this phase.
