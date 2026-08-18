# Category-Aware Guide Data Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add six strict category profiles, reproducible category/review data tooling, and twelve honest pilot products without modifying Canonical v1 or auto-approving extracted facts.

**Architecture:** Canonical v1 remains the authority for product identity, brand, raw category, and price. A new Guide-owned category profile registry defines field applicability and capability, while a content-addressed category fact sidecar carries only independently approved category-specific facts. Offline tools generate deterministic candidates and review queues; separate promotion commands atomically build production assets from explicit approval decisions.

**Tech Stack:** Python 3.11, Pydantic v2, JSONL/JSON content-addressed assets, FastAPI/Starlette integration, pytest, vanilla JavaScript browser gates.

---

## 1. Execution Rules

- Work from `/Users/bytedance/Desktop/xiaoro-fresh`.
- Start from clean `rebuild@a29d727`.
- Do not modify `data/canonical/**`, `app/services/**`, `app/database/**`, or
  `app/guide/decision/deterministic_ranking.py`.
- Do not import legacy modules into `app/guide` or `app/guide_runtime`.
- Automated extraction creates candidates only. It never creates an approved
  decision.
- One Integration Writer owns shared runtime, API, SSE, frontend, tasks,
  checklist, progress, and ledgers.
- Do not push, deploy, or switch traffic.

## 2. File Ownership

| Workstream | Owned files |
| --- | --- |
| Category contracts | `app/guide/retrieval/category_profiles.py`, `category_fact_contracts.py`, `category_taxonomy.py`, `app/guide/understanding/contracts.py`, focused tests |
| Data tools | `app/guide/retrieval/category_fact_assets.py`, `tools/guide_data/**`, `tests/guide/tools/**`, data fixtures |
| Routing/behavior | `app/guide/understanding/exact_parsing.py`, `app/guide/intent/task_planning.py`, category fact projection, focused behavior tests |
| Integration Writer | `app/guide_runtime/composition.py`, `app/guide/application/chat_api_adapter.py`, formal HTTP/SSE/frontend tests and cycle docs |

## Task 1: Freeze Baseline and Audit Identity

**Files:**
- Create: `docs/audits/category-data-foundation/audit_ledger.csv`
- Create: `docs/audits/category-data-foundation/progress.md`
- Test: `tests/guide/retrieval/test_category_taxonomy.py`
- Test: `tests/guide/retrieval/test_approved_review_assets.py`

- [ ] **Step 1: Verify the clean baseline**

Run:

```bash
git status --short --branch
git rev-parse HEAD
python3 -m pytest -c pytest-guide.ini -q \
  tests/guide/retrieval/test_category_taxonomy.py \
  tests/guide/retrieval/test_canonical_retrieval.py \
  tests/guide/retrieval/test_scenario_constraints.py \
  tests/guide/adapters/catalog/test_canonical_guide_catalog.py \
  tests/guide/retrieval/test_approved_review_assets.py
```

Expected:

```text
## rebuild
a29d727
52 passed
```

- [ ] **Step 2: Freeze protected hashes**

Run:

```bash
git ls-tree -r HEAD -- app/services app/database data/canonical \
  app/guide/decision/deterministic_ranking.py > \
  /tmp/category-data-protected-tree.txt
shasum -a 256 app/guide/decision/deterministic_ranking.py
```

Expected ranking SHA:

```text
4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f
```

- [ ] **Step 3: Record the opening audit row**

Create the ledger header:

```csv
timestamp,capability_key,iteration_id,audit_key,audit_profile,scope_manifest,source_commit,status,severity_counts,report,evidence
```

Use:

```text
capability_key=category-aware-data-foundation
audit_profile=category-data-full-file-v1
status=FINDINGS
severity_counts=P0=0;P1=2;P2=1
report=docs/audits/category-data-foundation/opening_audit.md
```

- [ ] **Step 4: Commit the audit baseline**

```bash
git add docs/audits/category-data-foundation
git commit -m "docs(guide): freeze category data audit baseline"
```

## Task 2: Add Strict Category Profile Contracts

**Files:**
- Create: `app/guide/retrieval/category_profiles.py`
- Create: `tests/guide/retrieval/test_category_profiles.py`
- Modify: `app/guide/retrieval/category_taxonomy.py`

- [ ] **Step 1: Write failing profile tests**

Create:

```python
from app.guide.retrieval.category_profiles import (
    CategoryProfile,
    category_profile_for,
)
from app.guide.retrieval.category_taxonomy import raw_category_mapping


def test_all_six_profiles_are_stable() -> None:
    assert {item.value for item in CategoryProfile} == {
        "skincare",
        "suncare",
        "base_makeup",
        "color_makeup",
        "cleanser",
        "fragrance",
    }


def test_all_39_canonical_categories_map_exactly_once() -> None:
    mapping = raw_category_mapping()
    assert len(mapping) == 39
    assert len(set(mapping)) == 39
    assert all(category_profile_for(value) in CategoryProfile for value in mapping)


def test_unknown_category_fails_closed() -> None:
    try:
        category_profile_for("美容仪")
    except KeyError:
        return
    raise AssertionError("unknown category must not default to skincare")
```

- [ ] **Step 2: Run RED**

```bash
python3 -m pytest -c pytest-guide.ini -q \
  tests/guide/retrieval/test_category_profiles.py
```

Expected: collection FAIL because `category_profiles` does not exist.

- [ ] **Step 3: Implement the immutable profile registry**

Create:

```python
from enum import Enum
from types import MappingProxyType


class CategoryProfile(str, Enum):
    SKINCARE = "skincare"
    SUNCARE = "suncare"
    BASE_MAKEUP = "base_makeup"
    COLOR_MAKEUP = "color_makeup"
    CLEANSER = "cleanser"
    FRAGRANCE = "fragrance"


RAW_CATEGORY_PROFILES = MappingProxyType({
    "乳液": CategoryProfile.SKINCARE,
    "乳霜": CategoryProfile.SKINCARE,
    "爽肤水": CategoryProfile.SKINCARE,
    "眼部精华": CategoryProfile.SKINCARE,
    "眼霜": CategoryProfile.SKINCARE,
    "精华": CategoryProfile.SKINCARE,
    "精华水": CategoryProfile.SKINCARE,
    "精华液": CategoryProfile.SKINCARE,
    "面膜": CategoryProfile.SKINCARE,
    "面霜": CategoryProfile.SKINCARE,
    "防晒": CategoryProfile.SUNCARE,
    "防晒乳": CategoryProfile.SUNCARE,
    "防晒乳液": CategoryProfile.SUNCARE,
    "防晒隔离": CategoryProfile.SUNCARE,
    "防晒霜": CategoryProfile.SUNCARE,
    "妆前乳": CategoryProfile.BASE_MAKEUP,
    "散粉": CategoryProfile.BASE_MAKEUP,
    "气垫": CategoryProfile.BASE_MAKEUP,
    "气垫粉底": CategoryProfile.BASE_MAKEUP,
    "气垫粉底液": CategoryProfile.BASE_MAKEUP,
    "粉底液": CategoryProfile.BASE_MAKEUP,
    "蜜粉": CategoryProfile.BASE_MAKEUP,
    "遮瑕膏": CategoryProfile.BASE_MAKEUP,
    "单色眼影": CategoryProfile.COLOR_MAKEUP,
    "口红": CategoryProfile.COLOR_MAKEUP,
    "唇膏": CategoryProfile.COLOR_MAKEUP,
    "腮红": CategoryProfile.COLOR_MAKEUP,
    "卸妆": CategoryProfile.CLEANSER,
    "卸妆水/洁肤液": CategoryProfile.CLEANSER,
    "卸妆洁肤液/卸妆水": CategoryProfile.CLEANSER,
    "卸妆膏": CategoryProfile.CLEANSER,
    "洁面/清洁": CategoryProfile.CLEANSER,
    "洁面乳/泡沫洁面乳": CategoryProfile.CLEANSER,
    "洁面乳/洁面泡沫": CategoryProfile.CLEANSER,
    "洁面泡沫": CategoryProfile.CLEANSER,
    "洁面霜/洁面": CategoryProfile.CLEANSER,
    "洁颜油/卸妆油": CategoryProfile.CLEANSER,
    "洁颜霜/卸妆膏": CategoryProfile.CLEANSER,
    "香水": CategoryProfile.FRAGRANCE,
})


def category_profile_for(raw_category: str) -> CategoryProfile:
    return RAW_CATEGORY_PROFILES[raw_category]
```

Update `category_taxonomy.py` so `raw_category_mapping()` returns the immutable
mapping and existing sunscreen/serum families remain byte-for-byte compatible.

- [ ] **Step 4: Run GREEN**

```bash
python3 -m pytest -c pytest-guide.ini -q \
  tests/guide/retrieval/test_category_profiles.py \
  tests/guide/retrieval/test_category_taxonomy.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/guide/retrieval/category_profiles.py \
  app/guide/retrieval/category_taxonomy.py \
  tests/guide/retrieval/test_category_profiles.py
git commit -m "feat(guide): add strict category profiles"
```

## Task 3: Add Field Definitions and Capability Policy

**Files:**
- Create: `app/guide/retrieval/category_fact_contracts.py`
- Create: `tests/guide/retrieval/test_category_fact_contracts.py`

- [ ] **Step 1: Write failing contract tests**

```python
import pytest
from pydantic import ValidationError

from app.guide.retrieval.category_fact_contracts import (
    CategoryFieldDefinition,
    CategoryProfile,
    SourceClass,
    category_field_registry,
)


def test_base_makeup_has_only_its_declared_fields() -> None:
    registry = category_field_registry()
    keys = {item.key for item in registry.for_profile(CategoryProfile.BASE_MAKEUP)}
    assert {"shade", "finish", "coverage", "longevity", "texture"} <= keys
    assert "fragrance_family" not in keys


def test_unapproved_source_cannot_gain_compare_or_rank() -> None:
    with pytest.raises(ValidationError):
        CategoryFieldDefinition(
            key="shade",
            label="色号",
            value_type="string",
            profiles=[CategoryProfile.BASE_MAKEUP],
            sources=[SourceClass.UNKNOWN],
            capabilities=["evidence", "compare"],
        )
```

- [ ] **Step 2: Run RED**

```bash
python3 -m pytest -c pytest-guide.ini -q \
  tests/guide/retrieval/test_category_fact_contracts.py
```

Expected: FAIL because contracts do not exist.

- [ ] **Step 3: Implement strict models**

Implement:

```python
from enum import Enum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.guide.retrieval.category_profiles import CategoryProfile


class SourceClass(str, Enum):
    CANONICAL_CORE = "canonical_core"
    STRUCTURED_OFFICIAL = "structured_official"
    OFFICIAL_PACKAGING = "official_packaging"
    OFFICIAL_DESCRIPTION = "official_description"
    OCR_PACKAGING = "ocr_packaging"
    OCR_INGREDIENT_LIST = "ocr_ingredient_list"
    APPROVED_CONSUMER_REVIEW = "approved_consumer_review"
    UNKNOWN = "unknown"


Capability = Literal[
    "evidence", "display", "compare", "hard_filter", "soft_rank"
]


class CategoryFieldDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    label: str = Field(min_length=1, max_length=32)
    value_type: Literal["string", "string_list", "number", "boolean"]
    profiles: frozenset[CategoryProfile]
    sources: tuple[SourceClass, ...]
    capabilities: frozenset[Capability]
    unknown_policy: Literal["preserve_unknown"] = "preserve_unknown"
    conflict_policy: Literal["record"] = "record"

    @model_validator(mode="after")
    def validate_authority(self):
        if "evidence" not in self.capabilities:
            raise ValueError("every field requires evidence capability")
        if SourceClass.UNKNOWN in self.sources and len(self.capabilities) > 1:
            raise ValueError("unknown source is evidence-only")
        return self
```

Define the exact common and profile-specific field set from the approved design.
Reject duplicate keys and duplicate aliases.

- [ ] **Step 4: Run GREEN and contract expansion**

```bash
python3 -m pytest -c pytest-guide.ini -q \
  tests/guide/retrieval/test_category_fact_contracts.py \
  tests/guide/test_architecture_boundaries.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/guide/retrieval/category_fact_contracts.py \
  tests/guide/retrieval/test_category_fact_contracts.py
git commit -m "feat(guide): define category field authority"
```

## Task 4: Expand Understanding and Task Planning

**Files:**
- Modify: `app/guide/understanding/contracts.py`
- Modify: `app/guide/understanding/exact_parsing.py`
- Modify: `app/guide/intent/task_planning.py`
- Test: `tests/guide/understanding/test_text_understanding.py`
- Create: `tests/guide/understanding/test_category_profile_parsing.py`
- Test: `tests/guide/intent/test_task_planning.py`

- [ ] **Step 1: Write RED cases for six profiles**

```python
import pytest

from app.guide.understanding.exact_parsing import parse_exact_constraints
from app.guide.understanding.contracts import CategoryDraft, TopicCode


@pytest.mark.parametrize(
    ("message", "topic"),
    [
        ("推荐一款修护精华", TopicCode.SERUM),
        ("推荐通勤防晒", TopicCode.SUNSCREEN),
        ("推荐持妆粉底液", TopicCode.BASE_MAKEUP),
        ("推荐显白口红", TopicCode.COLOR_MAKEUP),
        ("推荐温和卸妆油", TopicCode.CLEANSER),
        ("推荐木质调香水", TopicCode.FRAGRANCE),
    ],
)
def test_six_category_topics_are_parsed(message, topic) -> None:
    constraints, issues = parse_exact_constraints(message)
    assert issues == []
    assert next(
        item.value for item in constraints if isinstance(item, CategoryDraft)
    ) is topic
```

- [ ] **Step 2: Run RED**

```bash
python3 -m pytest -c pytest-guide.ini -q \
  tests/guide/understanding/test_category_profile_parsing.py \
  tests/guide/intent/test_task_planning.py
```

Expected: new topic enum cases FAIL.

- [ ] **Step 3: Add topic codes and longest-alias-first parsing**

Add:

```python
class TopicCode(str, Enum):
    SUNSCREEN = "sunscreen"
    SERUM = "serum"
    SKINCARE = "skincare"
    BASE_MAKEUP = "base_makeup"
    COLOR_MAKEUP = "color_makeup"
    CLEANSER = "cleanser"
    FRAGRANCE = "fragrance"
```

Define aliases in descending length so `卸妆油` is not swallowed by `卸妆`
and `防晒隔离` remains sunscreen. Keep `精华水` and `眼部精华` under
`SKINCARE`, not `SERUM`.

Update clarification copy to list the six supported profiles. Keep the existing
repair-efficacy requirement only for `TopicCode.SERUM`.

- [ ] **Step 4: Run GREEN**

```bash
python3 -m pytest -c pytest-guide.ini -q \
  tests/guide/understanding \
  tests/guide/intent/test_task_planning.py \
  tests/guide/application/test_chat_api_adapter.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/guide/understanding/contracts.py \
  app/guide/understanding/exact_parsing.py \
  app/guide/intent/task_planning.py \
  tests/guide/understanding/test_category_profile_parsing.py \
  tests/guide/understanding/test_text_understanding.py \
  tests/guide/intent/test_task_planning.py
git commit -m "feat(guide): route six category profiles"
```

## Task 5: Add Category Fact Asset Contracts and Loader

**Files:**
- Create: `app/guide/retrieval/category_fact_assets.py`
- Create: `tests/guide/retrieval/test_category_fact_assets.py`
- Create: `tests/fixtures/guide/category_facts/approved.jsonl`
- Create: `tests/fixtures/guide/category_facts/manifest.json`

- [ ] **Step 1: Write loader RED tests**

Test exact fields:

```python
def test_loader_requires_content_addressed_sorted_assets(tmp_path):
    loaded = load_category_fact_assets(
        manifest_path=FIXTURE_MANIFEST,
        facts_path=FIXTURE_FACTS,
        expected_manifest_sha256=EXPECTED_MANIFEST_SHA256,
    )
    assert [item.fact_id for item in loaded.facts] == sorted(
        item.fact_id for item in loaded.facts
    )
    assert all(item.source_refs for item in loaded.facts)


def test_loader_rejects_category_profile_mismatch(tmp_path):
    manifest_path, facts_path = mutable_fixture(tmp_path)
    facts = read_jsonl(facts_path)
    facts[0]["category_profile"] = "fragrance"
    manifest_sha256 = write_and_rehash(
        manifest_path,
        facts_path,
        facts,
    )
    with pytest.raises(CategoryFactAssetIntegrityError):
        load_category_fact_assets(
            manifest_path=manifest_path,
            facts_path=facts_path,
            expected_manifest_sha256=manifest_sha256,
        )
```

- [ ] **Step 2: Run RED**

```bash
python3 -m pytest -c pytest-guide.ini -q \
  tests/guide/retrieval/test_category_fact_assets.py
```

Expected: FAIL because loader does not exist.

- [ ] **Step 3: Implement deterministic asset validation**

The production fact model must be:

```python
class ApprovedCategoryFact(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    fact_id: str
    product_id: int = Field(gt=0)
    category_profile: CategoryProfile
    field_key: str
    value: JsonValue
    source_class: SourceClass
    source_refs: tuple[str, ...]
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_status: Literal["approved_fact"] = "approved_fact"
    reviewer: str
    reviewed_at: datetime
```

Validate:

- source and manifest SHA-256;
- sorted unique fact IDs;
- `fact_count=0` as a valid empty approved sidecar;
- fact field/profile applicability;
- product/profile binding against Canonical category mapping;
- no local absolute path or raw HTML;
- duplicate exact facts collapse;
- conflicting stable identity fails.

- [ ] **Step 4: Run GREEN**

```bash
python3 -m pytest -c pytest-guide.ini -q \
  tests/guide/retrieval/test_category_fact_assets.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/guide/retrieval/category_fact_assets.py \
  tests/guide/retrieval/test_category_fact_assets.py \
  tests/fixtures/guide/category_facts
git commit -m "feat(guide): validate approved category facts"
```

## Task 6: Build Deterministic Candidate Extraction

**Files:**
- Create: `tools/guide_data/__init__.py`
- Create: `tools/guide_data/build_category_fact_candidates.py`
- Create: `tests/guide/tools/test_build_category_fact_candidates.py`
- Create: `tests/fixtures/guide/category_data/source_manifest.json`
- Create: `tests/fixtures/guide/category_data/official_product.html`
- Create: `tests/fixtures/guide/category_data/ocr_observation.json`

- [ ] **Step 1: Write RED for deterministic candidates**

```python
def test_candidate_build_is_byte_deterministic(tmp_path):
    first = run_builder(tmp_path / "first", reversed_inputs=False)
    second = run_builder(tmp_path / "second", reversed_inputs=True)
    assert first.read_bytes() == second.read_bytes()


def test_builder_never_approves_candidates(tmp_path):
    rows = read_jsonl(run_builder(tmp_path))
    assert rows
    assert {row["status"] for row in rows} == {"pending"}
    assert all("reviewer" not in row for row in rows)
```

- [ ] **Step 2: Run RED**

```bash
python3 -m pytest -c pytest-guide.ini -q \
  tests/guide/tools/test_build_category_fact_candidates.py
```

- [ ] **Step 3: Implement the CLI**

CLI:

```text
python -m tools.guide_data.build_category_fact_candidates \
  --source-manifest tests/fixtures/guide/category_data/source_manifest.json \
  --canonical-products data/canonical/core_products_v1.jsonl \
  --output /tmp/category-fact-pending.jsonl \
  --quarantine /tmp/category-fact-quarantine.jsonl
```

Candidate ID:

```python
candidate_id = sha256(
    (
        f"{product_id}\0{category_profile}\0{field_key}\0"
        f"{source_sha256}\0{source_locator}\0{normalized_value_json}"
    ).encode("utf-8")
).hexdigest()
```

Reject unsupported profile/field/source combinations into quarantine. Strip
PII and absolute paths before serialization. Sort by candidate ID.

- [ ] **Step 4: Run GREEN**

```bash
python3 -m pytest -c pytest-guide.ini -q \
  tests/guide/tools/test_build_category_fact_candidates.py
```

- [ ] **Step 5: Commit**

```bash
git add tools/guide_data \
  tests/guide/tools/test_build_category_fact_candidates.py \
  tests/fixtures/guide/category_data
git commit -m "feat(tools): build category fact candidates"
```

## Task 7: Add Explicit Promotion for Approved Category Facts

**Files:**
- Create: `tools/guide_data/promote_approved_category_facts.py`
- Create: `tests/guide/tools/test_promote_approved_category_facts.py`

- [ ] **Step 1: Write promotion RED tests**

```python
def test_promotion_requires_complete_human_decision(tmp_path):
    candidates = pending_candidates(tmp_path)
    decisions = [{"candidate_id": candidates[0]["candidate_id"]}]
    with pytest.raises(ValueError, match="reviewer"):
        promote(candidates, decisions, tmp_path / "out")


def test_failed_promotion_keeps_previous_asset(tmp_path):
    existing = install_existing_asset(tmp_path)
    with pytest.raises(ValueError):
        promote_invalid(tmp_path)
    assert existing.read_bytes() == ORIGINAL_BYTES
```

- [ ] **Step 2: Run RED**

```bash
python3 -m pytest -c pytest-guide.ini -q \
  tests/guide/tools/test_promote_approved_category_facts.py
```

- [ ] **Step 3: Implement atomic promotion**

Require each decision to contain:

```json
{
  "candidate_id": "0000000000000000000000000000000000000000000000000000000000000001",
  "decision": "approved_fact",
  "reviewer": "human-reviewer-01",
  "reviewed_at": "2026-08-10T00:00:00Z",
  "reason": "原始页面明确标注，且产品与字段归属已人工核对"
}
```

Write facts and manifest to sibling temporary files, fsync, validate with
`load_category_fact_assets`, then use `os.replace`. Reject unknown candidates,
duplicate decisions, non-approved statuses in the production output, and hash
drift.

- [ ] **Step 4: Run GREEN**

```bash
python3 -m pytest -c pytest-guide.ini -q \
  tests/guide/tools/test_promote_approved_category_facts.py \
  tests/guide/retrieval/test_category_fact_assets.py
```

- [ ] **Step 5: Commit**

```bash
git add tools/guide_data/promote_approved_category_facts.py \
  tests/guide/tools/test_promote_approved_category_facts.py
git commit -m "feat(tools): promote reviewed category facts"
```

## Task 8: Project Twelve Pilot Products Honestly

**Files:**
- Create: `data/guide_category_facts/category_facts_v1.jsonl`
- Create: `data/guide_category_facts/category_facts_v1_manifest.json`
- Create: `docs/audits/category-data-foundation/pilot_coverage.md`
- Create: `tests/guide/retrieval/test_category_pilot_coverage.py`

- [ ] **Step 1: Write the pilot coverage RED test**

```python
PILOT_IDS = {
    "skincare": {38, 91},
    "suncare": {53, 57},
    "base_makeup": {79, 80},
    "color_makeup": {86, 114},
    "cleanser": {69, 103},
    "fragrance": {120, 121},
}


def test_pilot_matrix_is_exact_and_honest(category_assets, canonical_reader):
    assert set().union(*PILOT_IDS.values()) == set(category_assets.pilot_ids)
    for profile, product_ids in PILOT_IDS.items():
        assert category_assets.pilot_ids_for(profile) == product_ids
        for product_id in product_ids:
            assert canonical_reader.get(product_id).fields["category"].resolved_state == "known"
    assert all(
        fact.source_refs and fact.evidence_status == "approved_fact"
        for fact in category_assets.facts
    )


def test_empty_approved_sidecar_keeps_all_specialized_fields_unknown(
    empty_category_assets,
):
    assert empty_category_assets.fact_count == 0
    assert empty_category_assets.facts == ()
    assert empty_category_assets.pilot_ids == set().union(
        *PILOT_IDS.values()
    )
```

- [ ] **Step 2: Run RED**

```bash
python3 -m pytest -c pytest-guide.ini -q \
  tests/guide/retrieval/test_category_pilot_coverage.py
```

- [ ] **Step 3: Generate the approved asset only from existing approved decisions**

Use the promotion tool. If no independently approved category-specific fact is
available for a pilot field, record it as missing in `pilot_coverage.md`; do
not create a fact row.

The report must include, per pilot product:

```text
profile
product_id
applicable_fields
approved_known_fields
unknown_fields
conflict_fields
source_refs
```

- [ ] **Step 4: Run GREEN and hash verification**

```bash
python3 -m pytest -c pytest-guide.ini -q \
  tests/guide/retrieval/test_category_pilot_coverage.py \
  tests/guide/retrieval/test_category_fact_assets.py
shasum -a 256 data/guide_category_facts/*
```

- [ ] **Step 5: Commit**

```bash
git add data/guide_category_facts \
  docs/audits/category-data-foundation/pilot_coverage.md \
  tests/guide/retrieval/test_category_pilot_coverage.py
git commit -m "data(guide): add category pilot coverage"
```

## Task 9: Compose Category Facts into Guide Ports

**Files:**
- Create: `app/guide/retrieval/category_fact_reader.py`
- Modify: `app/guide/adapters/catalog/canonical_guide_catalog.py`
- Modify: `app/guide/decision/contracts.py`
- Modify: `app/guide/presentation/contracts.py`
- Modify: `app/guide/presentation/response_planning.py`
- Test: `tests/guide/adapters/catalog/test_canonical_guide_catalog.py`
- Create: `tests/guide/retrieval/test_category_fact_reader.py`

- [ ] **Step 1: Write RED for authorization and unknown preservation**

```python
def test_category_fact_reader_returns_only_authorized_profile_values(reader):
    values = reader.read(product_id=79, profile="base_makeup")
    assert all(value.field_key != "fragrance_family" for value in values)


def test_unknown_category_fact_never_changes_winner(orchestrator):
    baseline = orchestrator.orchestrate(turn("推荐持妆粉底液"))
    poisoned = orchestrator_with_unapproved_candidate(
        field_key="longevity",
        value="72小时持妆",
    ).orchestrate(turn("推荐持妆粉底液"))
    assert card_ids(poisoned) == card_ids(baseline)
```

- [ ] **Step 2: Run RED**

```bash
python3 -m pytest -c pytest-guide.ini -q \
  tests/guide/retrieval/test_category_fact_reader.py \
  tests/guide/adapters/catalog/test_canonical_guide_catalog.py
```

- [ ] **Step 3: Implement additive projection**

Add a strict `CategoryFactPort`. Extend decision and presentation facts with:

```python
category_profile: CategoryProfile
category_fields: tuple[AuthorizedCategoryFact, ...]
```

Do not add arbitrary dictionaries. `AuthorizedCategoryFact` must preserve
field key, typed value, state, source refs, and allowed public capabilities.
The recommendation sorter remains unchanged unless a field is explicitly
`soft_rank` and independently approved.

- [ ] **Step 4: Run GREEN**

```bash
python3 -m pytest -c pytest-guide.ini -q \
  tests/guide/retrieval/test_category_fact_reader.py \
  tests/guide/adapters/catalog/test_canonical_guide_catalog.py \
  tests/guide/decision/test_recommendation.py \
  tests/guide/presentation/test_response_planning.py
```

- [ ] **Step 5: Commit**

```bash
git add app/guide/retrieval/category_fact_reader.py \
  app/guide/adapters/catalog/canonical_guide_catalog.py \
  app/guide/decision/contracts.py \
  app/guide/presentation/contracts.py \
  app/guide/presentation/response_planning.py \
  tests/guide/retrieval/test_category_fact_reader.py \
  tests/guide/adapters/catalog/test_canonical_guide_catalog.py
git commit -m "feat(guide): project authorized category facts"
```

## Task 10: Add Review Candidate and Promotion Tools

**Files:**
- Create: `tools/guide_data/build_review_candidates.py`
- Create: `tools/guide_data/promote_approved_reviews.py`
- Create: `tests/guide/tools/test_build_review_candidates.py`
- Create: `tests/guide/tools/test_promote_approved_reviews.py`

- [ ] **Step 1: Write RED for fixture determinism and existing six approvals**

```python
def test_review_candidate_fixture_is_byte_deterministic(tmp_path):
    first = build_review_candidates_from_fixture(
        output_root=tmp_path / "first",
        reverse_inputs=False,
    )
    second = build_review_candidates_from_fixture(
        output_root=tmp_path / "second",
        reverse_inputs=True,
    )
    assert first.pending.read_bytes() == second.pending.read_bytes()
    assert first.quarantine.read_bytes() == second.quarantine.read_bytes()


def test_promotion_preserves_existing_six_approved_sources(tmp_path):
    manifest_path, sources_path, manifest_sha256 = (
        promote_existing_decisions(tmp_path)
    )
    loaded = load_approved_review_assets(
        manifest_path=manifest_path,
        sources_path=sources_path,
        expected_manifest_sha256=manifest_sha256,
    )
    assert loaded.catalog.approved_source_count == 6
    assert {item.product_id for item in loaded.evidence} == {42, 49, 55}


def test_missing_original_html_never_claims_historical_reproduction(tmp_path):
    result = build_review_candidates_from_fixture(output_root=tmp_path)
    assert result.provenance_status == "fixture_only"
    assert result.historical_counts == {
        "total_candidates": 336,
        "strict_candidates": 111,
        "status": "not_rerun",
    }
```

- [ ] **Step 2: Run RED**

```bash
python3 -m pytest -c pytest-guide.ini -q \
  tests/guide/tools/test_build_review_candidates.py \
  tests/guide/tools/test_promote_approved_reviews.py
```

- [ ] **Step 3: Implement candidate generation**

Stable source identity remains:

```text
review_tmall_item_{item_id}_html_{full_sha256}_ordinal_{page_ordinal_8d}
```

The candidate builder writes pending/quarantine assets only. The promotion
tool requires explicit reviewer identity, atomically regenerates JSONL,
manifest, and the current audit machine block, then validates through
`load_approved_review_assets`.

The three historical source HTML files are not in the reproducible repository.
The tool must expose `fixture_only`/`not_rerun` provenance until source files
matching all three locked HTML SHA-256 values are explicitly supplied. It must
never convert historical 336/111 metadata into a successful rerun claim.

- [ ] **Step 4: Run GREEN and existing source regression**

```bash
python3 -m pytest -c pytest-guide.ini -q \
  tests/guide/tools/test_build_review_candidates.py \
  tests/guide/tools/test_promote_approved_reviews.py \
  tests/guide/retrieval/test_approved_review_assets.py \
  tests/guide/retrieval/test_review_evidence_reader.py \
  tests/guide/retrieval/test_review_summary.py
```

- [ ] **Step 5: Commit**

```bash
git add tools/guide_data/build_review_candidates.py \
  tools/guide_data/promote_approved_reviews.py \
  tests/guide/tools/test_build_review_candidates.py \
  tests/guide/tools/test_promote_approved_reviews.py
git commit -m "feat(tools): rebuild approved review assets"
```

## Task 11: Wire Runtime, Formal Routes, and Browser Behavior

**Files:**
- Modify: `app/guide_runtime/composition.py`
- Modify: `app/guide/application/chat_api_adapter.py`
- Modify: `app/api/v1/chat.py`
- Modify: `app/static/chat.html`
- Test: `tests/guide/runtime/test_composition.py`
- Test: `tests/guide/application/test_formal_chat_router_http.py`
- Test: `tests/guide/runtime/test_frontend_scope.py`
- Create: `tools/guide_gates/category_profile_browser_gate.py`

- [ ] **Step 1: Write shared RED tests**

Add parameterized formal HTTP/SSE cases:

```python
@pytest.mark.parametrize(
    ("message", "expected_profile", "expected_ids"),
    [
        ("推荐修护精华", "skincare", [38, 91]),
        ("推荐通勤防晒", "suncare", [53, 57]),
        ("推荐持妆粉底液", "base_makeup", [79, 80]),
        ("推荐显白口红", "color_makeup", [86, 114]),
        ("推荐温和卸妆油", "cleanser", [69, 103]),
        ("推荐木质调香水", "fragrance", [120, 121]),
    ],
)
def test_six_profiles_use_guide_and_exact_cards(
    pilot_only_formal_client,
    message,
    expected_profile,
    expected_ids,
):
    response = pilot_only_formal_client.post(
        "/chat/message",
        json={
            "message": message,
            "session_id": f"category-{expected_profile}",
            "conversation_version": 0,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"]["category_profile"] == expected_profile
    assert [item["id"] for item in payload["products"]] == expected_ids
    assert payload["card_display_contract"]["visible_product_ids"] == (
        expected_ids
    )
```

`pilot_only_formal_client` must use the real Canonical reader and real Guide
contracts, but its category catalog is explicitly limited to the twelve pilot
IDs. Exact pilot IDs are asserted only in this isolated integration fixture.
The production browser gate must instead assert:

- ChatOwner is Guide;
- every returned ID belongs to the requested profile;
- card count is 1–3;
- backend card order equals rendered order;
- category-specific facts are authorized or explicitly unavailable.

Do not force production ranking to return the two pilot IDs when the full
103-product catalog contains other eligible products.

Assert:

- one `start`;
- one terminal `end` or `error`;
- `answer_contract`, `card_display_contract`, products, and message order;
- exact product IDs and card count;
- category fact fields never appear as raw HTML/OCR;
- missing profile facts render explicit unavailable copy.

- [ ] **Step 2: Run RED**

```bash
python3 -m pytest -c pytest-guide.ini -q \
  tests/guide/application/test_formal_chat_router_http.py \
  tests/guide/runtime/test_composition.py \
  tests/guide/runtime/test_frontend_scope.py
```

- [ ] **Step 3: Wire the approved category asset**

Add `GUIDE_CATEGORY_FACT_RELATIVE_PATH` in composition and set
`GUIDE_CATEGORY_FACT_MANIFEST_SHA256` to the exact 64-character value printed
by:

```bash
jq -r '.manifest_sha256' \
  data/guide_category_facts/category_facts_v1_manifest.json
```

Add a test that reads the manifest and asserts exact equality with the constant.
Do not read the lock dynamically at runtime and do not use a wildcard hash.

Load the category fact reader once, inject it into the catalog, and keep
construction behind the existing threadpool/lazy runtime boundary. Update
owner classification only for newly supported category topics. Internal Guide
errors must remain terminal and must not fall back to legacy.

Frontend rendering is additive: show category facts only from typed event/card
fields, never parse answer text or use `innerHTML` with untrusted values.

- [ ] **Step 4: Run GREEN**

```bash
python3 -m pytest -c pytest-guide.ini -q \
  tests/guide/application/test_formal_chat_router_http.py \
  tests/guide/runtime/test_composition.py \
  tests/guide/runtime/test_frontend_scope.py
python3 tools/guide_gates/category_profile_browser_gate.py
```

Expected: six profiles pass, page errors 0, SSE errors 0, product-image errors
0.

- [ ] **Step 5: Commit**

```bash
git add app/guide_runtime/composition.py \
  app/guide/application/chat_api_adapter.py \
  app/api/v1/chat.py app/static/chat.html \
  tests/guide/runtime/test_composition.py \
  tests/guide/application/test_formal_chat_router_http.py \
  tests/guide/runtime/test_frontend_scope.py \
  tools/guide_gates/category_profile_browser_gate.py
git commit -m "feat(guide): expose category-aware recommendations"
```

## Task 12: Full Verification, Final Audit, and Handoff

**Files:**
- Modify: `.trae/specs/complete-category-aware-guide-data-foundation/tasks.md`
- Modify: `.trae/specs/complete-category-aware-guide-data-foundation/checklist.md`
- Modify: `.trae/specs/complete-category-aware-guide-data-foundation/progress.md`
- Modify: `docs/audits/category-data-foundation/audit_ledger.csv`
- Create: `docs/audits/category-data-foundation/final_handoff.md`

- [ ] **Step 1: Run focused and full suites**

```bash
python3 -m pytest -c pytest-guide.ini -q \
  tests/guide/retrieval/test_category_profiles.py \
  tests/guide/retrieval/test_category_fact_contracts.py \
  tests/guide/retrieval/test_category_fact_assets.py \
  tests/guide/retrieval/test_category_fact_reader.py \
  tests/guide/retrieval/test_category_pilot_coverage.py \
  tests/guide/tools/test_build_category_fact_candidates.py \
  tests/guide/tools/test_promote_approved_category_facts.py \
  tests/guide/tools/test_build_review_candidates.py \
  tests/guide/tools/test_promote_approved_reviews.py

UV_OFFLINE=1 uv run \
  --with-requirements requirements-guide-runtime-test.txt \
  python -m pytest -c pytest-guide.ini -q

UV_OFFLINE=1 uv run \
  --with-requirements requirements-guide-runtime-test.txt \
  python -m pytest -c pytest-guide.ini -q tests/guide/runtime
```

Expected: zero failures. If the offline cache lacks a locked wheel, classify
`ENVIRONMENT`, use the already approved combined environment, and record the
exact interpreter and package versions.

- [ ] **Step 2: Run static and protection gates**

```bash
python3 -m compileall -q app/guide app/guide_runtime tools/guide_data
python3 -m app.guide.check_boundaries app/guide
python3 -m app.guide.check_boundaries app/guide_runtime
git diff --check
git diff --exit-code a29d727 -- app/services app/database data/canonical \
  app/guide/decision/deterministic_ranking.py
shasum -a 256 app/guide/decision/deterministic_ranking.py
```

Expected: both boundaries pass, protected diff empty, ranking SHA unchanged.

- [ ] **Step 3: Run browser gates**

Run normal, adversarial, category profile, consultation, review, and image
gates against isolated state directories and ports. Expected:

```text
page errors = 0
SSE errors = 0
unexpected HTTP 5xx = 0
failed product images = 0
cross-session leakage = 0
```

- [ ] **Step 4: Run the unique final independent audit**

Create capability:

```text
FINAL-CATEGORY-DATA-AUDIT
```

Freeze the production file manifest. The independent auditor is read-only.
Confirmed findings require a RED test and a single-writer fix. Rerun normal
quality gates after fixes; do not invoke a second full-file audit for the same
audit key.

- [ ] **Step 5: Close tasks and write handoff**

The handoff must report:

- final code SHA;
- six-profile mapping count 39/39;
- exact pilot IDs;
- approved/unknown/conflict counts by profile;
- existing approved review count and product coverage;
- candidate and quarantine counts;
- focused/full/runtime/browser results;
- audit result and evidence paths;
- protected path and ranking proof;
- confirmation that no push/deploy/traffic switch occurred.

- [ ] **Step 6: Commit final closure**

```bash
git add .trae/specs/complete-category-aware-guide-data-foundation \
  docs/audits/category-data-foundation
git commit -m "docs(guide): close category data foundation"
```

## Spec Coverage Matrix

| Design requirement | Implementation tasks |
| --- | --- |
| Six profiles and 39/39 mapping | Tasks 2 and 4 |
| Field applicability, sources, and capability | Tasks 3 and 9 |
| Canonical v1 and ranking remain protected | Tasks 1 and 12 |
| Deterministic pending category candidates | Task 6 |
| Human-decision-only category promotion | Tasks 7 and 8 |
| Twelve honest pilots and empty-sidecar support | Task 8 |
| Category facts projected through strict Guide ports | Task 9 |
| Review candidate and promotion tools | Task 10 |
| Six formal HTTP/SSE/frontend paths | Task 11 |
| Dynamic concurrency and audit idempotency | Tasks 1, 12, and 13 |
| Full tests, browser gates, and final handoff | Tasks 12 and 13 |
