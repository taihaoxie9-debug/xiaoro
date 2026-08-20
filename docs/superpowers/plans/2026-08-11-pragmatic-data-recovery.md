# Pragmatic Guide Data Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Inventory existing local HTML/OCR sources, recover verifiable evidence for the 12 category pilots and three review-covered products, and produce deterministic pending/quarantine queues without approving or inventing facts.

**Architecture:** A read-only inventory hashes local sources and binds them to product/item/SKU identities. Existing category/review candidate builders classify source-backed records into pending or quarantine. Missing evidence removes only the affected optional field; products with trusted core identity/category/price remain available with `unknown`.

**Tech Stack:** Python 3.11 standard library, existing Guide candidate builders, JSONL manifests, SHA-256, pytest

---

## Authority And Scope

Read in this order:

1. `docs/superpowers/specs/2026-08-10-guide-intent-cutover-and-pragmatic-data-recovery-design.md`
2. `docs/superpowers/specs/2026-08-10-category-aware-guide-data-foundation-design.md`
3. This plan
4. `.trae/specs/complete-category-aware-guide-data-foundation/**`

Hard constraints:

- no formal full-file audit; the core closure plan owns the project's one opening audit;
- no changes to `data/canonical/**`;
- no automatic approval or promotion;
- no reviewer identity fabrication;
- no raw HTML, absolute local path, API key or PII in production assets or Git;
- comments cannot create formula, safety, verified-absence, filtering or winner facts;
- OCR cannot create efficacy, safety or verified-absence facts;
- missing optional evidence means field-level `unknown`, not product deletion;
- whole-product quarantine is limited to identity/SKU binding failures or core identity conflicts.

## Target Products

Category pilots:

```text
skincare: 38, 91
suncare: 53, 57
base_makeup: 79, 80
color_makeup: 86, 114
cleanser: 69, 103
fragrance: 120, 121
```

Approved-review products:

```text
42, 49, 55
```

## Task 1: Build A Read-Only Source Inventory

**Files:**
- Create: `tools/guide_data/inventory_local_sources.py`
- Test: `tests/guide/tools/test_inventory_local_sources.py`
- Create during execution: `docs/audits/guide-closure/data/source_inventory_summary.md`

- [ ] **Step 1: Write inventory RED tests**

```python
import json
from pathlib import Path

import pytest

from tools.guide_data.inventory_local_sources import inventory_sources


def test_inventory_hashes_without_copying_source_content(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"
    source_root.mkdir()
    source = source_root / "product.html"
    source.write_text("<html>review</html>", encoding="utf-8")
    output = tmp_path / "output" / "inventory.jsonl"
    result = inventory_sources(
        roots=[source_root],
        output_path=output,
    )
    rows = [
        json.loads(line)
        for line in output.read_text().splitlines()
    ]
    assert result.file_count == 1
    assert rows[0]["relative_name"] == "product.html"
    assert rows[0]["sha256"]
    assert "review" not in output.read_text()
    assert str(tmp_path) not in output.read_text()


def test_inventory_rejects_output_inside_source_tree(tmp_path: Path) -> None:
    source_root = tmp_path / "sources"
    source_root.mkdir()
    with pytest.raises(ValueError, match="output must be outside source roots"):
        inventory_sources(
            roots=[source_root],
            output_path=source_root / "inventory.jsonl",
        )
```

- [ ] **Step 2: Verify RED**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q tests/guide/tools/test_inventory_local_sources.py
```

Expected: missing module error.

- [ ] **Step 3: Implement inventory**

Supported extensions:

```python
SUPPORTED_SUFFIXES = {
    ".html",
    ".htm",
    ".json",
    ".jsonl",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
}
```

Each output row:

```json
{
  "content_type": "html",
  "relative_name": "product.html",
  "sha256": "64 lowercase hex characters",
  "size_bytes": 123,
  "source_root_id": "sha256 of normalized source root label, not its path"
}
```

Rules:

- use `os.open(..., O_NOFOLLOW)` where available;
- reject symlinks, sockets and non-regular files;
- hash bytes once;
- do not parse content;
- do not output absolute paths;
- sort by `(sha256, relative_name, source_root_id)`;
- write atomically with mode `0600`;
- do not mutate source timestamps or files.

- [ ] **Step 4: Run tests**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q tests/guide/tools/test_inventory_local_sources.py
```

Expected: PASS.

- [ ] **Step 5: Run inventory against known local roots**

Run only when each root exists:

```bash
PYTHONPATH=. /private/tmp/xiaoro-guide-runtime-venv/bin/python \
  tools/guide_data/inventory_local_sources.py \
  --root /Users/bytedance/Desktop/xiaoro-shopping-master/.tmp_user_download_audit \
  --root /Users/bytedance/Desktop/xiaoro-shopping-master/data \
  --root /Users/bytedance/Desktop/xiaoro-fresh/tests/fixtures/guide \
  --output /private/tmp/xiaoro-guide-source-inventory.jsonl
```

Expected: a local inventory outside Git. Record only aggregate counts and the
inventory SHA in `source_inventory_summary.md`.

- [ ] **Step 6: Commit tool and tests**

```bash
git add tools/guide_data/inventory_local_sources.py tests/guide/tools/test_inventory_local_sources.py docs/audits/guide-closure/data/source_inventory_summary.md
git commit -m "feat(data): inventory local Guide sources"
```

## Task 2: Locate The Three Historical Review HTML Files By Hash

**Files:**
- Create: `tools/guide_data/find_locked_review_sources.py`
- Test: `tests/guide/tools/test_find_locked_review_sources.py`
- Create during execution: `docs/audits/guide-closure/data/review_source_recovery.json`

- [ ] **Step 1: Write exact-hash lookup tests**

```python
import json
from pathlib import Path

from tools.guide_data.find_locked_review_sources import find_locked_sources


LOCKED = {
    "b31206098d6839257e5dd29c1fae71495b067029568763d9a726b16fc47fd3e4",
    "55996a2a8207e65eb434fa376d61dc0f34d5621f51f9c3754e2369021d9a7f44",
    "56719aa64a4222a961b2ea118cf51415f25c4f88560e5de83172adc8e9c13783",
}


def write_inventory(tmp_path: Path, *, hashes: list[str]) -> Path:
    path = tmp_path / "inventory.jsonl"
    rows = [
        {
            "content_type": "html",
            "relative_name": f"source-{index}.html",
            "sha256": value,
            "size_bytes": 100 + index,
            "source_root_id": "a" * 64,
        }
        for index, value in enumerate(hashes, start=1)
    ]
    path.write_text(
        "".join(
            json.dumps(row, sort_keys=True) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    return path


def test_lookup_matches_only_full_sha256(tmp_path) -> None:
    inventory = write_inventory(
        tmp_path,
        hashes=[next(iter(LOCKED)), "0" * 64],
    )
    result = find_locked_sources(inventory, locked_hashes=LOCKED)
    assert result.found_count == 1
    assert result.missing_count == 2
```

- [ ] **Step 2: Verify RED**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q tests/guide/tools/test_find_locked_review_sources.py
```

Expected: missing module failure.

- [ ] **Step 3: Implement lookup**

Output one row per locked hash:

```json
{
  "html_sha256": "locked hash",
  "status": "found|missing|duplicate",
  "matches": [
    {
      "relative_name": "redacted relative name",
      "source_root_id": "opaque root ID",
      "size_bytes": 123
    }
  ]
}
```

Do not copy raw HTML. `duplicate` means multiple byte-identical local files and
is not a content conflict.

- [ ] **Step 4: Run lookup on the local inventory**

```bash
PYTHONPATH=. /private/tmp/xiaoro-guide-runtime-venv/bin/python \
  tools/guide_data/find_locked_review_sources.py \
  --inventory /private/tmp/xiaoro-guide-source-inventory.jsonl \
  --approved-manifest data/guide_review_sources/approved_tmall_feed_reviews_v1_manifest.json \
  --output docs/audits/guide-closure/data/review_source_recovery.json
```

Expected:

- `found` when exact bytes exist;
- `missing` when they do not;
- never infer a match from item ID, filename or OCR text.

- [ ] **Step 5: Commit recovery result**

```bash
git add tools/guide_data/find_locked_review_sources.py tests/guide/tools/test_find_locked_review_sources.py docs/audits/guide-closure/data/review_source_recovery.json
git commit -m "docs(data): record locked review source recovery"
```

## Task 3: Build A Pilot Field Coverage Report

**Files:**
- Create: `tools/guide_data/report_pilot_field_coverage.py`
- Test: `tests/guide/tools/test_report_pilot_field_coverage.py`
- Create during execution: `docs/audits/guide-closure/data/pilot_field_coverage.json`

- [ ] **Step 1: Write field-level discard RED**

```python
from app.guide.retrieval.category_profiles import CategoryProfile
from tools.guide_data.report_pilot_field_coverage import (
    build_product_coverage,
)


def field(state: str, value=None) -> dict:
    return {"resolved_state": state, "value": value}


def product(
    *,
    product_id: int,
    identity_state: str = "known",
    texture_state: str = "unknown",
) -> dict:
    return {
        "product_id": product_id,
        "fields": {
            "product_identity": field(
                identity_state,
                "祖玛珑英国梨与小苍兰",
            ),
            "brand": field("known", "Jo Malone London/祖玛珑"),
            "category": field("known", "香水"),
            "price": field("known", 309.74),
            "texture": field(texture_state),
        },
    }


def test_missing_optional_field_keeps_product() -> None:
    report = build_product_coverage(
        product(product_id=120, texture_state="unknown"),
        profile=CategoryProfile.FRAGRANCE,
    )
    assert report["product_status"] == "retained"
    assert report["fields"]["texture"]["state"] == "unknown"


def test_identity_conflict_quarantines_whole_product() -> None:
    report = build_product_coverage(
        product(product_id=120, identity_state="conflict"),
        profile=CategoryProfile.FRAGRANCE,
    )
    assert report["product_status"] == "quarantine"
```

- [ ] **Step 2: Verify RED**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q tests/guide/tools/test_report_pilot_field_coverage.py
```

Expected: missing module failure.

- [ ] **Step 3: Implement report**

For each target product emit:

```json
{
  "product_id": 120,
  "category_profile": "fragrance",
  "product_status": "retained",
  "core": {
    "identity": "known",
    "brand": "known",
    "category": "known",
    "price": "known"
  },
  "fields": {
    "top_notes": {"state": "unknown", "action": "source_recovery"},
    "longevity": {"state": "unknown", "action": "source_recovery"}
  }
}
```

Rules:

- optional missing/conflict fields never remove a trusted product;
- identity/category/price conflict quarantines the product;
- `action` is one of `keep`, `source_recovery`, `discard_candidate`;
- no raw field value is copied into the report;
- field definitions come from `category_field_registry()`.

Expose `build_product_coverage(product: Mapping[str, object], *,
profile: CategoryProfile) -> dict[str, object]` so the CLI and unit tests use the
same classification path.

- [ ] **Step 4: Generate report**

```bash
PYTHONPATH=. /private/tmp/xiaoro-guide-runtime-venv/bin/python \
  tools/guide_data/report_pilot_field_coverage.py \
  --canonical-manifest data/canonical/core_products_v1_manifest.json \
  --canonical-products data/canonical/core_products_v1.jsonl \
  --category-manifest data/guide_category_facts/category_facts_v1_manifest.json \
  --product-id 38 --product-id 91 \
  --product-id 53 --product-id 57 \
  --product-id 79 --product-id 80 \
  --product-id 86 --product-id 114 \
  --product-id 69 --product-id 103 \
  --product-id 120 --product-id 121 \
  --product-id 42 --product-id 49 --product-id 55 \
  --output docs/audits/guide-closure/data/pilot_field_coverage.json
```

- [ ] **Step 5: Commit**

```bash
git add tools/guide_data/report_pilot_field_coverage.py tests/guide/tools/test_report_pilot_field_coverage.py docs/audits/guide-closure/data/pilot_field_coverage.json
git commit -m "docs(data): report pilot field coverage"
```

## Task 4: Rebuild Pending And Quarantine Queues From Found Sources

**Files:**
- Reuse: `tools/guide_data/build_review_candidates.py`
- Reuse: `tools/guide_data/build_category_fact_candidates.py`
- Create during execution: `/private/tmp/xiaoro-guide-recovered-review-queue/`
- Create during execution: `/private/tmp/xiaoro-guide-recovered-category-queue/`
- Create: `docs/audits/guide-closure/data/candidate_queue_summary.json`
- Test: existing Guide data-tool tests

- [ ] **Step 1: Build source manifests outside Git**

For each found source, create a local manifest using:

```json
{
  "schema_version": "review-candidate-sources-v1",
  "sources": [
    {
      "collected_at": "timestamp from approved source metadata",
      "item_id": "exact bound item ID",
      "path": "relative path under the selected local source root",
      "product_id": 42,
      "sku_id": "exact bound SKU ID"
    }
  ]
}
```

For category data use the existing
`guide-category-source-manifest-v1` schema. Every source entry must contain the
actual byte SHA from inventory.

- [ ] **Step 2: Run review candidate builder only when sources are found**

```bash
PYTHONPATH=. /private/tmp/xiaoro-guide-runtime-venv/bin/python \
  tools/guide_data/build_review_candidates.py \
  --source-manifest /private/tmp/xiaoro-review-source-manifest.json \
  --output-root /private/tmp/xiaoro-guide-recovered-review-queue
```

Expected:

- pending and quarantine JSONL;
- no approved output;
- `provenance_status=historical_reproduced` only when all three locked hashes,
  336 extracted candidates and 111 pending candidates match;
- otherwise `fixture_only` or `source_incomplete`, never a false 336/111 claim.

- [ ] **Step 3: Run category candidate builder for source-backed pilot fields**

```bash
PYTHONPATH=. /private/tmp/xiaoro-guide-runtime-venv/bin/python \
  tools/guide_data/build_category_fact_candidates.py \
  --source-manifest /private/tmp/xiaoro-category-source-manifest.json \
  --canonical-products data/canonical/core_products_v1.jsonl \
  --output /private/tmp/xiaoro-guide-recovered-category-queue/pending.jsonl \
  --quarantine /private/tmp/xiaoro-guide-recovered-category-queue/quarantine.jsonl
```

Expected: pending/quarantine only.

- [ ] **Step 4: Verify queues**

Run:

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/tools/test_build_review_candidates.py \
  tests/guide/tools/test_build_category_fact_candidates.py \
  tests/guide/tools/test_promote_approved_reviews.py \
  tests/guide/tools/test_promote_approved_category_facts.py
```

Expected: PASS.

- [ ] **Step 5: Write aggregate-only queue summary**

`candidate_queue_summary.json` may contain:

- source inventory SHA;
- found/missing locked source counts;
- product IDs;
- extracted/deduplicated/pending/quarantine counts;
- queue SHA values;
- provenance status;
- `automatic_approvals=0`.

It must not contain raw review, OCR text, PII or absolute paths.

- [ ] **Step 6: Commit summary only**

```bash
git add docs/audits/guide-closure/data/candidate_queue_summary.json
git commit -m "docs(data): record recovered candidate queues"
```

Do not commit the local raw sources or candidate queues.

## Task 5: Prove Production Assets Remain Unchanged

**Files:**
- Create: `tests/guide/tools/test_recovery_is_non_promoting.py`
- Modify: `docs/audits/guide-closure/data/source_inventory_summary.md`
- Test: all Guide data-tool suites

- [ ] **Step 1: Write non-promotion assertions**

```python
from hashlib import sha256
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_recovery_does_not_change_production_assets() -> None:
    category = ROOT / "data/guide_category_facts/category_facts_v1_manifest.json"
    reviews = ROOT / "data/guide_review_sources/approved_tmall_feed_reviews_v1.jsonl"
    assert sha256(category.read_bytes()).hexdigest() == (
        "dc528a034779559e0ac9b6444f1b0365e3041478d71ebbc703da3aaaf0e6179c"
    )
    assert sha256(reviews.read_bytes()).hexdigest() == (
        "22bac50e053a621826c831565b3a18e1df3592049ac35377298bac0ab0536171"
    )
```

- [ ] **Step 2: Run data tests**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q tests/guide/tools tests/guide/retrieval
```

Expected: PASS.

- [ ] **Step 3: Run protection gates**

```bash
git diff --exit-code 2199164 -- \
  data/canonical \
  data/guide_category_facts \
  data/guide_review_sources \
  app/guide/decision/deterministic_ranking.py

git diff --check
```

Expected: zero diff.

- [ ] **Step 4: Finalize source summary**

Write exact aggregate values from the committed reports:

```bash
python3 - <<'PY'
import json
from pathlib import Path

root = Path("docs/audits/guide-closure/data")
recovery = json.loads(
    (root / "review_source_recovery.json").read_text(encoding="utf-8")
)
queues = json.loads(
    (root / "candidate_queue_summary.json").read_text(encoding="utf-8")
)
rows = [
    "target_products=15",
    "source_inventory_status=complete",
    f"locked_review_sources_found={recovery['found_count']}",
    f"locked_review_sources_missing={recovery['missing_count']}",
    f"category_pending={queues['category']['pending_count']}",
    f"category_quarantine={queues['category']['quarantine_count']}",
    f"review_pending={queues['review']['pending_count']}",
    f"review_quarantine={queues['review']['quarantine_count']}",
    "automatic_approvals=0",
    "production_fact_count=0",
    "approved_review_sources=6",
]
(root / "source_inventory_summary.md").write_text(
    "# Guide Source Inventory Summary\n\n```text\n"
    + "\n".join(rows)
    + "\n```\n",
    encoding="utf-8",
)
PY
```

- [ ] **Step 5: Commit**

```bash
git add tests/guide/tools/test_recovery_is_non_promoting.py docs/audits/guide-closure/data/source_inventory_summary.md
git commit -m "test(data): prove recovery cannot promote facts"
```
