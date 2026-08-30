# General Knowledge Retrieval Stability Design

**Date:** 2026-08-31

**Repository:** `/Users/bytedance/Desktop/xiaoro-fresh/.tmp-task11-r5-seal-worktree`

**Status:** Approved for implementation

## Goal

Make the existing 22-topic, 209-block reviewed general-knowledge corpus
reliably answer supported skincare education questions without unrelated
citations or unsupported relationship claims.

This is a retrieval-stability repair. It does not expand the corpus, add a
second knowledge dispatcher, or introduce text embeddings.

## Current Failure

The current `GeneralKnowledgeRetriever` combines raw-query terms and the
model's free-form `question_meaning`, then chooses either shared terms or raw
literal anchors:

```python
anchor_terms = (
    shared_anchors
    if shared_anchors
    else self._literal_anchor_terms(query)
)
```

That makes generic relationship words such as "区别" or "一起使用" capable of
replacing the user's explicit ingredient names as retrieval authority.
Chinese/ASCII mixtures such as `维C` and `A醇` are also split poorly. The
retriever has no typed entity coverage gate, so a high lexical score can return
a fluent but unrelated block.

Observed real-backend failures include:

- `烟酰胺和A醇有什么区别，能一起用吗？` citing face-cream/乳液 content;
- `维C白天到底能不能用？` returning no citation despite direct corpus evidence;
- `怎么判断自己是不是敏感肌？` preferring product-image guidance over the
  identification section;
- `防晒为什么过几个小时还要补涂？` mixing relevant sunscreen evidence with
  unrelated oily-skin and setting-makeup citations.

The failure is not a lack of FAQ sentences. It is a missing typed retrieval
contract.

## Scope

### In scope

- a typed `KnowledgeQuerySpec`;
- canonical knowledge concepts and entity aliases;
- typed knowledge relation hints;
- raw-text authority for explicit entities;
- parent/child concept matching;
- deterministic lexical candidate scoring;
- deterministic entity and relation coverage;
- multi-entity evidence assembly;
- section- and relation-aware ranking;
- explicit whole-query or partial evidence gaps;
- real citations in backend and frontend output;
- deterministic coverage for all 22 current topics;
- repeated real DeepSeek, backend, SSE, and browser acceptance.

### Out of scope

- text embeddings or vector search;
- new knowledge documents or rewritten reviewed source text;
- free-form answer generation from an LLM;
- product recommendation or product ranking changes;
- changes to the legacy repository at
  `/Users/bytedance/Desktop/xiaoro-shopping-master`;
- sentence-specific branches, fixed question-to-ID maps, or test-only
  production behavior.

## Architecture

```text
HTTP request
  -> TurnMeaning
       operation_hint
       knowledge_relation_hints
  -> StructuredUnderstanding
  -> one TaskPlan
       knowledge_relation_hints
  -> existing general_knowledge processor
  -> KnowledgeQuerySpec
       raw_query
       question_meaning
       concept_ids
       entity_mentions
       relation_intents
       safety_sensitive
       prior_knowledge_ids
  -> existing GeneralKnowledgeRetriever
       typed candidate eligibility
       deterministic lexical score
       section/relation rerank
       multi-entity assembly
       coverage validation
  -> GeneralKnowledgePacket
       hits
       coverage
  -> code-owned reviewed-text renderer
  -> general_knowledge SSE event
  -> presentation contract + visible citations
```

There remains exactly one route decision, one `TaskPlan`, one
`general_knowledge` processor, and one `GeneralKnowledgeRetriever`.

## Responsibility Split

### Deterministic parsing

Deterministic code owns:

- Unicode normalization;
- explicit alias matching in the raw user text;
- canonical entity identity;
- explicit relationship markers;
- parent/child concept expansion;
- safety flags already accepted by `TaskPlan`;
- entity, relation, and permission coverage;
- final candidate ordering and fail-closed behavior.

Explicit raw-text entities are authoritative. A model translation may not
remove, replace, or invent them.

### Semantic model

The existing single TurnMeaning call owns open-language interpretation. For
general knowledge it may emit relation hints:

```text
overview
mechanism
difference
compatibility
usage
selection
identification
safety
```

The model does not emit knowledge IDs, source paths, citations, entity IDs, or
answers. Explicit deterministic relation markers are retained; model hints
only fill relations that are not explicit in the raw text.

### Vector retrieval

No text vector path is added. Existing OpenCLIP image-vector behavior is
unchanged.

## Typed Knowledge Model

### Query

```python
KnowledgeRelationIntent = Literal[
    "overview",
    "mechanism",
    "difference",
    "compatibility",
    "usage",
    "selection",
    "identification",
    "safety",
]


class KnowledgeEntityMention:
    entity_id: str
    raw_text: str


class KnowledgeQuerySpec:
    raw_query: str
    question_meaning: str
    concept_ids: tuple[str, ...]
    entity_mentions: tuple[KnowledgeEntityMention, ...]
    relation_intents: tuple[KnowledgeRelationIntent, ...]
    safety_sensitive: bool
    prior_knowledge_ids: tuple[str, ...]
    top_k: int = 3
```

`entity_mentions` are built only from the raw request. `question_meaning` is a
lexical expansion input and never an entity-identity authority.

### Knowledge blocks

Published blocks gain retrieval metadata:

```python
class GeneralKnowledgeBlock:
    ...
    primary_concept_ids: tuple[str, ...]
    mentioned_concept_ids: tuple[str, ...]
    primary_entity_ids: tuple[str, ...]
    mentioned_entity_ids: tuple[str, ...]
    relation_intents: tuple[KnowledgeRelationIntent, ...]
```

`primary_concept_ids` contain the source document's parent and child path, for
example:

```text
ingredient
ingredient.niacinamide
```

`primary_entity_ids` identify what the source document is about.
`mentioned_concept_ids` and `mentioned_entity_ids` are identities explicitly
present in that exact block.
The distinction prevents a generic document that merely mentions retinol from
outranking the dedicated retinol document.

### Metadata source

The existing reviewed text and permission records remain unchanged. A new
reviewed retrieval-profile catalog maps each of the 22 source documents and
each section title to:

- parent and child concepts;
- primary entities;
- section relation intents.

The build step derives block-level mentioned entities from exact source text,
joins the reviewed profile, validates complete source/section coverage, and
publishes the metadata into the existing content-addressed block JSONL.

This is published as the `guide-general-knowledge-v2` schema. The immutable v1
artifact remains as historical evidence but runtime composition moves its
single manifest lock to v2. The v2 manifest records the retrieval-profile
SHA-256. Runtime refuses a missing, extra, stale, or unpinned profile.
Knowledge IDs remain source-content identities; the blocks-file and manifest
hashes capture retrieval metadata changes.

## Canonical Entity Aliases

Aliases are centralized in the knowledge ontology, not scattered through
query branches. The first required ingredient identities are:

| Entity | Required aliases |
|---|---|
| `ingredient.niacinamide` | 烟酰胺, 维生素B3, niacinamide |
| `ingredient.retinol` | A醇, A 醇, 视黄醇, 维A, 维A醇, retinol |
| `ingredient.vitamin_c` | 维C, VC, 维生素C, 抗坏血酸, vitamin C, ascorbic acid |
| `ingredient.salicylic_acid` | 水杨酸, BHA, salicylic acid |
| `ingredient.acid` | 酸类, 刷酸, 果酸, AHA |
| `ingredient.proxylane` | 玻色因, 羟丙基四氢吡喃三醇, pro-xylane |
| `ingredient.peptide` | 肽, 肽类, 胜肽, 多肽, peptide |

The same ontology contains concepts for all 22 source topics, including skin
states, routines, and product categories. Aliases are domain vocabulary, not
complete user sentences.

Matching uses NFKC and case folding while preserving the exact matched raw
substring. Whitespace variants such as `A 醇` and `维 C` normalize to the same
entity without making arbitrary single ASCII characters into anchors.

## Relation Semantics

Generic explicit markers are deterministic:

| Relation | Examples |
|---|---|
| `difference` | 区别, 差别, 不同, 一回事 |
| `compatibility` | 一起用, 同用, 叠加, 搭配, 冲突 |
| `mechanism` | 作用, 原理, 为什么, 是什么 |
| `usage` | 怎么用, 白天, 晚上, 顺序, 频率, 补涂 |
| `selection` | 怎么选, 如何选择 |
| `identification` | 怎么判断, 如何判断 |
| `safety` | 孕期, 哺乳期, 刺痛, 爆皮, 破皮, 严重 |

These markers are generic language rules. No complete acceptance question is
stored in production code.

## Retrieval Rules

### Candidate eligibility

1. If explicit entities exist, a candidate must have a matching primary or
   mentioned entity.
2. If no entity exists but typed concepts exist, a candidate must share the
   deepest available concept.
3. If neither exists, lexical fallback requires a rare literal anchor from the
   raw text; model-only overlap cannot authorize a hit.
4. Rejected blocks are impossible inputs.
5. Permission policy remains authoritative after relevance scoring.

Raw literal anchors are always retained. Shared raw/model terms may add
lexical evidence but may never replace them.

### Ranking

Ranking remains deterministic:

```text
lexical IDF score
+ primary entity match
+ exact block entity mention
+ deepest concept match
+ requested relation match
+ section-title match
+ bounded related-prior boost
+ safety escalation boost when safety_sensitive
- relation mismatch
- intro boilerplate
- product-specific redirect
```

Tie-breaking remains:

```text
score descending
source_path ascending
section_order ascending
knowledge_id ascending
```

### Multi-entity assembly

For `difference`, the packet must contain evidence for every explicit entity.
A mechanism/overview block for each entity is valid comparison evidence.

For `compatibility`, separate descriptions are not enough. The relation is
covered only when one reviewed block explicitly mentions every requested
entity and is tagged for compatibility, usage, or safety. Otherwise the packet
may answer covered relations and must mark compatibility as missing.

For example:

```text
烟酰胺和A醇有什么区别，能一起用吗？
```

may retrieve reviewed mechanism evidence for both ingredients. Because the
current corpus has no direct reviewed block for that pair, the answer must say
that the compatibility part lacks direct reviewed evidence. It must not infer
compatibility from two independent ingredient descriptions.

## Coverage Contract

```python
class GeneralKnowledgeCoverage:
    required_concept_ids: tuple[str, ...]
    covered_concept_ids: tuple[str, ...]
    required_entity_ids: tuple[str, ...]
    covered_entity_ids: tuple[str, ...]
    required_relation_intents: tuple[KnowledgeRelationIntent, ...]
    covered_relation_intents: tuple[KnowledgeRelationIntent, ...]
    missing_concept_ids: tuple[str, ...]
    missing_entity_ids: tuple[str, ...]
    missing_relation_intents: tuple[KnowledgeRelationIntent, ...]
    complete: bool
```

Every selected citation must contribute to entity, concept, relation, safety,
or directly related follow-up coverage. Filler hits are removed before
`top_k`; a top-three slot is not filled merely because a weak score is above a
global threshold.

The renderer follows these rules:

- complete coverage: answer only from selected reviewed public text;
- partial relation coverage: answer covered parts and name the unsupported
  relation;
- missing required entity: do not perform the requested comparison;
- no usable hit: return the existing explicit evidence gap;
- escalation-only evidence: emit the existing non-diagnostic professional
  boundary;
- product-specific redirect: never turn it into a general or product fact.

## Routing Boundary

The semantic prompt is clarified, not replaced:

- "how to choose/use/understand a category" without a request to find products
  is general knowledge;
- "recommend/show/find specific products" is recommendation;
- a current symptom or reaction asking what to do is consultation/assessment;
- a general mechanism or safety explanation remains knowledge when it is not a
  request to assess the user's current condition.

Required outcomes for the six observed probes are:

| Query | Expected result |
|---|---|
| 烟酰胺和A醇有什么区别，能一起用吗？ | general knowledge; both entities cited; compatibility gap |
| 怎么判断自己是不是敏感肌？ | general knowledge; identification section first |
| 刷酸后爆皮刺痛应该怎么办？ | consultation/safety path; no general-knowledge answer |
| 防晒为什么过几个小时还要补涂？ | general knowledge; sunscreen citations only |
| 维C白天到底能不能用？ | general knowledge; vitamin-C citation |
| 油皮夏天应该怎么选面霜？ | general knowledge selection guidance |

## Citation Delivery

The `general_knowledge` SSE event remains the authoritative evidence event. It
adds the coverage contract and keeps each citation bound to a reviewed
knowledge ID, source path, title, section, review decision, and public excerpt.

The frontend validates that contract and renders the citations through the
existing citation surface. It does not scrape source labels from answer prose
and does not synthesize links or evidence.

## Stability Definition

Deterministic acceptance uses a checked-in matrix with at least one common
query for every current source topic plus alias, multi-entity, no-hit, and
routing-boundary probes.

The release threshold is:

```text
22/22 source topics represented
Recall@3 = 100%
wrong-topic citation count = 0
wrong-section citation count = 0
required entity coverage = 100%
unsupported compatibility claims = 0
expected no-hit precision = 100%
byte-identical ordering across repeated deterministic runs
```

Real acceptance runs the six observed probes twice from clean independent
sessions through:

```text
real DeepSeek TurnMeaning
-> real FastAPI backend
-> exact SSE
-> shipped browser frontend
```

Both consecutive runs must pass without selective reruns. Provider transport
failure may be retried once according to the existing bounded policy; semantic
or citation failure is a product failure and restarts the two-run acceptance
after repair.

## Automatic Repair Loop

The executor continues without user approval for ordinary failures:

1. preserve the failing query, TurnMeaning, `KnowledgeQuerySpec`, packet, SSE,
   DOM, and screenshot;
2. identify the earliest owner: semantic relation, ontology, metadata,
   eligibility, ranking, coverage, renderer, or frontend;
3. add a class-level failing regression;
4. verify RED for the observed reason;
5. implement the smallest shared-owner fix;
6. rerun focused tests;
7. rerun the deterministic matrix;
8. restart the two consecutive real acceptance runs.

Execution stops only for missing credentials, a persistent external outage,
destructive operations requiring consent, or a required change outside this
approved scope.

## Non-Negotiable Invariants

- No sentence-specific production branch.
- No fixed question-to-knowledge-ID mapping.
- No second knowledge dispatcher or answer path.
- No text vectors in this change.
- No unsupported relation inference.
- No general knowledge used as product truth, hard filter, rank signal,
  profile write, diagnosis, or safety guarantee.
- No citation without a selected reviewed block.
- No edits to `/Users/bytedance/Desktop/xiaoro-shopping-master`.
