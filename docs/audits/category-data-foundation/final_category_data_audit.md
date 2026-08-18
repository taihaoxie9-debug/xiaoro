# FINAL-CATEGORY-DATA-AUDIT

## Identity

- Audit profile: `final-category-data-audit-v1`
- Frozen source commit:
  `59833501223213991cb37ba765e5b9ac42cae7d9`
- Frozen production files: `41`
- Scope manifest SHA-256:
  `ed8de1ff252b477ef7ba559ac3e19212be6967ccf1efd27fcb1238aafe0e905b`
- Scope status: historical malformed-scope evidence. The original requested
  path list named a nonexistent review reader and materialized only 41 files.
- Audit key:
  `1b3611b13ef377099ee008cdbcb30f950797fadc09d4b025a0fb24f44c6181c7`
- Full-file audit invocations for this key: `1`
- Auditor mode: independent and read-only

## Opening Result

`P0=0;P1=1;P2=1`

1. `P1`: `tools/guide_data/promote_approved_reviews.py` accepted
   human-looking decision metadata without an externally locked decision
   digest and detached HMAC. Coordinated candidate and decision rewrites
   could therefore fabricate approval.
2. `P2`: the review source JSONL, audit Markdown, and manifest were replaced
   sequentially. An unlocked reader could observe a fail-closed mixed
   generation, and interruption could leave the asset unavailable until a
   later promotion recovered it.

The opening audit result was `FINDINGS`, not an initial PASS.

## RED And Fix

- RED result: `28 failed, 1 passed`.
- Single-writer source fix:
  `a4d7a6b665a70fbd63ae7ece4f0d17e3723aa33e`.
- Patch-equivalent integration fix:
  `4206f45f5b0c4738c2592dc4d0115f947266132b`.
- Stable patch ID:
  `4fdc2344f10a48ec7905131fa661f80e1645d2a1`.

The fix requires an external decisions SHA-256 and detached HMAC for every
non-empty approval batch. The signature binds the locked candidate manifest
and canonical decision manifest; the CLI reads the key only through a named
environment variable.

Review sources and audit records are now immutable generations. Both are
installed and validated before a single atomic `os.replace` switches the
stable manifest pointer. Before that switch, readers load the old complete
generation; after it, readers load the new complete generation. Symlink,
path traversal, missing generation, and conflicting-generation cases fail
closed.

## Targeted Clearance

The audit key above was not invoked again. A separate targeted read-only
verifier inspected only the two confirmed findings and reported:

```text
TARGETED-VERIFICATION: PASS
P0=0;P1=0;P2=0
80 passed
```

The implementation writer's broader focused and review regressions reported
`117 passed`; main-branch post-integration focused verification reported
`120 passed`.

## Task 24 Scope Correction

The historical 41-file manifest, its audit key, and its ledger row remain
unchanged. They are retained as malformed-scope evidence rather than
rewritten as a corrected audit.

The corrected frozen scope at the same source checkpoint is:

```text
source_commit=59833501223213991cb37ba765e5b9ac42cae7d9
production_files=42
scope_manifest_sha256=9bd6fbef8072acfb770af95bdcead537a11e0c262ee85092c859ae177bdb14e1
audit_key=d88c16831e176cbc4b3445294a1d9fddf6ffcfd97eeafe3e04f451c1e595114e
review_reader_path=app/guide/retrieval/review_reader.py
review_reader_git_blob=4db1174c053b3fcb33aa1b7f4da9122969433467
review_reader_file_sha256=2d15d42a5e5224567e930527abde2570741b0c13083790115d607fd8e1194a32
```

The corrected path follows the production reference chain:

```text
app/guide_runtime/composition.py
-> build_review_evidence_reader
-> load_approved_review_assets
-> ReviewEvidenceReader
-> text and image recommendation flows
```

An independent read-only auditor inspected the frozen reader and its runtime
reference chain. The targeted result was:

```text
TARGETED-READER-VERIFICATION: PASS
98 passed
P0=0;P1=0;P2=0
full_file_invocations=0
targeted_reader_invocations=1
```

No full-file audit was repeated for either the historical or corrected key.

## Normal Gates After Fix

- Guide full: `2511 passed`, one pre-existing Pydantic namespace warning
- Runtime full: `155 passed`
- Compileall: PASS
- `app/guide` boundary: PASS
- `app/guide_runtime` boundary: PASS
- Protected diff: empty
- Ranking SHA-256:
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`
- Browser matrix: `7/7` PASS
- Page, console, SSE, HTTP 5xx, failed image, cross-session, late-event,
  and XSS errors: `0`

## Final Disposition

`FINDINGS_CLEARED`

There are no unresolved P0-P2 findings. The unique final full-file audit was
not repeated after the fix or the Task 24 scope correction.
