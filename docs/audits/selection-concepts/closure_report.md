# Selection Parent Concept Closure Report

Date: 2026-08-16

Status: `CLOSED`

## Inventory

The production inventory was built from structured SelectionFacts, not from
keyword scans of prose:

```text
products: 100
SelectionFacts: 2322
soft-rank SelectionFacts: 1775
non-rank SelectionFacts: 547
rank strength 1: 1312
rank strength 2: 463
```

## Manual Review

The main-agent review covered 103 candidate value projections:

```text
mapped projections: 99
left as free descriptors: 4
field-scoped parent concepts: 48
unreviewed candidates: 0
```

The review excludes product-specific technologies, ingredients, cold
marketing metaphors, medical implications, sparse fragrance notes, and
compound values that cannot be projected without losing source meaning.

This is not a user phrase dictionary. Open language is translated to one of
the 48 reviewed field-scoped concept IDs or to `null`. A `null` result remains
a free descriptor and cannot alter structured rank.

## Runtime Semantics

The ranking contract is:

```text
prefer + supports -> matched
prefer + opposes -> mismatch
avoid + opposes  -> matched
avoid + supports -> mismatch
no reviewed evidence -> unknown
```

Additional invariants:

- same concept from multiple facts scores once;
- the highest admissible evidence strength is used once;
- all supporting `source_refs` are preserved for presentation;
- evidence strength does not claim stronger product effect;
- another positive fact in the same field is not counter-evidence;
- only an explicit reviewed opposing projection becomes `mismatch`;
- merchant-positive safety claims are ignored in safety-sensitive ranking;
- GeneralKnowledge and free descriptors cannot affect rank;
- relative comparison distinguishes numeric, ordered, preference-match,
  evidence-support, and unsupported relations.

Ranking reasons and answer reasons consume the same concept and relative
outcomes, including the same `source_refs`.

## Content Locks

```text
inventory SHA-256:
a4a97a5f4d26b9db63336a4a713924427f0c91f123e3c754cee82dea637d8134

review SHA-256:
94c5725c3926dca9ece2d09a45030d9ca78494c610fe8c54d616df1bf1732097

projection SHA-256:
b504acf214c05dd214306a9fb43148162cae673e1ee7c95251c5d2dff05af5c7

manifest logical self-hash:
4f8eac7811ce57fb75da868efba1e58f2fc3b07fb596e144051c957aca01732b
```

The loader verifies inventory, review, projection bytes, counts, ordering,
source SelectionFact identity, and the review-derived projection set.

## Verification

Concept contracts, content-addressed assets, reader behavior, ranking,
relative comparison, production composition, and cross-vertical frontend
matrix are included in the final green suites:

```text
focused suites: 4734 passed
Guide full: 7619 passed
frontend handoff matrices: 45 passed
```

No vector index, long-tail phrase table, second model call, or legacy RAG
import was introduced.
