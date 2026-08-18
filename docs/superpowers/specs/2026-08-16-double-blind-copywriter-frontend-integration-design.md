# Double-Blind Copywriter and Frontend Integration Design

Date: 2026-08-16

Repository: `/Users/bytedance/Desktop/xiaoro-fresh`

Branch: `rebuild`

Reference frontend:
`/Users/bytedance/Desktop/xiaoro-shopping-master/app/static/chat.html`

## Goal

Finish the local XiaoRo consumer experience without changing the established
visual design.

The implementation must:

1. preserve the old frontend's colors, typography, spacing, layout, cards,
   bubbles, sidebar, input area, responsive behavior, and animation language;
2. consume the new typed SSE contracts instead of the old loose event and
   Markdown conventions;
3. restore a natural shopping-advisor voice through a second, isolated
   copywriting model call;
4. keep product selection, ordering, state, safety, and hard facts owned by
   code;
5. render recommendation, comparison, knowledge, follow-up, clarification,
   consultation, and image flows cleanly;
6. run locally and pass browser screenshot audits on desktop and mobile;
7. stop before production deployment.

## Final Decisions

The following decisions are approved:

- The old visual style is the baseline. This is an integration and content
  architecture change, not a redesign.
- Visual parity means the same palette, typography, spacing discipline,
  card language, and consumer-shopping tone. The temporary thinking panel
  and non-recommendation layouts may be refined when the old implementation
  is visually weak, as long as they remain recognizably part of the same
  product.
- A semantic turn may use at most two model calls.
- Call one is the existing `TurnMeaning` translator.
- Code remains the sole owner of binding, state transitions, retrieval,
  filtering, safety, ranking, product order, and fact admission.
- Call two is a blind copywriter. It receives only a compact,
  code-approved presentation packet.
- The copywriter may vary wording and tone. It cannot alter product slots,
  product order, numbers, ingredients, warnings, or evidence attribution.
- Hard facts are rendered directly by code. Soft facts may be paraphrased.
  Narrative and transitions are written by the copywriter.
- The copywriter gate checks factual boundaries, not exact wording.
- No reviewer model or third call is allowed.
- Copywriter failure falls back to deterministic copy.
- Product cards use real labels rather than uncalibrated match percentages.
- The temporary thinking panel disappears as soon as answer text starts.
- Detailed claims, quotes, and source references are not duplicated in the
  main answer. They live in expandable evidence areas.
- The main agent performs all implementation and browser QA. Sub-agents are
  forbidden.

## Old Frontend Audit

### Visual shell to preserve

The old `chat.html` provides the approved visual language:

- left conversation and collection sidebar;
- compact top header;
- centered conversation canvas;
- user and assistant bubbles;
- rose accent colors and neutral green-gray surfaces;
- fixed composer with image upload;
- recommendation cards with image, rank, title, metadata, price, badge,
  reason, and product link;
- collapsible evidence and decision sections;
- typewriter answer rendering;
- responsive mobile layout.

The implementation may make small spacing or overflow fixes, but it must not
replace the visual theme, introduce a new design system, or rebuild the page
as a different-looking application.

The old frontend is a behavioral and aesthetic reference, not a requirement
to preserve every weak layout. When audit shows an awkward or cluttered
component, the implementation may improve composition while retaining the
same colors, typography, density, icon style, and interaction rhythm.

### Old answer structure to preserve

The old presenter and prompt contracts use a readable three-part answer:

```text
1. A useful human conclusion
2. One bounded block per product
3. A final "how to choose" recommendation
```

The old recommendation requirements were:

```text
first-paragraph summary

product name
- reference price
- category-relevant core information
- one concrete caution

final selection advice
```

The new implementation preserves this reading rhythm but does not preserve
the old presenter’s keyword rules, unsupported marketing claims, or
Markdown-dependent business logic.

### Old logic not to copy

Do not copy:

- frontend-generated default match percentages;
- legacy `thinking`, `scenario_intent`, `routine`, and loose payload guessing;
- product decisions inferred from Markdown headings;
- uncontrolled duplicate full product cards or cards for unauthorized
  products; the intentional mini inline card plus final full card shelf is
  preserved;
- raw merchant OCR dumped into answer prose;
- frontend business ranking;
- the old presenter's large phrase dictionary and category-specific decision
  rules;
- optional LLM output that can reorder or redefine products.

## Two-Call Architecture

### Call 1: semantic translator

The existing single-call `TurnMeaning` architecture remains unchanged:

```text
user message + bounded conversation context
  -> TurnMeaning
  -> code grounding and reference binding
  -> code-owned state diff and TaskPlan
```

The translator cannot see the final selected product set and cannot write the
answer.

### Code-owned decision pipeline

Code then performs:

```text
canonical retrieval
hard eligibility
safety gates
common-concept and facet ranking
relative comparison
evidence retrieval
winner/tie/insufficient-evidence determination
ordered product slots
```

The result is immutable before the copywriter starts.

### PresentationPacket

Code builds a compact strict packet containing only approved display
material:

```text
turn mode
bounded user-need summary
winner status
ordered opaque product slots
product identity and category
reference price and specification
two to four relevant soft facts
locked hard facts
required warnings
fact IDs and source type
allowed attribution language
main-answer length budget
```

The packet excludes:

- rejected products;
- hidden candidate IDs not displayed to the user;
- database rows and unavailable fields;
- raw conversation history;
- raw user prompt-injection text;
- state mutation APIs;
- ranking functions;
- unreviewed evidence;
- full OCR documents.

Each approved fact has a stable ID and one of:

```text
verified_fact
merchant_claim
consumer_report
package_warning
unknown
```

For narrative input, the packet prefers reviewed `plain_meaning` text.
`exact_text`, numbers, qualifiers, and source references remain available to
code for direct rendering and evidence expansion.

### Call 2: blind copywriter

The copywriter receives only `PresentationPacket`.

It writes strict JSON, never Markdown:

```json
{
  "summary_copy": "string",
  "product_copy": [
    {
      "slot_id": "p1",
      "positioning": "string",
      "advisor_reason": "string",
      "used_soft_fact_ids": ["fact-id"]
    }
  ],
  "closing_copy": "string"
}
```

Invocation policy:

```text
recommendation with displayed products: call
comparison with displayed products: call
product suitability with sufficient display material: call
product or general knowledge with approved answer evidence: call
contentful follow-up or relative recommendation: call
clarification: skip
public error: skip
medical escalation: skip
empty or evidence-gap-only result: use deterministic copy
```

Copywriter configuration is explicit and separate from translation
configuration. Local runtime startup must fail closed to deterministic copy
when no copywriter key or model is configured; it must not silently reuse an
unselected provider.

The copywriter cannot output:

- product IDs or a new product list;
- prices, specifications, percentages, sample sizes, or ingredient lists;
- winner status;
- card order;
- hard warnings;
- source references;
- state changes;
- HTML or Markdown;
- medical conclusions;
- guarantees.

The copywriter can naturally express approved soft meaning, for example:

```text
轻薄清透、不黏腻
  -> 更偏轻盈清爽的肤感

快速成膜
  -> 早上赶时间时会更利落

商家主打油皮适用
  -> 更偏油皮友好的清爽路线
```

Attribution remains visible. A merchant phrase such as `油皮亲妈` may be
shown only as:

```text
商家主打「油皮亲妈」
```

or safely paraphrased as:

```text
更偏油皮友好的清爽路线
```

It must not become `最适合油皮`, `闭眼入`, `保证不闷痘`, or another
unsupported superlative or safety guarantee.

## Three-Layer Fact Responsibility

### Layer 1: locked facts rendered by code

Code directly renders:

- product name and opaque slot binding;
- image and product link;
- card order;
- price and specification;
- SPF/PA and other numeric parameters;
- ingredient names;
- percentages, sample size, and duration;
- package warnings;
- exact merchant or consumer quote when shown;
- evidence type and source link;
- required qualifier and disclaimer.

These are ordinary structured components, not prose generated by code.

### Layer 2: soft facts paraphrased by the copywriter

The copywriter may paraphrase:

- texture and sensory feel;
- usage context;
- non-safety positioning;
- ordinary merchant positioning with explicit attribution;
- bounded consumer experience themes;
- relative emphasis between approved facts.

No exact-word equality is required.

### Layer 3: advisor narrative written by the copywriter

The copywriter owns:

- the first-paragraph conclusion;
- one positioning sentence per displayed product;
- transitions between products;
- the final "how to choose" paragraph;
- concise, friendly shopping-advisor tone.

The target voice is an experienced, direct beauty advisor:

- specific rather than generic;
- warm but not overenthusiastic;
- decisive when evidence permits;
- explicit about uncertainty;
- free of internal system language;
- free of excessive technical vocabulary;
- free of empty marketing slogans.

## Lightweight Copy Validation

The validator protects decision and fact boundaries without grading style.

It checks only:

1. strict JSON schema;
2. every required slot appears exactly once;
3. no unknown, missing, or reordered slot;
4. every referenced soft fact ID belongs to that slot;
5. no new product or ingredient name;
6. no new number, percentage, sample size, duration, price, or specification;
7. no unsupported superlative when winner status is tie or insufficient;
8. no absolute safety, medical, efficacy, or allergy guarantee;
9. required warning and attribution remain code-rendered;
10. configured length bounds.

It does not check:

- exact words;
- exact sentence order inside a field;
- synonyms such as `轻薄清爽` versus `轻盈不黏`;
- punctuation;
- stylistic variation;
- complete JSON equality against a golden answer.

Repeated failures at this layer must trigger an architecture checkpoint before
prompt tuning. The checkpoint must distinguish:

```text
false truth
validator too strict
packet missing useful facts
copywriter responsibility too broad
prompt under-specified
model schema instability
```

Case-specific prompt patches are forbidden.

## Fallback Behavior

The copywriter is called once. There is no repair or reviewer call.

On timeout, provider failure, invalid JSON, slot violation, or hard fact
violation:

```text
use deterministic bounded copy
keep ordered products and hard facts
render the same frontend structure
record fallback telemetry
continue the user turn
```

The fallback copy must be readable but does not need to imitate free-form
model prose.

## Presentation Contract

Add a typed presentation event rather than asking the frontend to parse
Markdown:

```text
presentation_contract
```

Its data contains:

```text
mode
winner status
summary copy
ordered product sections
closing copy
direct fact components
required caution components
evidence-group counts
copy source: model | fallback
```

The existing typed events remain authorities:

```text
decision_process
answer_contract
card_display_contract
products
merchant_claims
review_evidence
product_evidence
general_knowledge
pitfalls
citations
message
end
```

`presentation_contract` does not replace the decision result. It binds
display copy to the already-final result.

The `message` event remains a concise compatibility and history text. New
frontend rendering prefers `presentation_contract`.

### Mode-specific presentation union

`presentation_contract` is a discriminated union, not one recommendation
shape reused for every task:

```text
RecommendationPresentation
ComparisonPresentation
SingleProductPresentation
ProductKnowledgePresentation
GeneralKnowledgePresentation
FollowupPresentation
ImageIdentityPresentation
ImageRecommendationPresentation
ImageSuitabilityPresentation
ImageComparisonPresentation
ConsultationPresentation
ClarificationPresentation
ErrorPresentation
```

Each type has its own allowed sections and card policy.

Shared visual components may be reused, but the copywriter receives a
mode-specific schema and instructions. Recommendation prose is never used as
the fallback shape for knowledge, consultation, clarification, or errors.

The mode-specific contracts define:

```text
required narrative fields
optional narrative fields
allowed product slots
inline mini-card positions
final full-card shelf policy
pitfall policy
evidence policy
closing-action policy
```

## Card Ownership and Section Order

### Sole card authority

The existing `CardDisplayContract` is the sole authority for whether cards
appear and which products they represent:

```text
mode
visible_product_ids
max_cards
reason
```

Neither the copywriter nor the frontend may add a card because a product name
appears in prose.

The presentation packet creates one opaque copy slot for every and only every
`visible_product_id`, preserving exact order:

```text
visible_product_ids = [55, 57, 54]
copy slots          = [p1, p2, p3]
```

The copywriter must return exactly one `product_copy` entry for each visible
slot when product sections are required. It cannot write copy for a hidden
product or omit a visible product.

### Two intentional card representations

The old frontend intentionally has two distinct representations of one
authorized product:

```text
1. a compact inline mini card directly below the product's first primary
   name in the answer;
2. a full product card in the final card shelf after the answer and pitfall
   content.
```

This is not treated as an accidental duplicate. The mini card supports
reading continuity; the full card supports inspection, collection, and
opening the product link.

For each authorized visible product:

```text
inline mini card count <= 1
final full card count <= 1
both representations bind the same product ID and source image
```

The primary answer section is:

```text
product heading
model-written positioning
compact inline mini card
bounded direct facts
required caution
```

After the complete answer and pitfall section, the frontend renders the full
card shelf in `visible_product_ids` order.

If the closing advice refers to an already-rendered product, it uses a text
reference or focus link to the existing inline/full card representations. It
does not create a third card.

The inline mini card contains only:

```text
product image
compact product name
reference price
click target
```

The final full card retains the old visual design:

```text
image
rank
name
brand/category metadata
reference price and price note
real status badge
bounded reason
official/detail link when available
collection action
```

### Typed section order

`presentation_contract` contains an explicit ordered section list using
discriminated section types:

```text
summary
product_section(slot_id)
comparison
closing_advice
pitfalls
evidence
```

The frontend renders this order directly. It does not discover section order
from Markdown headings or from event arrival timing.

The contract validator requires:

- every `product_section` slot belongs to `visible_product_ids`;
- each visible product slot occurs at most once;
- recommendation and comparison include all required visible slots;
- zero-card modes contain no `product_section`;
- pitfalls appear after the main conclusion and product sections;
- final full card shelf appears after pitfalls;
- evidence appears after the full card shelf unless a required high-risk
  warning must be surfaced earlier.

### Mode-specific card matrix

#### Recommendation

```text
cards: 1 to 3
authority: recommendation CardDisplayContract
placement: one inline mini card below each product section
final shelf: the same 1 to 3 products as full cards
```

#### Comparison

```text
cards: exactly the 2 to 4 compared product IDs
authority: comparison CardDisplayContract
placement: inline mini card paired with each compared product section
desktop: side-by-side comparison layout when space permits
mobile: stacked in the same comparison order
unrelated recommendation cards: forbidden
final shelf: full cards for exactly the compared products
```

#### Single-product judgement or suitability

```text
cards: exactly 1 when a product is canonically bound
authority: single CardDisplayContract
placement: inline mini card immediately below the bound product name
final shelf: one full card
other prior candidates: forbidden
```

#### Product-specific knowledge

```text
cards: 1 only when the answer is about one explicitly bound product
placement: inline mini card below the first product-specific answer block
final shelf: one full card
general alternatives: forbidden unless the user asked for alternatives
```

If product-specific knowledge has no valid canonical binding, it must
clarify or answer without a product card according to the typed backend
result.

#### General knowledge

```text
cards: 0
examples: SPF meaning, general ingredient education, routine education
```

General knowledge must not attach a product merely because an example or
brand appears in evidence.

#### Follow-up

```text
price/ingredient/usage question about one focus: at most that one card
comparison follow-up: only the bound comparison set
new recommendation request: recommendation card policy
state revision without product result: zero cards
ambiguous reference: zero cards and clarify
```

Do not replay the entire previous recommendation shelf for a focused
follow-up.

#### Image identify and similar search

```text
uploaded image: remains in the user message
confirmed identified product: one inline mini card below the identity
sentence and one full card in the final shelf
similar candidates: inline sections and final full cards only for result IDs
authorized by image CardDisplayContract
unconfirmed identity: zero product cards and a recovery prompt
```

#### Image suitability

```text
cards: exactly the one product bound to image ordinal 1
placement: inline mini card below the suitability conclusion
final shelf: one full card
```

#### Multi-image comparison

```text
cards: exactly the 2 to 4 canonically confirmed image products
order: image ordinal order from the comparison contract
placement: inline mini cards in comparison sections
final shelf: full cards for the same products in image ordinal order
```

#### Consultation, clarification, errors, and medical escalation

```text
cards: 0 unless a later, separate recommendation turn is executed
```

Profile collection and confirmation do not show products. Public errors do
not show stale cards from a previous turn.

### Pitfall placement

Typed `PitfallsEvent` remains the source of caution cards.

The final answer order is:

```text
main summary
authorized product or comparison sections
closing advice
pitfall panel
final full product card shelf
evidence drawers
```

Pitfalls are filtered to:

- the visible products in the current card contract; or
- a turn-level caution explicitly marked as not product-specific.

High severity items remain separate and visible. Medium and low severity
items may be combined into the old compact `其他注意` treatment.

A required product warning may also appear as one short direct fact inside
that product section, but the full evidence-backed pitfall is rendered once
in the final pitfall panel.

### Product image sourcing

Card images are separate from the previously reported missing detail-evidence
images. Missing detail images do not imply that the same number of product
card hero images is missing.

Image source priority:

```text
fresh content-addressed seed product image
fresh verified local product asset
old repository verified PRODUCT_DISPLAY_OVERRIDES/local asset
manually audited official product-page capture for the exact product
generated neutral placeholder only when no exact product image is approved
```

An official-page capture must record:

```text
exact product identity
source URL
capture timestamp
file SHA-256
crop decision
review status
```

Do not use a visually similar but unverified product image. Do not silently
reuse another variant's image.

## Frontend Rendering

### Temporary thinking panel

The thinking panel is separate from the answer.

It appears immediately after send and cycles through mode-specific states.

The old panel is not copied literally. Use the old rose accent, neutral
surface, compact radius, and typography to build a cleaner transient
pipeline:

```text
one stable compact container
one prominent current-stage sentence
three or four small progress markers
completed markers become quiet checks
current marker breathes
future markers remain muted
no large nested step cards
no technical scores or internal IDs
```

The panel may borrow the recommendation card's visual language, but it must
remain lighter than a result card and must not compete with the final answer.

Recommendation:

```text
正在理解你的需求
正在读取商品资料
正在核对预算、肤质和风险
正在整理推荐结果
```

Comparison:

```text
正在确认比较对象
正在对齐商品事实
正在比较差异和风险
正在整理选择建议
```

Knowledge:

```text
正在定位问题
正在查找审核证据
正在核对回答边界
正在整理答案
```

Image:

```text
正在分析图片
正在确认商品对象
正在检索或比较候选
正在整理结果
```

The frontend starts this sequence locally to avoid an empty wait. Actual
`stage` events advance or replace the visible label. The animation never
delays an available answer.

On the first answer character:

```text
fade opacity to zero
translate upward slightly
remove after approximately 350ms
start or continue typewriter rendering
```

No completed thinking summary remains in the conversation.

### Shared visual grammar across modes

Recommendation is the visual reference, not the universal content template.

Other modes reuse its visual grammar:

```text
same heading hierarchy
same rose status labels
same compact metadata rows
same evidence and pitfall treatment
same inline mini-card and final full-card components when cards are legal
same typewriter and transition timing
```

They retain mode-specific information architecture. Comparison may use a
two-column difference layout, knowledge may use direct-answer and evidence
blocks, consultation may use question/provisional-state blocks, and image
flows may use ordinal image references. These extensions may improve on the
old layout while remaining visually consistent.

### Recommendation answer

Render in the old three-part rhythm:

```text
human summary
product sections/cards
how-to-choose closing advice
```

Each product section has:

```text
real status label
product name
model-written positioning
reference price
two or three category-relevant hard fact components
one required caution when present
```

Category-relevant facts:

```text
suncare: SPF/PA, texture, film speed, usage context, water resistance
serum/skincare: efficacy, ingredient facts, texture, tolerance warning
base makeup: coverage, finish, longevity, skin fit
cleanser: cleansing power, rinse behavior, after-feel, removal ability
color makeup: finish, color payoff, longevity, shade information
fragrance: fragrance family, intensity, longevity, usage context
```

Do not mechanically show ingredients for every category.

Product cards are embedded below their matching product sections. The old
final `为你挑到这些` shelf is also preserved, using the same authorized
product IDs and order.

### Comparison

Render:

```text
clear comparison conclusion
shared-dimension comparison rows
per-product positioning
who each option suits
final choice advice
```

Comparison facts come only from `comparison_data`, decision slots, cards,
and approved evidence.

Only compared products receive cards. Mentioning a product in an evidence
quote or historical context does not authorize a card.

Compared products receive compact inline cards in their sections and full
cards in the final shelf.

### Knowledge and follow-up

Knowledge renders:

```text
direct answer
what the approved evidence says
boundary or caveat
expandable source details
```

Follow-up answers the requested point and does not repeat the full original
recommendation unless the task requires a new selection.

Product-specific knowledge may render one bound card. General knowledge,
unbound questions, and ordinary educational answers render no product card.

### Clarification and errors

Clarification renders the typed question and bounded option chips.

Public errors render friendly messages and recovery actions. Internal error
codes are not exposed as primary user text.

Both modes render zero product cards and must clear any uncommitted deferred
cards from the current turn.

### Evidence areas

Default visibility:

```text
required high-risk warning: expanded
ordinary caution: visible but compact
why this order: collapsed
merchant claims: collapsed
consumer quotes: collapsed
source refs and exact evidence: collapsed
```

The main answer does not duplicate the full contents of these panels.

### Length and overflow

- summary: two to four short sentences;
- product positioning: one or two sentences;
- advisor reason: one sentence;
- closing advice: one short paragraph;
- product title: maximum two visual lines;
- card reason: maximum three visual lines before expand;
- no raw OCR line breaks;
- no unbounded word or URL overflow;
- desktop cards remain stable;
- mobile cards stack without horizontal clipping.

## Frontend Code Shape

Do not introduce React or a new frontend framework.

Preserve the existing HTML and CSS visual shell. Extract or add small,
testable vanilla-JavaScript units only where they reduce the current
monolith:

```text
typed SSE reducer
thinking-stage controller
presentation-contract renderer
product-card fact selector
evidence drawer renderer
history serialization adapter
```

The frontend must not:

- infer business winner state;
- recalculate ranking;
- invent match percentages;
- parse Markdown headings to discover products;
- turn unknown facts into negative facts;
- decide whether a merchant claim is verified.

## Cost and Latency

The second call uses a compact packet for at most the displayed products and
facts. It must report:

```text
prompt tokens
completion tokens
total tokens
latency
model
fallback reason
```

The implementation must measure the total incremental cost and p95 latency.
The copywriter call may add latency, but the temporary thinking animation
covers the wait without delaying completed content.

## Testing Strategy

### TDD

Every contract, adapter, validator, packet builder, fallback, and renderer
change follows RED -> GREEN -> regression.

### Decision invariance

For every copywriter test:

```text
selected product IDs before copy == after copy
product order before copy == after copy
winner status before copy == after copy
state delta before copy == after copy
safety result before copy == after copy
hard fact payload before copy == after copy
```

All counts must remain exact.

### Copywriter gate

The copywriter corpus covers:

- recommendation across all supported categories;
- comparison;
- suitability;
- single-product judgement;
- product knowledge;
- general knowledge;
- follow-up;
- relative recommendation;
- insufficient evidence;
- ties;
- hard safety warnings;
- merchant claims;
- consumer percentages and sample sizes;
- missing facts;
- prompt injection in the original user text;
- schema-invalid output and provider failure.

Scoring is layered:

```text
schema
slot binding
fact-reference grounding
hard atom preservation
winner language authorization
safety and attribution
readability
```

Readability allows paraphrase. It must not use full-text equality.

### Card binding gate

For every public mode assert:

```text
rendered card IDs == CardDisplayContract.visible_product_ids
rendered card order == CardDisplayContract.visible_product_ids
each visible product renders at most one inline mini card
each visible product renders at most one final full card
contentful product modes render both authorized representations
hidden or merely mentioned products render zero cards
zero-card modes render zero cards
pitfall product IDs are a subset of visible product IDs
history reload preserves the same card and section order
```

Explicit cases include:

- three-product recommendation;
- two-product and four-product comparison;
- one-product price, ingredient, usage, and suitability question;
- general knowledge with a product used only as an example;
- ambiguous ordinal;
- state-only budget or skin revision;
- one-image identity;
- one-image suitability;
- two-to-four-image comparison;
- image identity failure;
- consultation and medical escalation;
- copywriter prose that mentions a hidden product name;
- duplicate copywriter slot output.

### Browser audit

Use the built-in browser and screenshots after each meaningful frontend
iteration.

Desktop and mobile coverage:

```text
empty state
temporary thinking animation
recommendation
comparison
product knowledge
general knowledge
clarification
provider fallback
single-image identify/recommend
single-image suitability
two-to-four-image comparison
multi-turn follow-up
history reload
long title and long fact text
missing image and missing link
```

Minimum viewports:

```text
desktop: 1440 x 900
mobile: 390 x 844
```

For each flow verify:

- no overlap or clipping;
- stable card dimensions;
- correct event order;
- thinking panel disappears at first answer text;
- exactly one authorized inline mini card and one authorized final full card
  per visible product, with no third or unauthorized duplicate;
- no raw Markdown leakage;
- no raw unavailable fields;
- no console errors;
- no failed required assets;
- direct facts match backend payload;
- responsive behavior matches the old visual baseline.

### Final local gates

Run:

```text
focused copywriter and presentation tests
Guide full
runtime/application/state/presentation tests
frontend contract and XSS tests
compileall
architecture and import boundaries
git diff --check
staged-index check
desktop/mobile browser screenshots
three official copywriter gate samples
```

The old frontend screenshots are visual references, not pixel hashes that
forbid necessary content-height changes.

## Admission Criteria

Local frontend completion requires:

```text
translator calls <= 1
copywriter calls <= 1
reviewer/repair calls = 0
selected product change after copy = 0
product order change after copy = 0
state change after copy = 0
safety change after copy = 0
hard fact mutation = 0
unsupported winner language = 0
unsupported safety guarantee = 0
frontend required-flow pass rate = 100%
browser console errors = 0
desktop/mobile overlap defects = 0
```

Copywriter prose does not need to be identical across runs.

Official copywriter admission requires:

```text
common readability and usefulness >= 90%
schema-valid structured copy >= 95%
all slot/order/state/safety/hard-fact violations = 0
all three official runs independently meet the thresholds
```

Readability truth is rubric-based and allows equivalent wording. A failed
style preference is not promoted into a hard factual failure.

If official copywriter quality is not adequate, the verdict remains
`NO-GO` at the earliest unclosed layer. Thresholds are not lowered after a
failure.

## Scope Boundaries

In scope:

- copywriter contracts and adapter;
- presentation packet and validator;
- deterministic fallback;
- typed presentation event;
- concise compatibility message;
- frontend typed SSE integration;
- old visual-style preservation;
- local browser screenshot audit;
- local run instructions and closure report.

Out of scope:

- production deployment;
- traffic switch;
- new product crawling;
- new vector index;
- unrelated backend ranking changes;
- redesigning the visual identity;
- React migration;
- third model or reviewer;
- sub-agents.

## Completion Definition

The work is complete when the local application runs end to end with:

```text
natural advisor copy
unchanged product decisions
direct locked facts
clean three-part presentation
temporary disappearing thinking animation
typed structured panels
old visual identity
green desktop and mobile screenshot audit
green local and official gates
```

No deployment occurs in this phase.
