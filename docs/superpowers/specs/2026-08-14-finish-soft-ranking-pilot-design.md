# Finish Soft-Ranking Pilot Design

## Goal

Validate that one additional category fact can participate in recommendation
ranking without changing broad recall, excluding candidates with missing data,
or altering existing behavior when the new constraint is absent.

The pilot field is `finish`, using a value such as `自然裸妆`.

## Scope

This pilot covers the typed `TaskPlan -> decision -> ordered candidates` path.
It does not add natural-language extraction, change category recall, promote new
data, or onboard additional fields.

## Design

Add a generic typed facet constraint that identifies a registered category
field and a normalized requested value. The decision layer evaluates the
constraint only against `AuthorizedCategoryFact` values already present in
`DecisionProductFacts.category_fields`.

Only a known fact with the `soft_rank` capability may affect ranking. The
ordering for the pilot is:

1. Known matching value.
2. Unknown or unavailable value.
3. Known non-matching value.

All candidates remain eligible. Existing category, budget, efficacy, skin, and
exclusion behavior remains authoritative.

The retrieval layer remains category-only and must return the same candidates
in the same stable order as before decision ranking.

## Safety Rules

- `finish` never becomes a hard filter.
- Missing `finish` data never excludes a candidate.
- Facts without `soft_rank` capability cannot affect ranking.
- Merchant claims may influence soft ranking but never safety filtering.
- No facet constraint means byte-for-byte equivalent ordered product IDs,
  winner status, and comparison dimensions to the existing behavior.
- Ranking remains deterministic with `product_id` as the final stable tie
  breaker.

## Verification

TDD must prove:

1. A matching `finish` candidate moves ahead of unknown and mismatching
   candidates.
2. Unknown and mismatching candidates remain in the result.
3. A fact without `soft_rank` capability cannot influence ordering.
4. Removing the facet constraint restores the existing ordering.
5. Existing budget, skin, efficacy, exclusion, and deterministic ranking tests
   remain green.
6. Category retrieval candidate IDs are unchanged by the pilot.

## Rollout Gate

The pilot may be generalized to more fields only if all verification passes
without changing existing no-facet behavior. A failed invariant blocks rollout;
the response must fix the generic engine rather than add a field-specific
branch.
