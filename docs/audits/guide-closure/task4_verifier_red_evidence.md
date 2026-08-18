# Task4 Verifier Finding RED Evidence

## Frozen Input

- branch: `guide-task4-merger`
- base commit: `142f80e227ccbe7abf61b196ab7905d965f3f7a6`
- verifier worktree:
  `/private/tmp/xiaoro-task4-final-verifier.H87oTN/worktree`
- formal audit invocations: `0` for this finding repair

## RED Command

```bash
PYTHONDONTWRITEBYTECODE=1 \
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/intent/test_signal_merger.py::test_reference_kind_has_one_authority_across_full_pipeline \
  tests/guide/intent/test_signal_merger.py::test_nested_ingredient_does_not_drop_negative_selection_event \
  tests/guide/intent/test_signal_merger.py::test_typed_revision_replaces_only_prior_positive_topic \
  tests/guide/intent/test_signal_merger.py::test_modal_and_action_boundary_fail_closed_across_full_pipeline
```

Observed before production edits: `17 failed, 1 passed`. The passing case was
the preserved ordinary coordination contract `香水和洁面 -> clarify`.

## Full-Pipeline Failure Records

### Exact candidate ordinal 2 versus semantic ordinal 3

| Layer | Frozen output |
| --- | --- |
| exact | `candidate_ordinal=2`, source span `0:3` |
| semantic | `candidate_ordinal=3`, confidence `0.95` |
| merger | references `[2, 3]`; no reference trace |
| TaskPlan | mode `recommend`; references `[2, 3]` |
| RetrievalResult | `eligible` |
| DecisionResult | `pending_retrieval` |
| ResponsePlan/SSE | `pending_evidence` |
| conversation state | `eligible_after_visible_cards` |

Earliest failed contract: `IntentSignalMerger` grouped references by
`(kind, ordinal)` rather than assigning one authority per reference kind.

### `不选择酒精香水`

| Layer | Frozen output |
| --- | --- |
| exact | category `fragrance`; exclusions `[]`; issues `[]`; selection events `[]` |
| semantic | topic `fragrance`, confidence `0.95` |
| merger | topic `fragrance`; trace `topic=agree`; no issues |
| TaskPlan | mode `recommend`; category `fragrance`; exclusions `[]` |
| RetrievalResult | `eligible` |
| DecisionResult | `pending_retrieval` |
| ResponsePlan/SSE | `pending_evidence` |
| conversation state | `eligible_after_visible_cards` |

Earliest failed contract: exact event binding dropped the whole selection
event when an ingredient token appeared between the action and category.

### `先选择香水，最后改选洁面`

| Layer | Frozen output |
| --- | --- |
| exact | categories `[]`; issues `[ambiguous_category]` |
| semantic | topic `cleanser`, confidence `0.95` |
| merger | topic `null`; resolution `clarify` |
| TaskPlan | mode `clarify`; no category |
| RetrievalResult | `not_invoked` |
| DecisionResult | `not_invoked` |
| ResponsePlan/SSE | `typed_clarification` |
| conversation state | `unchanged` |

Earliest failed contract: exact lexer/event composition had no typed revision
marker or revision action property, so both positive topics survived.

### `可能不选择香水`

| Layer | Frozen output |
| --- | --- |
| exact | categories `[]`; issues `[]`; hard exclusion `fragrance` |
| semantic | topic `fragrance`, confidence `0.95` |
| merger | topic `null`; resolution `exact_wins` |
| TaskPlan | mode `clarify` |
| RetrievalResult | `not_invoked` |
| DecisionResult | `not_invoked` |
| ResponsePlan/SSE | `typed_clarification` |
| conversation state | `unchanged` |

Earliest failed contract: `可能` was not a typed modal token and therefore did
not make the selection operator stack uncertain.

### `没有负担的防晒`

| Layer | Frozen output |
| --- | --- |
| exact | categories `[]`; issues `[ambiguous_category]`; synthetic event count `1` |
| semantic | topic `sunscreen`, confidence `0.95` |
| merger | topic `null`; resolution `clarify` |
| TaskPlan | mode `clarify` |
| RetrievalResult | `not_invoked` |
| DecisionResult | `not_invoked` |
| ResponsePlan/SSE | `typed_clarification` |
| conversation state | `unchanged` |

Earliest failed contract: the no-action operator path synthesized a selection
event from `没有` alone.

## GREEN Verification

- Four new parameterized nodes: `18 passed`.
- Generated structural matrix: `127 passed`.
- Changed focused suite: `1477 passed`.
- Tasks 26-32 exact/TaskPlan/API/decision core: `1156 passed`,
  `408 deselected`.
- Round 9 formal matrix: `112 passed`, `131 deselected`.
- Fresh-state formal HTTP suite: `243 passed`.
- Fresh-state Guide full: `4162 passed`, with one pre-existing Pydantic
  protected-namespace warning for `model_name`.
- Fresh-state runtime full: `189 passed`.
- `app/guide` boundary: zero violations.
- `app/guide_runtime` boundary: zero violations.
- `compileall`: exit `0`.
- `git diff --check`: exit `0`.
- Complete verifier sentences in production source: zero matches.
- Protected Canonical, approved review, and deterministic ranking paths:
  no diff from `142f80e`.
- Deterministic ranking SHA256:
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`.
- Formal audit invocations added by this repair: `0`.

An initial non-fresh formal run reused fixed session IDs and produced ten
`ConversationStateConflict` failures. No changed Task4 file appeared in those
stacks. The required isolated-state rerun is the `243 passed` result above.

## 2026-08-11 Exact Parser P1 Incident RED

### Frozen Input

- branch: `guide-task4-merger`
- incident base commit:
  `5e75533761bf1950f0a00e106054b3814fa0e119`
- writer worktree: `/private/tmp/xiaoro-guide-task4`
- worktree before reproduction: clean
- formal audit invocations: `0` for this incident repair

The records below were captured from the real exact parser, semantic proposal,
single merger, and TaskPlan on the frozen incident base before any test or
production edit.

### A. Signed range accepted as a positive budget

Representative integer input: `预算 - 100到200元推荐香水`.
The decimal variant `预算 - 100.5到200.75元推荐香水` followed the same
incorrect path with a positive `100.5..200.75` range.

| Layer | Frozen output |
| --- | --- |
| exact | `BudgetDraft(minimum=100, maximum=200)`; category `fragrance`; issues `[]` |
| semantic | goal `recommendation`; topic `fragrance`; confidence `0.95` |
| merger | topic `fragrance`; no uncertainty; trace `topic=agree`, `goal=semantic_fills` |
| TaskPlan | mode `recommend`; positive budget range `100..200`; category `fragrance` |
| RetrievalResult | `eligible` |
| DecisionResult | `pending_retrieval` |
| ResponsePlan/SSE | `pending_evidence` |
| conversation state | `eligible_after_visible_cards` |

Earliest failed contract: the exact budget parser searched for an unsigned
range before checking a spaced leading sign. The range lookbehind inspected
the space immediately before `100`, so the preceding `-` did not prevent a
positive match.

### B. Sentence terminator treated as category-list punctuation

Input: `不要香水。防晒`.

| Layer | Frozen output |
| --- | --- |
| exact | selection events `negative fragrance`, `negative sunscreen`, both with clause text `不要香水。防晒`; constraints `[]`; issues `[]` |
| semantic | goal `recommendation`; topic `sunscreen`; confidence `0.95` |
| merger | topic `null`; issue `ambiguous_category`; trace `topic=exact_wins` with exact value `excluded:sunscreen` |
| TaskPlan | mode `clarify`; no category or exclusion constraint |
| RetrievalResult | `not_invoked` |
| DecisionResult | `not_invoked` |
| ResponsePlan/SSE | `typed_clarification` |
| conversation state | `unchanged` |

Earliest failed contract: exact clause composition treated every punctuation
boundary between two category tokens as a continued category list. The full
stop was therefore ignored and the first clause's negative action captured the
new sentence's `防晒` target.

### C. Grouped amount truncated at the first separator

Representative input: `预算1,000元推荐防晒`. The full-width separator input
`预算1，000元推荐防晒` produced the same output.

| Layer | Frozen output |
| --- | --- |
| exact | `BudgetDraft(minimum=null, maximum=1)`; category `sunscreen`; issues `[]` |
| semantic | goal `recommendation`; topic `sunscreen`; confidence `0.95` |
| merger | topic `sunscreen`; no uncertainty; trace `topic=agree`, `goal=semantic_fills` |
| TaskPlan | mode `recommend`; budget maximum `1`; category `sunscreen` |
| RetrievalResult | `eligible` |
| DecisionResult | `pending_retrieval` |
| ResponsePlan/SSE | `pending_evidence` |
| conversation state | `eligible_after_visible_cards` |

Earliest failed contract: the exact numeric grammar accepted the ungrouped
prefix `1` as a complete budget before the comma. It neither owned nor
validated the remaining grouped digits, so an amount of 1000 silently became
1.

### General RED Matrix

| Typed grammar dimension | RED representatives | Required typed result |
| --- | --- | --- |
| signed integer or decimal range | `预算 - 100到200元`, `预算 - 100.5到200.75元`, including Unicode/full-width minus | no positive `BudgetDraft`; `invalid_budget`; TaskPlan `clarify` |
| terminal clause punctuation | `不要香水。防晒`, plus terminal ASCII/full-width sentence punctuation | first exclusion remains scoped to `fragrance`; new explicit topic is `sunscreen`; no inherited exclusion |
| category-list punctuation | `不要香水，防晒`, `不要香水、防晒` | both categories remain targets of the same explicit negative selection |
| negative withdrawal inheritance | `先选择香水。最后不考虑了` and existing separator matrix | active target still crosses a clause boundary for an explicit targetless negative withdrawal |
| valid grouped integers | `1,000`, `1，000`, full-width digits, and common space-grouped forms | one normalized finite decimal value `1000`, never a numeric prefix |
| valid grouped decimals | `1,000.50` and full-width equivalent | one normalized finite decimal value `1000.50` |
| malformed or ambiguous grouping | incomplete groups, mixed separators, comma-decimal forms such as `1,5` | no partial budget; `invalid_budget`; TaskPlan `clarify` |

The repair boundary is limited to typed numeric lexing/validation and typed
clause composition in `app/guide/understanding/exact_parsing.py`. Merger,
TaskPlan, retrieval, decision, response, API, Presenter, and state consumers
must remain unchanged.
