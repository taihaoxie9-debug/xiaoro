# Single-Call Concept Ranking and Frontend Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking. The main agent executes all work;
> sub-agents are forbidden by the user.

**Goal:** Replace the two-stage semantic lane with one translation call,
project reviewed common product concepts into reliable soft ranking and
comparison, rebuild semantic truth by ownership, and publish a
`FRONTEND-GO` or evidence-backed `NO-GO` verdict.

**Architecture:** One model emits source-grounded `TurnMeaning` hints. Code
grounds text, resolves references, admits executable operations, owns all
state transitions, and matches reviewed parent-concept identities. Long-tail
descriptions remain ProductEvidence retrieval material. Existing hard
eligibility, safety, state reducer, ProductEvidence, GeneralKnowledge, and
typed SSE remain the authorities in their domains.

**Tech Stack:** Python 3.11, Pydantic v2, pytest, SQLite CAS state,
content-addressed JSONL assets, official DeepSeek/SiliconFlow JSON adapters.

---

## 0. Execution Rules

Use:

```text
/Users/bytedance/Desktop/xiaoro-fresh
branch: rebuild
```

Read first:

```text
docs/superpowers/specs/
2026-08-15-single-call-concept-ranking-frontend-gate-design.md

docs/audits/semantic-transitions/single_call_pilot_report.md

docs/audits/backend-handoff/closure_report.md
```

Do not:

- use sub-agents;
- add a second model call or repair call;
- add phrase/case dictionaries;
- build a vector index;
- modify frontend rendering;
- import legacy `app.services`;
- crawl new web pages;
- lower gate thresholds after a failure;
- stage, commit, push, deploy, or switch traffic.

Keep:

```text
app/static/chat.html SHA-256
70ec29f8298fb912e578b718a214619d590214ddcd556ad0ad7ab1613efdbc95
```

Long-running commands start once and are polled every 30 seconds until exit.

For two consecutive failed fixes at one layer:

1. stop implementation/prompt tuning;
2. write an architecture checkpoint;
3. identify false truth or responsibility overload;
4. choose a general repair;
5. continue autonomously without waiting for the sleeping user.

Estimated duration:

```text
common concept audit: 1-2 hours
one-call contract/binding/integration: 2-3 hours
ranking/comparison/evidence alignment: 1.5-2.5 hours
128-case audit and local gates: 1.5-2 hours
official gates and closure: 1-2 hours

expected total: 6-10 hours
```

## Task 1: Freeze Selection Concept Inventory

**Files:**

- Create:
  `docs/audits/selection-concepts/inventory_v1.json`
- Create:
  `tools/guide_data/audit_selection_parent_concepts.py`
- Test:
  `tests/guide/tools/test_audit_selection_parent_concepts.py`

- [ ] **Step 1: Write the inventory RED test**

The test builds production `SelectionFactReader`, scans all canonical products,
and expects a stable inventory with:

```text
product count
total SelectionFact count
soft-rank count
profile/field product coverage
profile/field distinct-value count
value product coverage
strength and attribution counts
```

It must assert the current locked totals:

```text
100 products
2,322 SelectionFacts
1,775 soft-rank SelectionFacts
```

- [ ] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/tools/test_audit_selection_parent_concepts.py
```

Expected: fail because the inventory builder does not exist.

- [ ] **Step 3: Implement deterministic inventory**

Use production readers and structured fields. Do not scan prose for
keywords. Sort all profile, field, value, product, and source inventories.

- [ ] **Step 4: Materialize and verify**

```bash
.venv/bin/python -m tools.guide_data.audit_selection_parent_concepts \
  --inventory-only \
  --output docs/audits/selection-concepts/inventory_v1.json

.venv/bin/python -m pytest -q \
  tests/guide/tools/test_audit_selection_parent_concepts.py
```

Expected: PASS and byte-identical rerun.

## Task 2: Audit and Publish Parent Concepts

**Files:**

- Create:
  `app/guide/retrieval/selection_parent_concept_contracts.py`
- Create:
  `app/guide/retrieval/selection_parent_concept_assets.py`
- Create:
  `app/guide/retrieval/selection_parent_concept_reader.py`
- Create:
  `docs/audits/selection-concepts/review_v1.jsonl`
- Create:
  `docs/audits/selection-concepts/architecture_checkpoint.md`
- Create:
  `data/guide_selection_concepts/selection_concepts_v1_manifest.json`
- Create:
  `data/guide_selection_concepts/selection_concepts_v1.<sha>.jsonl`
- Modify:
  `app/guide_runtime/composition.py`
- Test:
  `tests/guide/retrieval/test_selection_parent_concept_contracts.py`
- Test:
  `tests/guide/retrieval/test_selection_parent_concept_assets.py`
- Test:
  `tests/guide/retrieval/test_selection_parent_concept_reader.py`
- Test:
  `tests/guide/runtime/test_composition.py`

- [ ] **Step 1: Write strict contract RED tests**

Define reviewed rows with:

```text
product/profile/field/value identity
concept_id|null
stance: supports|opposes|not_comparable
comparability: binary|ordered|numeric|none
rationale
source SelectionFact identity
rank strength
source refs
```

Reject:

- unknown profile/field;
- concept IDs without field scope;
- unreviewed rows;
- source identity drift;
- strength/source changes;
- duplicate review rows;
- unordered IDs or references.

- [ ] **Step 2: Run RED**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/retrieval/test_selection_parent_concept_contracts.py \
  tests/guide/retrieval/test_selection_parent_concept_assets.py \
  tests/guide/retrieval/test_selection_parent_concept_reader.py
```

- [ ] **Step 3: Implement contracts and content-addressed loader**

The loader verifies:

```text
manifest self-hash
runtime expected hash
asset bytes
source SelectionFact inventory hash
review hash
counts and ordering
```

- [ ] **Step 4: Main-agent manual audit**

Review candidates profile by profile, starting with coverage:

```text
skincare efficacy/texture/suitable_skin/skin_concern
suncare texture/film_speed/water_resistance/finish/usage_context
base makeup longevity/finish/texture/coverage
cleanser cleansing_power/rinse_behavior/texture
color makeup finish/color_payoff/longevity
```

Do not automatically accept values based on frequency.

Reject or leave `concept_id = null` for:

- product-specific technologies;
- cold marketing metaphors;
- ingredients;
- medical implications;
- sparse fragrance notes;
- compound values that cannot be split without source loss.

- [ ] **Step 5: Publish asset**

```bash
.venv/bin/python -m tools.guide_data.audit_selection_parent_concepts \
  --inventory docs/audits/selection-concepts/inventory_v1.json \
  --reviews docs/audits/selection-concepts/review_v1.jsonl \
  --output-dir data/guide_selection_concepts
```

- [ ] **Step 6: Verify clean audit**

Expected:

```text
all candidate rows reviewed
missing/duplicate/unknown/source mismatch = 0
published concepts use only audited source facts
```

- [ ] **Step 7: Pin the runtime asset**

Add one logical manifest SHA constant to `app/guide_runtime/composition.py`.
Load and verify the asset once during runtime composition. Add a drift test
that changes concept bytes while preserving the path and expects startup to
fail.

## Task 3: Define One-Call TurnMeaning

**Files:**

- Create:
  `app/guide/understanding/turn_meaning_contracts.py`
- Create:
  `app/guide/adapters/llm/turn_meaning_prompt.py`
- Test:
  `tests/guide/understanding/test_turn_meaning_contracts.py`
- Test:
  `tests/guide/adapters/test_turn_meaning_prompt.py`

- [ ] **Step 1: Write contract RED tests**

Contract fields:

```text
operation_hint
topic_hint
reference_mentions
product_mentions
budget_candidates
observation_candidates
preference_candidates
relative_candidates
question_meaning
safety_language
```

Raw mentions contain exact text but no model offsets.

Forbid:

```text
IDs
state operations
final constraints
TaskPlan
scores/winner
catalog facts
answers
```

- [ ] **Step 2: Write prompt RED tests**

The prompt contains one schema and the reviewed compact concept catalog. It
must not contain:

```text
case IDs
fixture messages
route/detail stages
state operations
product data
long-tail synonym lists
```

- [ ] **Step 3: Run RED**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/understanding/test_turn_meaning_contracts.py \
  tests/guide/adapters/test_turn_meaning_prompt.py
```

- [ ] **Step 4: Implement minimal strict contracts and prompt**

Use a compact catalog generated from the locked parent-concept asset. The
catalog lists concept identities, not user phrase aliases.

- [ ] **Step 5: Run GREEN**

Run the focused tests and existing semantic forbidden-field suites.

## Task 4: Build One-Call Provider Adapters

**Files:**

- Create:
  `app/guide/adapters/llm/deepseek_turn_meaning.py`
- Create:
  `app/guide/adapters/llm/siliconflow_turn_meaning.py`
- Modify:
  `app/guide_runtime/composition.py`
- Test:
  `tests/guide/adapters/test_deepseek_turn_meaning.py`
- Test:
  `tests/guide/adapters/test_siliconflow_turn_meaning.py`
- Test:
  `tests/guide/runtime/test_composition_understanding.py`

- [ ] **Step 1: Write one-call RED tests**

Use mock transports and assert:

```text
one HTTP request for executable turns
one HTTP request for clarification turns
zero repair/reviewer requests
strict schema parsing
forbidden output rejection
secret redaction
usage accounting
```

- [ ] **Step 2: Run RED**

Expected: new adapters unavailable.

- [ ] **Step 3: Implement adapters**

Reuse `OpenAIJsonClient`, provider safety, usage limits, identity, and cache
primitives. Cache one complete `TurnMeaning`, not route/detail fragments.

- [ ] **Step 4: Switch runtime composition**

Production `build_text_understanding` constructs the single-call adapter.
Keep old two-stage adapters importable only for frozen control tests; they are
not the production lane.

- [ ] **Step 5: Run GREEN and import boundary**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/adapters/test_deepseek_turn_meaning.py \
  tests/guide/adapters/test_siliconflow_turn_meaning.py \
  tests/guide/runtime/test_composition_understanding.py \
  tests/guide/runtime/test_import_boundary.py
```

## Task 5: Ground Source and Resolve References

**Files:**

- Create:
  `app/guide/understanding/source_grounding.py`
- Create:
  `app/guide/intent/reference_admission.py`
- Test:
  `tests/guide/understanding/test_source_grounding.py`
- Test:
  `tests/guide/intent/test_reference_admission.py`

- [ ] **Step 1: Write grounding RED tests**

Cover:

```text
unique exact raw text
wrong offsets no longer relevant
missing raw text rejected
repeated raw text remains ambiguous
no substring invention
```

- [ ] **Step 2: Write reference RED tests**

Cover:

```text
"第二款" -> candidate 2
"第一张图" -> image 1
"图一" -> image 1
"这个" + focused product -> current product
"它" + focused image only -> current image
"两支" + current candidate batch -> current batch
"另一个" without unique baseline -> clarification
candidate/image collision -> clarification unless family hint resolves it
out-of-range ordinal -> clarification
```

Tests assert bindings and clarification codes, not phrase-specific
production branches.

- [ ] **Step 3: Run RED**

- [ ] **Step 4: Implement general grounding and admission**

Model family/ordinal/plurality values are hints. Code checks current authority
and returns a typed admitted binding or typed ambiguity.

Do not add a phrase alias registry. Exact parsers may prove closed forms but
cannot veto a uniquely admitted ordinary semantic reference.

- [ ] **Step 5: Re-evaluate saved eight pilot outputs**

Use the unchanged evidence:

```text
/private/tmp/xiaoro-single-call-semantic-pilot-20260815/results.jsonl
```

Expected:

- current item and current batch label disagreements resolve by authority;
- `另一个` remains non-executable and clarifies;
- no paid provider call.

## Task 6: Compile Executable Meaning and Preserve Code-Owned State

**Files:**

- Create:
  `app/guide/intent/executable_intent_compiler.py`
- Modify:
  `app/guide/understanding/parallel_understanding.py`
- Modify:
  `app/guide/intent/signal_merger.py`
- Modify:
  `app/guide/intent/task_planning.py`
- Modify:
  `app/guide/intent/transition_planning.py`
- Test:
  `tests/guide/intent/test_executable_intent_compiler.py`
- Test:
  `tests/guide/intent/test_constraint_transitions.py`
- Test:
  `tests/guide/intent/test_signal_merger.py`

- [ ] **Step 1: Write executable-admission RED tests**

Test:

```text
operation hint plus valid binding -> executable goal
operation hint plus unresolved binding -> clarification
topic hint plus exact narrower category -> canonical topic
ordinary semantic preference survives missing exact phrase proof
hard/safety candidate still requires safety policy
```

- [ ] **Step 2: Write state invariant RED tests**

Preserve:

```text
unmentioned constraint retain
same value retain
replacement needs current-turn proof
removal is value-bound
fresh request noninheritance
semantic cannot weaken safety
```

- [ ] **Step 3: Run RED**

- [ ] **Step 4: Implement compiler and simplify merger**

The exact lane supplies proofs and vetoes impossible/hard conflicts. It is not
a co-equal open-language classifier.

Keep `reduce_constraint_state` as the only state mutation authority.

- [ ] **Step 5: Run focused GREEN**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/understanding \
  tests/guide/intent
```

## Task 7: Compile Common Concepts and Free Descriptors

**Files:**

- Create:
  `app/guide/intent/concept_preferences.py`
- Modify:
  `app/guide/intent/contracts.py`
- Modify:
  `app/guide/intent/task_planning.py`
- Test:
  `tests/guide/intent/test_concept_preferences.py`
- Test:
  `tests/guide/intent/test_task_planning.py`

- [ ] **Step 1: Write RED tests**

Cover:

```text
"想镇定泛红" -> efficacy.soothing
"清爽又舒缓" -> texture.refreshing + efficacy.soothing
unsupported "雨后潮湿木头感" -> free descriptor, no concept constraint
same concept repeated -> one query slot
avoid polarity preserved
safety strength cannot become ordinary soft preference
profile-inapplicable concept rejected
```

- [ ] **Step 2: Run RED**

- [ ] **Step 3: Implement concept compiler**

The model selects only reviewed concept IDs. Code validates profile/field
applicability against the locked concept asset.

Unsupported descriptors remain available to ProductEvidence query meaning but
do not enter structured rank.

- [ ] **Step 4: Run GREEN**

Run intent and ProductEvidence focused suites.

## Task 8: Correct Soft Ranking Semantics

**Files:**

- Create:
  `app/guide/decision/concept_ranking.py`
- Modify:
  `app/guide/decision/facet_ranking.py`
- Modify:
  `app/guide/decision/recommendation.py`
- Modify:
  `app/guide/decision/contracts.py`
- Test:
  `tests/guide/decision/test_concept_ranking.py`
- Test:
  `tests/guide/decision/test_recommendation.py`

- [ ] **Step 1: Write RED tests**

Required cases:

```text
舒缓 / 舒缓泛红 / 舒缓皮肤不适 -> one soothing slot
multiple sources for one concept -> max strength once
no concept evidence -> unknown, not mismatch
explicit opposing reviewed fact -> mismatch
merchant positive safety ignored in serious safety mode
different concepts score independently
free descriptor cannot alter order
hard exclusion always dominates soft concept
```

- [ ] **Step 2: Run RED**

- [ ] **Step 3: Implement ranking**

Use the content-addressed parent-concept reader. Preserve exact source refs and
attribution in each matched slot.

Do not reinterpret strength 2 as a stronger product effect; it is stronger
evidence only.

- [ ] **Step 4: Run GREEN**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/decision/test_concept_ranking.py \
  tests/guide/decision/test_recommendation.py
```

## Task 9: Add Bounded Relative Comparison

**Files:**

- Create:
  `app/guide/decision/relative_comparison.py`
- Modify:
  `app/guide/intent/contracts.py`
- Modify:
  `app/guide/intent/task_planning.py`
- Modify:
  `app/guide/application/text_recommendation_flow.py`
- Test:
  `tests/guide/decision/test_relative_comparison.py`
- Test:
  `tests/guide/application/test_text_recommendation_flow.py`

- [ ] **Step 1: Write RED tests**

Cover:

```text
candidate 2 + price lower
current item + refreshing support
current item + soothing evidence fit
coverage ordered values when present
missing baseline -> clarification
unsupported dimension -> evidence gap
binary evidence cannot claim stronger effect
```

- [ ] **Step 2: Run RED**

- [ ] **Step 3: Implement relation planner**

Outputs distinguish:

```text
numeric/ordered comparison
better preference match
better evidence support
unsupported comparison
```

- [ ] **Step 4: Run GREEN**

Run decision, text flow, comparison, and follow-up suites.

## Task 10: Lock Ranking-to-Answer Evidence

**Files:**

- Modify:
  `app/guide/decision/contracts.py`
- Modify:
  `app/guide/application/product_evidence_answer.py`
- Modify:
  `app/guide/application/chat_api_adapter.py`
- Modify:
  `app/guide/presentation/sse_events.py`
- Test:
  `tests/guide/application/test_product_evidence_answer.py`
- Test:
  `tests/guide/application/test_chat_api_adapter.py`
- Test:
  `tests/guide/presentation/test_phase2_evidence_sse_contracts.py`
- Test:
  `tests/guide/presentation/test_response_planning.py`

- [ ] **Step 1: Write RED tests**

Assert:

```text
matched concept slot exposes exact source refs
answer reason uses one of the same refs
unrelated ProductEvidence cannot explain rank
free descriptor answer cannot change order
evidence-strength wording says stronger evidence, not stronger effect
```

- [ ] **Step 2: Run RED**

- [ ] **Step 3: Implement typed evidence alignment**

Do not add presenter-side ranking logic. The backend event carries already
validated source alignment.

- [ ] **Step 4: Run GREEN**

## Task 11: Re-Audit the 128-Case Semantic Truth

**Files:**

- Create:
  `docs/audits/semantic-turn-meaning/fixture_review_v1.jsonl`
- Create:
  `docs/audits/semantic-turn-meaning/architecture_checkpoint.md`
- Create:
  `tests/fixtures/guide/intent/turn_meaning_gate_v1.jsonl`
- Create:
  `tools/guide_gates/run_real_turn_meaning_gate.py`
- Test:
  `tests/guide/tools/test_run_real_turn_meaning_gate.py`
- Test:
  `tests/guide/tools/test_turn_meaning_gate.py`

- [ ] **Step 1: Audit every row manually**

For all 128 rows record:

```text
required translation atoms
allowed equivalents
don't-care fields
forbidden atoms
binding expectations
final task/state expectation
```

Correct known contradictions such as:

```text
post-cleanse topic truth
equivalent image spans
reasonable sensitivity concern output
revision references already owned by exact code
semantic request versus executable clarification
```

- [ ] **Step 2: Write gate RED tests**

The gate must fail:

- full JSON equality scoring;
- two provider calls;
- repair calls;
- invented raw text;
- state/result mismatch;
- hard safety violations.

- [ ] **Step 3: Implement one-call gate**

Report per layer and family:

```text
translation
grounding
binding
TaskPlan/state
decision
runtime
```

- [ ] **Step 4: Add metamorphic holdout**

Generate deterministic transformations without a model:

```text
benign filler
clause reordering
equivalent punctuation
reference-preserving paraphrase fixtures
unmentioned-state invariants
```

No transformed message is inserted into the prompt.

- [ ] **Step 5: Run local gate**

Expected before official execution:

```text
all fixture contracts valid
one-call assertion active
hard gates active
offline deterministic cases green
```

## Task 12: Cross-Vertical Frontend Handoff Matrix

**Files:**

- Modify:
  `docs/audits/backend-handoff/handoff_matrix_v1.jsonl`
- Modify:
  `tests/guide/runtime/test_backend_handoff_matrix.py`
- Create:
  `docs/audits/backend-handoff/frontend_gate_matrix_v1.jsonl`

- [ ] **Step 1: Add common concept and relative cases**

Add:

```text
舒缓 request -> soothing concept rank
清爽舒缓 -> two slots
unknown concept evidence -> unknown
explicit opposing evidence -> mismatch
more affordable candidate
better refreshing match
stronger soothing evidence wording
unsupported comparison evidence gap
```

- [ ] **Step 2: Preserve all existing vertical cases**

Profile, image, consultation, product/general knowledge, recommendation,
comparison, and follow-up remain green.

- [ ] **Step 3: Run matrix**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/runtime/test_backend_handoff_matrix.py
```

## Task 13: Full Local Gates

- [ ] **Step 1: Run focused semantic/concept suites**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/understanding \
  tests/guide/intent \
  tests/guide/decision \
  tests/guide/retrieval/test_selection_parent_concept_contracts.py \
  tests/guide/retrieval/test_selection_parent_concept_assets.py \
  tests/guide/retrieval/test_selection_parent_concept_reader.py \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/runtime/test_backend_handoff_matrix.py
```

- [ ] **Step 2: Run Guide full once**

```bash
.venv/bin/python -m pytest -q tests/guide
```

Poll until exit; do not duplicate.

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
git diff --cached --name-only
shasum -a 256 app/static/chat.html
```

Expected:

```text
all pass
staged index empty
frontend hash unchanged
```

## Task 14: Three Official One-Call Gates

- [ ] **Step 1: Confirm no old process**

```bash
ps -o pid,etime,state,command -ax | \
  rg "run_real_turn_meaning_gate|run_official_deepseek" | \
  rg -v "rg " || true
```

- [ ] **Step 2: Run official gate 1**

```bash
.venv/bin/python -m tools.guide_gates.run_real_turn_meaning_gate \
  --output-dir /private/tmp/xiaoro-turn-meaning-official-1
```

- [ ] **Step 3: Run official gate 2**

```bash
.venv/bin/python -m tools.guide_gates.run_real_turn_meaning_gate \
  --output-dir /private/tmp/xiaoro-turn-meaning-official-2
```

- [ ] **Step 4: Run official gate 3**

```bash
.venv/bin/python -m tools.guide_gates.run_real_turn_meaning_gate \
  --output-dir /private/tmp/xiaoro-turn-meaning-official-3
```

Each starts only after the previous run exits.

- [ ] **Step 5: Compare**

Record:

```text
provider call count
schema validity
translation coverage
invented source atoms
binding success
end-to-end success
unauthorized state transitions
unmentioned state changes
hard safety overrides
wrong product selections
ranking/answer source mismatches
p95
tokens
summary/evidence SHA
```

Frontend admission requires all hard counts zero and end-to-end common success
at least 90%.

## Task 15: Closure and Frontend Verdict

**Files:**

- Create:
  `docs/audits/semantic-turn-meaning/closure_report.md`
- Create:
  `docs/audits/selection-concepts/closure_report.md`
- Create:
  `docs/audits/backend-handoff/frontend_gate_closure.md`

- [ ] **Step 1: Architecture review**

Answer:

```text
Is there exactly one model request?
Does code own all bindings and state transitions?
Can exact parsing veto ordinary open semantics?
Can free descriptors alter rank?
Can absence of evidence become mismatch?
Can vector similarity or general knowledge influence rank?
Can ranking and answer cite different facts?
Does any provider/presenter duplicate business decisions?
```

- [ ] **Step 2: Failure review**

List every repeated failure, architecture checkpoint, general repair, rejected
patch, remaining limitation, and bounded fail-closed case.

- [ ] **Step 3: Publish verdict**

Publish `FRONTEND-GO` only when:

```text
end-to-end >= 90%
provider calls = 1 per turn
all hard safety/state/product/source errors = 0
local gates green
frontend bytes frozen
```

Otherwise publish `NO-GO` with the earliest unclosed layer. Do not begin
frontend implementation in this goal.

- [ ] **Step 4: Stop cleanly**

Verify no Goal-started process remains. Do not commit, push, deploy, or alter
traffic.
