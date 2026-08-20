# Historical Boundary Audit v2

## Scope

This audit treats the existing real captures as the review corpus. It does
not create another review set and does not add wording-specific behavior.
Older runs are evidence of failure classes, not additive certification for
the current prompt version.

## Recurrent Findings

| Boundary | Evidence | Current status |
| --- | --- | --- |
| Ingredient exclusion -> Canonical entity -> product evidence | `shop-exclusion-withdrawal`, v42 | Repaired with `ingredient_exclusion`, shared entity normalization, and fail-closed fixture truth. |
| Image anchor -> budget revision -> new candidate ordinal | `image-budget-similarity`, v20 | Repaired; v22 captured all five turns with the image anchor preserved. |
| Symptom update for a bound image/product suitability conclusion | `image-sunscreen-suitability`, v21 | Repaired by the v22 suitability precedence rule and an end-to-end provider probe. |
| Unbound general-knowledge pivot during active consultation | `knowledge-consultation-switch-t3`, v19 and v22 | Still weak. v19 routed correctly but showed unstable continuity; v22 translated the same standalone concept question as `assessment`. |

## Non-Candidates For Another Repair

- Old fixed fixtures that had incorrect card expectations or overly narrow
  semantic allowlists are fixture-authoring evidence, not new product rules.
- Isolated provider enum failures were handled by closed schema-contract
  instructions, not parser tolerance.
- A rare phrasing does not justify a new rule if it does not expose a missing
  parent operation, binding authority, state transition, or data fact.

## One Bounded Repair

The remaining repair is a parent-operation priority, not a phrase rule:

```text
active consultation
+ standalone general definition/comparison question
+ no current symptom update
+ no bound product/image suitability request
-> knowledge + new_task
```

The model must not retain consultation merely because the question is about
skin. The code already routes a valid `knowledge` result to the general
knowledge processor and preserves prior consultation state for later return.

## Exit Rule

After a test-first prompt-contract update and one real end-to-end probe for
this boundary:

1. freeze the prompt and application code;
2. do not generate another review corpus;
3. run the independent blind exam exactly once;
4. treat blind failures as scored evidence, not a reason to add phrase rules.
