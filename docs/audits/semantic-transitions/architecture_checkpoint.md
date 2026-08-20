# Semantic Transition Architecture Checkpoint

Date: 2026-08-15

## Decision

The integrated design now has one authority boundary:

```text
current-message meaning + exact source proof
    -> deterministic constraint reducer
    -> final TaskPlan
    -> persisted RecommendationQueryContext
```

The model translates current-message meaning. It does not output or own
`add`, `retain`, `replace`, or `remove`.

## Ownership Audit

### Does the model output a stored-state operation?

No. `SemanticIntentProposal` is `guide-semantic-intent-v7` and has no
`acts` field or `SemanticAct*` type. Detail contracts likewise contain only
the meaning fields allowed for their route. The intent prompts contain no
`add_preference`, `revise_constraint`, or `withdraw_constraint` instruction.

The remaining `revise_constraint` and `withdraw_constraint` strings are enum
values for the deterministic exact parser. They are code-owned proof types,
not model output.

### Can an unmentioned constraint change?

No. `reduce_constraint_state` begins from the stored
`RecommendationQueryContext` only for a follow-up or an exact revision. It
changes a slot only when the current turn binds that slot. Unmentioned slots
remain in the state. A fresh recommendation starts from an empty state and
cannot inherit stale constraints.

The frozen metamorphic fixture proves:

- budget replacement retains a repeated alcohol exclusion;
- budget replacement preserves an unmentioned alcohol exclusion;
- repeating an exclusion is idempotent;
- a fresh skincare request does not inherit sunscreen budget or exclusions.

Fixture:
`tests/fixtures/guide/intent/transition_metamorphic_v1.jsonl`

SHA-256:
`ba25e6db32d5805c6660ecbcfbb7220179f2ec5d03913028747207e195ec2d1b`

### Can semantic output weaken exact safety?

No. A stored safety-sensitive state is combined monotonically with the
current state. A validated semantic facet cannot downgrade it. Multi-valued
hard removals require an exact proof bound to the named value. A target-kind
only removal fails closed.

### Are preferences represented twice?

No at the state boundary. Exact and validated-semantic candidates may arrive
through different understanding lanes, but the reducer canonicalizes them to
one slot identity:

```text
category
budget
skin
efficacy
exclusion:<casefold value>
inclusion:<casefold value>
facet:<field_key>:<casefold value>
```

Equal identities are idempotent and produce at most one stored constraint.
This identity is also the deduplication boundary for transition traces.

### Do closed operations share one reducer?

Yes. The text runtime calls `plan_code_owned_transitions`, which calls
`reduce_constraint_state`. The legacy budget and skin fast-path adapters also
call that same reducer. They preserve their public response shape but have no
independent mutation rules.

### Did a second intent or recommendation path appear?

No. `transition_planning.py` is a compiler between the existing understanding
result and the existing `TaskPlan`; it is not another model call, retriever, or
recommendation engine. The runtime and the model gate both invoke this shared
compiler, preventing an evaluator-only shadow reducer.

### Which exact parsers remain field-specific?

The exact parser retains closed grammars for:

- category revision;
- budget revision;
- skin revision;
- efficacy revision;
- named ingredient inclusion/exclusion withdrawal;
- named facet withdrawal.

These parsers only issue typed proof with an exact source span. Field-specific
parsing is required because replacement/removal is a state transaction, while
open-ended product preference meaning remains the model's translation job.
The exact parsers do not form a global product or preference keyword
dictionary.

## Runtime and Contract Evidence

Current versions:

```text
guide-semantic-intent-v7
guide-detail-recommendation-v5
guide-detail-assessment-v3
guide-detail-comparison-v3
guide-detail-followup-v6
guide-detail-knowledge-v3
guide-detail-image-v1
guide-semantic-intent-prompt-v14
guide-semantic-detail-prompt-v10
guide-semantic-route-prompt-v7
```

Focused verification:

```text
101 passed in 3.59s
  route binding, route prompt, two-stage adapters, cache, official runner

4322 passed in 23.50s
  understanding, intent, query context, text recommendation flow

7389 passed in 418.62s
  Guide full

237 passed in 70.06s
  Guide runtime

25 passed in 2.41s
  architecture and import boundaries

compileall app/tools: passed
git diff --check: passed
staged index: empty
```

Guide full emitted five existing Pydantic/deprecation warnings and no test
failures. Frontend rendering remains outside this Goal;
`app/static/chat.html` still has the frozen SHA-256
`70ec29f8298fb912e578b718a214619d590214ddcd556ad0ad7ab1613efdbc95`.

## Track A Changed Paths

Production:

```text
app/guide/adapters/llm/contracts.py
app/guide/adapters/llm/intent_detail_prompt.py
app/guide/adapters/llm/intent_prompt.py
app/guide/adapters/llm/intent_route_prompt.py
app/guide/application/query_context.py
app/guide/application/text_recommendation_flow.py
app/guide/intent/budget_revision_planning.py
app/guide/intent/constraint_transitions.py
app/guide/intent/contracts.py
app/guide/intent/signal_merger.py
app/guide/intent/skin_revision_planning.py
app/guide/intent/task_planning.py
app/guide/intent/transition_planning.py
app/guide/understanding/colloquial_budget.py
app/guide/understanding/contracts.py
app/guide/understanding/exact_parsing.py
app/guide/understanding/followup_parsing.py
app/guide/understanding/parallel_understanding.py
app/guide/understanding/semantic_contracts.py
app/guide/understanding/semantic_detail_contracts.py
app/guide/understanding/text_understanding.py
app/guide/understanding/two_stage_semantic.py
```

Gates and frozen data:

```text
tools/guide_gates/guide_pipeline_evaluator.py
tools/guide_gates/intent_model_ab.py
tools/guide_gates/real_ab_evidence.py
tools/guide_gates/run_real_intent_ab.py
tools/guide_gates/run_real_two_stage_intent_ab.py
tools/guide_gates/two_stage_intent_gate.py
tests/fixtures/guide/intent/semantic_intent_ab_v2.jsonl
tests/fixtures/guide/intent/transition_metamorphic_v1.jsonl
tests/fixtures/guide/intent/two_stage_smoke_v1.jsonl
tests/fixtures/guide/intent/two_stage_smoke_v1_manifest.json
```

Tests changed under:

```text
tests/guide/adapters/
tests/guide/application/
tests/guide/intent/
tests/guide/tools/
tests/guide/understanding/
```

## Remaining Checkpoint Risk

This checkpoint proves local ownership and deterministic state behavior. It
does not prove production readiness. Guide full, runtime, static boundaries,
and three sequential official model gates still must pass. Until then the
semantic lane remains `NO-GO`.

## Repeated-Failure Audit: Full Route Translation

The official full gate failed at the same earliest layer in four sequential
runs. The latest evidence is:

```text
two_stage_flash: 101 / 128 route matches (78.9%)
two_stage_pro:   104 / 128 route matches (81.3%)
```

The separate route-only replay found 27 Flash mismatches and 24 Pro
mismatches. Flash contained 19 goal errors and 8 topic errors. Pro contained
15 goal errors, 6 reproducible topic errors, and 3 calls whose route-only
replay differed from the recorded gate result.

### Earliest failing layer

Raw `SemanticRouteProposal` translation. Unauthorized state transitions are
already zero, so the reducer, TaskPlan compiler, and ranking path are not the
earliest defect.

### Contract that owns the behavior

`intent_route_prompt.py` owns the model-facing goal/topic taxonomy.
`SemanticRouteProposal` owns only strict output shape and cannot repair a
semantically wrong but schema-valid route.

### Why the previous fixes did not address the class

Route prompt versions v2 through v4 accumulated surface-form rules. In
particular, v4 says an explicit constraint revision is `followup` and that a
pronoun or ordinal is normally `followup`. Those rules conflict with the
frozen business outcomes:

```text
change a selection preference and keep shopping -> recommendation
correct a reported observation               -> assessment
change the subject of an explanation          -> knowledge
compare two image ordinals                     -> comparison
find a visually similar item from an image     -> image_similarity
```

The topic rule also says a general symptom assessment should use `skincare`
even when cleansing is mentioned. That conflicts with the narrower-object
contract for cleanser reactions, sunscreen reactions, and base-makeup
performance.

### Responsibility overload

The route prompt was using reference form and revision wording as if they were
business goals. This makes it partly decide state-operation semantics, which
belongs to exact proof plus the deterministic reducer, and turns `followup`
into a catch-all. It also mixed symptom interpretation with topic
generalization.

### General fix selected

Use one outcome-based route taxonomy:

```text
goal  = the most specific operation requested in the current message
topic = the narrowest explicit or source-bound business object
```

References, revisions, negations, and injections are orthogonal input
properties. They cannot override a more specific requested operation.
`followup` is reserved for an elliptical continuation or request for more
detail that has no more specific operation. `skincare` is used only when no
narrower category owns the current question. The fix must remain a compact
category policy and must not add case IDs, frozen messages, or phrase-answer
pairs to the prompt.

### Alternatives rejected

- Lowering the 95% route gate would hide translation defects.
- Overriding raw routes in gate-only code would make the gate test a shadow
  classifier instead of production semantics.
- Adding one prompt example for each failed sentence would recreate an
  unbounded phrase dictionary.
- Moving open-language route classification into deterministic code would
  violate the translator boundary and duplicate the model with brittle
  keyword rules.

## Second Repeated-Failure Audit: Binding Admission

The outcome-based v5 and v6 route policies corrected the original broad
taxonomy failures but both stopped at the same result:

```text
v5 Flash: 118 / 128 route, 120 / 128 goal, 126 / 128 topic
v5 Pro:   118 / 128 route, 121 / 128 goal, 124 / 128 topic

v6 Flash: 118 / 128 route, 121 / 128 goal, 125 / 128 topic
v6 Pro:   118 / 128 route, 122 / 128 goal, 124 / 128 topic
```

Both runs had zero provider or schema failures. The wording change moved
errors between categories but did not improve the route total.

### Earliest failing layer

Raw route translation still fails first. In v6 the largest repeatable Flash
cluster is an unresolved pronoun, candidate ordinal, or image reference being
classified as executable `followup`.

### Contract that owns the behavior

The route adapter currently sends the complete `SemanticContext` and asks the
model to infer binding availability from:

```text
visible_candidate_count
focused_candidate_ordinal
image_count
focused_image_ordinal
active_topic
active_constraint_kinds
```

The fields are typed, but their binding semantics are only prose. The model
must reconstruct deterministic reference-admission rules while also
classifying the open-language request.

### Why v5 and v6 did not address the class

Both versions improved the goal taxonomy but continued to use the phrase
`source-bound` without supplying a code-derived list of bindings. This left
the model free to treat a textual pronoun or ordinal as resolved even when
typed context proved that no matching object existed.

### Responsibility overload

Open-language route classification belongs to the model. Deciding whether
ordinal 2 exists, whether an unnumbered singular product has a focused item,
or whether an unnumbered image has a focused image is deterministic context
admission. The route model currently owns both.

### General fix selected

Code will derive an immutable route binding packet from `SemanticContext`:

```text
admitted candidate ordinals
focused current-item ordinal or null
current-batch availability
admitted image ordinals
focused current-image ordinal or null
current topic or null
admitted previous-constraint kinds
pending clarification or null
```

The route prompt receives this packet instead of raw bookkeeping fields and
treats it as authority. A textual reference cannot create a binding absent
from the packet. The model still decides the open semantic operation and
topic; code does not classify phrases, goals, or categories.

### Alternatives rejected

- More reference examples in the prompt would be phrase-level patching.
- Letting the gate repair raw route output would hide model translation
  quality and create a gate-only classifier.
- A second model call to resolve references violates the one-call authority
  design and adds cost without determinism.
- A keyword parser for pronouns or shopping language would recreate the
  prohibited global phrase dictionary.

### Binding-packet verification result

The v7 implementation passed its strict local binding and adapter contracts,
but the real route-only result did not improve:

```text
v7 Flash: 117 / 128 route, 120 / 128 goal, 124 / 128 topic
          1 invalid output after repair
v7 Pro:   118 / 128 route, 122 / 128 goal, 123 / 128 topic
          0 provider/schema failures
```

The binding packet is retained because it removes deterministic object
availability from model responsibility and prevents raw conversation
bookkeeping from entering the route prompt. It is not claimed as a model
quality fix.

No fourth prompt-tuning pass is permitted in this checkpoint. Three general
policies converged on the same roughly 92% ceiling while changing which
sentences failed. Further sentence-level tuning would violate the
no-phrase-patch rule. The code-owned transition and safety architecture is
locally closed, but official semantic quality remains `NO-GO`. Final official
gates will still use the frozen 95% route and 90% detail thresholds; those
thresholds are not lowered or redefined.
