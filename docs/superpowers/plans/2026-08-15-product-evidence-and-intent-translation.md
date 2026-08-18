# Product Evidence and Intent Translation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking. The user explicitly forbids
> sub-agents for this work.

**Goal:** Preserve every useful product-detail image statement as answerable
evidence, project only comparable evidence into ranking, and let indirect or
follow-up product questions retrieve grounded, product-scoped answers.

**Architecture:** Close the current Merchant Claim checkpoint first. Add a
content-addressed `EvidenceBlock` asset with an explicit per-image audit ledger,
then build a deterministic product-scoped retriever over raw text, unrestricted
question meaning, relations, qualifiers, FAQ text, and free descriptors. Wire
the retriever into the existing understanding and presentation boundaries;
do not create a second orchestrator.

**Tech Stack:** Python 3.11, Pydantic v2 strict/frozen contracts, JSONL,
SHA-256 manifests, pytest, RapidOCR/Pillow for assisted extraction, existing
Guide typed SSE and deterministic decision logic.

---

## 0. File and Ownership Map

Create these focused modules:

- `app/guide/retrieval/product_evidence_assets.py`
  Strict evidence, relation, qualifier, audit, manifest, and loader contracts.
- `app/guide/retrieval/product_evidence_reader.py`
  In-memory `product_id` index and storage-independent reader port.
- `app/guide/retrieval/product_evidence_retrieval.py`
  Deterministic product-scoped scoring and `EvidencePacket` construction.
- `app/guide/application/product_evidence_answer.py`
  Code-controlled attribution, qualifier, disclaimer, and citation rendering.
- `tools/guide_data/recover_product_detail_images.py`
  Exact old-asset, saved-HTML, and public-page recovery inventory.
- `tools/guide_data/build_product_evidence.py`
  Deterministic review/audit-to-content-addressed-asset builder.

Modify these existing boundaries only:

- `app/guide/understanding/semantic_detail_contracts.py`
  Carry unrestricted `question_meaning` and safety sensitivity.
- `app/guide/understanding/semantic_contracts.py`
  Carry the translated meaning through the merged proposal.
- `app/guide/understanding/contracts.py`
  Carry meaning into `StructuredUnderstanding`.
- `app/guide/intent/signal_merger.py`
  Project semantic meaning without converting it to a fixed intent enum.
- `app/guide/intent/contracts.py`
  Carry question meaning and safety sensitivity in `TaskPlan`.
- `app/guide/intent/task_planning.py`
  Compile the generic evidence query inputs without reading evidence.
- `app/guide/application/text_recommendation_flow.py`
  Execute product questions and attach relevant evidence to other task modes.
- `app/guide/presentation/sse_events.py`
  Add one typed `product_evidence` event.
- `app/guide/application/chat_api_adapter.py`
  Serialize the typed event.
- `app/guide_runtime/composition.py`
  Lock and compose the evidence asset and retriever.
- `app/static/chat.html`
  Render attributed evidence only if the current typed UI needs it.

Keep ranking in the current CategoryFact/Facet path. Do not make the evidence
reader a hidden ranking engine.

## Task 1: Close the 1,136-Claim Checkpoint

**Files:**
- Modify: `app/guide_runtime/composition.py:120-136`
- Modify: `tests/guide/runtime/test_composition.py:30-90`
- Modify: `tests/guide/data/test_merchant_claim_production_assets.py:12-140`
- Create:
  `data/guide_merchant_claims/raw_reviews/xiaoro_ocr_review_existing_expansion_suncare_20260814_summary.md`
- Create:
  `data/guide_merchant_claims/raw_reviews/xiaoro_ocr_review_existing_expansion_base_makeup_20260814_summary.md`
- Create:
  `data/guide_merchant_claims/raw_reviews/xiaoro_ocr_review_existing_expansion_color_makeup_20260814_summary.md`
- Create:
  `data/guide_merchant_claims/raw_reviews/xiaoro_ocr_review_existing_expansion_cleanser_20260814_summary.md`
- Create:
  `data/guide_merchant_claims/raw_reviews/xiaoro_ocr_review_existing_expansion_fragrance_20260814_summary.md`

- [ ] **Step 1: Write the failing lock expectations**

Set production expectations to:

```python
EXPECTED_MANIFEST_SHA256 = (
    "84e38beaa132f655597c8e5aafa577d2abd51ff17db14101f31be1a831ba7c9c"
)
EXPECTED_CLAIMS_SHA256 = (
    "8d69e82fb49842cc1a1b4c649bcad812d0d3c58e02ad3e163685fc4704cf3cc3"
)
```

Assert `claim_count == 1136`, `product_count == 98`,
`source_file_count == 103`, 23 raw review JSONL files, and 23 summary files.

- [ ] **Step 2: Run the lock tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/data/test_merchant_claim_production_assets.py \
  tests/guide/runtime/test_composition.py
```

Expected: failures for the old 1,106 lock and five missing summaries.

- [ ] **Step 3: Write the five exact summary files**

Each summary must identify its review JSONL, included product IDs, accepted
content types, safety handling, and exact-source rule. It must not claim a
test result that was not run.

- [ ] **Step 4: Update runtime locks**

Use:

```python
GUIDE_MERCHANT_CLAIM_ASSET_RELATIVE_PATH = (
    Path("data")
    / "guide_merchant_claims"
    / (
        "merchant_claims_v1."
        "8d69e82fb49842cc1a1b4c649bcad812d0d3c58e02ad3e163685fc4704cf3cc3"
        ".jsonl"
    )
)
GUIDE_MERCHANT_CLAIM_MANIFEST_SHA256 = (
    "84e38beaa132f655597c8e5aafa577d2abd51ff17db14101f31be1a831ba7c9c"
)
```

- [ ] **Step 5: Run focused checkpoint tests**

Run the command from Step 2.

Expected: all tests pass.

- [ ] **Step 6: Commit the checkpoint**

```bash
git add app/guide_runtime/composition.py \
  tests/guide/runtime/test_composition.py \
  tests/guide/data/test_merchant_claim_production_assets.py \
  data/guide_merchant_claims/raw_reviews/*existing_expansion*summary.md \
  data/guide_merchant_claims/merchant_claims_v1_manifest.json \
  data/guide_merchant_claims/merchant_claims_v1.8d69e82fb49842cc1a1b4c649bcad812d0d3c58e02ad3e163685fc4704cf3cc3.jsonl
git commit -m "data(guide): publish expanded merchant claims"
```

## Task 2: Define Loss-Resistant Evidence Contracts

**Files:**
- Create: `app/guide/retrieval/product_evidence_assets.py`
- Test: `tests/guide/retrieval/test_product_evidence_assets.py`

- [ ] **Step 1: Write RED contract tests**

Cover:

```python
def test_accepted_evidence_is_answerable_and_content_addressed() -> None:
    block = ProductEvidenceBlock.model_validate(
        {
            "evidence_id": expected_id,
            "product_id": 78,
            "subject_scope": "exact_product",
            "management_label": "consumer_self_report",
            "exact_text": "91%消费者认同水润舒缓",
            "plain_meaning": "消费者认同水润舒缓",
            "relations": [
                {
                    "subject": "91%",
                    "predicate": "consumer_agrees",
                    "object": "水润舒缓",
                }
            ],
            "qualifiers": {
                "sample_size": 35,
                "population": "18-35岁中国敏感肌消费者",
                "method": "消费者自评",
                "disclaimer": "结果仅供参考，实际结果因人而异",
            },
            "free_descriptors": ["水润舒缓", "消费者认同"],
            "review_status": "accepted",
            "allowed_uses": ["answer", "display", "weak_soft_rank"],
            "forbidden_uses": [
                "hard_filter",
                "safety_guarantee",
                "clinical_effectiveness",
            ],
            "source": source_payload,
        },
        strict=True,
    )
    assert "answer" in block.allowed_uses
```

Also assert:

- `accepted` requires `answer` unless it is a safety transcript;
- `blocked`, `ambiguous`, `irrelevant`, `expired`, `cross_product`, and
  `duplicate` cannot enter answer/rank projections;
- merchant safety claims cannot have `hard_filter`;
- consumer self-report cannot claim `clinical_effectiveness`;
- `evidence_id` and manifest SHA must match canonical JSON;
- source image SHA, source locator, and image index are mandatory.

- [ ] **Step 2: Run the tests and verify RED**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/retrieval/test_product_evidence_assets.py
```

Expected: import failure for the new module.

- [ ] **Step 3: Implement strict frozen contracts**

Implement these concrete types:

```python
EvidenceStatus = Literal[
    "accepted",
    "ambiguous",
    "irrelevant",
    "expired",
    "cross_product",
    "duplicate",
    "blocked",
]
ManagementLabel = Literal[
    "merchant_claim",
    "consumer_self_report",
    "merchant_cited_test",
    "packaging_information",
    "faq",
    "usage",
    "safety_transcript",
    "brand_research",
    "product_specification",
    "unclassified",
]
EvidenceUse = Literal[
    "answer",
    "display",
    "compare",
    "weak_soft_rank",
    "soft_rank",
    "hard_filter",
]
ForbiddenUse = Literal[
    "hard_filter",
    "safety_guarantee",
    "clinical_effectiveness",
    "cross_product_attribution",
]
```

Add `EvidenceRelation`, `EvidenceQualifiers`, `EvidenceSource`,
`ProductEvidenceBlock`, `ImageAuditRecord`, `ProductEvidenceManifest`, and
`ProductEvidenceAssets`. Use canonical JSON SHA functions matching existing
Merchant Claim assets.

- [ ] **Step 4: Run contract tests**

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app/guide/retrieval/product_evidence_assets.py \
  tests/guide/retrieval/test_product_evidence_assets.py
git commit -m "feat(guide): add product evidence contracts"
```

## Task 3: Build the Audit Ledger and Content-Addressed Asset

**Files:**
- Create: `tools/guide_data/build_product_evidence.py`
- Test: `tests/guide/tools/test_build_product_evidence.py`
- Create: `data/guide_product_evidence/reviews/`
- Create: `data/guide_product_evidence/image_audit/`

- [ ] **Step 1: Write RED builder tests**

The fixture must contain:

- one accepted FAQ block;
- one accepted consumer self-report with qualifiers;
- one safety transcript;
- one ambiguous block;
- one irrelevant image;
- one duplicate image reference.

Assert deterministic byte equality over two builds, sorted IDs, exact image
binding, no unreviewed image, and manifest counts by status and allowed use.

- [ ] **Step 2: Run builder tests and verify RED**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/tools/test_build_product_evidence.py
```

- [ ] **Step 3: Implement the builder**

The builder signature is:

```python
def build_product_evidence(
    *,
    source_root: str | Path,
    image_root: str | Path,
    audit_paths: tuple[Path, ...],
    review_paths: tuple[Path, ...],
    output_root: str | Path,
) -> ProductEvidenceBuildResult:
    ...
```

It must reject:

- a review block whose image is not in the bound OCR source;
- a source SHA or image SHA mismatch;
- accepted text not visible in the reviewed image transcript unless the row
  explicitly records `visual_transcription` and an image region;
- an image with no audit status;
- duplicate semantic rows without a duplicate back-reference;
- any forbidden safety capability.

- [ ] **Step 4: Run builder tests**

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tools/guide_data/build_product_evidence.py \
  tests/guide/tools/test_build_product_evidence.py \
  data/guide_product_evidence
git commit -m "feat(data): build audited product evidence"
```

## Task 4: Recover the 667 Missing Historical Images

**Files:**
- Create: `tools/guide_data/recover_product_detail_images.py`
- Test: `tests/guide/tools/test_recover_product_detail_images.py`
- Create: `data/guide_product_evidence/recovery_manifest_v1.jsonl`
- Modify: `data/guide_merchant_claims/source_ocr/detail_*_ocr.json`
  only when adding verified source URLs or local-image bindings.

- [ ] **Step 1: Write RED recovery precedence tests**

Test this exact precedence:

```text
exact old asset SHA
  > identity-matched saved HTML image
  > current public detail image as a new source version
  > blocked with attempted-source records
```

Assert a current replacement never receives the historical image SHA.

- [ ] **Step 2: Run recovery tests and verify RED**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/tools/test_recover_product_detail_images.py
```

- [ ] **Step 3: Implement deterministic inventory and recovery**

The tool must emit one row per referenced image:

```json
{
  "product_id": 50,
  "source_file": "detail_50_ocr.json",
  "image_index": 0,
  "historical_file": "O1CN....jpg",
  "status": "recovered_exact",
  "recovery_source": "old_asset",
  "local_image": "source_images/50/000_<sha>.jpg",
  "image_sha256": "<sha>",
  "attempts": ["old_asset_inventory"]
}
```

Blocked rows must list all attempted sources and a concrete reason.

- [ ] **Step 4: Run the recovery tool over all 972 references**

Use the old repo as read-only:

```bash
.venv/bin/python -m tools.guide_data.recover_product_detail_images \
  --source-root data/guide_merchant_claims/source_ocr \
  --image-root data/guide_merchant_claims/source_images \
  --old-root /Users/bytedance/Desktop/xiaoro-shopping-master \
  --output data/guide_product_evidence/recovery_manifest_v1.jsonl
```

Poll every 30 seconds. If the process stops making progress for 10 minutes,
inspect it, terminate its process group, clean only its temporary files, and
retry once.

- [ ] **Step 5: Verify recovery accounting**

Assert:

```text
recovered_exact + recovered_from_html + current_new_version + blocked = 972
```

Every non-blocked row must point to a real file whose SHA matches the row.

- [ ] **Step 6: Commit recovery tooling and inventory**

Do not claim blocked rows were visually reviewed.

## Task 5: Main-Agent Visual Review of All Available Images

**Files:**
- Create/modify:
  `data/guide_product_evidence/image_audit/<profile>_<batch>.jsonl`
- Create/modify:
  `data/guide_product_evidence/reviews/<profile>_<batch>.jsonl`
- Create:
  `data/guide_product_evidence/review_progress_v1.json`

- [ ] **Step 1: Generate a zero-decision review queue**

The queue may include OCR, dimensions, source URL, and existing claims, but it
must not auto-accept evidence.

- [ ] **Step 2: Review images product by product**

The main Agent personally inspects each available image. For every image:

- bind the subject: exact product, exact variant, brand, gift, bundle, or other;
- preserve useful complete statements and visual relationships;
- attach footnotes, sample size, population, method, baseline, duration, and
  disclaimer;
- add management label, zero or more free descriptors, allowed uses, and
  forbidden uses;
- record one explicit image status even when no evidence is accepted.

- [ ] **Step 3: Apply the safety policy during review**

Merchant "free from", allergy, sensitive-skin, pregnancy, or
post-procedure language is `safety_transcript` unless a separate strong source
proves the fact. It receives answer/display attribution only.

- [ ] **Step 4: Check progress after each product**

Update:

```json
{
  "last_product_id": 78,
  "reviewed_images": 318,
  "accepted_blocks": 0,
  "ambiguous_blocks": 0,
  "blocked_images": 0
}
```

Counts must be recomputed from audit files, not manually invented.

- [ ] **Step 5: Build and validate after each category batch**

Run the builder and focused data tests after skincare, suncare, base makeup,
color makeup, cleanser, and fragrance batches. Fix source or relationship
errors before moving on.

- [ ] **Step 6: Finish only with complete accounting**

The review phase is complete when:

```text
reviewed available images + blocked unavailable images = 972
unreviewed = 0
```

## Task 6: Add the Product-Scoped Reader and Retriever

**Files:**
- Create: `app/guide/retrieval/product_evidence_reader.py`
- Create: `app/guide/retrieval/product_evidence_retrieval.py`
- Test: `tests/guide/retrieval/test_product_evidence_retrieval.py`

- [ ] **Step 1: Write RED retrieval tests**

Use Winona evidence and assert:

- "那个布会不会往下掉" selects the non-slip consumer self-report;
- "红脸火辣辣" selects redness/heat evidence and its qualifiers;
- "收到的包装怎么不一样" selects packaging information without a
  predefined packaging intent;
- a query for product 34 never returns product 78 evidence;
- a safety query returns the transcript plus fail-closed caveat, not a safety
  guarantee;
- repeated evidence is deduplicated;
- at most five blocks per product and eight total are exposed.

- [ ] **Step 2: Run retrieval tests and verify RED**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/retrieval/test_product_evidence_retrieval.py
```

- [ ] **Step 3: Implement `EvidenceQuery` and `EvidencePacket`**

Use strict frozen contracts:

```python
class EvidenceQuery(_StrictFrozenModel):
    product_ids: tuple[int, ...] = Field(min_length=1, max_length=4)
    raw_question: str = Field(min_length=1, max_length=4000)
    question_meaning: str = Field(min_length=1, max_length=256)
    safety_sensitive: bool


class EvidencePacket(_StrictFrozenModel):
    query: EvidenceQuery
    selected: tuple[EvidenceSelection, ...]
    safety_caveats: tuple[str, ...]
    missing_aspects: tuple[str, ...]
```

- [ ] **Step 4: Implement deterministic scoring**

Score only blocks already scoped to requested product IDs. Combine:

- exact substring;
- normalized token overlap;
- relation subject/predicate/object overlap;
- FAQ question/answer overlap;
- qualifier overlap;
- free descriptor overlap;
- optional semantic score as a bounded additive signal;
- exact-product precedence;
- capability and safety filtering.

Return stable ordering using `(score desc, evidence_id asc)`.

- [ ] **Step 5: Run retrieval tests**

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add app/guide/retrieval/product_evidence_reader.py \
  app/guide/retrieval/product_evidence_retrieval.py \
  tests/guide/retrieval/test_product_evidence_retrieval.py
git commit -m "feat(guide): retrieve product-scoped evidence"
```

## Task 7: Carry Unrestricted Question Meaning Through Understanding

**Files:**
- Modify: `app/guide/understanding/semantic_detail_contracts.py`
- Modify: `app/guide/understanding/semantic_contracts.py`
- Modify: `app/guide/understanding/contracts.py`
- Modify: `app/guide/intent/signal_merger.py`
- Modify: `app/guide/intent/contracts.py`
- Modify: `app/guide/intent/task_planning.py`
- Modify: `app/guide/adapters/llm/intent_detail_prompt.py`
- Test: `tests/guide/understanding/test_semantic_detail_contracts.py`
- Test: `tests/guide/intent/test_signal_merger.py`
- Test: `tests/guide/intent/test_task_planning.py`

- [ ] **Step 1: Write RED translation tests**

Assert:

```python
KnowledgeDetails(
    question_meaning="询问面膜是否容易滑落",
    safety_sensitive=False,
    concerns=(),
    product_mentions=(mention,),
)
```

survives merger and planning without becoming a fixed concern enum.

Also assert a safety-sensitive paraphrase remains typed and an empty/overlong
meaning is rejected.

- [ ] **Step 2: Run tests and verify RED**

- [ ] **Step 3: Add two generic fields**

Add to detail proposals, `SemanticIntentProposal`, `StructuredUnderstanding`,
and `TaskPlan`:

```python
question_meaning: str | None = Field(default=None, max_length=256)
safety_sensitive: bool = False
```

For executable product questions, code falls back to normalized raw question
text only when the semantic lane is unavailable; it does not invent a tag.

- [ ] **Step 4: Tighten prompts**

Require `question_meaning` to be a short unrestricted description of what the
user asks, not an answer, product fact, ID, or fixed label. Require
`safety_sensitive=true` for allergy, absolute exclusion, pregnancy,
post-procedure safety, or adverse-reaction questions.

- [ ] **Step 5: Run understanding and intent tests**

Expected: all pass; existing preference and hard-exclusion tests remain green.

- [ ] **Step 6: Commit**

## Task 8: Ground Answer Construction and Typed Events

**Files:**
- Create: `app/guide/application/product_evidence_answer.py`
- Modify: `app/guide/presentation/sse_events.py`
- Modify: `app/guide/application/chat_api_adapter.py`
- Modify: `app/static/chat.html`
- Test: `tests/guide/application/test_product_evidence_answer.py`
- Test: `tests/guide/runtime/test_frontend_scope.py`

- [ ] **Step 1: Write RED answer tests**

Assert code renders:

```text
商家引用的35人消费者自评中，91%受试者认同水润舒缓。
这是消费者自评，不是客观仪器测试；商家脚注称实际结果因人而异。
```

from evidence fields, and rejects an answer plan containing an unreferenced
number or unsupported safety conclusion.

- [ ] **Step 2: Run tests and verify RED**

- [ ] **Step 3: Implement code-controlled rendering**

Add `ProductEvidenceData` and `ProductEvidenceEvent`. The answer composer may
order evidence, but exact numbers, qualifiers, attribution, disclaimer,
safety caveat, and citation are rendered from `EvidencePacket`.

- [ ] **Step 4: Serialize and render the typed event**

Frontend HTML must escape all evidence text and visibly show source type and
verification status. Do not expose local paths.

- [ ] **Step 5: Run answer and frontend tests**

- [ ] **Step 6: Commit**

## Task 9: Integrate the Retriever Into the Existing Orchestrator

**Files:**
- Modify: `app/guide/application/text_recommendation_flow.py`
- Modify: `app/guide_runtime/composition.py`
- Test: `tests/guide/application/test_text_recommendation_flow.py`
- Test: `tests/guide/runtime/test_composition.py`

- [ ] **Step 1: Write RED real-flow tests**

Cover:

1. direct product question about Winona slippage;
2. paraphrase "脸跟着火一样，这个能敷吗";
3. follow-up "它那个35个人测的靠谱吗";
4. ordinal reference "第二个对刺痛怎么样";
5. packaging-version question;
6. comparison asking for a dimension present only in evidence;
7. recommendation still uses standard ranking and only attaches relevant
   evidence;
8. safety question remains fail-closed.

- [ ] **Step 2: Run tests and verify the earliest RED layer**

Record whether each case first fails at product reference, question meaning,
retrieval, decision, or answer.

- [ ] **Step 3: Compose the evidence reader**

Add manifest and asset locks in `composition.py`, load the content-addressed
asset, and inject one retriever into `TextRecommendationOrchestrator`.

- [ ] **Step 4: Execute product-question modes**

Replace current placeholder `knowledge` and `followup` replies with:

```text
resolved product_ids + raw question + question_meaning
  -> EvidenceQuery
  -> EvidencePacket
  -> ProductEvidenceEvent + grounded MessageEvent
```

For suitability, comparison, and recommendation, attach evidence after the
decision; evidence must not select or rescue a winner.

- [ ] **Step 5: Preserve conversation references**

Keep visible candidate order and focused evidence IDs so "第二个" and "那个35人
测试" resolve without re-clarifying when only one valid reference exists.

- [ ] **Step 6: Run focused real-flow tests**

Expected: all pass, with no unsupported facts and no over-clarification.

- [ ] **Step 7: Commit**

## Task 10: Earliest-Failure End-to-End Audit

**Files:**
- Create: `docs/audits/product-evidence/real_question_matrix.jsonl`
- Create: `docs/audits/product-evidence/closure_report.md`
- Modify tests only at the earliest failing boundary.

- [ ] **Step 1: Build the real-question matrix**

Include direct, paraphrased, indirect, ordinal, follow-up, comparison,
recommendation, no-evidence, and safety questions across all six category
profiles. Each row records expected product, expected evidence IDs or expected
no-evidence result, and prohibited claims.

- [ ] **Step 2: Run the matrix through the normal runtime**

Record:

```text
product reference
question meaning
selected evidence IDs
decision result
final answer
clarification
first failing layer
```

- [ ] **Step 3: Repair only the earliest failing layer**

For each failure:

- add one focused boundary test;
- add one end-to-end regression;
- fix the owning layer;
- rerun the case and its category batch.

Do not add answer-layer keyword branches for understanding or retrieval
failures.

- [ ] **Step 4: Repeat until matrix gates pass**

Ordinary direct/paraphrased/follow-up questions must route at least 90%;
ordinary false clarification must be at most 10%; wrong-product evidence,
unsupported numbers, and safety guarantee violations must be zero.

## Task 11: Full Verification and Final Report

**Files:**
- Modify: `docs/audits/product-evidence/closure_report.md`

- [ ] **Step 1: Run focused tests**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/retrieval/test_product_evidence_assets.py \
  tests/guide/tools/test_build_product_evidence.py \
  tests/guide/tools/test_recover_product_detail_images.py \
  tests/guide/retrieval/test_product_evidence_retrieval.py \
  tests/guide/application/test_product_evidence_answer.py \
  tests/guide/application/test_text_recommendation_flow.py
```

- [ ] **Step 2: Run Guide full with polling**

```bash
.venv/bin/python -m pytest -c pytest-guide.ini -q tests/guide
```

- [ ] **Step 3: Run runtime full with polling**

```bash
.venv/bin/python -m pytest -c pytest-guide.ini -q tests/guide/runtime
```

- [ ] **Step 4: Run compile and boundaries**

```bash
.venv/bin/python -m compileall -q app tools
.venv/bin/python -m pytest -c pytest-guide.ini -q \
  tests/guide/test_architecture_boundaries.py \
  tests/guide/runtime/test_import_boundary.py
git diff --check
```

- [ ] **Step 5: Check residual processes**

Verify no pytest, Uvicorn, Playwright, crawler, or local HTTP server remains
from this run.

- [ ] **Step 6: Write the closure report**

Report:

- 972-image accounting;
- recovery status distribution;
- image-review status distribution;
- accepted evidence blocks by management label and category;
- answerable, compare, soft-rank, hard-filter, and safety-transcript counts;
- claims, evidence, audit, and manifest SHA values;
- real-question route and false-clarification rates;
- earliest-layer failures and repairs;
- blocked sources and every recovery attempt;
- deviations from the approved architecture;
- residual risks and exact Git status.

- [ ] **Step 7: Commit final verified state**

Do not push or deploy.
