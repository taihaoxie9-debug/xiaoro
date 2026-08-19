# Fragrance OCR Review Summary

## Scope

- Inputs: `detail_120_ocr.json`, `detail_121_ocr.json`, `detail_143_ocr.json`
- Reviewed: 25 image entries (PID 120: 7; PID 121: 1; PID 143: 17)
- Output rows: 16
- `image_index` is zero-based and refers to the source JSON `images` array.
- `display_claim` preserves the OCR wording; only line breaks and surrounding whitespace are collapsed.
- No repository files, database records, registry definitions, or source OCR files were changed.

## Results

| PID | Accepted rows | Usable fragrance findings |
|---:|---:|---|
| 120 | 3 | Two bottle-image confirmations of `Cologne`; one generic seller safety/allergy statement retained only as paraphrased safety guidance |
| 121 | 0 | The sole image shows `N°5 L'EAU` and hand cream packaging, but no reliable notes, family, concentration, sillage, longevity, audience, or occasion |
| 143 | 13 | EDP packaging evidence; citrus opening; May rose and jasmine heart; broad floral family; female marketing positioning; label usage and safety statements |

Field totals:

| `field_key` | Rows |
|---|---:|
| `concentration` | 8 |
| `fragrance_notes` | 2 |
| `fragrance_family` | 1 |
| `audience` | 1 |
| `usage` | 1 |
| `safety` | 3 |

Repeated concentration rows are retained because they are independent image-level evidence with distinct files and scopes.

## Missing Evidence

- PID 120: no current-SKU-safe top/middle/base notes, fragrance family, sillage, longevity, audience, or occasion in these old OCR images.
- PID 121: no extractable fragrance registry value from the only image. `L'EAU` is treated as the product name, not as proof of EDT/EDP concentration.
- PID 143: no explicit base notes, sillage, longevity, or occasion. No duration or projection strength was inferred.
- Ingredient/allergen disclosures were not converted into fragrance notes.

## Discarded Material

- PID 120 image 0: price rules.
- PID 120 image 2: shared information covering many Jo Malone SKUs; audience, family, and concentration values cannot be bound to the current SKU.
- PID 120 image 3: `持久留香` appears over a multi-SKU promotional composition and is therefore discarded, along with the ranking language.
- PID 120 image 6: generic classic-bottle series marketing, not a current-SKU fragrance-family statement.
- PID 143 images 4 and 9: membership gifts and samples.
- PID 143 image 5: price rules.
- PID 143 image 6: recommended cross-SKU bath/body products.
- PID 143 images 7 and 10: packaging, membership, customer-service, and delivery material.
- PID 143 images 3 and 15: `PARFUM` packaging conflicts with the current EDP scope and is treated as another concentration/version.
- Logo-only images and non-semantic packaging text were not emitted.

## Safety Handling

Safety and allergy text is only restated at its source scope. The PID 120 Q&A remains generic seller guidance and does not prove the current SKU's alcohol percentage. The PID 143 label warning and disclosed fragrance-related ingredients are not converted into diagnoses, contraindications beyond the label, or inferred allergen effects.
