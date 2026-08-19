# Phase 2 Review Source Audit

## Current Conclusion

- Audit date: 2026-08-09
- Audit locator:
  `docs/audits/phase2-scenario-feedback/review_source_audit.md`
- Catalog ID: `phase2-approved-tmall-feed-reviews`
- Catalog version:
  `approved-tmall-feed-reviews-v1:sha256:22bac50e053a621826c831565b3a18e1df3592049ac35377298bac0ab0536171`
- Approved review source count: `6`
- Approved product count: `3`
- Approved product coverage: products `42`, `49`, and `55`, with exactly
  `2` approved sources per product

The current approved catalog is the six-record Tmall feed review asset. Each
record has a stable review source ID derived only from the Tmall item ID, the
complete original HTML SHA-256, and its 1-based page ordinal. The feed ID is
auxiliary locator metadata and does not participate in source identity. Each
record also has Canonical product ownership, a source-verifiable locator,
verbatim content, collection metadata, and content hashes. The manifest's
`audit_locator` resolves to this document, so this section is the current
conclusion for that catalog.

<!-- current-approved-catalog:start -->
```json
{"approved_product_count":3,"approved_product_counts":{"42":2,"49":2,"55":2},"approved_source_count":6,"audit_locator":"docs/audits/phase2-scenario-feedback/review_source_audit.md","catalog_id":"phase2-approved-tmall-feed-reviews","catalog_version":"approved-tmall-feed-reviews-v1:sha256:22bac50e053a621826c831565b3a18e1df3592049ac35377298bac0ab0536171","manifest_file":"data/guide_review_sources/approved_tmall_feed_reviews_v1_manifest.json","manifest_file_sha256":"2d4acdb1251e1b65d2b92fb2b052734f58b56cd4cd558e783c0391432c630460","manifest_file_sha256_semantics":"raw-file-bytes:includes-manifest_sha256:includes-trailing-newline","manifest_sha256":"823c249166e93b4ab709b3423fa8a97a23e3ab3e7677e5d39d74abc21c165113","manifest_sha256_semantics":"canonical-json:exclude-manifest_sha256:utf-8:sorted-keys:compact:no-trailing-newline","sources_file":"data/guide_review_sources/approved_tmall_feed_reviews_v1.jsonl","sources_sha256":"22bac50e053a621826c831565b3a18e1df3592049ac35377298bac0ab0536171"}
```
<!-- current-approved-catalog:end -->

## Current Asset Results

| Product | Approved stable source IDs and auxiliary feeds | Product binding |
| --- | --- | --- |
| `42` | `review_tmall_item_998532090974_html_b31206098d6839257e5dd29c1fae71495b067029568763d9a726b16fc47fd3e4_ordinal_00000001` (feed `1303713936059`); `review_tmall_item_998532090974_html_b31206098d6839257e5dd29c1fae71495b067029568763d9a726b16fc47fd3e4_ordinal_00000002` (feed `1307660701413`) | item `998532090974`, SKU `6153782938028`, HTML SHA-256 `b31206098d6839257e5dd29c1fae71495b067029568763d9a726b16fc47fd3e4` |
| `49` | `review_tmall_item_525332729369_html_55996a2a8207e65eb434fa376d61dc0f34d5621f51f9c3754e2369021d9a7f44_ordinal_00000001` (feed `1306554487880`); `review_tmall_item_525332729369_html_55996a2a8207e65eb434fa376d61dc0f34d5621f51f9c3754e2369021d9a7f44_ordinal_00000002` (feed `1308815628363`) | item `525332729369`, SKU `5214914101911`, HTML SHA-256 `55996a2a8207e65eb434fa376d61dc0f34d5621f51f9c3754e2369021d9a7f44` |
| `55` | `review_tmall_item_746513552108_html_56719aa64a4222a961b2ea118cf51415f25c4f88560e5de83172adc8e9c13783_ordinal_00000001` (feed `1307612064428`); `review_tmall_item_746513552108_html_56719aa64a4222a961b2ea118cf51415f25c4f88560e5de83172adc8e9c13783_ordinal_00000002` (feed `1305316624545`) | item `746513552108`, SKU `5318505666088`, HTML SHA-256 `56719aa64a4222a961b2ea118cf51415f25c4f88560e5de83172adc8e9c13783` |

The source asset raw-file SHA-256 is
`22bac50e053a621826c831565b3a18e1df3592049ac35377298bac0ab0536171`
and is embedded in `catalog_version`. The manifest's logical SHA-256 is
`823c249166e93b4ab709b3423fa8a97a23e3ab3e7677e5d39d74abc21c165113`;
it is computed over UTF-8 canonical compact JSON with sorted keys, excluding
`manifest_sha256`, with no trailing newline. The raw manifest file includes
the self-hash field and a trailing newline, so its byte-level SHA-256 is the
intentionally different
`2d4acdb1251e1b65d2b92fb2b052734f58b56cd4cd558e783c0391432c630460`.

## Current Reproduction

```bash
shasum -a 256 \
  data/guide_review_sources/approved_tmall_feed_reviews_v1.jsonl \
  data/guide_review_sources/approved_tmall_feed_reviews_v1_manifest.json
PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
import hashlib
import json
from pathlib import Path

path = Path(
    "data/guide_review_sources/"
    "approved_tmall_feed_reviews_v1_manifest.json"
)
manifest = json.loads(path.read_text(encoding="utf-8"))
unsigned = {
    key: value
    for key, value in manifest.items()
    if key != "manifest_sha256"
}
canonical = json.dumps(
    unsigned,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
print("manifest logical", hashlib.sha256(canonical).hexdigest())
print("manifest embedded", manifest["manifest_sha256"])
print("manifest raw", hashlib.sha256(path.read_bytes()).hexdigest())
PY
PYTHONPATH=. /Library/Frameworks/Python.framework/Versions/3.11/bin/python3 \
  -m pytest -c pytest-guide.ini -q \
  tests/guide/retrieval/test_approved_review_assets.py
```

The mechanical test resolves the manifest's `audit_locator`, validates this
document's current JSON block against the loaded production catalog, checks
the six records and `42:2`, `49:2`, `55:2` coverage, and verifies both source
and manifest hash semantics. The stable-ID tests also verify exact-duplicate
idempotency, conflicting-record rejection, cross-product rejection, and that
feed IDs remain auxiliary locator metadata.

## Historical Pre-Reconstruction Baseline (`approved=0`)

- Historical audit date: 2026-08-09
- Historical code baseline:
  `6123c7bf26056375a12f50ba22d2c8e6a0faf141`
- Historical catalog ID: `phase2-review-source-audit`
- Historical catalog version: `git-6123c7b-assets-v1`
- Approved review source count: `0`

This is the explicitly historical source-discovery baseline from before the
approved Tmall feed review asset was reconstructed. It remains useful for
showing why the pre-existing aggregate, mixed, and editorial assets were
rejected, but it is not the current approved catalog conclusion.

### Historical Asset Results

| Asset | Structured result | Review evidence decision |
| --- | --- | --- |
| `data/seed_dump.sql` | No review/comment table; 103 product rows contain `user_review_notes`, but no `source_id` or `review_id` | Rejected: mixed marketing, Q&A, cross-SKU page text, and review snippets cannot be separated or located per review |
| `products.rating` / `products.review_count` | Aggregate product columns only | Rejected: no review text or per-review provenance |
| `data/canonical/shadow_review_v1/review_decisions.jsonl` | 1,234 field-review decisions; two are `user_signal` | Rejected as review sources: these are audit summaries, and their evidence IDs do not resolve to original review records with source locators |
| Canonical and shadow-review manifests | Counts and content hashes only | Rejected: manifests prove asset integrity but do not contain original review records |
| `data/canonical/core_products_v1.jsonl` | Canonical field values and source refs only | Rejected: no original review record or independently verifiable review excerpt |
| `data/beauty_products_seed.json` | Product catalog metadata and manually checked product sources | Rejected: no per-review records |
| `data/knowledge_docs/*.md` | 22 editorial knowledge documents | Rejected: knowledge content is not consumer review evidence |

The two `user_signal` decisions are:

- product 117, finish signal, one unresolved evidence ID;
- product 68, texture signal, two evidence IDs that appear as Canonical field
  refs but have no original source record or locator in the repository.

Neither can support a positive review summary.

### Historical Reproduction

```bash
rg -n -i '^CREATE TABLE|^COPY public\.' data/seed_dump.sql
rg -n -i \
  '^CREATE TABLE public\.[A-Za-z0-9_]*(review|comment)|^COPY public\.[A-Za-z0-9_]*(review|comment)' \
  data/seed_dump.sql
rg -o '"source_id"' data/seed_dump.sql data/beauty_products_seed.json \
  data/canonical --glob '*.json' --glob '*.jsonl' --glob '*.sql' | wc -l
rg -o '"review_id"' data/seed_dump.sql data/beauty_products_seed.json \
  data/canonical --glob '*.json' --glob '*.jsonl' --glob '*.sql' | wc -l
rg -o 'user_review_notes' data/seed_dump.sql | wc -l
wc -l data/canonical/shadow_review_v1/review_decisions.jsonl
jq -c 'select(.status == "user_signal")' \
  data/canonical/shadow_review_v1/review_decisions.jsonl | wc -l
find data/knowledge_docs -type f | wc -l
shasum -a 256 \
  data/seed_dump.sql \
  data/beauty_products_seed.json \
  data/canonical/core_products_v1.jsonl \
  data/canonical/core_products_v1_manifest.json \
  data/canonical/shadow_review_v1/review_decisions.jsonl \
  data/canonical/shadow_review_v1/review_decisions_manifest.json
find data/knowledge_docs -type f -print0 | sort -z | \
  xargs -0 shasum -a 256 | shasum -a 256
```

Observed counts:

```text
review/comment tables: 0
source_id keys: 0
review_id keys: 0
mixed user_review_notes fields: 103
shadow review decisions: 1234
user_signal decisions: 2
approved review sources: 0
```

Audited asset hashes:

```text
seed_dump.sql
  ae45bbb513868619e578f63f252fff549ad62289aba0d474e2ae65aa754bc386
beauty_products_seed.json
  d89463c42a24e5d2b22adeb7b617f4fe13c89387736f88267936bcb6ed64dc74
core_products_v1.jsonl
  0ba95df8c38d39f5bc0d73a32c318b157903abb64778c3e7b0acebfb75e95734
core_products_v1_manifest.json
  e0430a244af451a3fa73642295c4a79128e1622dfeed19ff8140eda9f2df0c69
review_decisions.jsonl
  12b0e1f82df3509ad8886af68a04ddcc62b28f3d3a5c72f4496ea22708fe50e9
review_decisions_manifest.json
  999be8b3238176ed57cab47d2fa7db30ed76a2840908bc9c2d52c06a3ec7f633
knowledge_docs aggregate
  9a4eaacd6a88f996c52db8c68f1df4e713f4fdcc8a856d6798b1cf02f555101a
```

## Consequence

Products `42`, `49`, and `55` now have approved, auditable review evidence
and may use the positive review-summary path subject to the existing
evidence contracts. Products outside that set remain fail-closed with
verified absence. The historical rejected assets remain unapproved and
cannot be substituted for the six-record catalog.
