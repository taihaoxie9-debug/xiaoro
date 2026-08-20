# Evidence Use Audit and Unified Ranking Design

**Status:** Approved for Goal-mode implementation.

**Repository:** `/Users/bytedance/Desktop/xiaoro-fresh`

**Branch:** `rebuild`

**Scope boundary:** Backend only. Stop before frontend rendering changes.

## 1. One-Line Goal

Use every reviewed product-detail fact for every decision purpose it can
legitimately support, without letting repeated merchant copy inflate ranking
or letting a merchant safety claim satisfy a serious allergy, pregnancy, or
absolute-exclusion request.

## 2. Why This Intermediate Phase Exists

The image-evidence phase successfully preserved the product-detail asset, but
preservation and use are different completion criteria.

The current production assets contain:

- 1,262 `ProductEvidenceBlock` records;
- 1,079 accepted, answerable blocks across 86 products;
- 299 accepted blocks authorized for `soft_rank` or `weak_soft_rank`;
- 144 accepted blocks authorized for `hard_filter`;
- 534 accepted blocks authorized for comparison;
- 1,136 normalized Merchant Claims;
- 778 Merchant Claims marked for soft ranking;
- 398 merged soft-ranking category facts active at runtime;
- 100 of 103 products with at least one active soft-ranking fact.

Those numbers do not mean the new high-fidelity image asset is fully used.
Today:

1. the answer retriever can search accepted Product Evidence;
2. the existing facet ranker consumes Category Facts and normalized Merchant
   Claims;
3. Product Evidence `soft_rank`, `weak_soft_rank`, and `compare` permissions
   are not direct inputs to the decision engine;
4. Product Evidence `hard_filter` is used only for evidence-side variant
   conflict handling, not as a recommendation exclusion input;
5. the same underlying image statement may exist in Merchant Claims and
   Product Evidence, so feeding both independently would double count it;
6. some selection-relevant ingredient, efficacy, suitability, and scenario
   evidence is answerable but lacks the ranking permission it should have.

This phase closes that usage gap before broader semantic work or frontend
tuning.

## 3. Superseded Rule

This design supersedes the earlier blanket rule:

```text
merchant "sensitive skin suitable" or "post-procedure suitable"
  -> display only, never rank
```

The replacement is context-sensitive:

```text
ordinary preference
  -> merchant claim may provide weak soft-ranking evidence

serious safety constraint
  -> merchant claim cannot satisfy the constraint or improve rank
```

Examples:

| User statement | Interpreted strength | Merchant claim use |
|---|---|---|
| `我是敏感肌，想找温和一点的` | preference | weak soft rank + attributed answer |
| `刚做完医美，想找温和一点的` | preference | weak soft rank + attributed answer |
| `我酒精过敏，绝对不能含酒精` | safety | ignored for passing/ranking; strong evidence required |
| `孕期必须确认能用` | safety | ignored for passing/ranking; fail closed without strong evidence |
| unclear severity | unknown | treat as safety, not preference |

## 4. Public Architecture Stays Two-Lane

There are only two product-selection lanes:

```text
hard constraints
  -> decide whether a candidate remains eligible

soft preferences
  -> reorder eligible candidates
```

`weak_soft_rank` is not a third pipeline. It is only a lower evidence weight
inside the one soft-ranking engine.

The model never chooses whether evidence is weak or strong. Evidence strength
is deterministic from the reviewed source and use authorization.

## 5. Static Capability Versus Runtime Use

The system must separate two questions.

### 5.1 Static capability

Asked once during evidence audit:

```text
What is the strongest use this evidence can ever support?
```

Examples:

| Evidence | Static maximum |
|---|---|
| ordinary merchant efficacy claim | answer + compare + weak soft rank |
| merchant ingredient-benefit claim | answer + compare + weak soft rank |
| merchant suitability or scenario claim | answer + compare + weak soft rank |
| consumer self-report | answer + weak soft rank |
| product-level human or instrument test with method and sample | answer + compare + soft rank |
| in-vitro ingredient mechanism without product outcome | answer only |
| exact package ingredient list | answer + compare + hard constraint support |
| exact SPF, size, shade, or variant specification | answer + compare + hard constraint support |
| merchant positive safety claim | answer + contextual weak soft-rank capability |
| official/package contraindication or warning | answer + safety-gate input |
| usage steps, batch lookup, packaging history, brand story | answer only |

### 5.2 Runtime use

Asked for every user request:

```text
Given the user's requested dimension and constraint strength,
which of the statically authorized uses are allowed now?
```

Runtime may always reduce a static capability. It may never upgrade it.

Examples:

- a merchant "sensitive skin suitable" claim may match an ordinary
  sensitivity preference;
- the same claim is disabled for an allergy or absolute safety request;
- a verified ingredient presence can be a soft preference match or a hard
  inclusion constraint depending on user wording;
- an unverifiable exclusion remains unknown and fails closed when hard.

## 6. Evidence Use Audit

The main Agent must audit all 1,079 accepted Product Evidence blocks. Sampling
is not sufficient.

For every block, the audit must decide:

1. whether it is useful only for answering;
2. whether it distinguishes products on a user-relevant selection dimension;
3. whether it supports comparison;
4. whether its source allows weak soft rank, normal soft rank, hard
   constraints, or a safety gate;
5. whether its subject is the exact product, exact variant, family, bundle,
   gift, or another product;
6. whether the existing use permissions are correct;
7. why any selection-relevant evidence remains answer-only.

The audit must not bulk-authorize records through a global keyword list.
Existing exact text, relations, qualifiers, provenance, and subject scope are
review inputs. Any permission change requires returning to the source image or
other audited visual source.

`unclassified` remains legal. Uncertain relationships remain answer-only or
ambiguous; they must not be forced into a facet.

## 7. Unified Selection Projection

Raw Product Evidence remains the answer source. Ranking consumes a derived,
reviewed projection, not the raw block text.

Conceptually:

```text
Canonical / approved Category Facts
Merchant Claims
accepted Product Evidence with rank authorization
        |
        v
unified selection projection
        |
        v
existing DecisionProductFacts.category_fields
        |
        v
existing hard gate + facet ranker
```

The projection is not a second Agent, recommendation engine, or source of
truth. It is a deterministic adapter into the existing Category Fact/Facet
path.

A projected selection fact needs:

```text
product_id
category_profile
subject_scope
variant_scope
field_key
normalized_value
evidence_strength
source evidence IDs / claim IDs
capability ceiling
review rationale
```

Open descriptions remain preserved in Product Evidence. Only the small
selection-facing projection is normalized.

Unknown or non-applicable projection fields are dropped from ranking without
discarding the underlying answer evidence.

## 8. Duplicate-Free Scoring

Evidence count must never equal ranking strength.

The scoring identity is:

```text
product_id
+ subject_scope
+ variant_scope
+ field_key
+ normalized requested value
```

For a single candidate and a single user-requested value, all matching source
records collapse into one scoring slot.

Example:

```text
user asks:
  oily-skin suitable + hydrating + lightweight

scoring slots:
  suitable_skin=oily
  efficacy=hydrating
  texture=lightweight
```

Five images that all say "油皮挚爱" still fill only the
`suitable_skin=oily` slot once.

If multiple sources support one slot:

```text
rank contribution = maximum authorized evidence strength
not the sum of source strengths
```

The source list remains available for provenance and answer display.

Different normalized user targets remain different slots. For example,
`efficacy=hydrating` and `efficacy=soothing` may each contribute once when the
user asks for both.

Variant evidence must not spill into another variant or the whole family.

## 9. Soft-Ranking Strength

The backend exposes one soft-ranking result. Evidence weight is internal:

```text
2 = reviewed strong product-level fact or qualifying product-level test
1 = merchant claim or consumer self-report
0 = unknown / no authorized evidence
```

Known mismatch remains worse than unknown, preserving the current
match-over-unknown-over-mismatch contract.

The existing no-preference path must remain byte-for-byte order compatible.
Unrequested merchant claims never add points.

No quantity bonus, source-count bonus, image-count bonus, copy-length bonus,
or marketing-density bonus is allowed.

## 10. User-Strength Translation and Safety

The semantic layer already carries:

```text
preference
safety
unknown
```

It remains a translator, not a policy engine.

Code applies these rules:

1. explicit deterministic hard/safety signals cannot be downgraded by the
   model;
2. `preference` may consume merchant weak-soft evidence;
3. `safety` disables merchant claims as pass/rank evidence;
4. `unknown` follows the strict safety side;
5. missing strong evidence for a hard safety request fails closed;
6. positive merchant safety language is always attributed as a merchant
   claim;
7. no evidence can produce a safety guarantee.

Model variation may cause an overly cautious result, but it must not allow a
serious constraint to pass on weak merchant evidence.

Repeated real-model gates must measure route/detail validity and outcome
stability. A failing broad gate keeps production status at NO-GO.

## 11. Recommendation, Comparison, and Follow-Up

### 11.1 Recommendation

- apply hard constraints first;
- create one slot per user-requested facet value;
- project only authorized evidence;
- deduplicate by selection identity;
- choose the strongest source per slot;
- rank eligible products deterministically;
- preserve existing business tie-breakers.

### 11.2 Comparison

Comparison uses the same unified selection facts and Product Evidence
provenance. It must not declare a winner from the number of claims or images.
Requested dimensions are compared directly; unrequested evidence may be shown
as supporting product information but does not add rank points.

### 11.3 Follow-up

Simple current-item and ordinal follow-ups reuse the persisted candidate,
product, and compiled preference context. A follow-up must not reclassify the
same claim into a different strength merely because the user used a pronoun.

## 12. Backend Presentation Boundary

This Goal stops before frontend implementation.

The backend may extend typed events or response contracts only as needed to
expose:

- matched selection dimensions;
- evidence strength;
- merchant-claim attribution;
- source evidence IDs;
- unknown or safety boundaries.

Do not modify `app/static/chat.html` in this Goal. Backend verification ends
when the typed payload is stable and tested for later frontend consumption.

## 13. Verification

### 13.1 Asset and audit gates

- all 1,079 accepted blocks receive a checked use decision;
- every permission change has visual-source confirmation;
- every selection-relevant answer-only block has an explicit reason;
- nonaccepted blocks never enter the projection;
- content-addressed evidence, projection, and manifest hashes validate;
- per-profile before/after capability coverage is reported.

### 13.2 Duplicate and scoring gates

- one claim repeated across images scores once;
- the same source present in Merchant Claims and Product Evidence scores once;
- strong and weak evidence for one slot use the strong score, not the sum;
- two distinct requested values may score independently;
- family or variant evidence cannot leak scope;
- unrequested marketing claims cannot affect order;
- no-preference order remains unchanged.

### 13.3 Safety gates

Use the same merchant suitability statement in paired tests:

```text
"我是敏感肌，想找温和一点的"
  -> ordinary preference, weak soft rank allowed

"我酒精过敏，绝对不能含酒精"
  -> safety constraint, merchant claim ignored
```

Also cover pregnancy, active post-procedure risk, unknown strength, missing
evidence, exact ingredient presence, and verified warning behavior.

### 13.4 End-to-end gates

Cover at minimum:

- ordinary recommendation with multiple facets;
- direct product comparison;
- same-product follow-up;
- candidate ordinal follow-up;
- ingredient inclusion and exclusion;
- merchant suitability preference;
- severe safety request;
- product with unknown evidence;
- product with duplicate source claims.

Run focused, Runtime, Boundary, compile, and diff checks. Run repeated official
real-model broad gates. A local fixture pass cannot override a real-model
failure.

## 14. Closure Report

The backend closure report must include:

- evidence counts before and after use audit;
- changed capability counts by category profile and management label;
- count and examples of selection-relevant answer-only blocks;
- projection count and unique scoring-key count;
- cross-asset duplicate count;
- active product/facet coverage by category profile;
- recommendation, comparison, and follow-up test results;
- repeated real-model route/detail/outcome results;
- remaining blocked or ambiguous evidence;
- explicit frontend handoff contract;
- final GO/NO-GO status and reason.

## 15. Explicit Non-Goals

- no frontend rendering changes;
- no recrawl of the 80 blocked images;
- no second Agent or second ranking engine;
- no global keyword dictionary as the evidence authorization mechanism;
- no model-authored product facts, scores, IDs, citations, or safety result;
- no source-count or marketing-volume ranking bonus;
- no push or deploy;
- no production GO while the official broad model gate remains red.
