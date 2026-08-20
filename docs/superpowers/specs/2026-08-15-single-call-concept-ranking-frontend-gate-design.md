# Single-Call Concept Ranking and Frontend Gate Design

Date: 2026-08-15

Repository: `/Users/bytedance/Desktop/xiaoro-fresh`

Branch: `rebuild`

## Goal

Close the final backend gap before frontend work:

```text
infinite user language
  -> one model translation
  -> deterministic binding and executable admission
  -> common concept projection
  -> evidence-bounded ranking/comparison
  -> typed backend events
```

The phase ends with either:

```text
FRONTEND-GO
```

or:

```text
NO-GO plus the earliest unresolved architecture layer
```

It does not modify frontend rendering.

## Current Evidence

The data and evidence foundation is already closed:

```text
products with SelectionFacts: 100
SelectionFacts: 2,322
soft-rank SelectionFacts: 1,775
strength 1: 1,312
strength 2: 463
non-ranking: 547
unresolved machine-style concepts: 0
```

Duplicate facts share one identity and one score slot. Repeated images and
repeated sources do not accumulate score; the strongest admissible evidence
wins.

The previous eight-case pilot proved:

```text
one-call schema-valid output: 8/8
strict first-pilot acceptance: 3/8
meaning present but deterministic label disagreed: 4/8
non-executable request requiring code clarification: 1/8
token reduction versus two-stage: about 62%
```

The pilot therefore supports one-call translation but rejects the first
contract as still too authoritative about reference kinds, canonical topic,
and executable route.

## Product Scope

This is not a full long-tail ontology project.

The current soft-rank inventory shows high-value coverage in:

```text
skincare:
  efficacy, texture, skin_concern, suitable_skin

suncare:
  efficacy, texture, film_speed, suitable_skin,
  water_resistance, finish, usage_context

base_makeup:
  longevity, finish, texture, efficacy, suitable_skin, coverage

cleanser:
  cleansing_power, rinse_behavior, efficacy, texture, suitable_skin

color_makeup:
  finish, color_family, color_payoff, texture, makeup_effect
```

Fragrance coverage is sparse and product-specific. Fragrance long-tail
language remains ProductEvidence retrieval/answer material unless the audit
finds a repeated, stable, decision-relevant concept.

Ingredients remain exact or safety evidence, not an open semantic parent
concept system.

## Responsibility Boundary

### Model: one translator

The model receives:

```text
current message
compact code-derived binding authority
compact reviewed parent-concept catalog
one universal schema
```

It returns one `TurnMeaning`:

```text
operation_hint
topic_hint
raw reference mentions
raw product mentions
budget candidates
observation candidates
preference candidates
relative-comparison candidates
question_meaning
safety_language
```

It does not return:

```text
character offsets
product/candidate/image IDs
authoritative reference kinds
stored-state operations
final constraints
TaskPlan
scores, winners, catalog facts, or answers
```

There is exactly one provider request. There is no route call, detail call,
format-repair call, or reviewer call.

### Code: admission and execution

Code performs:

```text
unique source grounding
binding against current candidates/images/topic/constraints
number and ordinal validation
final executable goal selection
category/profile applicability
hard safety policy
old/new state diff
TaskPlan construction
```

The exact parser is a deterministic validator and proof source. It is not a
second language interpreter and cannot reject an ordinary semantic
translation merely because it lacks a matching phrase rule.

### Retrieval: evidence only

The phase does not build a vector store or a long-tail synonym dictionary.

```text
reviewed common concept -> structured soft rank
free descriptor -> existing ProductEvidence retrieval and answer
no evidence -> unknown/evidence gap
```

Any future vector index may generate candidates only. It may never directly
decide rank, safety, polarity, or a factual answer.

## TurnMeaning Contract

### Source-grounded mentions

The model returns exact raw substrings, without offsets. Code finds all exact
occurrences:

```text
one occurrence -> source grounded
zero occurrences -> rejected
multiple occurrences without a unique context binding -> clarification
```

### Reference mentions

A reference mention contains:

```text
raw_text
object_family_hint: product|image|topic|constraint|unknown
ordinal_hint: 1..4|null
plurality_hint: single|batch|unknown
```

These are translation hints, not admitted bindings.

Code resolves:

```text
explicit candidate ordinal
explicit image ordinal
focused current product
focused current image
current candidate batch
current topic
previous constraint
```

If two admitted objects remain possible, code clarifies. The absence of an
exact-parser phrase match alone is not ambiguity.

### Preference mentions

A preference contains:

```text
field_key
concept_id|null
raw_text
polarity: prefer|avoid
strength: ordinary|safety|unknown
```

`concept_id` comes only from the reviewed compact catalog. Unsupported
long-tail meaning uses `concept_id = null` and remains a free descriptor.

### Relative mentions

A relative mention contains:

```text
field_key
concept_id|null
direction: higher|lower
baseline_reference
raw_text
```

Code admits the relation only when:

- the baseline resolves;
- the field applies to the current category profile;
- the data supports a comparable relation.

Numeric or ordered evidence may support `higher/lower`. Binary or
positive-only evidence supports only:

```text
better matched to the request
or
better supported by evidence
```

It cannot support a stronger real-world effect claim.

## Parent Concept Asset

### Purpose

Parent concepts bridge infinite user language to repeated, stable product
decision dimensions:

```text
user "镇定泛红"
  -> efficacy.soothing

facts "舒缓泛红", "舒缓皮肤不适", "维稳"
  -> efficacy.soothing
```

Code matches concept identity, not surface text.

### Not a synonym dictionary

The asset maps reviewed SelectionFact identities to parent concepts. It does
not enumerate user phrases.

Each row contains:

```text
profile
field_key
source normalized value
concept_id|null
stance: supports|opposes|not_comparable
comparability: binary|ordered|numeric|none
rationale
review decision
```

The source SelectionFact remains unchanged and keeps its exact value, evidence
strength, source references, safety role, and capabilities.

### Admission criteria

A parent concept is published only when it is:

- repeated across products or an established high-frequency buying dimension;
- useful for actual recommendation/comparison;
- semantically stable inside one field/profile;
- supported by reviewed evidence;
- not a product-specific marketing metaphor;
- not an ingredient or medical safety shortcut.

Sparse and cold values remain `concept_id = null`.

### Candidate areas

The inventory suggests auditing, not automatically accepting:

```text
skincare efficacy:
  soothing, hydration, barrier_repair, oil_control,
  brightening, firming, anti_aging

skincare/suncare texture:
  refreshing, lightweight, non_sticky, moisturizing

suncare:
  fast_film, water_resistant, makeup_friendly,
  no_white_cast

base makeup:
  coverage, longevity, matte, natural, glow,
  lightweight, moisturizing, non_cakey

cleanser:
  cleansing_power, non_stripping, easy_rinse,
  no_film, double_cleanse

color makeup:
  matte, glossy, color_payoff, longevity
```

The audit may merge, reject, or leave any candidate unpublished.

## Ranking Semantics

### Query slots

Each admitted common preference creates one slot:

```text
profile + field_key + concept_id + polarity
```

Duplicate user mentions create one slot.

### Product evidence

Multiple source facts projecting to the same product slot contribute once:

```text
score = maximum admissible rank strength
```

Sources are unioned for explanation, not summed.

### Match state

Positive-only evidence cannot prove a mismatch.

```text
matching support -> matched
no matching support and no explicit contradiction -> unknown
explicit reviewed opposing fact -> mismatch
```

For `avoid` preferences:

```text
explicit opposing/presence fact -> mismatch
reviewed absence/supporting fact -> matched
otherwise -> unknown
```

Hard ingredient and safety constraints remain in the existing hard-filter and
safety-gate path.

### Ordering

Hard eligibility runs first. Within eligible products:

```text
skin applicability
matched common-concept slots
user relation/baseline fit
evidence-weighted score
unknown count
price
stable product ID
```

Evidence strength and user preference importance are separate concepts.
This phase does not add arbitrary user priority weights; explicit hard/safety
requirements remain hard, and ordinary preferences remain equal slots.

## Comparison Semantics

The common relative contract supports:

```text
price/budget
skin suitability
reviewed common concepts
ordered category facts such as coverage or longevity where available
hard ingredient/safety fit
```

It does not promise comparative conclusions for unsupported marketing
language.

Examples:

```text
"比第二款便宜"
  -> numeric price comparison

"换个更清爽的"
  -> candidate with refreshing support over a baseline without it
  -> wording: better matches the refreshing preference

"更舒缓"
  -> stronger evidence fit, not stronger biological effect,
     unless a directly comparable reviewed measurement exists
```

## Evidence and Answer Alignment

Every matched slot carries:

```text
concept identity
rank strength
attribution
source refs
```

The answer contract may mention the ranking reason only from those same source
refs. It cannot replace a ranking fact with an unrelated claim.

Free-descriptor ProductEvidence remains available for answer detail but cannot
retroactively change product order.

## Test Truth Model

The existing 128-case fixture is audited row by row into four ownership
sections:

```text
translation requirements
allowed semantic equivalents/don't-care fields
deterministic binding expectations
final TaskPlan/state/runtime expectations
```

The gate no longer requires full JSON equality.

It separately reports:

```text
schema validity
one-call count
required semantic coverage
invented source atoms
binding admission
final mode/topic/constraints
state transitions
selected product IDs
hard safety violations
```

Visible development cases are supplemented by deterministic paraphrase and
metamorphic transforms. Prompt changes cannot contain case IDs or frozen
messages.

## Frontend Admission

`FRONTEND-GO` requires:

```text
end-to-end common-question success >= 90%
provider calls per semantic turn = 1
unauthorized state transitions = 0
unmentioned constraint changes = 0
hard safety overrides = 0
wrong product selections = 0
ranking/answer source mismatch = 0
```

Remaining failures must be bounded:

```text
typed clarification
unknown
evidence gap
unsupported comparison
```

Production release remains stricter and requires the agreed repeated official
gate. Frontend admission does not authorize deployment.

## Autonomous Failure Policy

The main agent runs the goal without sub-agents.

For every failure:

1. identify the earliest failing layer;
2. add or preserve a focused RED test;
3. fix the owner layer only;
4. run focused then broader regression.

If two consecutive fixes fail at the same layer:

1. stop prompt or example tuning;
2. write an architecture checkpoint;
3. identify responsibility overload or a false contract;
4. select a general fix;
5. resume without waiting for the sleeping user.

Forbidden fixes:

```text
case-specific prompt examples
phrase dictionaries
gate-only output repair
threshold reduction
second model calls
answer-layer patches for ranking defects
vector similarity as final authority
```

Long-running tests and official gates start once and are polled to exit.

## Scope Boundaries

Not included:

- frontend rendering;
- long-tail concept taxonomy;
- vector index construction;
- live price/stock refresh;
- new web crawling;
- medical or ingredient inference beyond reviewed evidence;
- legacy `app.services` RAG;
- push, deploy, or traffic changes.

The shared dirty implementation is not staged or committed during autonomous
execution.

