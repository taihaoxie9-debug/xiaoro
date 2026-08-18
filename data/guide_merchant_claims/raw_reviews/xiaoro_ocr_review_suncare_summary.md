# Suncare OCR Detail Review

## Scope

- 审查 PID：`101, 102, 130, 26, 51, 52, 53, 54, 55, 56, 57, 58`
- 人工逐项阅读 `12` 个 OCR JSON、共 `103` 个 `images` 数组条目。
- 输出有效宣称 `64` 条，覆盖 `8` 个 PID；`4` 个 PID 零提取。
- `image_index` 为各 JSON 中 `images` 数组的 1-based 顺序；同时保留原始 `image_file`。
- 未使用全局词表或关键词批量扫描替代语义阅读。

## Review Rules

- 只保留能绑定当前商品、且对防晒选购或使用有意义的商家宣称。
- 活动、优惠、销量榜、`NO.1`、赠品、售后承诺、品牌历史和无属性信息均丢弃。
- 家族矩阵中其他防晒、喷雾、素颜霜、修白盾等串 SKU 宣称均丢弃。
- SPF/PA、成分和安全信息仅在清晰包装实拍/背标等强包装证据下作为相应结构化字段；普通详情页中的不含、安全、孕妇或敏感人群安全话术统一记为 `safety_transcript`。
- 同一属性在重复详情图、主图和买家图中重复出现时，仅保留信息最完整或证据更强的一条。
- `claim_scope` 均为 `exact_product`；无法确认当前商品归属的内容未写入。

## Product Results

| PID | Images | Claims | Result |
|---:|---:|---:|---|
| 101 | 0 | 0 | JSON 标记 `no_detail_images` |
| 102 | 4 | 8 | 保留肤质、质地、肤感、用法、防水、包装 SPF/PA 及安全转述 |
| 130 | 1 | 2 | 排除销量榜与赠品，仅保留当前小白管肤感和瓶身 SPF/PA |
| 26 | 0 | 0 | JSON 标记 `no_detail_images` |
| 51 | 0 | 0 | JSON 标记 `no_detail_images` |
| 52 | 5 | 5 | 保留菁纯防晒质地、成膜和妆效；价格说明及不清晰包装值丢弃 |
| 53 | 1 | 0 | 唯一图片为平台价格说明，无商品宣称 |
| 54 | 13 | 6 | 保留小蓝瓶肤质、质地、膜感、波段、用法和 SPF/PA；家族其他 SKU 全部丢弃 |
| 55 | 25 | 11 | 保留清透防晒乳肤质、质地、清洁、成膜、妆效、光谱及安全转述；榜单、礼盒和其他防晒 SKU 丢弃 |
| 56 | 11 | 8 | 保留蓝胖子质地、妆效、防水、用法及背标 SPF/PA、部分成分和警示 |
| 57 | 22 | 13 | 保留水润凝蜜质地、成膜、妆效、防水、场景、用法、肤质、清洁、包装 SPF/PA 和警示 |
| 58 | 21 | 11 | 保留盾护防晒膜持久、防水、耐摩擦、户外场景、用法、质地、哑光妆效和包装 SPF/PA；活动榜单及家族其他管丢弃 |

## Field Counts

| Field | Count |
|---|---:|
| `texture` | 11 |
| `usage` | 9 |
| `finish` | 8 |
| `safety_transcript` | 7 |
| `film_speed` | 6 |
| `spf_pa` | 6 |
| `suitable_skin` | 5 |
| `water_resistance` | 4 |
| `cleansing` | 2 |
| `protection_scope` | 2 |
| `usage_scenario` | 2 |
| `friction_resistance` | 1 |
| `ingredients_present` | 1 |

## Evidence Notes

- PID 54 图片 3 的 OCR 在“敏肌适用”附近仅识别到“酒精”，缺少可确认的否定符号，因此未提取“不含酒精”。
- PID 55 的“0 添加/无酒精/无香精/无传统防腐/不致痘”等均为详情页商家话术，只进入 `safety_transcript`。
- PID 56 的 `ingredients_present` 来自买家实拍中文背标，仅摘录 OCR 清晰且有筛选意义的在配成分。
- PID 57 的 SPF/PA 采用带包装正反面图中清晰的“浴前·浴后 SPF50+ PA+++”，未采用 OCR 缺号或模糊的买家图。
- PID 58 的最终 SPF/PA 采用买家实拍“浴前 SPF50+，浴后 SPF41，PA++++”；活动主图中的榜单、赠量及“免补涂”促销组合文案未收录。
