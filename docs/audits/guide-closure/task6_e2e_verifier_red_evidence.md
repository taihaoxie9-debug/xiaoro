# Task 6 E2E RED Evidence

## Scope And Provenance

- implementation baseline:
  `cf77738d33f7442072f00e1f01403dcd84796300`
- rejected candidate:
  `e3e123a3199c0366b322762a2ebafc7dfaa4e600`
- authoritative read-only report:
  `/private/tmp/xiaoro-task6-e3e-authoritative-e3e123a/report.md`
- frozen cases:
  `tests/fixtures/guide/intent/semantic_intent_ab_v1.jsonl`
- candidate RED source:
  `4511f23e5877abd572d55615fd9468baf761272a`
- formal full-file audit invocations in this worktree: `0`
- new audit key: `none`
- network/provider/key use: `none`

This document freezes targeted RED/GREEN evidence only. It is not a formal
audit and does not change the existing audit ledger, tasks, checklist, or
progress.

## Frozen Production RED

The authoritative probe used real `build_runtime_orchestrator`, SQLite state,
Canonical assets, and production `TextRecommendationOrchestrator.stream()`.
For the 14 constructible open-semantic cases below:

```text
semantic_invocations=0/14
expected_semantic_invocations=14/14
wrong_card_cases=7/14
legacy_fallbacks=0
```

The earliest routing failure was the pre-understanding operation dispatcher.
`parse_followup()` used an unanchored ordinal search and discarded the rest of
the message. Unsupported budget/skin/followup drafts could also pre-route
non-closed messages before `ParallelUnderstanding`.

Legend:

- `S`: frozen expected semantic `goal/topic/reference`
- `M`: merger result from the same validated proposal
- `T`: pre-fix TaskPlan result
- `R/D`: retrieval/decision actually reached by the pre-router
- `E`: production SSE summary
- `State`: authoritative SQLite state transition

| Case | Exact | S | M | T | R/D | E | State |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `assess-011-candidate-ordinal` | candidate ordinal 2 | assessment/serum/candidate 2 | assessment/serum, no issue | clarify | followup selected ordinal 2 | card events | v2 -> v3 |
| `assess-013-pronoun-current` | none | assessment/skincare/current topic | assessment/skincare, no issue | clarify | not reached | typed clarify | v2 unchanged |
| `clar-015-revision-missing-target` | none | clarification/sunscreen | clarification/sunscreen, missing goal | clarify | not reached | typed clarify | v2 unchanged |
| `cmp-010-candidate-ordinals` | ambiguous candidate ordinals | comparison/serum/candidates 1,2 | comparison/serum, ambiguous reference | clarify | followup selected ordinal 1 | card events | v3 -> v4 |
| `cmp-012-pronoun-second` | candidate ordinal 2 | comparison/fragrance/candidate 2 + current topic | comparison/fragrance, no issue | clarify | followup selected ordinal 2 | card events | v3 -> v4 |
| `follow-007-pronoun-it` | none | followup/cleanser/current topic | followup/cleanser, no issue | recommend | not reached | typed clarify | v3 unchanged |
| `follow-009-budget-revision` | exclude alcohol; unsupported budget format | followup/sunscreen/current topic; revise budget | followup/sunscreen, exact issue + unconfirmed revision | clarify | not reached | typed clarify | v3 unchanged |
| `follow-011-skin-revision` | skin oily-sensitive | followup/base makeup/current topic; revise skin | followup/base makeup, unconfirmed revision | clarify | not reached | typed clarify | v3 unchanged |
| `follow-012-alcohol-followup` | candidate 2; exclude alcohol | followup/serum/candidate 2 | followup/serum, no issue | clarify | followup selected ordinal 2 | card events | v3 -> v4 |
| `follow-015-injection-winner` | candidate ordinal 2 | followup/sunscreen/candidate 2 | followup/sunscreen, no issue | recommend | followup selected ordinal 2 | card events | v3 -> v4 |
| `know-012-candidate-reference` | candidate ordinal 2 | knowledge/sunscreen/candidate 2 | knowledge/sunscreen, no issue | clarify | followup selected ordinal 2 | card events | v2 -> v3 |
| `suit-009-budget-fit` | none | suitability/serum/current topic | suitability/serum, no issue | clarify | not reached | typed clarify | v2 unchanged |
| `suit-011-candidate-ordinal` | candidate ordinal 3 | suitability/serum/candidate 3 | suitability/serum, no issue | clarify | followup selected ordinal 3 | card events | v3 -> v4 |
| `suit-014-revision-skin` | skin oily-sensitive | suitability/serum/current topic; revise skin | suitability/serum, unconfirmed revision | clarify | not reached | typed clarify | v4 unchanged |

The seven wrong-card cases are therefore frozen as:

```text
assess-011-candidate-ordinal
cmp-010-candidate-ordinals
cmp-012-pronoun-second
follow-012-alcohol-followup
follow-015-injection-winner
know-012-candidate-reference
suit-011-candidate-ordinal
```

`follow-015-injection-winner` exposes the next earliest layer after routing:
an open semantic `FOLLOWUP` proposal was compiled as a fresh recommendation.
Because only the closed operation dispatcher owns executable ordinal followup,
semantic followup must fail closed instead of selecting a new batch.

## Closed, Missing, And Unconstructible Contexts

- `follow-001-second-candidate` and `follow-002-first-candidate` are accepted
  only when the typed operation source span covers the complete message.
- `clar-004-low-info-question` uses real empty state; no candidate snapshot is
  fabricated.
- `follow-004-fourth-candidate` and `follow-014-revision-to-third` declare four
  visible candidates, while production `ConversationSnapshot` permits three.
  They remain typed `UNCONSTRUCTIBLE`; the gate does not widen production state
  or alter the fixture.
- image-state cases require image authority and are not represented by a text
  recommendation snapshot.

## Model Vertical RED Boundary

The rejected candidate's `stream_text_vertical()` is accepted only as a
model-isolation API. It must consume all 128 validated proposals exactly once
through real exact, merger, TaskPlan, Guide retrieval, decision, presentation,
and SSE. It cannot satisfy production-routing status and the production gate
must never call it.

Additional frozen RED nodes:

1. clarify plus any `CardDisplayContractEvent` is a wrong selection;
2. evaluator exception makes all dependent hard fields `UNAVAILABLE`;
3. stable semantic hash excludes latency and usage;
4. preloaded legacy calls in newly created threads must be observed;
5. both `sys` and `threading` profiles plus `sys.meta_path` must be restored on
   normal, concurrent, and partial-install-failure paths;
6. real adapter usage must come from the same HTTP/validation request;
7. missing key exits 2 with no output directory or stdout/stderr.

## Candidate Acceptance

| Candidate commit | Decision |
| --- | --- |
| `6243fe4` | reject; mixed independent planning with production pre-router |
| `4511f23` | selectively replay model vertical, CardDisplay, availability, and observer concepts |
| `84676ea` | independently replay typed proposal + usage single-request contract |
| `e3e123a` | replay cleanup principle, extended to both sys and threading hooks |

No candidate stack was cherry-picked.
