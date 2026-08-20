# Single-Call TurnMeaning Closure Report

Date: 2026-08-16

Repository: `/Users/bytedance/Desktop/xiaoro-fresh`

Branch: `rebuild`

Status: `FRONTEND-GO`

## Closed Architecture

The production semantic path is:

```text
one TurnMeaning provider request
  -> source-grounded code binding
  -> code-owned executable goal normalization
  -> code-owned state diff and TaskPlan
  -> deterministic retrieval, ranking, and presentation
```

The model does not own:

```text
character offsets
product, candidate, or image IDs
final reference binding
state add/retain/replace/remove operations
TaskPlan
product facts
ranking
answer text
```

Production defaults to `SiliconFlowTurnMeaningAdapter` plus
`SingleCallUnderstanding`. There is no route/detail pair, semantic cache,
repair request, reviewer request, or second state decision call.

Provider failure and schema-invalid output use the exact-only fail-closed
path. Closed exact controls may skip the provider; a semantic turn issues at
most one request.

## Binding and Execution

Reference hints are not binding authority. Code validates raw text against
the current message and resolves only objects authorized by the current
context:

- explicit candidate and image ordinals must exist;
- a non-ordinal pronoun uses the focused object;
- a one-item visible batch may bind that unique candidate;
- a multi-item batch cannot be guessed from a non-ordinal singular hint;
- equivalent exact and semantic references deduplicate by object identity;
- previous constraints require exact revision proof before mutation.

Grounded structure may normalize a model operation hint without another
model call:

```text
assessment + product + observation -> suitability
assessment + product               -> product knowledge
clarification + product + question -> product knowledge
image similarity + image           -> follow-up
follow-up + new selection fields    -> recommendation
```

These are structural rules. No fixture sentence, Chinese phrase answer, or
user-language dictionary was added to production code.

## State and Safety

`StoredState + current TurnMeaning` is reduced once by code. The reducer
enforces:

- unmentioned state is retained;
- equal values are retained;
- replacement and removal require current-turn proof;
- fresh recommendation does not inherit stale category-scoped state;
- semantic output cannot weaken a hard safety constraint;
- ordinary open descriptors cannot become hard filters;
- missing evidence remains `unknown`.

All three official runs have zero:

```text
unmentioned state changes
unauthorized state transitions
hard safety overrides
wrong product selections
ranking/answer source mismatches
invented source atoms
```

## Reaudited Gate

The 128 rows are scored by separate owners:

```text
translation requirements and allowed equivalents
source grounding
code binding
TaskPlan and state result
hard safety/product/source invariants
```

Complete model JSON equality and model-provided character offsets are not
truth.

Current assets:

```text
fixture review SHA-256:
f2ca9513a80a2fa6c55fc34a4c1f3cb1986d0215425bd4a87f4da0d20301e19e

turn meaning gate SHA-256:
bab9aea7aa9778da3edf002d587d9ae35c9487af805c80062d31e821b3fec3e1
```

## Official Runs

Three official `deepseek-v4-pro` runs issued exactly 128 provider requests
each. Invalid output was never retried or repaired and counts as an
end-to-end failure.

| Run | Schema valid | Translation | Binding | TaskPlan | End to end | Invalid | p95 | Tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 123/128 | 122/128 | 123/128 | 123/128 | 122/128 (95.31%) | 5 | 3247 ms | 151740 |
| 2 | 120/128 | 119/128 | 120/128 | 120/128 | 119/128 (92.97%) | 8 | 3220 ms | 147864 |
| 3 | 122/128 | 121/128 | 122/128 | 122/128 | 121/128 (94.53%) | 6 | 3249 ms | 150311 |

Every schema-valid run has the same one remaining translation miss:

```text
rec-007-paraphrase-serum
```

`水后乳前` was translated as broad skincare rather than serum. It remains a
real failed case. No code phrase rule or prompt sentence patch was added for
it.

Raw official evidence:

| Run | results.jsonl SHA-256 | Actual summary.json SHA-256 |
|---|---|---|
| 1 | `2794e446a123a059acfe9cbbf65c5b0c56983a393008f1df8b395c0a435132ed` | `afeaba3ba97c9d33ff5b95ad9a6266490950225434598d85c2a5e4b296588ce8` |
| 2 | `2c560130abf5abf1388d99581c793360d0de133fb816499428faf0f8bf5c57bd` | `cd26dab9b835869d15cb42ed465a8c9bc0c2dd9e2aa7aadb5d9dd13c372f4a12` |
| 3 | `5b4f79afd31e96ea46d50f2e62d430c373713fefe0b4ca41e848af0ad7f8fd88` | `119050f82f827fc5daefac6d16a2afbb6923bfa7974c215c78142b00b58c1c3a` |

The original runner wrote the summary digest before appending the file's
newline. Its recorded summary digest therefore did not match the actual
file. The runner now hashes the exact written bytes.

The original runner also required 128 schema-valid evaluations when setting
its final boolean, although the locked admission contract counts invalid
output as failed cases within the 90% denominator. This made Gate 3 report
`passed=false` despite 121/128 end-to-end success. A RED test reproduced the
bug; the final runner now applies:

```text
128 total cases
end-to-end success >= 90%
one provider request per case
all hard counts = 0
```

No official request was rerun. The immutable model outputs were replayed
through the final fixture and evaluator:

```text
official replay SHA-256:
d0526be105f690a23bfac63b9cfe198452a55533a899c1ff544ac23757e0d9aa
```

## Final Local Gates

```text
focused semantic/concept/runtime suites:
4734 passed

Guide full:
7619 passed, 5 warnings

runtime/application/state/presentation/public contracts:
1425 passed

backend and frontend handoff matrices:
45 passed

architecture and import boundaries:
25 passed

compileall app/tools:
passed

git diff --check:
passed

staged index:
empty
```

The five warnings are pre-existing Pydantic protected-namespace and legacy
script invalid-escape warnings.

## Verdict

The three official end-to-end rates are all at least 90%, every semantic turn
uses one provider request, and every hard state, safety, product, and source
count is zero.

```text
FRONTEND-GO
```
