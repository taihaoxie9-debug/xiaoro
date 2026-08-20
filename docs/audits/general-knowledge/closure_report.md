# Trusted General Knowledge Closure Report

Date: 2026-08-15

Repository: `/Users/bytedance/Desktop/xiaoro-fresh`

Branch: `rebuild`

Release status: backend knowledge implementation complete; overall release
remains `NO-GO` because the official semantic model gate is not yet green.

## Result

The 22 existing local educational Markdown documents are now a Guide-owned,
audited, content-addressed knowledge asset.

```text
source documents: 22
candidate blocks: 241
reviewed blocks: 241
published blocks: 209

general_answer: 174
escalation_only: 27
product_specific_redirect: 8
rejected: 32

missing reviews: 0
duplicate reviews: 0
unknown reviews: 0
invalid reviews: 0
permission mismatches: 0
source mismatches: 0
```

The main agent read and assigned one manual disposition to every candidate.
No text/title vocabulary scanner granted permissions.

## Source Documents

| Source | Source SHA-256 |
|---|---|
| `01-敏感肌选品原则.md` | `e5da1260e8de1fa7ea8d3f1e092c238c5e7e21b563e5497527bee3001de713a1` |
| `02-油皮与混油皮护肤方案.md` | `62f0061c2b24376c3c8b7b2624a752b652ef3878dc3ca221eb8a4b19f8eaa9ba` |
| `03-干皮保湿修护方案.md` | `025043e6ae977e47ef6d4717b8f30b07a7a0b22a9f86408425eb5eb81b19310d` |
| `04-痘肌选品与避雷.md` | `ebb35dbc39d433db690c43d2a6d8adf17abed5502edca164ff49982271adcc66` |
| `05-屏障受损怎么修护.md` | `481122058b90c692eb14b0363bd4daa2b6c3925a05feb41c0e0310603b1f74ca` |
| `06-防晒怎么选.md` | `1da37247f0af76d931b2465670ca6763a21acd4c02f896dabd744bb45a0b0a5e` |
| `07-精华怎么选.md` | `cae34db0e9abfe7f533c200c6769bc4aa32a37828aa8a54d5fbf67f8bbabedd8` |
| `08-面霜怎么选.md` | `842e7eb4b59bc8c4328f97aebd6d41b790aac8b9b670c837bf7656bfe9af60c8` |
| `09-洁面怎么选.md` | `d8fb50334427fa85cb42251e703beb040d834ba77e3a972ca6e7de25595de57a` |
| `10-卸妆怎么选.md` | `9f43e0c65ad778295c2e398055d104da45e9391610451fbe566eb27ac6519242` |
| `11-眼霜怎么选.md` | `76cb6b262c6a0f00c1d072cb7b4a07be02fae3c3f38606d713d0f176d2aa496f` |
| `12-面膜怎么选.md` | `a2364f86fd73db9ef077ee3507fe929f9dc3af18801965c71af0f47eb96db922` |
| `13-烟酰胺适合谁.md` | `c5ce058e0a43ec2ad883a32c20301b2a10597b341ebb55c889f897f089e81b13` |
| `14-视黄醇A醇适合谁.md` | `179d29b390a48218ef9b48f3a8bec8b7a02f3b037363413a6f9010a9665461e1` |
| `15-水杨酸与酸类产品适合谁.md` | `5fa3c74ca677b72a36c22df788df69f33339c5fd96455c2ed210fc4eb2dfcc5e` |
| `16-玻色因与肽类抗老怎么理解.md` | `d7fab57d426af68661245be4b51a017da2cb55ab7322d16b63935ae6ccd7a97d` |
| `17-维C抗氧化怎么用.md` | `affe1a957df21dc879abc10510ec520782cd06249ee2a486486776b45e9cc6b6` |
| `18-粉底液按肤质怎么选.md` | `bae231304c9d88974d6350618415eab9678974fed21220b7d1f44a4d616750a0` |
| `19-定妆产品怎么选.md` | `ac90daf848befe3f8a2921beacb0ae5a41a40b2e65623f87fcd585f39c4c6ecf` |
| `20-口红与唇妆怎么按场景选.md` | `3dd52d2c545980a1275553b0da37d80d995cc6a3e1d51878f114f9e1f413abf1` |
| `21-干敏肌抗初老精华怎么选.md` | `44ceac5e5320c359887768d0671ef9a5ef710f577b2b87e8ef49b63113af395d` |
| `22-怎么判断自己是不是敏感肌.md` | `ed7b3e28ed5d380a8da58eb0665034bc26eba73f1d81217ec08d5c1d2b05e26c` |

Concatenated source bytes SHA-256:

```text
2512f3fda4f86a5bba026a52d8259aaa851709bd64a85629f973340539321680
```

## Content-Addressed Assets

```text
schema_version:
guide-general-knowledge-v1

candidate JSONL SHA-256:
bb8f25a5fe5a119d29877054302cf3919e180663e5f28cf1d5eb618b0bc4a2a8

manual decision catalog SHA-256:
afde2f019b05a5fb3a02acb30656217dc50aa2a4b132aecbaa84f234a7d40051

concatenated review JSONL SHA-256:
2283b892c6f8de4ea5228289789b447e32af1083ee92c2e766e8876b2e9e9e87

published JSONL SHA-256:
6ca9dfa1acda79972842645737760764662e7d53a5fc3276109110ea81d3e453

manifest logical self-hash:
562161e524dc63cd418cd8ddf098c3f41add86ecd9ef5a9cffee83865cadd10e

manifest file bytes SHA-256:
f0bbcf268e6508b130d158cfd0ecc5ed02f1e50847ab4eb28511dc459829b178
```

Runtime composition pins the logical manifest hash and loads/verifies the
asset once. Loader verification covers:

- manifest self-hash and runtime lock;
- content-addressed JSONL filename and bytes;
- source document hashes;
- review-file hash inventory;
- block IDs, order, permissions, and counts;
- decision and allowed-use counts;
- exclusion of rejected blocks.

## Permission Model

Every reviewed block has all five forbidden uses:

```text
product_fact
hard_filter
soft_rank
safety_guarantee
profile_write
```

Published allowed-use counts:

```text
answer: 174
citation: 209
followup: 209
medical_escalation: 27
```

The application passes GeneralKnowledge only to the deterministic retriever
and code-owned renderer. No GeneralKnowledge type is imported by decision,
SelectionFact, category fact, hard filtering, ranking, or profile modules.

## Retrieval Behavior

The retriever uses:

- lowercase ASCII source/query terms;
- Chinese source/query characters, runs, and bigrams;
- corpus document frequency;
- separate body, H1, and H2 weights;
- one global low-confidence threshold;
- a bounded related-prior boost;
- a fixed product-redirect penalty;
- medical escalation boost only for safety-sensitive queries.

It does not use a global skincare keyword dictionary, embeddings, an online
provider, or a title-specific threshold.

Frozen representative outcomes:

```text
SPF和PA分别是什么意思
-> 06 防晒怎么选 / 怎么选

烟酰胺有什么作用
-> 13 烟酰胺适合谁 / 关键成分/原理

敏感肌怎么判断
-> 22 怎么判断自己是不是敏感肌 / 判断章节

口红通勤怎么选
-> 20 口红与唇妆 / 通勤场景 guidance

玻色因有什么作用
-> 16 玻色因与肽类 / general mechanism
   (specific-product redirects cannot outrank it)

明天上海天气怎么样
-> no hit / explicit evidence gap
```

## Answer and State Flow

The backend emits:

```text
event: general_knowledge
data:
  query
  citations[]
    knowledge_id
    title
    section_title
    exact_excerpt
    source_path
    review_decision
  educational_only: true
  medical_escalation
```

The renderer:

- copies only audited exact excerpts for ordinary education;
- never generates knowledge prose with a model;
- emits an explicit evidence gap for no hit;
- emits a professional-care boundary for escalation blocks;
- never renders product-redirect text as a general product fact;
- never exposes local absolute paths or SHA values in prose.

Conversation state stores sorted, unique
`focused_general_knowledge_ids` and the last question. General follow-up may
use those IDs only as a bounded related-query boost. A fresh unrelated
knowledge question receives no prior boost and clears the old IDs.

Product IDs always route to ProductEvidence before GeneralKnowledge. General
answers do not modify recommendation query context, candidate order, focused
product, or profile state. Product/recommendation state transitions clear
general-knowledge focus where they create a new product result.

## Architecture Audit

Does Guide import legacy `app.services`?

```text
No.
```

Can general knowledge select or rank a product?

```text
No. There is no import or data path into decision/ranking/SelectionFact.
```

Can it satisfy a hard or safety constraint?

```text
No. Every block forbids hard_filter and safety_guarantee.
```

Can product-specific text leak into ordinary general answers?

```text
No. Product blocks are redirects; renderer excludes their exact text from
ordinary answer prose.
```

Is every runtime block reviewed?

```text
Yes. Clean audit covers all 241 candidates; 209 non-rejected blocks publish.
```

Is the asset loaded once?

```text
Yes. Runtime composition constructs one locked asset and one retriever.
```

Can follow-up inherit unrelated knowledge?

```text
No. Prior boost requires follow-up mode and related source-term overlap.
Fresh knowledge uses no prior IDs.
```

Does a model synthesize unsupported knowledge prose?

```text
No. Retrieval and rendering are deterministic code.
```

## Verification

```text
14 passed
  strict knowledge contracts

11 passed
  controlled Markdown parser

10 passed
  audit and materialization

6 passed
  content-addressed assets and drift rejection

9 passed
  deterministic real-corpus retrieval

128 passed
  renderer, typed SSE, chat adapter, public contracts

747 passed in 83.84s
  integrated knowledge/state/application/runtime focused suite

7456 passed in 440.50s
  Guide full

239 passed in 76.72s
  Guide runtime

26 passed in 2.46s
  architecture/import boundaries plus frontend freeze

compileall app/tools: passed
git diff --check: passed
staged index: empty
```

Frontend remained unchanged:

```text
app/static/chat.html
SHA-256:
70ec29f8298fb912e578b718a214619d590214ddcd556ad0ad7ab1613efdbc95
```

## Changed Paths

Created:

```text
app/guide/application/general_knowledge_answer.py
app/guide/retrieval/general_knowledge_assets.py
app/guide/retrieval/general_knowledge_contracts.py
app/guide/retrieval/general_knowledge_retrieval.py
app/guide/retrieval/general_knowledge_terms.py
tools/guide_data/build_general_knowledge.py
tools/guide_data/audit_general_knowledge.py
data/guide_general_knowledge/
docs/audits/general-knowledge/
tests/guide/application/test_general_knowledge_answer.py
tests/guide/retrieval/test_general_knowledge_assets.py
tests/guide/retrieval/test_general_knowledge_contracts.py
tests/guide/retrieval/test_general_knowledge_retrieval.py
tests/guide/tools/test_audit_general_knowledge.py
tests/guide/tools/test_build_general_knowledge.py
```

Modified:

```text
app/guide/application/chat_api_adapter.py
app/guide/application/text_recommendation_flow.py
app/guide/feedback/contracts.py
app/guide/presentation/sse_events.py
app/guide_runtime/composition.py
tests/guide/adapters/state/test_sqlite_conversation_state.py
tests/guide/application/test_chat_api_adapter.py
tests/guide/application/test_text_recommendation_flow.py
tests/guide/runtime/test_composition.py
```

No implementation or asset files were staged, committed, pushed, or
deployed.

## Remaining Risks

- The 22 documents are local educational seeds, not a licensed,
  primary-source medical corpus.
- Block review is a conservative engineering audit, not formal medical or
  regulatory review.
- Lexical retrieval can miss paraphrases that share no meaningful source
  terms; it intentionally returns a gap instead of guessing.
- Exact excerpts preserve original Markdown and any limitations of the source
  writing.
- The frontend does not render `general_knowledge` yet by explicit scope.
- Official real-model semantic route/detail quality remains the release
  blocker. Backend knowledge completion does not change the overall
  `NO-GO`.
