# Product Evidence Closure Report

**Date:** 2026-08-15

**Repository:** `/Users/bytedance/Desktop/xiaoro-fresh`

**Branch:** `rebuild`

**Design baseline:** commit `3b43943`

**Plan baseline:** commit `8b5e981`

## Verdict

商品证据资产和商品证据主链已经闭合：

- 103 个商品源文件全部盘点；
- 972 个图片引用全部有 recovery row 和 audit row；
- 892 张可用图片已逐图审核，80 张不可恢复图片有 blocked 证据；
- 1,262 个 EvidenceBlock 中 1,079 个 accepted，全部可 answer/display；
- typed 30-case 生产矩阵 30/30；
- 真实 V4-Pro 商品矩阵原始整轮严格 21/30，用户结果 29/30；
- 唯一失败的医美后安全 case 经 detail v6 和安全 transcript 提名修复后，
  单独真实复验通过，因此当前组合闭合 30/30 用户结果；
- 没有错商品证据、模型数字编造或安全保证越权；
- focused、Guide full、runtime full、compile、boundary/import 和
  `git diff --check` 全部通过。

广域官方 32-case 模型选择 gate 仍为 **NO-GO**。没有选择生产 lane，
没有 push、deploy 或切流量。该 NO-GO 不否定本次商品证据闭环，但阻止把
当前两阶段模型宣称为全域生产就绪。

## Asset Closure

| Metric | Count |
|---|---:|
| Canonical products / OCR source files | 103 |
| Referenced images | 972 |
| Physical reviewed images | 892 |
| Blocked images | 80 |
| Unreviewed available images | 0 |
| Physical image bytes | 188,615,485 |
| Image-bearing products | 101 |
| Source files with zero image references | 2 |
| Evidence blocks | 1,262 |
| Accepted evidence blocks | 1,079 |
| Products with accepted evidence | 86 |

Zero-reference source files:

- `detail_26_ocr.json`
- `detail_100_ocr.json`

Available-image products without accepted evidence are PID 53 and PID 108.
Their images were audited, but no block was authorized as accepted answer
evidence.

## Recovery

| Recovery status | Count |
|---|---:|
| `existing_local` | 305 |
| `recovered_from_html` | 543 |
| `current_new_version` | 44 |
| `blocked` | 80 |
| **Total** | **972** |

The 44 current images remain explicitly versioned as
`current_new_version`; none reuse a historical SHA or masquerade as a
historical source.

Every blocked row records the same complete attempt sequence:

```text
existing_local -> old_asset -> saved_html -> current_source
```

Every blocked row ended with:

```text
no identity-bound source image was recoverable
```

| Product ID | Blocked images |
|---:|---:|
| 60 | 5 |
| 72 | 7 |
| 79 | 11 |
| 89 | 1 |
| 90 | 3 |
| 91 | 10 |
| 92 | 5 |
| 93 | 2 |
| 94 | 6 |
| 103 | 9 |
| 116 | 1 |
| 121 | 1 |
| 122 | 10 |
| 146 | 9 |
| **Total** | **80** |

The authoritative per-image filenames, attempts and reasons remain in
`data/guide_product_evidence/recovery_manifest_v1.jsonl`.

## Visual Review

| Image review status | Count |
|---|---:|
| `accepted` | 668 |
| `ambiguous` | 18 |
| `cross_product` | 45 |
| `duplicate` | 66 |
| `expired` | 28 |
| `irrelevant` | 67 |
| `blocked` | 80 |
| **Total** | **972** |

The 892 available files all have a non-blocked audit outcome. Complex
relationships that could not be reconstructed reliably remain ambiguous;
they were not converted into guessed relations.

## Evidence Coverage

### Status

| Evidence status | Count |
|---|---:|
| `accepted` | 1,079 |
| `ambiguous` | 31 |
| `cross_product` | 77 |
| `expired` | 75 |
| **Total** | **1,262** |

### Accepted Labels

| Management label | Accepted |
|---|---:|
| `merchant_claim` | 294 |
| `product_specification` | 162 |
| `safety_transcript` | 126 |
| `merchant_cited_test` | 117 |
| `packaging_information` | 104 |
| `brand_research` | 99 |
| `usage` | 79 |
| `consumer_self_report` | 48 |
| `faq` | 47 |
| `unclassified` | 3 |
| **Total** | **1,079** |

`unclassified` was retained instead of forcing useful content into a false
closed taxonomy.

### Allowed Uses

| Allowed use | Blocks |
|---|---:|
| `answer` | 1,079 |
| `display` | 1,079 |
| `compare` | 534 |
| `weak_soft_rank` | 241 |
| `hard_filter` | 144 |
| `soft_rank` | 58 |

All 1,262 blocks forbid `safety_guarantee`. A total of 1,118 forbid
`hard_filter`; 75 consumer/test blocks explicitly forbid
`clinical_effectiveness`; 160 cross-product records forbid
`cross_product_attribution`.

### Category Profiles

| Profile | Products | Blocks | Accepted |
|---|---:|---:|---:|
| `skincare` | 41 | 583 | 505 |
| `suncare` | 10 | 183 | 161 |
| `base_makeup` | 17 | 200 | 168 |
| `color_makeup` | 5 | 53 | 37 |
| `cleanser` | 11 | 210 | 186 |
| `fragrance` | 2 | 33 | 22 |
| **Total** | **86** | **1,262** | **1,079** |

### Transcription

| Basis | Blocks |
|---|---:|
| `visual_transcription` | 1,221 |
| `ocr_exact` | 41 |

OCR remained a candidate/source aid. The evidence asset is overwhelmingly
based on image-bound visual transcription.

## Runtime Closure

The runtime uses one bounded chain:

```text
existing understanding
  -> Canonical product binding / conversation reference
  -> EvidenceQuery
  -> product_id hard-scoped ProductEvidenceRetriever
  -> EvidencePacket
  -> code-controlled answer and typed product_evidence SSE
```

Key invariants verified:

- product IDs come from Canonical code, never from model output;
- full Canonical names can be recovered when the model omits a mention;
- slash-separated aliases resolving to one Canonical ID are collapsed;
- product-name words are removed from content relevance without deleting the
  original question;
- free descriptors remain bounded supporting signals;
- exact-variant evidence outranks broad product-family evidence;
- evidence cannot select or rescue recommendation/comparison winners;
- suitability, comparison and recommendation attach evidence only after the
  decision;
- current-item and ordinal conversation references persist across turns;
- accepted 35ml and 100ml variants produce a qualified multi-version packet,
  not an invented single answer;
- safety-sensitive queries can nominate product-scoped safety transcripts
  across paraphrases, but only with fail-closed attribution;
- frontend renders escaped evidence, qualifiers, safety caveats, evidence
  gaps and variant ambiguity without exposing local paths or source SHAs.

## Real Matrix

### Typed Runtime

`tests/guide/runtime/test_product_evidence_real_matrix.py`:

```text
30/30 passed
```

This uses the normal runtime, real production assets, Canonical resolution,
SQLite conversation state, real decision code and a typed translator fixture.

### Real V4-Pro

Full route-v4/detail-v5 run:

```text
strict:               21/30 = 70.00%
user-visible outcome: 29/30 = 96.67%
false clarification:   1/30 = 3.33%
wrong-product evidence: 0
provider failures:      1
```

The eight non-strict but successful outcomes were:

- semantically valid `suitability` instead of `knowledge`;
- semantically valid `suitability` for an ordinal fit follow-up;
- a stronger main-package water-resistance block instead of a buyer-photo
  block;
- the dedicated 35-person method footnote instead of the percentage claim.

These equivalences are explicit in
`docs/audits/product-evidence/model_acceptance_v1.json`; strict results remain
unchanged.

The only original user-outcome failure was:

```text
skincare-safety-post-procedure
```

Earliest failure was detail schema translation: the model put the string
`safety_sensitive` into `concerns`. Detail prompt v6 separated the boolean
from concern enums. A real current-state rerun then produced:

```text
mode: suitability
product_ids: [78]
first evidence: a65aa34c4134de285b7d57eda00c441a4175389ceebd44ffa34f74435d1a2272
first label: safety_transcript
caveat: merchant safety claim; not a safety guarantee or hard-filter fact
```

The current combined user-outcome closure is therefore 30/30. This is not
reported as a retroactive 30/30 strict run.

### Official Broad Model Gate

The latest complete official broad smoke was route-v4/detail-v5:

```text
selected_lane: null
exit_code: 3

two_stage_pro:
  route: 30/32 = 93.75%
  detail: 14/25 = 56.00%
  critical route errors: 2
  unsafe task mismatches: 9

two_stage_flash:
  route: 25/32 = 78.125%
  detail: 10/20 = 50.00%
  critical route errors: 5
  unsafe task mismatches: 7
```

Detail v6 fixes the observed safety enum failure but cannot remove the
unchanged route critical errors. The official selection remains NO-GO, and
no production model lane was selected.

## Earliest-Failure Repairs

| Earliest layer | Repair |
|---|---|
| Product reference | Collapse two aliases that resolve to one Canonical ID |
| Product reference | Recover exact full Canonical names omitted by the model |
| Product reference | Parse singular product pronouns without treating “这个品类” as an item |
| Task translation | Normalize a sole `current_item` knowledge reference to follow-up |
| Question translation | Route v4 defines comparison, assessment, revision, image and injection boundaries |
| Detail translation | Detail v6 keeps `safety_sensitive` out of concern enums |
| Retrieval input | Carry code-controlled Canonical identity names only for noise removal |
| Retrieval | Separate provenance language from open product content |
| Retrieval | Restrict confirmed variant boost to `exact_variant` |
| Retrieval | Penalize explicit “this image does not support X” blocks as primary answers |
| Retrieval | Detect strong cross-variant relation conflicts and return both variants |
| Safety retrieval | Nominate product-scoped safety transcripts across plain paraphrases |
| Answer | Render code-controlled ambiguity and safety boundaries |
| Frontend | Add escaped typed product-evidence and ambiguity panels |
| Verifier | Stop old frozen fixtures from falsely comparing undeclared new query fields |

No repair added an answer-layer branch for a failed product reference,
translation or retrieval case.

## Hashes

### Contract Hashes

| Asset | Contract SHA-256 |
|---|---|
| Merchant claims | `8d69e82fb49842cc1a1b4c649bcad812d0d3c58e02ad3e163685fc4704cf3cc3` |
| Merchant claims manifest | `84e38beaa132f655597c8e5aafa577d2abd51ff17db14101f31be1a831ba7c9c` |
| Product evidence | `2c573584788fea81fbe6b6acc33e917f4354b611494bbc52f97c581fed1be517` |
| Image audit | `7118c769fc8189f8fa9fcdcd55d49ecce72ba3ae0c8d3a89329095528259f4a6` |
| Product evidence manifest | `c50c1a289600018ca10b23f08d1f37c7a28169cd5db9115cec36dee78878001d` |

Manifest contract hashes are self-hashes of canonical unsigned payloads.
Physical file hashes are:

| File | Physical SHA-256 |
|---|---|
| Product evidence manifest | `0871e1bcc767a542f31495aca7f0e5cf81a902a0e80bf44b92f54fc67bf3e611` |
| Recovery manifest | `9dde340c824bca49aff180d1e1397d32e10b802f34f53f74ddb57add1944eca9` |
| Merchant claims manifest | `df0f927bfc3d5f06b0d22cbc3b9ff5edd28a4625b103452fbbee9a0fbbb7d3a5` |

## Verification

```text
focused product-evidence suite:
  217 passed

Guide full:
  7308 passed, 5 pre-existing warnings

runtime full:
  233 passed

architecture/import boundaries:
  25 passed

compileall:
  passed

git diff --check:
  passed
```

The five Guide warnings are existing Pydantic protected-namespace and legacy
script escape warnings; no test failed.

No pytest, Uvicorn, Playwright, crawler or local HTTP server from this run
remained active after verification.

## Deviations

The approved architecture was preserved. Additive deviations discovered from
real data were:

1. `EvidenceQuery.product_mention_spans` and
   `EvidenceQuery.product_identity_names` were added so confirmed identity text
   can be removed from relevance scoring without mutating the raw question.
2. `EvidencePacket.ambiguity_reasons` was added because real 35ml/100ml
   evidence proved that `missing_aspects` alone cannot represent a material
   variant conflict.
3. Canonical slash aliases are indexed from the Canonical identity itself;
   no global product dictionary was introduced.
4. Safety transcript nomination is capability-driven under
   `safety_sensitive`, not dependent on fixed product-question tags.
5. The official old detail verifier ignores only the two query fields absent
   from its frozen labels. Product-evidence tests independently enforce those
   fields.

## Residual Risks

1. Eighty historical images remain physically unavailable. All four recovery
   sources were attempted and recorded; these images were not claimed as
   visually reviewed.
2. PID 53 and PID 108 have reviewed available images but no accepted
   answerable block.
3. The broad official model gate is still NO-GO. Product-evidence questions
   close under the real matrix, but broad production semantic cutover must
   remain disabled until that separate gate passes.
4. The worktree contains the full implementation and data assets but is not
   committed. No push or deployment was performed.

## Git Status

HEAD remains:

```text
8b5e981 docs(guide): plan product evidence rollout
```

`git status --short --branch` at closure:

```text
## rebuild
 M .trae/specs/complete-guide-closure-continuously/spec.md
 M app/guide/adapters/llm/intent_detail_prompt.py
 M app/guide/adapters/llm/intent_prompt.py
 M app/guide/adapters/llm/intent_route_prompt.py
 M app/guide/application/chat_api_adapter.py
 M app/guide/application/text_recommendation_flow.py
 M app/guide/decision/facet_ranking.py
 M app/guide/feedback/contracts.py
 M app/guide/intent/contracts.py
 M app/guide/intent/signal_merger.py
 M app/guide/intent/task_planning.py
 M app/guide/presentation/sse_events.py
 M app/guide/retrieval/category_fact_contracts.py
 M app/guide/retrieval/product_name_resolver.py
 M app/guide/understanding/colloquial_budget.py
 M app/guide/understanding/contracts.py
 M app/guide/understanding/exact_parsing.py
 M app/guide/understanding/followup_parsing.py
 M app/guide/understanding/parallel_understanding.py
 M app/guide/understanding/semantic_contracts.py
 M app/guide/understanding/semantic_detail_contracts.py
 M app/guide/understanding/text_understanding.py
 M app/guide/understanding/two_stage_semantic.py
 M app/guide_runtime/composition.py
 M app/static/chat.html
 M docs/audits/category-data-foundation/pilot_coverage.md
 M tests/guide/adapters/test_intent_detail_prompt.py
 M tests/guide/adapters/test_intent_prompt.py
 M tests/guide/adapters/test_intent_route_prompt.py
 M tests/guide/application/test_text_recommendation_flow.py
 M tests/guide/data/test_full_catalog_source_policy.py
 M tests/guide/decision/test_recommendation.py
 M tests/guide/intent/test_signal_merger.py
 M tests/guide/intent/test_task_planning.py
 M tests/guide/retrieval/test_category_fact_contracts.py
 M tests/guide/retrieval/test_category_pilot_coverage.py
 M tests/guide/retrieval/test_product_name_resolver.py
 M tests/guide/runtime/test_composition.py
 M tests/guide/runtime/test_composition_understanding.py
 M tests/guide/runtime/test_frontend_scope.py
 M tests/guide/tools/test_run_real_two_stage_intent_ab.py
 M tests/guide/understanding/test_budget_candidate_validation.py
 M tests/guide/understanding/test_category_profile_parsing.py
 M tests/guide/understanding/test_followup_parsing.py
 M tests/guide/understanding/test_semantic_detail_contracts.py
 M tests/guide/understanding/test_semantic_intent_contracts.py
 M tests/guide/understanding/test_text_understanding.py
 M tests/guide/understanding/test_two_stage_semantic.py
 M tools/guide_gates/run_real_two_stage_intent_ab.py
?? app/guide/application/product_evidence_answer.py
?? app/guide/intent/facet_preferences.py
?? app/guide/retrieval/merchant_claim_assets.py
?? app/guide/retrieval/merchant_claim_reader.py
?? app/guide/retrieval/product_evidence_assets.py
?? app/guide/retrieval/product_evidence_reader.py
?? app/guide/retrieval/product_evidence_retrieval.py
?? data/guide_merchant_claims/
?? data/guide_official_descriptions/
?? data/guide_product_evidence/
?? docs/audits/product-evidence/
?? docs/superpowers/plans/2026-08-14-phase2-guide-night-closure.md
?? docs/superpowers/plans/2026-08-15-natural-language-facet-mainchain.md
?? docs/superpowers/prompts/2026-08-14-phase2-main-chain-data-overnight.md
?? tests/guide/application/test_product_evidence_answer.py
?? tests/guide/data/test_merchant_claim_production_assets.py
?? tests/guide/data/test_product_evidence_production_assets.py
?? tests/guide/retrieval/test_merchant_claim_reader.py
?? tests/guide/retrieval/test_product_evidence_assets.py
?? tests/guide/retrieval/test_product_evidence_retrieval.py
?? tests/guide/runtime/test_product_evidence_real_matrix.py
?? tests/guide/tools/test_build_ocr_merchant_claims.py
?? tests/guide/tools/test_build_product_evidence.py
?? tests/guide/tools/test_crawl_jd_detail_ocr.py
?? tests/guide/tools/test_curate_ocr_review_candidates.py
?? tests/guide/tools/test_recover_product_detail_images.py
?? tools/guide_data/build_ocr_merchant_claims.py
?? tools/guide_data/build_product_evidence.py
?? tools/guide_data/crawl_jd_detail_ocr.py
?? tools/guide_data/curate_ocr_review_candidates.py
?? tools/guide_data/recover_product_detail_images.py
?? tools/guide_gates/run_official_deepseek_smoke.py
```
