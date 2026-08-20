# Continuous Conversation Acceptance Design

Date: 2026-08-17

Repository: `/Users/bytedance/Desktop/xiaoro-fresh`

Branch: `rebuild`

Status: Approved for planning

## 1. Decision

The previous Unified Router closure is retained as component-level evidence,
but it is no longer sufficient for product-readiness.

Product-readiness now requires:

1. twenty independent conversations;
2. five real sequential turns per conversation;
3. state produced by each turn becoming the next turn's actual input;
4. earliest-distortion diagnosis inside the 100-turn backend gate;
5. public answer validation with the copywriter disabled;
6. three complete random conversations, fifteen turns total, rendered through
   the browser for final experience acceptance.

The browser sample is not where semantic, routing, binding, or state failures
are first diagnosed. Those failures must already be visible and classified
by the backend gate.

## 2. Why The Previous Evidence Was Insufficient

The previous blind batches measured individual turns, often from constructed
starting snapshots. They proved that many current-turn translations, routes,
bindings, state transitions, and card projections were correct. They did not
prove that five real turns could build and preserve the same state without
drift.

The browser matrix injected reviewed presentation fixtures. It proved layout,
cards, images, streaming behavior, and responsive rendering. It did not prove
that the real backend's public `message` text was natural or free of internal
language.

The live five-turn probe exposed this gap:

- an internal concept ID appeared in public copy;
- `Canonical` appeared in a public suitability answer;
- a basic general-knowledge question had no covered answer;
- returning to the earlier second product after a knowledge detour clarified
  instead of restoring focus;
- product-knowledge fallback was thin and used recommendation-like framing.

These are acceptance-design failures, not reasons to add phrase-specific
patches.

## 3. Authority Boundaries

The existing architecture remains authoritative:

- the semantic model translates open user language once per turn;
- semantic admission verifies source-bound meaning;
- Canonical identity and controlled aliases bind products and variants;
- Unified Router selects the processor and continuity;
- `FocusState`, `SessionProfile`, `PendingTurn`, and conversation snapshots
  own state;
- retrieval and decision code own evidence, safety, eligibility, and order;
- presentation code owns all public copy and cards.

The new gate observes these boundaries. It does not move responsibilities
between them.

## 4. Backend Gate: 20 Conversations By 5 Turns

### 4.1 Conversation construction

Create exactly twenty independent trajectories. Every trajectory:

- starts with an empty session;
- has exactly five natural user turns;
- uses one stable session ID and owner;
- consumes the real committed snapshot from the previous turn;
- includes at least one continuation, correction, reference, or mode switch;
- is frozen before provider execution;
- is not a simple paraphrase of another trajectory.

The twenty trajectories collectively cover:

- recommendation and condition revision;
- product knowledge and focused follow-up;
- general knowledge and return to prior product focus;
- comparison with two or three products;
- dynamic consultation, correction, confirmation, and exit;
- session-profile projection and other-person isolation;
- image identity, suitability, similarity, and image comparison;
- clarification, no-match, and safety escalation;
- `PendingTurn`, withdrawal, replacement, and budget changes.

### 4.2 Runtime configuration

For the broad backend gate:

```text
real TurnMeaning provider: enabled
semantic calls: exactly 100
copywriter: disabled
copywriter calls: 0
format repair or retry: 0
```

The deterministic fallback is part of the production contract. It must be
safe and usable without relying on model polishing.

### 4.3 Per-turn capture

Every turn records:

```text
user message
starting snapshot and hashes
semantic context
raw provider output
semantic admission outcomes
product and reference bindings
route and continuity
state transition
TaskPlan
retrieval and data-support result
card IDs and specifications
presentation contract
public message events
terminal snapshot and hashes
```

### 4.4 Per-turn evaluation

Each turn freezes acceptable:

- semantic meaning;
- product and image bindings;
- processor, continuity, and focus source;
- allowed state changes;
- task mode and constraints;
- card IDs;
- clarification and safety behavior;
- public answer duties.

Public answer duties include:

- no internal protocol, concept, field, or audit language;
- no unrelated recommendation framing in product knowledge;
- no stale or unrelated cards;
- no answer claiming unavailable evidence;
- a natural, direct explanation when evidence is missing;
- a useful answer when reviewed evidence exists;
- no contradiction between `message`, presentation sections, and cards.

## 5. Earliest-Distortion Diagnosis

Every failed turn receives exactly one earliest layer:

1. `model_translation`
2. `semantic_admission`
3. `identity_binding`
4. `route_selection`
5. `state_transition`
6. `decision_execution`
7. `data_coverage`
8. `public_presentation`

Diagnosis occurs during the `20 x 5` backend gate. A failure cannot be
deferred to browser testing.

Examples:

- "return to the earlier second product" is not fixed with a phrase branch;
  translation, reference admission, stored focus, and route priority are
  inspected in order;
- `Canonical` is not removed with final string replacement; public contracts
  must not receive internal vocabulary;
- a missing ingredient comparison is not fixed by hard-coding one answer;
  reviewed knowledge coverage and generic unsupported-answer behavior are
  inspected;
- a missing SKU specification is not parsed from the product name; reviewed
  product or variant projection is fixed.

## 6. General-Fix Rule

A fix is acceptable only when it changes the responsible boundary and is
proved by a failing test first.

Phrase-specific matching is allowed only for genuinely closed protocol
vocabulary such as explicit ordinals, enum values, and version identifiers.
Open natural-language meaning cannot be repaired by adding one observed
sentence or synonym to a keyword table.

For each failure:

1. preserve the raw turn, provider output, and state;
2. reproduce the earliest layer under TDD;
3. determine whether the responsibility or data contract is wrong;
4. implement the smallest general correction;
5. replay every previously captured trajectory without API calls;
6. continue with unseen trajectories only after prior evidence is green.

## 7. Backend Acceptance

First-pass qualification:

```text
complete-trajectory success >= 18 / 20
```

A trajectory passes only when all five turns pass.

Zero-tolerance counters:

```text
wrong product or image binding = 0
unauthorized state transition = 0
hard-condition override = 0
unsafe downgrade = 0
cross-session or cross-subject leakage = 0
internal public-language leakage = 0
stale-focus hijack = 0
```

After fixes, all one hundred captured turns must replay `100 / 100` on the
current code with zero provider and copywriter calls.

## 8. Browser Acceptance: 3 Conversations By 5 Turns

After the backend gate passes, select three complete trajectories using a
frozen random seed from the eligible backend set:

```text
3 conversations x 5 turns = 15 browser turns
```

Selection happens before viewing rendered results. The three trajectories
must collectively include:

- a cross-mode product-focus return;
- a dynamic consultation or session-profile transition;
- an image or comparison flow.

The browser runtime reuses captured TurnMeaning outputs, avoiding duplicate
semantic calls. The real copywriter may be enabled for these fifteen turns
only:

```text
additional semantic calls = 0
maximum copywriter calls = 15
```

The same captured SSE is rendered at desktop `1440x900` and mobile
`390x844`, without additional model calls.

All fifteen turns must pass:

- correct streaming and thinking-panel lifecycle;
- correct public copy and section duties;
- correct inline and bottom cards;
- no stale cards after mode switches;
- comparison table behavior;
- no internal terms;
- no image failure, overflow, overlap, or clipped text;
- no console or relevant network error.

Browser acceptance is a presentation and integration sample. It does not
replace backend diagnosis.

## 9. API Budget

Development fixes use fake or captured semantic outputs.

The real-model budget is:

```text
backend qualification: 100 semantic calls, once
backend repair replays: 0 calls
browser acceptance: 0 semantic calls, at most 15 copywriter calls
```

No provider rerun occurs after a code fix unless captured replay cannot
represent the changed semantic contract. Any proposed extra real call must be
reported before execution.

## 10. Timebox

Target: one to two hours.

Expected allocation:

```text
gate and fixture contracts: 20-30 minutes
known focus/public-copy fixes: 30-45 minutes
20 x 5 execution and diagnosis: 15-30 minutes
browser 3 x 5 and closure: 20-30 minutes
```

This estimate assumes the live probe exposed boundary defects rather than a
new orchestration design failure. The timebox cannot override the no-patch
rule. A new architecture-level defect is reported and fixed correctly even
if that exceeds two hours.

## 11. Exit Criteria

The new closure is complete only when:

1. the twenty five-turn trajectories are frozen before execution;
2. every backend failure has an earliest layer;
3. first-pass complete-trajectory success is at least 18/20;
4. all zero-tolerance counters are zero;
5. captured current-code replay is 100/100;
6. deterministic fallback public copy is usable and leak-free;
7. three random complete conversations render 15/15 in desktop and mobile;
8. focused and full pytest pass without a new warning category;
9. closure evidence records hashes, API calls, failures, fixes, and rollback;
10. no production deployment occurs.
