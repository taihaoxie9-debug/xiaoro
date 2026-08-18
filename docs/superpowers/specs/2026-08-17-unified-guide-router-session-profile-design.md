# Unified Guide Router And Session Profile Design

Date: 2026-08-17

Repository: `/Users/bytedance/Desktop/xiaoro-fresh`

Branch: `rebuild`

Status: Approved for implementation

## 1. Goal

Close the remaining pre-launch gaps without replacing the established
selection engine:

1. project reviewed product specifications into every eligible card;
2. give recommendation, comparison, product knowledge, general knowledge,
   image, follow-up, and consultation their own presentation duties;
3. route every turn through one semantic translation and one local router;
4. let a conversation move between those modes without losing product,
   image, recommendation, knowledge, consultation, or profile context;
5. replace the fixed consultation questionnaire with source-bound dynamic
   observation, provisional assessment, and follow-up;
6. keep user profile data session-local by default;
7. prove behavior with offline replay, real intent-model smoke tests, two
   independent blind batches, and desktop/mobile browser acceptance.

The implementation remains local. It does not deploy production traffic.

## 2. Existing Foundations To Preserve

The following components are established and remain authoritative:

- Canonical product IDs and the controlled exact-product, exact-variant, and
  ambiguous-family alias registry;
- `SelectionFact`, hard filtering, safety gates, soft ranking, relative
  comparison, and stable product ordering;
- the reviewed Selection Parent Concept asset:
  - 2,322 product selection facts;
  - 1,775 soft-rank facts;
  - 103 reviewed source values;
  - 99 approved projections;
  - 48 field-scoped parent concepts;
- code-owned constraint transitions;
- `PendingTurn`, SQLite CAS, public-event delayed commit, owner isolation, and
  session deletion;
- the approved old XiaoRo visual shell and typed SSE presentation path.

The parent-concept asset is a product-fact projection, not a user phrase
dictionary. It may admit an open ordinary preference into a reviewed concept.
It must not become a universal router vocabulary.

## 3. Non-Goals

- No production deployment.
- No account system, multi-person dossiers, or long-term profile UI.
- No automatic cross-session profile inheritance.
- No second semantic judge, copy repair call, or model retry.
- No model-owned product IDs, ranking, hard filtering, safety decision, or
  state mutation.
- No global synonym table that attempts to enumerate natural language.
- No replacement of the current selection and ranking engine.
- No chain-of-thought persistence or display.

## 4. Authority Model

### 4.1 Semantic model

One intent-model call translates the current turn into source-bound atoms:

- operation and topic hints;
- continuity hint: continue, return to prior focus, or start a new task;
- product and image mentions;
- references and ordinals;
- budget, ordinary preference, and hard-condition candidates;
- consultation observations, locations, triggers, duration, and severity;
- question meaning;
- a provisional consultation hypothesis and the highest-value missing
  observation.

The model may propose meaning. It cannot bind a Canonical product ID, mutate
stored constraints, select products, or persist a profile.

### 4.2 Semantic admission code

Three independent admission paths validate model output:

1. task and focus admission;
2. product preference admission;
3. consultation observation admission.

Every candidate receives one auditable disposition:

```text
admitted
retained_free
deferred_until_topic
rejected_protocol
```

No semantically plausible candidate may disappear silently.

Exact string equality is reserved for protocol identity, numeric values,
source spans, versions, and Canonical IDs. Open meaning is admitted through
reviewed concepts or retained losslessly as a free descriptor.

### 4.3 Local router

The router chooses the processor and state transition using:

```text
validated current turn
> explicit pending-turn reply
> current focus state
> confirmed session profile
> unknown
```

It owns:

- continue, supplement, correct, withdraw, replace-task, and return-to-focus
  behavior;
- focus binding;
- whether consultation continues, pauses, resumes, or exits;
- whether image identity feeds recommendation, comparison, suitability, or
  product knowledge;
- whether clarification is required.

### 4.4 Decision code

Existing code remains the sole owner of:

- safety and product eligibility;
- category, budget, and explicit exclusion hard filters;
- skin, efficacy, scenario, texture, facet, and parent-concept soft ranking;
- relative comparisons;
- evidence support and unknown handling;
- budget proximity as a final tie-break;
- stable product ordering.

## 5. Unified Router V1

### 5.1 Feature flag

Add:

```text
GUIDE_UNIFIED_ROUTER_ENABLED=true|false
```

When disabled, the existing owner selection and flows remain available.
New snapshot fields are optional and backward compatible. A failed new gate
can therefore disable the router without reverting specification, card, or
presentation fixes.

### 5.2 Route contract

The local router returns a strict decision:

```text
processor:
  recommendation
  comparison
  product_knowledge
  general_knowledge
  image_identity
  consultation
  clarification
  safety_escalation

continuity:
  continue
  supplement
  correct
  withdraw
  replace_task
  return_to_focus

focus_source:
  explicit_product
  candidate_batch
  current_product
  confirmed_image
  knowledge_topic
  consultation
  none
```

The router emits no user prose and performs no retrieval.

### 5.3 Routing priority

1. Active damage or serious adverse-reaction language enters safety
   escalation.
2. An explicit new task cancels a conflicting `PendingTurn`.
3. A valid pending reply resumes its stored task.
4. A current image is identified before downstream shopping behavior.
5. Explicit product names and valid references bind product focus.
6. Explicit operation and question meaning choose the processor.
7. A genuine continuation may reuse an existing focus.
8. Missing or ambiguous binding produces one precise clarification.

An active consultation can never claim every later turn. "先看防晒" exits
consultation for the current turn while preserving unconfirmed observations.

## 6. Focus State

`ConversationSnapshot` gains an optional `focus_state`. It stores independent
recoverable focuses rather than one implicit global focus:

```text
active_processor
current_product_id
current_candidate_batch
confirmed_image_products
current_knowledge_topic
last_question_meaning
```

Existing `query_context`, `candidates`, `focused_candidate_ordinal`,
general-knowledge focus, consultation state, and `PendingTurn` remain the
authoritative data for their domains. `focus_state` references them; it does
not duplicate hidden candidates, ranking output, or raw transcripts.

A mode switch updates `active_processor` without clearing unrelated valid
focus. This supports:

```text
recommend sunscreen
-> ask about the second product
-> discuss current redness
-> ask what retinol is
-> return to the earlier second product
-> revise budget and recommend again
```

Confirmed image identity is persisted only as Canonical product IDs plus
upload ordinals. Unconfirmed image candidates are never persisted as focus.

## 7. Session Profile

### 7.1 Profile structure

The default profile is session-local and separated into:

```text
base_skin:
  oily | dry | combination | normal | unknown

stable_tendencies:
  sensitivity
  seasonal_redness
  acid_triggered_irritation
  dehydration
  other reviewed tendencies

current_conditions:
  redness
  stinging
  flaking
  tightness
  swelling
  broken_skin
  oozing
  persistent_pain

explicit_restrictions:
  user-confirmed ingredient exclusions or allergies
```

Each stored item carries source turn, status, and confirmation state.

### 7.2 How facts enter the profile

- "我是敏感肌" directly confirms a session-level stable tendency.
- "我最近泛红刺痛" records current conditions, not a permanent skin type.
- "我可能是敏感肌" remains provisional and may start consultation.
- "给朋友看，她是敏感肌" is current-task subject data and must not modify
  the user's own profile.
- A dynamic consultation conclusion enters the session profile only after
  explicit user confirmation.

New sessions inherit nothing by default. Deleting a session removes this
profile with the rest of the snapshot.

### 7.3 Decision projection

The profile does not introduce a second ranker.

```text
current explicit request > confirmed session profile > unknown
```

- base skin and stable sensitivity tendencies become existing soft ranking
  inputs;
- explicit ingredient exclusions or allergies become existing hard filters;
- active damage and serious adverse reactions enter the existing safety gate;
- ordinary merchant "sensitive skin suitable" claims cannot satisfy a hard
  safety condition;
- the same profile fact cannot score twice through two projections.

Automatic writes to the current long-term `profile_state` are disabled.
Long-term opt-in, viewing, editing, and account ownership remain post-launch.

## 8. Dynamic Light Consultation

### 8.1 Observation model

Consultation is no longer an ordered five-question form. The model extracts
all observations expressed in a turn, including:

- oiliness and location;
- dryness, tightness, or flaking and location;
- redness and trigger;
- stinging, burning, or pain and context;
- persistence or recurrence;
- swelling, breakage, or oozing.

Code verifies every observation against current-message source text. It may
normalize a supported observation but cannot invent "T-zone", "cheeks", or a
trigger absent from the message.

### 8.2 Provisional assessment

The model may propose:

- base skin direction;
- stable tendencies;
- current condition;
- observation IDs supporting each conclusion;
- the most useful missing dimension.

Code accepts a displayed base-skin direction only when at least two
compatible observations support it. One safety signal is sufficient for a
safety response. Contradictory or insufficient observations remain
provisional.

### 8.3 Dynamic questions

Each turn asks at most one focused question. The next question is selected
from the largest decision-relevant gap, not from a fixed order:

```text
unknown oil/dry location
unknown persistence or trigger
unknown ordinary-product tolerance
unknown active-damage risk
confirmation or correction
```

Typical consultation length is two to four turns. Users may correct an
observation, change topic, or exit at any time. Corrections replace the
affected observation; they do not accumulate contradictory facts.

## 9. Image As An Identity Entry

Image handling performs:

```text
visual/OCR candidates
-> fail-closed Canonical identity
-> local router
-> existing downstream processor
```

- image only: identity plus concise product profile;
- image plus product question: product knowledge or suitability;
- "找相似": explain each candidate's shared and different dimensions;
- "找相似，100以内、更清爽": ordinary constrained recommendation;
- two or three confirmed images: standard comparison;
- unconfirmed identity: zero cards and a request for a clearer image.

The source product does not consume an alternative recommendation slot.
Comparison defaults to two products and allows at most three.

## 10. Specification Projection

Card specification resolution is SKU-aware:

1. use an accepted exact-variant `net_content` fact only when its
   `variant_scope` matches the bound variant;
2. otherwise use a unique accepted exact-product specification;
3. if multiple incompatible specifications remain, omit specification;
4. never infer capacity from product name, another variant, bundle gift, or
   expired promotion.

The same resolved specification appears in:

- inline card;
- direct fact row as `reference price / specification`;
- full product card;
- product knowledge and comparison when relevant.

Examples:

```text
¥1050 / 50ml
¥1080 / 50ml
¥88.11 / 15g x 2
```

User-facing copy omits internal phrases such as "页面组合" and "页面记录版本".

## 11. Presentation Contracts

### 11.1 Global language rules

Public copy must not expose:

```text
candidate
code verification
hard condition
evidence level
admission
cannot pass
page record version
this round
```

Use "品牌主打" once as the natural attribution for ordinary merchant
positioning. Do not repeat "商家宣称" before every sentence.

Useful reviewed data should be visible, but raw evidence rows must not be
dumped. Recommendation targets 80%-90% coverage of high-value merged
narrative atoms. Deep mechanisms, patents, brand history, and research appear
only when directly requested.

Missing optional fields are omitted. They never render "unknown" or
"unverified".

### 11.2 Recommendation and revision

```text
natural advisor summary
product title
compact inline card
brand positioning with useful proof point when available
reference price / specification
optional ingredients
suitable user or scenario
XiaoRo reason
...
non-repetitive final recommendation
full product cards
compact actionable pitfalls
```

The summary discusses value, trade-offs, route, or scenario. The closing
answers which product to choose under which situation. They must not repeat
the same function.

### 11.3 Comparison

- default two products, maximum three;
- practical conclusion first;
- horizontal table for shared reviewed dimensions;
- full product explanation after the table;
- scenario-based closing;
- comparison product shelf and actionable pitfalls.

### 11.4 Product knowledge and focused follow-up

Answer only the question asked:

```text
product title
inline card
direct answer sections, such as brand positioning, texture, usage, or caution
single bottom product card
```

Do not add recommendation reasons or a generic final recommendation.

Whenever a response explicitly mentions and binds a product, its corresponding
bottom card is shown. General knowledge with no product remains zero-card.

### 11.5 Image

Once identity is confirmed, reuse the relevant recommendation, comparison,
knowledge, or suitability presentation contract. Image identity itself does
not create a thin parallel shopping template.

### 11.6 Pitfalls

Pitfalls are user actions, not internal policy explanations. They may say:

- patch test first when the skin is stable;
- pause new products during active redness or stinging;
- reapply sunscreen during prolonged outdoor exposure;
- check the current package ingredient list for an explicit exclusion.

They must not explain hard filters, evidence tiers, or why code admitted a
claim.

### 11.7 Product shelf titles

```text
recommendation: 为你挑到这些
explicitly mentioned products: 本轮提到的商品
confirmed image products: 本轮识别到的商品
comparison: 本次对比商品
```

## 12. Fallback

The copywriter remains optional and receives approved facts only. It cannot
change hard facts or product order.

If the copywriter is unavailable or invalid:

- do not retry;
- use a mode-specific deterministic fallback;
- preserve useful approved facts;
- preserve section duties;
- never emit audit or filtering language.

Product knowledge, caution follow-up, and consultation fallback are distinct
from recommendation fallback.

## 13. Verification

### 13.1 Offline replay

Before new API calls, replay all stored semantic outputs through:

```text
schema
-> admission
-> binding
-> routing
-> state transition
-> task execution
-> SSE
-> presentation contract
```

The copywriter is disabled.

### 13.2 Real-model smoke

Run approximately 40 deliberately mixed turns with one intent-model call per
turn. Persist raw input, context, model output, route decision, final state,
and result hashes. Do not call the copywriter.

### 13.3 Independent blind batches

Run two separately frozen batches of 100 natural cases. Batch two must not be
the same cases or simple paraphrases of batch one. Both include isolated
questions and independent multi-turn contexts. Inputs include colloquial
language, typos, omissions, corrections, withdrawals, topic switches,
references, nicknames, images, consultation observations, and conflicting
conditions.

Each expected result freezes:

- acceptable semantic meaning;
- bound products or images;
- processor and continuity;
- allowed state changes;
- TaskPlan;
- card IDs;
- clarification and safety behavior.

Pass criteria for both batches:

```text
end-to-end success >= 90%
each major category >= 80%
wrong product selection = 0
unauthorized state transition = 0
hard-condition override = 0
unsafe downgrade = 0
cross-session leakage = 0
```

### 13.4 Earliest-distortion audit

Every failure is assigned to the first incorrect layer:

1. model translation;
2. semantic admission;
3. identity/reference binding;
4. route selection;
5. state transition;
6. decision execution;
7. presentation.

Fixes target the general responsibility boundary. A failing sentence cannot
be patched with an ad-hoc keyword unless the vocabulary is genuinely closed.
Saved model outputs are replayed offline after each change.

### 13.5 Final acceptance

- focused and full Guide tests pass;
- real intent gates pass;
- desktop and mobile browser matrices pass;
- SSE delivery, disconnect discard, CAS, refresh, worker isolation, deletion,
  and owner isolation pass;
- no product image failure, overflow, console error, or relevant network
  error;
- thinking disappears on the first answer character;
- no production deployment occurs.

## 14. Exit Criteria

This phase is complete only when:

1. specification and high-value data render consistently;
2. every product-bearing mode uses its approved presentation contract;
3. the unified router can move among all supported processors without stale
   focus hijacking;
4. dynamic consultation accepts natural multi-observation answers;
5. session profile projection obeys source and safety priority;
6. the feature flag can return to the old router;
7. both independent blind batches meet the thresholds;
8. full automated and browser acceptance evidence is recorded.
