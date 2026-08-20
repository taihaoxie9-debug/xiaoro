# Phase 2 Audit Idempotency and Agent Token Telemetry Design

## Status

Approved direction, written specification pending final user review.

## Problem

The continuous Phase 2 workflow currently combines workstream review,
review-fix verification, integration-owner inspection, resume-time adoption
checks, and final full-file review. These checks have no shared idempotency key.
As a result, identical file content may be audited again after cherry-pick,
context recovery, or agent restart.

The existing token ledger records only cumulative Goal tokens. It does not
record input, output, cache-read, or cache-write tokens. Historical cache usage
therefore cannot be reconstructed honestly, and project cost cannot be
calculated without provider usage and pricing data.

## Goals

1. Run at most one full-file audit at the beginning of each capability loop.
2. Reuse an existing audit result when file blobs and the audit profile are
   identical, even if branch or commit SHA differs.
3. Verify fixes with RED/GREEN tests and normal gates instead of repeating
   full-file audits inside the same loop.
4. Preserve exactly one independent full-file audit for final Phase 2 closure.
5. Prevent unavailable auditors or an absent user from stopping unrelated work.
6. Prevent duplicate cherry-picks and semantically duplicate integration
   commits.
7. Record Agent token cache telemetry and cost inputs when the platform exposes
   them, while marking unavailable historical fields explicitly.

## Non-Goals

- No application runtime behavior changes.
- No changes under `app/services`, `app/database`, or `data/canonical`.
- No attempt to infer historical cache hits from total token usage.
- No estimated cost without an identified model, a dated price source, and
  provider usage fields.
- No removal of focused tests, boundary checks, HTTP checks, browser gates, or
  the final independent audit.

## Capability Loop Identity

Every implementation loop has:

- `capability_key`: stable capability name, such as
  `consultation-profile-vertical`;
- `iteration_id`: unique execution attempt for that capability;
- `base_tree`: Git tree or worktree snapshot at loop start;
- `scope_paths`: sorted production files included in the opening audit;
- `audit_profile_version`: versioned review dimensions and severity policy.

A loop must not create a new `iteration_id` merely to repeat an audit. A new
iteration is allowed only after the previous capability loop is closed or the
objective and owned scope materially change.

## Audit Key

The audit key is independent of commit SHA:

```text
audit_key = sha256(
  audit_profile_version
  + sorted(scope_path + NUL + file_blob_sha256)
)
```

The audit ledger is append-only. A prior PASS with the same `audit_key` is an
audit cache hit and must be reused across worktrees, cherry-picks, rebases, and
session resumes.

Commit SHA, branch name, worktree path, and iteration ID are recorded as
provenance but do not invalidate an otherwise identical audit key.

## Per-Loop Audit State Machine

### Start

1. Freeze `capability_key`, `iteration_id`, scope, and blob manifest.
2. Compute `audit_key`.
3. Look up the append-only audit ledger.
4. If the key already has PASS, record `REUSED_PASS` and do not invoke an
   auditor.
5. Otherwise run one opening full-file audit and record its result.

### Implementation

Confirmed findings become failing tests before production fixes. After editing,
run:

- targeted RED/GREEN tests;
- affected focused regression;
- `app/guide` and `app/guide_runtime` boundaries;
- `git diff --check`;
- required HTTP and browser gates.

Do not run another full-file audit in the same capability loop. A fix for an
opening audit finding is verified by its regression and gates.

### Auditor Unavailable

An auditor failure is recorded once per `audit_key`. The same loop must not
retry the same unavailable auditor repeatedly.

The main execution thread performs one bounded baseline inspection, records
`LOCAL_BASELINE_ONLY`, and continues the capability and all independent
workstreams. This status cannot satisfy the final independent audit, but it
must not wait for the user or stop unrelated work.

### Close

Close the loop only after the required tests and vertical gates pass. Record
the final blob manifest and integration evidence. Do not perform a second
full-file audit.

## Final Audit

After all capabilities are integrated, open one distinct
`FINAL-PHASE2-AUDIT` iteration. It performs exactly one independent full-file
audit over the final production blob manifest.

Confirmed findings receive RED tests and fixes. Fix verification reruns the
affected tests and complete final gates, not another full-file audit. If fixes
materially alter the final audited scope, the final report records the changed
blob manifest and test evidence; it does not create an audit retry loop.

## Duplicate Commit Prevention

Before integration, compute:

- stable patch ID for the candidate commit;
- sorted final production blob manifest;
- capability key and source commit provenance.

If the same stable patch ID or equivalent final blob manifest is already
integrated, record `INTEGRATION_REUSED` and do not cherry-pick, amend, or create
another equivalent commit.

Documentation-only checkpoint commits remain allowed when they append new
evidence. They must not restate an existing checkpoint under a new commit.

## Audit Ledger

Create:

`docs/audits/phase2-continuous/audit_ledger.csv`

Required columns:

```text
timestamp
goal_id
capability_key
iteration_id
audit_key
audit_profile_version
scope_manifest_sha256
source_commit
result
reused_from_audit_key
finding_counts
evidence_path
notes
```

Allowed results:

```text
PASS
REUSED_PASS
LOCAL_BASELINE_ONLY
BLOCKED
FINAL_PASS
```

`audit_key + result event` entries are append-only. Reuse records may repeat the
key as provenance, but only one real auditor invocation may exist for a key.

## Agent Token Ledger

Create:

`docs/audits/phase2-continuous/agent_token_usage.csv`

Required columns:

```text
timestamp
goal_id
iteration_id
event
cumulative_tokens
prompt_tokens_total
prompt_uncached_tokens
cache_read_tokens
cache_write_tokens
output_tokens
cache_hit_rate
model
pricing_snapshot
estimated_cost
telemetry_source
status
```

The normalized cache hit rate is:

```text
cache_read_tokens / (cache_read_tokens + prompt_uncached_tokens)
```

It is calculated only when both fields are available from the same provider
usage record.

Cost is calculated only when:

1. the exact model is known;
2. input, output, cache-read, and cache-write usage semantics are known;
3. the dated pricing snapshot is recorded.

Otherwise `cache_hit_rate` or `estimated_cost` is `UNAVAILABLE`.

The historical Slice 1.7-2.0 Goal retains its authoritative total of
`26,788,605` tokens. Its cache and cost breakdown fields are recorded as
`UNAVAILABLE`; no assumed hit rate is added.

## Checkpoint Rules

At every capability checkpoint:

1. query the available Goal/provider usage telemetry;
2. append one token row;
3. append one audit reuse/invocation row if audit state changed;
4. append the normal progress entry;
5. continue to the next runnable task.

Missing cache telemetry is not a workflow blocker. It is recorded as
`UNAVAILABLE` and execution continues.

## Files to Update

- `.trae/specs/complete-phase2-continuously/spec.md`
- `.trae/specs/complete-phase2-continuously/tasks.md`
- `.trae/specs/complete-phase2-continuously/checklist.md`
- `.trae/specs/complete-phase2-continuously/progress.md`
- `docs/superpowers/plans/2026-08-09-phase2-continuous-ralph.md`

Files to create:

- `docs/audits/phase2-continuous/audit_ledger.csv`
- `docs/audits/phase2-continuous/agent_token_usage.csv`
- `docs/superpowers/prompts/2026-08-09-phase2-continuous-resume.md`

## Acceptance Criteria

- The authoritative spec says one opening full-file audit per capability loop.
- Repeated full-file audits inside one loop are explicitly forbidden.
- Same audit blobs/profile reuse prior PASS across commit SHA changes.
- Review fixes use RED/GREEN and gates without a re-audit loop.
- Final Phase 2 has exactly one independent full-file audit iteration.
- Auditor unavailability is recorded once and does not stop independent work.
- Equivalent patch IDs/blob manifests do not create duplicate commits.
- Both ledgers have fixed schemas and append-only rules.
- Historical cache telemetry is marked `UNAVAILABLE`.
- The resume prompt enforces these rules before continuing existing worktrees.

## Risks and Controls

- **Risk: reduced review coverage after a fix.**
  Control: every confirmed finding requires a RED regression, and final closure
  retains one independent audit.
- **Risk: false audit cache hit.**
  Control: the key includes every scoped file blob and the audit profile
  version.
- **Risk: capability loops are renamed to bypass the one-audit rule.**
  Control: stable `capability_key` is separate from `iteration_id`, and scope
  expansion must be recorded.
- **Risk: misleading cost reporting.**
  Control: missing telemetry or pricing produces `UNAVAILABLE`, never a guessed
  value.
