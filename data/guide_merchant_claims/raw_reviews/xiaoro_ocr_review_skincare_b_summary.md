# OCR Skincare Review B

## Scope

- 审查 PID：39、40、41、42、43、45、46、47、48、49、50、59、60、61、62、63、64。
- 来源：`detail_<pid>_ocr.json`，共逐图人工核读 199 张旧 OCR 图片。
- 输出：145 条 JSONL，覆盖 14 个有有效字段证据的 PID。
- `image_index` 为源 JSON `images` 数组的零基索引；`source` 仅保存源文件 basename。
- 仅提取 `texture`、`suitable_skin`、`skin_concern`、`efficacy`、`mechanism`、`usage`、`safety_transcript`。

## Counts

| field_key | count |
|---|---:|
| efficacy | 42 |
| mechanism | 33 |
| safety_transcript | 15 |
| skin_concern | 6 |
| suitable_skin | 18 |
| texture | 11 |
| usage | 20 |
| **Total** | **145** |

| pid | rows | review note |
|---:|---:|---|
| 39 | 0 | 仅品牌/系列英文，无目标字段证据 |
| 40 | 0 | `images` 为空 |
| 41 | 1 | 美白/透白功效 |
| 42 | 14 | CT50功效、质地及线粒体/胶原机制 |
| 43 | 2 | 保湿、干纹和锁水功效 |
| 45 | 16 | 干燥敏感肌、神经酰胺机制、质地、用法 |
| 46 | 0 | 仅采销/品牌推荐与销售说明，无目标字段证据 |
| 47 | 12 | 仅保留夜胶原霜；其他胶原霜SKU未混入 |
| 48 | 17 | 仅保留菁纯奢护霜；轻盈面霜等系列SKU未混入 |
| 49 | 5 | 屏障保湿霜功效与PBS机制 |
| 50 | 12 | 特护霜敏感场景、质地、功效、机制和无添加 |
| 59 | 2 | 两张独立主图的同一功效证据 |
| 60 | 7 | 菌菇水泛红/闭口功效与NF-kB机制 |
| 61 | 2 | 金盏花水控油、痘痘闭口和泛红功效 |
| 62 | 23 | 樱花水与原生液按scope拆分，未合并成单一SKU |
| 63 | 12 | 极光水双相质地、四酸/酶机制、用法和安全提示 |
| 64 | 20 | 流金水功效、肤质、保湿机制、用法和安全转录 |

## Review Rules

- 按护肤品类语义逐图判断，没有使用统一关键词词表批量扫取。
- `exact_display_claim` 保留 OCR 原文及可辨识断行；`normalized_value` 只做语义归一，不把缺失百分号或模糊数字强行修复。
- 商家功效与机制均按宣称记录；体外、3D 模型或原料实验在 `scope`/`rationale` 中明确限定。
- 无添加、温和、低刺激、儿童限制、项目后可用、伤口禁用和防晒警示全部进入 `safety_transcript`。
- 榜单、活动、价格、回购、赠品、会员权益、物流、售后和用户晒单均丢弃。
- 系列对比图仅提取当前 SKU 对应列；明确存在双版本的 PID 62 使用变体级 `scope` 分开记录。

## Ambiguities

- PID 62 image 8 只识别到“尼泊金酯/香精/酒精/防腐剂”，否定图标未被 OCR 识别，因此仅原样转录，未归一为“不含”。
- PID 64 image 10 明文识别到“不添加酒精成分”，香精和油分的否定图标在 OCR 中缺失；归一值明确标注为图示宣称。
- OCR 中的“I川型/川型胶原”结合相邻 I 型、V 型版面归一为 III 型，但原文保持不改。

## Validation

- 145/145 行通过 `jq` 解析。
- 145/145 行字段集合一致。
- 145/145 行的 `source`、`image_index`、`image_file` 与源 JSON 完全匹配。
- 未修改 fresh 仓库；仅写入用户指定的两个 `/private/tmp` 文件。
