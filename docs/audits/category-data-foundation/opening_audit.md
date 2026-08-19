# Category-Aware Data Foundation Opening Audit

## Scope

- Repository: `/Users/bytedance/Desktop/xiaoro-fresh`
- Frozen source: `4dda1cae24082c385d01e756ed62f9d15c1894a3`
- Audit profile: `category-data-full-file-v1`
- Files reviewed: 11
- Lines reviewed: 2,852
- Result: `P0=0; P1=2; P2=1`

## Mechanical Facts

- Canonical products: 103
- Canonical raw categories: 39
- Guide formal topics: 2 (`sunscreen`, `serum`)
- Canonical fields per product: 13
- Known domain fields: 239/927 (25.8%)
- Historical review candidates: 336
- Historical strict review candidates: 111
- Approved review sources: 6
- Approved review products: 42, 49, 55
- Current approved review product coverage: 3/103 (about 2.9%)
- Focused verification: 52 passed

The three original HTML files used for the historical 336/111 audit are not
present in the current reproducible repository or surviving source
directories. Those counts are provenance, not a result rerun by this audit.

## Findings

### 1. [P1] Guide formal category routing covers only sunscreen and serum

- File: `app/guide/understanding/contracts.py:21-24`
- Confidence: 10/10

The final Canonical catalog has 39 raw categories, but `TopicCode` only exposes
`sunscreen` and `serum`. Foundation, cushion, cleanser, makeup remover,
fragrance, lipstick, and other categories cannot enter the formal Guide
category path and continue to depend on legacy routing.

Required direction:

- add six explicit category profiles;
- map all 39 raw categories exactly once;
- fail closed on an unmapped category;
- do not default an unknown category to skincare.

### 2. [P1] Guide decision facts do not expose category-specific fields

- File: `app/guide/adapters/catalog/canonical_guide_catalog.py:49-89`
- Confidence: 10/10

The Guide decision surface currently reads price, efficacy, suitable skin,
ingredients present, and verified absences. It has no formal foundation
shade/finish/coverage/longevity, fragrance family/note/longevity, or cleanser
cleansing/rinse/double-cleanse fields.

Required direction:

- define strict field applicability by profile;
- define source authorization and capability separately from value;
- keep unknown/conflict/not-applicable neutral;
- use the old facet registry only as design reference.

### 3. [P2] Approved review assets have a validator but no reproducible builder

- File: `app/guide/retrieval/approved_review_assets.py:123-166`
- Confidence: 9/10

The loader strongly validates the existing six approved rows, but the
reproducible repository has no production tool that builds pending candidates,
quarantine, review decisions, JSONL, manifest, and the audit machine block from
declared raw inputs. Manual expansion would require synchronized edits across
multiple artifacts.

Required direction:

- add deterministic pending/quarantine builders;
- require explicit human decisions for promotion;
- atomically regenerate production assets;
- preserve the current six approved sources byte-for-byte;
- never claim a 336/111 rerun without the locked original HTML inputs.

## Verification

Executed:

```text
tests/guide/retrieval/test_category_taxonomy.py
tests/guide/retrieval/test_canonical_retrieval.py
tests/guide/retrieval/test_scenario_constraints.py
tests/guide/adapters/catalog/test_canonical_guide_catalog.py
tests/guide/retrieval/test_approved_review_assets.py
```

Result:

```text
52 passed in 0.66s
```

Generated visual reports:

```text
/tmp/xiaoro-fresh_category_audit_20260810/report.html
/tmp/xiaoro-fresh_category_audit_20260810/report.md
```
