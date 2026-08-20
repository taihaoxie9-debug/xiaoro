# Guide Presentation Final Alignment Design

Date: 2026-08-16

Repository: `/Users/bytedance/Desktop/xiaoro-fresh`

Branch: `rebuild`

Reference repository:
`/Users/bytedance/Desktop/xiaoro-shopping-master`

## Status

Approved in visual brainstorming.

This document supersedes the presentation behavior in:

- `2026-08-16-double-blind-copywriter-frontend-integration-design.md`;
- `docs/audits/frontend-integration/old_frontend_behavior.md`;
- `tests/fixtures/guide/presentation/frontend_mode_matrix_v1.jsonl`.

The superseded documents remain useful historical evidence, but they are not
the product truth for final implementation where they conflict with this
document.

## Goal

Finish the local XiaoRo frontend integration with the old visual shell and a
new, auditable presentation contract.

The final experience must:

1. preserve the old rose, muted green-gray, and warm-neutral visual shell;
2. make recommendation copy feel like a real shopping advisor rather than an
   audit report;
3. keep product binding, filtering, ranking, safety, numbers, ingredients,
   warnings, and source attribution owned by code;
4. expose most useful approved product information without dumping raw
   evidence into the chat;
5. give each user-visible mode its own information architecture;
6. insert a real inline product image card directly below each product title
   while the structured answer streams;
7. remove the transient thinking panel on the first answer character;
8. run and pass local browser acceptance only; production deployment is out
   of scope.

## Non-Goals

- No production deployment.
- No third model call, reviewer model, repair call, or retry call.
- No model-owned product selection, ordering, or state mutation.
- No raw OCR, source wall, review wall, or category-fact table in the main
  chat answer.
- No uncalibrated match percentage.
- No redesign of the page shell, sidebar, composer, typography, or palette.
- No new medical diagnosis capability.

## Final Product Decisions

### Visual shell

Preserve:

- page layout and conversation width;
- sidebar and composer;
- user and assistant bubble alignment;
- typography and spacing rhythm;
- rose accent, warm neutral surfaces, and restrained green-gray support color;
- card radius of 8px or less;
- typewriter behavior;
- mobile stacking behavior.

Do not add decorative gradients, floating section cards, nested cards, or
marketing-page composition.

### Main recommendation structure

Recommendation uses this order:

```text
long human summary

product 1 title
inline product image card
full brand positioning paragraph
reference price / exact specification
optional core ingredients
suitable user
advisor reason

product 2
same shape

product 3
same shape

long final recommendation
full product card shelf
compact pitfalls
```

The summary is normally 2-4 sentences. It gives the advisor's judgment and
explains the three product routes in ordinary language.

The closing is normally 2-3 sentences. It identifies the primary choice, the
balanced alternative, and the scenario-driven alternative. It must not
explain internal ranking policy.

### Product block fields

Each product block may render:

1. product name;
2. inline image card with image, name, and price;
3. one full brand-positioning paragraph;
4. `reference price / specification`;
5. core ingredients, only when exact reviewed data is available;
6. suitable user;
7. XiaoRo advisor reason.

Missing fields are omitted. The frontend must not render placeholders such
as:

```text
currently unverified
unknown
information unavailable
not enough evidence to fill this row
```

Missing core ingredients therefore remove the entire ingredient row.

### Full product shelf

The full shelf remains after the closing.

- It contains exactly the products bound by
  `CardDisplayContract.visible_product_ids`.
- It uses the same order as the answer.
- Recommendation normally contains three cards when three eligible products
  exist.
- Each full card may contain at most two code-grounded route labels.
- Green change-summary chips are forbidden in the answer body.
- Route labels are not match percentages.

### Pitfalls

Pitfalls render after the full card shelf.

They are compact and limited to actionable warnings, for example:

- reviewed ingredient conflict with an explicit exclusion;
- package warning;
- water resistance does not remove the need to reapply;
- sensitive users should not treat a merchant safety claim as a guarantee.

Pitfalls are not an evidence wall.

### Evidence visibility

Evidence remains available to code and mode-specific product-knowledge
answers. Ordinary recommendation does not render:

- merchant quote walls;
- consumer review walls;
- source drawers;
- citation lists;
- raw test blocks;
- category fact tables;
- internal selection explanations.

When the user explicitly asks a deep product, brand, research, test, patent,
mechanism, or source question, the product-knowledge mode may use that
material.

## Narrative Fact Architecture

### Problem in the current contract

The current implementation:

1. projects at most two ordinary merchant claims per product;
2. appends preference and concept matches first;
3. truncates `approved_soft_facts` to four.

This can discard the product's most useful differentiating claims and
produce thin copy.

### Narrative atoms

Raw approved rows are first converted into merged narrative atoms.

For example:

```text
light
clear
non-sticky
non-greasy
```

becomes one texture atom rather than four repeated facts.

Eligible narrative dimensions include:

- texture and sensory feel;
- finish and tone effect;
- film speed;
- makeup compatibility;
- water and sweat resistance positioning;
- use context;
- distinctive ordinary efficacy;
- product route and practical positioning.

### Ordinary recommendation exclusions

The following are excluded from ordinary recommendation unless directly
requested:

- cell, biomarker, or biological-model terminology;
- patent counts, paper counts, R&D headcount, and brand history;
- historical sales rankings;
- coupons, gifts, bundles, and expired promotions;
- mechanism counts that do not help a purchase decision;
- generic usage instructions;
- ambiguous, expired, cross-product, or unreviewed claims;
- medical or absolute safety language;
- percentages whose sample, duration, method, or measured object is missing.

### Selection policy

Code selects narrative atoms lexicographically, not through a model:

1. direct relevance to the user's explicit need;
2. ability to distinguish the product from the other displayed products;
3. evidence and identity strength;
4. consumer usefulness;
5. stable field and source ordering.

The target is not a fixed raw-row count. Each product should normally expose
4-7 merged narrative atoms and the copywriter should cover at least 80% of
the required atoms.

`used_soft_fact_ids` remains mandatory. Validation computes coverage over
merged atoms, not raw database rows.

There is no model retry. Invalid model output uses deterministic local
fallback.

### Numeric proof points

At most one directly relevant numeric proof point may appear per product in
ordinary recommendation.

The exact percentage, sample size, duration, measured object, and
attribution are code-owned and rendered without model rewriting.

The model may connect the proof point to the surrounding narrative but may
not change it. For example, a reviewed result that users agreed a product
felt light cannot become a claim that users considered it the best outdoor
sunscreen.

## Copywriter Contract

The second call remains blind to hidden candidates and ranking logic.

It receives:

- mode;
- bounded user need;
- ordered opaque slots;
- merged approved narrative atoms;
- required atom IDs;
- attribution type;
- winner or evidence status;
- length ranges.

It does not receive:

- hidden candidates;
- ranking implementation;
- raw OCR;
- unrestricted evidence;
- state mutation capability.

The copywriter writes:

- summary;
- product positioning;
- advisor reason;
- closing;
- used fact IDs.

It must not write:

- price, specification, SPF/PA, percentages, sample size, or duration;
- ingredients or package warnings;
- a new product order;
- internal terms such as ranking tier, budget utilization algorithm, or
  constraint precedence;
- medical conclusions;
- unsupported superlatives or guarantees.

Recommended content ranges:

```text
summary: 140-260 Chinese characters when enough facts exist
product positioning: 70-150 Chinese characters
advisor reason: 40-110 Chinese characters
closing: 90-200 Chinese characters
```

These are target ranges, not padding requirements.

## Budget Semantics

Budget remains a hard eligibility boundary.

When the user gives an explicit maximum, price proximity to that maximum is
a final soft ordering signal among otherwise equivalent candidates.

Ordering precedence is:

```text
hard safety and eligibility
explicit skin, efficacy, scenario, facet, and concept fit
relative requirement
evidence support and unknown count
budget proximity
stable product ID tie-break
```

Budget proximity must not override a stronger fit or a safety conflict.

Example:

```text
budget maximum: 300
otherwise equivalent eligible prices: 299, 199, 169, 125, 96
preferred order: 299, 199, 169, 125, 96
```

This is not a global "more expensive is better" policy.

Without an explicit maximum, the existing non-budget stable order remains.

## Thinking Pipeline

### Lifecycle

The thinking panel is transient:

```text
mode-specific stage events
-> current stage sentence and quiet markers
-> first answer character appears
-> add leaving state immediately
-> fade and translate for 320ms
-> remove node from DOM
```

No stage timeline, step labels, or thinking history remains below the answer.
History snapshots remove the transient panel.

### Mode-specific stages

```text
recommendation:
  understanding -> retrieval -> decision -> copy

comparison:
  understanding -> retrieval -> decision -> copy

single suitability:
  understanding -> retrieval -> decision -> copy

general or product knowledge:
  understanding -> retrieval -> copy

focused follow-up:
  state -> decision -> copy

budget or skin revision:
  state -> retrieval -> decision -> copy

image identity:
  image_observation -> decision -> copy

image recommendation:
  image_observation -> retrieval -> decision -> copy

image suitability or comparison:
  image_observation -> decision -> copy

consultation:
  state -> observation -> copy

medical escalation:
  state -> observation

clarification and public error:
  no thinking panel
```

The visible sentence uses the actual SSE `stage.summary`. Modes may share a
stage skeleton while displaying different summaries.

## Structured Streaming and Image Insertion

The target visual sequence is:

```text
thinking panel
first summary character
thinking panel leaves
summary typewriter output
product title
inline product image card inserted as one structured node
brand paragraph typewriter output
code-owned fact rows
advisor reason
next product
closing
full product shelf
pitfalls
```

The inline image card appears immediately below the product title, before
brand copy and direct facts.

This supersedes the current `renderPresentation()` order, which appends the
inline card after direct facts.

The inline and full cards bind the same product ID, image, and detail URL.
A later text reference focuses the existing card and does not create a third
representation.

## Image Identity Safety

The current binding policy remains:

```text
minimum similarity: 0.8
minimum top-candidate margin: 0.1
```

Confirmation also requires:

- canonical product identity;
- no disqualifying OCR conflict;
- supported category and visual metadata.

Only `IdentityState.CONFIRMED` may enter decision logic or product cards.

These states fail closed with zero cards:

- visual unavailable;
- no candidate;
- insufficient candidates;
- low confidence;
- ambiguous candidates;
- non-canonical candidate;
- canonical identity unavailable;
- OCR conflict.

The user-facing failure asks for a clearer front image with complete
packaging text. It does not show a guessed product.

## User-Visible Mode Matrix

The implementation must cover these 20 user-visible scenarios:

| # | Scenario | Main structure | Cards |
|---|---|---|---:|
| 1 | recommendation | full recommendation structure | 1-3 |
| 2 | named comparison | conclusion, comparison table, choice | 2-4 |
| 3 | single suitability | direct judgment, fit, conflict, action | 1 |
| 4 | focused product follow-up | answer only the bound product | 1 |
| 5 | relative follow-up | delta, comparison, replacement detail | 1-3 |
| 6 | budget or skin revision | complete rerun recommendation | 1-3 |
| 7 | state-only follow-up | one concise clarification | 0 |
| 8 | product knowledge | direct answer, limits, purchase meaning | 1 |
| 9 | general knowledge | conclusion, explanation, practical advice | 0 |
| 10 | image identity confirmed | identity and bounded facts | 1 |
| 11 | image recommendation | image route, alternatives, differences | 1-3 |
| 12 | image suitability | identity, fit judgment, warning | 1 |
| 13 | image comparison | upload order, comparison, choice | 2-4 |
| 14 | consultation entry/question | one question at a time | 0 |
| 15 | consultation provisional | observations and next question | 0 |
| 16 | consultation confirm/reject | profile confirmation or continue | 0 |
| 17 | medical escalation | stop shopping and advise professional help | 0 |
| 18 | clarification | ask only for missing binding information | 0 |
| 19 | no match/evidence gap | explain blocker and relaxation choices | 0 |
| 20 | public error | short recoverable message | 0 |

Post-consultation recommendation reuses scenario 1.

Image unconfirmed is the zero-card failure state associated with scenarios
10-13 and must be tested explicitly.

## Mode-Specific Requirements

### Comparison

- Start with the practical difference, not a raw table.
- Compare only shared, reviewed dimensions.
- Keep product order stable.
- End with a clear scenario-based choice.
- Put warnings after the comparison rather than filling missing cells with
  "unknown".

### Single suitability

- Lead with suitable, unsuitable, or evidence-insufficient.
- Explain the strongest match and strongest conflict.
- Do not let ordinary merchant positioning override an explicit exclusion.
- Show one bound product card only.

### Follow-up

- Focused product follow-up shows only the referenced product.
- Relative follow-up explains the practical delta in prose and a compact
  comparison table.
- Do not render green change-summary chips.
- State-only follow-up shows no stale cards.

### Revision

Budget and skin revision rerun retrieval and decision and produce a complete
recommendation result.

The answer must not show internal chips such as:

```text
budget maximum: 300
keep: refreshing, commute
```

### Knowledge

- General knowledge has zero cards.
- Product knowledge shows only the bound product.
- Deep brand, research, patent, mechanism, or test material appears only
  when the user asks for it.
- No evidence wall appears after an ordinary answer.

### Consultation

- Ask one question at a time.
- Provisional conclusions display their observation basis.
- Confirmation naturally tells the user how later shopping answers will use
  the profile.
- Medical escalation stops shopping and shows zero cards.

### Clarification, no match, and error

- All are zero-card states.
- Clarification asks one precise question.
- No-match explains which constraints could not be jointly satisfied and
  offers actionable relaxation choices.
- Error is short, recoverable, and never reuses stale cards.

## Section Order

Product-bearing modes use:

```text
summary
optional comparison
product sections
closing
full cards
pitfalls
```

Evidence is not a default visible section.

This supersedes the current order:

```text
closing -> pitfalls -> full cards -> evidence
```

Zero-product modes use only their mode-specific sections.

## Error and Fallback Policy

- Copywriter unavailable: deterministic local copy.
- Copywriter invalid: deterministic local copy; no retry.
- Missing optional fact: omit the row.
- Missing required product identity or image binding: fail closed.
- Image unconfirmed: zero cards and request a clearer image.
- No eligible product: zero cards and actionable no-match copy.
- Public error: no stale products and no thinking panel.

## Implementation Boundaries

Expected implementation areas:

- `app/guide/decision/recommendation.py`
- `app/guide/presentation/copywriter_contracts.py`
- `app/guide/presentation/copywriter_prompt.py`
- `app/guide/presentation/copywriter_validation.py`
- `app/guide/presentation/presentation_packet.py`
- `app/guide/presentation/presentation_compiler.py`
- `app/guide/application/text_recommendation_flow.py`
- `app/guide/application/image_recommendation_flow.py`
- `app/static/guide-presentation.js`
- `app/static/chat.html`
- presentation, decision, runtime, and browser test fixtures

Do not refactor unrelated intent, retrieval, state, or data ingestion code.

## Test and Acceptance Plan

### Decision tests

- explicit maximum filters above-budget products;
- otherwise equivalent candidates prefer smaller distance to the maximum;
- stronger skin, efficacy, scenario, facet, concept, or safety evidence
  remains ahead of budget proximity;
- no-maximum behavior remains stable.

### Presentation contract tests

- narrative atoms are merged deterministically;
- required atom coverage is at least 80%;
- optional missing rows are absent;
- numeric proof point remains exact and code-owned;
- section order is closing, full cards, pitfalls;
- card IDs exactly match visible product IDs;
- revision carries product slots;
- no green change-summary chips exist.

### Copywriter gates

- one provider call only;
- no hard fact leakage;
- no internal ranking language;
- no unsupported attribution;
- no product reorder;
- sufficient narrative coverage;
- natural summary and closing length;
- deterministic fallback on invalid output.

### Frontend contract tests

- one renderer per mode family;
- product title precedes inline image card;
- inline image card precedes brand copy and direct facts;
- later product references do not create duplicate cards;
- full shelf follows closing;
- pitfalls follow full shelf;
- zero-card modes clear stale products;
- history removes the thinking panel;
- XSS-safe DOM APIs only.

### Image tests

- confirmed identity may render one card;
- low confidence, ambiguity, OCR conflict, and unavailable visual states
  render zero cards;
- thresholds remain 0.8 similarity and 0.1 margin;
- multiple-image order is stable.

### Browser acceptance

Run all 20 scenarios on desktop and mobile.

Verify:

- no overlap or horizontal overflow;
- all product images load;
- inline card appears at the product title during streaming;
- first answer character dismisses thinking;
- thinking node is removed after 320ms;
- no stage timeline remains below the answer;
- no raw evidence wall;
- no missing-field placeholder;
- no unapproved green change chips;
- full card shelf and pitfalls use the approved order;
- console and relevant network requests are clean.

## Exit Criteria

Local frontend integration is complete when:

1. all focused and full guide tests pass;
2. official copywriter gates pass under the new fact coverage contract;
3. all 20 desktop and mobile browser scenarios pass;
4. product images have no failures;
5. the user-approved visual shell is preserved;
6. no production deployment has occurred.
