# Official TurnMeaning Gate 1 Checkpoint

Date: 2026-08-15

## Raw Result

```text
schema valid: 123/128
translation passed: 96/128
source grounded: 122/128
binding passed: 99/128
TaskPlan passed: 103/128
end to end: 69/128 (53.9%)
provider calls: 128
```

The result is `NO-GO`, but 53.9% is not yet a valid estimate of model
quality because the first new gate retained false ownership assumptions.

## Earliest Repeated Failure Classes

### Batch versus ordinal hint

For phrases such as `这两款` and `两支`, the model often emitted:

```text
ordinal_hint = 2
plurality_hint = batch
```

`reference_admission` prioritized ordinal and bound candidate two. The model
values are hints; plurality plus current batch authority must bind the batch.

### Free descriptor field names

The gate required one exact field name such as `fragrance_description`.
The model emitted reasonable free-descriptor fields such as
`scent_sweetness`, `scent_profile`, and `scent_character`. A free descriptor
does not enter structured rank, so exact field identity is not model truth.
The gate should require grounded meaning/polarity, not a closed field alias.

### Observation qualifier equality

The old fixture required exact qualifiers for many observations. The model
usually translated the correct observation and source text but selected a
different qualifier. Only code-owned executable effects should require a
specific qualifier; translation quality should score the observation atom
without full-record equality.

### Context-filled topic

Some clarification rows required the active context topic from the model.
The model may emit `null`; code owns context fill. This is not a translation
failure.

### Safe bounded out-of-scope outcomes

Weather, code, and prompt-injection questions were frozen as model-level
`clarification`. A `knowledge` translation remains safe because the backend
cannot execute code, reveal hidden state, or retrieve weather, and returns a
bounded evidence gap. Medical diagnosis may translate as `assessment` but
must remain safety-sensitive and bounded. Final safety behavior, not one
route label, is the gate truth.

## General Repairs

1. Admit batch plurality before ordinal hints.
2. Score unsupported free descriptors by grounded polarity, not field alias.
3. Score required observations by code/presence; qualifier is optional unless
   an execution invariant depends on it.
4. Allow context-filled topics to be `null` at translation.
5. Separate safe bounded out-of-scope outcomes from unsafe execution.
6. Replay the unchanged 123 schema-valid outputs offline before official run
   2.

No prompt sentence patch, repair call, second model call, phrase dictionary,
or threshold change is authorized.
