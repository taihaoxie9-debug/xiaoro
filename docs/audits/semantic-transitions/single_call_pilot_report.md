# Single-Call Semantic Translation Pilot Report

Date: 2026-08-15

Repository: `/Users/bytedance/Desktop/xiaoro-fresh`

Branch: `rebuild`

Production status: unchanged `NO-GO`

## Question

Does replacing the current route-then-detail model flow with one compact
universal translation call make the representative failures understandable
without product RAG or long conversation context?

## Experiment

Eight existing official-gate cases were selected:

```text
recommendation
comparison
suitability
image similarity
knowledge
assessment
constraint revision follow-up
missing-target clarification
```

Each case sent only:

```text
current message
code-derived binding authority
one universal output schema
```

No product facts, ranking facts, knowledge documents, conversation transcript,
answers, or hidden reasoning were sent. There was no repair call.

## Raw Result

```text
official model: deepseek-v4-pro
cases: 8
provider calls: 8
schema valid: 8/8
strict pilot accepted: 3/8
prompt tokens: 4,413
completion tokens: 1,138
total tokens: 5,551
```

Evidence:

```text
/private/tmp/xiaoro-single-call-semantic-pilot-20260815

results.jsonl SHA-256:
e76a23e66491f79700069e053439d0ab6f8ccb23af7bd9b29f02c9d43df00aee

summary.json SHA-256:
e17ee43c49547022bf3ed419261f5f492c7e685fbbe3e52957e2e28664c45cb6
```

The original summary recorded seven source-grounded rows. A TDD review found
that the pilot ordinal parser incorrectly treated the `一` inside `另一个`
and `两支` as ordinal syntax. The parser now requires `第X` or `图X`, and the
focused regression is green. Corrected offline evaluation has five fully
source-grounded rows. The strict accepted count remains 3/8, so this bug does
not change the main pilot result.

## Cost Comparison

For the same eight cases in official run 2:

```text
current two-stage flow:
stage calls: 16
prompt tokens: 13,412
completion tokens: 1,178
total tokens: 14,590

single-call pilot:
provider calls: 8
prompt tokens: 4,413
completion tokens: 1,138
total tokens: 5,551
```

The single-call prompt used about 38% of the two-stage total, a reduction of
about 62%. Completion volume was nearly unchanged; the saving came mainly
from not sending two separate instruction/context prompts.

## Case Review

| Case | Old full gate | Strict pilot | What the model actually returned | Diagnosis |
|---|---|---|---|---|
| sunscreen paraphrase recommendation | fail | pass | recommendation, sunscreen, `通勤`, `挡紫外线`, `不搓泥` | Model understood the request; old detail gate did not score the important preference fields. |
| compare two serums | fail | fail | comparison, serum, texture and efficacy, raw `两支` | Meaning is present. The model labeled `两支` as candidate ordinal instead of current batch. Reference kind is deterministic binding work. |
| sensitive-skin sunscreen suitability | fail | fail | suitability, sunscreen, `敏感肌`, safety false, raw `这个` | Meaning and safety boundary are correct. The model labeled `这个` as candidate ordinal instead of current item. Code already knows the focused item. |
| first-image similarity | fail | pass | image similarity with raw `第一张图` | Proves the old gold span `第一张` was unnecessarily narrow. Both resolve to image one. |
| fragrance-note knowledge | fail | pass | knowledge, fragrance, correct question meaning | Old run 2 failed only because its exact concern tuple differed. |
| post-cleanse assessment | fail | fail | assessment plus exact tightness/flaking observations and qualifiers | Only topic differs: model returned skincare, pilot expected cleanser. The original fixture expected skincare while the current prompt says cleanser. This is a contract contradiction. |
| budget revision follow-up | fail | fail | follow-up, sunscreen, `三百以内`, `不要含酒精` | All state-relevant meaning is present. It missed the `previous_constraint` label, which exact code already derives before the reducer. |
| missing-target revision | fail | fail | follow-up, raw `另一个`, no concrete ordinal | The semantic reading “switch to another” is reasonable, but it is not executable. Correct code must reject the unresolved binding and produce clarification. |

## What 3/8 Means

The first one-call contract did not meet its predeclared `5/8` minimum, so
simply merging route and detail is not sufficient.

It does not show that the model failed to understand five messages:

```text
direct contract pass: 3
meaning present but deterministic label disagreed: 4
non-executable semantic request requiring code clarification: 1
```

This manual classification is not substituted for the strict score. It
identifies the next responsibility defect.

## Responsibility Finding

The pilot schema still asked the model to do too much:

```text
choose authoritative reference kind
choose the canonical business topic
choose an executable goal before binding validation
```

Those are not all open-language translation:

- candidate/image/current-item/current-batch admission is code-owned context;
- an exact budget revision is code-owned parsing and state comparison;
- final clarification depends on whether a translated reference can bind;
- canonical topic can be narrowed by exact events such as post-cleanse
  observation after translation.

The model should return raw referring language and semantic observations. Code
should decide the binding kind and final executable route.

## Revised Direction

The next contract should be thinner:

```text
model once:
  operation hint
  topic hint
  raw reference phrases
  raw observations/preferences/budget/product mentions
  question meaning and safety-language interpretation

code:
  uniquely ground raw phrases
  parse ordinals and budgets
  bind current item, batch, image, topic, or prior constraint
  canonicalize executable topic
  decide clarification versus execution
  compute state transitions
  build TaskPlan
```

The gate should separately report:

```text
translation coverage
invented semantic atoms
binding admission
final TaskPlan
state-transition invariants
hard safety violations
provider call count
```

It should not collapse all six responsibilities into one byte-exact detail
score.

## Verdict

```text
Does the first single-call schema pass? No: 3/8.

Does the experiment support the one-call direction? Yes.

Why? It cut tokens by about 62%, produced valid structured output 8/8, and
contained the state-relevant meaning in seven cases. Most remaining failures
were authoritative labels that should move to deterministic code.

Is the architecture ready to replace production? No.
```

The next legitimate step is to design and test code-owned reference binding
and executable-route admission against these unchanged eight outputs before
another paid model run. No production prompt, gate threshold, or runtime path
was changed by this pilot.

## Verification

```text
10 passed
  tests/guide/tools/test_single_call_semantic_pilot.py

compileall pilot module:
passed

git diff --check:
passed
```

