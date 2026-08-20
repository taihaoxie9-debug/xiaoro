# Task 5 Verifier RED Evidence

## Scope

- Frozen branch: `guide-task5-understanding`
- Frozen HEAD: `5d6cbb6f28f5ba9837b9cff21a46149d4ed72b76`
- Verification type: targeted Task 5 incident evidence only
- Formal full-file audit invoked: no
- Protected baseline aggregate SHA256:
  `dc8b889efe79ec70c5489afb4a5e7d2bc91f98bce11d7fba74ab0e4f6bebe0d3`

The rows below freeze the first contract violation. `not_invoked` means the
upstream typed result correctly or incorrectly stopped the downstream layer;
it is not a downstream failure.

The initial `P1-1` section preserves an earlier interim acceptance criterion
from HEAD `5d6cbb6`. The final review at HEAD `8162cc3` found that allowing a
unique exact topic to continue still guesses the goal. `Final Review P1-A`
therefore supersedes that interim conclusion: ordinary text with
`semantic_required=True` must clarify whenever the provider is unavailable.

## P1-1 Provider Failure Blocks An Authoritative Exact Request

Frozen input: `500元内推荐防晒`, semantic provider unavailable.

| Layer | Frozen output |
| --- | --- |
| exact | `BudgetDraft(maximum=500)`, `CategoryDraft(sunscreen)`, no issue |
| semantic | `None`; provider unavailable |
| context | empty typed `SemanticContext` |
| merger | `goal=clarification`, `topic=sunscreen`, issue `missing_category`; traces `topic/exact_wins`, `semantic/semantic_unavailable` |
| TaskPlan | `mode=clarify`, typed budget/category retained, no required evidence |
| RetrievalResult | `not_invoked` |
| DecisionResult | `not_invoked` |
| ResponsePlan/SSE | typed clarification |
| state | unchanged |

Earliest failure: `app/guide/intent/signal_merger.py`. A unique authoritative
exact topic with no blocking exact issue is converted to clarification solely
because `semantic is None`.

RED nodes:

- `tests/guide/understanding/test_parallel_understanding.py::test_authoritative_exact_request_recommends_when_provider_fails`
- `tests/guide/intent/test_signal_merger.py::test_semantic_unavailable_keeps_simple_authoritative_exact_recommendation`
- `tests/guide/intent/test_signal_merger.py::test_semantic_unavailable_does_not_relax_hard_topic_conflict`

## P1-2 Consultation Recommendation Bypasses Parallel Understanding

Frozen input: a completed consultation session followed by ordinary text whose
topic requires semantic understanding.

| Layer | Frozen output |
| --- | --- |
| exact | no authoritative topic for the semantic paraphrase |
| semantic | not invoked by the consultation recommendation orchestrator |
| context | exact-only implementation ignores the typed context |
| merger | not invoked; `ExactOnlyTextUnderstanding` returns its own result |
| TaskPlan | `mode=clarify` because category is absent |
| RetrievalResult | `not_invoked` |
| DecisionResult | `not_invoked` |
| ResponsePlan/SSE | typed clarification instead of recommendation |
| state | prior consultation/profile state remains unchanged |

Earliest failure: `app/guide_runtime/composition.py`.
`build_consultation_vertical_runtime()` constructs its recommendation
orchestrator without the `TextUnderstandingPort` assembled by
`build_text_understanding()`.

RED nodes:

- `tests/guide/runtime/test_composition_understanding.py::test_consultation_recommendation_uses_injected_parallel_understanding`
- `tests/guide/runtime/test_consultation_vertical_composition.py::test_consultation_followup_ordinary_text_uses_semantic_port`

## P2-1 Confirmed Long-Term Profile Is Missing From SemanticContext

Frozen input: confirmed long-term `skin_type=dry`, then an ordinary
recommendation turn.

| Layer | Frozen output |
| --- | --- |
| exact | current-turn exact constraints only |
| semantic | invoked before `profile_resolver`; receives no confirmed profile field |
| context | `confirmed_profile_fields=()` despite a confirmed `skin_type` |
| merger | cannot observe the closed long-term profile field name |
| TaskPlan | initially has no profile-derived skin constraint |
| RetrievalResult | may still run after the later profile fill |
| DecisionResult | may still use `dry` because `_fill_profile_skin()` calls the resolver after understanding |
| ResponsePlan/SSE | can appear correct, masking the semantic-context contract failure |
| state | successful result may persist `skin=dry` |

Earliest failure: `app/guide/application/text_recommendation_flow.py`.
The existing resolver is called too late and its result is not passed to
`resolve_semantic_context()`.

RED nodes:

- `tests/guide/application/test_text_recommendation_flow.py::test_confirmed_profile_fields_reach_understanding_before_profile_fill`
- `tests/guide/application/test_text_recommendation_flow.py::test_profile_resolver_is_called_once_and_reused_for_profile_fill`

## P2-2 Key Plus Unselected Model Silently Becomes Exact-Only

Frozen environment: `GUIDE_LLM_API_KEY` present,
`GUIDE_LLM_MODEL` absent, no explicitly injected semantic port.

| Layer | Frozen output |
| --- | --- |
| exact | selected as the only understanding lane |
| semantic | silently not assembled |
| context | built but ignored by `ExactOnlyTextUnderstanding` |
| merger | bypassed |
| TaskPlan | depends on exact-only coverage |
| RetrievalResult | may run for literal topics or remain `not_invoked` for semantic paraphrases |
| DecisionResult | follows the incomplete TaskPlan |
| ResponsePlan/SSE | recommendation or clarification varies by literal exact coverage |
| state | may persist an exact-only result |

Earliest failure: `app/guide_runtime/composition.py`.
`not config.is_ready` conflates no Key with Key plus an unselected model, and
the injected-port cache path invents `guide-semantic-fake` as a model identity.

RED nodes:

- `tests/guide/runtime/test_composition_understanding.py::test_key_without_selected_model_fails_closed`
- `tests/guide/runtime/test_composition_understanding.py::test_explicit_semantic_port_needs_no_fabricated_model_identity`

## P2-3 Same-Second Access Does Not Produce True LRU

Frozen sequence with a constant clock and capacity two:

1. put key A;
2. put key B;
3. hit key A;
4. put key C.

| Layer | Frozen output |
| --- | --- |
| exact | not applicable |
| semantic | validated proposals only |
| context | fingerprinted typed context; no plaintext |
| merger | not applicable |
| TaskPlan | not applicable |
| RetrievalResult | not applicable |
| DecisionResult | not applicable |
| ResponsePlan/SSE | not applicable |
| state | all rows keep the same second-level `last_access_epoch`; eviction falls back to fingerprint order and can evict hit key A |

Earliest failure: `app/guide/adapters/llm/intent_cache.py`. Cache access order is
not represented independently from epoch seconds.

RED node:

- `tests/guide/adapters/test_intent_cache.py::test_frozen_clock_hit_updates_monotonic_lru_rank`

## Approved Design 3.7/3.9 Gap: Semantic Acts

Frozen input: `不是不要酒精，我是不要味道太冲`, with a validated semantic
proposal that names `withdraw_constraint` for the closed
`ingredient_exclusion` target.

| Layer | Frozen output |
| --- | --- |
| exact | currently retains `ExclusionDraft(value=酒精)` |
| semantic | schema has no `acts`; the proposed operation cannot be represented |
| context | no pending clarification field |
| merger | cannot detect an attempted hard-constraint withdrawal |
| TaskPlan | can compile the retained exclusion without confirmation |
| RetrievalResult | eligible if a topic is otherwise available |
| DecisionResult | can filter using the still-retained exclusion |
| ResponsePlan/SSE | can present a recommendation without confirming the revision |
| state | a successful recommendation could persist the wrong constraint |

Earliest failures:

1. `app/guide/understanding/semantic_contracts.py` and
   `app/guide/adapters/llm/intent_prompt.py` cannot represent/request the closed
   act.
2. After the contract exists, `app/guide/intent/signal_merger.py` must keep
   exact authority and emit `confirm_hard_constraint_revision` unless exact
   independently confirms the revision.

RED nodes:

- `tests/guide/understanding/test_semantic_intent_contracts.py::test_semantic_acts_are_closed_strict_and_bounded`
- `tests/guide/understanding/test_semantic_intent_contracts.py::test_semantic_act_target_rejects_free_text_ids_numbers_and_facts`
- `tests/guide/adapters/test_intent_prompt.py::test_prompt_requires_closed_acts_without_values_or_facts`
- `tests/guide/adapters/test_siliconflow_intent.py::test_adapter_accepts_legacy_fixture_without_acts`
- `tests/guide/intent/test_signal_merger.py::test_semantic_withdrawal_of_exact_hard_constraint_requires_confirmation`
- `tests/guide/intent/test_signal_merger.py::test_exact_confirmed_hard_revision_remains_authoritative`
- `tests/guide/intent/test_task_planning.py::test_hard_constraint_revision_confirmation_blocks_retrieval`

## Final Review P1-A Frozen Trace

- Frozen HEAD: `8162cc3ca9131e0bfad6190ac852affcbad00a5b`
- Replay type: targeted incident replay only
- Formal full-file audit invoked: no

Primary frozen input: `对比防晒`, semantic provider unavailable.

| Layer | Frozen output |
| --- | --- |
| exact | `CategoryDraft(sunscreen)`, no issue; exact does not own the comparison goal |
| semantic | provider raises; normalized to `None` |
| context | `SemanticContext(version=0, active_topic=None, visible_candidate_count=0, confirmed_profile_fields=())` |
| merger | incorrectly returns `goal=recommendation`, `topic=sunscreen`, no issue; traces `topic/exact_wins`, `semantic/semantic_unavailable` |
| TaskPlan | incorrectly returns `mode=recommend`, category `sunscreen`, required evidence `canonical_product` |
| RetrievalResult | incorrectly invoked; 12 Canonical sunscreen candidates: `26,51,52,53,54,55,56,57,58,101,102,130` |
| DecisionResult | incorrectly invoked; ordered IDs start `55,57,54`, `winner_status=selected` |
| ResponsePlan/SSE | incorrectly emits `decision_process`, `answer_contract`, `products`, `message`, `end` instead of a typed clarification |
| state | incorrectly changes from absent to version 1 with topic `sunscreen` and candidates `55,57,54` |

The same frozen failure was reproduced for all semantic-goal families required
by the incident:

| Input | Intended semantic ownership | Actual merger/response |
| --- | --- | --- |
| `推荐防晒` | recommendation | recommendation + products |
| `对比防晒` | comparison | recommendation + products |
| `防晒适合我吗` | suitability | recommendation + products |
| `防晒有哪些成分` | knowledge | recommendation + products |

Earliest failure: provider failure and caller-authorized semantic skipping share
the same `semantic=None` merger input. The merger therefore cannot distinguish
`semantic unavailable` from `semantic skipped by a protocol-closed typed
operation` and defaults an exact topic to recommendation.

## Final Review P1-B Frozen Trace

- Frozen HEAD: `8162cc3ca9131e0bfad6190ac852affcbad00a5b`
- Replay type: isolated in-memory conversation replay
- Formal full-file audit invoked: no

Frozen setup: the first turn stores a confirmed recommendation context with
`budget_maximum=500`, `topic=sunscreen`, three visible candidates, and
conversation version 1. The second ordinary-language turn has a validated
semantic `revise_constraint(budget)` proposal but no independent exact revision
confirmation.

| Layer | Frozen output |
| --- | --- |
| exact | no constraint and no issue |
| semantic | `goal=recommendation`, `topic=sunscreen`, typed act `revise_constraint(budget)`, confidence `0.99` |
| context | `SemanticContext(version=1, active_topic=sunscreen, visible_candidate_count=3, confirmed_profile_fields=())` |
| merger | incorrectly returns no issue; trace `act.revise_constraint.budget` has `exact_value=absent`, `resolution=exact_wins` |
| TaskPlan | incorrectly returns `mode=recommend`, category `sunscreen`, required evidence `canonical_product`; original budget is absent |
| RetrievalResult | incorrectly invoked for sunscreen |
| DecisionResult | incorrectly invoked and selects products |
| ResponsePlan/SSE | incorrectly emits `decision_process`, `answer_contract`, `products`, `message`, `end` instead of `clarify` |
| state | incorrectly changes version `1 -> 2` and clears `budget_maximum` from `500 -> None` |

Earliest failure: `app/guide/intent/signal_merger.py` treats absence of exact
revision evidence as `exact_wins`. Both `revise_constraint` and
`withdraw_constraint` must instead require independent positive typed exact
confirmation; absence is a blocking
`confirm_hard_constraint_revision` issue.

## Incident P1-C Caller Skip Request Is Mistaken For Authorization

- Frozen HEAD: `676a39e8abf9968c7c0589da2248cef7c3754536`
- Replay type: targeted full-chain disposition replay
- Formal full-file audit invoked: no

Frozen condition: the caller passes `semantic_required=False`, while the exact
lane emits no typed closed-operation proof. The ordinary request has only a
`CategoryDraft(sunscreen)` topic signal.

| Layer | Frozen output |
| --- | --- |
| exact | `CategoryDraft(sunscreen)`, no issue, no `ExactRevisionConfirmation`; no ordinal `ReferenceDraft` |
| semantic | intentionally not invoked; caller supplied `semantic_required=False` |
| context | empty typed `SemanticContext` |
| merger | incorrectly treats `SKIPPED_BY_CONTRACT` as authorization and returns `goal=recommendation`, `topic=sunscreen`, no issue |
| TaskPlan | incorrectly returns `mode=recommend`, required evidence `canonical_product` |
| RetrievalResult | incorrectly eligible instead of `not_invoked` |
| DecisionResult | incorrectly reachable instead of `not_invoked` |
| ResponsePlan/SSE | incorrectly eligible for product delivery instead of typed clarification |
| state | incorrectly eligible to advance after visible cards instead of remaining unchanged |

The failure is independent of the semantic goal family hidden by the skip:

| Input | Exact closed-operation proof | Actual merger/TaskPlan |
| --- | --- | --- |
| `推荐防晒` | none | `recommendation` / `recommend` |
| `对比防晒` | none | `recommendation` / `recommend` |
| `防晒适合我吗` | none | `recommendation` / `recommend` |
| `防晒有哪些成分` | none | `recommendation` / `recommend` |

Control input: `先选择香水，后来改选洁面`. The exact lane emits
`ExactRevisionConfirmation(operation=revise_constraint, target=category,
source_span=...)`; that positive typed proof may authorize only its matching
closed revision path. A budget, ordinary constraint, topic draft, or the
boolean `False` alone is never authorization.

Candidate and image ordinals are already owned by dedicated follow-up/image
parsers before the general recommendation merger. Their exact parser projection
also carries a typed `ReferenceDraft` with `source_span`; the general merger
must remain fail-closed unless such a dedicated path explicitly requires a
skip.

Earliest failures:

1. `app/guide/understanding/parallel_understanding.py` converts the caller's
   boolean request directly into `SKIPPED_BY_CONTRACT` without requiring exact
   lane proof.
2. `app/guide/intent/signal_merger.py` trusts the disposition without
   validating a typed proof with operation, target, and source span.

RED nodes:

- `tests/guide/understanding/test_parallel_understanding.py::test_semantic_skip_without_closed_exact_proof_clarifies`
- `tests/guide/understanding/test_parallel_understanding.py::test_matching_typed_revision_proof_authorizes_semantic_skip`
- `tests/guide/intent/test_signal_merger.py::test_skip_disposition_without_closed_exact_proof_clarifies`
- `tests/guide/intent/test_signal_merger.py::test_skip_disposition_accepts_matching_typed_revision_proof`
- `tests/guide/intent/test_task_planning.py::test_unproved_semantic_skip_blocks_all_downstream_work`

### Incident P1-C RED/GREEN Verification

- Initial RED: `10 failed, 2 passed`. Every failure was the expected
  no-proof or invalid-proof path continuing as recommendation; both matching
  typed revision controls already passed.
- Minimal GREEN for the same nodes plus mismatch coverage: `13 passed`.
- Expanded coordinator skip/control matrix: `9 passed`.
- Complete parallel/merger/TaskPlan suites: `2990 passed`.
- Exact parser, text understanding, and semantic contract regression:
  `842 passed`.
- Frozen Round 9 formal matrix: `112 passed, 131 deselected`.
- Task 5 application/runtime focused suite in a fresh isolated state directory:
  `403 passed`.
- The same focused suite was first run against a reused default SQLite state:
  `10 failed, 393 passed`, all with pre-existing session versions causing
  `ConversationStateConflict`. No code changed for those failures; the required
  fresh-state rerun above passed.
- Fresh isolated Guide full: `6808 passed, 1 warning`. The warning is the
  pre-existing Pydantic `model_name` protected-namespace warning.
- Fresh isolated runtime full: `216 passed`.
- Architecture/import boundaries: `25 passed`; `app.guide` boundary checker
  reported zero violations.
- `compileall`, worktree/cached `git diff --check`, forbidden-path diff, and
  protected-path diff: PASS.
- Protected aggregate SHA256 values remained:
  - Canonical: `ef446aede0dcc0e92be1c8a1ff922154611eb0e11474e5e26d5dc57f2c768d0f`
  - approved reviews: `4a370d27e64d1affa49c03c2ebc21d51f652cdca162626a75249dafc8ce438b7`
  - category facts: `1a3640fe3c40337a5c87bb405a6e6116ae2fd77935ca86b3bf7f5d9e3dfff53c`
  - deterministic ranking: `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`
- Targeted final diff review: `P0=0;P1=0;P2=0`.
- Formal full-file audit invoked for this incident: no.

## Final Verifier P1-D Proof Span Leaves An Open Goal

- Frozen HEAD: `c278a5c27ae607808d1b6e72086510a61b407b9f`
- Replay type: targeted incident replay only
- Formal full-file audit invoked: no

Frozen inputs:

- `后来改选洁面，对比一下`
- `后来改选洁面，适合我吗`
- `后来改选洁面，有哪些成分`

| Layer | Frozen output |
| --- | --- |
| exact | `CategoryDraft(cleanser)`, no issue; one `ExactRevisionConfirmation(revise_constraint, category, span=2:6)` whose slice is only `改选洁面` |
| semantic | intentionally not invoked because the caller supplied `semantic_required=False` |
| context | empty typed `SemanticContext` |
| merger | incorrectly returns `goal=recommendation`, `topic=cleanser`, no issue because it checks proof count, bounds, target type and target presence only |
| TaskPlan | incorrectly returns `mode=recommend`, required evidence `canonical_product` |
| RetrievalResult | incorrectly eligible for cleanser retrieval |
| DecisionResult | incorrectly reachable and able to select a cleanser |
| ResponsePlan/SSE | incorrectly eligible to emit products and a recommendation instead of typed clarification |
| state | incorrectly eligible to advance after product delivery |

The text after the proof span contains the open semantic goals `comparison`,
`suitability` and `knowledge`. A category revision proof cannot authorize any
of those goals, and the merger must not infer recommendation from the topic.

Control input: `后来改选洁面`. The exact parser owns the complete closed
revision clause, so that operation may continue without invoking the semantic
lane. Whitespace and punctuation outside the parser-bound proof do not create
an open goal.

Earliest failures:

1. `app/guide/understanding/exact_parsing.py` projects only the action/target
   span and omits the structurally parsed revision wrapper from its proof span.
2. `app/guide/intent/signal_merger.py` does not require the current-message
   proof to cover all semantic input before authorizing a skip.

RED nodes:

- `tests/guide/understanding/test_parallel_understanding.py::test_closed_revision_with_open_goal_clarifies`
- `tests/guide/understanding/test_parallel_understanding.py::test_pure_closed_revision_control_can_skip_semantic`
- `tests/guide/intent/test_signal_merger.py::test_skip_proof_cannot_authorize_open_goal_suffix`

## Final Verifier P2-D Revision Proof Is Not Bound To The Message

- Frozen HEAD: `c278a5c27ae607808d1b6e72086510a61b407b9f`
- Replay type: direct typed merger replay
- Formal full-file audit invoked: no

Frozen input: current message `后来改选洁面`, with a caller-constructed
`ExactRevisionConfirmation(revise_constraint, category, span=0:2)`.

| Layer | Frozen output |
| --- | --- |
| exact parser replay | the real parser produces a different source span for the category revision |
| supplied proof | operation and target match, but the span slice is not the parser-produced proof for the current message |
| merger | skip path rejects some malformed spans, but semantic-act authorization incorrectly accepts any same-operation/same-target proof; no parser replay binds it to the message |
| TaskPlan | can incorrectly remain `recommend` when the semantic act should require confirmation |
| RetrievalResult | incorrectly eligible |
| DecisionResult | incorrectly reachable |
| ResponsePlan/SSE | incorrectly eligible for product delivery |
| state | incorrectly eligible to commit a revision |

The same defect accepts a stale proof copied from another message and any
in-bounds forged span. Out-of-bounds spans are also unauthorized.

Earliest failure: `app/guide/intent/signal_merger.py`.
`_has_matching_revision_confirmation()` compares only operation and target.
Authorization requires a typed proof whose boundaries and exact slice match
the proof independently reproduced by the exact parser for the current
message.

RED nodes:

- `tests/guide/intent/test_signal_merger.py::test_semantic_act_rejects_unbound_revision_span`

## Final Verifier P2-E Default Profile Pollutes Confirmed Context

- Frozen HEAD: `c278a5c27ae607808d1b6e72086510a61b407b9f`
- Replay type: typed context-resolver replay
- Formal full-file audit invoked: no

Frozen input: `ResolvedProfileContext` contains only
`ResolvedProfileValue(field=skin_type, source=default, provenance=empty)`.

| Layer | Frozen output |
| --- | --- |
| profile contract | correctly distinguishes `default` from current explicit, confirmed session and long-term values |
| ContextResolver | incorrectly maps every known field name, regardless of typed source/provenance, to `ConfirmedProfileField.SKIN_TYPE` |
| semantic context | incorrectly exposes `skin_type` as confirmed |
| semantic provider | can treat an application default as user-confirmed context |
| merger/TaskPlan | can consume a proposal influenced by false confirmation |
| retrieval/decision/presentation | downstream result can appear valid while using polluted semantic context |
| state | unchanged by the resolver itself |

Earliest failure: `app/guide/understanding/context_resolver.py`. Only values
with the profile contract's explicit or confirmed provenance may become
`ConfirmedProfileField`; default values must not enter.

RED node:

- `tests/guide/understanding/test_context_resolver.py::test_default_profile_value_is_not_confirmed`

## Final Verifier P2-F Intent Cache Follows Untrusted Paths

- Frozen HEAD: `c278a5c27ae607808d1b6e72086510a61b407b9f`
- Replay type: isolated filesystem safety replay
- Formal full-file audit invoked: no

Frozen inputs:

- cache database leaf is a symlink to a protected file;
- a cache parent below the trusted root is a directory symlink;
- cache database path is outside the trusted state root.

| Layer | Frozen output |
| --- | --- |
| composition | constructs `IntentProposalCache(state_root / "intent_cache.sqlite3")` without passing trusted-root authority |
| cache path preparation | calls `Path.parent.mkdir()` and then `sqlite3.connect(path)`; no no-follow traversal, regular-file check, ownership check or containment contract |
| SQLite open | follows a database leaf or parent symlink according to normal filesystem resolution |
| cache read/write | can open or mutate a target outside the intended state root |
| conversation state comparison | `SqliteConversationState` rejects these paths and pins the database inode; the intent cache does not |

Earliest failures:

1. `app/guide/adapters/llm/intent_cache.py` has no trusted-root/no-follow
   storage adapter.
2. `app/guide_runtime/composition.py` does not pass the trusted state root.

RED nodes:

- `tests/guide/adapters/test_intent_cache.py::test_cache_rejects_symlink_database_leaf_without_touching_target`
- `tests/guide/adapters/test_intent_cache.py::test_cache_rejects_symlink_parent_below_trusted_root`
- `tests/guide/adapters/test_intent_cache.py::test_cache_rejects_database_outside_trusted_root`
- `tests/guide/adapters/test_intent_cache.py::test_cache_rejects_parent_drift_after_initialization`
- `tests/guide/runtime/test_composition_understanding.py::test_runtime_intent_cache_is_bound_to_state_root`

### Final Verifier Incident RED

- New targeted nodes: `16 failed, 2 passed`.
- P1-D open-goal failures: `6` across coordinator and merger responsibility
  tests.
- P2-D unbound-proof failures: `3`.
- P2-E default-provenance failure: `1`.
- P2-F cache path/composition failures: `6`.
- Controls already passing before production changes: pure closed revision and
  parser-produced current-message revision proof.
- Every failure matched the frozen earliest contract violation; there were no
  collection, fixture or environment errors.

### Final Verifier Incident GREEN

- A second same-layer RED found unpunctuated semantic tails that the first
  clause-wide proof projection over-claimed: `6 failed, 6 passed`.
- The parser now binds a proof to the continuous typed revision structure:
  an exact revision marker, punctuation/whitespace gap, and the parsed
  action/target span. It does not claim the rest of the clause.
- Final open-goal matrix, current-message proof controls and profile RED:
  `14 passed`.
- Intent cache plus composition/cache-hit suite: `17 passed`.
- Shared conversation-state storage regression: `24 passed`.
- Semantic/parallel/cache/context/profile focused suite: `128 passed`.
- Merger/TaskPlan/exact focused suite: `3777 passed`.
- Frozen Round 9 formal matrix: `112 passed, 131 deselected`.
- Application/runtime combined suite in isolated state: `1205 passed`.
- Final isolated Guide full: `6828 passed, 1 warning`. The warning is the
  pre-existing Pydantic `model_name` protected-namespace warning.
- Final isolated runtime full: `217 passed`.
- Architecture/import boundaries: `25 passed`; `app.guide` boundary checker
  reported zero violations.
- `compileall`, worktree/cached `git diff --check`, forbidden-path diff and
  protected-path diff: PASS.
- Protected aggregate SHA256 values remained:
  - Canonical: `ef446aede0dcc0e92be1c8a1ff922154611eb0e11474e5e26d5dc57f2c768d0f`
  - approved reviews: `4a370d27e64d1affa49c03c2ebc21d51f652cdca162626a75249dafc8ce438b7`
  - category facts: `1a3640fe3c40337a5c87bb405a6e6116ae2fd77935ca86b3bf7f5d9e3dfff53c`
  - deterministic ranking: `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`
- Cache and conversation state now share `TrustedSqliteStorage`: trusted-root
  containment, component-wise `O_NOFOLLOW`, private owner/mode checks,
  regular-file enforcement, hard-link inode anchor verification, parent/leaf
  drift rejection and no-follow sidecar hardening. Intent cache remains the
  separate `intent_cache.sqlite3` database, and composition passes the same
  trusted runtime state root explicitly.
- Targeted final diff review: `P0=0;P1=0;P2=0`.
- Formal full-file audit invoked for these findings: no.

## Incident P1-G SQLite Sidecar Replacement TOCTOU

- Frozen HEAD: `6bdcd3a92427ef3e44db5f98e7ba32d67509e173`
- Replay type: deterministic `os.open` replacement probe
- Formal full-file audit invoked: no

Frozen setup:

1. initialize a trusted SQLite database in WAL mode;
2. create an existing `.<database>.inode-wal` sidecar below the trusted
   database parent;
3. enter `TrustedSqliteStorage.secure_database_files()`;
4. allow its no-follow `os.open(..., dir_fd=parent_descriptor)` to return a
   descriptor for the original regular sidecar;
5. before control returns from the patched `os.open`, unlink the directory
   entry and replace it with a symlink to a protected file outside the trusted
   state root.

| Boundary | Frozen output |
| --- | --- |
| trusted parent | opened with `O_DIRECTORY | O_NOFOLLOW`; descriptor remains bound to the original parent |
| sidecar open | `O_NOFOLLOW` opens the original regular `-wal` file and returns its descriptor |
| concurrent replacement | the fixed parent's `-wal` directory entry becomes a symlink after `os.open` returns |
| descriptor validation | `os.fstat(descriptor)` still reports the unlinked original regular inode |
| directory-entry binding | not performed; no `os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)` comparison exists |
| permission hardening | `os.fchmod(descriptor, 0o600)` touches only the stale opened inode |
| function result | incorrectly returns successfully and leaves the replacement symlink in place |
| protected target | unchanged in this probe because the stale FD, rather than the symlink target, receives `fchmod` |
| next SQLite boundary | SQLite still opens the anchor and its `-wal`/`-shm` companions by pathname, so it can encounter the unchecked replacement |

The same missing binding permits an existing sidecar directory entry to be
replaced with a different regular inode after `os.open`. A fixed parent
descriptor alone is also insufficient: if the database parent is renamed and
the original path is replaced while a sidecar FD is being validated, the
descriptor continues to address the moved directory but SQLite's later
pathname open addresses the replacement path.

Existing `connect()` checks `_verify_database_anchor()` immediately before and
after `sqlite3.connect()`. That hard-link proof binds the main database and its
`.inode` anchor only. It neither binds `-wal`/`-shm` entries to opened
descriptors nor carries sidecar identities across SQLite connection and
transaction boundaries. Adding one more point-in-time check would therefore
leave a second check-to-open race and would allow a regular-inode replacement
to become the new unchecked baseline.

Earliest failure:
`app/guide/adapters/state/trusted_sqlite_storage.py`.
Every existing main database, anchor, WAL and SHM entry must be opened relative
to one fixed parent descriptor, immediately rebound to its no-follow directory
entry by device, inode and file type, and checked again after any mutation.
The fixed parent descriptor must also be rebound to the trusted path. SQLite
connection and transaction operations must verify persistent file anchors
before and after each pathname-sensitive boundary so a replacement cannot
silently pass.

RED nodes:

- `tests/guide/adapters/state/test_sqlite_conversation_state.py::test_secure_files_rejects_sidecar_symlink_replacement_after_open`
- `tests/guide/adapters/state/test_sqlite_conversation_state.py::test_secure_files_rejects_sidecar_inode_replacement_after_open`
- `tests/guide/adapters/state/test_sqlite_conversation_state.py::test_secure_files_rejects_parent_drift_after_sidecar_open`

Required controls:

- normal WAL creation and private file modes;
- optimistic CAS with one winner;
- two-process and multi-worker state continuity;
- restart round trips;
- intent-cache reads, writes, expiry and deterministic LRU.

### Incident P1-G RED/GREEN Verification

- Primary deterministic RED: `3 failed`. In every case
  `secure_database_files()` returned without raising after the opened sidecar
  directory entry became a symlink, a different regular inode, or belonged to
  a parent path that had drifted. All failures were the expected
  `DID NOT RAISE`; there were no fixture or environment errors.
- Boundary RED: `2 failed`. Replacing an existing WAL after
  `sqlite3.connect()` returned or from the trace callback inside
  `BEGIN IMMEDIATE` was not detected. Both failures were the expected
  `DID NOT RAISE`.
- The first expanded storage/cache run after adding persistent sidecar anchors
  produced `1 failed, 43 passed`: one of two legitimate worker processes saw
  SQLite's concurrent WAL lifecycle as `state database file anchor changed`.
  The shared trusted-parent `flock` was therefore made exclusive for the
  complete anchor-plus-SQLite path window. CAS remained database-version
  based; the lock only coordinates trusted file lifecycle.
- Final five attack nodes plus WAL/CAS/cache controls: `8 passed`.
- Complete `SqliteConversationState` and intent-cache suites: `44 passed`.
- All state adapters plus intent cache: `174 passed`.
- Cross-worker text state: `20 passed`.
- Independent process probes:
  - 2 workers: one `saved`, one `conflict`;
  - 4 workers: one `saved`, three `conflict`.
- Terminal-delivery boundary matrix: `34 passed`.
- Semantic adapter/parallel-understanding intent smoke: `119 passed`.
- Final storage/cache/cross-worker rerun: `64 passed`.
- Isolated Guide non-runtime full: `6616 passed, 1 warning`.
- Isolated runtime full: `217 passed`.
- Final isolated Guide full including runtime: `6833 passed, 1 warning`.
- The warning is the pre-existing Pydantic `model_name`
  protected-namespace warning.
- Architecture/import boundaries: `25 passed`.
- `compileall`, worktree and cached `git diff --check`, forbidden-path diff
  and protected-path diff: PASS.
- Protected aggregate SHA256 values remained:
  - Canonical:
    `ef446aede0dcc0e92be1c8a1ff922154611eb0e11474e5e26d5dc57f2c768d0f`
  - approved reviews:
    `4a370d27e64d1affa49c03c2ebc21d51f652cdca162626a75249dafc8ce438b7`
  - category facts:
    `1a3640fe3c40337a5c87bb405a6e6116ae2fd77935ca86b3bf7f5d9e3dfff53c`
  - deterministic ranking:
    `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`
- The shared adapter now binds the main database, inode hard-link, WAL and SHM
  entries to descriptors opened relative to one fixed parent descriptor. It
  compares no-follow directory-entry type/device/inode before permission
  mutation and again afterward, rebinds the parent descriptor to the trusted
  path, and carries the anchors across SQLite connect, execute, transaction,
  commit and rollback boundaries. Normal SQLite sidecar deletion is accepted
  only after connection close; a sidecar still present then must retain its
  anchored identity.
- Targeted changed-files review: `P0=0;P1=0;P2=0`.
- Formal full-file audit invoked for this incident: no.
