# TurnMeaning Truth Architecture Checkpoint

Date: 2026-08-15

## Decision

The previous 128-case fixture is retained as source history, not reused as
the scoring contract. Every row was re-published with four owners:

```text
translation requirements
allowed equivalents and don't-care fields
deterministic binding truth
final TaskPlan, transition, and state truth
```

The new gate never compares a complete model JSON object.

## Corrected False Truth

- `assess-001-post-cleanse-tight`: model topic may be `skincare` or
  `cleanser`; code narrows the executable topic to cleanser from the
  post-cleanse event.
- `img-001-find-similar-first`: `第一张` and `第一张图` are equivalent when
  both bind `image:1`; character offsets are not model truth.
- `follow-009-budget-revision`: the model translates the budget and safety
  language; code owns `budget:replace`, `exclusion:酒精:retain`, and final
  state.
- `clar-015-revision-missing-target`: `followup` is a valid translation, but
  `另一个` has no unique object, so code must produce `clarify`.
- `follow-013-current-topic-cheaper`: a current topic and candidate batch do
  not establish one price baseline, so the bounded relative contract
  clarifies.

## Gate Rules

Hard failures:

```text
provider calls per case != 1
invented or non-unique raw source text
forbidden output accepted
unauthorized or unmentioned state change
hard safety override
wrong product selection
ranking/answer source mismatch
```

Quality admission:

```text
128 unique cases
end-to-end pass rate >= 90%
all hard counts = 0
```

The runner has no repair, reviewer, route, or detail call.

## Assets

```text
fixture review:
f2ca9513a80a2fa6c55fc34a4c1f3cb1986d0215425bd4a87f4da0d20301e19e

turn meaning gate:
bab9aea7aa9778da3edf002d587d9ae35c9487af805c80062d31e821b3fec3e1

frontend gate matrix:
c0db544a8c6788ae9bce46a056b728f88807d8eb090496dd39d2c753812a1414
```

No case ID, fixture sentence, or phrase-answer pair is present in the
production prompt.
