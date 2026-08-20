# Evidence Use and Unified Ranking Closure Report

**Date:** 2026-08-15

**Repository:** `/Users/bytedance/Desktop/xiaoro-fresh`

**Branch:** `rebuild`

## Verdict

本次后端目标已经闭合，但生产发布仍为 **NO-GO**。

- 1,079 条 accepted ProductEvidence 全部完成人工选择用途审计；
- Category Facts、Merchant Claims、ProductEvidence 已统一投影为
  2,336 个去重 `SelectionFact`；
- 对外决策只有硬条件和软排序，弱证据只是软排序内部 1 分；
- 推荐、直接比较、current-item 和 ordinal follow-up 均已输出 typed
  selection slots；
- 第二次完整 Guide 回归为 `7,365 passed`；
- 三次官方真实模型 broad gate 均为 `selected_lane=null`、exit code 3；
- 未改前端渲染，未 push、deploy 或切流量。

因此，本报告确认“证据用途、排序、安全和后端 payload”完成，不宣称
当前模型 lane 可以上线。

## Asset Locks

| Asset | SHA-256 |
|---|---|
| ProductEvidence JSONL | `b6a4afda1a2597c76c35957ee172500b97ce44751645609668408aeca671543a` |
| Image audit JSONL | `95887e17cce615927c489e6de208ab919a8fe25ca35e2e8db7d8f04ec0283920` |
| ProductEvidence manifest | `dbabbece8e267f6a5b36704a00405b803f530f4cbfd3218678ba2e910115c80b` |
| Merchant Claim manifest | `84e38beaa132f655597c8e5aafa577d2abd51ff17db14101f31be1a831ba7c9c` |
| Category Fact manifest | `2293593579a73004ca36653c8cde97041a18ccda6b8ac1397cb5cd7ff5455a43` |

The ProductEvidence manifest covers 972 image references, 1,262 evidence
blocks, and 86 products with evidence.

## Audit Closure

| Review decision | Blocks |
|---|---:|
| `projected` | 518 |
| `answer_only` | 328 |
| `comparison_only` | 192 |
| `safety_gate` | 41 |
| **Accepted and reviewed** | **1,079** |

Audit integrity:

```text
accepted_missing = 0
authorization_mismatches = 0
duplicate_projection_keys_within_one_review = 0
invalid_reviews = 0
```

The reviewed evidence contains 955 strength-1 and 341 strength-2 ranking
projections. Non-ranking compare, hard-filter, and safety projections remain
typed but carry no rank strength.

### Allowed Uses

| Allowed use | Blocks |
|---|---:|
| `answer` | 1,079 |
| `display` | 1,079 |
| `compare` | 666 |
| `hard_filter` | 143 |
| `safety_gate` | 41 |
| `soft_rank` | 82 |
| `weak_soft_rank` | 348 |

`weak_soft_rank` is retained only as an asset permission tag. Runtime converts
it to strength 1 inside the single soft-ranking path; it is not a third
decision lane.

## Capability Change

The baseline asset had 299 unique soft-eligible blocks. The reviewed asset has
429 unique soft-eligible blocks. One PID 104 block carries both legacy soft
permission tags, so the manifest's two soft counts sum to 430.

| Profile | Soft before | Soft after | Compare before | Compare after | Hard before | Hard after |
|---|---:|---:|---:|---:|---:|---:|
| `skincare` | 117 | 182 | 230 | 298 | 54 | 53 |
| `suncare` | 44 | 73 | 73 | 97 | 30 | 30 |
| `base_makeup` | 61 | 72 | 97 | 104 | 22 | 22 |
| `cleanser` | 54 | 78 | 99 | 129 | 24 | 24 |
| `color_makeup` | 20 | 20 | 27 | 30 | 9 | 9 |
| `fragrance` | 3 | 4 | 8 | 8 | 5 | 5 |
| **Total** | **299** | **429** | **534** | **666** | **144** | **143** |

The one removed hard authorization was a PID 98 family/variant composition
block. It remains usable for comparison and weighted selection but cannot
satisfy an exact-product hard ingredient condition.

| Management label | Soft before | Soft after | Compare before | Compare after | Hard after |
|---|---:|---:|---:|---:|---:|
| `brand_research` | 1 | 0 | 4 | 4 | 0 |
| `consumer_self_report` | 35 | 39 | 5 | 11 | 0 |
| `faq` | 8 | 10 | 7 | 12 | 1 |
| `merchant_cited_test` | 29 | 34 | 82 | 89 | 0 |
| `merchant_claim` | 211 | 229 | 229 | 267 | 0 |
| `packaging_information` | 2 | 13 | 23 | 23 | 14 |
| `product_specification` | 13 | 30 | 158 | 160 | 127 |
| `safety_transcript` | 0 | 74 | 0 | 74 | 0 |
| `unclassified` | 0 | 0 | 0 | 0 | 0 |
| `usage` | 0 | 0 | 26 | 26 | 1 |

Safety transcripts can support ordinary preference ranking at weak strength,
but only 41 reviewed warning projections enter `safety_gate`. Merchant-positive
safety claims never become hard facts.

## Answer-Only Exceptions

Only four blocks that were soft-eligible before the audit became
`answer_only`:

| Count | Reason |
|---:|---|
| 2 | Consumer-study index blocks name appearance/skin topics but do not state a confirmed improvement direction. |
| 1 | A test-method index summarizes three methods and sample sets without an independent result; scoring it would duplicate child results. |
| 1 | A raw-material origin/yield/concentration narrative is background marketing, not a current-product preference fact. |

All 328 `answer_only` blocks have a nonempty rationale. Historical narrative,
general science, usage instructions that do not distinguish candidates, and
unrecoverable relations remain answerable without being allowed to move rank.

## Unified Selection Facts

Before deduplication, the three readers produce:

| Source | Raw projected facts |
|---|---:|
| Approved Category Facts | 279 |
| Merchant Claims | 1,033 |
| Reviewed ProductEvidence | 1,502 |
| **Raw total** | **2,814** |

Runtime deduplication uses:

```text
product_id
+ subject_scope
+ variant_scope
+ field_key
+ normalized_value.casefold()
```

Result:

```text
unique SelectionFact keys = 2,336
duplicate occurrences removed = 478
keys with more than one occurrence = 422
cross-asset duplicate keys = 342
single-asset duplicate keys = 80
```

Duplicate sources do not add scores. The merged fact takes the maximum rank
strength, unions capabilities and source references, and preserves all
attributions.

### Strength and Safety

| Dimension | Count |
|---|---:|
| Strength 1 | 1,326 |
| Strength 2 | 463 |
| No ranking strength | 547 |
| `ordinary` | 2,139 |
| `merchant_positive_safety` | 156 |
| `verified_warning` | 41 |

### Attribution Sets

| Exact attribution set | Facts |
|---|---:|
| `merchant_claim` | 1,456 |
| `verified_fact` | 761 |
| `consumer_report` | 61 |
| `merchant_claim + verified_fact` | 38 |
| `consumer_report + merchant_claim` | 18 |
| `consumer_report + verified_fact` | 2 |

### Runtime Coverage

| Metric | Count |
|---|---:|
| Catalog products | 103 |
| Products with soft facts | 100 |
| Products with hard-filter facts | 31 |
| Products with safety-gate facts | 29 |
| Active soft-ranking fields | 38 |
| Facts with `soft_rank` | 1,789 |
| Facts with `compare` | 2,251 |
| Facts with `hard_filter` | 358 |
| Facts with `safety_gate` | 41 |

## Decision Behavior

The decision path is:

```text
exact/code-owned hard constraints
  -> product eligibility
  -> one slot per requested field/value
  -> match / unknown / mismatch
  -> maximum evidence strength per slot
  -> weighted soft ordering
```

Verified facts and qualified tests score 2. Merchant claims and consumer
self-reports score 1. Unknown evidence scores 0. Repeated claims and repeated
images cannot accumulate points.

Ordinary sensitive-skin and ordinary post-procedure preferences may use weak
merchant evidence. Pregnancy, allergy, active damage, adverse reaction,
absolute exclusion, and unknown safety severity use the strict safety path.
In safety-sensitive ranking, `merchant_positive_safety` is ignored.

`claimed_ingredients` can satisfy an ordinary soft preference but cannot
satisfy `InclusionConstraint`. Hard ingredient inclusion requires an
`ingredients_present` fact with `hard_filter`; claimed absence and verified
absence remain separate fields.

## Backend Handoff

Recommendation, named comparison, direct suitability, budget/skin revision,
current-item follow-up, and ordinal follow-up now emit
`DecisionProcessData.selection_slots`.

Each `SelectionSlotData` carries:

```text
product_id
field_key
requested_value
matched_value
match_status
rank_strength
source_refs
attribution
```

Matched slots require evidence value, strength, source references, and
attribution. Unknown or mismatch slots cannot fabricate those fields.
`RecommendationQueryContext` persists facets, ingredient inclusions, and
`safety_sensitive`, so a simple follow-up replays the same code-owned
constraints rather than asking the model to reinterpret “第二个怎么样”.

The frontend handoff contract is complete. Rendering these new fields is
explicitly outside this goal.

## Verification

The first full Guide run exposed 16 failures. They were repaired at the
earliest failing contracts: category-field applicability, deterministic pilot
coverage, typed inclusion compilation, and hard-constraint structural
equality.

| Check | Result |
|---|---|
| Focused evidence/ranking/backend suite | `3,262 passed` |
| Runtime suite | `237 passed` |
| Architecture/import boundary | `25 passed` |
| ProductEvidence real matrix | `1 passed` |
| Full Guide rerun | `7,365 passed, 5 warnings` |
| `python -m compileall -q app tools` | PASS |
| `git diff --check` | PASS |

Full Guide command:

```bash
.venv/bin/python -m pytest -q tests/guide
```

Final full runtime:

```text
7365 passed, 5 warnings in 426.59s
```

## Official Real-Model Gate

Three independent official runs used the frozen 32-case smoke manifest.
`invalid` below counts semantic calls that returned invalid output after the
configured repair attempt and therefore fell back to the exact lane.

| Run | Lane | Route | Detail | Critical route | Invalid | Unsafe task mismatch | Selected |
|---:|---|---:|---:|---:|---:|---:|---|
| 1 | `two_stage_flash` | 78.125% | 50.00% | 5 | 6 | 7 | no |
| 1 | `two_stage_pro` | 90.625% | 58.33% | 3 | 2 | 9 | no |
| 2 | `two_stage_flash` | 78.125% | 50.00% | 5 | 6 | 7 | no |
| 2 | `two_stage_pro` | 90.625% | 58.33% | 3 | 2 | 9 | no |
| 3 | `two_stage_flash` | 78.125% | 45.00% | 5 | 6 | 7 | no |
| 3 | `two_stage_pro` | 90.625% | 58.33% | 3 | 2 | 9 | no |

All three runs had:

```text
hard_constraint_override_count = 0
invalid_output_task_plan_invocation_count = 0
wrong_product_selection_count = 0
selected_lane = null
exit_code = 3
```

Run artifacts:

| Run | Directory | Summary SHA-256 |
|---:|---|---|
| 1 | `/private/tmp/xiaoro-evidence-use-official-run-1` | `c376b7f46a0517904b270e0de4bd60dd54b2f387dd2b4170eb6375694a76ddcd` |
| 2 | `/private/tmp/xiaoro-evidence-use-official-run-2` | `1b26d60a36a9b4bc724e169ea87a8e7740152111dcde76ef2cbf3ca8c66fa9e1` |
| 3 | `/private/tmp/xiaoro-evidence-use-official-run-3` | `f9d84046daf3a2ea93dac2a31a67f9011914e99f0a4c50e1896921ca41bbeb7a` |

The repeatability shows a real model-contract problem, not a one-run network
fluke. Fixture expectations were not weakened.

## Frontend and Release Boundary

The pre-goal dirty frontend was frozen byte-for-byte:

```text
app/static/chat.html
SHA-256 = 70ec29f8298fb912e578b718a214619d590214ddcd556ad0ad7ab1613efdbc95
```

This command produced no output:

```bash
git diff --name-only 4a60283..HEAD -- app/static/chat.html
```

The file already had uncommitted work before this goal; this goal did not
change its frozen bytes. The existing dirty worktree was preserved.

Release boundary:

```text
backend evidence/ranking/payload: COMPLETE
frontend rendering: NOT STARTED BY THIS GOAL
production model selection: NO-GO
push: NOT RUN
deploy: NOT RUN
traffic switch: NOT RUN
blocked-image recrawl: NOT RUN
```

Remaining blockers are the official broad model route/detail hard gates and
repeated invalid structured outputs. The 80 blocked historical images remain
a documented, low-priority data gap and were not allowed to block this backend
closure.
