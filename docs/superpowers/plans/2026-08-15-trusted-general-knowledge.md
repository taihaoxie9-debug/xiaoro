# Trusted General Knowledge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking. The user explicitly forbids
> sub-agents; the main agent performs the full block audit.

**Goal:** Turn the 22 existing educational Markdown documents into an audited,
content-addressed Guide knowledge asset with deterministic retrieval, typed
citations, and bounded follow-up.

**Architecture:** Parse controlled Markdown structure into candidate blocks,
audit each block for allowed use, publish immutable JSONL assets, and retrieve
with deterministic lexical scoring loaded once per runtime. Product questions
remain on ProductEvidence; general knowledge never ranks or hard-filters
products.

**Tech Stack:** Python 3.11 standard library, Pydantic v2 strict/frozen
contracts, SHA-256 JSONL manifests, pytest, existing Guide SSE and SQLite
conversation state.

---

## 0. Execution Rules

**Repository:** `/Users/bytedance/Desktop/xiaoro-fresh`

**Branch:** `rebuild`

Use the existing dirty worktree. Preserve unrelated changes.

Do not:

- dispatch sub-agents;
- import `app.services.knowledge_base` or `app.services.rag`;
- crawl web sources in this phase;
- add PostgreSQL, embedding, Milvus, or another LLM call;
- use general knowledge for product facts, ranking, hard filters, profile
  writes, or safety guarantees;
- modify frontend rendering;
- push or deploy.

For a long-running test/build command, start it once and poll every 30 seconds
until exit. Do not duplicate the process.

After two same-layer failures, stop editing and write the earliest-layer
analysis before selecting a general fix. No title-specific or question-specific
retrieval patches.

Every production change follows RED → observed failure → GREEN.

The existing worktree contains approved uncommitted implementation. Do not
stage or commit implementation or asset files during this Goal. Record each
tested checkpoint and final path inventory in the closure report. Only these
new plan documents may be committed before execution.

## 1. File and Ownership Map

Create:

- `app/guide/retrieval/general_knowledge_contracts.py`
  Strict documents, blocks, manifests, queries, hits, and packets.
- `app/guide/retrieval/general_knowledge_assets.py`
  Content-addressed loader and manifest verification.
- `app/guide/retrieval/general_knowledge_retrieval.py`
  Deterministic query term extraction and scoring.
- `app/guide/application/general_knowledge_answer.py`
  Code-owned excerpt/citation rendering.
- `tools/guide_data/build_general_knowledge.py`
  Controlled Markdown parser and JSONL builder.
- `tools/guide_data/audit_general_knowledge.py`
  Review completeness and permission verifier.
- `data/guide_general_knowledge/reviews/*.jsonl`
  Main-agent block decisions.
- `data/guide_general_knowledge/general_knowledge_v1_manifest.json`
  Runtime asset lock.
- `tests/guide/retrieval/test_general_knowledge_contracts.py`
- `tests/guide/retrieval/test_general_knowledge_assets.py`
- `tests/guide/retrieval/test_general_knowledge_retrieval.py`
- `tests/guide/application/test_general_knowledge_answer.py`
- `tests/guide/tools/test_build_general_knowledge.py`
- `tests/guide/tools/test_audit_general_knowledge.py`
- `docs/audits/general-knowledge/architecture_checkpoint.md`
- `docs/audits/general-knowledge/closure_report.md`

Modify:

- `app/guide/application/text_recommendation_flow.py`
  Route product-free knowledge to the new retriever.
- `app/guide/feedback/contracts.py`
  Persist focused general-knowledge IDs and prior question.
- `app/guide/presentation/sse_events.py`
  Add typed general-knowledge citation event.
- `app/guide/application/chat_api_adapter.py`
  Preserve typed event in the public backend contract.
- `app/guide_runtime/composition.py`
  Load the pinned knowledge reader once.
- `tests/guide/application/test_text_recommendation_flow.py`
- `tests/guide/runtime/test_composition.py`
- `tests/guide/runtime/test_frontend_scope.py`
  Freeze frontend bytes; do not render the new event.

## Task 1: Define Strict General-Knowledge Contracts

**Files:**

- Create: `app/guide/retrieval/general_knowledge_contracts.py`
- Create: `tests/guide/retrieval/test_general_knowledge_contracts.py`

- [ ] **Step 1: Write RED contract tests**

Use the desired API:

```python
block = GeneralKnowledgeBlock(
    knowledge_id=expected_id,
    document_id=document_id,
    title="防晒怎么选",
    section_title="怎么选",
    exact_text="SPF针对UVB，PA针对UVA。",
    source_path="data/knowledge_docs/06-防晒怎么选.md",
    source_sha256="a" * 64,
    block_sha256="b" * 64,
    section_order=2,
    review_decision="general_answer",
    allowed_uses={"answer", "citation", "followup"},
    forbidden_uses={
        "product_fact",
        "hard_filter",
        "soft_rank",
        "safety_guarantee",
        "profile_write",
    },
    review_rationale="通用防晒指标解释，不指向具体商品。",
    retrieval_terms=("spf", "pa", "uvb", "uva", "防晒"),
)
```

Assert:

- IDs are deterministic content hashes;
- published answer blocks require answer/citation permissions;
- every block forbids product fact, hard filter, soft rank, safety guarantee,
  and profile write;
- `escalation_only` forbids ordinary answer use;
- `product_specific_redirect` forbids answer use;
- rejected blocks cannot enter runtime assets;
- paths are repository-relative and cannot contain `..`;
- source refs and terms are sorted unique tuples;
- query and packet ordering is deterministic.

- [ ] **Step 2: Run tests and verify RED**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/retrieval/test_general_knowledge_contracts.py
```

Expected: import failure.

- [ ] **Step 3: Implement minimal contracts**

Add:

```python
def general_knowledge_id(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()
```

Implement strict/frozen:

```text
GeneralKnowledgeDocument
GeneralKnowledgeBlock
GeneralKnowledgeManifest
GeneralKnowledgeQuery
GeneralKnowledgeHit
GeneralKnowledgePacket
```

Use explicit literals from the design spec.

- [ ] **Step 4: Run contract tests**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/retrieval/test_general_knowledge_contracts.py
```

Expected: PASS.

- [ ] **Step 5: Record the contract checkpoint**

Record the focused pass count and changed paths. Do not stage or commit
implementation files.

## Task 2: Build Candidate Blocks from Controlled Markdown

**Files:**

- Create: `tools/guide_data/build_general_knowledge.py`
- Create: `tests/guide/tools/test_build_general_knowledge.py`

- [ ] **Step 1: Write RED parser tests**

Test one H1, H2 ordering, paragraphs, and list groups:

```python
source = """# 防晒怎么选

导语。

## 关键成分/原理

SPF针对UVB。

- PA针对UVA。
- 海边需要防水抗汗。
"""
```

Expected blocks preserve exact source text, heading ownership, source order,
and SHA identity.

Reject:

```text
missing H1
two H1 headings
text before H1
H3 without H2
empty H2
duplicate source path
oversized paragraph
```

- [ ] **Step 2: Run parser tests and verify RED**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/tools/test_build_general_knowledge.py
```

Expected: missing builder import.

- [ ] **Step 3: Implement the controlled parser**

Parse line structure, not arbitrary character windows:

```python
def parse_knowledge_document(
    path: Path,
    *,
    repo_root: Path,
) -> ParsedKnowledgeDocument:
    ...
```

Keep paragraph and contiguous-list boundaries. Normalize line endings only;
do not rewrite source claims.

- [ ] **Step 4: Add deterministic retrieval terms**

Implement:

```python
def retrieval_terms(*parts: str) -> tuple[str, ...]:
    # lowercase ASCII words + Chinese characters + Chinese bigrams
```

Do not add a domain keyword dictionary. Terms come only from source text.

- [ ] **Step 5: Run builder tests**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/tools/test_build_general_knowledge.py
```

Expected: PASS.

## Task 3: Audit Every Candidate Block

**Files:**

- Create: `data/guide_general_knowledge/reviews/*.jsonl`
- Create: `tools/guide_data/audit_general_knowledge.py`
- Create: `tests/guide/tools/test_audit_general_knowledge.py`

- [ ] **Step 1: Generate the review candidate inventory**

Run the builder in candidate mode:

```bash
.venv/bin/python -m tools.guide_data.build_general_knowledge \
  --source-dir data/knowledge_docs \
  --candidate-output /private/tmp/xiaoro-general-knowledge-candidates.jsonl
```

Record candidate count and aggregate SHA before reviewing.

- [ ] **Step 2: Write RED audit tests**

Assert the audit fails for:

```text
missing review
duplicate review
unknown block ID
empty rationale
answer permission on escalation-only block
product-specific block authorized as general answer
missing mandatory forbidden uses
source SHA mismatch
```

- [ ] **Step 3: Run audit tests and verify RED**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/tools/test_audit_general_knowledge.py
```

Expected: missing audit implementation.

- [ ] **Step 4: Implement the completeness auditor**

Return typed counts:

```text
candidate_total
reviewed_total
missing_total
general_answer
escalation_only
product_specific_redirect
rejected
permission_mismatches
invalid_reviews
```

`--require-clean` exits nonzero unless every candidate has one valid review.

- [ ] **Step 5: Main agent reviews every candidate**

For every row, inspect the exact source block and write one decision:

```json
{
  "candidate_id": "...",
  "review_decision": "general_answer",
  "allowed_uses": ["answer", "citation", "followup"],
  "forbidden_uses": [
    "product_fact",
    "hard_filter",
    "soft_rank",
    "safety_guarantee",
    "profile_write"
  ],
  "review_rationale": "通用教育内容，不声明诊断或具体商品事实。"
}
```

Rules:

- pregnancy, medication, severe symptoms, and open wounds are at most
  `escalation_only`;
- current product formula, price, and comparison paragraphs are
  `product_specific_redirect` or rejected;
- unsupported absolutes are rejected;
- duplicate filler is rejected;
- no automatic vocabulary scan may grant permission.

- [ ] **Step 6: Run clean audit**

```bash
.venv/bin/python -m tools.guide_data.audit_general_knowledge \
  --candidate /private/tmp/xiaoro-general-knowledge-candidates.jsonl \
  --review-dir data/guide_general_knowledge/reviews \
  --require-clean
```

Expected:

```text
missing_total = 0
permission_mismatches = 0
invalid_reviews = 0
```

- [ ] **Step 7: Write the audit checkpoint**

Create `docs/audits/general-knowledge/architecture_checkpoint.md` with:

- counts by decision, source document, and section;
- every product-specific block disposition;
- every pregnancy/medical block disposition;
- why no block can rank or hard-filter a product;
- examples of accepted, escalation, redirect, and rejected blocks.

## Task 4: Publish and Lock Content-Addressed Assets

**Files:**

- Create: `app/guide/retrieval/general_knowledge_assets.py`
- Create: `tests/guide/retrieval/test_general_knowledge_assets.py`
- Create: `data/guide_general_knowledge/general_knowledge_v1.<sha>.jsonl`
- Create: `data/guide_general_knowledge/general_knowledge_v1_manifest.json`
- Modify: `app/guide_runtime/composition.py`
- Modify: `tests/guide/runtime/test_composition.py`

- [ ] **Step 1: Write RED asset tests**

Assert:

- manifest logical self-hash;
- JSONL filename matches content hash;
- all source SHAs match current Markdown;
- no rejected block is published;
- runtime block order is deterministic;
- every published block has a clean audit;
- builder rerun is byte-identical;
- runtime rejects a manifest hash mismatch.

- [ ] **Step 2: Run asset tests and verify RED**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/retrieval/test_general_knowledge_assets.py \
  tests/guide/runtime/test_composition.py
```

Expected: missing loader and composition lock.

- [ ] **Step 3: Implement asset loader and manifest verification**

Expose:

```python
def load_general_knowledge_assets(
    manifest_path: Path,
    *,
    expected_manifest_sha256: str,
) -> GeneralKnowledgeAssets:
    ...
```

Validate before returning any block.

- [ ] **Step 4: Build production assets**

```bash
.venv/bin/python -m tools.guide_data.build_general_knowledge \
  --source-dir data/knowledge_docs \
  --review-dir data/guide_general_knowledge/reviews \
  --output-dir data/guide_general_knowledge
```

- [ ] **Step 5: Pin the manifest in composition**

Add one reader instance per runtime. Do not load JSONL per request.

- [ ] **Step 6: Run asset and composition tests**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/retrieval/test_general_knowledge_assets.py \
  tests/guide/runtime/test_composition.py
```

Expected: PASS.

- [ ] **Step 7: Record the audited-asset checkpoint**

Record audit counts, asset hashes, focused pass counts, and changed paths.
Confirm `git diff --cached --name-only` is empty.

## Task 5: Implement Deterministic Retrieval

**Files:**

- Create: `app/guide/retrieval/general_knowledge_retrieval.py`
- Create: `tests/guide/retrieval/test_general_knowledge_retrieval.py`

- [ ] **Step 1: Write RED ranking tests**

Freeze:

```text
"SPF和PA分别是什么意思" -> 防晒/关键成分 section
"烟酰胺有什么作用" -> 烟酰胺/关键成分 section
"敏感肌怎么判断" -> 判断敏感肌 section
"口红通勤怎么选" -> 唇妆/怎么选 section
unrelated weather query -> no hit
same query -> byte-identical ordered IDs
prior IDs boost only a related follow-up
product-specific redirect cannot outrank a general block for education
```

- [ ] **Step 2: Run retrieval tests and verify RED**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/retrieval/test_general_knowledge_retrieval.py
```

Expected: missing retriever import.

- [ ] **Step 3: Implement query term extraction and scoring**

Use source-derived terms only. Score title/section phrase, coverage,
rare-term overlap, topic compatibility, and bounded prior-block boost.

Expose:

```python
class GeneralKnowledgeRetriever:
    def retrieve(
        self,
        query: GeneralKnowledgeQuery,
    ) -> GeneralKnowledgePacket:
        ...
```

- [ ] **Step 4: Implement deterministic gap threshold**

The threshold is tested against the frozen corpus and stored as a named
constant. Do not add per-question thresholds.

- [ ] **Step 5: Run retrieval tests**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/retrieval/test_general_knowledge_retrieval.py
```

Expected: PASS.

## Task 6: Add Typed Answer and SSE Contracts

**Files:**

- Create: `app/guide/application/general_knowledge_answer.py`
- Create: `tests/guide/application/test_general_knowledge_answer.py`
- Modify: `app/guide/presentation/sse_events.py`
- Modify: `app/guide/application/chat_api_adapter.py`
- Modify: `tests/guide/application/test_chat_api_adapter.py`

- [ ] **Step 1: Write RED renderer and SSE tests**

Assert:

- exact excerpts and source titles are present;
- `educational_only=True`;
- escalation blocks produce an escalation boundary;
- product-specific redirect never appears as a general product fact;
- no hit produces an explicit evidence gap;
- local absolute paths and SHA values never enter user-visible prose;
- unknown fields are rejected by strict SSE contracts.

- [ ] **Step 2: Run tests and verify RED**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/application/test_general_knowledge_answer.py \
  tests/guide/application/test_chat_api_adapter.py
```

Expected: missing renderer/event failures.

- [ ] **Step 3: Implement citation data**

Add:

```python
class GeneralKnowledgeCitationData(_Strict):
    knowledge_id: str
    title: str
    section_title: str
    exact_excerpt: str
    source_path: str
    review_decision: Literal[
        "general_answer",
        "escalation_only",
        "product_specific_redirect",
    ]


class GeneralKnowledgeData(_Strict):
    query: str
    citations: list[GeneralKnowledgeCitationData]
    educational_only: Literal[True] = True
    medical_escalation: bool
```

Add typed `GeneralKnowledgeEvent`.

- [ ] **Step 4: Implement code-owned renderer**

Render only selected exact excerpts, headings, educational boundary, and
escalation copy. Do not invoke an answer LLM.

- [ ] **Step 5: Run renderer and public-contract tests**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/application/test_general_knowledge_answer.py \
  tests/guide/application/test_chat_api_adapter.py \
  tests/guide/test_public_contracts.py
```

Expected: PASS.

## Task 7: Connect Knowledge and Follow-Up

**Files:**

- Modify: `app/guide/application/text_recommendation_flow.py`
- Modify: `app/guide/feedback/contracts.py`
- Modify: `app/guide_runtime/composition.py`
- Modify: `tests/guide/application/test_text_recommendation_flow.py`
- Modify: `tests/guide/application/test_query_context.py`
- Modify: `tests/guide/runtime/test_composition.py`

- [ ] **Step 1: Write RED flow cases**

Freeze:

```text
product knowledge -> ProductEvidence only
general knowledge -> GeneralKnowledge only
ambiguous product -> clarification
general no-hit -> evidence gap
general follow-up -> bounded prior-ID boost
unrelated fresh question -> no prior knowledge inheritance
medical block -> escalation
general block -> cannot change profile or recommendation state
```

- [ ] **Step 2: Run flow tests and verify RED**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/runtime/test_composition.py
```

Expected: product-free knowledge still returns the current missing-evidence
message.

- [ ] **Step 3: Extend conversation snapshot**

Add immutable fields:

```python
focused_general_knowledge_ids: tuple[str, ...] = ()
last_general_knowledge_question: str | None = None
```

Validate sorted/unique IDs and bounded question length.

- [ ] **Step 4: Route knowledge by bound product identity**

Implement:

```text
product_ids -> product evidence
no product_ids -> general knowledge
```

Do not merge packets.

- [ ] **Step 5: Persist general knowledge focus**

After a general answer, save selected IDs and the question with CAS semantics.
General follow-up uses them as a boost. Fresh unrelated tasks clear them.

- [ ] **Step 6: Run application, state, and runtime tests**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/application/test_cross_worker_text_state.py \
  tests/guide/adapters/state \
  tests/guide/runtime/test_composition.py \
  tests/guide/runtime/test_runtime_http.py
```

Expected: PASS.

- [ ] **Step 7: Freeze frontend bytes**

Run:

```bash
shasum -a 256 app/static/chat.html
```

Assert the existing frontend-scope test remains unchanged. Do not render the
new event.

## Task 8: Knowledge Architecture Audit and Closure

**Files:**

- Create: `docs/audits/general-knowledge/closure_report.md`

- [ ] **Step 1: Audit architecture**

Answer:

```text
Does Guide import app.services?
Can knowledge select or rank a product?
Can general knowledge satisfy a hard/safety constraint?
Can product-specific text leak into general answers?
Is every runtime block reviewed?
Is the asset loaded once?
Can a follow-up inherit unrelated knowledge?
Is any model generating unsupported knowledge prose?
```

- [ ] **Step 2: Run knowledge focused suite**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/retrieval/test_general_knowledge_contracts.py \
  tests/guide/retrieval/test_general_knowledge_assets.py \
  tests/guide/retrieval/test_general_knowledge_retrieval.py \
  tests/guide/application/test_general_knowledge_answer.py \
  tests/guide/tools/test_build_general_knowledge.py \
  tests/guide/tools/test_audit_general_knowledge.py \
  tests/guide/application/test_text_recommendation_flow.py
```

Expected: PASS.

- [ ] **Step 3: Run full local gates**

Start once and poll:

```bash
.venv/bin/python -m pytest -q tests/guide
.venv/bin/python -m pytest -q tests/guide/runtime
.venv/bin/python -m compileall -q app tools
.venv/bin/python -m pytest -q \
  tests/guide/test_architecture_boundaries.py \
  tests/guide/runtime/test_import_boundary.py
git diff --check
```

Expected: PASS.

- [ ] **Step 4: Write closure report**

Include:

- 22 source documents and source SHAs;
- candidate/review/published counts;
- decision and permission counts;
- manifest and JSONL SHAs;
- representative retrievals and gaps;
- medical and product-specific boundary examples;
- tests and architecture audit;
- remaining risks;
- frontend handoff fields.

- [ ] **Step 5: Record the knowledge-runtime checkpoint**

Record the full local gate results and path inventory. Do not stage, commit,
push, or deploy implementation.
