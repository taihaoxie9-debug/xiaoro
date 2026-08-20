# Slice 1.8 Verified-Absence 事实审计

状态：`CONFIRMED_NO_GO`

执行边界：只读商品事实；未联网；未修改 `data/canonical/**`；未开放成分排除成功能力

## 结论

- 决策：用户已明确确认 `NO-GO`
- 用户确认：“确认 Slice 1.8 采用 NO-GO：不修改 Canonical、不开放成分排除成功能力，并继续进入 Slice 1.9”
- Canonical 商品：103
- 受支持商品：28（防晒 12，精华/精华液 16）
- 审核决定：1234；其中 `verified_absences` 审核决定：0
- 出现明确 absence 表述的受支持商品：5
- 候选事实：14
- 严格合格事实：0
- Canonical 前后 SHA 一致：是

## 结构化摘要

| Key | Value |
|---|---|
| schema_version | verified-absence-audit-v1 |
| recommendation | NO-GO |
| supported_product_ids | 26,32,33,34,35,36,37,38,39,40,41,42,51,52,53,54,55,56,57,58,59,63,91,101,102,105,129,130 |
| supported_category:精华 | 14 |
| supported_category:精华液 | 2 |
| supported_category:防晒 | 5 |
| supported_category:防晒乳 | 1 |
| supported_category:防晒乳液 | 4 |
| supported_category:防晒隔离 | 1 |
| supported_category:防晒霜 | 1 |
| canonical_products | 103 |
| supported_products | 28 |
| supported_sunscreen_products | 12 |
| supported_serum_products | 16 |
| review_decisions | 1234 |
| supported_review_decisions | 320 |
| verified_absence_review_decisions | 0 |
| seed_image_records | 103 |
| beauty_seed_products | 56 |
| candidate_source_products | 5 |
| candidate_facts | 14 |
| qualified_facts | 0 |
| rejected_facts | 14 |
| canonical_sha_unchanged | true |

现有本地来源记录中能找到“不含/不添加/无香”等明确表述，但没有任何一条
同时具备来源获取时间、absence 专项审核决定、absence 审核人和原始来源内容
SHA。商品 91 另有来源记录 25ml 与 Canonical 50ml 的版本歧义。因此本轮不能
把任何候选写成 `verified_absences=known`，也不能开放成分排除成功能力。

## 严格准入

每条事实必须同时包含：

1. `product_id`
2. 规范化物质名
3. 明确 absence 原文
4. 正式来源 URL 或标识
5. 来源获取时间
6. source class
7. absence 审核决定和审核人
8. source content SHA

任一字段缺失即为 `NO-GO`。数据库记录的 `created_at/updated_at` 只作为本地
记录时间展示，不冒充来源获取时间；`data/seed_dump.sql` 单行 SHA 只用于机械
回指，不冒充原始网页或正式资料的 content SHA。

## 扫描结果

| 范围 | 数量 | 结果 |
|---|---:|---|
| Canonical 商品 | 103 | 全量读取 |
| 受支持防晒 | 12 | 全部 `verified_absences=unknown` |
| 受支持精华/精华液 | 16 | 全部 `verified_absences=unknown` |
| 受支持商品审核决定 | 320 | 无 absence 专项决定 |
| 图片 source metadata | 103 | 仅图片 SHA，不是来源内容 SHA |
| beauty seed metadata | 56 | 有部分正式链接，不含本次所需完整审计链 |
| absence 候选来源商品 | 5 | 14 条候选全部拒绝 |

## 候选分组

| Product | Canonical 类目 | 候选物质 | 来源标识 | 主要拒绝原因 |
|---:|---|---|---|---|
| 53 | 防晒乳液 | 香精 | `tmall item 572910260362` | “无香”需审核规范化；缺获取时间、absence 审核和 source content SHA |
| 54 | 防晒霜 | 酒精 | `tmall item 526608696236` | 表述来自派生 OCR enrich；缺获取时间、absence 审核和 source content SHA |
| 55 | 防晒乳 | 酒精、香精、色素、防腐剂 | `tmall item 746513552108` | 缺获取时间、absence 审核和 source content SHA；后两项仍需物质规范化复核 |
| 63 | 精华液 | 酒精、香精、色素、矿油、尼泊金酯类防腐剂 | `tmall item 611233066987` | 缺获取时间、absence 审核和 source content SHA；色素仍需物质规范化复核 |
| 91 | 精华 | 香精、色素、矿油 | `jd item 10069603621835` | 缺获取时间、absence 审核和 source content SHA；25ml/50ml 版本歧义 |

## 结构化候选

| Candidate ID | Product ID | Substance | Source line | Rejection codes |
|---|---:|---|---:|---|
| p53-fragrance | 53 | 香精 | 344 | MISSING_ABSENCE_REVIEW, MISSING_SOURCE_ACQUIRED_AT, MISSING_SOURCE_CONTENT_SHA, SOURCE_TERM_REQUIRES_REVIEW_NORMALIZATION |
| p54-alcohol | 54 | 酒精 | 340 | DERIVED_ENRICHMENT_NOT_PRIMARY_SOURCE, MISSING_ABSENCE_REVIEW, MISSING_SOURCE_ACQUIRED_AT, MISSING_SOURCE_CONTENT_SHA |
| p55-alcohol | 55 | 酒精 | 312 | DERIVED_ENRICHMENT_NOT_PRIMARY_SOURCE, MISSING_ABSENCE_REVIEW, MISSING_SOURCE_ACQUIRED_AT, MISSING_SOURCE_CONTENT_SHA |
| p55-fragrance | 55 | 香精 | 312 | DERIVED_ENRICHMENT_NOT_PRIMARY_SOURCE, MISSING_ABSENCE_REVIEW, MISSING_SOURCE_ACQUIRED_AT, MISSING_SOURCE_CONTENT_SHA |
| p55-colorant | 55 | 色素 | 312 | DERIVED_ENRICHMENT_NOT_PRIMARY_SOURCE, MISSING_ABSENCE_REVIEW, MISSING_SOURCE_ACQUIRED_AT, MISSING_SOURCE_CONTENT_SHA, SUBSTANCE_CLASS_REQUIRES_NORMALIZATION |
| p55-preservative | 55 | 防腐剂 | 312 | DERIVED_ENRICHMENT_NOT_PRIMARY_SOURCE, MISSING_ABSENCE_REVIEW, MISSING_SOURCE_ACQUIRED_AT, MISSING_SOURCE_CONTENT_SHA, SUBSTANCE_CLASS_REQUIRES_NORMALIZATION |
| p63-alcohol | 63 | 酒精 | 308 | DERIVED_ENRICHMENT_NOT_PRIMARY_SOURCE, MISSING_ABSENCE_REVIEW, MISSING_SOURCE_ACQUIRED_AT, MISSING_SOURCE_CONTENT_SHA |
| p63-fragrance | 63 | 香精 | 308 | DERIVED_ENRICHMENT_NOT_PRIMARY_SOURCE, MISSING_ABSENCE_REVIEW, MISSING_SOURCE_ACQUIRED_AT, MISSING_SOURCE_CONTENT_SHA |
| p63-colorant | 63 | 色素 | 308 | DERIVED_ENRICHMENT_NOT_PRIMARY_SOURCE, MISSING_ABSENCE_REVIEW, MISSING_SOURCE_ACQUIRED_AT, MISSING_SOURCE_CONTENT_SHA, SUBSTANCE_CLASS_REQUIRES_NORMALIZATION |
| p63-mineral-oil | 63 | 矿油 | 308 | DERIVED_ENRICHMENT_NOT_PRIMARY_SOURCE, MISSING_ABSENCE_REVIEW, MISSING_SOURCE_ACQUIRED_AT, MISSING_SOURCE_CONTENT_SHA |
| p63-parabens | 63 | 尼泊金酯类防腐剂 | 308 | DERIVED_ENRICHMENT_NOT_PRIMARY_SOURCE, MISSING_ABSENCE_REVIEW, MISSING_SOURCE_ACQUIRED_AT, MISSING_SOURCE_CONTENT_SHA |
| p91-fragrance | 91 | 香精 | 333 | DERIVED_ENRICHMENT_NOT_PRIMARY_SOURCE, MISSING_ABSENCE_REVIEW, MISSING_SOURCE_ACQUIRED_AT, MISSING_SOURCE_CONTENT_SHA, SOURCE_PRODUCT_VARIANT_AMBIGUOUS |
| p91-colorant | 91 | 色素 | 333 | DERIVED_ENRICHMENT_NOT_PRIMARY_SOURCE, MISSING_ABSENCE_REVIEW, MISSING_SOURCE_ACQUIRED_AT, MISSING_SOURCE_CONTENT_SHA, SOURCE_PRODUCT_VARIANT_AMBIGUOUS, SUBSTANCE_CLASS_REQUIRES_NORMALIZATION |
| p91-mineral-oil | 91 | 矿油 | 333 | DERIVED_ENRICHMENT_NOT_PRIMARY_SOURCE, MISSING_ABSENCE_REVIEW, MISSING_SOURCE_ACQUIRED_AT, MISSING_SOURCE_CONTENT_SHA, SOURCE_PRODUCT_VARIANT_AMBIGUOUS |

逐条字段、真实 URL、本地记录时间、seed 行号、整行 SHA、相关但不构成 absence
批准的 safety 审核决定，均见
[`verified_absence_audit.json`](verified_absence_audit.json)。

## 弱推断排除

- 成分表未出现某物质，不推导为“不含”。
- 完整 INCI 的差集不构成 absence。
- “温和”“敏感肌可用”“不刺激”等泛化安全文案不构成 absence。
- 用户评价或客服泛称不构成正式 absence。
- 两篇知识文档中的“小棕瓶不含酒精”被隔离为非正式知识来源，未进入候选。
- “不含致痘刺激成分”“无油配方”没有单一规范化物质名，未进入 14 条候选。

## 审核记录边界

商品 53、54、55、63、91 均存在 `safety` 审核决定和审核人，但这些决定审核的
是结构化 safety 字段，不是具体 absence 事实，不能挪作 absence 批准记录。
全量 1234 条审核决定中没有 `facet_key=verified_absences` 的记录。

## Canonical 保护值

| Path | SHA before | SHA after |
|---|---|---|
| `data/canonical/core_products_v1.jsonl` | `0ba95df8c38d39f5bc0d73a32c318b157903abb64778c3e7b0acebfb75e95734` | `0ba95df8c38d39f5bc0d73a32c318b157903abb64778c3e7b0acebfb75e95734` |
| `data/canonical/core_products_v1_manifest.json` | `e0430a244af451a3fa73642295c4a79128e1622dfeed19ff8140eda9f2df0c69` | `e0430a244af451a3fa73642295c4a79128e1622dfeed19ff8140eda9f2df0c69` |
| `data/canonical/shadow_review_v1/review_decisions.jsonl` | `12b0e1f82df3509ad8886af68a04ddcc62b28f3d3a5c72f4496ea22708fe50e9` | `12b0e1f82df3509ad8886af68a04ddcc62b28f3d3a5c72f4496ea22708fe50e9` |
| `data/canonical/shadow_review_v1/review_decisions_manifest.json` | `999be8b3238176ed57cab47d2fa7db30ed76a2840908bc9c2d52c06a3ec7f633` | `999be8b3238176ed57cab47d2fa7db30ed76a2840908bc9c2d52c06a3ec7f633` |
| `data/canonical/seed_product_images_v1.jsonl` | `5a5a0c40deb80050b59b52203339497c73c3df1adc37b90799b1a62b1e5d9ab0` | `5a5a0c40deb80050b59b52203339497c73c3df1adc37b90799b1a62b1e5d9ab0` |
| `data/canonical/seed_product_images_v1_manifest.json` | `47e3680b6b6d5c497890ae320c61b8a8deea8cd5e5ff8baccd2b7c13d661fdd7` | `47e3680b6b6d5c497890ae320c61b8a8deea8cd5e5ff8baccd2b7c13d661fdd7` |

## 决策门检查点

| Key | Value |
|---|---|
| state | CONFIRMED_NO_GO |
| decision | NO-GO |
| token_checkpoint | SLICE_1_8_COMPLETE_OR_CONFIRMED_NO_GO |
| goal_id | 6a76acf2a50b6afe00c97e8c |
| cumulative_tokens | 0 |
| stage_delta | 0 |
| token_observation | GET_GOAL_CONFIRMED |
| goal_status | active |
| head | 27c02b0ea93158bc0b866cdff53f7bc4def31ae1 |
| user_approval_recorded | true |
| user_approval_statement | 确认 Slice 1.8 采用 NO-GO：不修改 Canonical、不开放成分排除成功能力，并继续进入 Slice 1.9 |
| recorded_at | 2026-08-08T06:44:16Z |
| task_4_6_complete | true |
| canonical_change_authorized | false |
| canonical_status | UNCHANGED |
| ingredient_exclusion_success_capability | BLOCKED |
| go_subtasks | 5.1,5.3,5.4=N/A_NO_GO |
| next_stage | SLICE_1_9 |

用户已批准 `NO-GO`。因此 Task 5.1、5.3、5.4 作为 GO 分支条件项明确
`N/A`；Canonical 保持不变，成分排除成功能力继续阻塞，阶段进入 Slice 1.9。
