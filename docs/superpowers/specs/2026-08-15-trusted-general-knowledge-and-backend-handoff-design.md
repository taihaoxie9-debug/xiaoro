# Trusted General Knowledge and Backend Handoff Design

**Date:** 2026-08-15

**Repository:** `/Users/bytedance/Desktop/xiaoro-fresh`

**Branch:** `rebuild`

**Status:** Proposed for implementation

**Depends on:** `2026-08-15-semantic-translation-and-code-owned-transitions-design.md`

## 1. Decision

The next backend phase has three ordered tracks:

1. close semantic translation and code-owned state transitions;
2. publish a Guide-owned, trusted general-knowledge asset from the 22 existing
   local skincare documents and connect it to typed knowledge answers;
3. run one backend handoff matrix covering profile, image, consultation,
   knowledge, recommendation, comparison, and follow-up behavior.

Execution stops after the backend contracts and gates are green and before
frontend rendering.

The general-knowledge implementation will not import or revive the legacy
`app.services.knowledge_base` or `app.services.rag` runtime. Guide architecture
boundaries explicitly forbid those imports, and the legacy implementation:

- depends on PostgreSQL and legacy service singletons;
- encodes every candidate again on every request;
- scans only the newest 100 rows;
- generates vectors without persisting them;
- mixes product recall, knowledge recall, answer generation, and pitfalls.

The new path is a small Guide retrieval component over content-addressed,
audited local assets.

## 2. Current Assets

The fresh repository already contains:

```text
data/knowledge_docs/*.md
22 documents
1,135 lines
85,465 bytes
```

They cover:

- sensitive, dry, oily, acne-prone, and barrier-damaged skin;
- sunscreen, cleanser, makeup removal, serum, cream, eye cream, and masks;
- niacinamide, retinol, acids, vitamin C, peptides, and proxylane;
- base makeup, setting products, lip products, and fragrance;
- light-assessment topics such as recognizing sensitive skin.

The documents are useful seed material, but they are not automatically trusted
facts. Some paragraphs:

- contain medical or pregnancy cautions;
- contain product examples, prices, and formula claims that can become stale;
- summarize public information without primary-source URLs;
- use broad educational language that must not become a product hard fact.

Every answerable block therefore needs an explicit use audit before runtime
publication.

## 3. Alternatives

### 3.1 Reuse the legacy PostgreSQL RAG service

Rejected. It violates Guide import boundaries, performs unbounded online
candidate encoding, and reintroduces the legacy product/RAG architecture that
the rebuild branch intentionally removed.

### 3.2 Crawl and rebuild a new medical knowledge corpus tonight

Rejected. Source verification, licensing, medical review, deduplication, and
freshness cannot be completed safely inside this backend closure window.

### 3.3 Compile and audit the 22 local documents into Guide assets

Selected. The corpus is small, already local, relevant to the product domain,
and sufficient to close common educational questions. It can be audited
block-by-block, content-addressed, loaded once, and retrieved deterministically
without another model call.

## 4. Knowledge Use Boundary

General-knowledge blocks may be used for:

```text
general educational answers
ingredient and routine explanations
category-selection guidance
pitfall and escalation reminders
knowledge follow-up context
displayed citations
```

They may not be used for:

```text
product facts
product hard filtering
product ranking
verified product absences
pregnancy or allergy guarantees
medical diagnosis
profile confirmation
claims about a current product formula or price
```

Product-specific questions continue to use:

```text
Canonical facts
SelectionFact
ProductEvidence
```

Light consultation continues to use its dedicated observation, provisional
assessment, confirmation, and medical-escalation contracts.

General knowledge cannot override either path.

## 5. Knowledge Contracts

### 5.1 Source document

```python
class GeneralKnowledgeDocument:
    document_id: str
    title: str
    source_path: str
    source_sha256: str
    document_kind: Literal["educational_seed"]
```

`document_id` is derived from canonical document content. Absolute local paths
are never published.

### 5.2 Audited block

```python
class GeneralKnowledgeBlock:
    knowledge_id: str
    document_id: str
    title: str
    section_title: str
    exact_text: str
    source_path: str
    source_sha256: str
    block_sha256: str
    review_decision: Literal[
        "general_answer",
        "escalation_only",
        "product_specific_redirect",
        "rejected",
    ]
    allowed_uses: frozenset[
        Literal[
            "answer",
            "citation",
            "followup",
            "medical_escalation",
        ]
    ]
    forbidden_uses: frozenset[
        Literal[
            "product_fact",
            "hard_filter",
            "soft_rank",
            "safety_guarantee",
            "profile_write",
        ]
    ]
    review_rationale: str
```

All published blocks require a nonempty review rationale.

### 5.3 Asset manifest

The runtime asset is content addressed:

```text
data/guide_general_knowledge/
  general_knowledge_v1.<sha256>.jsonl
  general_knowledge_v1_manifest.json
  reviews/*.jsonl
```

The manifest records:

- source document count and SHA set;
- total and accepted block counts;
- review-decision and allowed-use counts;
- asset and review SHA-256 values;
- schema version.

Runtime composition pins the manifest hash.

## 6. Structural Parsing and Audit

The source grammar is intentionally narrow:

```text
one H1 document title
zero or more H2 sections
paragraphs and list items inside a section
```

The builder rejects:

- missing or repeated H1 titles;
- content before the H1;
- empty H2 sections;
- malformed heading order;
- duplicate source paths or source hashes;
- empty blocks;
- blocks exceeding the contract limit.

Blocks follow section and paragraph boundaries. The builder does not slice
sentences by arbitrary character counts.

Review is block-level, not document-level. A useful educational paragraph may
be accepted while a stale product-price paragraph in the same document is
redirected or rejected.

### 6.1 Audit policy

Use `general_answer` when a block gives non-product-specific education and
does not claim diagnosis or guaranteed safety.

Use `escalation_only` when a block supports a boundary such as persistent
redness, severe acne, open wounds, or medication requiring professional care.
These blocks may trigger or support an escalation message but cannot produce a
diagnosis.

Use `product_specific_redirect` when a paragraph names product formulas,
prices, current versions, or comparative product claims. Runtime redirects the
question to Canonical/ProductEvidence if that product is in the catalog;
otherwise it states that current product evidence is unavailable.

Use `rejected` for unsupported absolutes, stale promotions, duplicated filler,
or text that cannot be safely attributed.

Product-specific sections in documents 21 and 22 require particular scrutiny;
they are not accepted as general product truth merely because they already
exist in the repository.

## 7. Deterministic Retrieval

The corpus is small enough to load once and search in process. Retrieval does
not call an embedding API or answer model.

### 7.1 Query

```python
class GeneralKnowledgeQuery:
    raw_question: str
    question_meaning: str
    topic: TopicCode | None
    safety_sensitive: bool
    prior_knowledge_ids: tuple[str, ...]
    top_k: int = 3
```

### 7.2 Scoring

The builder precomputes normalized retrieval terms for each block:

- lowercase ASCII terms;
- contiguous Chinese characters;
- Chinese character bigrams;
- H1 and H2 title terms.

Runtime scores:

```text
exact title/section phrase
+ query term coverage
+ rare-term overlap
+ topic compatibility
+ bounded prior-block follow-up boost
- product-specific redirect penalty
- generic boilerplate penalty
```

Tie-breaking is:

```text
score descending
document_id ascending
section order ascending
knowledge_id ascending
```

No retrieved block can select a product or affect recommendation order.

### 7.3 Retrieval result

```python
class GeneralKnowledgeHit:
    block: GeneralKnowledgeBlock
    score: float
    matched_terms: tuple[str, ...]
```

Unknown or low-confidence retrieval returns an empty packet. The system then
states the evidence gap instead of generating a generic answer.

## 8. Answer and Citation Contract

The backend emits a typed event:

```python
class GeneralKnowledgeCitationData:
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


class GeneralKnowledgeData:
    query: str
    citations: list[GeneralKnowledgeCitationData]
    educational_only: Literal[True] = True
    medical_escalation: bool
```

The code renderer:

- answers only from selected exact excerpts;
- names the document and section;
- marks the content as general education;
- includes professional-care escalation when an accepted escalation block is
  selected;
- never turns a general ingredient statement into a current-product fact;
- never claims a diagnosis or guaranteed safety.

No answer-synthesis model is added in this phase.

## 9. Knowledge Routing

For `TaskPlan.mode == "knowledge"`:

```text
resolved product IDs
  -> ProductEvidenceRetriever

no product ID + general educational question
  -> GeneralKnowledgeRetriever

ambiguous product mention
  -> product-reference clarification

no general hit
  -> explicit knowledge gap
```

ProductEvidence and general-knowledge citations are not merged into one
untyped list.

## 10. Knowledge Follow-Up

`ConversationSnapshot` stores:

```text
focused_general_knowledge_ids
last_general_knowledge_question
```

A later knowledge follow-up may use those IDs as a bounded retrieval boost.
It cannot use them as proof for a new product, safety guarantee, or medical
claim.

Examples:

```text
“SPF和PA分别是什么意思”
“那为什么海边要更高？”

“烟酰胺有什么作用”
“敏感肌怎么开始用？”
```

Reference and state rules from the semantic-transition design still apply.
An unrelated fresh question does not inherit prior knowledge blocks.

## 11. Backend Handoff Matrix

Before frontend work, run one typed matrix for the following verticals.

### 11.1 User profile

Verify:

- profile ownership cannot be changed by a client or another session;
- only confirmed facts persist;
- current explicit input overrides session and long-term profile;
- confirmed profile values reach text and image suitability;
- consultation confirmation writes the expected profile version;
- rejection and medical escalation do not write an ordinary profile fact.

### 11.2 Image

Verify:

- single-image identification;
- visually similar product recall;
- image suitability using server-resolved profile context;
- multi-image comparison;
- ambiguous or low-similarity images fail closed;
- image references cannot bind nonexistent ordinals.

### 11.3 Light consultation

Verify:

- entry and observable question sequence;
- answer collection without duplicate observations;
- provisional conclusion;
- explicit user confirmation before profile persistence;
- rejection path;
- medical escalation path;
- ordinary post-consultation recommendation uses the confirmed profile.

### 11.4 Knowledge

Verify:

- general educational retrieval with typed citations;
- product-specific knowledge remains on ProductEvidence;
- general knowledge cannot become a product fact;
- low-confidence queries state an evidence gap;
- medical/safety content escalates appropriately;
- current-item and general-knowledge follow-ups preserve the correct evidence
  scope.

### 11.5 Recommendation, comparison, and follow-up

Verify:

- ordinary recommendation with multiple soft slots;
- hard safety condition dominating soft rank;
- direct named comparison;
- current-item and ordinal follow-up;
- budget, skin, category, efficacy, inclusion, exclusion, and facet
  transitions;
- unmentioned constraints remain unchanged;
- typed selection slots and evidence attribution survive follow-up.

## 12. Gate Policy

Local gates:

```text
knowledge asset and audit tests
knowledge retrieval and rendering tests
profile/image/consultation/knowledge/recommendation matrix
Guide full
Guide runtime
architecture/import boundaries
compileall
git diff --check
```

Official semantic gates run three independent times after the semantic schema
and transition reducer are complete.

Frontend handoff requires:

```text
stable typed SSE contracts
all local vertical gates green
same non-null official selected lane in three runs
zero hard-constraint override
zero unauthorized state transition
zero wrong-product selection
zero unsafe TaskPlan mismatch
```

If the official gate remains red, backend implementation may be complete but
the release status remains `NO-GO`.

## 13. Scope

### In scope

- block-level audit of the 22 existing documents;
- content-addressed Guide knowledge assets;
- deterministic general-knowledge retrieval;
- typed citations and code-rendered educational answers;
- bounded knowledge follow-up state;
- five-vertical backend handoff matrix;
- local and official backend gates;
- closure report.

### Out of scope

- web crawling or creating a new medical corpus;
- importing legacy PostgreSQL knowledge rows;
- online embedding or Milvus;
- model-generated knowledge prose;
- using general knowledge for product ranking or hard filtering;
- frontend rendering;
- push, deploy, or production traffic switch.

## 14. Completion and Time Boundary

This scope is feasible as an overnight backend goal because the corpus,
profile store, image runtime, consultation vertical, ProductEvidence path, and
follow-up state already exist. The new work is bounded to:

- semantic authority cleanup;
- auditing and compiling a small local knowledge corpus;
- deterministic retrieval and typed handoff;
- cross-vertical verification.

Completion cannot be promised in advance for the official model lane because
provider behavior is external. The implementation must not weaken gate
expectations to manufacture a green result.

Execution stops before frontend rendering. A green backend handoff permits the
next phase to begin frontend implementation immediately.
