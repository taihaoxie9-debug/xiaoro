# Finish Soft-Ranking Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that one authorized `finish` fact can change candidate order without changing recall or excluding candidates with missing or mismatching values.

**Architecture:** Add a generic typed facet constraint and a generic soft-facet evaluator. The recommendation decision inserts the evaluator's deterministic rank after existing skin rank and before price only when facet constraints are present; the no-facet code path retains the existing sort key exactly.

**Tech Stack:** Python 3.11, Pydantic v2, pytest, existing deterministic ranking and category-fact contracts.

---

### Task 1: Typed Facet Constraint

**Files:**
- Modify: `app/guide/intent/contracts.py`
- Test: `tests/guide/decision/test_recommendation.py`

- [ ] **Step 1: Write the failing contract usage test**

Import and construct:

```python
FacetConstraint(field_key="finish", value="自然裸妆")
```

Use it in the recommendation test helper so the strict `TaskConstraint`
union must accept the new discriminator.

- [ ] **Step 2: Run the focused test to verify RED**

Run:

```bash
.venv/bin/python -m pytest \
  tests/guide/decision/test_recommendation.py::test_finish_soft_rank_orders_match_unknown_then_mismatch \
  -q
```

Expected: FAIL because `FacetConstraint` is not defined.

- [ ] **Step 3: Add the minimal strict contract**

```python
class FacetConstraint(_StrictContract):
    kind: Literal["facet"] = "facet"
    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    value: str = Field(min_length=1, max_length=128)
```

Add it to `TaskConstraint`. Do not add natural-language extraction.

### Task 2: Generic Soft-Facet Evaluator

**Files:**
- Create: `app/guide/decision/facet_ranking.py`
- Test: `tests/guide/decision/test_recommendation.py`

- [ ] **Step 1: Add three RED behaviors**

Create color-makeup decision facts for:

```python
matched = ("自然裸妆",)  # soft_rank allowed
unknown = None
mismatch = ("哑光",)    # soft_rank allowed
```

Assert:

```python
result.ordered_product_ids == [matched_id, unknown_id, mismatch_id]
assert all(item.disposition == "eligible" for item in result.evaluations)
```

Add a fact with no `soft_rank` capability and assert its matching value does
not move it ahead of a cheaper unknown candidate.

- [ ] **Step 2: Run tests and verify RED**

Expected: old price-only order or missing evaluator.

- [ ] **Step 3: Implement the generic evaluator**

Expose:

```python
@dataclass(frozen=True, slots=True)
class SoftFacetRanking:
    mismatch_count: int
    unknown_count: int

def rank_soft_facets(
    product: DecisionProductFacts,
    constraints: tuple[FacetConstraint, ...],
) -> SoftFacetRanking:
    ...
```

Rules:

- Registered and profile-applicable fields only.
- Known facts require `soft_rank` capability to affect rank.
- Exact NFKC/casefold-normalized match ranks first.
- Missing, non-known, or unauthorized facts rank unknown.
- Known authorized non-match ranks last.
- Duplicate facet field keys fail closed.
- No field-specific `finish` branch is permitted.

### Task 3: Recommendation Integration

**Files:**
- Modify: `app/guide/decision/recommendation.py`
- Test: `tests/guide/decision/test_recommendation.py`
- Existing test: `tests/guide/retrieval/test_canonical_retrieval.py`

- [ ] **Step 1: Insert soft rank only for facet requests**

With facets, use:

```python
(
    row["skin_rank"],
    row["facet_mismatch_count"],
    row["facet_unknown_count"],
    row["price"],
)
```

Without facets, retain the existing exact key:

```python
(row["skin_rank"], row["price"])
```

- [ ] **Step 2: Record auditable dimensions**

Add `facet:finish` to `comparison_dimensions` and
`facet=finish:自然裸妆` to evidence references only when the constraint exists.

- [ ] **Step 3: Verify GREEN and invariants**

Run:

```bash
.venv/bin/python -m pytest \
  tests/guide/decision/test_recommendation.py \
  tests/guide/retrieval/test_canonical_retrieval.py -q
```

Expected: all pass.

Then run:

```bash
.venv/bin/python -m pytest tests/guide/decision tests/guide/retrieval -q
```

Expected: all pass with unchanged retrieval candidate IDs.

### Task 4: Final Verification

**Files:** No additional production files.

- [ ] **Step 1: Run intent/runtime regression**

```bash
.venv/bin/python -m pytest tests/guide/intent tests/guide/runtime -q
```

- [ ] **Step 2: Run static checks**

```bash
.venv/bin/python -m compileall -q app/guide
.venv/bin/python -m app.guide.check_boundaries
git diff --check
```

- [ ] **Step 3: Report rollout decision**

Roll out more fields only if:

- match/unknown/mismatch ordering passes;
- all candidates remain eligible;
- no-facet ordering remains unchanged;
- no-capability facts cannot influence order;
- retrieval candidate IDs remain unchanged;
- focused regressions and boundaries pass.
