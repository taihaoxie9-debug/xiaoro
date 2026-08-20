# Review Summary

- Reviewed PIDs: 72, 73, 74, 75, 76, 77, 89, 90, 91, 92, 93, 94, 98, 99
- Input files: 14
- OCR image entries reviewed: 54
- Accepted evidence records: 84
- Output JSONL: `/private/tmp/xiaoro_ocr_review_skincare_c.jsonl`
- Evidence basis: manual, image-by-image reading of the legacy OCR text stored in each requested `detail_<pid>_ocr.json`

## Field Counts

| field_key | records |
|---|---:|
| efficacy | 29 |
| mechanism | 14 |
| safety_transcript | 11 |
| skin_concern | 8 |
| suitable_skin | 6 |
| texture | 8 |
| usage | 8 |

## PID Counts

| pid | records | note |
|---:|---:|---|
| 72 | 8 | Current eye-cream claims retained; multi-product comparison and sales/patent ranking material discarded. |
| 73 | 1 | Promotion, gifts, and sales ranking discarded. |
| 74 | 4 | Medical-device scope preserved; promotion and gift content discarded. |
| 75 | 0 | Source explicitly reports `no_detail_images`. |
| 76 | 1 | Current mask efficacy only. |
| 77 | 2 | B5 serum promotion discarded as cross-SKU; B5 mask claims retained. |
| 89 | 3 | Current lotion claims retained; membership gifts discarded. |
| 90 | 2 | Current 40 ml product retained; 100 ml packaging-comparison variants discarded. |
| 91 | 14 | Current barrier serum retained; institutional history and explicitly named other products discarded. |
| 92 | 6 | Product claims retained; brand story discarded. |
| 93 | 3 | Product claims retained; market ranking discarded. |
| 94 | 11 | Current eye-serum claims retained; referenced companion products were not attributed to the current SKU. |
| 98 | 18 | Blue and green mask variants separated with variant-specific scopes; price rules and duplicate/reposted claims discarded. |
| 99 | 11 | Current mask and packaging-label claims retained; gifts, product-family cross-SKU panel, store services, price rules, and empty review image discarded. |

## Review Rules

- No unified vocabulary scan was used; every accepted record was judged from its local skincare meaning and SKU context.
- `display_claim` preserves the legacy OCR wording exactly, including OCR punctuation or character errors.
- `normalized_value` expresses the reviewed meaning without upgrading merchant claims into verified clinical facts.
- Safety, no-additive, tolerability, and sensitive-skin safety-style statements are confined to `safety_transcript`.
- Promotions, rankings, gifts, price rules, and ambiguous cross-SKU material were excluded.
- PID 98 is the only multi-variant listing retained: blue and green claims were accepted only where the image text bound them unambiguously to a named variant.
