# Double-Blind Copywriter and Frontend Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking. The user explicitly requires the
> main agent to execute all work; sub-agents are forbidden.

**Goal:** Build a locally runnable XiaoRo frontend that preserves the old
visual identity, uses a second blind model call for natural advisor copy,
renders hard facts deterministically, and displays exactly the product cards
authorized by typed backend contracts.

**Architecture:** The existing `TurnMeaning` call remains the only semantic
translator. Code completes binding, state, retrieval, safety, ranking, and
card selection, then builds an immutable `PresentationPacket`. A separate
copywriter sees only approved soft facts and opaque display slots, returns
mode-specific structured prose, and cannot change decisions or locked facts.
The frontend consumes a typed `presentation_contract`, renders old-style
three-part answers, inserts compact inline cards plus a final full-card shelf,
and removes the transient thinking panel at the first answer character.

**Tech Stack:** Python 3.11, Pydantic v2, FastAPI, typed SSE, vanilla
JavaScript, pytest, Node-based frontend contract tests, Playwright/browser
automation, SQLite CAS state, DeepSeek/SiliconFlow OpenAI-compatible JSON
adapters.

---

## Execution Rules

Work only in:

```text
/Users/bytedance/Desktop/xiaoro-fresh
branch: rebuild
```

Reference the old implementation only for behavior and aesthetics:

```text
/Users/bytedance/Desktop/xiaoro-shopping-master/app/static/chat.html
/Users/bytedance/Desktop/xiaoro-shopping-master/app/services/v2/presenter.py
/Users/bytedance/Desktop/xiaoro-shopping-master/app/services/v2/agent.py
/Users/bytedance/Desktop/xiaoro-shopping-master/app/services/v2/output_contract.py
```

When a display behavior is unclear:

1. locate the exact old frontend/presenter code;
2. locate its regression test;
3. run the old page in the built-in browser;
4. capture a screenshot;
5. record the observed behavior;
6. preserve the useful behavior, not the old business logic.

Do not:

- use sub-agents;
- add a third model, reviewer, repair call, or retry;
- allow copy to change product IDs, order, state, safety, or locked facts;
- copy the old phrase dictionaries or frontend ranking;
- rebuild the UI in React;
- redesign the established visual identity;
- deploy, switch traffic, or modify production configuration;
- crawl unrelated product pages;
- stage unrelated dirty files.

Use strict TDD. Every behavior change starts with a focused failing test.

After two failed fixes in the same layer:

1. stop prompt or validator tuning;
2. write an architecture checkpoint;
3. determine whether truth is false, the packet is incomplete, the validator
   is too strict, or the copywriter owns too much;
4. apply one general fix;
5. replay saved model output offline before another paid run.

Long-running commands start once and are polled until exit.

## File Map

### New backend files

```text
app/guide/presentation/copywriter_contracts.py
  Strict presentation packet, mode-specific copy, sections, facts, slots,
  telemetry, and fallback contracts.

app/guide/presentation/presentation_packet.py
  Converts final decision/card/evidence events into a compact immutable
  packet. Never calls a model.

app/guide/presentation/copywriter_prompt.py
  Provider-neutral system/user messages. Contains no fixture sentences.

app/guide/presentation/copywriter_validation.py
  Lightweight slot, fact-ID, numeric atom, product/ingredient, winner-language,
  and guarantee checks.

app/guide/presentation/copywriter_fallback.py
  Deterministic mode-specific bounded copy.

app/guide/presentation/presentation_compiler.py
  Calls at most one copywriter request, validates or falls back, attaches
  direct facts and section order, and returns `PresentationContractData`.

app/guide/adapters/llm/presentation_copywriter_adapter.py
  Shared OpenAI-compatible one-request adapter.

app/guide/adapters/llm/deepseek_presentation_copywriter.py
app/guide/adapters/llm/siliconflow_presentation_copywriter.py
  Explicit provider request bodies with thinking disabled.

app/guide_runtime/copywriter_config.py
  Separate environment contract, budgets, timeout, and model selection.

tools/guide_gates/presentation_copy_gate.py
tools/guide_gates/run_real_presentation_copy_gate.py
  Layered offline and official copy quality gates.

tools/guide_data/audit_frontend_product_images.py
  Card-image coverage, source, SHA, identity, and fallback inventory.
```

### Modified backend files

```text
app/guide/presentation/sse_events.py
app/guide/application/text_recommendation_flow.py
app/guide/application/image_recommendation_flow.py
app/guide/application/consultation_chat_flow.py
app/guide/application/chat_api_adapter.py
app/guide_runtime/composition.py
app/guide_runtime/app.py
```

### Frontend files

```text
app/static/chat.html
  Preserve visual shell and CSS; wire typed presentation events, improved
  thinking panel, mode renderers, inline mini cards, final full shelf,
  pitfalls, evidence, and history.

app/static/guide-presentation.js
  Pure typed event reducer, slot/card binding, section ordering, copy token
  substitution, and history normalization. No business decisions.
```

### New audits and fixtures

```text
docs/audits/frontend-integration/old_frontend_behavior.md
docs/audits/frontend-integration/old_visual_shell_v1.json
docs/audits/frontend-integration/product_image_inventory_v1.json
docs/audits/frontend-integration/copywriter_architecture_checkpoint.md
docs/audits/frontend-integration/browser_closure.md
docs/audits/frontend-integration/closure_report.md
tests/fixtures/guide/presentation/copy_gate_v1.jsonl
tests/fixtures/guide/presentation/frontend_mode_matrix_v1.jsonl
```

## Task 1: Freeze Old Behavior and Current Typed Contracts

**Files:**

- Create: `docs/audits/frontend-integration/old_frontend_behavior.md`
- Create: `docs/audits/frontend-integration/old_visual_shell_v1.json`
- Create: `tests/fixtures/guide/presentation/frontend_mode_matrix_v1.jsonl`
- Test: `tests/guide/runtime/test_frontend_mode_matrix.py`
- Test: `tests/guide/runtime/test_frontend_visual_shell.py`

- [ ] **Step 1: Write the mode-matrix RED test**

Create a strict 18-intent matrix covering:

```python
EXPECTED_MODES = {
    "recommend",
    "comparison",
    "suitability",
    "knowledge_product",
    "knowledge_general",
    "followup_product",
    "followup_state",
    "clarify",
    "revise",
    "image_recommend",
    "image_identity",
    "image_compare",
    "image_suitability",
    "consultation_entry",
    "consultation_provisional",
    "consultation_confirmation",
    "consultation_medical_escalation",
    "error",
}
```

Each row must declare:

```text
copy schema
visible product IDs
inline mini-card IDs
final full-card IDs
pitfall product IDs
section order
thinking stages
history behavior
```

- [ ] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/runtime/test_frontend_mode_matrix.py
```

Expected: FAIL because the fixture and loader do not exist.

- [ ] **Step 3: Audit old behavior**

Read and record exact behavior from:

```text
chat.html:
  getProductsInContractOrder
  getDisplaySections
  renderStructuredPanelsInContractOrder
  buildInlineProductNode
  displayProducts
  displayPitfalls
  displayDecisionProcess
  renderStoredMessages

v2 agent:
  _build_answer_contract
  inline_images
  display_sections

v2 presenter:
  _build_diandian_recommendation
  _build_product_block
  _build_summary
```

The audit must distinguish:

```text
preserve
preserve with refinement
replace with typed contract
reject as old business logic
```

- [ ] **Step 4: Publish the visual-shell lock**

Record critical computed values and screenshot geometry:

```text
CSS color variables
body and chat background
sidebar width
header height
conversation max width
message bubble widths
composer position and height
desktop recommendation grid columns
mobile breakpoint and stacking
font family and main type scale
border radii
```

The test fails if these values change outside the approved answer,
thinking-panel, overflow, or responsive-fix selectors.

- [ ] **Step 5: Publish the matrix**

Use canonical JSONL sorted by `case_id`. Example:

```json
{"case_id":"recommend-three","mode":"recommend","visible_product_ids":[55,57,54],"inline_card_ids":[55,57,54],"full_card_ids":[55,57,54],"pitfall_product_ids":[],"section_order":["summary","product:p1","product:p2","product:p3","closing","pitfalls","full_cards","evidence"],"thinking_stages":["understanding","retrieval","decision","copy"]}
```

- [ ] **Step 6: Run GREEN**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/runtime/test_frontend_mode_matrix.py \
  tests/guide/runtime/test_frontend_visual_shell.py
```

Expected: PASS with all modes and zero duplicate case IDs.

- [ ] **Step 7: Commit only Task 1 files**

```bash
git add \
  docs/audits/frontend-integration/old_frontend_behavior.md \
  docs/audits/frontend-integration/old_visual_shell_v1.json \
  tests/fixtures/guide/presentation/frontend_mode_matrix_v1.jsonl \
  tests/guide/runtime/test_frontend_mode_matrix.py \
  tests/guide/runtime/test_frontend_visual_shell.py
git commit -m "test: freeze frontend mode behavior"
```

## Task 2: Define Copywriter and Presentation Contracts

**Files:**

- Create: `app/guide/presentation/copywriter_contracts.py`
- Modify: `app/guide/presentation/sse_events.py`
- Test: `tests/guide/presentation/test_copywriter_contracts.py`
- Test: `tests/guide/presentation/test_presentation_sse_contracts.py`

- [ ] **Step 1: Write strict contract RED tests**

Tests require:

```python
class CopySlot(BaseModel):
    slot_id: str
    product_id: int
    approved_soft_facts: tuple[ApprovedSoftFact, ...]
    locked_facts: tuple[LockedFact, ...]
    required_cautions: tuple[DirectCaution, ...]

class PresentationPacket(BaseModel):
    mode: PresentationMode
    winner_status: str | None
    slots: tuple[CopySlot, ...]
    section_order: tuple[PresentationSectionSpec, ...]
    copy_budget: CopyLengthBudget

class CopywriterDraft(BaseModel):
    mode: PresentationMode
    summary_copy: str
    product_copy: tuple[ProductCopy, ...]
    closing_copy: str | None

class RecommendationPresentationData(BaseModel):
    mode: PresentationMode
    copy_source: Literal["model", "fallback"]
    sections: tuple[PresentationSection, ...]
    card_display: CardDisplayContract
    telemetry: CopywriterTelemetry
```

Reject:

- duplicate slots;
- product copy outside slots;
- reordered product copy;
- product sections in zero-card modes;
- inline/full card IDs that differ from `CardDisplayContract`;
- hard facts inside free-form copy fields;
- unknown section types;
- evidence before required caution;
- final card shelf before closing/pitfalls.

- [ ] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/presentation/test_copywriter_contracts.py \
  tests/guide/presentation/test_presentation_sse_contracts.py
```

- [ ] **Step 3: Implement strict frozen models**

Use:

```python
class _StrictFrozen(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )
```

Use discriminated unions for mode-specific data:

```python
PresentationContractData = Annotated[
    RecommendationPresentationData
    | ComparisonPresentationData
    | SingleProductPresentationData
    | ProductKnowledgePresentationData
    | GeneralKnowledgePresentationData
    | FollowupPresentationData
    | ImagePresentationData
    | ConsultationPresentationData
    | ClarificationPresentationData
    | ErrorPresentationData,
    Field(discriminator="mode"),
]
```

- [ ] **Step 4: Add the SSE event**

Add:

```python
class PresentationContractEvent(_Strict):
    event: Literal[
        "presentation_contract"
    ] = "presentation_contract"
    data: PresentationContractData
```

Insert it in `SseEvent` before `MessageEvent`.

- [ ] **Step 5: Run GREEN**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/presentation/test_copywriter_contracts.py \
  tests/guide/presentation/test_presentation_sse_contracts.py \
  tests/guide/presentation/test_card_display_contracts.py
```

- [ ] **Step 6: Commit**

```bash
git add \
  app/guide/presentation/copywriter_contracts.py \
  app/guide/presentation/sse_events.py \
  tests/guide/presentation/test_copywriter_contracts.py \
  tests/guide/presentation/test_presentation_sse_contracts.py
git commit -m "feat: add typed presentation contracts"
```

## Task 3: Build Compact Presentation Packets

**Files:**

- Create: `app/guide/presentation/presentation_packet.py`
- Test: `tests/guide/presentation/test_presentation_packet.py`

- [ ] **Step 1: Write packet-builder RED tests**

Require:

```python
packet = build_presentation_packet(
    mode="recommendation",
    user_need_summary="500元内，油敏肌，防晒",
    decision=decision,
    card_display=card_display,
    cards=cards,
    merchant_claims=claims,
    review_evidence=reviews,
    product_evidence=evidence,
    pitfalls=pitfalls,
)
```

Assert:

- slots exactly match `visible_product_ids`;
- no unavailable category facts enter packet facts;
- only two to four relevant soft facts per slot;
- package warnings and numeric facts are locked;
- merchant and consumer facts keep attribution;
- `plain_meaning` is preferred over raw OCR;
- rejected products and history products are absent;
- zero-card modes have zero slots;
- prompt-injection text is absent;
- packet bytes are deterministic.

- [ ] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/presentation/test_presentation_packet.py
```

- [ ] **Step 3: Implement fact normalization**

Implement:

```python
def normalize_display_text(value: str, *, limit: int) -> str:
    value = " ".join(value.replace("\r", " ").replace("\n", " ").split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"
```

Do not infer facts from raw text. Use typed evidence fields.

- [ ] **Step 4: Implement relevance selection**

Priority:

```text
required package warning
matched decision/concept slot
user-requested category field
verified numeric/product fact
ordinary merchant claim
consumer report
```

Merchant-positive safety claims never become locked safety facts.

- [ ] **Step 5: Run GREEN and deterministic rerun**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/presentation/test_presentation_packet.py
```

Serialize the same packet twice and assert byte identity.

- [ ] **Step 6: Commit**

```bash
git add \
  app/guide/presentation/presentation_packet.py \
  tests/guide/presentation/test_presentation_packet.py
git commit -m "feat: build bounded presentation packets"
```

## Task 4: Add Blind Copywriter Prompt, Adapter, and Configuration

**Files:**

- Create: `app/guide/presentation/copywriter_prompt.py`
- Create: `app/guide/adapters/llm/presentation_copywriter_adapter.py`
- Create: `app/guide/adapters/llm/deepseek_presentation_copywriter.py`
- Create: `app/guide/adapters/llm/siliconflow_presentation_copywriter.py`
- Create: `app/guide_runtime/copywriter_config.py`
- Test: `tests/guide/presentation/test_copywriter_prompt.py`
- Test: `tests/guide/adapters/test_presentation_copywriter.py`
- Test: `tests/guide/runtime/test_copywriter_config.py`

- [ ] **Step 1: Write prompt RED tests**

Assert the prompt:

- contains packet JSON and strict output schema;
- states model cannot change slots or emit hard facts;
- allows soft paraphrase and advisor tone;
- distinguishes merchant/consumer/verified attribution;
- bans unsupported winner and safety language;
- contains no fixture sentence or product-specific answer;
- requests JSON, not Markdown;
- stays below a locked character budget.

- [ ] **Step 2: Write adapter RED tests**

Use `httpx.MockTransport` and assert:

```text
one HTTP request
thinking disabled
temperature bounded
response_format=json_object
no repair
usage captured
invalid JSON raises typed failure
provider failure does not retry
```

- [ ] **Step 3: Write config RED tests**

New variables:

```text
GUIDE_COPY_LLM_API_KEY
GUIDE_COPY_LLM_BASE_URL
GUIDE_COPY_LLM_MODEL
GUIDE_COPY_LLM_TIMEOUT_SECONDS
GUIDE_COPY_LLM_MAX_TOKENS
GUIDE_COPY_LLM_DAILY_BUDGET_CNY
GUIDE_COPY_LLM_DAILY_CALL_CAP
```

Missing key/model yields deterministic fallback configuration, not translator
key reuse.

- [ ] **Step 4: Run RED**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/presentation/test_copywriter_prompt.py \
  tests/guide/adapters/test_presentation_copywriter.py \
  tests/guide/runtime/test_copywriter_config.py
```

- [ ] **Step 5: Implement minimal adapters**

Expose:

```python
class PresentationCopywriterPort(Protocol):
    def write(
        self,
        packet: PresentationPacket,
    ) -> CopywriterCallResult: ...
```

No `repair`, `review`, or retry method exists.

- [ ] **Step 6: Run GREEN**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/presentation/test_copywriter_prompt.py \
  tests/guide/adapters/test_presentation_copywriter.py \
  tests/guide/runtime/test_copywriter_config.py
```

- [ ] **Step 7: Commit**

```bash
git add \
  app/guide/presentation/copywriter_prompt.py \
  app/guide/adapters/llm/presentation_copywriter_adapter.py \
  app/guide/adapters/llm/deepseek_presentation_copywriter.py \
  app/guide/adapters/llm/siliconflow_presentation_copywriter.py \
  app/guide_runtime/copywriter_config.py \
  tests/guide/presentation/test_copywriter_prompt.py \
  tests/guide/adapters/test_presentation_copywriter.py \
  tests/guide/runtime/test_copywriter_config.py
git commit -m "feat: add blind presentation copywriter"
```

## Task 5: Validate Copy Without Grading Style

**Files:**

- Create: `app/guide/presentation/copywriter_validation.py`
- Create: `app/guide/presentation/copywriter_fallback.py`
- Test: `tests/guide/presentation/test_copywriter_validation.py`
- Test: `tests/guide/presentation/test_copywriter_fallback.py`

- [ ] **Step 1: Write validator RED tests**

Accept:

```text
轻薄清爽 -> 轻盈不黏
快速成膜 -> 早上赶时间时更利落
different punctuation and sentence order
different but bounded advisor transitions
```

Reject:

```text
unknown slot
duplicate or reordered slot
new price, percentage, sample size, duration
new ingredient or product name
best/most suitable language without authorized winner
merchant claim presented as verified
allergy-free or medical guarantee
HTML/Markdown
overlong fields
```

- [ ] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/presentation/test_copywriter_validation.py
```

- [ ] **Step 3: Implement lightweight checks**

Expose:

```python
def validate_copywriter_draft(
    packet: PresentationPacket,
    draft: CopywriterDraft,
) -> ValidatedCopywriterDraft:
    ...
```

Use structured slot/fact sets and lexical hard atoms only. Do not build a
semantic synonym dictionary.

- [ ] **Step 4: Write and implement fallback**

Fallback returns mode-specific strict copy:

```python
def fallback_copy(packet: PresentationPacket) -> CopywriterDraft:
    ...
```

It uses bounded `plain_meaning`, never raw OCR.

- [ ] **Step 5: Run GREEN**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/presentation/test_copywriter_validation.py \
  tests/guide/presentation/test_copywriter_fallback.py
```

- [ ] **Step 6: Commit**

```bash
git add \
  app/guide/presentation/copywriter_validation.py \
  app/guide/presentation/copywriter_fallback.py \
  tests/guide/presentation/test_copywriter_validation.py \
  tests/guide/presentation/test_copywriter_fallback.py
git commit -m "feat: validate and fallback presentation copy"
```

## Task 6: Compile Mode-Specific Presentation Contracts

**Files:**

- Create: `app/guide/presentation/presentation_compiler.py`
- Test: `tests/guide/presentation/test_presentation_compiler.py`

- [ ] **Step 1: Write mode compiler RED tests**

Cover all mode families. Example:

```python
result = compile_presentation(
    inputs,
    copywriter=recording_copywriter,
)

assert result.mode == "recommendation"
assert result.copy_source == "model"
assert result.card_display.visible_product_ids == (55, 57, 54)
assert [section.slot_id for section in result.product_sections] == [
    "p1", "p2", "p3"
]
```

Assert clarification, errors, medical escalation, and evidence-gap-only
answers do not call the copywriter.

- [ ] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/presentation/test_presentation_compiler.py
```

- [ ] **Step 3: Implement one-call orchestration**

```python
try:
    call = copywriter.write(packet)
    copy = validate_copywriter_draft(packet, call.draft)
    source = "model"
except CopywriterFailure:
    copy = fallback_copy(packet)
    source = "fallback"
```

Never call `write()` twice.

- [ ] **Step 4: Attach direct facts and card sections**

Build exact section order:

```text
summary
product sections with inline mini-card intents
comparison/knowledge-specific panels
closing
pitfalls
final full-card shelf
evidence
```

- [ ] **Step 5: Run GREEN**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/presentation/test_presentation_compiler.py
```

- [ ] **Step 6: Commit**

```bash
git add \
  app/guide/presentation/presentation_compiler.py \
  tests/guide/presentation/test_presentation_compiler.py
git commit -m "feat: compile mode-specific presentations"
```

## Task 7: Integrate Text Recommendation, Comparison, Knowledge, and Follow-Up

**Files:**

- Modify: `app/guide/application/text_recommendation_flow.py`
- Modify: `app/guide_runtime/composition.py`
- Test: `tests/guide/application/test_text_presentation_integration.py`
- Test: `tests/guide/runtime/test_composition_copywriter.py`

- [ ] **Step 1: Write event-sequence RED tests**

For recommendation require:

```text
start
stage
intent
evidence/decision events
answer_contract
card_display_contract
products
presentation_contract
message
end
```

For general knowledge require:

```text
start
intent
general_knowledge
presentation_contract
message
end
```

For clarification require no presentation model call and no card events.

- [ ] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/application/test_text_presentation_integration.py \
  tests/guide/runtime/test_composition_copywriter.py
```

- [ ] **Step 3: Build runtime copywriter**

In composition:

```python
copywriter = build_presentation_copywriter()
presentation_compiler = PresentationCompiler(
    copywriter=copywriter,
)
```

Missing config uses an explicit disabled port that always selects fallback.

- [ ] **Step 4: Integrate without changing decisions**

Capture already-final:

```text
DecisionResult
CardDisplayContract
ProductCard list
evidence events
pitfalls
```

Then compile presentation. Do not move ranking, state save, or card selection
after copy.

- [ ] **Step 5: Remove duplicate claims from compatibility message**

Replace `_append_source_quotes()` use in the main message with one concise
bounded compatibility summary. Claims remain in typed evidence events and
the presentation evidence section.

- [ ] **Step 6: Verify decision invariance**

Run the same turn with copywriter enabled and disabled. Assert identical:

```text
ordered product IDs
winner status
card display contract
conversation state
pitfall evidence refs
```

- [ ] **Step 7: Run GREEN**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/application/test_text_presentation_integration.py \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/runtime/test_composition_copywriter.py
```

- [ ] **Step 8: Commit**

```bash
git add \
  app/guide/application/text_recommendation_flow.py \
  app/guide_runtime/composition.py \
  tests/guide/application/test_text_presentation_integration.py \
  tests/guide/runtime/test_composition_copywriter.py
git commit -m "feat: integrate text presentation copy"
```

## Task 8: Integrate Image and Consultation Modes

**Files:**

- Modify: `app/guide/application/image_recommendation_flow.py`
- Modify: `app/guide/application/consultation_chat_flow.py`
- Test: `tests/guide/application/test_image_presentation_integration.py`
- Test: `tests/guide/application/test_consultation_presentation_integration.py`

- [ ] **Step 1: Write image RED tests**

Assert:

- image identity shows only confirmed product;
- similar search shows only authorized result IDs;
- image suitability shows one product;
- image comparison preserves ordinal product order;
- identity failure shows zero cards and skips copywriter;
- hidden OCR/evidence products do not produce copy slots.

- [ ] **Step 2: Write consultation RED tests**

Assert entry, answer, provisional, confirmation, rejection, and medical
escalation all use zero-card mode. Medical escalation skips copywriter.

- [ ] **Step 3: Run RED**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/application/test_image_presentation_integration.py \
  tests/guide/application/test_consultation_presentation_integration.py
```

- [ ] **Step 4: Integrate image packets**

Use image card contracts as the slot authority. Do not derive card slots from
OCR text or similarity payloads.

- [ ] **Step 5: Integrate consultation copy**

Use deterministic copy for clarification and medical escalation. General
consultation observations may use model copy only when the approved packet
contains no medical escalation.

- [ ] **Step 6: Run GREEN**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/application/test_image_presentation_integration.py \
  tests/guide/application/test_consultation_presentation_integration.py \
  tests/guide/application/test_image_recommendation_flow.py \
  tests/guide/application/test_consultation_chat_flow.py
```

- [ ] **Step 7: Commit**

```bash
git add \
  app/guide/application/image_recommendation_flow.py \
  app/guide/application/consultation_chat_flow.py \
  tests/guide/application/test_image_presentation_integration.py \
  tests/guide/application/test_consultation_presentation_integration.py
git commit -m "feat: integrate image and consultation presentation"
```

## Task 9: Validate Public SSE and Persist Presentation History

**Files:**

- Modify: `app/guide/application/chat_api_adapter.py`
- Modify: `app/guide_runtime/app.py`
- Test: `tests/guide/application/test_chat_presentation_adapter.py`
- Test: `tests/guide/runtime/test_presentation_runtime_http.py`

- [ ] **Step 1: Write public sequence RED tests**

Require `presentation_contract` after final card/evidence inputs and before
`message`.

Reject:

- contract slots different from card display IDs;
- contract section order different from mode;
- presentation after message;
- presentation on error;
- zero-card mode with product sections;
- pitfall product outside visible IDs.

- [ ] **Step 2: Write history RED tests**

Persist:

```text
presentation mode
copy source
section order
inline mini-card IDs
final full-card IDs
pitfall and evidence section payloads
```

Reload must preserve exact IDs/order without invoking either model.

- [ ] **Step 3: Run RED**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/application/test_chat_presentation_adapter.py \
  tests/guide/runtime/test_presentation_runtime_http.py
```

- [ ] **Step 4: Implement adapter validation**

Use existing `_validate_guide_event_sequence()` and typed models. Do not add
loose dictionary fallbacks.

- [ ] **Step 5: Implement compatibility aggregation**

Add `presentation_contract` to non-streaming `/message` aggregation without
changing terminal delivery transaction behavior.

- [ ] **Step 6: Run GREEN**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/application/test_chat_presentation_adapter.py \
  tests/guide/application/test_chat_api_adapter.py \
  tests/guide/runtime/test_presentation_runtime_http.py \
  tests/guide/runtime/test_runtime_http.py
```

- [ ] **Step 7: Commit**

```bash
git add \
  app/guide/application/chat_api_adapter.py \
  app/guide_runtime/app.py \
  tests/guide/application/test_chat_presentation_adapter.py \
  tests/guide/runtime/test_presentation_runtime_http.py
git commit -m "feat: expose typed presentation SSE"
```

## Task 10: Add Typed Frontend Reducer and Refined Thinking Panel

**Files:**

- Create: `app/static/guide-presentation.js`
- Modify: `app/static/chat.html`
- Test: `tests/guide/runtime/test_frontend_presentation_reducer.py`
- Test: `tests/guide/runtime/test_frontend_thinking_panel.py`

- [ ] **Step 1: Write reducer RED tests**

Using Node, require:

```javascript
const state = reduceGuideEvent(previous, {
  event: 'presentation_contract',
  data: payload,
});
```

Assert event order, slot IDs, card contracts, and zero-card cleanup.

- [ ] **Step 2: Write thinking-panel RED tests**

Require:

```text
starts immediately on send
stable compact container
four mode-specific labels
stage event advances current marker
first answer character triggers fade
removed after 350ms
answer is never delayed
no persisted thinking panel in history
```

- [ ] **Step 3: Run RED**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/runtime/test_frontend_presentation_reducer.py \
  tests/guide/runtime/test_frontend_thinking_panel.py
```

- [ ] **Step 4: Implement pure reducer**

Expose:

```javascript
window.XiaoRoPresentation = {
  createTurnState,
  reduceGuideEvent,
  resolveVisibleProducts,
  substituteProductSlots,
  serializePresentation,
  restorePresentation
};
```

No function may calculate winner or rank.

- [ ] **Step 5: Implement refined thinking UI**

Reuse old CSS variables and typography. Add a compact stable component with
one active label and four small markers. Do not use large nested cards.

- [ ] **Step 6: Run GREEN**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/runtime/test_frontend_presentation_reducer.py \
  tests/guide/runtime/test_frontend_thinking_panel.py \
  tests/guide/runtime/test_frontend_scope.py
```

- [ ] **Step 7: Commit**

```bash
git add \
  app/static/guide-presentation.js \
  app/static/chat.html \
  tests/guide/runtime/test_frontend_presentation_reducer.py \
  tests/guide/runtime/test_frontend_thinking_panel.py
git commit -m "feat: add typed frontend presentation state"
```

## Task 11: Render Mode-Specific Copy and Both Card Forms

**Files:**

- Modify: `app/static/chat.html`
- Modify: `app/static/guide-presentation.js`
- Test: `tests/guide/runtime/test_frontend_mode_rendering.py`
- Test: `tests/guide/runtime/test_frontend_card_binding.py`

- [ ] **Step 1: Write mode-renderer RED tests**

Require separate renderers:

```javascript
renderRecommendationPresentation
renderComparisonPresentation
renderSingleProductPresentation
renderProductKnowledgePresentation
renderGeneralKnowledgePresentation
renderFollowupPresentation
renderImagePresentation
renderConsultationPresentation
renderClarificationPresentation
renderErrorPresentation
```

- [ ] **Step 2: Write card-binding RED tests**

For each visible product assert:

```text
one inline mini card under primary product section
one final full card in shelf
same product ID and image in both
later product references are clickable links, not third cards
hidden products render no card
full shelf order equals visible_product_ids
```

- [ ] **Step 3: Run RED**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/runtime/test_frontend_mode_rendering.py \
  tests/guide/runtime/test_frontend_card_binding.py
```

- [ ] **Step 4: Reuse old visual components**

Reuse or refine:

```text
buildInlineProductNode
displayProducts
displayComparison
displayPitfalls
recommendation card CSS
inline product CSS
typewriter renderer
```

Replace uncalibrated `% 契合` with backend-provided real status labels.

- [ ] **Step 5: Add slot links**

Substitute:

```text
{{product:p1}}
```

with a safe button/link bound to the existing product section. Click scrolls
to and briefly highlights the card.

- [ ] **Step 6: Render final shelf**

Use only `CardDisplayContract.visible_product_ids`; do not render all products
received from another event.

- [ ] **Step 7: Run GREEN**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/runtime/test_frontend_mode_rendering.py \
  tests/guide/runtime/test_frontend_card_binding.py \
  tests/guide/runtime/test_frontend_scope.py
```

- [ ] **Step 8: Commit**

```bash
git add \
  app/static/chat.html \
  app/static/guide-presentation.js \
  tests/guide/runtime/test_frontend_mode_rendering.py \
  tests/guide/runtime/test_frontend_card_binding.py
git commit -m "feat: render typed advisor responses"
```

## Task 12: Render Pitfalls, Evidence, Errors, and History Safely

**Files:**

- Modify: `app/static/chat.html`
- Modify: `app/static/guide-presentation.js`
- Test: `tests/guide/runtime/test_frontend_evidence_rendering.py`
- Test: `tests/guide/runtime/test_frontend_presentation_xss.py`
- Test: `tests/guide/runtime/test_frontend_presentation_history.py`

- [ ] **Step 1: Write evidence RED tests**

Assert:

- high severity visible separately;
- medium/low combine into `其他注意`;
- pitfall product IDs are visible IDs;
- claims, reviews, and exact sources default collapsed;
- main copy does not duplicate full evidence;
- unavailable facts never render.

- [ ] **Step 2: Write XSS RED tests**

Inject model/evidence strings containing:

```html
<img src=x onerror=alert(1)>
<script>alert(1)</script>
[click](javascript:alert(1))
{{product:unknown}}
```

Assert no unsafe DOM, URL, or slot binding.

- [ ] **Step 3: Write history RED tests**

Complete a turn, serialize, reload, and assert identical:

```text
section order
copy source
inline cards
full shelf
pitfalls
evidence drawers
clickable product references
```

No duplicate panel or model call occurs on reload.

- [ ] **Step 4: Run RED**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/runtime/test_frontend_evidence_rendering.py \
  tests/guide/runtime/test_frontend_presentation_xss.py \
  tests/guide/runtime/test_frontend_presentation_history.py
```

- [ ] **Step 5: Implement using DOM nodes**

Use `textContent`, `createTextNode`, and safe URL helpers. Do not inject model
HTML with `innerHTML`.

- [ ] **Step 6: Run GREEN**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/runtime/test_frontend_evidence_rendering.py \
  tests/guide/runtime/test_frontend_presentation_xss.py \
  tests/guide/runtime/test_frontend_presentation_history.py \
  tests/guide/runtime/test_frontend_scope.py
```

- [ ] **Step 7: Commit**

```bash
git add \
  app/static/chat.html \
  app/static/guide-presentation.js \
  tests/guide/runtime/test_frontend_evidence_rendering.py \
  tests/guide/runtime/test_frontend_presentation_xss.py \
  tests/guide/runtime/test_frontend_presentation_history.py
git commit -m "feat: render presentation evidence safely"
```

## Task 13: Audit and Complete Product Card Images

**Files:**

- Create: `tools/guide_data/audit_frontend_product_images.py`
- Create: `docs/audits/frontend-integration/product_image_inventory_v1.json`
- Modify when the tested inventory reports an exact card-image gap:
  `data/canonical/seed_product_images_v1.jsonl`
- Modify when the tested inventory reports an exact card-image gap:
  `data/canonical/seed_product_images_v1_manifest.json`
- Test: `tests/guide/tools/test_audit_frontend_product_images.py`
- Test: `tests/guide/data/test_frontend_product_image_inventory.py`

- [ ] **Step 1: Write image inventory RED test**

Inventory fields:

```text
product ID
canonical identity
image path
source kind
source URL
source SHA
file SHA
review status
pixel dimensions
missing/broken/mismatched status
```

- [ ] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/tools/test_audit_frontend_product_images.py
```

- [ ] **Step 3: Audit source priority**

For every displayed canonical product:

1. fresh content-addressed asset;
2. fresh local verified asset;
3. old repository verified local asset;
4. official exact product page capture;
5. neutral placeholder.

Never use another product or variant as a visual substitute.

- [ ] **Step 4: Capture only exact missing card images**

Use built-in browser. Record URL, time, crop, and SHA. Do not crawl products
that already have an approved card image.

- [ ] **Step 5: Publish content-addressed inventory**

Generate canonical JSON and manifest; rerun byte-identically.

- [ ] **Step 6: Run GREEN**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/tools/test_audit_frontend_product_images.py \
  tests/guide/data/test_frontend_product_image_inventory.py
```

- [ ] **Step 7: Commit**

```bash
git add \
  tools/guide_data/audit_frontend_product_images.py \
  docs/audits/frontend-integration/product_image_inventory_v1.json \
  tests/guide/tools/test_audit_frontend_product_images.py \
  tests/guide/data/test_frontend_product_image_inventory.py
git add -- \
  data/canonical/seed_product_images_v1.jsonl \
  data/canonical/seed_product_images_v1_manifest.json
git commit -m "data: audit frontend product images"
```

If the inventory proves both canonical seed files are byte-identical, omit
the second `git add` command and record `canonical_seed_changed=false` in the
inventory.

## Task 14: Build Layered Copywriter Gates

**Files:**

- Create: `tests/fixtures/guide/presentation/copy_gate_v1.jsonl`
- Create: `tools/guide_gates/presentation_copy_gate.py`
- Create: `tools/guide_gates/run_real_presentation_copy_gate.py`
- Test: `tests/guide/tools/test_presentation_copy_gate.py`
- Test: `tests/guide/tools/test_run_real_presentation_copy_gate.py`
- Create: `docs/audits/frontend-integration/copywriter_architecture_checkpoint.md`

- [ ] **Step 1: Publish audited fixture truth**

Rows contain:

```text
required slots
allowed soft fact IDs
locked atoms
winner-language policy
required attribution
forbidden factual claims
readability rubric
don't-care wording
```

Do not store an exact golden paragraph.

- [ ] **Step 2: Write gate RED tests**

Gate must:

- fail second copywriter request;
- fail slot/order/state/hard-fact mutation;
- fail new numbers or ingredients;
- fail unsupported best/safest language;
- allow paraphrases;
- allow different sentence order;
- count schema-invalid output as failed without retry;
- keep hard counts separate from readability.

- [ ] **Step 3: Implement offline gate**

Report:

```text
schema
slot binding
fact grounding
hard atoms
winner language
safety attribution
readability
latency
tokens
```

- [ ] **Step 4: Run local fixture gate**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/tools/test_presentation_copy_gate.py \
  tests/guide/tools/test_run_real_presentation_copy_gate.py
```

- [ ] **Step 5: Run three official gates sequentially**

Each saved output is immutable and content-addressed. No repair or reviewer.

Admission:

```text
readability/usefulness >= 90%
schema valid >= 95%
all hard violations = 0
one copywriter request per eligible case
```

After repeated same-layer failure, write the checkpoint before changing
prompt or validator.

- [ ] **Step 6: Commit gate code and audited fixture**

```bash
git add \
  tests/fixtures/guide/presentation/copy_gate_v1.jsonl \
  tools/guide_gates/presentation_copy_gate.py \
  tools/guide_gates/run_real_presentation_copy_gate.py \
  tests/guide/tools/test_presentation_copy_gate.py \
  tests/guide/tools/test_run_real_presentation_copy_gate.py \
  docs/audits/frontend-integration/copywriter_architecture_checkpoint.md
git commit -m "test: add presentation copywriter gates"
```

Before commit, run:

```bash
git diff --cached | rg -n "Authorization|api[_-]?key|sk-[A-Za-z0-9]"
```

Expected: no output.

## Task 15: Browser Screenshot Audit and Visual Refinement

**Files:**

- Create: `docs/audits/frontend-integration/browser_closure.md`
- Store screenshots under:
  `docs/audits/frontend-integration/screenshots/`
- Modify: `app/static/chat.html`
- Modify: `app/static/guide-presentation.js`
- Test: `tests/guide/runtime/test_frontend_browser_contract.py`

- [ ] **Step 1: Start one local configured server**

Use explicit translator and copywriter config. If a port is occupied, use the
next free port. Record the URL.

- [ ] **Step 2: Capture visual baseline**

Open old frontend and current frontend in separate browser tabs. Capture:

```text
empty desktop
empty mobile
old recommendation result
old inline mini card
old final full-card shelf
old pitfall panel
```

- [ ] **Step 3: Run each frontend mode**

Use real or audited deterministic backend inputs for every row in the mode
matrix. Capture desktop `1440x900` and mobile `390x844`.

- [ ] **Step 4: Inspect after every flow**

Check:

```text
screenshots
DOM snapshot
browser console
network requests
SSE event order
image natural dimensions
scroll and focus behavior
```

- [ ] **Step 5: Refine within old design language**

Allowed:

- thinking panel composition;
- non-recommendation section layout;
- spacing and overflow fixes;
- mobile stacking;
- clearer labels and disclosure hierarchy.

Forbidden:

- new palette;
- new typography;
- marketing landing-page layout;
- decorative gradients/orbs;
- unrelated redesign.

After each refinement run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/runtime/test_frontend_visual_shell.py
```

Expected: PASS. Any locked shell-token change must be reverted unless it is
an explicit overflow/responsive selector listed in the approved exception
set.

- [ ] **Step 6: Verify card and canvas pixels**

Assert:

```text
nonblank page
all product images load or show approved fallback
no overlap
no clipped longest title
no duplicate third card
inline and full cards share product ID/image
thinking disappears at first answer character
```

- [ ] **Step 7: Write browser closure**

For every screenshot record:

```text
viewport
flow
input
event sequence
visible card IDs
console errors
network failures
verdict
```

- [ ] **Step 8: Run browser contract test**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/runtime/test_frontend_browser_contract.py
```

- [ ] **Step 9: Commit final frontend refinement and audit**

```bash
git add \
  app/static/chat.html \
  app/static/guide-presentation.js \
  tests/guide/runtime/test_frontend_browser_contract.py \
  docs/audits/frontend-integration/browser_closure.md \
  docs/audits/frontend-integration/screenshots
git commit -m "test: close local frontend browser audit"
```

## Task 16: Full Regression and Local Closure

**Files:**

- Create: `docs/audits/frontend-integration/closure_report.md`
- Modify: `README.md`

- [ ] **Step 1: Run focused suites**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/presentation \
  tests/guide/adapters/test_presentation_copywriter.py \
  tests/guide/application/test_text_presentation_integration.py \
  tests/guide/application/test_image_presentation_integration.py \
  tests/guide/application/test_consultation_presentation_integration.py \
  tests/guide/application/test_chat_presentation_adapter.py \
  tests/guide/runtime/test_frontend_mode_matrix.py \
  tests/guide/runtime/test_frontend_presentation_reducer.py \
  tests/guide/runtime/test_frontend_thinking_panel.py \
  tests/guide/runtime/test_frontend_mode_rendering.py \
  tests/guide/runtime/test_frontend_card_binding.py \
  tests/guide/runtime/test_frontend_evidence_rendering.py \
  tests/guide/runtime/test_frontend_presentation_xss.py \
  tests/guide/runtime/test_frontend_presentation_history.py
```

- [ ] **Step 2: Run Guide full once**

```bash
.venv/bin/python -m pytest -q tests/guide
```

Poll until exit. Do not duplicate the run.

- [ ] **Step 3: Run runtime/application/state/presentation**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/runtime \
  tests/guide/application \
  tests/guide/adapters/state \
  tests/guide/presentation \
  tests/guide/test_public_contracts.py
```

- [ ] **Step 4: Run static boundaries**

```bash
.venv/bin/python -m compileall -q app tools
.venv/bin/python -m pytest -q \
  tests/guide/test_architecture_boundaries.py \
  tests/guide/runtime/test_import_boundary.py
git diff --check
```

- [ ] **Step 5: Verify process and deployment boundaries**

Assert:

```text
no duplicate test/server processes
no production deployment
no traffic switch
no secret file staged
no unrelated dirty file staged
```

- [ ] **Step 6: Update local run instructions**

Document separate translator and copywriter environment variables and the
local URL. Never print secret values.

- [ ] **Step 7: Publish closure verdict**

`FRONTEND-LOCAL-GO` requires:

```text
translator requests <= 1
copywriter requests <= 1
reviewer/repair requests = 0
decision/state/safety/hard-fact mutations = 0
copywriter hard violations = 0
required frontend modes = 100% green
desktop/mobile overlap defects = 0
locked visual-shell drift = 0
console errors = 0
required image failures = 0
all local test gates green
three official copywriter gates green
```

Otherwise publish `NO-GO` with the earliest unclosed layer.

- [ ] **Step 8: Stop cleanly**

Stop Goal-started servers after final screenshots unless the final response
needs one local server URL for user review. Do not deploy.

## Expected Final Artifacts

```text
docs/superpowers/specs/
  2026-08-16-double-blind-copywriter-frontend-integration-design.md

docs/superpowers/plans/
  2026-08-16-double-blind-copywriter-frontend-integration.md

docs/audits/frontend-integration/
  old_frontend_behavior.md
  product_image_inventory_v1.json
  copywriter_architecture_checkpoint.md
  browser_closure.md
  closure_report.md
  screenshots/*
```

## Final Output

The implementation session ends with exactly one evidence-backed verdict:

```text
FRONTEND-LOCAL-GO
```

or:

```text
NO-GO + earliest unclosed layer
```

No production deployment occurs.
