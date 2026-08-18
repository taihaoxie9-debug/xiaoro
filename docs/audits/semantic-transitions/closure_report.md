# Semantic Translation and Code-Owned Transition Closure

Date: 2026-08-15

Repository: `/Users/bytedance/Desktop/xiaoro-fresh`

Branch: `rebuild`

Semantic release status: `NO-GO`

## Scope

This phase removed stored-state authority from the model without adding a
reviewer call, a phrase dictionary, or a gate-only classifier.

The target boundary is now:

```text
model:
  translate current message
  return typed current-turn meaning
  preserve source text and offsets

code:
  admit bindings
  validate exact revision proof
  compare old and new state
  choose add/retain/replace/remove
  apply safety rules
  construct final TaskPlan
```

## Final Contracts

`SemanticIntentProposal` is schema `guide-semantic-intent-v7` and has no
mutation acts. Every executable reference carries:

```text
kind
ordinal when applicable
raw_text
start
end
```

Offsets must rebind uniquely to the current user message. Text alone cannot
create candidate, image, current-item, topic, or previous-constraint
authority.

`SemanticRouteBindingAuthority` is derived by code from conversation context
and exposes only:

```text
admitted candidate ordinals
focused current item
current-batch availability
admitted image ordinals
focused current image
current topic
admitted previous-constraint kinds
pending clarification
```

The route model receives this read-only authority packet instead of raw
conversation bookkeeping.

## Single State Reducer

All executable state transitions converge on:

```python
reduce_constraint_state(
    previous,
    current_constraints,
    revision_confirmations,
    goal,
    safety_sensitive,
    transition_requested,
)
```

`plan_code_owned_transitions` is the shared runtime/gate compiler around that
reducer.

The enforced invariants are:

1. Unmentioned old constraints remain unchanged.
2. Equal old/new values do not produce a modification.
3. Single-value replacement requires exact source-bound revision proof.
4. Multi-value removal names and binds the removed value.
5. Fresh recommendation does not inherit old query constraints.
6. Category replacement clears category-scoped slots.
7. Semantic output cannot lower safety sensitivity.
8. Exact and semantic equivalents deduplicate before transition planning.
9. Invalid model output cannot invoke TaskPlan.
10. There is no second model call that decides or reviews stored-state change.

Budget revision, skin revision, text runtime, and official evaluation use this
same authority. No parallel mutation engine remains.

## Repeated-Failure Architecture Audit

Three general route policies were tried before final closure:

```text
v5 Flash: 118/128
v5 Pro:   118/128

v6 Flash: 118/128
v6 Pro:   118/128

v7 Flash: 117/128 plus 1 invalid output
v7 Pro:   118/128
```

The first audit removed revision/reference form from business-goal ownership.
The second audit moved deterministic binding admission from the model into
`SemanticRouteBindingAuthority`.

Both are retained because they correct responsibility boundaries. They did
not break the roughly 92% route-quality ceiling.

A fourth prompt-tuning pass was intentionally rejected. The failed sentences
moved between versions while aggregate quality remained flat. Adding more
surface-form examples would create the prohibited phrase-patch architecture
without addressing the model's translation stability.

## Local Verification

The final implementation passed:

```text
focused vertical suites:
4719 passed

Guide full:
7492 passed

Guide runtime:
275 passed

application/state/SSE/public contracts:
1137 passed

architecture/import boundaries:
25 passed

compileall app/tools:
passed

git diff --check:
passed

staged index:
empty
```

The 35-row backend handoff matrix also proves budget/skin replacement,
constraint retention, fresh-request noninheritance, current-item/ordinal
binding, profile consumption, and safety gating through real composed paths:

```text
36 passed
```

## Three Official Runs

Unchanged production thresholds:

```text
route >= 95%
detail >= 90%
zero unsafe TaskPlan mismatch
zero unauthorized transition
zero hard-constraint override
zero wrong-product selection
same non-null selected lane three times
```

### Run 1

```text
selected_lane: null

two_stage_flash smoke:
route 29/32 = 90.63%
detail 12/26 = 46.15%
schema-invalid rows: 1
p95: 3602 ms

two_stage_pro full:
route 118/128 = 92.19%
detail 55/112 = 49.11%
unsafe TaskPlan mismatch: 1
unauthorized transitions: 0
hard overrides: 0
wrong products: 0
p95: 5821 ms

summary SHA-256:
34ee40db32ecc71a549fd14ebc1bc2a6f5f2a5e4c4db2881d4dfb008c2a11540

stable evidence SHA-256:
b9461ef3b40fdff033b36b405824ce19fdf148beea3111478cb207f9f5d5a08a
```

### Run 2

```text
selected_lane: null

two_stage_flash smoke:
route 29/32 = 90.63%
detail 11/26 = 42.31%
schema-invalid rows: 1
p95: 4107 ms

two_stage_pro full:
route 119/128 = 92.97%
detail 55/112 = 49.11%
unsafe TaskPlan mismatch: 1
unauthorized transitions: 0
hard overrides: 0
wrong products: 0
p95: 6359 ms

summary SHA-256:
bd45111bd3b0395858354cf28372d62f404a9c928837f67810cce768828ed8d4

stable evidence SHA-256:
a3255e3a19aa7a170630dbfd99d119d0e86f5b711a4ad8e285e7ab29e2bdd6bd
```

### Run 3

```text
selected_lane: null

two_stage_flash smoke:
route 29/32 = 90.63%
detail 13/26 = 50.00%
schema-invalid rows: 1
p95: 4786 ms

two_stage_pro smoke:
route 29/32 = 90.63%
detail 14/26 = 53.85%
unsafe TaskPlan mismatch: 1
unauthorized transitions: 0
hard overrides: 0
wrong products: 0
p95: 7577 ms

full phase:
not run because smoke hard gate failed

summary SHA-256:
1af51a5d7fd5896ff25a799ac9155dda96e2b354e3ed465b6e6e4f6bf4b2ae30

stable evidence SHA-256:
fc27f5c096511133c5bf6f3dd193e6364ff017fb2aea9ecdc7634ee93166c5da
```

All three runs had:

```text
invalid-output TaskPlan invocation: 0
unauthorized constraint transition: 0
hard constraint override: 0
wrong product selection: 0
```

The code-owned boundary therefore prevents several dangerous outcomes, but it
does not convert a mistranslated message into a correct task. Fail-closed
clarification is safer than wrong mutation, yet the frequency is too high for
the agreed production experience.

## Final Diagnosis

### Earliest remaining failure

Official model route/detail translation.

The reducer and state store are not the earliest failing layer:

- unauthorized transition is zero in all three runs;
- hard-condition override is zero;
- wrong-product selection is zero;
- invalid output never invokes TaskPlan.

### Why no further patch was applied

The model has already been relieved of deterministic binding and state
authority. Three category-level prompt designs converged at the same route
ceiling, and final detail accuracy is much farther below threshold. Another
sentence-level prompt pass would tune the fixture rather than repair the
architecture.

### Legitimate next design choices

The next phase must treat translation quality as a model/capability decision,
not a state-machine bug. Valid options include:

- evaluate a materially stronger official model against the same frozen gate;
- train or distill a route/detail translator on the frozen typed contract;
- simplify or repartition the semantic output contract only if the business
  contract can remain equally expressive;
- add provider-supported constrained structured decoding if it preserves one
  semantic pass and does not hide semantic mismatches.

Rejected options remain:

- lowering 95%/90%;
- adding frozen-message or keyword patches;
- repairing raw routes only inside the gate;
- adding a second reviewer model;
- returning state authority to the model.

## Handoff Verdict

```text
state ownership architecture: CLOSED
local backend behavior: GREEN
official semantic quality: RED
frontend implementation: STOP
production release: NO-GO
```

The next approved action is a design review of model/contract strategy. This
closure does not authorize frontend work, commit, push, deploy, or traffic
change.

