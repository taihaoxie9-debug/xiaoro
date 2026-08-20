# Selection Concept Identity Closure

**Date:** 2026-08-15

**Repository:** `/Users/bytedance/Desktop/xiaoro-fresh`

**Branch:** `rebuild`

## Verdict

The post-evidence selection-concept audit is closed:

```text
machine-style soft facts reviewed = 40
affected products = 8
kept closed efficacy enums = 6
normalized concepts = 30
dropped ordinary safety duplicates = 4
unresolved machine-style soft facts = 0
```

The audit did not change:

- answer text;
- display claims;
- source locators;
- ProductEvidence qualifiers or disclaimers;
- allowed-use permissions;
- rank strengths;
- verified facts;
- safety warnings.

## Why This Audit Was Needed

The answer and permission audit was already complete, but some legacy
MerchantClaim and ProductEvidence projections still used machine values such
as:

```text
redness_relief
barrier_support
skin_refining
all_skin_types
```

Open Chinese preferences are matched against normalized selection values.
These values could therefore miss a Chinese request even though the exact
answer evidence existed.

## Decisions

The authoritative row-by-row review is:

```text
docs/audits/evidence-use/selection_concept_audit_v1.jsonl
sha256 = 7093fe8bfd4051d177ed6cd7121c8e368b7fd8ba2c5807cfc684e88633724413
```

Six values remain machine enums because they are members of the project's
closed `EfficacyTarget` contract, including `anti_aging`, `brightening`, and
`soothing`.

Thirty values were normalized to source-faithful Chinese concepts. Examples:

```text
redness_relief -> 舒缓泛红
fine_line_reduction -> 淡化细纹
barrier_repair -> 修护屏障
hydrating -> 补水
skin_refining/smoothing -> texture:平滑细腻
acne_improvement -> skin_concern:痘痘
closed_comedone_improvement -> skin_concern:闭口
```

Four ordinary MerchantClaim facts were removed:

```text
PID 105 suitable_skin:all_skin_types
PID 106 suitable_skin:all_skin_types
PID 106 skin_concern:compromised_barrier
PID 106 skin_concern:redness
```

They duplicated safety-style ProductEvidence while carrying the weaker
`ordinary` role. Keeping them would have allowed the ordinary source to mask
the reviewed `merchant_positive_safety` role. ProductEvidence remains
available for ordinary weak ranking and is ignored in serious safety mode.

## Asset Locks

| Asset | SHA-256 |
|---|---|
| Selection concept audit | `7093fe8bfd4051d177ed6cd7121c8e368b7fd8ba2c5807cfc684e88633724413` |
| MerchantClaim JSONL | `8b90f33d45368c269076d96a8b0ca76fd1c5fcac988fd96cc93937da7d4207fd` |
| MerchantClaim manifest | `d906c0a6d42636c89d1ccb408413c786b817cbb2ddf44678143c427228a21e75` |
| ProductEvidence JSONL | `f3872a84388c7d5abfe73f8512d327f8294988daa46ed97823f961122370cb04` |
| Image audit JSONL | `112e2483b01d9dac8d7d1515d69e6ef68e7aab44395b21441585b11bcb85ad3b` |
| ProductEvidence manifest | `44b4956f4ca14a3149f2895e628a03510de331b9b684dc32fde5fe075c7ddb3b` |

## Runtime Effect

Before:

```text
unique SelectionFact = 2,336
strength 1 = 1,326
strength 2 = 463
non-ranking = 547
```

After:

```text
unique SelectionFact = 2,322
strength 1 = 1,312
strength 2 = 463
non-ranking = 547
```

The fourteen removed rows are duplicate weak concepts or unsafe ordinary
duplicates. No strong or non-ranking fact was lost.

PID 106 now has:

```text
efficacy:舒缓泛红
efficacy:舒缓皮肤不适
efficacy:改善毛孔粗大
texture:平滑细腻
texture:清爽
skin_concern:痘痘
skin_concern:闭口
suitable_skin:全肤质 (merchant_positive_safety)
```

The 80.65% and 14-day consumer statements remain exact ProductEvidence with
sample, method, duration, and disclaimer.

## Verification

```text
builder and selection focused: 31 passed
ProductEvidence answer/retrieval/real matrix: 25 passed
selection concept identity: 2 passed
git diff --check: PASS
frontend SHA-256:
70ec29f8298fb912e578b718a214619d590214ddcd556ad0ad7ab1613efdbc95
```

The runtime imports no new alias dictionary. The concept audit is applied only
at asset build time and is included in both asset provenance locks.
