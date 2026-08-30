# Semantic Patch Audit v1

## Scope

- Repository: `/Users/bytedance/Desktop/xiaoro-fresh`
- Branch: `rebuild`
- Qualification plan:
  `docs/superpowers/plans/2026-08-18-continuous-conversation-final-acceptance.md`
- Rule: a natural-language wording is not a durable implementation key.

## Required Semantic Shape

```text
user wording -> model parent concept + source-grounded target
             -> Canonical concept/data mapping
             -> code validates state and evidence
             -> processor and presentation
```

The product-facing matcher consumes finite Canonical concepts and fields. It
does not consume the particular Chinese words that caused the user request.

Example:

```text
user: "保湿" / "补水" / "想润一点"
model parent: hydration
data descendants: water_retention / hydration / moisturising evidence

user: "不要酒精" / "避开乙醇" / "排除酒精"
model parent: ingredient_exclusion
Canonical target: alcohol
data fields: ingredients_present / verified_absences
```

The model can request a semantic change to a parent concept. Code alone
decides whether that request is a legal add, retain, replace, or remove
against the saved typed state.

## Frozen Failure Evidence

Fixed capture `backend-fixed-self-only-20x5-resumed-real-v42.json`,
`shop-exclusion-withdrawal-t1`, proves the current boundary defect:

```text
message: 给我挑修护精华，敏感皮，先排除酒精
model atom: field_key=ingredient, polarity=avoid, raw_text=酒精
compiled result: free descriptor only
missing result: ExclusionConstraint(酒精)
```

The model recognized the requested ingredient target. The new TurnMeaning
compiler had no closed `ingredient_exclusion` parent bridge, so the target
was treated as an open descriptor. Adding a regex for "排除" would only hide
that missing bridge.

## Canonical Descendant Gap

The audit also found that the required data-side descendant mapping is not
yet available at runtime:

```text
user target: 酒精
product fact: 乙醇
current evaluator: raw substring comparison
result: 酒精 does not match 乙醇
```

`tests/guide/adapters/catalog/test_verified_absence_audit.py` contains a
test-only substance table that labels `酒精` as `alcohol`, but production
selection code does not consume that table. The runtime must instead use one
Canonical ingredient-entity registry:

```text
ingredient_exclusion(alcohol)
  -> alcohol entity aliases: 酒精 / 乙醇 / alcohol
  -> ingredients_present and verified_absences normalized to alcohol
```

This is a data ontology requirement, not a language regex. Until the runtime
registry exists, an exclusion request may only fail closed; it must never
claim that a product satisfies a substance exclusion from an unmatched
surface spelling.

## Fixed Fixture Data Finding

The current Canonical asset has zero products with:

```text
verified_absences.resolved_state = known
```

The existing verified-absence audit is an explicit `CONFIRMED_NO_GO`: no
supported serum or sunscreen has an approved absence fact that may make an
ingredient-exclusion request succeed. Therefore the current fixed trajectory
`shop-exclusion-withdrawal` is not a valid product expectation:

```text
t1: 修护精华 + 敏感皮 + 排除酒精
current expected cards: [38, 91]
correct Canonical result: zero cards
```

This is a fixture/data-contract defect, not a model or ranking defect. The
trajectory must be rebuilt only after the parent-concept withdrawal path is
available:

```text
t1: hard ingredient exclusion -> zero-card fail-closed result
t2: user explicitly withdraws the parent constraint -> normal recommendation
t3-t5: follow-up and comparison against the newly displayed batch
```

Do not fabricate a `verified_absences` fact, relax fail-closed filtering, or
keep the old follow-up expectations merely to preserve the current fixture.

## Classification

### Remove Immediately

| Location | Why | Required action |
| --- | --- | --- |
| `app/guide/understanding/exact_parsing.py:_EXPLICIT_FILTER_EXCLUSION` | Matches the literal verbs `排除/避开/过滤掉` to repair one observed wording. | Remove with its direct phrase-only tests. |
| `tests/guide/understanding/test_text_understanding.py:test_explicit_filter_exclusion_is_captured_exactly` | Locks the wrong exact-language ownership. | Replace with a TurnMeaning parent-concept test. |
| `tests/guide/intent/test_task_planning.py:test_explicit_filter_exclusion_compiles_bare_value` | Exercises the same wrong exact-language ownership. | Replace with a semantic compiler projection test. |

### Migrate To A Parent-Concept Bridge

| Location | Current behavior | Required destination |
| --- | --- | --- |
| `TurnMeaning.preference_candidates` -> `compile_turn_meaning()` | Allows arbitrary `field_key`; `ingredient + avoid` becomes a free descriptor. | Introduce a closed `ingredient_exclusion` parent projection that produces `ExclusionDraft` only after source grounding and Canonical target normalization. |
| `app/guide/adapters/llm/turn_meaning_prompt.py` | Lists generic preference fields but does not define the ingredient-exclusion parent contract. | Require the model to emit the finite parent for a hard ingredient absence request; require the target to be a current-message substring; forbid product facts and IDs. |
| `tests/guide/adapters/catalog/test_verified_absence_audit.py:SUBSTANCE_SLUGS` and `app/guide/decision/recommendation.py:_exclusion_disposition()` | The canonical entity table is test-only while runtime compares raw strings. | Promote a reviewed ingredient-entity registry to production and normalize both requested targets and allowed product fact values before evidence evaluation. |
| `app/guide/understanding/exact_parsing.py:_HARD_ABSENCE_EXCLUSION`, `_BARE_ABSENCE_EXCLUSION`, `_EXPLICIT_ALLERGY_EXCLUSION` | Infers `ingredient_exclusion` from wording. | Keep only temporary legacy fallback behavior until provider-backed parent projection is green; remove it from the provider-backed authority path. Safety escalation remains code-owned after source-grounded model safety atoms. |
| `app/guide/understanding/exact_parsing.py:_EXCLUSION_*`, `_INCLUSION_WITHDRAWAL` | Enumerates many cancellation phrasings. | Model translates the requested parent and target; `reduce_constraint_state()` validates the resulting typed transition. |
| `app/guide/understanding/exact_parsing.py:_EFFICACY_*`, `_SKIN_REVISION_CONFIRMATION` and related revision parsers | Infers semantic replacement or withdrawal from fixed wording. | Use finite efficacy/skin parent concepts plus a source-grounded revision intent; retain state cleanup such as `_drop_efficacy_concept()` as code-owned execution. |
| `app/guide/understanding/colloquial_budget.py` cue-specific approximate and bound patterns | Infers words such as `大概`, `左右`, and `上限`. | Model supplies a finite budget relation plus source span; code converts the nominated numeric token and validates arithmetic. Keep numeral conversion, not wording interpretation. |
| `app/guide/application/pending_turn.py` affirmative and rejection phrase patterns | Interprets open-language confirmation or rejection locally. | Add a finite pending-response semantic atom or reuse a source-grounded clarification response field; code resumes, corrects, or retains the pending turn. |

### Keep As Deterministic Code

| Location | Reason |
| --- | --- |
| `app/guide/intent/constraint_transitions.py` | Typed `add/retain/replace/remove`, previous-state comparison, and efficacy-concept cleanup are state execution, not language interpretation. |
| `app/guide/application/text_recommendation_flow.py` pending-turn persistence and zero-result snapshot commit | SSE/state contract repairs; they do not decide what user wording means. |
| `app/guide/feedback/contracts.py:PendingBudgetRange` | A typed one-sided-bound data contract. |
| `app/guide/intent/unified_turn_router.py` released current-batch handling | Prevents stale product bindings when a new task starts. |
| `app/guide/retrieval/product_name_resolver.py` controlled aliases and brand-qualified identity checks | Canonical identity mapping, not unbounded intent interpretation. |
| Source grounding, numeric conversion, amount arithmetic, ordinal resolution, and product fact evaluation | Deterministic validation over a model-nominated atom. |

## Current Diff Review

| Changed area | Classification | Audit result |
| --- | --- | --- |
| `app/guide/application/text_recommendation_flow.py` pending-turn preservation, revision mode, and zero-result commit | keep | Public event and version-commit correctness; no phrase decides a business concept. |
| `app/guide/feedback/contracts.py:PendingBudgetRange` | keep | Supports one-sided typed bounds after a bound has been semantically identified. |
| `app/guide/intent/unified_turn_router.py` new-task batch release | keep | Stops stale Canonical product bindings; does not classify language. |
| `app/guide/retrieval/product_name_resolver.py` brand-qualified controlled alias | keep | Uses reviewed Canonical aliases plus product brand identity; it is not an arbitrary text synonym rule. |
| `app/guide/intent/constraint_transitions.py:_drop_efficacy_concept` | keep | Cleans typed state after a valid parent transition. |
| `app/guide/intent/transition_planning.py:parse_exact_efficacy_withdrawals` use | migrate_to_parent_concept | The state cleanup is valid, but the withdrawal trigger currently comes from wording rules. |
| `app/guide/understanding/exact_parsing.py` newly added efficacy revision and withdrawal patterns | migrate_to_parent_concept | Semantic action recognition belongs to the model parent/change contract. |
| `app/guide/understanding/exact_parsing.py` pre-existing exclusion, inclusion, skin revision, and withdrawal patterns | migrate_to_parent_concept | These are the same architectural smell at larger scope; retain only a non-authoritative legacy fallback until each parent path is migrated. |
| `app/guide/understanding/colloquial_budget.py` new `大概/左右/上限` phrase branches | migrate_to_parent_concept | Keep Chinese-number conversion, but the model should nominate relation and source span instead of code inferring the wording. |
| `app/guide/application/pending_turn.py` affirmative/rejection regex path | migrate_to_parent_concept | Pending replies need a finite semantic response/change atom; code should only apply it to the stored pending state. |
| `app/guide/understanding/exact_parsing.py:_EXPLICIT_FILTER_EXCLUSION` | remove | Confirmed wording-level repair for the observed fixed sentence; removed in this audit. |
| `app/guide/retrieval/ingredient_entities.py` | keep | Canonical data entity registry shared by semantic projection and decision evidence matching. |
| `shop-exclusion-withdrawal` fixed fixture | rebuild_from_data | Its nonempty initial result contradicts the verified-absence NO-GO evidence; do not retain it as a passing regression. |

## Parent-Concept Audit Requirements

Before a semantic patch can be accepted, the change must answer all of these:

1. What finite parent concept is being added or consumed?
2. What source-grounded target does the model provide?
3. Which Canonical target normalization resolves that target?
4. Which product data field or descendant concept is queried?
5. Which code-owned state transition is legal?
6. What happens when product evidence is present, verified absent, conflicting,
   or unknown?
7. Does the test vary user wording while keeping the expected parent concept
   constant?

Any proposal whose answer is "add a phrase to a regex" is rejected unless it
only parses a numeric token or validates a protocol identity.

## Next Repair Sequence

1. Remove the immediate phrase patch listed above.
2. Add RED tests for distinct wordings that arrive as the same
   `ingredient_exclusion(alcohol)` parent concept.
3. Repair the TurnMeaning prompt, parent-concept contract, source admission,
   and compiler projection.
4. Reuse the existing typed state reducer and evidence evaluator.
5. Replay the frozen capture at zero API.
6. Repeat this classification for efficacy, skin, budget, pending reply, and
   reference transitions before any new phrase rule is introduced.
