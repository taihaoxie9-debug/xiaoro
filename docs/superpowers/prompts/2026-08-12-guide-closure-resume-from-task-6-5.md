# Guide Closure Resume From Task 6.5

Use the following prompt to continue the current Guide closure program:

```text
/ralph-loop

Continue only in:

/Users/bytedance/Desktop/xiaoro-fresh

Target branch:

rebuild

Do not implement in `/Users/bytedance/Desktop/xiaoro-shopping-master`. That is
the old dirty workspace and is read-only except for previously approved source
inventory work.

## 1. Current checkpoint

Treat these as facts to verify, not work to repeat:

- `270a73a7d94426e25c116ae8b50cc01f264eeff8` or a reviewed strict successor is
  the minimum legal checkpoint.
- Tasks 1-5, 7, 9 and 10 are complete.
- Task 6.1-6.4d is complete.
- Task 6.5-6.7 and Tasks 8, 11, 12 and 13 are incomplete.
- The two targeted major findings are already fixed in `5b295bb`.
- The authoritative remaining execution plan is:
  `docs/superpowers/plans/2026-08-12-guide-closure-remaining-execution.md`.
- The checkpoint design is:
  `docs/superpowers/specs/2026-08-12-guide-closure-loop-prompt-design.md`.

Do not rerun completed tasks.

## 2. Exactly one formal audit

The user's rule is: audit once at the beginning, never repeat it.

That opening formal audit has already happened:

- profile: `guide-closure-full-file-v1`
- audit key:
  `b874c83c4f79b594a80de475b9a353755b27a9b90e7dd03a743e392aad40d0da`
- authoritative ledger:
  `docs/audits/guide-closure/audit_ledger.csv`
- real invocations: `1`
- repeat invocations: `0`

At every resume, read the ledger and verify this identity. Never invoke another
formal full-file audit, create another audit key, run a capability audit, run a
final audit, or rename a repeated audit as review/recheck.
Do not ask the user to perform, review or approve an audit. The single opening
audit is already complete; once this loop starts, automatically execute all
unblocked remaining work.

Allowed verification:

- changed-files targeted review;
- RED/GREEN;
- focused/full/runtime tests;
- compileall and boundary checks;
- dependency inventory;
- frozen SHA verification;
- cross-worker and browser gates.

These are verifications, not formal audits.

## 3. Start-of-run guard

Before implementation:

1. Verify branch, HEAD ancestry and `git status`.
2. Do not reset, restore, checkout, stash, clean or overwrite user changes.
3. Read spec/tasks/checklist/progress and the remaining execution plan.
4. Verify the audit ledger has one row and invocation remains 1.
5. Check for pytest, Playwright, Uvicorn and A/B runner processes.
6. Check only whether `GUIDE_LLM_API_KEY` is PRESENT or MISSING. Never read,
   print, search, log or persist its value.

If files changed since the checkpoint, classify each change before acting.
Work with legitimate changes; do not revert them.

## 4. Missing-Key stop rule

If `GUIDE_LLM_API_KEY=MISSING`:

- report once that a fresh Key is the only current hard prerequisite;
- report current HEAD, worktree status, audit invocation 1/repeat 0 and absence
  or presence of residual processes;
- do not run tests, network requests, browser gates or implementation;
- do not enter Task 8;
- do not append another repetitive blocker Round to progress;
- do not create an empty commit;
- terminate this loop run.

Do not poll forever. Run this same Prompt again after the fresh Key is present.

## 5. Key-present execution order

If `GUIDE_LLM_API_KEY=PRESENT`, execute
`docs/superpowers/plans/2026-08-12-guide-closure-remaining-execution.md`
task by task:

1. Task 6.5: run the frozen V4-Flash/V3.2 real A/B.
2. Task 6.6-6.7: prove all hard counts are AVAILABLE and zero, then record the
   mechanical model selection.
3. Task 8: persist bounded clarification state and switch all default public
   launchers/routes to Guide.
4. Task 11: inventory all static/dynamic/runtime/test/script/background legacy
   importers, reach zero runtime importers, then physically delete the old chat
   chain with `git rm`.
5. Task 12: run bounded focused/full/runtime/all-tests/model/state/browser and
   protected-asset gates.
6. Task 13: write final handoff, reconcile tasks/checklist, verify clean state.

Dependencies are strict:

- no passing real model -> no Task 8;
- Task 8 not fully green -> no Task 11 deletion;
- runtime/background importers nonzero -> no legacy deletion;
- Task 11 incomplete -> no final closure;
- tasks/checklist not fully evidenced -> never mark COMPLETE.

## 6. Repair discipline

For every failure, freeze the input and inspect:

exact
-> semantic proposal
-> merger trace
-> TaskPlan
-> RetrievalResult
-> DecisionResult
-> ResponsePlan/SSE
-> conversation state

The first violated typed contract owns the RED and the fix.

Never:

- add a full-sentence keyword/regex patch for one fixture;
- reinterpret intent in API, Presenter or frontend;
- filter/rank/select a winner again in retrieval or presentation;
- change expected data to hide production drift;
- add a test-only production bypass;
- patch, wrap or copy the old `app/services/**` chat chain;
- use UNAVAILABLE, `None` or constant zero as a hard-gate PASS;
- modify Canonical, deterministic ranking or approved review data.

If both real models fail, allow at most three generalizable
prompt/schema/context/merger repair loops. If still failing, record NO-GO and
keep typed clarification; do not cut over.

## 7. Long-process control

- Run at most one heavy process at a time.
- Send a concise status heartbeat every 30 seconds.
- On 30 seconds without useful output, inspect the OS process before waiting.
- Give every long process a hard timeout.
- On timeout, send TERM, wait briefly, send KILL only if necessary, then prove
  the PID exited.
- Do not start another broad test while one is running.
- Diagnose one failure with the smallest focused test, not another full suite.
- Do not leave completed agents or child processes marked running.

## 8. Agent and writer control

Start in INCIDENT mode after the Key becomes present:

- root orchestrator: 1;
- fixer/writer: at most 1;
- independent read-only verifier: 1;
- integration writer: at most 1;
- one writer per file authority.

Only expand after two consecutive green checkpoints with non-overlapping file
domains. On contract conflict, legacy fallback, state leakage, hard-constraint
override, protected-asset drift or verifier disagreement, return immediately
to 1 fixer + 1 verifier.

One frozen SHA and one file scope have only one authoritative verifier.

## 9. Checkpoint evidence

For each real checkpoint record:

- task/subtask;
- source and integration SHA;
- RED and earliest failing layer;
- focused/full/runtime/boundary/browser results actually run;
- model/prompt/schema/usage/latency/cost status;
- all hard-gate counts;
- audit key, invocation 1, repeat 0;
- protected hashes;
- remaining dependency and next task.

Do not let progress/tasks/checklist run ahead of code or evidence.

## 10. Completion boundary

Mark COMPLETE only when:

- a real default model passed all hard gates;
- hard override, forbidden-to-TaskPlan, wrong selection and legacy fallback
  are all zero;
- bounded clarification state works across workers and resets on success;
- default launchers and public message/stream are Guide-only;
- old Agent, Presenter, intent and old route dependencies are physically
  deleted;
- runtime importers are zero;
- focused/full/runtime/all-tests/model/state/browser gates pass;
- Canonical 103, ranking SHA and six approved reviews are unchanged;
- audit invocation remains 1 and repeat remains 0;
- tasks/checklist are fully evidenced;
- worktree is clean;
- nothing was pushed, deployed or switched to production traffic.

Do not wait for routine checkpoint approval. Stop only for the explicit
external/destructive conditions in the remaining execution plan.
```
