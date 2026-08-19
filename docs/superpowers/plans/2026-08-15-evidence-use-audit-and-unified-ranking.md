# Evidence Use Audit and Unified Ranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `executing-plans` to implement this plan task-by-task. Steps use checkbox
> (`- [ ]`) syntax for tracking. The user explicitly forbids sub-agents.

**Goal:** Audit every accepted Product Evidence block, project every legitimate
selection fact into the existing hard/soft decision path without duplicate
scoring, and close recommendation, comparison, and simple follow-up backend
behavior before frontend rendering.

**Architecture:** Add an explicit, visually confirmed selection-use review to
each accepted `ProductEvidenceBlock`. Convert approved Category Facts, Merchant
Claims, and reviewed Product Evidence projections into one deterministic
`SelectionFactReader`, deduplicated by product/scope/facet/value and carrying
the maximum evidence strength. Feed those facts into the existing
`DecisionProductFacts` and `rank_soft_facets`; do not create a second
recommendation engine.

**Tech Stack:** Python 3.11, Pydantic v2 strict/frozen contracts, content-
addressed JSONL and SHA-256 manifests, pytest, existing Guide semantic
contracts, Category Fact registry, deterministic ranking, typed SSE.

**Repository:** `/Users/bytedance/Desktop/xiaoro-fresh`

**Branch:** `rebuild`

**Execution boundary:** Work in the existing dirty `rebuild` worktree, preserve
all current changes, do not use sub-agents, do not modify
`app/static/chat.html`, do not recrawl blocked images, and do not push/deploy.

---

## 0. File and Ownership Map

Create:

- `app/guide/retrieval/selection_fact_contracts.py`
  Strict per-value selection facts, source references, rank strengths, and
  deterministic deduplication keys.
- `app/guide/retrieval/selection_fact_reader.py`
  Adapter that projects Category Facts, Merchant Claims, and reviewed Product
  Evidence into one product-scoped selection-fact view.
- `tools/guide_data/audit_product_evidence_uses.py`
  Completeness and coverage verifier for the manual evidence-use audit.
- `docs/audits/evidence-use/closure_report.md`
  Final backend audit, ranking, safety, model-gate, and frontend-handoff report.

Modify:

- `app/guide/retrieval/product_evidence_assets.py`
  Add reviewed selection projections and require a completed use decision on
  accepted evidence.
- `app/guide/retrieval/product_evidence_reader.py`
  Expose accepted selection-reviewed evidence without performing ranking.
- `tools/guide_data/build_product_evidence.py`
  Carry selection review data into content-addressed evidence.
- `data/guide_product_evidence/reviews/*.jsonl`
  Record the visual, per-block selection-use audit.
- `data/guide_product_evidence/product_evidence_v1_manifest.json`
  Publish rebuilt evidence and audit locks.
- `app/guide/retrieval/merchant_claim_reader.py`
  Provide source claims to the unified selection reader; stop merging claim
  counts into rank strength.
- `app/guide/decision/contracts.py`
  Carry value-specific `selection_facts`.
- `app/guide/decision/facet_ranking.py`
  Score one user-requested facet/value slot once and use maximum source
  strength.
- `app/guide/decision/recommendation.py`
  Add weighted-match ordering without changing hard-gate or no-facet behavior.
- `app/guide/adapters/catalog/canonical_guide_catalog.py`
  Attach unified selection facts to decision products.
- `app/guide_runtime/composition.py`
  Compose and lock the reviewed Product Evidence and selection reader.
- `app/guide/understanding/semantic_contracts.py`
  Add category-aware recommendation fields needed for efficacy, suitability,
  concern, usage context, and ingredient presence.
- `app/guide/understanding/semantic_detail_contracts.py`
  Carry typed preference/safety strength.
- `app/guide/adapters/llm/intent_detail_prompt.py`
  Distinguish ordinary sensitivity/post-procedure preference from explicit
  allergy, pregnancy, and absolute safety constraints.
- `app/guide/intent/signal_merger.py`
  Preserve deterministic hard signals and route semantic preference strength.
- `app/guide/intent/task_planning.py`
  Compile ordinary selection requests to facets and serious constraints to the
  existing hard path.
- `app/guide/intent/contracts.py`
  Add a typed ingredient-presence inclusion constraint to the existing hard
  lane; do not overload soft facets.
- `app/guide/application/text_recommendation_flow.py`
  Emit backend selection evidence and preserve it through comparison/follow-up.
- `app/guide/presentation/sse_events.py`
  Add typed backend fields for matched slots, evidence strength, attribution,
  and boundaries without frontend changes.

Primary tests:

- `tests/guide/retrieval/test_product_evidence_assets.py`
- `tests/guide/tools/test_build_product_evidence.py`
- `tests/guide/data/test_product_evidence_production_assets.py`
- `tests/guide/retrieval/test_selection_fact_contracts.py`
- `tests/guide/retrieval/test_selection_fact_reader.py`
- `tests/guide/decision/test_recommendation.py`
- `tests/guide/intent/test_signal_merger.py`
- `tests/guide/intent/test_task_planning.py`
- `tests/guide/adapters/test_intent_detail_prompt.py`
- `tests/guide/application/test_text_recommendation_flow.py`
- `tests/guide/runtime/test_composition.py`
- `tests/guide/runtime/test_product_evidence_real_matrix.py`

## Task 1: Freeze Baseline and Frontend Boundary

**Files:**
- Create: `tests/guide/data/test_evidence_use_baseline.py`
- Modify: `tests/guide/runtime/test_frontend_scope.py`

- [ ] **Step 1: Write baseline assertions**

Add:

```python
def test_evidence_use_baseline_is_explicit() -> None:
    assets = _load_production_product_evidence()
    accepted = [
        item
        for item in assets.evidence
        if item.review_status == "accepted"
    ]
    assert len(assets.evidence) == 1262
    assert len(accepted) == 1079
    assert sum(
        bool({"soft_rank", "weak_soft_rank"} & item.allowed_uses)
        for item in accepted
    ) == 299
    assert sum("hard_filter" in item.allowed_uses for item in accepted) == 144
    assert sum("compare" in item.allowed_uses for item in accepted) == 534
```

Add a frontend-freeze assertion:

```python
def test_backend_ranking_goal_does_not_change_chat_renderer() -> None:
    assert sha256((REPO_ROOT / "app/static/chat.html").read_bytes()).hexdigest() \
        == EXPECTED_PRE_GOAL_CHAT_SHA256
```

Record `EXPECTED_PRE_GOAL_CHAT_SHA256` from the current dirty worktree, not
from `HEAD`.

- [ ] **Step 2: Run the focused baseline**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/data/test_evidence_use_baseline.py \
  tests/guide/runtime/test_frontend_scope.py
```

Expected: baseline counts pass; the new frontend hash freezes the current file.

- [ ] **Step 3: Record the measured baseline**

Create `docs/audits/evidence-use/baseline.json` with:

```json
{
  "evidence_total": 1262,
  "accepted": 1079,
  "soft_or_weak": 299,
  "hard_filter": 144,
  "compare": 534,
  "merchant_claims": 1136,
  "merchant_soft_claims": 778,
  "active_soft_facts": 398,
  "products_with_active_soft_fact": 100
}
```

- [ ] **Step 4: Commit the baseline gate**

```bash
git add tests/guide/data/test_evidence_use_baseline.py \
  tests/guide/runtime/test_frontend_scope.py \
  docs/audits/evidence-use/baseline.json
git commit -m "test(guide): freeze evidence use baseline"
```

## Task 2: Define Selection Review and Selection Fact Contracts

**Files:**
- Modify: `app/guide/retrieval/product_evidence_assets.py`
- Create: `app/guide/retrieval/selection_fact_contracts.py`
- Test: `tests/guide/retrieval/test_product_evidence_assets.py`
- Create: `tests/guide/retrieval/test_selection_fact_contracts.py`

- [ ] **Step 1: Write RED contract tests**

Add tests for this reviewed projection:

```python
selection_review = {
    "decision": "projected",
    "visual_confirmed": True,
    "rationale": "商家直接描述油皮适用，允许普通偏好弱软排",
    "projections": [
        {
            "field_key": "suitable_skin",
            "normalized_value": "油性",
            "capabilities": ["compare", "soft_rank"],
            "rank_strength": 1,
        }
    ],
}
```

Assert:

- accepted evidence requires `selection_review`;
- nonaccepted evidence forbids it;
- `answer_only` and `safety_gate` decisions require no soft projection;
- every permission change requires `visual_confirmed=True`;
- rank strength is exactly `1` or `2`;
- rank strength is required for `soft_rank` and forbidden otherwise;
- merchant/consumer evidence cannot use strength `2`;
- hard-filter projection requires `hard_filter` in block `allowed_uses`;
- projection field keys must exist in `category_field_registry`;
- projection IDs are content addressed and deterministic.

Define the strict runtime contract:

```python
class SelectionFact(_StrictFrozenModel):
    product_id: int
    category_profile: CategoryProfile
    subject_scope: SubjectScope
    variant_scope: str | None
    field_key: str
    normalized_value: str
    rank_strength: Literal[1, 2] | None
    safety_role: Literal[
        "ordinary",
        "merchant_positive_safety",
        "verified_warning",
    ]
    capabilities: frozenset[
        Literal["compare", "soft_rank", "hard_filter", "safety_gate"]
    ]
    source_refs: tuple[str, ...]
```

Its identity is:

```python
(
    product_id,
    subject_scope,
    variant_scope,
    field_key,
    normalized_value.casefold(),
)
```

Implement it as a property:

```python
@property
def selection_key(self) -> tuple[object, ...]:
    return (
        self.product_id,
        self.subject_scope,
        self.variant_scope,
        self.field_key,
        self.normalized_value.casefold(),
    )
```

- [ ] **Step 2: Run tests and verify RED**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/retrieval/test_product_evidence_assets.py \
  tests/guide/retrieval/test_selection_fact_contracts.py
```

Expected: imports or validation fail because selection contracts do not exist.

- [ ] **Step 3: Implement minimal strict contracts**

Add `SelectionProjection` and `EvidenceSelectionReview` to
`product_evidence_assets.py`. Add:

```python
selection_review: EvidenceSelectionReview | None = None
```

to `ProductEvidenceBlock`, then validate:

```python
if self.review_status == "accepted" and self.selection_review is None:
    raise ValueError("accepted evidence requires selection use review")
if self.review_status != "accepted" and self.selection_review is not None:
    raise ValueError("nonaccepted evidence forbids selection use review")
```

Implement `SelectionFact` and:

```python
def merge_selection_facts(
    facts: Iterable[SelectionFact],
) -> tuple[SelectionFact, ...]:
    merged: dict[tuple[object, ...], SelectionFact] = {}
    for fact in facts:
        key = fact.selection_key
        previous = merged.get(key)
        if previous is None:
            merged[key] = fact
            continue
        strengths = tuple(
            value
            for value in (previous.rank_strength, fact.rank_strength)
            if value is not None
        )
        roles = {previous.safety_role, fact.safety_role}
        safety_role = (
            "verified_warning"
            if "verified_warning" in roles
            else (
                "ordinary"
                if "ordinary" in roles
                else "merchant_positive_safety"
            )
        )
        merged[key] = previous.model_copy(
            update={
                "rank_strength": max(strengths) if strengths else None,
                "capabilities": (
                    previous.capabilities | fact.capabilities
                ),
                "safety_role": safety_role,
                "source_refs": tuple(
                    sorted(
                        {
                            *previous.source_refs,
                            *fact.source_refs,
                        }
                    )
                ),
            }
        )
    return tuple(
        merged[key]
        for key in sorted(merged, key=repr)
    )
```

The merge must union sorted source references and take maximum rank strength.
Conflicting scope/value records remain separate; it must never sum strength.
When any merged source is an ordinary/verified fact, the merged
`safety_role` is not `merchant_positive_safety`; weak merchant safety language
must not suppress a stronger exact fact.

- [ ] **Step 4: Update fixture builders and run GREEN**

Update test fixture helpers to include an explicit answer-only review:

```python
"selection_review": {
    "decision": "answer_only",
    "visual_confirmed": True,
    "rationale": "使用说明不区分候选商品",
    "projections": [],
}
```

Run the Step 2 command.

Expected: all tests pass.

- [ ] **Step 5: Commit contracts**

```bash
git add app/guide/retrieval/product_evidence_assets.py \
  app/guide/retrieval/selection_fact_contracts.py \
  tests/guide/retrieval/test_product_evidence_assets.py \
  tests/guide/retrieval/test_selection_fact_contracts.py
git commit -m "feat(guide): define reviewed selection facts"
```

## Task 3: Carry Selection Review Through the Evidence Builder

**Files:**
- Modify: `tools/guide_data/build_product_evidence.py`
- Modify: `tests/guide/tools/test_build_product_evidence.py`
- Create: `tools/guide_data/audit_product_evidence_uses.py`
- Create: `tests/guide/tools/test_audit_product_evidence_uses.py`

- [ ] **Step 1: Write RED builder tests**

Assert that:

```python
payload["selection_review"] = row["selection_review"]
```

is part of `ProductEvidenceBlock` hashing, the builder rejects accepted rows
without it, and two semantically identical runs are byte-identical across
different `PYTHONHASHSEED` values.

Add verifier expectations:

```python
result = audit_product_evidence_uses(review_paths)
assert result.accepted_reviewed == 1079
assert result.accepted_missing == 0
assert result.nonaccepted_with_review == 0
assert result.answer_only_without_rationale == 0
```

- [ ] **Step 2: Run tests and verify RED**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/tools/test_build_product_evidence.py \
  tests/guide/tools/test_audit_product_evidence_uses.py
```

Expected: builder drops the new field and verifier import fails.

- [ ] **Step 3: Implement builder and verifier**

The verifier must report, without authorizing anything:

- total accepted rows;
- reviewed versus missing;
- projected versus answer-only versus safety-gate;
- projections by profile, field, capability, and strength;
- answer-only blocks whose concrete rationale is empty;
- duplicate projection keys within one block;
- invalid hard/soft source authority.

It must not use text keywords to decide eligibility.

- [ ] **Step 4: Run tests and verify GREEN**

Run the Step 2 command.

Expected: all tests pass on fixtures.

- [ ] **Step 5: Commit tooling**

```bash
git add tools/guide_data/build_product_evidence.py \
  tools/guide_data/audit_product_evidence_uses.py \
  tests/guide/tools/test_build_product_evidence.py \
  tests/guide/tools/test_audit_product_evidence_uses.py
git commit -m "feat(data): verify evidence use reviews"
```

## Task 4: Audit Skincare Evidence

**Files:**
- Modify: `data/guide_product_evidence/reviews/skincare_batch_*.jsonl`
- Update: `data/guide_product_evidence/review_progress_v1.json`

- [ ] **Step 1: Inventory the exact audit set**

Run the verifier restricted to `category_profile=skincare`.

Expected baseline:

```text
accepted blocks = 505
selection-reviewed = 0
```

- [ ] **Step 2: Review every accepted block against its source image**

For each accepted block:

1. open `source.resolved_image_file`;
2. confirm subject and variant scope;
3. decide answer-only, projected, or safety-gate;
4. add zero or more category-applicable projections;
5. use strength `1` for merchant claims/self-report and `2` only for strong
   product facts or qualifying product-level tests;
6. record a concrete Chinese rationale;
7. do not alter exact text, qualifiers, or source bindings unless the image
   proves the existing record wrong.

Required scrutiny areas:

- efficacy and skin concern;
- ingredient presence versus ingredient-benefit marketing;
- suitable skin and ordinary sensitivity preference;
- active post-procedure safety versus ordinary preference;
- in-vitro mechanism versus product-level outcome;
- complete ingredient lists and exact variant scope.

- [ ] **Step 3: Verify skincare closure**

Expected:

```text
accepted = 505
selection-reviewed = 505
missing = 0
```

Run affected image/evidence builder tests after every 100 blocks.

- [ ] **Step 4: Commit skincare audit**

```bash
git add data/guide_product_evidence/reviews/skincare_batch_*.jsonl \
  data/guide_product_evidence/review_progress_v1.json
git commit -m "data(guide): audit skincare evidence uses"
```

## Task 5: Audit Suncare and Base Makeup Evidence

**Files:**
- Modify: `data/guide_product_evidence/reviews/suncare_batch_*.jsonl`
- Modify: `data/guide_product_evidence/reviews/base_makeup_batch_*.jsonl`
- Update: `data/guide_product_evidence/review_progress_v1.json`

- [ ] **Step 1: Audit all 161 accepted suncare blocks**

Visually verify SPF/PA, protection spectrum, water resistance, application
area, texture, finish, film speed, suitability, reapplication, and safety
language. Exact package UV facts may support hard constraints. Merchant
"sensitive skin" language is weak-soft only for ordinary preference.

- [ ] **Step 2: Close the suncare verifier**

Expected:

```text
accepted = 161
selection-reviewed = 161
missing = 0
```

- [ ] **Step 3: Audit all 168 accepted base-makeup blocks**

Visually verify finish, coverage, longevity, texture, shade/undertone,
suitable skin, SPF, ingredient presence, and exact variant boundaries.
Shade mapping supports comparison; it must not create a generic product
quality bonus.

- [ ] **Step 4: Close the base-makeup verifier**

Expected:

```text
accepted = 168
selection-reviewed = 168
missing = 0
```

- [ ] **Step 5: Commit both profiles**

```bash
git add data/guide_product_evidence/reviews/suncare_batch_*.jsonl \
  data/guide_product_evidence/reviews/base_makeup_batch_*.jsonl \
  data/guide_product_evidence/review_progress_v1.json
git commit -m "data(guide): audit sun and base makeup evidence uses"
```

## Task 6: Audit Cleanser, Color Makeup, and Fragrance Evidence

**Files:**
- Modify: `data/guide_product_evidence/reviews/cleanser_batch_*.jsonl`
- Modify: `data/guide_product_evidence/reviews/color_makeup_batch_*.jsonl`
- Modify: `data/guide_product_evidence/reviews/fragrance_batch_*.jsonl`
- Update: `data/guide_product_evidence/review_progress_v1.json`

- [ ] **Step 1: Audit all 186 accepted cleanser blocks**

Review cleansing power, rinse behavior, makeup-removal scope, texture,
surfactant/formula facts, suitable skin, double-cleanse guidance, and warnings.
Usage sequence is answer-only unless it distinguishes a requested use context.

- [ ] **Step 2: Audit all 37 accepted color-makeup blocks**

Review finish, color family, payoff, makeup effect/style, longevity,
application area, and exact shade scope. Marketing quantity cannot add weight.

- [ ] **Step 3: Audit all 22 accepted fragrance blocks**

Review concentration, note structure, fragrance description, longevity,
audience, use context, exact size/variant, and full ingredient labels.
Historical brand narrative remains answer-only.

- [ ] **Step 4: Close the full 1,079-block verifier**

Expected:

```text
accepted = 1079
selection-reviewed = 1079
missing = 0
nonaccepted_with_review = 0
```

- [ ] **Step 5: Commit remaining profiles**

```bash
git add data/guide_product_evidence/reviews/cleanser_batch_*.jsonl \
  data/guide_product_evidence/reviews/color_makeup_batch_*.jsonl \
  data/guide_product_evidence/reviews/fragrance_batch_*.jsonl \
  data/guide_product_evidence/review_progress_v1.json
git commit -m "data(guide): close evidence use audit"
```

## Task 7: Rebuild and Lock Product Evidence

**Files:**
- Modify: `data/guide_product_evidence/product_evidence_v1_manifest.json`
- Create: the `product_evidence_v1.${EVIDENCE_SHA}.jsonl` path printed by
  the production builder
- Create: the `image_audit_v1.${AUDIT_SHA}.jsonl` path printed by the
  production builder
- Modify: `app/guide_runtime/composition.py`
- Modify: `tests/guide/data/test_product_evidence_production_assets.py`
- Modify: `tests/guide/runtime/test_composition.py`

- [ ] **Step 1: Run production build**

Run:

```bash
audit_args=()
for path in data/guide_product_evidence/image_audit/*.jsonl; do
  audit_args+=(--audit "$path")
done
review_args=()
for path in data/guide_product_evidence/reviews/*.jsonl; do
  review_args+=(--review "$path")
done
.venv/bin/python -m tools.guide_data.build_product_evidence \
  --source-root data/guide_merchant_claims/source_ocr \
  --image-root data/guide_merchant_claims/source_images \
  "${audit_args[@]}" \
  "${review_args[@]}" \
  --recovery-manifest \
    data/guide_product_evidence/recovery_manifest_v1.jsonl \
  --output-root data/guide_product_evidence
```

Expected:

```text
evidence_count = 1262
accepted = 1079
image_count = 972
selection-reviewed accepted = 1079
```

- [ ] **Step 2: Write RED lock assertions**

Update tests with the newly measured evidence SHA, audit SHA, manifest SHA,
allowed-use counts, selection-decision counts, and per-strength counts.

Expected: runtime lock remains old and tests fail.

- [ ] **Step 3: Update runtime locks**

Point composition only at the new content-addressed filenames and manifest
hash. Never edit the old immutable JSONL.

- [ ] **Step 4: Run production asset tests**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/data/test_product_evidence_production_assets.py \
  tests/guide/retrieval/test_product_evidence_assets.py \
  tests/guide/runtime/test_composition.py
```

Expected: all pass.

- [ ] **Step 5: Commit rebuilt assets**

```bash
git add data/guide_product_evidence \
  app/guide_runtime/composition.py \
  tests/guide/data/test_product_evidence_production_assets.py \
  tests/guide/runtime/test_composition.py
git commit -m "data(guide): publish reviewed evidence uses"
```

## Task 8: Build Unified, Duplicate-Free Selection Facts

**Files:**
- Create: `app/guide/retrieval/selection_fact_reader.py`
- Modify: `app/guide/retrieval/merchant_claim_reader.py`
- Modify: `app/guide/retrieval/product_evidence_reader.py`
- Create: `tests/guide/retrieval/test_selection_fact_reader.py`
- Modify: `app/guide_runtime/composition.py`

- [ ] **Step 1: Write RED reader tests**

Create fixtures where one merchant claim and one Product Evidence block both
project:

```text
product=78
field=efficacy
value=hydrating
```

Assert:

```python
facts = reader.read(product_id=78, profile=CategoryProfile.SKINCARE)
hydrating = next(item for item in facts if item.normalized_value == "hydrating")
assert hydrating.rank_strength == 2
assert len(hydrating.source_refs) == 2
assert len(facts) == 1
```

Also cover:

- five repeated merchant claims remain one selection fact;
- strong plus weak uses maximum `2`, never sum `3`;
- different values remain separate;
- variant scopes remain separate;
- wrong-profile projections are rejected;
- positive merchant safety facts retain an explicit
  `merchant_positive_safety` role for the decision layer.

- [ ] **Step 2: Run tests and verify RED**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/retrieval/test_selection_fact_reader.py
```

Expected: import failure.

- [ ] **Step 3: Implement the reader**

Project:

1. approved Category Facts as strength `2`;
2. ordinary Merchant Claims as strength `1`;
3. reviewed Product Evidence projections at their audited strength.

Merge only through `merge_selection_facts`. Do not count source rows.

Expose:

```python
def read(
    self,
    *,
    product_id: int,
    profile: CategoryProfile,
) -> tuple[SelectionFact, ...]:
    base = self._base.read(product_id=product_id, profile=profile)
    claims = self._claims.read(product_id=product_id)
    evidence = self._evidence.read(product_id=product_id)
    return merge_selection_facts(
        (
            *self._project_base(base, product_id=product_id),
            *self._project_claims(claims, profile=profile),
            *self._project_evidence(evidence, profile=profile),
        )
    )
```

The reader is static and must not inspect the user query. It labels positive
merchant safety facts with
`safety_role="merchant_positive_safety"`. The decision layer suppresses those
facts when `TaskPlan.safety_sensitive=True`, while retaining verified warnings
and strong exact facts.

Implement these private projection boundaries with explicit return types:

```python
def _project_base(
    self,
    facts: tuple[AuthorizedCategoryFact, ...],
    *,
    product_id: int,
) -> tuple[SelectionFact, ...]:
    projected: list[SelectionFact] = []
    for fact in facts:
        if fact.resolved_state != "known":
            continue
        values = (
            (fact.value,)
            if isinstance(fact.value, str)
            else fact.value
        )
        if not isinstance(values, tuple):
            continue
        capabilities = frozenset(
            capability
            for capability in fact.capabilities
            if capability in {"compare", "soft_rank", "hard_filter"}
        )
        if not capabilities:
            continue
        for value in values:
            projected.append(
                SelectionFact(
                    product_id=product_id,
                    category_profile=fact.category_profile,
                    subject_scope="exact_product",
                    variant_scope=None,
                    field_key=fact.field_key,
                    normalized_value=value,
                    rank_strength=(
                        2 if "soft_rank" in capabilities else None
                    ),
                    safety_role="ordinary",
                    capabilities=capabilities,
                    source_refs=fact.source_refs,
                )
            )
    return tuple(projected)

def _project_claims(
    self,
    claims: tuple[MerchantClaim, ...],
    *,
    profile: CategoryProfile,
) -> tuple[SelectionFact, ...]:
    projected: list[SelectionFact] = []
    for claim in claims:
        if claim.category_profile is not profile:
            continue
        capabilities = frozenset(
            capability
            for capability in claim.capabilities
            if capability in {"compare", "soft_rank"}
        )
        if not capabilities:
            continue
        projected.append(
            SelectionFact(
                product_id=claim.product_id,
                category_profile=profile,
                subject_scope="exact_product",
                variant_scope=None,
                field_key=claim.field_key,
                normalized_value=claim.normalized_value,
                rank_strength=(
                    1 if "soft_rank" in capabilities else None
                ),
                safety_role=(
                    "merchant_positive_safety"
                    if claim.claim_scope == "safety_transcript"
                    else "ordinary"
                ),
                capabilities=capabilities,
                source_refs=(claim.source_locator,),
            )
        )
    return tuple(projected)

def _project_evidence(
    self,
    blocks: tuple[ProductEvidenceBlock, ...],
    *,
    profile: CategoryProfile,
) -> tuple[SelectionFact, ...]:
    projected: list[SelectionFact] = []
    for block in blocks:
        review = block.selection_review
        if block.review_status != "accepted" or review is None:
            continue
        for item in review.projections:
            projected.append(
                SelectionFact(
                    product_id=block.product_id,
                    category_profile=profile,
                    subject_scope=block.subject_scope,
                    variant_scope=block.variant_scope,
                    field_key=item.field_key,
                    normalized_value=item.normalized_value,
                    rank_strength=item.rank_strength,
                    safety_role=item.safety_role,
                    capabilities=item.capabilities,
                    source_refs=(block.evidence_id,),
                )
            )
    return tuple(projected)
```

Each helper performs projection only. Only `merge_selection_facts` performs
deduplication.

- [ ] **Step 4: Compose once at runtime**

Build the reader once in `composition.py` from existing locked readers. Do not
reload JSONL per request.

- [ ] **Step 5: Run tests and verify GREEN**

Run the Step 2 command plus `tests/guide/runtime/test_composition.py`.

- [ ] **Step 6: Commit unified projection**

```bash
git add app/guide/retrieval/selection_fact_reader.py \
  app/guide/retrieval/selection_fact_contracts.py \
  app/guide/retrieval/merchant_claim_reader.py \
  app/guide/retrieval/product_evidence_reader.py \
  app/guide_runtime/composition.py \
  tests/guide/retrieval/test_selection_fact_reader.py \
  tests/guide/runtime/test_composition.py
git commit -m "feat(guide): unify selection evidence"
```

## Task 9: Add One-Slot Weighted Soft Ranking

**Files:**
- Modify: `app/guide/decision/contracts.py`
- Modify: `app/guide/decision/facet_ranking.py`
- Modify: `app/guide/decision/recommendation.py`
- Modify: `app/guide/adapters/catalog/canonical_guide_catalog.py`
- Modify: `tests/guide/decision/test_recommendation.py`

- [ ] **Step 1: Write RED ranking tests**

Add:

```python
def test_repeated_claims_fill_one_requested_slot_once() -> None:
    product = _product(
        selection_facts=(
            _selection_fact(
                field_key="suitable_skin",
                normalized_value="油性",
                rank_strength=1,
                source_refs=("claim-a",),
            ),
            _selection_fact(
                field_key="suitable_skin",
                normalized_value="油性",
                rank_strength=1,
                source_refs=("claim-b",),
            ),
        )
    )
    constraints = (
        FacetConstraint(field_key="suitable_skin", value="油性"),
    )
    result = rank_soft_facets(product, constraints)
    assert result.weighted_match_score == 1
    assert result.matched_slot_count == 1
```

Cover:

- five weak sources still score `1`;
- weak plus strong source scores `2`;
- hydrating and soothing requested together can score independently;
- unrequested efficacy claims do not score;
- exact variant facts do not leak;
- positive merchant safety facts score for an ordinary preference but are
  ignored when `safety_sensitive=True`;
- match outranks unknown; unknown outranks mismatch;
- no-facet order is byte-identical to current order.

- [ ] **Step 2: Run tests and verify RED**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/decision/test_recommendation.py
```

Expected: missing selection facts and weighted result fields.

- [ ] **Step 3: Carry selection facts**

Add:

```python
selection_facts: tuple[SelectionFact, ...] = ()
```

to `DecisionProductFacts`, validate sorted unique selection identities, and
populate it in `CanonicalGuideCatalog`.

- [ ] **Step 4: Implement slot scoring**

Return:

```python
@dataclass(frozen=True, slots=True)
class SoftFacetRanking:
    mismatch_count: int
    unknown_count: int
    matched_slot_count: int
    weighted_match_score: int
    matched_source_refs: tuple[str, ...]
```

For each unique `(field_key, canonical requested value)` constraint:

- select facts with the same field and applicable scope;
- match normalized targets;
- use maximum `rank_strength`;
- add one slot only;
- never sum sources.

Sort facet candidates by:

```text
skin_rank ascending
facet_mismatch_count ascending
weighted_match_score descending
facet_unknown_count ascending
price ascending
```

Add a `safety_sensitive: bool = False` argument to
`decide_recommendation` and `rank_soft_facets`. When true, ignore
`SelectionFact` rows whose
`safety_role == "merchant_positive_safety"`. Do not hide this branch in a
reader or prompt.

- [ ] **Step 5: Run GREEN and regression tests**

Run the Step 2 command and existing deterministic-ranking tests.

- [ ] **Step 6: Commit ranking**

```bash
git add app/guide/decision/contracts.py \
  app/guide/decision/facet_ranking.py \
  app/guide/decision/recommendation.py \
  app/guide/adapters/catalog/canonical_guide_catalog.py \
  tests/guide/decision/test_recommendation.py
git commit -m "feat(guide): rank one evidence slot once"
```

## Task 10: Close Preference Versus Serious Safety Translation

**Files:**
- Modify: `app/guide/understanding/semantic_contracts.py`
- Modify: `app/guide/understanding/semantic_detail_contracts.py`
- Modify: `app/guide/adapters/llm/intent_detail_prompt.py`
- Modify: `app/guide/intent/contracts.py`
- Modify: `app/guide/intent/signal_merger.py`
- Modify: `app/guide/intent/task_planning.py`
- Modify: `app/guide/decision/recommendation.py`
- Modify: `tests/guide/adapters/test_intent_detail_prompt.py`
- Modify: `tests/guide/intent/test_signal_merger.py`
- Modify: `tests/guide/intent/test_task_planning.py`

- [ ] **Step 1: Write paired RED cases**

Freeze:

```text
我是敏感肌，想找温和一点的
  -> suitable_skin preference facet
  -> safety_sensitive false

刚做完医美，想找温和一点的
  -> usage_context preference facet
  -> safety_sensitive false unless active damage/absolute safety is stated

我酒精过敏，绝对不能含酒精
  -> ingredient exclusion hard constraint
  -> safety_sensitive true

孕期必须确认能用
  -> safety-sensitive hard gate

无法判断强度
  -> strict side, never silent soft rank
```

Also assert deterministic exact hard signals cannot be overwritten by a model
`preference` proposal.

Freeze ingredient inclusion:

```text
最好含烟酰胺
  -> FacetConstraint(field_key="ingredients_present", value="烟酰胺")

必须含烟酰胺
  -> InclusionConstraint(field_key="ingredients_present", value="烟酰胺")
```

The model nominates the bound ingredient value. Deterministic code confirms
the absolute requirement from the current-message span; the model cannot turn
a soft phrase into a hard requirement by itself.

- [ ] **Step 2: Run tests and verify RED**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/adapters/test_intent_detail_prompt.py \
  tests/guide/intent/test_signal_merger.py \
  tests/guide/intent/test_task_planning.py
```

- [ ] **Step 3: Expand typed preference fields**

Add only category-registry-backed fields needed by the approved scope:

```python
EFFICACY = "efficacy"
SUITABLE_SKIN = "suitable_skin"
SKIN_CONCERN = "skin_concern"
USAGE_CONTEXT = "usage_context"
INGREDIENT_PRESENCE = "ingredients_present"
```

Unknown fields remain dropped; do not introduce free-form field names.

Add the hard-lane contract:

```python
class InclusionConstraint(_StrictContract):
    kind: Literal["include"] = "include"
    field_key: Literal["ingredients_present"] = "ingredients_present"
    value: str = Field(min_length=1, max_length=128)
```

Include it in `TaskConstraint`.

- [ ] **Step 4: Tighten prompt and merger**

State explicitly:

- bare sensitivity identity is preference;
- ordinary post-procedure preference is preference;
- allergy, intolerance, pregnancy, active adverse reaction, absolute
  must-not, and explicit active-damage safety are safety;
- unknown severity is strict;
- `safety_sensitive` is not a concern or product fact.

Code must preserve exact hard constraints over semantic proposals.

- [ ] **Step 5: Compile into existing lanes**

- ordinary selection preference -> `FacetConstraint`;
- explicit absolute ingredient presence -> `InclusionConstraint`;
- serious ingredient exclusion -> `ExclusionConstraint`;
- unknown safety strength -> typed fail-closed issue;
- no new intent pipeline.

In `decide_recommendation`, an inclusion constraint passes only when a
matching `SelectionFact` has `hard_filter` capability. Missing matching strong
evidence produces `excluded_evidence_unknown`; merchant claims cannot satisfy
the hard inclusion.

- [ ] **Step 6: Run GREEN and full intent regressions**

Run the Step 2 command plus all `tests/guide/understanding` tests.

- [ ] **Step 7: Commit translation**

```bash
git add app/guide/understanding/semantic_contracts.py \
  app/guide/understanding/semantic_detail_contracts.py \
  app/guide/adapters/llm/intent_detail_prompt.py \
  app/guide/intent/contracts.py \
  app/guide/intent/signal_merger.py \
  app/guide/intent/task_planning.py \
  app/guide/decision/recommendation.py \
  tests/guide/adapters/test_intent_detail_prompt.py \
  tests/guide/intent/test_signal_merger.py \
  tests/guide/intent/test_task_planning.py
git commit -m "feat(guide): split preference from safety"
```

## Task 11: Wire Recommendation, Comparison, and Follow-Up Backend

**Files:**
- Modify: `app/guide/application/text_recommendation_flow.py`
- Modify: `app/guide/presentation/sse_events.py`
- Modify: `tests/guide/application/test_text_recommendation_flow.py`
- Modify: `tests/guide/runtime/test_frontend_scope.py`

- [ ] **Step 1: Write recommendation RED**

Use three products with strong match, weak match, unknown, and repeated claim
sources. Assert:

```text
strong match > weak match > unknown > mismatch
candidate recall unchanged
one repeated fact contributes once
merchant reason is attributed
```

- [ ] **Step 2: Write comparison RED**

Compare two explicit products on requested facets. Assert the backend returns
one row per requested slot, source IDs, maximum strength, unknown boundaries,
and no claim-count winner bonus.

- [ ] **Step 3: Write follow-up RED**

Turn 1 recommends with sensitivity/texture preferences. Turn 2 asks:

```text
第二个怎么样
```

Assert the candidate ID, compiled preferences, selection source IDs, and
strength remain stable without reclassifying the pronoun turn.

- [ ] **Step 4: Extend typed backend payload**

Add strict payload fields:

```python
class MatchedSelectionSlot(_Strict):
    product_id: int
    field_key: str
    requested_value: str
    matched_value: str | None
    rank_strength: Literal[1, 2] | None
    source_refs: list[str]
    attribution: Literal["verified_fact", "merchant_claim", "consumer_report"]
```

Expose the payload through backend typed events only. Do not edit
`app/static/chat.html`.

Pass `task.safety_sensitive` explicitly from `text_recommendation_flow.py`
into `decide_recommendation`; no global request state is allowed.

- [ ] **Step 5: Run application tests**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/runtime/test_frontend_scope.py
```

Expected: all pass and frontend hash remains unchanged.

- [ ] **Step 6: Commit backend flow**

```bash
git add app/guide/application/text_recommendation_flow.py \
  app/guide/presentation/sse_events.py \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/runtime/test_frontend_scope.py
git commit -m "feat(guide): expose grounded ranking slots"
```

## Task 12: Full Backend Verification and Closure

**Files:**
- Modify: `tests/guide/runtime/test_product_evidence_real_matrix.py`
- Modify: `docs/audits/product-evidence/real_question_matrix.jsonl`
- Create: `docs/audits/evidence-use/closure_report.md`

- [ ] **Step 1: Extend real-question matrix**

Add cases for:

- ordinary sensitive-skin preference;
- ordinary post-procedure preference;
- alcohol allergy;
- pregnancy;
- ingredient inclusion and exclusion;
- duplicate merchant/image claim;
- multi-facet recommendation;
- direct comparison;
- current-item and ordinal follow-up;
- unknown evidence.

Freeze expected product IDs, selected slot keys, allowed source strength, and
safety outcome. Do not freeze model prose.

- [ ] **Step 2: Run focused suite**

```bash
.venv/bin/python -m pytest -q \
  tests/guide/retrieval/test_product_evidence_assets.py \
  tests/guide/retrieval/test_selection_fact_contracts.py \
  tests/guide/retrieval/test_selection_fact_reader.py \
  tests/guide/decision/test_recommendation.py \
  tests/guide/intent/test_signal_merger.py \
  tests/guide/intent/test_task_planning.py \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/runtime/test_product_evidence_real_matrix.py
```

- [ ] **Step 3: Run Runtime and Boundary suites**

```bash
.venv/bin/python -m pytest -q tests/guide/runtime
.venv/bin/python -m pytest -q \
  tests/guide/test_architecture_boundaries.py \
  tests/guide/runtime/test_import_boundary.py
```

- [ ] **Step 4: Run full Guide, compile, and diff checks**

```bash
.venv/bin/python -m pytest -q tests/guide
.venv/bin/python -m compileall -q app tools
git diff --check
```

- [ ] **Step 5: Run repeated official real-model gates**

Run the official two-stage broad gate three independent times:

```bash
.venv/bin/python -m tools.guide_gates.run_official_deepseek_smoke \
  --output-dir /private/tmp/xiaoro-evidence-use-official-run-1
.venv/bin/python -m tools.guide_gates.run_official_deepseek_smoke \
  --output-dir /private/tmp/xiaoro-evidence-use-official-run-2
.venv/bin/python -m tools.guide_gates.run_official_deepseek_smoke \
  --output-dir /private/tmp/xiaoro-evidence-use-official-run-3
```

The runner uses the frozen 128-case input and 32-case smoke manifest from
`tests/fixtures/guide/intent`. Record route accuracy, detail accuracy, invalid
outputs, unsafe task mismatches, selected lane, and exit code for each run.

If the broad gate remains red:

```text
selected_lane = null
production status = NO-GO
```

Do not weaken fixture expectations to manufacture a green result.

- [ ] **Step 6: Write closure report**

Include:

- 1,079-block audit closure;
- capability counts before/after by profile and management label;
- answer-only selection-candidate exceptions with rationale;
- unique selection key count and cross-asset duplicate count;
- active facet/product coverage;
- recommendation/comparison/follow-up outcomes;
- frontend payload contract and exact stop boundary;
- all test commands and results;
- real-model gate result;
- remaining risks and GO/NO-GO.

- [ ] **Step 7: Final scope check**

Assert:

```bash
git diff --name-only 4a60283..HEAD -- app/static/chat.html
```

Expected: no output.

Do not push or deploy.
