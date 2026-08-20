# Overnight Final Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish one controlled overnight acceptance of the Unified XiaoRo
chat chain, including an unseen 100-turn blind exam, real-image behavior,
copywriter richness, final presentation hierarchy, and a real `/chat`
browser `3 x 5`, without training on stale exercises or adding wording
patches.

**Architecture:** Preserve the existing authority chain: the model translates
open language into finite typed parent concepts; code validates source
grounding, Canonical identity, state transitions, product facts, and safety;
the presentation packet assigns approved facts to fixed public slots; the
frontend only renders that contract. Repairs are allowed only at the earliest
incorrect shared boundary and must be proved with RED -> GREEN tests.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, SQLite CAS state, typed SSE,
DeepSeek/SiliconFlow-compatible semantic and copywriter providers, pytest,
Node.js DOM contract tests, Playwright Chromium.

---

## 0. Authority And Tonight's Plain-Language Contract

Repository:

```text
/Users/bytedance/Desktop/xiaoro-fresh
```

Branch:

```text
rebuild
```

Reference-only repository:

```text
/Users/bytedance/Desktop/xiaoro-shopping-master
```

Do not edit or run the old repository as the acceptance runtime.

This document is the only execution contract for tonight. It supersedes the
remaining unchecked execution steps in:

```text
docs/superpowers/plans/2026-08-18-continuous-conversation-final-acceptance.md
```

The older document remains architecture and history evidence only.

In plain language, tonight does exactly this:

1. Do not create or rerun another 100 old exercise turns.
2. Audit old failures only to find shared architecture defects, stale fixture
   assumptions, wrong products/images, or state pollution.
3. Close the presentation hierarchy before the exam so facts cannot disappear
   between Canonical data, copywriter slots, and frontend DOM.
4. Qualify the current copywriter Prompt with 20 real packets.
5. Find and ground real product photos that are not the image index's own
   standard white-background inputs.
6. Freeze current code, Prompt, data, and two new unseen `20 x 5` papers.
7. Run Blind A once. Pass at `>=90/100`, `>=18/20`, with every serious counter
   equal to zero.
8. If A fails, invalidate it, use it only as exercise evidence, repair shared
   architecture under TDD, and use Blind B once. There is no Blind C.
9. Run three real five-turn browser conversations on `/chat`, with real
   semantic translation, real copywriting, real SSE, and real images.
10. Only after every gate passes, produce the closure report and perform the
    approved release/commit/push step.

The user explicitly authorized continuous execution on 2026-08-19. After this
document is synchronized, start Task 1 and continue without a voluntary pause
through the completed real `/chat` browser rendering acceptance.

Do not stop to ask for another approval after:

```text
old-question audit
presentation audit
any shared-layer repair
focused or full regression
copywriter qualification
image ground-truth freeze
Blind A sealing or scoring
Blind A invalidation
Blind B sealing or scoring
backend qualification
browser server startup
```

An ordinary failure is work to diagnose, not a checkpoint to hand back. A
serious failure stops only the active paid command; it does not stop the
overall execution. Preserve evidence, switch to zero API, repair the earliest
shared layer under TDD, replay, re-freeze, and automatically resume the
appropriate qualification.

## 1. Non-Negotiable Architecture Rules

### 1.1 Semantic authority

Required path:

```text
unlimited user wording
  -> model emits finite typed parent operation/concept/reference
  -> code admits source-grounded atoms
  -> code binds Canonical product/image/state
  -> code executes route, state, decision, and evidence policy
  -> presentation_contract
  -> frontend renderer
```

Prohibited permanent fixes:

```text
one observed sentence -> one regex
one verb/synonym -> one code branch
one product ID -> one special case
one stale fixture result -> retrieval rollback
one blind-paper miss -> same paper edited and rerun as blind
```

Allowed deterministic code:

```text
typed enum validation
numeric conversion after model nomination
source-span grounding
Canonical aliases
candidate/image ordinal binding
batch_size_hint validation
state legality and CAS
product-fact and safety evaluation
presentation slot ownership
```

Provider-backed semantic execution must not call legacy action parsers. Tests
must monkeypatch those parsers to fail if the provider path invokes them.

### 1.2 Earliest-layer diagnosis

Every failure receives exactly one earliest responsibility layer:

```text
model_translation
semantic_admission
identity_binding
route_selection
state_transition
decision_execution
data_coverage
public_presentation
browser_renderer
```

Stop diagnosis at the first incorrect layer. Do not repair downstream symptoms
before that layer is correct.

### 1.3 Mechanical anti-patch gate

Every repair must name:

```text
observed failure
unique earliest layer
finite parent operation or parent concept
source-grounded typed atom
code/data owner after translation
at least two wording variants with the same parent meaning
at least one negative case that must not map to that parent
```

If `model_translation` is wrong, repair a general parent-operation rule in the
Prompt and probe multiple unseen phrasings. Do not paste the failed sentence
or a synonym list into the Prompt.

If any code layer after translation is wrong, production code may inspect only
typed atoms, Canonical identity, deterministic numeric values, or state. It
must not inspect the raw user message to decide an open-language action.

For every semantic production diff, run:

```bash
git diff -U0 -- app/guide \
  | rg '^\+.*(re\.compile|re\.search|re\.match|关键词|同义词)'
```

Every hit must be either:

```text
pre-existing unchanged context
closed protocol/numeric syntax with a documented typed owner
test-only evidence
```

Any new action/intent wording regex, keyword list, product-ID branch, or
fixture-message literal fails the repair and must be removed.

Provider-path tests must monkeypatch legacy action parsers to raise. A repair
is not GREEN merely because the observed question passes; the wording
variants, negative case, provider-parser isolation test, and zero-API replay
must all pass.

### 1.4 Serious failures

These are zero-tolerance:

```text
wrong product binding
wrong image binding
unauthorized state transition
hard-condition override
unsafe downgrade
cross-session leakage
state corruption or version drift
high-confidence wrong image identity
```

An ordinary semantic, route, data, or presentation miss is scored and the
blind exam continues. A serious failure aborts the current paid command,
preserves evidence, starts zero-API diagnosis, and then follows the automatic
repair/replay/resume loop. It does not create a permission checkpoint.

The only allowed overall execution stops before browser acceptance are:

```text
projected or actual cumulative spend reaches CNY 28
credentials are absent or invalid and cannot be recovered locally
provider/runtime infrastructure remains unavailable after three bounded checks
product or image ground truth cannot be independently established
Blind B finishes below the agreed backend threshold
```

Code difficulty, ordinary test failure, blind score failure, or a discovered
shared architecture defect are not stop conditions before Blind B. A failed
Blind B is the single score-related discussion checkpoint because no Blind C
is authorized.

## 2. Old-Question Audit Policy

The historical pool, fixed exercises, real captures, zero-API captures, old
Blind A/B, and old blind pool are all **seen material**.

Current seen-message ledger:

```text
docs/audits/continuous-conversation/seen-message-ledger-v1.json
unique normalized seen messages = 1106
ledger sha256 =
701b25f64cac0ea081c44bb8b42ffcd0723340db83236a0b6e51a39d7779b2fc
```

Old questions are audited only for:

```text
wording-level regex or parser authority
missing finite parent concept
shared source-admission defect
wrong Canonical product/image binding
state contamination
public-presentation information loss
```

Do not repair:

```text
stale product IDs
old two-card assumptions after production moved to three cards
safe equivalent clarification wording
ordinary model variation that stays inside the typed contract
```

The historical `5 x 5` sample already established one valid shared defect:

```text
visible candidates = 3
user requested an explicit batch of 2
old behavior = silently bind all 3
current typed behavior = batch_size_hint=2 -> ambiguous clarification
```

That issue is closed by the typed batch contract. Do not invent a number-word
regex or revert the three-card product behavior.

## 3. Final Presentation Truth

The presentation audit is not satisfied by checking that a DOM node exists.
It must prove that each approved fact reaches the correct public hierarchy.

### 3.1 Fact ownership

```text
Canonical/category/selection/merchant/review fact
  -> approved_soft_fact | locked_fact | direct_caution
  -> positioning | direct_facts | advisor_reason | pitfalls
  -> PresentationSection
  -> Guide renderer DOM
```

Slot duties:

| Slot | Owns | Must not own |
|---|---|---|
| `summary` | overall judgment, budget value, route tradeoff, scenario | raw source wall, internal ranking |
| `positioning` | brand direction, approved efficacy, core ingredient, texture, broad suitable-skin fact | price/spec, invented match claim |
| `direct_facts` | reference price, exact specification, known core ingredients, known suitable skin, approved numeric proof point | model paraphrase |
| `advisor_reason` | relationship to this user's need, skin, budget, or use scenario | generic fact dump, product identity invention |
| `closing` | primary choice, alternative, and scenario switch | repeated summary, internal algorithm |
| `pitfalls` | actionable code-owned warning | raw evidence list, generic filler |

Facts with state `unknown`, `conflict`, or `not_applicable` are omitted. The
frontend must not display placeholders such as:

```text
未限定肤质
当前未核验
信息不足以填充本行
```

### 3.2 Richness And Safety Boundary

The afternoon decision is authoritative:

```text
approved efficacy may be rewritten naturally
approved ingredients may be rewritten naturally
approved texture and finish may be rewritten naturally
approved suitable-skin facts may be rewritten naturally
approved merchant numbers, duration, and claims may be rewritten with their
attribution intact
price and exact specification remain direct code-owned rows
```

The system is a shopping advisor, not a medical record generator. Validation
must block only:

```text
invented facts
wrong product ownership
changed number or specification
lost merchant/consumer attribution
absolute safety guarantees
medical diagnosis or treatment claims
internal system language
```

Do not reintroduce broad "safety" rejection that removes already approved
product facts merely because they contain an ingredient, efficacy, duration,
or merchant claim. A rich approved paragraph is a successful result, not a
validation risk.

### 3.3 Final recommendation format

Exact order:

```text
human summary

product title
unchanged G inline card
positioning / 品牌主打
direct facts
小 ro 的推荐理由

next products in the same shape

综合推荐 / closing
full product shelf
compact pitfalls
```

Visual freeze:

```text
standalone product title = rose
"小 ro 的推荐理由：" label = rose
normal prose, including product references = ordinary text color
G inline card structure and internal colors = unchanged
full shelf remains after closing
pitfalls remain after full shelf
```

### 3.4 Mode-specific duties

| Public mode | Required public structure |
|---|---|
| `recommendation` | summary -> products -> closing -> full shelf -> pitfalls |
| `revision` | updated summary -> new products -> closing -> full shelf -> pitfalls |
| `comparison` | summary -> comparison table -> products -> closing -> full shelf -> pitfalls |
| `product_knowledge` | bound product -> direct answer -> full shelf; no recommendation reason and no closing |
| `general_knowledge` | one direct knowledge body; zero cards |
| `consultation` | current observation/question/safety body; zero cards until a real recommendation task begins |
| `image_identity` | confirmed identity only; uncertainty clarifies; no guessed product |
| image recommendation | ordinary recommendation hierarchy, anchored by confirmed image identity |
| image suitability | ordinary product-knowledge/suitability hierarchy for one explicitly bound image |
| image comparison | ordinary comparison hierarchy in explicit image ordinal order |
| `clarification` | one clear question; zero cards |
| `error` | one actionable public error; zero cards |

Images are not an independent thin answer system. After identity binding they
reuse ordinary recommendation, product-knowledge, suitability, comparison,
fact projection, and presentation rules.

### 3.5 Known audit targets to prove before any paid exam

The following are hypotheses from read-only inspection, not approved fixes:

1. Recommendation card construction merges direct Canonical fields, while
   some product-knowledge, follow-up, image identity, image suitability, and
   image comparison paths rebuild `ProductCard` separately. Verify whether
   known `efficacy`, `ingredients_present`, and `suitable_skin` disappear on
   those paths.
2. Guide image turns may still flush legacy image-observation or suitability
   panels after a structured `presentation_contract`. Verify and remove only
   confirmed duplicate ownership.
3. Product references inside ordinary prose currently inherit rose styling.
   Verify against the visual freeze and scope rose to the product heading and
   recommendation label only.
4. The historical `frontend_mode_matrix_v1.jsonl` is superseded and does not
   express current product-knowledge/general-knowledge section truth. Replace
   it with a current matrix; do not bend runtime behavior to the old fixture.
5. `guide-presentation-copy-prompt-v6` has not yet received a fresh official
   20-packet real-provider qualification. The old v5 pass is historical only.
6. `copywriter_validation.py` currently authorizes numeric fragments in
   `efficacy` and `ingredients_present` soft facts, but another approved
   narrative field such as `finish` may still be rejected merely because it
   contains a duration. Verify exact approved numeric fragments by slot and
   fact ID; keep changed or invented numbers rejected.

## 4. Cost, Calls, Durability, And Stop Conditions

Hard cost stop:

```text
CNY 28 cumulative for this acceptance effort
```

Provider policy:

```text
semantic retry = 0
semantic format repair = 0
copywriter retry = 0
copywriter format repair = 0
```

Expected new paid calls:

```text
copywriter qualification = 20
Blind A semantic = 100
Blind B semantic = 0 unless A is invalidated
Blind B conditional maximum = 100
browser semantic = 15
browser copywriter = determined by the frozen mode matrix; use the real
copywriter on every eligible turn
```

Before each paid phase, record:

```text
prior call count
requested call count
reserved future calls
estimated CNY
current code/prompt/fixture hashes
```

After each provider attempt, atomically persist:

```text
raw output
typed output or failure code
input/context hash
prompt version
token counts
latency
earliest failure layer
partial summary
```

Every paid or browser task below contains its exact bounded command. Each
command derives a fresh timestamp:

```bash
RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
```

Use that value in every `/private/tmp` log and summary path. Never reuse stale
logs.

## Task 1: Freeze The Audit Baseline

**Files:**
- Verify:
  `docs/audits/continuous-conversation/seen-message-ledger-v1.json`
- Create:
  `docs/audits/continuous-conversation/overnight-baseline-v1.json`
- Create:
  `docs/audits/continuous-conversation/old-question-decision-v1.md`
- Create:
  `docs/audits/continuous-conversation/night-run-control-amendment-v4.json`

- [ ] **Step 1: Verify no accidental planning-phase code edit remains**

Run:

```bash
git status --short
git diff --check
git diff --exit-code -- \
  tests/guide/application/test_image_presentation_integration.py \
  tests/guide/application/test_text_presentation_integration.py
```

Expected: the two interrupted RED-test files have no diff; pre-existing dirty
worktree changes remain untouched.

- [ ] **Step 2: Record the CNY 28 amendment**

Update only the cost and current policy fields:

```json
{
  "hard_cost_stop_cny": 28,
  "provider_retry_count": 0,
  "format_repair_attempts": 0,
  "old_question_policy": "shared_architecture_audit_only",
  "blind_a_may_be_invalidated_once": true,
  "maximum_blind_exams": 2
}
```

- [ ] **Step 3: Freeze baseline hashes**

Record SHA-256 for:

```text
app/guide/adapters/llm/turn_meaning_prompt.py
app/guide/presentation/copywriter_prompt.py
app/guide/understanding/turn_meaning_contracts.py
app/guide/intent/unified_turn_router.py
app/guide/presentation/presentation_packet.py
app/guide/presentation/presentation_compiler.py
app/static/guide-presentation.js
app/static/chat.html
seen-message-ledger-v1.json
```

- [ ] **Step 4: Write the old-question decision**

The document must classify every reviewed old failure as one of:

```text
shared_architecture_defect
stale_fixture
ordinary_model_variation
serious_binding_or_state_failure
```

It must explicitly state:

```text
no new 100-turn exercise run
no stale product-ID repair
no old two-card assumption repair
no wording-level semantic patch
```

## Task 2: Audit And Close Presentation Responsibility

**Files:**
- Create:
  `docs/audits/continuous-conversation/presentation-slot-responsibility-audit-v1.md`
- Create:
  `docs/audits/continuous-conversation/presentation-mode-matrix-v2.json`
- Create:
  `app/guide/presentation/fact_admission.py`
- Create:
  `tools/guide_data/audit_presentation_fact_admission.py`
- Create:
  `tests/guide/presentation/test_fact_admission.py`
- Create:
  `tests/guide/tools/test_audit_presentation_fact_admission.py`
- Create:
  `docs/audits/continuous-conversation/presentation-fact-admission-v1.json`
- Modify if RED confirms shared projection loss:
  `app/guide/presentation/response_planning.py`
- Modify if RED confirms duplicate card construction:
  `app/guide/presentation/followup_response.py`
- Modify if RED confirms duplicate card construction:
  `app/guide/application/text_recommendation_flow.py`
- Modify if RED confirms duplicate card construction:
  `app/guide/application/image_recommendation_flow.py`
- Test:
  `tests/guide/presentation/test_response_planning.py`
- Test:
  `tests/guide/presentation/test_followup_response.py`
- Test:
  `tests/guide/application/test_text_presentation_integration.py`
- Test:
  `tests/guide/application/test_image_presentation_integration.py`

- [ ] **Step 1: Write the responsibility matrix before code**

For every mode in Section 3.3, record:

```text
source fact
fact state
packet ownership
copywriter slot
compiled section
frontend selector
omission rule
```

- [ ] **Step 2: Inventory every production display fact**

Build one zero-API row for every fact available to presentation from:

```text
Canonical direct product fields
category facts
selection and concept facts
production merchant claims
approved review summaries
pitfalls and safety claims
```

Each row must contain:

```python
class FactAdmissionAuditRow(BaseModel):
    product_id: int
    source_kind: str
    field_key: str
    attribution: FactAttribution
    allowed_use: str
    source_refs: tuple[str, ...]
    plain_meaning: str
    disposition: Literal[
        "positioning",
        "direct_fact",
        "caution",
        "excluded",
    ]
    reason_code: str
    packet_fact_id: str | None
```

The audit summary must report:

```text
approved eligible fact count
positioning fact count
direct-fact count
caution count
excluded count by reason
field-whitelist-only drop count
validator-only drop count
facts present in packet
facts selected into narrative atoms
```

Acceptance:

```text
unexplained approved-fact drops = 0
field-whitelist-only drops = 0
wrong product attribution = 0
facts without source refs admitted = 0
```

An excluded row is acceptable only for an explicit reason such as unreviewed
source, identity ambiguity, medical/absolute language, expired promotion, or
irrelevant raw evidence. "The field is not in a handwritten whitelist" is not
an acceptable reason by itself.

- [ ] **Step 3: Write RED for shared ProductCard projection**

Use Canonical product `38`, whose current known direct fields include efficacy,
ingredients, and suitable skin. Assert the same public facts survive in:

```text
ordinary recommendation
product knowledge
follow-up card
confirmed image identity
image suitability
image comparison
```

The invariant is:

```python
known_fields = {
    fact.field_key
    for fact in card.category_facts
    if fact.state == "known"
}
assert {
    "efficacy",
    "ingredients_present",
    "suitable_skin",
} <= known_fields
```

- [ ] **Step 4: Run RED**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/guide/presentation/test_response_planning.py \
  tests/guide/presentation/test_fact_admission.py \
  tests/guide/presentation/test_followup_response.py \
  tests/guide/application/test_text_presentation_integration.py \
  tests/guide/application/test_image_presentation_integration.py \
  tests/guide/tools/test_audit_presentation_fact_admission.py
```

Expected: only paths that independently rebuild a thin card fail.

- [ ] **Step 5: Introduce one public card projector**

If Step 4 confirms the hypothesis, create one shared function in
`response_planning.py`:

```python
def build_product_card(
    facts: ProductCardFacts,
    *,
    skin_match: Literal["matched", "unknown", "not_applicable"],
    matched_efficacies: Sequence[str] = (),
) -> ProductCard:
    return ProductCard(
        product_id=facts.product_id,
        category_profile=facts.category_profile,
        category_facts=merge_direct_display_facts(
            project_public_category_facts(facts.category_fields),
            facts,
        ),
        variant_scope=facts.variant_scope,
        specification=facts.specification,
        name=facts.name,
        brand=facts.brand,
        category=facts.category,
        price=facts.price,
        image_url=facts.image_url,
        detail_url=facts.detail_url,
        platform=facts.platform,
        image_source_sha256=facts.image_source_sha256,
        skin_match=skin_match,
        matched_efficacies=list(matched_efficacies),
        fact_warnings=list(facts.fact_warnings),
    )
```

Every confirmed call site must use this function. Do not add per-mode fact
lists.

- [ ] **Step 6: Run GREEN**

Run the Step 4 command.

Expected: PASS, with identical product order and card identity.

- [ ] **Step 7: Verify copywriter slot hierarchy**

For a rich recommendation packet, assert:

```text
positioning uses approved efficacy/ingredient/texture/suitable-skin facts
direct_facts contains exact price/spec/known ingredient/known suitable skin
advisor_reason relates the product to the user's current need
pitfalls remain code-owned
```

Also write a paired numeric-authorization test:

```python
def test_exact_number_from_any_approved_narrative_fact_is_allowed():
    packet = _packet(
        soft_facts=(
            _soft_fact(
                "soft-finish",
                attribution="merchant_claim",
                field_key="finish",
                plain_meaning="品牌主打：24小时不暗沉柔雾妆效",
            ),
        )
    )
    draft = _draft(
        positioning="品牌主打24小时不暗沉的柔雾妆效。",
        reason="适合更看重通勤持妆观感的人比较。",
        used_fact_ids=("soft-finish",),
    )

    assert validate_copywriter_draft(packet, draft) == draft


def test_changed_number_from_approved_fact_is_rejected():
    packet = _packet(
        soft_facts=(
            _soft_fact(
                "soft-finish",
                attribution="merchant_claim",
                field_key="finish",
                plain_meaning="品牌主打：24小时不暗沉柔雾妆效",
            ),
        )
    )
    draft = _draft(
        positioning="品牌主打48小时不暗沉的柔雾妆效。",
        reason="适合更看重通勤持妆观感的人比较。",
        used_fact_ids=("soft-finish",),
    )

    _invalid(packet, draft, CopywriterValidationErrorCode.HARD_FACT)
```

If the first test is RED, replace the narrow field-name whitelist with
same-slot approved-fact fragment authorization. Do not disable numeric
validation globally.

For a product with at least four eligible, relevant narrative dimensions,
require:

```text
packet narrative atoms = 4 to 7 when the data supports them
real copywriter used_fact_ids coverage >= 80%
at least three complementary dimensions remain visible in positioning
```

The upper bound prevents an evidence wall. The lower bound prevents approved
production data from collapsing into one generic sentence.

Do not increase validation merely to force longer prose. Richness is qualified
by the real copywriter gate and browser assertions, not by a brittle character
count patch.

## Task 3: Freeze The Final Frontend Renderer Contract

**Files:**
- Modify if RED confirms:
  `app/static/guide-presentation.js`
- Modify if RED confirms:
  `app/static/chat.html`
- Create:
  `tests/fixtures/guide/presentation/frontend_mode_matrix_v2.jsonl`
- Modify:
  `tests/guide/runtime/test_frontend_mode_matrix.py`
- Modify:
  `tests/guide/runtime/test_frontend_mode_rendering.py`
- Modify:
  `tests/guide/runtime/test_frontend_presentation_stream.py`
- Modify:
  `tests/guide/runtime/test_frontend_card_binding.py`

- [ ] **Step 1: Write RED for renderer ownership**

Assert:

```text
structured Guide presentation renders the main answer once
Guide image turns do not append legacy image-observation/suitability panels
full shelf renders once after closing
pitfalls render once after full shelf
mode switches leave no previous-turn card
```

- [ ] **Step 2: Write RED for exact rose scope**

Assert:

```text
.guide-presentation-product h3 = rose
.guide-product-advisor-reason strong = rose
.guide-product-ref = ordinary text color at rest
G inline card class list and child order are unchanged
```

The public label remains exactly:

```text
小 ro 的推荐理由：
```

- [ ] **Step 3: Remove only confirmed duplicate legacy ownership**

If RED confirms duplicate image panels, gate them with the same structured
contract ownership used by consultation:

```javascript
const guideOwnsPresentation = (
    GUIDE_RUNTIME_MODE
    && Boolean(deferredPanels.presentationContract)
);
if (!guideOwnsPresentation) {
    flushLegacyImagePanels();
}
```

Do not remove image observations from SSE, state, citations, or backend
evidence. Remove only duplicate public rendering.

- [ ] **Step 4: Scope ordinary product references**

Use ordinary color at rest:

```css
.guide-product-ref {
    color: inherit;
}

.guide-product-ref:hover,
.guide-product-ref:focus-visible {
    color: var(--primary-deep);
}
```

Keep a visible focus indicator. Do not use `outline: none` without a
replacement.

- [ ] **Step 5: Publish current mode matrix v2**

The matrix must encode current truth, including:

```text
product_knowledge = product -> direct_answer -> full_cards
general_knowledge = general_knowledge
consultation = observation/question/safety, zero cards
image recommendation = normal recommendation hierarchy
image suitability = normal suitability/product-knowledge hierarchy
image comparison = normal comparison hierarchy
```

Do not modify production to satisfy superseded v1 rows.

- [ ] **Step 6: Keep tonight's frontend scope on the approved format**

Required before release:

```text
all product images have intrinsic width/height
below-fold full-shelf images use loading="lazy"
long names and pitfalls wrap without horizontal overflow
desktop and mobile screenshots show no overlap or clipping
```

Do not expand tonight's work into unrelated feedback-modal accessibility,
global `transition: all` cleanup, sidebar redesign, or general page-shell
refactoring. Record those as non-blocking follow-up findings only.

- [ ] **Step 7: Run frontend GREEN**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/guide/runtime/test_frontend_mode_matrix.py \
  tests/guide/runtime/test_frontend_mode_rendering.py \
  tests/guide/runtime/test_frontend_presentation_stream.py \
  tests/guide/runtime/test_frontend_card_binding.py \
  tests/guide/runtime/test_frontend_presentation_history.py \
  tests/guide/runtime/test_frontend_presentation_reducer.py \
  tests/guide/runtime/test_frontend_presentation_xss.py
node --check app/static/guide-presentation.js
```

Expected: PASS, one owner per public section.

## Task 4: Qualify Current Copywriter Prompt v6

**Files:**
- Create:
  `tests/fixtures/guide/presentation/copy_gate_v3_production.jsonl`
- Create:
  `tests/fixtures/guide/presentation/copy_gate_v3_production_manifest.json`
- Verify:
  `tools/guide_gates/presentation_copy_gate.py`
- Verify:
  `tools/guide_gates/run_real_presentation_copy_gate.py`
- Create:
  `docs/audits/continuous-conversation/copywriter-20-v3/`
- Create:
  `docs/audits/continuous-conversation/copywriter-20-v3-decision.json`

- [ ] **Step 1: Run zero-API gate tests**

First freeze 20 reviewed packets built from the real production fact inventory,
not invented copy examples. They must cover rich recommendation, comparison,
product knowledge, general knowledge, consultation, and image modes.

Run:

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/guide/presentation \
  tests/guide/tools/test_presentation_copy_gate.py \
  tests/guide/tools/test_run_real_presentation_copy_gate.py
```

Expected: PASS.

- [ ] **Step 2: Confirm current Prompt version**

Required:

```text
PRESENTATION_COPY_PROMPT_VERSION =
guide-presentation-copy-prompt-v6
```

Do not count the historical v5 qualification as a v6 pass.

- [ ] **Step 3: Run the bounded real 20-packet gate**

Use one provider call per packet, retry `0`, max tokens equal to production.

Run:

```bash
RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
PYTHONPATH=. .venv/bin/python \
  -m tools.guide_gates.run_bounded_command \
  --timeout-seconds 1800 \
  --heartbeat-seconds 30 \
  --output "/private/tmp/xiaoro-copy-v3-${RUN_TS}.log" \
  --summary "/private/tmp/xiaoro-copy-v3-${RUN_TS}.json" \
  -- \
  .venv/bin/python \
  -m tools.guide_gates.run_real_presentation_copy_gate \
  --cases \
    tests/fixtures/guide/presentation/copy_gate_v3_production.jsonl \
  --output-dir \
    docs/audits/continuous-conversation/copywriter-20-v3 \
  --run-id copywriter-20-v3 \
  --prior-call-count 40 \
  --copywriter-call-cap 75 \
  --reserved-future-calls 15
```

Required result:

```text
provider calls = 20
usable presentation packets >= 18
readability passes >= 18
fact coverage passes >= 18
minimum used-fact coverage per passing rich slot >= 80%
internal language pass = 20
wrong slot/product ownership = 0
invented or changed hard facts = 0
lost merchant/consumer attribution = 0
hard violations = 0
```

- [ ] **Step 4: Score ordinary misses without prompt whack-a-mole**

One or two ordinary wording/schema misses are scored, not automatically used
to tune the Prompt. If the gate is below `18/20` or has any hard violation:

1. freeze all 20 outputs;
2. identify `packet_truth`, `prompt_responsibility`,
   `validator_overreach`, or `provider_schema`;
3. repair only the shared responsibility under TDD;
4. replay all saved outputs with zero API;
5. do not run another real copywriter batch unless current v6 outputs cannot
   represent the corrected contract.

## Task 5: Find And Ground Real Product Images

**Files:**
- Create:
  `docs/audits/continuous-conversation/real-image-ground-truth-v1.json`
- Create directory:
  `docs/audits/continuous-conversation/real-image-ground-truth-v1/`
- Verify:
  `data/guide_image_index/`
- Verify:
  `app/static/product-images/`

- [ ] **Step 1: Select three real-image duties**

Required:

```text
one clear non-index product photo
one real photo with background, angle, or crop
one two-image upload using two independently grounded products
```

- [ ] **Step 2: Establish ground truth before upload**

For every image, record:

```text
source URL
download timestamp
local SHA-256
expected Canonical product ID
expected full product name
visible packaging evidence
whether the image is cropped/angled/backgrounded
```

- [ ] **Step 3: Prove images are not index duplicates**

Compare each source SHA-256 with:

```text
image index source hashes
app/static/product-images hashes
seed image hashes
```

At least the clear and background/angle images must be non-index hashes.

- [ ] **Step 4: Freeze image acceptance**

Allowed outcomes:

```text
high-confidence correct identity
honest low-confidence/ambiguous clarification
```

Forbidden:

```text
high-confidence wrong product
silent ordinal swap
two images automatically treated as comparison without user intent
image upload changing the unrelated current product
```

## Task 6: Run Final Zero-API Regression And Freeze The System

**Files:**
- Create:
  `docs/audits/continuous-conversation/overnight-freeze-v1.json`

- [ ] **Step 1: Run focused regression**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/guide/understanding \
  tests/guide/intent \
  tests/guide/feedback \
  tests/guide/application \
  tests/guide/presentation \
  tests/guide/runtime \
  tests/guide/tools/test_continuous_conversation_fixture.py \
  tests/guide/tools/test_continuous_conversation_blind_fixture.py \
  tests/guide/tools/test_continuous_conversation_runtime.py \
  tests/guide/tools/test_run_real_continuous_conversation_gate.py \
  tests/guide/tools/test_run_real_presentation_copy_gate.py \
  tests/guide/tools/test_continuous_conversation_browser_audit.py
```

Expected: PASS.

- [ ] **Step 2: Run static checks**

Run:

```bash
git diff --check
PYTHONPATH=. .venv/bin/python -m compileall -q app tools tests
node --check app/static/guide-presentation.js
```

Expected: no error.

- [ ] **Step 3: Freeze system hashes**

Record:

```text
git HEAD
dirty diff hash
TurnMeaning Prompt version/hash
copywriter Prompt version/hash
Canonical product manifest hash
selection concept manifest hash
image index manifest hash
presentation mode matrix hash
real-image ground-truth hash
seen-message ledger hash
```

No production, Prompt, fixture, or data edit is allowed after this point
without invalidating the current blind paper.

## Task 7: Create And Seal New Blind A/B

**Files:**
- Create:
  `tests/fixtures/guide/conversation/continuous_blind_a_20x5_v2.jsonl`
- Create:
  `tests/fixtures/guide/conversation/continuous_blind_a_20x5_v2_manifest.json`
- Create:
  `tests/fixtures/guide/conversation/continuous_blind_b_20x5_v2.jsonl`
- Create:
  `tests/fixtures/guide/conversation/continuous_blind_b_20x5_v2_manifest.json`
- Create:
  `docs/audits/continuous-conversation/blind-v2-seal.json`

- [ ] **Step 1: Author two independent self-only papers**

Each paper:

```text
20 trajectories
5 turns each
100 turns total
self-only subject scope
natural difficulty distribution
no third-person profile duties
```

Collective coverage in each paper:

```text
recommendation and revision
product follow-up and focus return
general-knowledge detour
comparison
consultation correction and safety
pending confirmation/correction/rejection
ambiguous and explicit product references
image identity/suitability/recommendation/comparison
batch-size mismatch clarification
```

Most turns should be ordinary natural user language. Do not make every turn a
maximally tangled sentence.

- [ ] **Step 2: Validate unseen and disjoint status**

Normalize each message with the same ledger normalizer and assert:

```python
assert blind_a_messages.isdisjoint(seen_messages)
assert blind_b_messages.isdisjoint(seen_messages)
assert blind_a_messages.isdisjoint(blind_b_messages)
assert len(blind_a_messages) == 100
assert len(blind_b_messages) == 100
```

- [ ] **Step 3: Validate fixture truth at zero API**

Verify:

```text
product IDs exist
prices and hard conditions match Canonical data
image ordinals are in range
expected route and state duties are internally consistent
presentation mode duties use matrix v2
```

- [ ] **Step 4: Seal without previewing exam text**

Publish only:

```text
paper hash
manifest hash
trajectory count
turn count
coverage counts
disjointness result
```

Do not print question bodies in chat or the freeze report.

## Task 8: Run Blind A

**Files:**
- Create:
  `docs/audits/continuous-conversation/backend-blind-a-20x5-v2/`
- Create:
  `docs/audits/continuous-conversation/blind-exam-decision-v2.json`

- [ ] **Step 1: Recheck the seal**

Before the first call, verify all Task 6 and Task 7 hashes are unchanged.

- [ ] **Step 2: Run bounded Blind A**

Configuration:

```text
real TurnMeaning provider
copywriter disabled
100 semantic calls maximum
retry 0
format repair 0
per-turn atomic persistence
30-second heartbeat
```

Run:

```bash
RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
PYTHONPATH=. .venv/bin/python \
  -m tools.guide_gates.run_bounded_command \
  --timeout-seconds 7200 \
  --heartbeat-seconds 30 \
  --output "/private/tmp/xiaoro-blind-a-v2-${RUN_TS}.log" \
  --summary "/private/tmp/xiaoro-blind-a-v2-${RUN_TS}.json" \
  -- \
  .venv/bin/python \
  -m tools.guide_gates.run_real_continuous_conversation_gate \
  --cases \
    tests/fixtures/guide/conversation/continuous_blind_a_20x5_v2.jsonl \
  --manifest \
    tests/fixtures/guide/conversation/continuous_blind_a_20x5_v2_manifest.json \
  --output \
    docs/audits/continuous-conversation/backend-blind-a-20x5-v2/result.json \
  --disable-copywriter
```

- [ ] **Step 3: Score without mid-paper repair**

Pass only when:

```text
attempted turns = 100
passed turns >= 90
passed complete trajectories >= 18
all serious counters = 0
```

Ordinary failures continue. Serious failures abort only the active paid
command, then automatically enter the zero-API earliest-layer
repair/replay/resume loop from Section 1.

- [ ] **Step 4: Decide A**

If A passes, freeze it as the final backend decision and do not open B.

If A fails:

```text
A status = invalidated_to_exercise
B remains sealed
```

Only then inspect A failures and continue directly into Task 9. Do not pause
for another user decision.

## Task 9: Conditional Shared Repair And Blind B

**Files:**
- Conditionally create:
  `docs/audits/continuous-conversation/backend-blind-a-zero-api-replay-v2.json`
- Conditionally create:
  `docs/audits/continuous-conversation/backend-blind-b-20x5-v2/`

- [ ] **Step 1: Diagnose all A failures**

For each failure, preserve:

```text
message
typed context
raw model output
admission
binding
route
state
decision
presentation
earliest layer
```

- [ ] **Step 2: Repair only shared architecture**

Each behavior change requires:

```text
RED test over at least two wording variants
minimal shared-layer implementation
focused GREEN
zero-API replay of all captured A turns
```

Do not copy A wording into Prompt examples, keyword lists, or regexes.

- [ ] **Step 3: Re-freeze code and open B once**

Run B under the same scoring and stop rules as A.

Run:

```bash
RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
PYTHONPATH=. .venv/bin/python \
  -m tools.guide_gates.run_bounded_command \
  --timeout-seconds 7200 \
  --heartbeat-seconds 30 \
  --output "/private/tmp/xiaoro-blind-b-v2-${RUN_TS}.log" \
  --summary "/private/tmp/xiaoro-blind-b-v2-${RUN_TS}.json" \
  -- \
  .venv/bin/python \
  -m tools.guide_gates.run_real_continuous_conversation_gate \
  --cases \
    tests/fixtures/guide/conversation/continuous_blind_b_20x5_v2.jsonl \
  --manifest \
    tests/fixtures/guide/conversation/continuous_blind_b_20x5_v2_manifest.json \
  --output \
    docs/audits/continuous-conversation/backend-blind-b-20x5-v2/result.json \
  --disable-copywriter
```

No third paper is allowed. If B finishes below `90/100`, below `18/20`
complete trajectories, or with a serious counter above zero:

1. freeze the complete B evidence;
2. mark backend blind qualification as failed;
3. do not generate Blind C;
4. do not release;
5. classify the result using the decision table below;
6. stop at this single approved checkpoint and discuss the failure classes
   with the user before deciding whether browser evidence is still useful.

| B failure class | Meaning | Required action |
|---|---|---|
| provider/infrastructure invalid | timeout, auth, outage, or no valid provider response | Do not score as model quality; resume only unconsumed calls from atomic capture after infrastructure is healthy. |
| exam truth invalid | stale product ID/count, false hard-condition expectation, or internally inconsistent state duty | Correct fixture truth and re-score saved outputs at zero API. If the paper is broadly compromised, discuss whether a replacement paper is justified. |
| model translation miss | wrong parent operation/concept/reference before admission | Group misses by finite parent concept. Repair only a shared Prompt contract; do not copy B wording. B becomes exercise evidence and cannot certify the repaired Prompt. |
| deterministic code defect | model atom is correct but admission, binding, Router, state, decision, or presentation is wrong | Repair the earliest shared typed layer under TDD and replay B at zero API. Independent qualification remains absent until the user decides the next policy. |
| data coverage gap | required Canonical fact is absent, conflicting, or stale | Add reviewed data only when a source exists; otherwise keep fail-closed unknown/clarification and correct any false exam expectation. |
| public copy/renderer defect | semantic and product result are correct but facts are thin, rejected, duplicated, or misplaced | Repair packet/validator/renderer ownership and rerun copy/browser gates; do not change semantic Prompt. |
| serious binding/state/safety failure | wrong product/image, state corruption, hard-condition override, or unsafe downgrade | Release is blocked. Repair is mandatory; no threshold discussion can waive it. |

## Task 10: Run Real `/chat` Browser `3 x 5`

**Files:**
- Verify:
  `tools/guide_gates/continuous_conversation_browser_audit.py`
- Verify:
  `tests/guide/tools/test_continuous_conversation_browser_audit.py`
- Create:
  `tools/guide_gates/run_real_continuous_conversation_browser_audit.py`
- Create:
  `tests/guide/tools/test_run_real_continuous_conversation_browser_audit.py`
- Create:
  `docs/audits/continuous-conversation/browser-real-3x5-v2.json`
- Create directory:
  `docs/audits/continuous-conversation/browser-real-3x5-v2/`

- [ ] **Step 1: Start a clean real runtime**

Required:

```text
page = /chat
/demo is invalid
GUIDE_UNIFIED_ROUTER_ENABLED=true
real semantic provider
real copywriter
semantic retry=0
copywriter retry=0
```

- [ ] **Step 2: Run the product-focus trajectory**

```text
recommendation
-> product follow-up
-> general-knowledge detour
-> return to original product
-> comparison
```

- [ ] **Step 3: Run the consultation trajectory**

```text
consultation
-> correction
-> product interruption
-> return to consultation
-> safety escalation
```

- [ ] **Step 4: Run the real-image trajectory**

```text
upload two independently grounded real images together
-> ambiguous image reference
-> explicit image ordinal suitability
-> image-anchored recommendation
-> return to original product
```

The two uploaded images must be:

```text
one clear non-index product photo
one non-index photo with background, angle, or crop
```

This keeps the real-image and two-image duties inside the same five-turn
trajectory rather than adding another browser run.

- [ ] **Step 5: Verify every terminal turn**

Required:

```text
correct processor and presentation mode
correct conversation version increment
correct inline and full-card identities
real copywriter is used on every copywriter-eligible turn
approved facts remain rich after copywriting
for a data-rich product, at least three approved complementary dimensions are
visible across positioning and direct facts
no approved fact disappears solely because its field is outside a handwritten
whitelist or because it contains an approved numeric fragment
no unexpected fallback on a copywriter-eligible turn
deterministic clarification or medical-safety copy is allowed when that mode
intentionally does not delegate wording
no stale cards or legacy duplicate panels
all images load
no console or relevant network error
no overlap, clipping, or horizontal overflow
thinking advances at 1 second and leaves on first answer character
final rose scope is exact
presentation slot hierarchy is complete
```

Run desktop:

```text
1440 x 900
```

Run mobile visual verification:

```text
390 x 844
```

Take one terminal screenshot per turn and preserve SSE/DOM/console/network
evidence.

Final browser requirement:

```text
trajectories = 3/3
turns = 15/15
semantic calls = 15
copywriter calls = exact number of eligible turns observed from the frozen
mode matrix
unexpected fallbacks = 0
serious failures = 0
```

- [ ] **Step 6: Repair and resume browser failures without pausing**

For any failed browser turn:

1. save the screenshot, DOM, SSE, console, network, health, and active-request
   state;
2. assign the unique earliest layer, including `browser_renderer` only when
   every backend contract is correct;
3. write RED over the public contract or renderer invariant;
4. repair the shared owner, never the observed sentence or product ID;
5. run focused zero-API tests;
6. restart the affected five-turn trajectory from a clean session;
7. continue until the full browser result is `15/15` or an allowed hard stop
   from Section 1.4 is reached.

Do not stop after producing a browser finding. A finding is complete only when
the shared repair is GREEN and the real `/chat` trajectory passes.

## Task 11: Full Regression, Closure, And Release

**Files:**
- Create:
  `docs/audits/continuous-conversation/final-closure-2026-08-19.md`
- Create:
  `docs/audits/continuous-conversation/final-acceptance-summary-v2.json`
- Modify:
  `docs/audits/continuous-conversation/failure-ledger.md`

- [ ] **Step 1: Run the complete repository suite**

Run through the bounded wrapper:

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q
```

Expected: PASS with no new warning category.

- [ ] **Step 2: Run final static checks**

```bash
git diff --check
PYTHONPATH=. .venv/bin/python -m compileall -q app tools tests
node --check app/static/guide-presentation.js
```

Expected: no error.

- [ ] **Step 3: Publish the final acceptance table**

The closure report must include:

```text
old-question audit decision
presentation responsibility matrix
copywriter v6 score and hard-violation count
real-image ground truth and outcomes
Blind A or B final score
all zero-tolerance counters
browser 15/15 result
semantic/copywriter call counts
token counts and estimated CNY
code/prompt/data/fixture/output hashes
desktop/mobile screenshots
remaining non-blocking UI findings
```

- [ ] **Step 4: Release only after all gates pass**

Release condition:

```python
release_allowed = (
    copywriter_usable_count >= 18
    and copywriter_hard_violations == 0
    and blind_turns >= 90
    and blind_trajectories >= 18
    and zero_tolerance_total == 0
    and browser_turns == 15
    and browser_unexpected_fallbacks == 0
    and full_regression_passed
)
```

If false, do not claim completion and do not release.

If true:

1. review the exact final diff;
2. stage only acceptance-related files;
3. create one conventional commit;
4. push the `rebuild` branch;
5. use the repository's existing release mechanism;
6. record the commit, remote ref, deployment target, health result, and
   rollback point.

Never reset, checkout, stash, or overwrite unrelated dirty-worktree changes.

## Continuous Execution Endpoint

The user has already approved continuous execution. Start Task 1 after this
plan is synchronized.

Do not voluntarily stop before:

```text
real /chat browser trajectories have completed
browser rendering result is 15/15, or an allowed hard stop is proven
desktop and mobile evidence is preserved
final closure status truthfully records whether backend blind qualification
passed
```

The one score-related exception is a failed Blind B. Because no Blind C is
authorized, freeze B and return for discussion before browser execution.

After browser acceptance, continue directly through Task 11 regression,
closure, and conditional release. The first normal handoff point is the final
closure report, not an intermediate audit or backend checkpoint.
