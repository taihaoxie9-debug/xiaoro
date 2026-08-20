# Color Makeup OCR Review Summary

## Scope

- Reviewed only: `detail_114_ocr.json`, `detail_115_ocr.json`, `detail_116_ocr.json`, `detail_117_ocr.json`, `detail_118_ocr.json`, and `detail_86_ocr.json`.
- Reviewed all 28 `images[]` entries in source order.
- `image_index` in the JSONL is 1-based and matches each source JSON's `images[]` order.
- Output contains 44 atomic claim records. Product titles were used only to understand identity, never as claim evidence.
- The fresh repository was not modified.

## Results

| PID | Images | Accepted records | Main accepted fields |
|---:|---:|---:|---|
| 114 | 1 | 5 | `finish`, `texture`, `longevity`, `color_payoff` |
| 115 | 0 | 0 | None; source says `no_detail_images` |
| 116 | 1 | 3 | `color_family`, `color_payoff`, `suitable_skin` |
| 117 | 20 | 27 | `finish`, `color_family`, `makeup_effect`, `safety_claim` |
| 118 | 4 | 2 | `makeup_effect` |
| 86 | 2 | 7 | `finish`, `texture`, `color_family`, `suitable_style` |

## Category Decisions

- Lipstick: `哑光`, `哑润`, `水润`, and `润泽` were treated as lip finish. `丝滑` and `滋润` were treated as application feel/texture. This prevents velvet or matte appearance from being confused with the physical formula texture.
- Eyeshadow: `爆闪`, `碎闪`, `偏光`, `混闪`, and `湿漉漉` were treated as sparkle/visual finish. Base shades such as `冷萃棕底`, `透明底`, and `冷灰底` were treated as `color_family`. No sparkle wording was converted into powder texture.
- Blush: only the explicit on-face effects `修饰轮廓` and `提升气色` were retained. No matte, shimmer, coverage, or texture value was inferred from the product photo.
- `coverage` remains unknown for all six PIDs. `显色` and `一摸显色` were recorded as `color_payoff`, not coverage.
- Suitability was kept narrow: PID 116's `黄皮` wording is a merchant suitability claim; PID 86's bare-face/natural wording is `suitable_style`, not skin type.

## SKU Isolation

- PID 117 is a multi-variant listing. Every shade-specific claim uses `scope.level=sku_variant` with its explicit shade label.
- The four-shade image at index 13 was split by adjacent shade layout into `鸢尾蝶`, `海王心`, `橘汽摇滚`, and `薄荷爵士`; no value was promoted to PID-wide product scope.
- Repeated promotional images were not used to broaden a variant claim to sibling SKUs.
- PID 118 claims were limited to the explicitly named `NARS 腮红 4013`.

## Safety Handling

- `拒绝动物实验` is retained only as `品牌宣称拒绝动物实验`, scoped to the URBAN DECAY brand.
- It is not represented as third-party certification, verified cruelty-free status, ingredient safety, or suitability for a protected population.

## Exclusions

- Removed coupons, discounts, price explanations, membership benefits, rankings, livestream copy, celebrities/influencers, gifts, logistics, invoices, customs instructions, authenticity guarantees, and customer-review images without usable claims.
- Removed gift-product claims for setting spray and cleansing oil from PID 117.
- Did not infer PID 115 facts from its product title because it has no detail images.
- Did not use PID 118 title-only `显色` or PID 114/86 title-only shade information.
- OCR anomalies remain visible in `display_claim`; normalization is explicit in `normalized_value`. Notable cases are PID 116 `一摸显色` -> `一抹显色` and PID 117 `白兰碎闪` -> likely `白蓝碎闪`.

## Visual Cross-check

Four retained PID 117 sample images were still present locally and were visually checked: `钻石狗`, `溜溜冰`, `月亮勺`, and the `茶牛郎/钻石狗` campaign image. Their visible text supports the OCR interpretation. Other historical source images were absent locally, so those entries were reviewed from the preserved per-image OCR payload without inventing visual details.
