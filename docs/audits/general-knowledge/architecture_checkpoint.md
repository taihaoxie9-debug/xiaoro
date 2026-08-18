# General Knowledge Audit Architecture Checkpoint

Date: 2026-08-15

## Input Integrity

The main agent reviewed every structurally parsed block from the 22 existing
local Markdown documents.

```text
source documents: 22
candidate blocks: 241
candidate JSONL SHA-256:
bb8f25a5fe5a119d29877054302cf3919e180663e5f28cf1d5eb618b0bc4a2a8
```

The controlled parser normalizes line endings only. It preserves exact
paragraph/list text, H1/H2 ownership, source order, repository-relative source
path, source SHA-256, and block SHA-256. It does not use character windows or
a domain keyword dictionary.

The durable manual decision catalog is:

```text
docs/audits/general-knowledge/review_decisions_v1.jsonl
```

It contains one explicit disposition for each section order. Code only
materializes candidate IDs and source/block hashes; it never decides a
disposition from titles or text.

## Clean Audit

```text
candidate_total: 241
reviewed_total: 241
missing_total: 0
general_answer: 174
escalation_only: 27
product_specific_redirect: 8
rejected: 32
permission_mismatches: 0
invalid_reviews: 0
duplicate_reviews: 0
unknown_reviews: 0
source_mismatches: 0
clean: true
```

## Per-Document Decisions

| Document | Total | Answer | Escalate | Product redirect | Rejected |
|---|---:|---:|---:|---:|---:|
| 01 敏感肌选品原则 | 13 | 11 | 1 | 0 | 1 |
| 02 油皮与混油皮护肤方案 | 11 | 6 | 1 | 0 | 4 |
| 03 干皮保湿修护方案 | 11 | 9 | 1 | 0 | 1 |
| 04 痘肌选品与避雷 | 11 | 6 | 4 | 0 | 1 |
| 05 屏障受损怎么修护 | 12 | 10 | 1 | 0 | 1 |
| 06 防晒怎么选 | 11 | 5 | 1 | 0 | 5 |
| 07 精华怎么选 | 16 | 11 | 2 | 1 | 2 |
| 08 面霜怎么选 | 14 | 13 | 1 | 0 | 0 |
| 09 洁面怎么选 | 11 | 9 | 0 | 0 | 2 |
| 10 卸妆怎么选 | 13 | 7 | 1 | 0 | 5 |
| 11 眼霜怎么选 | 12 | 11 | 0 | 0 | 1 |
| 12 面膜怎么选 | 9 | 3 | 4 | 0 | 2 |
| 13 烟酰胺适合谁 | 9 | 9 | 0 | 0 | 0 |
| 14 视黄醇 A 醇适合谁 | 10 | 6 | 3 | 0 | 1 |
| 15 水杨酸与酸类产品适合谁 | 9 | 6 | 3 | 0 | 0 |
| 16 玻色因与肽类抗老怎么理解 | 9 | 9 | 0 | 0 | 0 |
| 17 维 C 抗氧化怎么用 | 10 | 9 | 0 | 0 | 1 |
| 18 粉底液按肤质怎么选 | 9 | 9 | 0 | 0 | 0 |
| 19 定妆产品怎么选 | 10 | 9 | 0 | 0 | 1 |
| 20 口红与唇妆怎么按场景选 | 12 | 7 | 2 | 0 | 3 |
| 21 干敏肌抗初老精华怎么选 | 8 | 2 | 0 | 6 | 0 |
| 22 怎么判断自己是不是敏感肌 | 11 | 7 | 2 | 1 | 1 |

The five broad repeated section groups account for most candidates:

| Section | Total | Answer | Escalate | Product redirect | Rejected |
|---|---:|---:|---:|---:|---:|
| 关键成分/原理 | 49 | 39 | 6 | 2 | 2 |
| 适合谁 | 44 | 31 | 9 | 0 | 4 |
| 怎么选 | 42 | 34 | 1 | 0 | 7 |
| 可以考虑的商品类型 | 41 | 27 | 1 | 2 | 11 |
| 避雷与注意 | 21 | 12 | 8 | 1 | 0 |

Section names did not determine permission. The same section can contain
answerable education, medical escalation, product-specific text, or rejected
content.

## Product-Specific Dispositions

Every product formula, version, price, named comparison, or current-product
conclusion is `product_specific_redirect`; none has ordinary answer
permission.

| Candidate ID | Document | Order | Reason |
|---|---|---:|---|
| `fdd9d2872c9409492954ad9a74b61a33c20ad6f82fb10c0782eee7d4758b674c` | 07 精华怎么选 | 9 | Names SK-II, 小棕瓶, 小黑瓶 and product-linked technologies |
| `e8d4198605fa833d4344980f6fc2dc73fb49d1af58dfbf392ca851a1b6e6126d` | 21 干敏肌抗初老精华怎么选 | 0 | Frames a current thousand-yuan product comparison |
| `ea0f4b0caa8a34f485501b4005ef5ccc2bae06c9eb1ae3016cfba3672c832ef6` | 21 干敏肌抗初老精华怎么选 | 3 | Named formulas, versions, prices, and cross-product conclusions |
| `9bee9359a6c325915a245c5c364c4fd3d59354ab215168f2cf862ec16894622f` | 21 干敏肌抗初老精华怎么选 | 4 | Ingredient claims tied to named products |
| `295a089d0f763a1ed4456084f8a87c5a0c7e0e3c7a86a5ec1efc5e7b290f5233` | 21 干敏肌抗初老精华怎么选 | 5 | Named formula/version safety and substitution claims |
| `27379c84dd08ce5efab0384e97ed2a777c4b5b3a6fc2c4a7cf9b2b6411f2c841` | 21 干敏肌抗初老精华怎么选 | 6 | Named product-type recommendations |
| `3f519a6cbb2f809a48a7757c341cd26e64a697ab9609cb67d26f3edb139f7b22` | 21 干敏肌抗初老精华怎么选 | 7 | Named product winner guidance |
| `7d993c39a630605b1517e2f7de5e511686c36a426b2ad1df2596a97fa390372b` | 22 怎么判断自己是不是敏感肌 | 6 | Uses named products as formula/suitability examples |

Runtime must redirect these questions to current Canonical/ProductEvidence.
The blocks cannot be used as product truth.

## Medical and Safety Dispositions

All blocks containing pregnancy/lactation, prescription or drug use, open
wounds, post-procedure professional care, or persistent/severe symptoms are
`escalation_only`. They have citation/follow-up/medical-escalation permission
and no ordinary answer permission.

| Candidate ID | Document | Order |
|---|---|---:|
| `de9f57af918cdb311533edd930bec14b72e4c92610b8cc709c0da56ce064016a` | 01 | 3 |
| `e803c20722b6fb676c87e0e77e22fd2e7284e5a0c6274f9c7483ae5be9e7f147` | 02 | 8 |
| `b62d8fee8ad1ae01f0c76a02010030b9e628962b47ff9d54756d3b3979d4f92a` | 03 | 2 |
| `3827441444ef990264fc40bf7a055582d24d28d3ae76ff08971d777375ca89ac` | 04 | 2 |
| `941881a1347cfcfd95fa4e4e64dcdb3ade4a8914256cdd103bf4ccf525546935` | 04 | 6 |
| `b9f915d5ad8af1de9ef92cf6175dfd4b0abfd8a84f09bbffa55b137e6aa687c1` | 04 | 7 |
| `bdd92196dca479d06bf0a95cfbf0f46906ce35eb94075928594b374cedf05dbe` | 04 | 8 |
| `8412c4cd6ef5fd98782b582a37f6a3a217784b5b367f194d58f81bd9b27bb004` | 05 | 3 |
| `0720519033b693d5fce8a533d03b9e6d33bb86500e0d1d160a09160edcc85148` | 06 | 2 |
| `13b626920b7c4d998adf1c37a3c277021a4f5d111353b1b905f405fe225a0af5` | 07 | 7 |
| `0ec1367f6ba15416ebac2a4a232ed78a990ec6772dc874b9990fcabe8179486f` | 07 | 11 |
| `9b961e68c50489614f5d4f56930445cc1235a124d89d9da0e5b188f883f02b69` | 08 | 6 |
| `3027a2ef6f29bc5e16ae9debb3c90d65f30b7c869fe9cc7726fc37ab7fcd4da2` | 10 | 10 |
| `dae46eff8a7a770b9df51fc8f0d369fa150da19d75aab35d7bed5f63dbad111a` | 12 | 1 |
| `0839180381fbdbaa12cc1afcecbf3748f5e5d246b620d61b768b91ba15d90d0b` | 12 | 4 |
| `5e6b339a3356ca7fad2b2d382a60b8cbbb1b3de5ddc4f620e58c36af19f79627` | 12 | 5 |
| `28ca8850276d5b0b0e0a5fdd51789e51ca27079d2c7dc89c9c18bc94e55f02c9` | 12 | 7 |
| `7fac71dad95aa3513d72534a5f643953d9fdc20e4b8edb2d708f9ac83afd21ff` | 14 | 1 |
| `8f1e1dfd5dad1fa711a1e14e84f21772a19722c7085e92a0add59ff8573164b6` | 14 | 2 |
| `d5e87ae09bfef89a622beec04389cd249b82faf3c2dc3ac691f4aec7763b4f65` | 14 | 7 |
| `6a0e48bb3bb7230bbc640dccad7f4b499a68107edfd0800ad4a49f1eccd8f22d` | 15 | 2 |
| `290579a4d6261f1518081150f17a656dc8f2632024d3431e4a41e65c98693188` | 15 | 5 |
| `26cefdeccf4bda398cf20a26f9aba52aa7deb7f88b2fdbc4d267e863c2fa8124` | 15 | 6 |
| `31273754982860557cc0489c56c2ec71dbf301dcaaf0d7cfefb8bb3e19ef3897` | 20 | 8 |
| `5c894ce7c2c0f2054052b7e4855483cf07f8998e4946a7d32e1d5ab2eea97d37` | 20 | 10 |
| `59dbdc5c95477fff7ee3f65b1263898f0a16ba21fe775b65012c7efd5aadca71` | 22 | 3 |
| `1b3f1f6cfbfbd8cb0d51967b01fae909462a8bdfbe2e9af25e434c3737c16d75` | 22 | 8 |

These blocks may support an escalation boundary. They cannot diagnose,
recommend a medicine, guarantee pregnancy/allergy safety, or write a profile
fact.

## Rejected Content

The 32 rejected blocks include:

- unsupported absolutes such as all people always needing sunscreen indoors;
- the outdated "physical sunscreen is a mirror" simplification;
- broad claims that dehydration directly causes more oil;
- absolute double-cleansing and sunscreen-removal rules;
- mixed general blocks whose unsafe statement cannot be separated without
  rewriting the source;
- rhetorical closings and heading-only filler with no independent answer
  value.

Rejected text remains traceable in the review inventory and is never
published.

## Permission Boundary

Every reviewed block, including redirects and rejected rows, carries the
complete forbidden-use set:

```text
product_fact
hard_filter
soft_rank
safety_guarantee
profile_write
```

The strict block contract rejects any missing forbidden use. `general_answer`
requires answer and citation permission. `escalation_only` forbids answer and
requires medical escalation permission. `product_specific_redirect` forbids
answer. `rejected` forbids all allowed uses.

Therefore no general-knowledge block can enter SelectionFact, product
ranking, hard filtering, safety guarantees, or profile state. Asset
publication and runtime integration remain pending at this checkpoint.

## Representative Decisions

Accepted:

```text
06 防晒 / 怎么选:
SPF targets UVB and PA targets UVA, with bounded scenario guidance.
```

Escalation:

```text
01 敏感肌 / 适合谁:
persistent erythema, pustules, severe scaling, or intolerable itching
requires dermatology care.
```

Product redirect:

```text
21 干敏肌抗初老精华 / 热门对比:
named formulas, versions, suitability conclusions, and current prices.
```

Rejected:

```text
09 洁面 / 清洁误区:
contains an absolute claim that cleanser cannot remove sunscreen.
```
