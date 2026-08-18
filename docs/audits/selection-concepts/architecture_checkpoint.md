# Selection Parent Concept Architecture Checkpoint

Date: 2026-08-15

## Inventory

```text
products with SelectionFacts: 100
SelectionFacts: 2,322
soft-rank SelectionFacts: 1,775
inventory SHA-256:
a4a97a5f4d26b9db63336a4a713924427f0c91f123e3c754cee82dea637d8134
```

## Candidate Boundary

The audit did not scan prose or build user-language aliases. Candidates were
limited to structured values that:

- belong to the reviewed core decision fields in the design;
- occur on at least two products;
- already carry `soft_rank`;
- preserve their original SelectionFact value and sources.

```text
candidates: 103
candidate JSONL SHA-256:
044097f23c4ff9b99178d9f78e1886b33073bf03b53d9be548046eebad652a4f
```

Single-product marketing descriptions remain free descriptors. Sparse
fragrance data, ingredients, mechanisms, and cold usage language were not
promoted.

## Manual Decisions

```text
reviewed: 103
mapped: 99
leave_free: 4
published parent concepts: 48

decision catalog SHA-256:
aec01a2ac6238558d7708b21d0337cc5b3ef367f0a9bd567b8acba899a518b34

full review SHA-256:
94c5725c3926dca9ece2d09a45030d9ca78494c610fe8c54d616df1bf1732097
```

The four `leave_free` values are:

```text
cleanser.rinse_behavior:
  柔嫩、无膜感、不粘腻、不紧绷
  reason: compound value would lose source meaning

cleanser.rinse_behavior:
  泡沫
  reason: field placement and meaning are insufficient

cleanser.texture:
  羊绒质地
  reason: product marketing metaphor

skincare.efficacy:
  强韧
  reason: ambiguous between barrier and elasticity
```

## Asset

```text
projection count: 99
concept count: 48
projection SHA-256:
b504acf214c05dd214306a9fb43148162cae673e1ee7c95251c5d2dff05af5c7

manifest logical self-hash:
4f8eac7811ce57fb75da868efba1e58f2fc3b07fb596e144051c957aca01732b

manifest file SHA-256:
aa80280189c0fd363c8f3ef5c316905c87043b800e91631a7160dbb5dc025879
```

Runtime composition pins the logical manifest hash. The loader verifies the
inventory, review, projection bytes, counts, and exact review-derived
projection set.

## Responsibility Verdict

This asset is a data-side concept projection, not a user phrase dictionary.

```text
model:
  maps open language to one of 48 reviewed field-scoped concepts or null

code:
  validates concept applicability and matches concept identity

free descriptor:
  remains ProductEvidence retrieval/answer material and cannot alter rank
```

No source SelectionFact, rank strength, safety role, attribution, or source
reference was rewritten.

