# Product Knowledge Coverage Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make all 1,079 accepted `answer` ProductEvidence blocks deterministically reachable, assemble up to three complementary facts for multi-aspect product questions, publish an honest 103-product coverage inventory, and pass two consecutive real DeepSeek/backend/SSE/browser runs without weakening evidence permissions or general-knowledge isolation.

**Architecture:** Extend the existing `EvidenceQuery -> ProductEvidenceRetriever -> ProductPublicFactProjection -> ProductKnowledgeAnswerPlan` path with code-owned question dimensions and per-selection coverage metadata. Keep the existing unified router and the single product-evidence retriever; use deterministic coverage-diverse ordering and answer selection, then enforce the result with an asset-wide gate, a reviewed FAQ rewrite matrix, a catalog coverage audit, and the existing browser runner.

**Tech Stack:** Python 3.11, Pydantic v2, FastAPI, pytest, DeepSeek V4 Pro, SSE, vanilla JavaScript, Playwright

---

## Execution Policy

Implement only in:

```text
/Users/bytedance/Desktop/xiaoro-fresh/.tmp-product-knowledge-coverage-worktree
```

Do not modify:

```text
/Users/bytedance/Desktop/xiaoro-shopping-master
```

Use TDD for every production change:

1. add the narrow failing contract;
2. run it and preserve the RED output;
3. repair the earliest shared owner;
4. run the focused GREEN suite;
5. commit the coherent change.

For an ordinary deterministic, backend, SSE, browser, or full-suite failure,
continue autonomously. Do not repeatedly call the model to obtain a lucky
pass. Repair the stable owner, rerun the focused deterministic gate, remove
only rejected generated evidence, and restart both real runs from run 1.

Stop only for missing credentials, a persistent external provider outage, a
destructive operation requiring approval, or a repair outside this approved
scope.

Before every commit:

```bash
git status --short
git diff --check
```

Stage only files owned by the current task. Never stage credentials, temporary
state databases, browser profiles, `.dbg` files, or unrelated audit output.

## Scope And File Ownership

**Question dimensions and retrieval coverage**

- Modify: `app/guide/application/product_evidence_answer.py`
- Modify: `app/guide/retrieval/product_evidence_retrieval.py`
- Modify: `tests/guide/application/test_product_evidence_answer.py`
- Modify: `tests/guide/retrieval/test_product_evidence_retrieval.py`

**Coverage-aware public fact selection**

- Modify: `app/guide/presentation/product_detail_selection.py`
- Modify: `app/guide/application/unified_guide_flow.py`
- Modify: `app/guide/application/text_recommendation_flow.py`
- Modify: `tests/guide/presentation/test_product_detail_selection.py`
- Modify: `tests/guide/application/test_text_recommendation_flow.py`

**Deterministic product-knowledge gate**

- Create:
  `tests/fixtures/guide/product_knowledge/product_knowledge_faq_rewrites_v1.jsonl`
- Create: `tools/guide_gates/run_product_knowledge_coverage_gate.py`
- Create: `tests/guide/tools/test_run_product_knowledge_coverage_gate.py`
- Generate:
  `docs/audits/product-knowledge/coverage-closure/deterministic/`

**Canonical catalog coverage audit**

- Create: `tools/guide_data/audit_product_knowledge_coverage.py`
- Create: `tests/guide/data/test_product_knowledge_coverage.py`
- Generate:
  `docs/audits/product-knowledge/coverage-closure/catalog-coverage.json`
- Generate:
  `docs/audits/product-knowledge/coverage-closure/catalog-coverage.md`

**Architecture and browser acceptance**

- Modify: `app/static/guide-presentation.js`
- Modify: `app/static/chat.html`
- Modify: `tests/guide/runtime/test_frontend_presentation_stream.py`
- Modify: `tests/guide/runtime/test_frontend_scope.py`
- Modify: `tools/guide_gates/check_single_path_architecture.py`
- Modify: `tests/guide/tools/test_single_path_architecture.py`
- Modify: `tests/guide/tools/test_no_sentence_patch.py`
- Modify: `tools/guide_gates/run_mainline_contract_browser_audit.py`
- Modify:
  `tests/guide/tools/test_run_mainline_contract_browser_audit.py`
- Generate:
  `docs/audits/product-knowledge/coverage-closure/real-run-01/`
- Generate:
  `docs/audits/product-knowledge/coverage-closure/real-run-02/`

**Closure report**

- Create:
  `docs/audits/product-knowledge/coverage-closure/report.md`
- Update:
  `docs/superpowers/plans/2026-08-31-product-knowledge-coverage-closure.md`

Do not modify ProductEvidence content or manifests unless a test proves that an
accepted runtime row is internally invalid. Do not import `qa_facts` from
`seed_dump.sql` or `beauty_products_seed.json`.

### Task 1: Carry Typed Product-Knowledge Dimensions Through Retrieval

**Files:**

- Modify: `app/guide/application/product_evidence_answer.py`
- Modify: `app/guide/retrieval/product_evidence_retrieval.py`
- Test: `tests/guide/application/test_product_evidence_answer.py`
- Test: `tests/guide/retrieval/test_product_evidence_retrieval.py`

- [x] **Step 1: Write failing dimension-resolution and strict-contract tests**

Extend the existing dimension tests so class-level language maps to these
stable field keys:

```python
assert resolve_product_knowledge_dimensions(
    "核心成分、怎么用、容量多大？"
) == ("ingredients_present", "usage", "net_content")
assert resolve_product_knowledge_dimensions(
    "新版和旧版差在哪，瓶口有结晶正常吗？"
) == ("variant_difference", "packaging_information")
assert resolve_product_knowledge_dimensions(
    "怎么保存，批次怎么看，二维码怎么验真？"
) == ("storage", "batch", "authenticity")
assert resolve_product_knowledge_dimensions(
    "敏感肌用它一定安全吗？"
) == ("suitable_skin", "safety_information")
```

Add retrieval-contract tests proving:

```python
query = EvidenceQuery(
    product_ids=(57,),
    search=prepare_evidence_search(
        source_text="怎么涂不搓泥，运输后开盖会不会溢？",
        question_meaning="询问防晒涂法和运输后开盖溢出",
    ),
    safety_sensitive=False,
    requested_dimensions=("usage", "packaging_information"),
)

assert query.requested_dimensions == (
    "usage",
    "packaging_information",
)
```

Also assert that list input freezes to a tuple, duplicate or malformed
dimensions are rejected, and existing callers that omit the field receive
`()`.

- [x] **Step 2: Run focused tests and verify RED**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/application/test_product_evidence_answer.py \
  tests/guide/retrieval/test_product_evidence_retrieval.py \
  -k "dimension or requested"
```

Expected: failures show missing dimensions and the absent
`EvidenceQuery.requested_dimensions` field.

- [x] **Step 3: Expand the code-owned dimension resolver**

Keep `resolve_product_knowledge_dimensions()` deterministic and ordered by
field registry. Extend `keyword_by_field` with:

```python
"variant_difference": (
    "新旧版",
    "新版",
    "旧版",
    "版本区别",
    "版本差异",
    "升级",
),
"packaging_information": (
    "包装",
    "瓶口",
    "泵头",
    "颗粒",
    "结晶",
    "溢出",
    "漏",
),
"storage": (
    "保存",
    "储存",
    "避光",
    "高温",
    "低温",
),
"batch": (
    "批次",
    "批号",
    "生产日期",
    "有效期",
),
"authenticity": (
    "防伪",
    "验真",
    "真假",
    "二维码",
    "溯源",
),
"safety_information": (
    "安全",
    "刺激",
    "过敏",
    "孕妇",
    "哺乳",
    "破皮",
),
```

These are concept-family aliases. Do not branch on a product ID, evidence ID,
case ID, or complete user sentence.

- [x] **Step 4: Extend the strict retrieval contracts**

Add:

```python
class EvidenceQuery(_StrictFrozenModel):
    product_ids: tuple[int, ...] = Field(min_length=1, max_length=4)
    search: PreparedEvidenceSearch
    safety_sensitive: bool
    requested_dimensions: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=12,
    )
    product_identity_names: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=4,
    )
```

Freeze `requested_dimensions` and require ordered unique values matching
`^[a-z][a-z0-9_]{1,63}$`.

Extend `EvidenceSelection` with deterministic coverage metadata:

```python
covered_dimensions: tuple[str, ...] = Field(
    default_factory=tuple,
    max_length=12,
)
```

Freeze and validate it with the same ordered-unique rule. This metadata is
code-derived; the model never supplies it.

- [x] **Step 5: Run focused GREEN tests**

Run the command from Step 2.

Expected: all selected tests pass.

- [x] **Step 6: Commit**

```bash
git add \
  app/guide/application/product_evidence_answer.py \
  app/guide/retrieval/product_evidence_retrieval.py \
  tests/guide/application/test_product_evidence_answer.py \
  tests/guide/retrieval/test_product_evidence_retrieval.py
git commit -m "feat(guide): type product knowledge dimensions"
```

### Task 2: Make Existing Retrieval Coverage-Diverse

**Files:**

- Modify: `app/guide/retrieval/product_evidence_retrieval.py`
- Test: `tests/guide/retrieval/test_product_evidence_retrieval.py`

- [x] **Step 1: Write failing evidence-dimension and diversity tests**

Add fixture blocks for:

```text
usage:
  relation predicate merchant_faq_answer
  subject "减少搓泥"

packaging_information:
  relation predicate merchant_faq_answer
  subject "运输后开盖溢出"

variant_difference:
  relation predicate merchant_version_comparison_claim

storage:
  relation predicate merchant_storage_faq

batch:
  relation predicate merchant_batch_code_example

authenticity:
  relation predicate merchant_authentication_guidance

safety_information:
  management_label safety_transcript
```

For a two-aspect query, assert:

```python
packet = retriever.retrieve(query)

assert tuple(
    selection.covered_dimensions
    for selection in packet.selected[:2]
) == (
    ("usage",),
    ("packaging_information",),
)
```

Add negative tests proving:

- a block without `answer` is never selected;
- a block from another product is never selected;
- an explicitly named variant suppresses conflicting variant evidence;
- repeated retrieval serializes to identical bytes;
- dimension diversity never admits a zero-score block.

- [x] **Step 2: Run the retrieval tests and verify RED**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q tests/guide/retrieval/test_product_evidence_retrieval.py \
  -k "coverage or dimension or non_answer or cross_product or variant"
```

Expected: coverage tuples are empty and score ordering does not guarantee one
selected block per requested aspect.

- [x] **Step 3: Derive dimensions from evidence classes and relations**

Add a private `_evidence_dimensions()` helper that uses:

```python
label_dimensions = {
    "usage": ("usage",),
    "product_specification": ("net_content",),
    "packaging_information": ("packaging_information",),
    "safety_transcript": ("safety_information",),
}
```

For relation predicates, tokenize by `_` and map concept families:

```python
relation_dimensions = (
    ({"version", "comparison"}, "variant_difference"),
    ({"storage"}, "storage"),
    ({"batch", "expiry"}, "batch"),
    ({"authenticity", "authentication"}, "authenticity"),
    ({"skin", "age", "suitability"}, "suitable_skin"),
    ({"usage", "action", "cleanse", "application"}, "usage"),
    ({"package", "packaging", "pump", "overflow"}, "packaging_information"),
)
```

Return dimensions in `query.requested_dimensions` order, followed by sorted
remaining dimensions. Keep the mapping product-neutral.

- [x] **Step 4: Apply deterministic coverage-diverse ordering**

After score sorting and variant handling, order positive-score selections as:

1. the highest-scoring selection covering each still-uncovered requested
   dimension, in request order;
2. remaining selections in the existing `(-score, evidence_id)` order;
3. existing deduplication and `per_product_limit`;
4. existing global `total_limit`.

Construct each selection with:

```python
EvidenceSelection(
    evidence=block,
    score=score,
    reasons=tuple(reasons),
    covered_dimensions=_evidence_dimensions(
        block,
        requested_dimensions=query.requested_dimensions,
    ),
)
```

Do not widen the 5-per-product or 8-per-packet limits.

- [x] **Step 5: Run the complete retrieval suite**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/retrieval/test_product_evidence_retrieval.py \
  tests/guide/retrieval/test_product_evidence_assets.py
```

Expected: all tests pass.

- [x] **Step 6: Commit**

```bash
git add \
  app/guide/retrieval/product_evidence_retrieval.py \
  tests/guide/retrieval/test_product_evidence_retrieval.py
git commit -m "feat(guide): diversify product evidence coverage"
```

### Task 3: Select Up To Three Complementary Public Facts

**Files:**

- Modify: `app/guide/presentation/product_detail_selection.py`
- Modify: `app/guide/application/product_evidence_answer.py`
- Test: `tests/guide/presentation/test_product_detail_selection.py`
- Test: `tests/guide/application/test_product_evidence_answer.py`

- [x] **Step 1: Write failing multi-evidence answer tests**

Build a projection with three evidence facts:

```python
facts = (
    _projected_fact(
        "evidence:usage",
        "faq",
        "使用问答",
        "精简护肤，吸收后同向推开。",
        source_kind="merchant",
    ),
    _projected_fact(
        "evidence:overflow",
        "faq",
        "使用问答",
        "运输后瓶口朝上静置2小时再打开。",
        source_kind="merchant",
    ),
    _projected_fact(
        "evidence:unrelated",
        "faq",
        "使用问答",
        "全身使用时肤感偏水润。",
        source_kind="merchant",
    ),
)
coverage = {
    "evidence:usage": ("usage",),
    "evidence:overflow": ("packaging_information",),
    "evidence:unrelated": ("texture",),
}
```

For requested `("usage", "packaging_information")`, assert:

```python
assert plan.used_fact_ids == (
    "evidence:usage",
    "evidence:overflow",
)
assert "同向推开" in plan.answer_text
assert "静置2小时" in plan.answer_text
assert "全身使用" not in plan.answer_text
assert plan.covered_dimensions == (
    "usage",
    "packaging_information",
)
assert plan.missing_dimensions == ()
```

Add tests for:

- one requested aspect uses one direct evidence fact and does not dump other
  FAQ rows;
- evidence is preferred over a duplicate Category Fact for the same aspect;
- Category Facts fill uncovered requested aspects;
- two covered aspects plus one missing aspect render the two facts and one
  explicit missing line;
- repeated meaning or same normalized value is displayed once;
- public facts remain capped at three;
- no selected fact returns the existing honest no-information answer.

- [x] **Step 2: Run answer-selection tests and verify RED**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/presentation/test_product_detail_selection.py \
  tests/guide/application/test_product_evidence_answer.py \
  -k "product_knowledge or complementary or missing_dimension"
```

Expected: only the first evidence fact is selected and coverage fields do not
exist.

- [x] **Step 3: Extend the answer-plan contract**

Add:

```python
class ProductKnowledgeAnswerPlan(_StrictFrozenModel):
    answer_text: str = Field(min_length=1, max_length=1600)
    direct_facts: tuple[ProjectedPublicFact, ...] = Field(
        default_factory=tuple,
        max_length=3,
    )
    used_fact_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=3,
    )
    requested_dimensions: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=12,
    )
    covered_dimensions: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=12,
    )
    missing_dimensions: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=12,
    )
```

Validate:

```text
used_fact_ids == direct_facts.fact_id
covered_dimensions is a subset of requested_dimensions
missing_dimensions == requested_dimensions - covered_dimensions
all dimension tuples are ordered unique
```

- [x] **Step 4: Make product-knowledge selection coverage-aware**

Extend `select_product_detail_facts()` with:

```python
evidence_dimensions: Mapping[str, Collection[str]] | None = None
```

Only the `PRODUCT_KNOWLEDGE` branch consumes this mapping. Its order is:

1. evidence facts that cover an uncovered requested dimension;
2. Category Facts that cover an uncovered requested dimension;
3. when no dimensions were recognized, only the first evidence fact;
4. never add a fact that contributes no new requested coverage;
5. stop at three facts.

Deduplicate by both `fact_id` and normalized `(field_key, display_value)`.
Recommendation, comparison, and image identity behavior must remain unchanged.

- [x] **Step 5: Build honest answer coverage**

Change `build_product_knowledge_answer_plan()` to accept:

```python
evidence_dimensions: Mapping[str, Collection[str]] | None = None
```

Compute coverage from selected fact IDs and Category Fact field keys. Render a
missing line only for requested dimensions not covered by the selected facts:

```python
"这款目前没有明确标注的"
f"{_PUBLIC_LABEL_BY_KEY.get(field_key, '相关')}信息。"
```

Add public labels for:

```python
"variant_difference": "版本差异",
"packaging_information": "包装异常",
"storage": "储存",
"batch": "批次",
"authenticity": "防伪",
"safety_information": "安全说明",
```

- [x] **Step 6: Run focused and neighboring GREEN tests**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/presentation/test_product_detail_selection.py \
  tests/guide/presentation/test_public_fact_projection.py \
  tests/guide/application/test_product_evidence_answer.py
```

Expected: all tests pass.

- [x] **Step 7: Commit**

```bash
git add \
  app/guide/presentation/product_detail_selection.py \
  app/guide/application/product_evidence_answer.py \
  tests/guide/presentation/test_product_detail_selection.py \
  tests/guide/application/test_product_evidence_answer.py
git commit -m "fix(guide): assemble complementary product facts"
```

### Task 4: Wire Coverage Through The Existing Product-Knowledge Flow

**Files:**

- Modify: `app/guide/application/unified_guide_flow.py`
- Modify: `app/guide/application/text_recommendation_flow.py`
- Test: `tests/guide/application/test_text_recommendation_flow.py`
- Test: `tests/guide/application/test_text_presentation_integration.py`

- [x] **Step 1: Write failing orchestration tests**

Add one explicit-product test and one current-item follow-up test. The first
query asks two aspects whose packet contains two matching evidence rows. Assert:

```python
assert result.decision.responsibility is Responsibility.PRODUCT_KNOWLEDGE
assert terminal.data.mode == "product_knowledge"
assert "同向推开" in terminal.data.public_copy.text
assert "静置2小时" in terminal.data.public_copy.text
assert terminal.data.public_copy.used_fact_ids == (
    f"evidence:{usage_id}",
    f"evidence:{overflow_id}",
)
```

For the follow-up, bind the current product from conversation state and assert
the same product ID is queried without a new explicit product mention.

Add a safety test proving an ordinary merchant claim cannot replace the
existing `_SAFETY_GAP_CAVEAT`.

- [x] **Step 2: Run orchestration tests and verify RED**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/application/test_text_presentation_integration.py \
  -k "product_knowledge and (multi or current or safety)"
```

Expected: the query lacks requested dimensions or the terminal copy contains
only one evidence fact.

- [x] **Step 3: Pass dimensions into the existing query**

In `_execute_product_evidence_task()` construct:

```python
query = EvidenceQuery(
    product_ids=tuple(task.product_ids),
    search=evidence_search,
    safety_sensitive=task.safety_sensitive,
    requested_dimensions=requested_dimensions,
    product_identity_names=self._product_identity_names(
        task.product_ids,
        product_resolution=product_resolution,
    ),
)
```

Resolve `requested_dimensions` before creating the query. Do not add a second
retrieval call.

- [x] **Step 4: Pass selected coverage to the answer planner**

Build:

```python
evidence_dimensions = {
    f"evidence:{item.evidence.evidence_id}": item.covered_dimensions
    for item in packet.selected
}
```

Pass it to `build_product_knowledge_answer_plan()`. Continue publishing the
entire audited `ProductEvidenceEvent` packet, while
`authoritative_public_copy.used_fact_ids` contains only the facts actually
shown to the user.

- [x] **Step 5: Run the product flow suites**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/application/test_text_presentation_integration.py \
  tests/guide/presentation/test_presentation_compiler.py \
  tests/guide/presentation/test_copy_evidence_validation.py
```

Expected: all tests pass.

- [x] **Step 6: Commit**

```bash
git add \
  app/guide/application/text_recommendation_flow.py \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/application/test_text_presentation_integration.py
git commit -m "feat(guide): publish product evidence coverage"
```

### Task 5: Add The Asset-Wide Product-Knowledge Gate

**Files:**

- Modify: `app/guide/retrieval/product_evidence_reader.py`
- Modify: `app/guide/retrieval/product_evidence_retrieval.py`
- Modify: `tests/guide/retrieval/test_product_evidence_retrieval.py`
- Create:
  `tests/fixtures/guide/product_knowledge/product_knowledge_faq_rewrites_v1.jsonl`
- Create: `tools/guide_gates/run_product_knowledge_coverage_gate.py`
- Create: `tests/guide/tools/test_run_product_knowledge_coverage_gate.py`
- Generate:
  `docs/audits/product-knowledge/coverage-closure/deterministic/`

- [x] **Step 1: Define the reviewed FAQ rewrite fixture**

Use this strict row schema:

```python
class ProductKnowledgeFaqCase(_StrictFrozenModel):
    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]+$")
    category: Literal[
        "ingredients",
        "usage",
        "specification",
        "skin_fit",
        "texture",
        "version",
        "packaging",
        "storage",
        "batch",
        "authenticity",
        "safety",
        "other",
    ]
    product_id: int = Field(gt=0)
    product_name: str = Field(min_length=1, max_length=160)
    evidence_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    direct_question: str = Field(min_length=1, max_length=256)
    question_meaning: str = Field(min_length=1, max_length=256)
    paraphrases: tuple[str, ...] = Field(default_factory=tuple, max_length=4)
    expected_dimensions: tuple[str, ...] = ()
    safety_sensitive: bool = False
```

Create exactly one row for each of the 47 accepted FAQ blocks. Bind each row to
the audited `evidence_id`; never bind by product name alone. Direct questions
must describe the evidence relation subject, and representative rows in every
listed category must include a natural paraphrase.

Examples:

```json
{"case_id":"faq-057-overflow","category":"packaging","product_id":57,"product_name":"碧柔Biore水活防晒水润凝蜜","evidence_id":"e3ee0783aa62d423918907246ca3084f9f82bf24a301857a78d88aab56a6a785","direct_question":"运输后打开这款防晒会溢出来吗？","question_meaning":"询问运输后开盖溢出和处理办法","paraphrases":["刚收到一开盖会不会喷出来？"],"expected_dimensions":["packaging_information"],"safety_sensitive":false}
{"case_id":"faq-120-alcohol-opening","category":"other","product_id":120,"product_name":"祖玛珑英国梨与小苍兰香水","evidence_id":"d452a07760f04eccd2e280a0174b48370f5f3cf35537189aba82ecbf89a2302f","direct_question":"刚喷时为什么酒精味很重？","question_meaning":"询问刚喷时酒精气味和等待时间","paraphrases":["第一下有点冲鼻子，放几分钟会好吗？"],"expected_dimensions":[],"safety_sensitive":false}
{"case_id":"faq-075-low-temperature-crystal","category":"storage","product_id":75,"product_name":"透明质酸钠修复贴","evidence_id":"6d04fe2892485e44b3cf9713faa78c0c2726814508515f8e83222fd5e2407404","direct_question":"低温出现白色结晶是什么情况？","question_meaning":"询问低温结晶原因和使用边界","paraphrases":["天冷后里面有白色晶体还能怎么看？"],"expected_dimensions":["packaging_information","storage"],"safety_sensitive":true}
```

- [x] **Step 2: Write failing gate tests**

Test that the gate rejects:

- a fixture that does not cover all 47 FAQ evidence IDs exactly once;
- a direct question or paraphrase whose expected evidence is outside Top 5;
- any miss among the 1,079 answerable evidence self-queries;
- a non-`answer` block appearing in ordinary answer results;
- any selected product ID outside `EvidenceQuery.product_ids`;
- a conflicting explicit variant;
- nondeterministic repeated retrieval;
- a multi-aspect case whose public answer omits an available dimension;
- a single-aspect case that displays an unrelated FAQ;
- output files that differ between identical runs.

The production assertion is:

```python
assert report.answerable_count == 1079
assert report.answerable_top5_count == 1079
assert report.faq_count == 47
assert report.faq_direct_top5_count == 47
assert report.non_answer_selection_count == 0
assert report.cross_product_selection_count == 0
assert report.wrong_variant_selection_count == 0
assert report.answer_coverage_failure_count == 0
assert report.deterministic_mismatch_count == 0
assert report.passed
```

- [x] **Step 3: Run gate tests and verify RED**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/tools/test_run_product_knowledge_coverage_gate.py
```

Expected: import or assertion failure because the gate and fixture are absent.

- [x] **Step 4: Implement the deterministic gate**

The gate must load only runtime-pinned assets via:

```python
reader = build_product_evidence_reader(repo_root)
retriever = ProductEvidenceRetriever(reader)
```

For every accepted `answer` block, query with its audited `plain_meaning`,
product ID, variant scope when present, and derived dimensions. Count success
when the exact evidence ID appears in Top 5.

For every accepted block without `answer`, run the same query and count a
failure if that exact evidence ID appears.

For FAQ rows, run `direct_question` and each paraphrase independently. Re-run
every query and compare `packet.model_dump_json()` byte-for-byte.

Write only these owned files, replacing them on repeat:

```text
results.jsonl
summary.json
SHA256SUMS
```

The CLI is:

```bash
python tools/guide_gates/run_product_knowledge_coverage_gate.py \
  --repo-root . \
  --cases tests/fixtures/guide/product_knowledge/product_knowledge_faq_rewrites_v1.jsonl \
  --output docs/audits/product-knowledge/coverage-closure/deterministic
```

- [x] **Step 5: Run focused GREEN tests and the production gate**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/tools/test_run_product_knowledge_coverage_gate.py

PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/run_product_knowledge_coverage_gate.py \
  --repo-root . \
  --cases \
  tests/fixtures/guide/product_knowledge/product_knowledge_faq_rewrites_v1.jsonl \
  --output \
  docs/audits/product-knowledge/coverage-closure/deterministic
```

Expected: the locked counts above are green and the CLI exits 0.

- [x] **Step 6: Commit**

```bash
git add \
  tests/fixtures/guide/product_knowledge/product_knowledge_faq_rewrites_v1.jsonl \
  tools/guide_gates/run_product_knowledge_coverage_gate.py \
  tests/guide/tools/test_run_product_knowledge_coverage_gate.py \
  docs/audits/product-knowledge/coverage-closure/deterministic
git commit -m "test(guide): gate product knowledge coverage"
```

### Task 6: Publish The 103-Product Coverage And Gap Inventory

**Files:**

- Create: `tools/guide_data/audit_product_knowledge_coverage.py`
- Create: `tests/guide/data/test_product_knowledge_coverage.py`
- Generate:
  `docs/audits/product-knowledge/coverage-closure/catalog-coverage.json`
- Generate:
  `docs/audits/product-knowledge/coverage-closure/catalog-coverage.md`

- [x] **Step 1: Write failing audit tests**

Use tiny fake readers to assert each row contains:

```python
{
    "product_id": 38,
    "identity": "理肤泉新B5多效修护精华",
    "identity_status": "valid",
    "answerable_evidence_count": 3,
    "faq_count": 1,
    "category_fact_count": 5,
    "covered_fields": [
        "efficacy",
        "ingredients_present",
        "suitable_skin",
    ],
    "missing_priority_fields": ["usage"],
}
```

Assert:

- rows are sorted by product ID;
- all 103 Canonical IDs appear exactly once;
- ProductEvidence and Category Facts remain separate source counts;
- PID 90 and PID 100 are reported as invalid/placeholder identities;
- missing fields remain missing and are never filled from raw `qa_facts`;
- two identical runs produce identical JSON and Markdown bytes.

- [x] **Step 2: Run audit tests and verify RED**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/data/test_product_knowledge_coverage.py
```

Expected: import failure because the audit module is absent.

- [x] **Step 3: Implement the source-aware audit**

Load:

```python
canonical = CanonicalProductReader.from_files(
    manifest_path=root / "data/canonical/core_products_v1_manifest.json",
    products_path=root / "data/canonical/core_products_v1.jsonl",
)
category_facts = build_category_fact_reader(canonical, repo_root=root)
evidence = build_product_evidence_reader(root)
```

For each sorted `canonical.product_ids`, record:

- normalized Canonical identity;
- identity status (`valid`, `underspecified`, or `placeholder`);
- accepted answer evidence count;
- FAQ count;
- accepted evidence management labels;
- known Category Fact fields;
- union of answerable evidence dimensions and known Category Fact fields;
- missing priority fields for the product category;
- a remediation class:
  `already_available`, `review_required`, `catalog_cleanup`, or
  `honest_unknown`.

Treat `"000"`, `"无"`, and brand-only identities as catalog cleanup entries.
This report is read-only and must not modify Canonical, Category Facts, or
ProductEvidence.

- [x] **Step 4: Generate and verify the production report**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_data/audit_product_knowledge_coverage.py \
  --repo-root . \
  --json-output \
  docs/audits/product-knowledge/coverage-closure/catalog-coverage.json \
  --markdown-output \
  docs/audits/product-knowledge/coverage-closure/catalog-coverage.md
```

Expected summary:

```text
canonical_product_count=103
product_evidence_product_count=86
category_fact_product_count=92
union_covered_product_count=98
```

The report must explicitly list PIDs 60, 72, 90, 93, and 100 and distinguish
content gaps from identity cleanup.

- [x] **Step 5: Run GREEN tests**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/data/test_product_knowledge_coverage.py \
  tests/guide/data/test_selected_catalog_runtime_coverage.py
```

Expected: all tests pass.

- [x] **Step 6: Commit**

```bash
git add \
  tools/guide_data/audit_product_knowledge_coverage.py \
  tests/guide/data/test_product_knowledge_coverage.py \
  docs/audits/product-knowledge/coverage-closure/catalog-coverage.json \
  docs/audits/product-knowledge/coverage-closure/catalog-coverage.md
git commit -m "docs(guide): audit product knowledge gaps"
```

### Task 7: Lock Permission, Isolation, And No-Patch Boundaries

**Files:**

- Modify: `tools/guide_gates/check_single_path_architecture.py`
- Modify: `tests/guide/tools/test_single_path_architecture.py`
- Modify: `tests/guide/tools/test_no_sentence_patch.py`
- Test: `tests/guide/application/test_general_knowledge_answer.py`
- Test: `tests/guide/retrieval/test_general_knowledge_retrieval.py`

- [x] **Step 1: Write failing architecture and anti-patch checks**

Add assertions that production code contains:

```text
one ProductEvidenceRetriever class
one product_knowledge execution branch
one UnifiedGuideFlow pre-routing path
zero text embedding imports under product evidence
zero reads of seed_dump.sql or beauty_products_seed.json from runtime
zero ProductEvidence imports in GeneralKnowledgeRetriever
zero full fixture question strings in app/guide
zero product_id/evidence_id/case_id branch conditions in changed production files
```

Add a general-knowledge regression proving a question without a concrete
product cannot emit a ProductEvidence citation.

- [x] **Step 2: Run boundary tests and verify RED**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/tools/test_single_path_architecture.py \
  tests/guide/tools/test_no_sentence_patch.py \
  tests/guide/application/test_general_knowledge_answer.py \
  tests/guide/retrieval/test_general_knowledge_retrieval.py
```

Expected: the new product-knowledge architecture assertions are absent or fail.

- [x] **Step 3: Extend the existing architecture scanner**

Inspect Python AST imports and call sites rather than raw substring counts.
Keep the existing gate as the single architecture scanner. Add product
knowledge checks beside the existing GeneralKnowledge checks; do not create a
parallel scanner.

The anti-patch fixture must reject this shape:

```python
if query == "碧柔防晒怎么涂才不搓泥":
    return SPECIAL_EVIDENCE_ID
```

It must allow class-level mappings such as relation predicate families and
dimension aliases.

- [x] **Step 4: Run GREEN boundary tests and the general-knowledge gate**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/tools/test_single_path_architecture.py \
  tests/guide/tools/test_no_sentence_patch.py \
  tests/guide/application/test_general_knowledge_answer.py \
  tests/guide/retrieval/test_general_knowledge_retrieval.py

PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/run_general_knowledge_recall_gate.py \
  --cases \
  tests/fixtures/guide/general_knowledge/general_knowledge_recall_v1.jsonl \
  --output \
  docs/audits/product-knowledge/coverage-closure/general-knowledge-regression
```

Expected:

```text
Recall@3=1.0
wrong topic=0
wrong section=0
entity failure=0
relation failure=0
deterministic mismatch=0
```

- [x] **Step 5: Commit**

```bash
git add \
  tools/guide_gates/check_single_path_architecture.py \
  tests/guide/tools/test_single_path_architecture.py \
  tests/guide/tools/test_no_sentence_patch.py \
  tests/guide/application/test_general_knowledge_answer.py \
  tests/guide/retrieval/test_general_knowledge_retrieval.py \
  docs/audits/product-knowledge/coverage-closure/general-knowledge-regression
git commit -m "test(guide): lock product knowledge boundaries"
```

### Task 8: Add And Run Two Real Product-Knowledge Browser Passes

**Files:**

- Modify: `app/static/guide-presentation.js`
- Modify: `app/static/chat.html`
- Modify: `tests/guide/runtime/test_frontend_presentation_stream.py`
- Modify: `tests/guide/runtime/test_frontend_scope.py`
- Modify: `tools/guide_gates/run_mainline_contract_browser_audit.py`
- Modify:
  `tests/guide/tools/test_run_mainline_contract_browser_audit.py`
- Generate:
  `docs/audits/product-knowledge/coverage-closure/real-run-01/`
- Generate:
  `docs/audits/product-knowledge/coverage-closure/real-run-02/`

- [x] **Step 1: Write failing trajectory and usefulness tests**

Extend `BoundedBrowserTurn` with:

```python
expected_product_ids: tuple[int, ...] = ()
expected_product_evidence_ids: tuple[str, ...] = ()
expected_used_fact_ids: tuple[str, ...] = ()
required_answer_text: tuple[str, ...] = ()
forbidden_answer_text: tuple[str, ...] = ()
```

Add `PRODUCT_KNOWLEDGE_TRAJECTORIES` for these eight scenarios:

```text
pk-core-ingredients:
  "理肤泉新B5多效修护精华确认有哪些核心成分？"

pk-faq-paraphrase:
  "祖玛珑英国梨与小苍兰刚喷出来有点冲，等几分钟会好吗？"

pk-version-difference:
  "赫莲娜绿宝瓶第六代跟旧版主要改了什么？"

pk-packaging-storage:
  "透明质酸钠修复贴低温后出现白色结晶，该怎么看？"

pk-current-item:
  t1 "薇诺娜舒敏保湿丝滑面膜先给我已确认资料。"
  t2 "那它具体怎么敷，敷完要洗吗？"

pk-multi-aspect:
  "碧柔Biore水活防晒水润凝蜜怎么涂不搓泥，运输后开盖会不会溢？"

pk-no-evidence:
  "灵芝焕能强韧精华水明确标注了哪些核心成分？"

pk-safety:
  "薇诺娜舒敏保湿丝滑面膜做完特殊美容项目后一定安全吗？"
```

The validator must reject wrong responsibility, wrong product binding, missing
expected evidence, evidence outside the product scope, missing used facts,
missing visible answer text, forbidden safety guarantees, missing product
card, missing citation/evidence UI, frontend contract errors, console errors,
or a malformed SSE lifecycle.

Add frontend reducer/rendering tests proving the guide-owned presentation
appends one evidence section after the answer/full-card content and preserves
`data-evidence-id` plus `data-guide-product-id` on each visible ProductEvidence
row. General-knowledge citations remain in their existing dedicated panel.

- [x] **Step 2: Run browser-runner tests and verify RED**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/tools/test_run_mainline_contract_browser_audit.py \
  -k "product_knowledge_coverage"
```

Expected: the trajectory set and product-evidence usefulness checks are absent.

- [x] **Step 3: Extend the existing browser runner**

Add CLI choice `product_knowledge` and dispatch it through the existing
`run_bounded_browser_audit()`. Capture the existing files for every turn:

```text
request.json
stream.sse
presentation-contract.json
terminal-dom.json
screenshot.png
console.json
network.json
```

Validate evidence IDs from the `product_evidence` SSE event and public fact IDs
from the `presentation_contract` event. Validate visible text from the same
terminal DOM and screenshot turn.

Wire `createEvidenceLayer()` into `renderPresentation()` and stop clearing
`deferredPanels.productEvidence` before the guide-owned renderer consumes it.
Render only ProductEvidence rows whose product IDs are visible, and attach:

```text
data-evidence-id="<64 hex evidence ID>"
data-guide-product-id="<canonical product ID>"
```

- [x] **Step 4: Run focused GREEN tests**

Run the command from Step 2.

Expected: all selected tests pass.

- [x] **Step 5: Start a clean real runtime**

Use the credential file without printing or committing its value:

```bash
export GUIDE_LLM_API_KEY="$(
  cat /Users/bytedance/Desktop/deepseek-key.txt
)"
export GUIDE_LLM_BASE_URL="https://api.deepseek.com"
export GUIDE_LLM_MODEL="deepseek-v4-pro"
export GUIDE_LLM_FORMAT_REPAIR_ATTEMPTS="0"
export GUIDE_COPY_LLM_API_KEY="$GUIDE_LLM_API_KEY"
export GUIDE_COPY_LLM_BASE_URL="$GUIDE_LLM_BASE_URL"
export GUIDE_COPY_LLM_MODEL="$GUIDE_LLM_MODEL"
export XIAORO_GUIDE_STATE_DIR="/tmp/xiaoro-product-knowledge-coverage"

/Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/uvicorn \
  app.guide_runtime.app:app \
  --host 127.0.0.1 \
  --port 8843
```

- [x] **Step 6: Run two consecutive real browser passes**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/run_mainline_contract_browser_audit.py \
  --base-url http://127.0.0.1:8843 \
  --trajectory-set product_knowledge \
  --viewport desktop \
  --output \
  docs/audits/product-knowledge/coverage-closure/real-run-01

PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/run_mainline_contract_browser_audit.py \
  --base-url http://127.0.0.1:8843 \
  --trajectory-set product_knowledge \
  --viewport desktop \
  --output \
  docs/audits/product-knowledge/coverage-closure/real-run-02
```

Expected per run:

```text
trajectory_count=8
turn_count=9
passed_turn_count=9
wrong responsibility=0
wrong product binding=0
missing expected evidence=0
cross-product evidence=0
answer coverage mismatch=0
frontend contract violation=0
console error=0
passed=true
```

If either run fails, preserve its directory, diagnose and repair the earliest
owner, rerun Tasks 5 and 7, write new clean run directories, and require two
new consecutive passes.

- [x] **Step 6: Commit**

```bash
git add \
  tools/guide_gates/run_mainline_contract_browser_audit.py \
  tests/guide/tools/test_run_mainline_contract_browser_audit.py \
  docs/audits/product-knowledge/coverage-closure/real-run-01 \
  docs/audits/product-knowledge/coverage-closure/real-run-02
git commit -m "test(guide): verify real product knowledge coverage"
```

### Task 9: Run Full Regression, Close The Report, And Push

**Files:**

- Create:
  `docs/audits/product-knowledge/coverage-closure/report.md`
- Update:
  `docs/superpowers/plans/2026-08-31-product-knowledge-coverage-closure.md`
- Modify only the earliest owner of any reproducible regression.

- [x] **Step 1: Run the focused product-knowledge suite**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/retrieval/test_product_evidence_assets.py \
  tests/guide/retrieval/test_product_evidence_retrieval.py \
  tests/guide/presentation/test_public_fact_projection.py \
  tests/guide/presentation/test_product_detail_selection.py \
  tests/guide/application/test_product_evidence_answer.py \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/application/test_text_presentation_integration.py \
  tests/guide/tools/test_run_product_knowledge_coverage_gate.py \
  tests/guide/data/test_product_knowledge_coverage.py \
  tests/guide/tools/test_run_mainline_contract_browser_audit.py
```

Expected: all tests pass.

- [x] **Step 2: Run deterministic product and general knowledge gates**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/run_product_knowledge_coverage_gate.py \
  --repo-root . \
  --cases \
  tests/fixtures/guide/product_knowledge/product_knowledge_faq_rewrites_v1.jsonl \
  --output \
  docs/audits/product-knowledge/coverage-closure/deterministic

PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/run_general_knowledge_recall_gate.py \
  --cases \
  tests/fixtures/guide/general_knowledge/general_knowledge_recall_v1.jsonl \
  --output \
  docs/audits/product-knowledge/coverage-closure/general-knowledge-regression
```

Expected: both commands exit 0 with their locked counts.

- [x] **Step 3: Run architecture and anti-patch gates**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/tools/test_no_sentence_patch.py \
  tests/guide/tools/test_single_path_architecture.py \
  tests/guide/test_architecture_boundaries.py
```

Expected:

```text
one unified router
one ProductEvidenceRetriever
one GeneralKnowledgeRetriever
no product evidence in general knowledge
no raw qa_facts runtime read
no text-vector dependency
no sentence/product/evidence ID production patch
```

- [x] **Step 4: Run the complete regression and static checks**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q

PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m compileall -q app tools

git diff --check
```

Expected: all tests and static checks pass.

- [x] **Step 5: Write the closure report**

Record:

```text
ProductEvidence manifest SHA-256
accepted answer evidence count
answerable Top5 count
FAQ direct and paraphrase counts
non-answer selection count
cross-product selection count
wrong-variant selection count
multi-aspect answer coverage failures
103-product coverage and gap summary
invalid identity list
general-knowledge Recall@3 and wrong-citation counts
real-run-01 result and evidence path
real-run-02 result and evidence path
full pytest result
remaining honest content gaps
```

State explicitly:

- raw `qa_facts` were not imported;
- no text vector path was added;
- ProductEvidence did not enter general knowledge;
- missing reviewed facts remain explicit unknowns;
- this is Demo closure, not strict production release approval.

- [x] **Step 6: Mark every completed plan checkbox**

Update this file so executed steps are `[x]`. Leave no checked item without
command output or committed evidence.

- [x] **Step 7: Inspect the final diff and staged files**

```bash
git status --short
git diff --stat
git diff -- \
  app/guide \
  tools/guide_data \
  tools/guide_gates \
  tests/guide \
  docs/audits/product-knowledge \
  docs/superpowers/specs/2026-08-31-product-knowledge-coverage-closure-design.md \
  docs/superpowers/plans/2026-08-31-product-knowledge-coverage-closure.md
```

Verify that no credential, temporary state, browser profile, rejected run,
unrelated audit directory, or change from the protected old repository is
staged.

- [x] **Step 8: Commit the report and plan completion**

```bash
git add \
  docs/audits/product-knowledge/coverage-closure/report.md \
  docs/superpowers/specs/2026-08-31-product-knowledge-coverage-closure-design.md \
  docs/superpowers/plans/2026-08-31-product-knowledge-coverage-closure.md
git commit -m "docs(guide): close product knowledge coverage"
```

- [ ] **Step 9: Push and verify the remote tree**

```bash
git push -u origin HEAD:wip/product-knowledge-coverage-closure
git rev-parse HEAD^{tree}
git ls-remote origin refs/heads/wip/product-knowledge-coverage-closure
```

Fetch the remote terminal commit and compare:

```bash
git fetch origin wip/product-knowledge-coverage-closure
test "$(
  git rev-parse HEAD^{tree}
)" = "$(
  git rev-parse FETCH_HEAD^{tree}
)"
```

If normal push reproduces the known remote object-pack failure, create a
tree-preserving snapshot commit whose tree is local `HEAD^{tree}` and whose
parent is a remote object already present on the server, push that snapshot,
then run the same local/remote tree comparison.

## Completion Criteria

The goal is complete only when all are true:

- 1,079/1,079 accepted `answer` ProductEvidence rows are Top-5 reachable;
- all 47 FAQ rows have one reviewed direct question and pass;
- representative natural rewrites across all required classes pass;
- repeated deterministic retrieval is byte-identical;
- non-`answer`, cross-product, and wrong-variant answer selections are zero;
- multi-aspect answers use up to three complementary facts;
- a focused single-aspect question does not dump unrelated FAQ content;
- partial evidence renders available facts plus explicit missing dimensions;
- all 103 Canonical products appear in the source-aware gap inventory;
- invalid identities are reported, not guessed;
- raw `qa_facts` are not imported;
- all existing 22 general-knowledge topics remain green at `Recall@3 = 100%`
  with zero wrong-topic and wrong-section citations;
- no text vector, second dispatcher, second product retriever, sentence patch,
  or ProductEvidence-to-general-knowledge path exists;
- both real DeepSeek/backend/SSE/browser runs pass consecutively;
- focused, architecture, anti-patch, and full pytest suites pass;
- `compileall` and `git diff --check` pass;
- the closure report is committed;
- the remote terminal tree equals the local terminal tree.
