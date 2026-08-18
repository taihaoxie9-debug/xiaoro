# Guide Three-Track Handoff

- status: INCOMPLETE
- code_source_commit: `3ebcb0f9e633e40c4ab8b80ab2ea0a19df4f869a`
- branch: `rebuild`
- required_ancestor: `c7fef22` present
- guide_entrypoint: `app.guide_runtime.app:app`
- public_message_owner: Guide
- public_stream_owner: Guide
- legacy_fallback_count: 0
- legacy_importer_count: 0
- formal_audit_invocations: 1
- formal_audit_repeats: 0

## Guide And Legacy Removal

- The default runtime and compatibility export resolve to Guide.
- V1/V2 Agent, Intent, Presenter, conversation owner, old chat route, and
  dedicated background importer are physically deleted.
- The deletion changed 52 files and removed 26,560 lines.
- Independent verification: PASS with P0/P1/P2 equal to 0.
- Post-deletion inventory: direct/dynamic/string/runtime/test/script/
  background/total all equal to 0.

## Two-Stage Intent

- route/detail contracts, short prompts, staged cache, shared repair budget,
  proposal projection, exact parallelism, and the single merger are present.
- Offline smoke: route `32/32`; detail `26/26`.
- Selected model: none.
- Runtime mode without a validated provider result: fail-closed clarification.
- Real current-contract V4-Flash/V3.2 A/B: NOT RUN because
  `GUIDE_LLM_API_KEY` is missing.
- Required 95% route, 90% detail, and zero unsafe TaskPlan gates therefore
  remain unavailable.

## Pilot Data

- Product IDs covered: `38,42,49,53,55,57,69,79,80,86,91,103,114,120,121`.
- Seed product rows: 15.
- Field status rows: 201.
- known/pending/quarantine/unknown: `89/7/19/86`.
- Locked HTML: found `3`, missing `0`, duplicate `0`.
- Locked source report SHA:
  `6819dadb23ed38540f24f0849cfec82c4db3a816f23c4a35310b285172f915ae`.
- Historical `336/111`: NOT REPRODUCED.
- Data verifier consensus PASS candidates: 0.
- Decisions/signatures/promotion invocations/production facts: `0/0/0/0`.

## Verification

- Task 11 collect: 6,894 tests.
- Task 11 targeted: 19 passed.
- State/cross-worker/SSE: 58 passed.
- Focused execution: 5,079 passed, 1 environment-isolation failure.
- compileall: PASS.
- `app/guide` boundary: 0 violations.
- `app/guide_runtime` boundary: 0 violations.
- diff check: PASS.
- protected Canonical, ranking, and six approved reviews: unchanged.
- browser matrix: NOT RUN after two `browser_runner.output_io` failures.
- Guide full/runtime full/all tests: NOT GREEN because the authoritative
  test environments split required dependencies.
- residual pytest/Uvicorn/Playwright/A-B processes: 0.

## Release Boundary

- not pushed
- not deployed
- no production traffic switch
- no data promotion

The closure must not be marked COMPLETE until the current two-stage real A/B,
full test environment, and browser matrix are all green.
