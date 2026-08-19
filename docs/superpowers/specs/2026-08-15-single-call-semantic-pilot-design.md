# Single-Call Semantic Translation Pilot Design

Date: 2026-08-15

## Goal

Run a bounded eight-case experiment that distinguishes model-understanding
failures from failures caused by the current two-stage contract and
byte-exact gate. The pilot must not modify production routing, state,
retrieval, ranking, or frontend code.

## Hypothesis

The official model can translate the representative messages in one call when
it receives one stable universal schema. A deterministic evaluator should
accept source-grounded equivalent spans and score required business meaning,
while continuing to reject invented text, missing required meaning, unsafe
state effects, and extra model calls.

## Cases

The pilot freezes eight existing cases:

```text
rec-006-paraphrase-sunscreen
cmp-002-two-serums
suit-001-sensitive-sunscreen
img-001-find-similar-first
know-006-fragrance-notes
assess-001-post-cleanse-tight
follow-009-budget-revision
clar-015-revision-missing-target
```

They cover open recommendation, comparison, suitability, image reference,
knowledge, assessment, state revision, and clarification.

## One-Call Contract

The model returns one strict object:

```text
goal
topic
references[]       kind + raw_text, no offsets
observations[]     code + present + qualifier + raw_text
preferences[]      field + raw_text + strength
budget_mentions[]  raw_text only
product_mentions[] raw_text only
question_meaning
safety_sensitive
```

The model does not emit:

```text
start/end offsets
product or candidate IDs
state operations
final constraints
TaskPlan
scores, winners, answers, or catalog facts
```

The request contains only the current message and code-derived binding
authority. It does not contain product RAG, catalog facts, conversation prose,
or answer context.

## Deterministic Admission

Code performs:

- unique exact-substring grounding for every `raw_text`;
- ordinal parsing from grounded reference text;
- admission against candidate/image/current-item/current-topic authority;
- exact budget parsing;
- required semantic-atom comparison;
- forbidden-field rejection.

Equivalent source spans are accepted when they resolve to the same object.
For example, both `第一张` and `第一张图` resolve to image ordinal one.

## Scoring

Each case has:

- one required goal;
- one allowed topic set;
- required resolved references;
- required observations;
- required preference fields;
- required parsed budget values;
- optional fields that are explicitly `don't care`.

The evaluator does not require the complete model JSON to equal one gold JSON.
It does require all case-owned business facts and rejects ungrounded text.

The experiment reports:

```text
schema-valid cases
source-grounded cases
goal/topic cases
required-semantic cases
fully accepted cases
provider call count
prompt/completion tokens
```

## Success Interpretation

This pilot is directional, not a production gate.

- `7/8` or `8/8` accepted with exactly eight provider calls supports replacing
  the two-stage contract with a one-call translator.
- `5/8` or `6/8` requires mismatch review before an architecture decision.
- below `5/8` contradicts the hypothesis for this schema.

No production threshold is lowered. Existing official `NO-GO` remains in
force regardless of pilot outcome.

## Isolation

Created pilot code and tests live under `tools/guide_gates` and
`tests/guide/tools`. Runtime evidence is written only below `/private/tmp`.
The API key is read through the existing private-key precheck and is never
written to evidence.

