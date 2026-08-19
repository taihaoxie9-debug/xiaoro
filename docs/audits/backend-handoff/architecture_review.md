# Backend Handoff Architecture Review

Date: 2026-08-15

## Matrix Evidence

```text
matrix rows: 35
matrix contract + row assertions: 36 passed in 2.67s

handoff_matrix_v1.jsonl SHA-256:
1c6cf19865021628b064df24184081645804d172ff7147b7792211dba4f4a1b8

test_backend_handoff_matrix.py SHA-256:
1d645a2a528a19f483ce8ffcc022105589f4c7330cc769494c51a53bb53bf4a7
```

Coverage:

```text
profile: 6
image: 6
consultation: 7
knowledge: 8
recommendation/comparison/follow-up: 8
```

The module executes composed consultation/profile state once, shares its
confirmed owner-bound profile with the production image suitability flow,
uses the production image flow and canonical catalog, loads both knowledge
assets through runtime composition, runs text recommendation/comparison and
follow-up through the real composer, and calls the single transition reducer
for direct state-transaction cases.

## Responsibility Review

### Is the model still translation-only?

Yes for stored state. `SemanticIntentProposal` has no mutation acts. The
remaining `revise_constraint` and `withdraw_constraint` strings are exact
parser proof enums, not model output.

The route model receives a code-derived binding authority packet. It cannot
create a candidate, image, focused object, topic, or prior-constraint
authority.

### Does code own every stored-state transition?

Yes. Text runtime, budget revision, skin revision, and official evaluator all
call the same `reduce_constraint_state` implementation through
`plan_code_owned_transitions` or a closed adapter. No second reducer was found.

### Can general knowledge influence product ranking?

No. GeneralKnowledge is consumed only by runtime composition, text
application routing, deterministic retrieval, code rendering, typed SSE, and
knowledge focus state. Decision, category-fact, SelectionFact, hard-filter,
and profile modules do not import it.

### Can ProductEvidence escape product scope?

No. ProductEvidence queries require explicit product IDs. The text flow checks
the product-scoped branch before general knowledge. Product/general packets
are emitted as distinct typed events and never merged.

### Can profile data cross owners?

No. Profile owner is server-composed from session identity for anonymous
runtime use. SQLite profile facts are owner-keyed, conversation owner is
immutable, and matrix execution proves another owner sees no fact.

Current explicit input outranks confirmed session and long-term profile. The
matrix proves an explicit oily turn changes only the current query while the
stored dry profile remains unchanged.

### Can consultation produce a diagnosis?

No. Consultation records observable answers and a provisional skin target.
Profile persistence requires explicit confirmation. Rejection is read-only.
Pain/severe boundaries emit terminal medical escalation, zero cards, and no
ordinary profile fact.

### Can image similarity bypass hard conditions?

No. Similarity performs recall/identity only. Typed budget/profile suitability
and canonical decision facts run afterward. Ambiguous identity stops before
decision and cards. Invalid image ordinals return typed clarification.

### Are there duplicate recommendation or retrieval engines?

No. The matrix imports production vertical components; it does not implement
an alternate engine. GeneralKnowledge adds one isolated retriever for a
different evidence domain and cannot select products. Product selection still
uses the existing Canonical/SelectionFact decision path.

### Does presenter/frontend code hide a backend defect?

No. Matrix assertions inspect typed events and stored state before frontend
rendering. `app/static/chat.html` is byte-frozen and unchanged:

```text
70ec29f8298fb912e578b718a214619d590214ddcd556ad0ad7ab1613efdbc95
```

The chat adapter has a strict zero-card `general_knowledge` protocol; it does
not synthesize missing products or answers.

## Complexity Added

New production abstractions:

```text
SemanticRouteBindingAuthority
GeneralKnowledgeDocument/Block/Manifest/Query/Hit/Packet
GeneralKnowledgeAssets loader
GeneralKnowledgeRetriever
RenderedGeneralKnowledgeAnswer
typed GeneralKnowledgeEvent
knowledge focus fields on ConversationSnapshot
```

New build/audit abstractions:

```text
controlled Markdown parser
manual disposition materializer
clean permission auditor
content-addressed asset publisher
```

Duplicated logic removed:

- build and runtime retrieval use the same source-derived term extractor;
- runtime and gate use the same transition compiler/reducer;
- profile resolution is shared by text and image composition;
- knowledge follow-up uses stored IDs only as a retriever boost, not a second
  answer path.

Files with broad orchestration responsibility:

- `text_recommendation_flow.py` routes recommendation, product knowledge, and
  general knowledge. The three branches remain separated by typed ports and
  packets; no evidence type is interpreted by another branch.
- `composition.py` owns asset locking and dependency assembly. It loads each
  knowledge asset once per runtime.
- `test_backend_handoff_matrix.py` is intentionally large test orchestration;
  it contains no production decision logic.

Compatibility branches:

- GeneralKnowledge is adapted to the existing public event dictionary while
  frontend rendering is intentionally deferred.
- Existing product-free knowledge fallback remains when a caller constructs a
  text orchestrator without a GeneralKnowledge retriever.

## Deficiencies Found During Matrix Work

1. The first matrix follow-up used "那海边呢", but the only source block
   containing "海边" was rejected because the same indivisible list block
   contained unsafe broad sunscreen claims. Returning a gap was correct.
   The matrix now uses "那海边场景呢", which is grounded by the accepted prior
   block's exact "场景" evidence.
2. The initial image similarity expected order was written as identity order.
   Production decision assets already freeze the actual ordered result as
   `[55, 57, 53]`; the matrix now records that authoritative order.
3. The first matrix version referenced a focused profile-image suite instead
   of executing the cross-vertical handoff. It now confirms a dry profile and
   consumes it in the production image suitability flow in the same
   owner/session state.

No production fix was required by the matrix. The defects were all in matrix
evidence construction or unsupported test assumptions.

## Remaining Architecture Risks

- Official DeepSeek route/detail quality remains below the frozen production
  threshold. Code safety and state authority are green, but semantic release
  is `NO-GO`.
- The local knowledge corpus is not a primary-source medical corpus and has
  not received formal medical/regulatory review.
- General knowledge is lexical and intentionally returns gaps for paraphrases
  without shared source terms.
- The two-stage semantic lane still incurs route and detail inference stages.
  No reviewer call was added, but the production cost/latency tradeoff remains
  for final design review.
- Frontend does not render `general_knowledge`; this is an intentional stop
  point, not a hidden backend fallback.

## Verdict

The backend ownership target is reached:

```text
model translation
  -> exact/source validation
  -> code-owned transitions and safety
  -> isolated evidence retrievers
  -> typed backend events and CAS state
```

No new responsibility collision that can corrupt production state or product
selection was found. Final production status still depends on local full gates
and three official model runs.
