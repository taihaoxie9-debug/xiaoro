# Skincare OCR Review A

## Scope

- Reviewed PIDs: `100, 105, 106, 129, 131, 132, 133, 135, 24, 32, 33, 34, 35, 36, 37, 38`
- Source files reviewed: 16
- OCR images reviewed: 35
- Extracted JSONL records: 33
- Output JSONL: `/private/tmp/xiaoro_ocr_review_skincare_a.jsonl`
- Repository writes: 0

## Result Counts

| field_key | records |
|---|---:|
| efficacy | 17 |
| mechanism | 4 |
| safety_transcript | 3 |
| usage | 3 |
| texture | 3 |
| suitable_skin | 2 |
| skin_concern | 1 |

| pid | records |
|---|---:|
| 24 | 1 |
| 32 | 1 |
| 35 | 1 |
| 36 | 3 |
| 37 | 1 |
| 38 | 2 |
| 105 | 7 |
| 106 | 17 |

## Review Rules

- Every `display_claim` is copied from one identified OCR image. OCR punctuation, line breaks, and suspected recognition errors are retained rather than silently repaired.
- `efficacy` and `mechanism` are merchant-claim evidence only. They are not promoted to confirmed efficacy, clinical evidence, ingredient facts, or independent ranking authority.
- Safety, pregnancy/lactation cautions, sensitive-skin usability, and low-irritation language are restricted to `safety_transcript`. All such records use `scope=safety_transcript_only` and `normalized_value.rankable=false`.
- Ingredient-list text was not promoted to strong evidence. Ingredient-effect panels and formula-system copy were retained only as merchant efficacy/mechanism claims where product attribution was clear.
- Promotions, prices, gifts, sales rankings, platform guarantees, version/packaging explanations, customer-photo noise, and unrelated or bundled SKU claims were excluded.
- Repeated near-identical images were reviewed but not duplicated in the output; the clearer, more complete source image was retained.

## No Extractable Detail Evidence

- No detail images: `100, 129, 131, 132, 133, 135, 33`
- PID `34`: one image reviewed; OCR only contained the brand string `ZSKINCEUTICALS`, with no usable skincare field.

## Image-Level Exclusions

- PID `105`: images 0 and 1 were near-duplicates, so image 1 was retained. Images 2-3 were packaging/version comparisons; image 4 was quantity/SKU display; image 5 was pricing policy; images 7-12 were empty or customer-photo noise; image 13 showed unrelated cross-SKU examples. The ingredient list in image 6 was not upgraded.
- PID `106`: image 1 was pricing policy; image 3 was primarily sales/title copy duplicating clearer efficacy evidence; images 8-9 were customer product photos without field evidence.
- PID `24`: price cuts, gifts, and logistics were removed; only the main cream's efficacy phrase remained.
- PID `32`: sales ranking, gift quantity, and logistics were removed.
- PID `35`: membership offers and the gifted discoloration serum were removed to avoid cross-SKU contamination.
- PID `36`: image 0 only contained a brand token. The formula panel in image 1 remains a mechanism claim, not ingredient proof.
- PID `37`: image 0 was empty and image 2 was unreadable bottle text; rankings, cross-border sales copy, and logistics were removed from image 1.
- PID `38`: image 1 mixed B5 mask and B5 serum and centered a mask claim, so it was excluded as bundle/cross-SKU evidence.

## Validation

- JSONL parse: passed
- Required provenance keys present on all 33 records: `pid`, `field_key`, `display_claim`, `normalized_value`, `scope`, `source_basename`, `image_file`, `image_index`, `rationale`
- Invalid efficacy/mechanism scope: 0
- Rankable safety transcript: 0
