# Official TurnMeaning Gate 2 Checkpoint

Date: 2026-08-16

## Raw Result

```text
schema valid: 120/128
translation passed: 116/128
source grounded: 120/128
binding passed: 120/128
TaskPlan passed: 116/128
end to end: 115/128 (89.84%)
provider calls: 128
invented source atoms: 0
ambiguous source atoms: 1
all state/safety/product/source hard counts: 0
```

The run is `NO-GO`: it is one case below the 90% threshold. The eight
schema-invalid outputs remain single-call fail-closed results and are not
repaired or retried.

## Repeated Earliest Failure Classes

Four valid model outputs expose code/truth ownership gaps that also appeared
in the first official run:

1. A non-ordinal product reference with exactly one visible candidate was
   rejected when no separate focus marker existed. The candidate is unique;
   code can bind it as the one-item current batch without trusting the
   model's ordinal hint.
2. `assessment` with a bound product and a post-use observation was left as
   a non-executable goal. The translation is valid; code should compile this
   shape to product suitability.
3. `clarification` with grounded question meaning and a bound candidate was
   left as a non-executable goal. The translation is valid; code should
   compile this bounded question to product knowledge.
4. `image_similarity` with a bound image was left as a non-executable goal
   for an image follow-up. The image binding is authoritative; code should
   compile the supported image continuation to follow-up.

`rec-007-paraphrase-serum` remains a real translation miss: `水后乳前` was
translated as broad skincare rather than serum. It stays failed and is not
converted into a code phrase rule.

## General Repair

- Bind a non-ordinal product mention to `current_batch` only when the batch
  contains exactly one candidate.
- Normalize executable goals from grounded structure after reference
  admission:
  - assessment + product reference + observation -> suitability;
  - clarification + product reference + question meaning -> knowledge;
  - image similarity + image reference -> follow-up.
- Record these operation labels as allowed equivalents in the audited truth
  by semantic family and reference shape.

No prompt sentence patch, phrase dictionary, second call, repair call,
reviewer, threshold change, or retry is authorized.
