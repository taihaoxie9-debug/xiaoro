# Product Evidence and Intent Translation Design

**Status:** Approved by the user for Goal-mode implementation.

**Repository:** `/Users/bytedance/Desktop/xiaoro-fresh`

**Branch:** `rebuild`

## 1. One-Line Goal

Make almost every useful, reviewed product-detail asset answerable, while
allowing only the smaller, comparable subset to influence retrieval,
comparison, or ranking. Users should be able to ask the same question in
ordinary, indirect, or follow-up language without forcing the system to
predefine every possible question.

## 2. Why This Work Exists

The current pipeline repeatedly compresses information:

```text
detail image
  -> linear OCR text
  -> a small set of fields
  -> a few merchant claims
  -> one or two visible answer fragments
```

A product page may contain ten layers of useful information. The crawler may
capture nine, curation may retain seven, but the guide may finally express only
two. This is a major asset loss even when the crawler itself worked correctly.

The problem has two independent sides:

1. **Product knowledge fidelity:** the system needs a loss-resistant product
   evidence asset instead of reducing every useful image to a narrow field.
2. **User-language translation:** the system must understand which product the
   user means and what they want to know, without clarifying every indirect
   phrase or requiring a dedicated intent for every possible question.

If either side fails, the other side has little value. Rich data with a weak
understanding layer remains unreachable. Good intent routing with shallow data
still produces empty or generic answers.

## 3. Confirmed Design Principles

### 3.1 Useful evidence is answerable by default

The denominator is not every advertisement image. It is every image content
block that human review accepts as useful product information.

For accepted product information:

```text
approximately 99% should be answerable
approximately 20%-30% may also be rankable or retrievable as a standard facet
```

The percentages are directional design expectations, not fabricated coverage
claims. Actual coverage must be measured after the full audit.

Examples:

| Evidence | Answer | Rank / retrieve |
|---|---:|---:|
| Merchant claims soothing redness | Yes, with attribution | Soft only |
| 91% of consumers agreed it felt hydrating | Yes, with study qualifiers | At most weak soft signal |
| New and old packaging ship randomly | Yes | No |
| Recommended skincare sequence | Yes | No |
| Merchant claims post-procedure suitability | Safety transcript only | No |
| Verified registration or complete package ingredients | Yes | May support a hard rule |

### 3.2 Classification cannot decide whether evidence is preserved

The project must not first invent five or ten buckets and discard anything that
does not fit them.

The required order is:

```text
inspect the image
  -> preserve the complete useful meaning
  -> record relationships and qualifiers
  -> add zero or more open-ended tags
  -> decide allowed uses
  -> optionally create standard projections
```

Tags are descriptive metadata. They are not admission tickets. New tags and
new relation types are expected to appear during the audit.

### 3.3 OCR is a candidate generator, not final evidence

Linear OCR loses columns, arrows, visual grouping, footnote links, question and
answer boundaries, and product-versus-gift boundaries.

The original image is the review authority. OCR helps locate text, but a
reviewer must return to the image for:

- multi-column percentages;
- before/after relationships;
- ingredient-to-effect arrows;
- footnote numbers and study qualifiers;
- FAQ question-to-answer pairs;
- current product versus gift, bundle, or related product;
- packaging and version differences.

If the image does not support a reliable relationship, the record remains
`ambiguous`; the system must not guess.

### 3.4 Ranking and answering are separate consumers

They share reviewed evidence but do not share the same admission rules:

```text
                         +-> standard projections -> ranking / comparison
reviewed product evidence
                         +-> full evidence search -> product answering
```

Ranking needs comparable, normalized dimensions. Answering can use unique
facts that apply to only one product.

### 3.5 The model translates language; it does not author facts

The model may translate:

```text
"它那个布会不会老往下掉？"
```

into:

```text
product: the currently referenced mask
question meaning: whether the sheet is conforming and likely to slip
```

The model must not invent the answer, a product ID, a percentage, a study
population, or a safety conclusion.

### 3.6 Clarification is a last resort

Clarify only when:

1. multiple plausible product references would materially change the answer; or
2. a safety-sensitive answer cannot be made without resolving the ambiguity.

If the reference is reliably inferable, continue and make the interpretation
visible instead of blocking the conversation.

### 3.7 Every layer has one responsibility

| Layer | Owns | Must not do |
|---|---|---|
| Crawl | Preserve source images and identity metadata | Infer product claims |
| Visual review | Understand image content and relationships | Rank products |
| Evidence policy | Authorize answer/compare/rank/safety uses | Rewrite user intent |
| Understanding | Translate who/what/safety context | Read product details |
| Evidence retrieval | Find relevant reviewed evidence | Pick recommendation winners |
| Decision | Apply hard rules and ranking | Write prose |
| Answer | Express selected evidence | Create facts or safety guarantees |

When an end-to-end case fails, repair the earliest failing layer. Do not add a
late keyword patch that hides an earlier data, reference, or translation error.

## 4. Current Measured State

The current source inventory contains:

- 103 product OCR source files;
- 972 detail images referenced by those sources;
- 953 images with non-empty OCR;
- about 232,115 OCR characters;
- 305 images physically preserved in the fresh repository;
- 667 historical images not yet physically present in the fresh image asset.

The 305 current images occupy about 54 MiB. Based on recorded image sizes, all
972 images would occupy roughly 185 MiB. Storage is not the main cost. Accurate
visual review and relationship recovery are the main cost.

The other 667 entries are not 667 known-empty records and not proof that their
content is lost. Their historical OCR JSON still preserves a filename, image
dimensions, and recognized text, but the fresh repository does not currently
contain the corresponding image bytes. Most of those historical records also
do not preserve a direct image URL. Recovery must therefore proceed in this
order:

1. search the old audited asset inventory for the exact historical image;
2. extract the exact image reference from the saved identity-matched HTML when
   available;
3. use the recorded product identity and SKU to fetch the current public detail
   page and compare its image identity;
4. if only a changed current image is available, preserve it as a new source
   version rather than pretending it is the historical source;
5. if no image can be recovered, mark the historical OCR source explicitly
   blocked and never claim that it received visual review.

The current Merchant Claim asset contains 1,136 claims, but the runtime and
tests still point at the earlier 1,106-claim lock. That checkpoint must be
closed before the new evidence asset is promoted.

## 5. This Is Not Another Full Agent Architecture

The existing guide already has useful boundaries for:

- structured understanding;
- product mention and reference resolution;
- task planning;
- recommendation, comparison, suitability, knowledge, and follow-up modes;
- hard constraints and soft facets;
- deterministic decision logic;
- typed SSE presentation.

The missing capability is a bounded product-evidence subsystem:

```text
existing understanding
  -> EvidenceQuery
  -> product-scoped EvidenceRetriever
  -> EvidencePacket
  -> existing answer/presentation flow
```

This is not a second orchestrator and not a second free-roaming Agent. It is a
new retrieval port with strict product, source, capability, and citation
boundaries.

## 6. Proposed Product Evidence Asset

### 6.1 EvidenceBlock

The durable unit is an `EvidenceBlock`, not a narrow `field_key`.

Conceptually, each block records:

```json
{
  "evidence_id": "content-addressed-id",
  "product_id": 78,
  "variant_scope": "exact_product",
  "subject_scope": "exact_product",
  "source": {
    "image_sha256": "...",
    "source_url": "...",
    "image_region": [0, 0, 790, 1364],
    "source_class": "merchant_description_image"
  },
  "exact_text": "91%消费者认同水润舒缓",
  "plain_meaning": "消费者对水润舒缓体验的认同",
  "relations": [
    {
      "subject": "91%",
      "predicate": "消费者认同",
      "object": "水润舒缓"
    }
  ],
  "qualifiers": {
    "sample_size": 35,
    "population": "18-35岁中国敏感肌消费者",
    "method": "消费者自评",
    "disclaimer": "结果仅供参考，实际结果因人而异"
  },
  "tags": ["水润", "舒缓", "消费者自评"],
  "review_status": "accepted",
  "allowed_uses": ["answer", "display", "weak_soft_rank"],
  "forbidden_uses": [
    "hard_filter",
    "safety_guarantee",
    "clinical_effectiveness"
  ]
}
```

This is a conceptual contract. Exact fields should follow the repository's
strict, frozen, content-addressed asset patterns during implementation.

### 6.2 Open-world tags

Tags may be added during review and may be product-specific. A missing tag does
not make a block unsearchable.

The word "tag" covers three different mechanisms. They must not be collapsed
into one giant vocabulary:

1. **Management labels** are a small, stable set such as merchant claim,
   consumer self-report, merchant-cited third-party test, packaging
   information, FAQ, usage, and safety transcript. They control provenance and
   allowed use.
2. **Ranking fields** are a limited, category-aware set such as efficacy,
   suitable skin, finish, texture, longevity, SPF/PA, and coverage. They exist
   only when evidence can be normalized and compared across products.
3. **Free descriptors** are open-ended phrases such as "not easy to slip,"
   "use promptly after opening," "new and old packaging ship randomly," or
   "use as step four." They help semantic retrieval but are not enums, schema
   gates, or new intent types.

Evidence retrieval searches:

- user raw text;
- translated question meaning;
- exact evidence text;
- plain meaning;
- relations;
- qualifiers;
- FAQ question and answer text;
- optional tags.

Tags improve precision. They are not the only retrieval route.

The retrieval contract is therefore:

```text
hard-scope to product_id
  -> search raw question
  -> search translated unrestricted meaning
  -> search exact text, plain meaning, relations, qualifiers, FAQ, and tags
  -> apply provenance, capability, and safety policy
  -> return cited evidence
```

The system never requires the model to select from hundreds or thousands of
free descriptors before retrieval can begin.

### 6.3 Review outcomes

Every image and every useful content block must have an explicit outcome:

| Status | Meaning |
|---|---|
| `accepted` | Valid product evidence; answerable by default |
| `ambiguous` | Useful-looking, but a relationship or subject cannot be proven |
| `irrelevant` | Not useful product information |
| `expired` | Time-sensitive promotion or obsolete campaign |
| `cross_product` | Belongs to a gift, bundle item, or different product |
| `duplicate` | Same evidence already preserved with a back-reference |

No image may be silently skipped.

## 7. Standard Projections

Evidence is preserved first. Standard projections are optional derived views.

```text
AnswerEvidenceView       default for accepted blocks
SoftRankProjection       normalized, comparable merchant or experience signal
CompareProjection        comparable dimension with source and qualifier parity
HardFilterProjection     strong evidence only
SafetyTranscriptView     attributed display only, never a safety guarantee
```

Every projection must link back to one or more `evidence_id` values. A
projection never replaces the source block.

Category profiles define which dimensions are comparable. They do not limit
what can be answered.

## 8. Intent Translation and Evidence Query

The understanding layer should not enumerate every product question.

It should produce a generic query:

```json
{
  "task": "product_question",
  "product_ids": [78],
  "raw_question": "它那个布会不会老往下掉？",
  "question_meaning": "询问该面膜的服帖性和是否容易滑落",
  "safety_sensitive": false,
  "reference_basis": "previous_visible_candidate"
}
```

The query describes:

- what the user wants to do;
- which product or products they mean;
- the unrestricted natural-language meaning of the question;
- whether safety handling is required;
- how the reference was resolved.

It does not require a predefined `sheet_slippage` intent or a fixed label from
a giant vocabulary.

## 9. Product-Scoped Evidence Retrieval

The retriever must:

1. hard-scope candidates to the resolved product IDs;
2. search both raw user wording and translated meaning;
3. search full evidence content, not tags alone;
4. prefer exact-product evidence over brand-level evidence;
5. enforce capability and safety policy before returning evidence;
6. return explicit no-evidence and ambiguity reasons;
7. keep deterministic citation IDs and selection reasons.

The result is an `EvidencePacket`:

```json
{
  "query": "询问面膜服帖和滑落体验",
  "product_ids": [78],
  "selected": [
    {
      "evidence_id": "...",
      "reason": "direct semantic match to 滑落",
      "source_label": "商家引用的消费者自评"
    }
  ],
  "safety_caveats": [],
  "missing_aspects": []
}
```

This may be described as product-evidence RAG, but it must not reuse a generic
knowledge RAG as an unrestricted Agent search. Product identity and evidence
policy are hard boundaries.

## 10. Answer Construction

The output layer receives only the selected packet. It may organize and
connect evidence, but facts remain code-controlled.

The model may choose:

- the order of explanation;
- concise versus detailed phrasing;
- whether to lead with a verdict or a caveat.

Code controls:

- product identity;
- exact numbers;
- evidence type;
- study population and sample size;
- comparison baseline;
- attribution;
- disclaimers;
- safety language;
- citations.

The model must not turn:

```text
35-person consumer self-report
```

into:

```text
clinically proven effectiveness
```

## 11. Two Reviewed Examples

### 11.1 Winona mask, product 78

Thirteen current images contain distinct evidence types:

- packaging-version notice;
- product positioning;
- problem and scenario pairings;
- instrumental test results;
- consumer self-report results;
- purslane mechanism claim;
- two-molecular-weight hyaluronic acid mechanism claim;
- six "free from" merchant claims;
- sheet material and liquid-capacity design;
- sheet experience self-reports;
- brand-level publication claim;
- two FAQ pairs;
- study footnotes and disclaimers.

The current 23 production claims preserve only part of this. Missing or
flattened content includes:

- 91% and 88% consumer self-reports;
- three 100% sheet-experience self-reports;
- scenario-to-problem relationships;
- packaging-version explanation;
- FAQ structure;
- ten-times carrying-capacity claim and footnote;
- the boundary between brand-level publications and product-level proof.

### 11.2 SkinCeuticals CE serum, product 34

Five current images contain:

- 15% vitamin C positioning and 30 ml specification;
- product identity, origin, ingredients, benefits, shelf-life advice;
- four problem scenarios;
- 15% L-ascorbic acid, 1% vitamin E, and 0.5% ferulic acid relationship;
- purity, concentration, and pH-below-3.5 claims;
- full skincare application sequence.

The current 13 claims omit or flatten:

- four scenario relationships;
- "use promptly after opening";
- the pH-below-3.5 claim;
- the merchant's absorption mechanism claim;
- the complete application sequence;
- ambiguity around the phrase "after beauty treatment."

These examples demonstrate why a field-first design loses information.

## 12. Current Chain Support and Gaps

### Already present

- task modes for recommendation, comparison, suitability, knowledge, and
  follow-up;
- product-name and conversational reference resolution;
- canonical product IDs;
- hard constraints and soft facet compilation;
- deterministic ranking and decision logic;
- typed response events;
- a Merchant Claim reader and display event.

### Missing

- the full `EvidenceBlock` asset;
- product-scoped evidence retrieval by unrestricted question meaning;
- `EvidenceQuery` and `EvidencePacket` contracts;
- executable product knowledge and follow-up branches;
- a grounded answer composer;
- full-image audit accounting;
- physical recovery or recrawl of 667 historical source images.

The current `knowledge` branch explicitly says it lacks evidence. The current
follow-up branch explicitly says it has no executable operation. Direct
suitability uses Canonical facts, and recommendation output mechanically
selects only a few merchant claims. The architecture can host the new
subsystem, but the feature does not exist yet.

## 13. Earliest-Failure Audit

End-to-end failures must be classified at the earliest incorrect layer:

```text
source image missing
  -> image content misunderstood
  -> evidence relationship modeled incorrectly
  -> capability authorization incorrect
  -> product reference incorrect
  -> question meaning translated incorrectly
  -> evidence retrieval incorrect
  -> ranking/decision incorrect
  -> answer expression incorrect
```

Repair that layer and add a regression at that boundary plus one real
end-to-end case. Do not compensate in a later layer.

Testing should be proportional, not enormous:

- strict contract tests for each boundary;
- a small set of representative category cases;
- historical failure cases;
- real indirect and follow-up language;
- end-to-end proof that the correct evidence was selected and cited;
- explicit over-clarification and fabrication checks.

## 14. Delivery Estimate

### Agreed overnight execution shape

The overnight work has three ordered objectives:

1. **Image evidence production:** recover the missing source images, personally
   review all available images, preserve useful content as open-world evidence
   blocks, and give every image and content block an explicit status.
2. **Architecture integration:** add the bounded product-evidence contracts,
   product-scoped retrieval, and grounded answer handoff without replacing the
   existing understanding, decision, or presentation architecture.
3. **Combined closure:** run real direct, indirect, paraphrased, and follow-up
   questions through the complete chain; classify each failure at the earliest
   incorrect layer; repair that layer instead of adding downstream keyword
   patches.

Visual review and evidence decisions must be performed by the main Agent
itself. Do not delegate image review, evidence extraction, relationship
recovery, or acceptance decisions to sub-agents. OCR and deterministic scripts
may assist with inventory, candidate generation, hashing, and validation, but
they cannot substitute for the main Agent reading the source image.

### What one focused day can credibly finish

- strict `EvidenceBlock`, `EvidenceQuery`, and `EvidencePacket` contracts;
- content-addressed asset loader and product-scoped reader;
- a deterministic retrieval baseline over raw text, meaning, relations,
  qualifiers, and tags;
- integration into existing knowledge/follow-up/answer boundaries;
- Winona 78 and SkinCeuticals 34 as real vertical slices;
- representative indirect-language, reference, safety, and no-evidence gates;
- closure of the current 1,136-claim runtime lock if handled first.

This is enough to prove the architecture end to end.

### What one focused day cannot honestly guarantee

- recover or recrawl all 667 missing historical images;
- visually review all 972 images;
- split every useful content block;
- verify every cross-product, footnote, and multi-column relationship;
- reach complete production coverage for all 103 products;
- run every broad acceptance gate after all data is promoted.

At 45-90 seconds per image, visual review alone is roughly 12-24 hours before
asset writing, source recovery, implementation, and verification.

### Realistic weekend interpretation

The code architecture and two real vertical slices are a one-day job. Full
catalog evidence recovery is a separate data-production track that can run
continuously after the contracts are proven. It must not be declared complete
from a sample.

The working target for the overnight Goal is full available-image closure, not
a sample. The main Agent should continue through the inventory instead of
stopping after representative products. Completion still depends on source
availability: recovered and reviewed images may be completed overnight, while
genuinely unavailable historical images must be reported as blocked with the
failed recovery path. A missing source must not be hidden to manufacture a
100% completion claim.

## 15. Definition of Done

The final Goal may be called complete only when:

1. every referenced image is physically available or explicitly blocked;
2. every image has a review status;
3. every useful accepted content block has an `EvidenceBlock`;
4. every accepted block is answerable unless a recorded safety policy forbids
   expression;
5. every rank/compare/hard projection links back to evidence;
6. no tag or predefined intent is required for answerability;
7. indirect, paraphrased, and follow-up questions retrieve the correct
   product-scoped evidence;
8. clarification occurs only under the agreed ambiguity rules;
9. answers preserve attribution, numbers, qualifiers, and disclaimers;
10. no model-generated product fact or safety guarantee is accepted;
11. ranking and answering remain independent consumers;
12. the current production asset/runtime/test locks are internally consistent;
13. focused, Guide, runtime, compile, boundary, and diff gates pass;
14. a final report lists accepted, ambiguous, rejected, expired, cross-product,
   duplicate, answerable, and rankable counts with evidence hashes.

## 16. Explicit Non-Goals

- no online image reading for every user question;
- no image binaries in PostgreSQL;
- no unrestricted Agent search over all products;
- no attempt to enumerate every possible user question;
- no fixed global tag vocabulary as an ingestion gate;
- no hard filtering from merchant marketing claims;
- no keyword patch in the answer layer to hide upstream failures;
- no sub-agent use for this work: the main Agent personally performs visual
  review, evidence extraction, relationship recovery, integration, and
  earliest-failure diagnosis;
- no implementation or Goal execution before final review of this written
  specification and explicit Goal activation.

## 17. Approved Technical Decisions

### 17.1 Storage

Use content-addressed JSONL plus a manifest and an in-memory product index for
the first production version. This matches the repository's existing
deterministic asset pattern, keeps every change reviewable, and avoids spending
the overnight window on database migrations. Image bytes stay in a
content-addressed file or object asset, not PostgreSQL.

The interface must remain storage-independent so a database-backed reader can
replace the JSONL reader later without changing understanding, decision, or
answer contracts.

### 17.2 Retrieval

Use a product-scoped deterministic hybrid:

1. exact phrase and normalized term matches;
2. FAQ question and answer matches;
3. structured relation and qualifier matches;
4. translated unrestricted question-meaning matches;
5. optional semantic similarity as a bounded candidate signal;
6. source-scope, capability, and safety-policy reranking.

Semantic similarity may nominate evidence but may not override product scope,
source identity, safety policy, or explicit contradictions. Free descriptors
and tags are supporting signals, never the sole retrieval path.

### 17.3 Evidence budget

Preserve the complete ranked packet internally. By default, expose up to five
non-duplicate evidence blocks per product and up to eight total blocks to the
answer composer. Prefer coverage of distinct requested aspects over repeated
claims. A user request for more detail or a follow-up may retrieve additional
blocks from the same full packet.

Safety caveats, source attribution, and qualifiers do not count against the
content budget and may not be dropped to save space.

### 17.4 Brand-level evidence

Keep brand-level and product-level evidence in the same asset schema with an
explicit `subject_scope`. Exact-product and exact-variant evidence always takes
precedence. Brand evidence may answer a brand-level question but cannot prove a
specific product effect unless an explicit source relationship binds it to
that product.

### 17.5 Execution order

Run the overnight Goal in this order:

1. close the existing 1,136-claim manifest/runtime/test checkpoint;
2. add the minimal open-world evidence contracts and deterministic asset
   validation;
3. recover source images and audit them product by product, allowing observed
   tags and relations to grow without changing the core contract;
4. build answer and optional ranking projections from reviewed blocks;
5. integrate `EvidenceQuery -> EvidenceRetriever -> EvidencePacket` into the
   existing knowledge, follow-up, suitability, comparison, and answer
   boundaries;
6. run real direct, indirect, paraphrased, ordinal-reference, and multi-turn
   cases;
7. diagnose and repair the earliest failing layer;
8. run focused, Guide, runtime, compile, boundary, and diff gates;
9. report complete counts, hashes, unavailable sources, and residual risks.
