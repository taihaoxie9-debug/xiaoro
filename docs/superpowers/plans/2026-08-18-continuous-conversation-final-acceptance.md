# Continuous Conversation Final Acceptance Implementation Plan

> **Superseded for execution on 2026-08-19:** The remaining unchecked steps
> in this document are replaced by
> `docs/superpowers/plans/2026-08-19-overnight-final-acceptance.md`.
> This file remains architecture and historical evidence only.

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. The main agent may dispatch read-only or isolated sub-agents for parallel evidence collection, but the main agent must personally review every responsibility decision, production edit, real-API run, and final acceptance result. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the Unified Router multi-turn mixed conversation chain with truthful layer-by-layer diagnosis, real semantic and copywriter qualification, an independent `20 x 5` blind exam, and three real five-turn browser trajectories using the approved G inline card.

**Architecture:** Keep the current "model translates, code judges" architecture. The model reduces unlimited user phrasing to finite semantic parent concepts; code validates source grounding, maps each parent concept to finite Canonical data concepts, executes typed state transitions, and judges product evidence. Repair only the earliest incorrect boundary: semantic context/prompt, source admission, Canonical/image binding, Unified Router, state commit, processor execution, data coverage, presentation contract, or browser renderer. Images remain context and identity inputs to the normal recommendation, product-knowledge, suitability, and comparison processors rather than a separate thin answer system.

**Tech Stack:** Python 3.11, Pydantic v2, FastAPI, SQLite CAS conversation state, typed SSE, DeepSeek/SiliconFlow-compatible JSON providers, pytest, Node.js DOM contract tests, Playwright Chromium.

---

## 1. Authority And Scope

Repository:

```text
/Users/bytedance/Desktop/xiaoro-fresh
```

Branch:

```text
rebuild
```

`/Users/bytedance/Desktop/xiaoro-shopping-master` is reference-only. Do not
edit or run the old v2 presenter as the acceptance runtime.

This plan supersedes the execution details in:

```text
docs/superpowers/plans/2026-08-17-continuous-conversation-closure.md
```

It retains the approved architecture in:

```text
docs/superpowers/specs/2026-08-17-continuous-conversation-acceptance-design.md
docs/superpowers/specs/2026-08-16-guide-presentation-final-alignment-design.md
```

The worktree is intentionally dirty. Do not use:

```text
git reset
git checkout
git stash
```

Do not commit unless the user explicitly asks for a commit. Use audit
artifacts, hashes, focused tests, and `git diff --check` as checkpoints.

### Self-only acceptance amendment (2026-08-18)

The user narrowed the final product and acceptance scope to the current user.
This amendment supersedes every third-person, friend, roommate, colleague,
partner, sibling, parent, gift-recipient, or subject-switch requirement later
in this plan.

The final fixed, blind, and browser qualifications must therefore satisfy:

```text
every trajectory subject_scope = self
every turn evaluates the current user's own need, skin state, or product task
subject_scope_hint acceptance = self or unknown
no paid call is spent on another person's profile or recommendation
```

Existing third-person captures remain immutable diagnostic evidence and their
calls remain in cumulative accounting, but they do not count toward final
qualification. Before the next provider call:

1. reselect the fixed 20 from self-only reviewed pool trajectories;
2. rewrite the six unconsumed blind-pool third-person trajectories as
   self-only trajectories while preserving their five-turn business duties;
3. regenerate fixed, blind A, and blind B manifests and hashes;
4. validate message uniqueness, fixed/blind disjointness, product facts,
   budgets, image ordinals, routes, and state duties at zero API.

Cross-session leakage and state corruption remain zero-tolerance failures.
The existing cross-subject instrumentation may remain in code, but deliberate
third-person isolation is no longer an acceptance target.

### Semantic Parent-Concept And Anti-Patch Amendment (2026-08-18)

This amendment governs every remaining semantic repair and supersedes any
local strategy that recognizes one user wording in order to fix one fixture.

The required path is:

```text
unlimited user wording
  -> model translates to a finite semantic parent concept plus source-grounded target
  -> code maps the parent concept to finite Canonical data concepts
  -> code validates, transitions state, and judges product facts
```

Examples:

```text
"保湿" / "补水" / "想润一点" -> hydration
product evidence such as "水润" / "锁水" / "润泽" -> hydration descendants

"不要酒精" / "避开乙醇" / "排除酒精" -> ingredient_exclusion(alcohol)
product facts "乙醇" / "alcohol" -> alcohol evidence identity
```

The model owns translation from wording to a finite parent concept. The code
owns source grounding, Canonical target normalization, state legality,
arithmetic, product identity, evidence evaluation, and public rendering. The
model never owns product IDs, candidate IDs, product facts, scores, or final
state commits.

The following are prohibited as permanent semantic fixes:

```text
adding a regex, keyword, or one-off phrase branch merely because a fixed or
blind utterance used that wording
making a product ID, fixture ID, or particular sentence a special case
using exact-language parsing to override a valid source-grounded model parent
concept in the provider-backed path
```

The following remain legitimate deterministic infrastructure:

```text
numeric token conversion and bound arithmetic after the model nominates a
source-grounded budget atom
source-span uniqueness checks
controlled Canonical product aliases and brand-to-identity matching
candidate/image ordinal binding
typed state transition validation and data-evidence evaluation
```

Before any further real semantic call, perform and record a patch-layer audit:

1. classify every current repair as `keep`, `migrate_to_parent_concept`, or
   `remove`;
2. remove confirmed wording-level patches before they are relied on by fixed
   qualification;
3. repair the underlying parent-concept bridge with RED -> GREEN tests;
4. replay the frozen capture with zero API;
5. continue fixed qualification only after the replay is green.

For every future failed turn, the mandatory stop protocol is:

```text
1. freeze the current-message text, typed context, raw model output, and
   terminal trace;
2. determine whether the model selected the wrong parent concept, the code
   failed to admit/map a correct parent concept, state/router execution was
   wrong, or Canonical evidence is absent or conflicting;
3. name exactly one earliest responsible layer;
4. write a RED test that varies wording while preserving the same parent
   concept and expected data behavior;
5. only then make the smallest parent-concept, data-contract, or state-layer
   repair; never special-case the observed sentence, product ID, or token.
```

## 2. Final Product Decisions

### Backend qualification

1. The fixed repair set is exactly `20 self-only conversations x 5 turns`.
2. After repair, the fixed set must complete `20/20` trajectories.
3. The independent exam is a different self-only `20 x 5` set frozen before
   the final qualification and not executed during development.
4. The independent exam passes only when:
   - at least `90/100` turns pass;
   - at least `18/20` complete trajectories pass;
   - all zero-tolerance counters remain zero.
5. An ordinary semantic, route, data, or presentation miss is recorded and
   the independent exam continues.
6. A serious failure aborts the exam immediately:
   - wrong product or image binding;
   - unauthorized state transition;
   - hard-condition override;
   - unsafe downgrade;
   - cross-session or cross-subject leakage;
   - state corruption or version drift.
7. "Abort immediately" applies to the current paid run, not the whole goal.
   The user granted standing authorization on 2026-08-18 to:
   - freeze the partial evidence and report the stop;
   - continue the active goal at zero API;
   - identify the unique earliest responsibility layer;
   - repair only a public rule under TDD;
   - replay the frozen evidence with zero provider calls;
   - automatically restart the relevant qualification after replay is green.
   Do not ask the user to re-authorize each repair/restart cycle.
8. Ask the user only when:
   - the CNY 18 stop or a provider-call cap must be changed;
   - product/fixture truth cannot be independently established;
   - credentials, provider availability, or another external dependency blocks
     progress;
   - a product decision outside the approved contract is required.
9. After any production, prompt, fixture, or data fix, the consumed blind exam
   is invalid. One pre-frozen disjoint retake set may be used. No third exam is
   allowed in this run.

This standing execution authorization is recorded in:

```text
docs/audits/continuous-conversation/execution-stop-policy-amendment-v3.json
```

### Copywriter qualification

1. The semantic backend gates run with the copywriter disabled.
2. A separate real copywriter gate runs exactly 20 reviewed packets.
3. The copywriter gate requires `20/20`, one call per packet, retry `0`.
4. Invalid JSON, truncation, invented facts, slot drift, internal language, or
   `copy_source=fallback` all fail copywriter qualification.
5. The final browser run requires real semantic translation and real
   copywriting on all 15 turns.

### Browser qualification

Run one production `/chat` web application, not a demo or fixture gallery.
Use one persistent browser context and cookie jar for each five-turn
conversation.

The three trajectories are:

```text
recommendation -> product follow-up -> knowledge detour
  -> return to product -> comparison

consultation -> correction -> product interruption
  -> return to consultation -> safety pivot

image identity -> ambiguous image reference -> explicit image suitability
  -> image-anchored recommendation -> original-product follow-up
```

All `3/3` trajectories and all `15/15` turns must pass.

### Approved frontend

Preserve the current G inline card structure and the existing full product
shelf. Do not redesign the card.

Only these text accents change:

```text
the standalone product title at the start of a product section: rose
"小 Ro 推荐：" label: rose
product names inside normal prose: ordinary text color
G inline card internal colors and typography: unchanged
```

## 3. API And Long-Run Safety

Normal allowance:

```text
targeted semantic probes: <= 10
fixed 20 x 5 semantic gate: 100
independent blind semantic gate: 100
conditional disjoint retake: <= 100
browser semantic calls: 15
copywriter packet gate: 20
browser copywriter calls: 15
provider retry: 0
format repair retry: 0
```

Maximum attempts in this plan:

```text
semantic calls: 545
copywriter calls: 55
```

The copywriter cap was explicitly revised by the user on 2026-08-18 after the
first 20-packet qualification exposed public-presentation and gate-truth
defects. The CNY 18 stop, provider retry `0`, and format repair `0` remain
unchanged. The immutable original control is preserved and the revision is
recorded in:

```text
docs/audits/continuous-conversation/night-run-control-amendment-v2.json
```

The user-approved spend stop is estimated CNY 18. Provider-reported monetary
cost is not guaranteed to be available. Therefore enforce both:

1. stop when provider-reported cumulative cost reaches CNY 18, when available;
2. always stop at the call caps above, even when monetary cost is unavailable.

Every paid call must persist:

```text
case and turn ID
input/context hash
raw provider output
parsed output or provider failure
trace ID
prompt/completion/total tokens
earliest failure layer
terminal snapshot or failure state
```

Every command longer than 30 seconds runs through
`tools/guide_gates/run_bounded_command.py` with:

```text
heartbeat: 30 seconds
process-group timeout
SIGTERM then SIGKILL cleanup
private log and summary files
```

Every gate writes an atomic partial artifact after each provider attempt.
No final response may be sent while a required execution session is running.

## 4. Responsibility Map

### Semantic translation and context

```text
app/guide/understanding/semantic_contracts.py
app/guide/understanding/context_resolver.py
app/guide/understanding/turn_meaning_contracts.py
app/guide/adapters/llm/turn_meaning_prompt.py
app/guide/intent/executable_intent_compiler.py
app/guide/intent/semantic_admission.py
```

### Routing, safety, and state

```text
app/guide/intent/unified_turn_router.py
app/guide/application/unified_guide_flow.py
app/guide/application/dynamic_consultation.py
app/guide/application/consultation_coordinator.py
app/guide/application/chat_api_adapter.py
app/guide/feedback/focus_state.py
app/guide/feedback/contracts.py
```

### Image integration

```text
app/guide/application/image_recommendation_flow.py
app/guide/application/text_recommendation_flow.py
app/guide/intent/task_planning.py
app/guide/decision/concept_ranking.py
app/guide/retrieval/selection_fact_reader.py
```

### Gate truth and replay

```text
tools/guide_gates/continuous_conversation_gate.py
tools/guide_gates/continuous_conversation_runtime.py
tools/guide_gates/continuous_conversation_fixture.py
tools/guide_gates/run_real_continuous_conversation_gate.py
tests/guide/tools/test_continuous_conversation_runtime.py
tests/guide/tools/test_run_real_continuous_conversation_gate.py
```

### Copywriter and browser

```text
tools/guide_gates/presentation_copy_gate.py
tools/guide_gates/run_real_presentation_copy_gate.py
app/guide/presentation/copywriter_prompt.py
app/guide/presentation/copywriter_validation.py
app/guide/presentation/presentation_compiler.py
app/static/guide-presentation.js
app/static/chat.html
```

## Task 1: Freeze The Night Run And Protect The Dirty Worktree

**Files:**
- Create:
  `docs/audits/continuous-conversation/night-run-control-v1.json`
- Create:
  `docs/audits/continuous-conversation/night-run-baseline-v1.json`

- [x] **Step 1: Record repository and branch**

Run:

```bash
git -C /Users/bytedance/Desktop/xiaoro-fresh rev-parse --show-toplevel
git -C /Users/bytedance/Desktop/xiaoro-fresh branch --show-current
git -C /Users/bytedance/Desktop/xiaoro-fresh status --short
```

Expected:

```text
/Users/bytedance/Desktop/xiaoro-fresh
rebuild
```

- [x] **Step 2: Write the immutable run-control artifact**

Create canonical JSON containing:

```json
{
  "schema_version": "guide-night-run-control-v1",
  "repository": "/Users/bytedance/Desktop/xiaoro-fresh",
  "branch": "rebuild",
  "fixed_trajectory_count": 20,
  "turns_per_trajectory": 5,
  "blind_turn_pass_minimum": 90,
  "blind_trajectory_pass_minimum": 18,
  "browser_trajectory_count": 3,
  "browser_turn_count": 15,
  "copywriter_case_count": 20,
  "semantic_call_cap": 545,
  "copywriter_call_cap": 55,
  "estimated_cost_stop_cny": "18.00",
  "provider_retry_count": 0,
  "format_repair_attempts": 0
}
```

- [x] **Step 3: Hash the files in the responsibility map**

Use `shasum -a 256` and write relative path plus SHA-256 to the baseline
artifact. Do not include API key paths, environment values, SQLite state, or
raw credentials.

- [x] **Step 4: Verify no unrelated file was modified**

Run:

```bash
git diff --check
```

Expected: no output.

## Task 2: Make The Gate Tell The Truth Before Fixing Product Code

**Files:**
- Modify:
  `tools/guide_gates/run_real_continuous_conversation_gate.py:929-1074`
- Modify:
  `tools/guide_gates/continuous_conversation_runtime.py:430-639`
- Modify:
  `tools/guide_gates/continuous_conversation_gate.py`
- Modify:
  `tests/guide/tools/test_run_real_continuous_conversation_gate.py`
- Modify:
  `tests/guide/tools/test_continuous_conversation_runtime.py`

- [x] **Step 1: Write RED for contiguous partial-capture replay**

```python
def test_partial_capture_replays_only_contiguous_captured_prefixes(
    tmp_path: Path,
) -> None:
    report = replay_captured_continuous_gate(
        trajectories=two_trajectories(),
        capture_path=partial_capture_with_five_plus_two_turns(),
        runtime_factory=local_runtime_factory(),
        state_root=tmp_path / "state",
        output_path=tmp_path / "replay.json",
        allow_partial=True,
    )

    assert report.expected_turn_count == 10
    assert report.captured_turn_count == 7
    assert report.replayed_turn_count == 7
    assert report.capture_complete is False
    assert report.provider_call_count == 0
```

Also add tests that reject:

```text
unknown trajectory or turn IDs
duplicate captured keys
a captured t3 when t2 is missing
message/input hash drift
```

- [x] **Step 2: Run the partial-replay RED**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/guide/tools/test_run_real_continuous_conversation_gate.py \
  -k 'partial_capture or capture_identity'
```

Expected: FAIL because replay currently requires exact equality with all 100
turn keys.

- [x] **Step 3: Implement captured-prefix validation**

Add an `allow_partial: bool = False` parameter and validate each trajectory as
a contiguous prefix:

```python
def _captured_prefix_turns(
    trajectories: tuple[ContinuousTrajectory, ...],
    by_key: dict[tuple[str, str], dict[str, object]],
) -> dict[str, tuple[ContinuousTurnExpectation, ...]]:
    known = {
        (trajectory.trajectory_id, turn.turn_id)
        for trajectory in trajectories
        for turn in trajectory.turns
    }
    if set(by_key).difference(known):
        raise ValueError("capture contains unknown turn identities")

    prefixes: dict[str, tuple[ContinuousTurnExpectation, ...]] = {}
    for trajectory in trajectories:
        captured: list[ContinuousTurnExpectation] = []
        missing_seen = False
        for turn in trajectory.turns:
            present = (trajectory.trajectory_id, turn.turn_id) in by_key
            if present and missing_seen:
                raise ValueError("capture turns must form a contiguous prefix")
            if present:
                captured.append(turn)
            else:
                missing_seen = True
        prefixes[trajectory.trajectory_id] = tuple(captured)
    return prefixes
```

Extend `ContinuousReplayReport` with:

```python
expected_turn_count: int = Field(ge=1)
capture_complete: bool
replay_passed: bool
```

`passed` remains qualification-level and is false for an incomplete capture.

- [x] **Step 4: Write RED proving image route reporting is not inferred from presentation**

Use the captured `image-clarify-and-recover-t1` meaning. Assert that the gate
reports the actual direct Router decision, not:

```python
processor = "image_identity" if has_confirmed_identity else ...
```

Before the image repair, the truthful expected observation is:

```text
actual Router processor: comparison
public intent: comparison
final focus: comparison
```

- [x] **Step 5: Replace event-shape route guessing**

After image observations are available, rebuild the exact Router input from
the confirmed image ordinals and call `route_unified_turn()` with the same
`meaning`, `understanding`, and starting snapshot. Store this decision in
`ContinuousRuntimeTurnResult.route`.

Do not expose the internal route in public SSE.

- [x] **Step 6: Remove false public-language counters from crashes**

A turn that produced no public message cannot increment
`internal_public_language_count`. Keep the runtime failure at the layer
reported by `failure_layer_for_last_error()`.

- [x] **Step 7: Run gate truth tests**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/guide/tools/test_run_real_continuous_conversation_gate.py \
  tests/guide/tools/test_continuous_conversation_runtime.py \
  tests/guide/tools/test_continuous_conversation_gate.py
```

Expected: PASS with zero provider calls.

- [x] **Step 8: Replay the existing 34-turn capture**

Run through `run_bounded_command.py` with a 30-second heartbeat and write a new
audit artifact. Required:

```text
captured turns: 34
replayed turns: 34 unless an earlier captured runtime failure blocks its suffix
provider calls: 0
copywriter calls: 0
each failure has one truthful earliest layer
```

## Task 3: Freeze Two Truly Independent Blind Exams Before Product Fixes

**Files:**
- Create:
  `tools/guide_gates/continuous_conversation_blind_fixture.py`
- Create:
  `tests/fixtures/guide/conversation/continuous_blind_pool_v1.jsonl`
- Create:
  `tests/fixtures/guide/conversation/continuous_blind_a_20x5_v1.jsonl`
- Create:
  `tests/fixtures/guide/conversation/continuous_blind_a_20x5_v1_manifest.json`
- Create:
  `tests/fixtures/guide/conversation/continuous_blind_b_20x5_v1.jsonl`
- Create:
  `tests/fixtures/guide/conversation/continuous_blind_b_20x5_v1_manifest.json`
- Create:
  `tests/guide/tools/test_continuous_conversation_blind_fixture.py`

The current pool has 30 trajectories and the fixed set already uses 20. Ten
remaining trajectories cannot supply an independent 20-trajectory exam.

- [x] **Step 1: Write RED for fixed/blind disjointness**

```python
def test_blind_exams_are_disjoint_from_fixed_and_each_other() -> None:
    fixed = load_frozen_trajectories()
    blind_a, blind_b = load_blind_exams()

    fixed_ids = {item.trajectory_id for item in fixed}
    a_ids = {item.trajectory_id for item in blind_a}
    b_ids = {item.trajectory_id for item in blind_b}

    assert len(blind_a) == len(blind_b) == 20
    assert fixed_ids.isdisjoint(a_ids)
    assert fixed_ids.isdisjoint(b_ids)
    assert a_ids.isdisjoint(b_ids)
    assert normalized_messages(fixed).isdisjoint(normalized_messages(blind_a))
    assert normalized_messages(fixed).isdisjoint(normalized_messages(blind_b))
    assert normalized_messages(blind_a).isdisjoint(normalized_messages(blind_b))
```

- [x] **Step 2: Build a 40-trajectory blind pool**

Use four balanced groups of ten:

```text
recommendation/revision/product follow-up
knowledge/comparison/return-to-focus
consultation/profile/other-person/safety
image identity/suitability/similarity/comparison/clarification
```

Each trajectory has five natural turns, a unique subject, and at least two
mode or focus transitions. Do not execute these trajectories against the
runtime during development.

An authorized sub-agent may draft the pool. The main agent must personally
review:

```text
budget arithmetic
Canonical product IDs and prices
image ordinal meaning
subject isolation
route and continuity duties
safety expectations
card identity sets
```

- [x] **Step 3: Freeze two disjoint deterministic exams**

```python
BLIND_SHUFFLE_SEED = 2026081801


def select_blind_exams(
    pool: Sequence[ContinuousTrajectory],
) -> tuple[
    tuple[ContinuousTrajectory, ...],
    tuple[ContinuousTrajectory, ...],
]:
    normalized = list(pool)
    if len(normalized) != 40:
        raise ValueError("blind pool must contain exactly forty trajectories")
    random.Random(BLIND_SHUFFLE_SEED).shuffle(normalized)
    return (
        tuple(sorted(normalized[:20], key=lambda item: item.trajectory_id)),
        tuple(sorted(normalized[20:], key=lambda item: item.trajectory_id)),
    )
```

Write both manifests and SHA-256 hashes before Task 4 edits production code.

- [x] **Step 4: Validate authoring without running the product runtime**

Run only fixture, canonical identity, price-boundary, uniqueness, and coverage
validators:

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/guide/tools/test_continuous_conversation_blind_fixture.py \
  tests/guide/data/test_full_catalog_source_policy.py
```

Expected: PASS. Do not run either blind exam.

## Task 4: Establish One Source-Grounded Safety Authority

**Files:**
- Create:
  `app/guide/understanding/safety_admission.py`
- Modify:
  `app/guide/application/unified_guide_flow.py`
- Modify:
  `app/guide/application/dynamic_consultation.py:178-214,526-563`
- Modify:
  `app/guide/intent/unified_turn_router.py:185-228,649-668`
- Test:
  `tests/guide/understanding/test_safety_admission.py`
- Modify:
  `tests/guide/intent/test_unified_turn_router.py`
- Modify:
  `tests/guide/application/test_dynamic_consultation.py`
- Modify:
  `tests/guide/tools/test_continuous_conversation_runtime.py`

- [x] **Step 1: Write RED for grounded ordinary and severe observations**

```python
def test_safety_signal_uses_only_grounded_observations() -> None:
    ordinary = admit_safety_signal(
        message="最近护肤后会发热泛红",
        candidates=(
            observation("burning", raw_text="发热", duration="current"),
            observation("redness", raw_text="泛红", duration="current"),
        ),
    )
    hallucinated = admit_safety_signal(
        message="最近只是有点干",
        candidates=(
            observation("oozing", raw_text="渗液", duration="current"),
        ),
    )
    severe = admit_safety_signal(
        message="现在仍然在渗，而且碰水会疼",
        candidates=(
            observation("oozing", raw_text="渗", duration="current"),
            observation("pain", raw_text="碰水会疼", duration="current"),
        ),
    )

    assert ordinary.requires_escalation is False
    assert hallucinated.requires_escalation is False
    assert severe.trigger_codes == ("oozing", "pain")
```

- [x] **Step 2: Implement a shared code-owned signal**

```python
class AdmittedSafetySignal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    trigger_codes: tuple[str, ...] = ()

    @property
    def requires_escalation(self) -> bool:
        return bool(self.trigger_codes)
```

`admit_safety_signal()` must use `ground_unique_text()` before applying the
single safety rule table.

- [x] **Step 3: Remove Router inspection of raw model observations**

Change `route_unified_turn()` to accept:

```python
safety_signal: AdmittedSafetySignal | None = None
```

Use only:

```python
if safety_signal is not None and safety_signal.requires_escalation:
    return UnifiedRouteDecision(
        processor="safety_escalation",
        continuity=_continuity(...),
        focus_source="consultation",
    )
```

Delete `_has_active_damage()`. Dynamic consultation calls the same policy
after `_admit_observations()` so Router and consultation cannot disagree.

- [x] **Step 4: Lock captured safety behavior**

The captured first turn:

```text
最近护肤后会发热泛红，想看看是什么状态
```

must route to `consultation`.

The later grounded `oozing`/`pain` turn must route and present safety while
continuing the existing consultation, not replacing it as a new task.

- [x] **Step 5: Run safety GREEN**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/guide/understanding/test_safety_admission.py \
  tests/guide/intent/test_unified_turn_router.py \
  tests/guide/application/test_dynamic_consultation.py \
  tests/guide/tools/test_continuous_conversation_runtime.py \
  -k 'safety or damage or escalation or pivot'
```

Expected: PASS with zero API calls.

## Task 5: Merge Images Into Normal Processors Without Losing Identity

**Files:**
- Modify:
  `app/guide/intent/unified_turn_router.py:355-415`
- Modify:
  `app/guide/application/image_recommendation_flow.py:1186-1229,1457-1488,1599-1692`
- Modify:
  `app/guide/application/text_recommendation_flow.py:930-958`
- Modify:
  `app/guide/application/chat_api_adapter.py:420-579`
- Modify:
  `app/guide/intent/contracts.py`
- Modify:
  `app/guide/intent/task_planning.py`
- Modify:
  `tools/guide_gates/continuous_conversation_runtime.py:430-639`
- Modify:
  `tests/guide/application/test_image_recommendation_flow.py`
- Modify:
  `tests/guide/application/test_chat_api_adapter.py`
- Modify:
  `tests/guide/intent/test_unified_turn_router.py`
- Modify:
  `tests/guide/tools/test_continuous_conversation_runtime.py`

- [x] **Step 1: Write RED for two-image identity**

```python
def test_two_confirmed_images_respect_explicit_identity_operation() -> None:
    route = route_unified_turn(
        meaning=image_identity_meaning(),
        understanding=image_identity_understanding(),
        snapshot=None,
        current_image_products=(
            confirmed_image(1, 53),
            confirmed_image(2, 55),
        ),
    )

    assert route.processor == "image_identity"
    assert [item.product_id for item in route.product_bindings] == [53, 55]
```

The current code fails because image count overrides the explicit operation
before `image_identity` is checked.

- [x] **Step 2: Give explicit operation precedence**

In `_select_processor()`:

```python
if operation == "image_identity":
    return "image_identity" if bindings else "clarification"
if operation == "comparison":
    return "comparison"
if has_current_images and len(bindings) >= 2:
    return "comparison"
```

Do not infer comparison merely from two uploaded images.

- [x] **Step 3: Add a real multi-image identity response**

For `image_identity`, emit:

```text
intent=image_identity
one confirmed observation per image ordinal
cards for exactly the confirmed products
Canonical/product evidence
image citations
presentation mode=image_identity
one terminal end
```

Do not emit comparison language, a winner, or a comparison task plan.

- [x] **Step 4: Make public-event commit the final image-state authority**

When confirmed `image_observation` events exist, the staged final snapshot
must set:

```python
has_image_delivery=True
focus_state.active_processor="image_identity"
focus_state.confirmed_image_products=(...)
```

For one identified image, set `current_product_id` to that product. For two or
three identified images, keep `current_product_id=None` until the user names
an ordinal.

- [x] **Step 5: Write RED for text follow-up to a prior image**

Cover:

```text
"它的参考价后面为什么没有规格" -> product_knowledge, image 1
"我说第一张，它适合敏感倾向吗" -> product_knowledge, image 1
"看那张图，帮我继续判断" -> clarification, no guessed image
"改看第二张，照它找一百元内的相似款" -> recommendation anchored by image 2
```

All successful turns advance exactly one version and retain both confirmed
image ordinals.

- [x] **Step 6: Represent image similarity as a code-owned recommendation anchor**

Add to `TaskPlan`:

```python
similarity_anchor_product_id: int | None = Field(default=None, gt=0)
```

The model never emits this ID. The bound image ordinal supplies it after
Canonical resolution.

For later text-only image similarity:

```text
anchor category and reviewed selection concepts feed normal recall/ranking
budget and exclusions remain hard filters
anchor product is excluded from alternative results
no eligible alternative produces a normal zero-card no-match
```

Do not require the old upload token or create an isolated image answer
template.

- [x] **Step 7: Keep route and goal contracts aligned**

Normalize `UnderstandingGoal.IMAGE_SIMILARITY` to an executable recommendation
only after the code-owned anchor has been bound. Preserve the anchor in
`TaskPlan.similarity_anchor_product_id`.

The downstream disagreement guard remains strict.

- [x] **Step 8: Run image and state GREEN**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/guide/intent/test_unified_turn_router.py \
  tests/guide/application/test_image_recommendation_flow.py \
  tests/guide/application/test_chat_api_adapter.py \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/tools/test_continuous_conversation_runtime.py \
  -k 'image or confirmed or similarity or version'
```

Expected: PASS with no wrong image binding, no double commit, and no runtime
error event.

## Task 6: Give The Model Enough Typed Context To Understand Continuation

**Files:**
- Modify:
  `app/guide/understanding/semantic_contracts.py:311-360`
- Modify:
  `app/guide/understanding/context_resolver.py:91-166`
- Modify:
  `app/guide/understanding/semantic_route_contracts.py:41-76`
- Modify:
  `app/guide/adapters/llm/turn_meaning_prompt.py`
- Modify:
  `tests/guide/understanding/test_context_resolver.py`
- Modify:
  `tests/guide/adapters/test_turn_meaning_prompt.py`
- Modify:
  `tests/guide/tools/test_continuous_conversation_runtime.py`

- [x] **Step 1: Write RED for closed active-dialogue context**

```python
def test_context_exposes_mode_without_raw_history_or_product_ids() -> None:
    context = resolve_semantic_context(
        conversation_version=2,
        snapshot=consultation_snapshot_with_open_question(),
    )

    assert context.active_dialogue == "consultation"
    assert context.awaiting_reply is True
    payload = context.model_dump_json()
    assert "product_id" not in payload
    assert "last_question_meaning" not in payload
```

- [x] **Step 2: Extend the typed context**

Add:

```python
ActiveDialogue = Literal[
    "recommendation",
    "comparison",
    "product_knowledge",
    "general_knowledge",
    "image_identity",
    "consultation",
    "clarification",
    "safety_escalation",
]

active_dialogue: ActiveDialogue | None = None
awaiting_reply: bool = False
```

These fields expose only closed state shape, never raw conversation history,
profile values, or product IDs.

- [x] **Step 3: Update prompt continuity rules**

Increment `TURN_MEANING_PROMPT_VERSION`.

Add explicit rules:

```text
When active_dialogue=consultation and awaiting_reply=true, a direct symptom,
location, duration, tolerance, or correction answer is continue.

Use new_task only when the current message explicitly starts an independent
goal or switches subject/task.

A subject switch from other to self is new_task even when the category is
unchanged.

An ambiguous reference remains clarification; do not guess an image or
product ordinal.
```

- [x] **Step 4: Lock known semantic classes**

Add deterministic prompt/payload tests for:

```text
consultation answer continuation
consultation correction
product interruption then return_to_focus
other-person to self switch
ambiguous image reference
explicit first/second image reference
```

- [x] **Step 5: Run semantic contract GREEN**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/guide/understanding/test_context_resolver.py \
  tests/guide/adapters/test_turn_meaning_prompt.py \
  tests/guide/understanding/test_turn_meaning_contracts.py \
  tests/guide/tools/test_continuous_conversation_runtime.py
```

Expected: PASS with zero API calls.

## Task 7: Correct Fixtures Only With Independent Business Proof

**Files:**
- Modify:
  `tests/fixtures/guide/conversation/continuous_trajectory_pool_v1.jsonl`
- Modify:
  `tests/fixtures/guide/conversation/continuous_20x5_v1.jsonl`
- Modify:
  `tests/fixtures/guide/conversation/continuous_20x5_v1_manifest.json`
- Modify:
  `tests/guide/tools/test_continuous_conversation_fixture.py`
- Modify:
  `docs/audits/continuous-conversation/failure-ledger.md`

- [x] **Step 1: Prove each fixture correction without using observed output**

Required independent proofs:

```text
budget card set: Canonical reference price compared to explicit maximum
clean-slate subject switch: no prior other-person profile enters the task
ranking order: identity set is authoritative unless order is itself a duty
safety continuation: same consultation remains active
multi-image identity: no arbitrary current product before an ordinal
presentation mode: must match the approved public mode contract
```

- [x] **Step 2: Keep semantically wrong model output as a model failure**

Do not widen `continuity_hints` merely because the model emitted `new_task`.
If typed context proves that the user answered the active consultation, the
correct translation is `continue`; repair context/prompt instead.

- [x] **Step 3: Regenerate manifest hashes**

Run the fixture freezer and verify canonical JSONL ordering. Record old and
new hashes plus the independent reason for every changed expectation in the
failure ledger.

- [x] **Step 4: Run fixture GREEN**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/guide/tools/test_continuous_conversation_fixture.py \
  tests/guide/data/test_full_catalog_source_policy.py
```

Expected: PASS.

## Task 8: Add Heartbeats, Timeouts, Health Polling, And Per-Turn Durability

**Files:**
- Modify:
  `tools/guide_gates/run_real_continuous_conversation_gate.py`
- Modify:
  `tools/guide_gates/run_real_presentation_copy_gate.py`
- Create:
  `tools/guide_gates/continuous_conversation_browser_audit.py`
- Modify:
  `tests/guide/tools/test_run_real_continuous_conversation_gate.py`
- Modify:
  `tests/guide/tools/test_run_real_presentation_copy_gate.py`
- Create:
  `tests/guide/tools/test_continuous_conversation_browser_audit.py`

- [x] **Step 1: Write RED for per-turn progress and atomic output**

After each provider attempt, assert:

```text
partial artifact exists
captured row count increased by one
progress line contains trajectory ID, turn ID, attempted calls, token total
no API key or Authorization value appears
```

- [x] **Step 2: Persist after every attempt**

Write the partial artifact through temporary-file replace after:

```text
successful translation and runtime
invalid model output
provider timeout
runtime exception
serious-failure abort
```

- [x] **Step 3: Use bounded commands for every long run**

Canonical wrapper:

```bash
PYTHONPATH=. .venv/bin/python -m tools.guide_gates.run_bounded_command \
  --timeout-seconds 7200 \
  --heartbeat-seconds 30 \
  --output /private/tmp/xiaoro-acceptance.log \
  --summary /private/tmp/xiaoro-acceptance-summary.json \
  -- \
  .venv/bin/python -m tools.guide_gates.run_real_continuous_conversation_gate \
  ...
```

- [x] **Step 4: Add browser health polling**

During each browser turn:

```text
provider call timeout <= 30 seconds
whole turn timeout <= 90 seconds
/health poll every 10 seconds from a separate client
page active-request count reaches zero before next turn
server and browser process groups terminate on timeout
```

A blocked `/health` probe is a runtime failure, not a reason to wait another
unbounded 120 seconds.

- [x] **Step 5: Run watchdog GREEN**

Use fake hanging provider/server processes. Required:

```text
heartbeat emitted
partial output preserved
SIGTERM sent
SIGKILL used only after grace period
no child process remains
```

## Task 9: Qualify Real Copywriting With Twenty Packets

**Files:**
- Create:
  `tests/fixtures/guide/presentation/copy_gate_v2.jsonl`
- Modify:
  `tools/guide_gates/run_real_presentation_copy_gate.py`
- Modify:
  `tests/guide/tools/test_run_real_presentation_copy_gate.py`
- Create:
  `docs/audits/continuous-conversation/copywriter-20-v1/`

- [x] **Step 1: Expand the reviewed packet set to twenty**

Required distribution:

```text
recommendation: 3, including one long three-product packet
comparison: 2
product knowledge/follow-up/suitability: 4
general knowledge: 2
consultation, correction, safety: 3
image identity/suitability/recommendation/comparison: 4
revision and no-match/clarification: 2
```

- [x] **Step 2: Match the real runtime token contract**

The runner currently uses `max_tokens=512`; runtime configuration uses 1536.
Change the gate adapter to:

```python
max_tokens=1536
```

Add a test that a three-product draft is not truncated and validates under
the same schema used in production.

- [x] **Step 3: Persist each copywriter result immediately**

After each packet, atomically update:

```text
results.jsonl
partial-summary.json
progress line
```

- [x] **Step 4: Run the real copywriter gate**

Use a bounded command, one call per case, retry `0`.

Required:

```text
provider calls = 20
passed = 20
schema valid = 20
readability = 20
fact coverage = 20
internal language pass = 20
hard violations = 0
```

Any fallback or adapter failure fails this task.

## Task 10: Run The Fixed 20-By-5 Repair Qualification

**Files:**
- Create:
  `docs/audits/continuous-conversation/backend-fixed-20x5-real-v2.json`
- Create:
  `docs/audits/continuous-conversation/backend-fixed-20x5-replay-v2.json`
- Create:
  `docs/audits/continuous-conversation/semantic-patch-audit-v1.md`
- Modify:
  `docs/audits/continuous-conversation/failure-ledger.md`

- [ ] **Step 0: Audit semantic patches before resuming paid qualification**

Classify every uncommitted semantic-related repair and every relevant
pre-existing exact-language branch as one of:

```text
keep: deterministic numeric conversion, source grounding, Canonical identity,
ordinal binding, state legality, or evidence evaluation
migrate_to_parent_concept: the branch interprets natural-language intent that
the model should normalize to a finite parent concept
remove: a fixed-utterance, product-specific, or phrase-specific special case
```

The audit must explicitly cover:

```text
exact_parsing exclusion, inclusion, efficacy, skin, and revision wording
colloquial budget wording
pending reply affirmation/rejection wording
TurnMeaning -> executable compiler parent-concept projection
selection concept and product-evidence descendant mapping
controlled product aliases versus uncontrolled text aliases
```

For every `migrate_to_parent_concept` item, state the destination parent
concept, Canonical target normalization, state-transition owner, and data
field contract. Remove confirmed `remove` items before the next paid call.
Do not merely widen an accepted wording list.

For a hard ingredient exclusion, a fixture may expect a nonempty result only
when Canonical `verified_absences` contains an approved matching entity. When
that evidence is unknown, the expected result is zero cards. A later
follow-up may name a product only after the user withdraws the exclusion and
a new displayed batch exists.

- [ ] **Step 1: Run focused zero-API regression**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/guide/intent/test_unified_turn_router.py \
  tests/guide/application/test_dynamic_consultation.py \
  tests/guide/application/test_image_recommendation_flow.py \
  tests/guide/application/test_chat_api_adapter.py \
  tests/guide/tools/test_continuous_conversation_runtime.py \
  tests/guide/tools/test_run_real_continuous_conversation_gate.py
```

Expected: PASS.

- [ ] **Step 2: Run at most ten targeted semantic probes**

Probe only:

```text
consultation continuation/correction
other-person to self switch
ordinary versus severe safety
ambiguous image reference
explicit image ordinal
image similarity
return to earlier focus
```

Stop the current paid probe run on a serious failure, save every raw output,
then automatically diagnose, repair under TDD, replay at zero API, and resume
the active goal under the standing authorization above.

- [ ] **Step 3: Run the real fixed 100 turns**

Use:

```text
real TurnMeaning provider
copywriter disabled
one semantic call per attempted turn
retry 0
30-second heartbeat
per-turn atomic capture
```

During this repair qualification, stop at the first failed ordinary turn,
classify it, repair under TDD, replay captured evidence at zero API, and use a
targeted semantic probe before restarting the final fixed run.

A serious failure follows the same repair loop but still aborts the current
paid command immediately. It does not require another user approval unless one
of the explicit escalation conditions in Backend qualification item 8 applies.

- [ ] **Step 4: Require fixed-set closure**

Required final fixed result:

```text
turns = 100/100
trajectories = 20/20
zero-tolerance counters = 0
copywriter calls = 0
```

- [ ] **Step 5: Replay the complete fixed capture**

Required:

```text
replayed turns = 100
provider calls = 0
copywriter calls = 0
passed turns = 100
passed trajectories = 20
results deterministic on current code
```

## Task 11: Run The Independent Blind 20-By-5 Exam

**Files:**
- Create:
  `docs/audits/continuous-conversation/backend-blind-a-20x5-real-v1.json`
- Conditionally create:
  `docs/audits/continuous-conversation/backend-blind-b-20x5-real-v1.json`
- Create:
  `docs/audits/continuous-conversation/blind-exam-decision-v1.json`

- [ ] **Step 1: Re-verify code and blind fixture hashes**

The production code, prompt version, fixed fixture, and both blind manifests
must be hashed before the first blind provider call.

- [ ] **Step 2: Run blind exam A without mid-run repair**

Rules:

```text
ordinary failure: record and continue
runtime crash: stop that trajectory, continue independent trajectories
serious zero-tolerance failure: abort the whole exam immediately
provider auth/budget/outage: abort as infrastructure-invalid
invalid model JSON: record model_translation failure, stop that trajectory,
  continue other trajectories
```

- [ ] **Step 3: Score exam A**

Pass only when:

```python
turn_pass_rate >= 0.90
passed_trajectory_count >= 18
all(zero_tolerance_counter == 0)
attempted_turn_count == 100
```

- [ ] **Step 4: Handle a failed exam without training on the paper**

If exam A fails:

1. freeze its complete evidence;
2. diagnose every failed turn by earliest layer;
3. repair under TDD;
4. replay exam A at zero API only as regression evidence;
5. run targeted semantic probes;
6. use blind exam B exactly once.

Do not claim exam A as independent after its failures were used for repair.
Do not create a third blind exam in this run.

- [ ] **Step 5: Freeze the blind decision**

Record:

```text
exam used for final decision
turn and trajectory pass rates
zero-tolerance counters
provider/token counts
source/fixture/output hashes
whether the conditional retake was consumed
```

## Task 12: Apply The Approved G Presentation Accent Only

**Files:**
- Modify:
  `app/static/guide-presentation.js:968-977,1021-1033,1168-1177,1219-1231`
- Modify:
  `app/static/chat.html:1510-1645`
- Modify:
  `tests/guide/runtime/test_frontend_mode_rendering.py`
- Modify:
  `tests/guide/runtime/test_frontend_presentation_stream.py`

- [ ] **Step 1: Write RED for exact rose scope**

Assert:

```text
product section h3 has the rose title class
"小 Ro 推荐：" label has the rose label class
normal paragraph product references retain normal text behavior
G inline card DOM and class list remain unchanged
```

- [ ] **Step 2: Add explicit classes**

Both synchronous and streaming renderers use:

```javascript
title.className = 'guide-product-section-title';
label.className = 'guide-advisor-label';
label.textContent = '小 Ro 推荐：';
```

- [ ] **Step 3: Add scoped CSS only**

```css
.guide-product-section-title,
.guide-advisor-label {
    color: var(--primary-deep);
}
```

Do not change:

```text
guide-inline-product-content
guide-inline-product-visual
guide-inline-product-info
guide-inline-product-brand
guide-inline-product-name
guide-inline-product-rule
guide-inline-product-price
```

- [ ] **Step 4: Run frontend contract GREEN**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/guide/runtime/test_frontend_mode_rendering.py \
  tests/guide/runtime/test_frontend_presentation_stream.py \
  tests/guide/runtime/test_frontend_card_binding.py
```

Expected: PASS and unchanged G card structure.

## Task 13: Run Three Real Five-Turn Browser Trajectories

**Files:**
- Create:
  `tools/guide_gates/continuous_conversation_browser_audit.py`
- Create:
  `tests/guide/tools/test_continuous_conversation_browser_audit.py`
- Create:
  `docs/audits/continuous-conversation/browser-real-3x5-v1.json`
- Create:
  `docs/audits/continuous-conversation/browser-real-3x5-v1/`

- [ ] **Step 1: Write RED for real-provider accounting**

```python
def test_browser_report_requires_real_semantic_and_copy_calls() -> None:
    report = load_browser_report()

    assert report.trajectory_count == 3
    assert report.turn_count == 15
    assert report.semantic_call_count == 15
    assert report.copywriter_call_count == 15
    assert all(row.copy_source == "model" for row in report.turns)
```

- [ ] **Step 2: Start the real clean runtime**

Required environment:

```text
GUIDE_UNIFIED_ROUTER_ENABLED=true
real TurnMeaning provider configured
real copywriter configured
semantic retry=0
copywriter retry=0
```

Never print key values.

- [ ] **Step 3: Execute the three trajectories**

For every trajectory:

```text
new session and owner
one persistent browser context for all five turns
wait for terminal SSE and active request count zero
verify committed conversation version increments by exactly one
take one screenshot after each terminal turn
```

- [ ] **Step 4: Poll health and fail boundedly**

Poll:

```text
browser state every 2 seconds
/health every 10 seconds
progress artifact after every turn
whole-turn timeout 90 seconds
whole browser run timeout 2700 seconds
```

On timeout, save the current SSE, DOM, console, network, screenshot, process
summary, and partial report before cleanup.

- [ ] **Step 5: Enforce browser acceptance**

Every turn requires:

```text
copy_source=model
no fallback_reason
correct processor/presentation mode
correct inline and bottom card identity sets
no stale card after a mode switch
no console or relevant network error
all images load
no overlap, clipped text, or horizontal overflow
thinking panel leaves after first answer character
product heading and "小 Ro 推荐：" are rose
normal prose remains normal color
G inline card classes and geometry remain unchanged
```

Required final result:

```text
trajectories = 3/3
turns = 15/15
semantic calls = 15
copywriter calls = 15
fallbacks = 0
serious failures = 0
```

## Task 14: Full Regression, Sanity Audit, And Closure

**Files:**
- Create:
  `docs/audits/continuous-conversation/final-closure-2026-08-18.md`
- Modify:
  `docs/audits/continuous-conversation/failure-ledger.md`

- [ ] **Step 1: Run focused suites**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/guide/understanding \
  tests/guide/intent \
  tests/guide/feedback \
  tests/guide/application \
  tests/guide/presentation \
  tests/guide/runtime \
  tests/guide/tools/test_continuous_conversation_fixture.py \
  tests/guide/tools/test_continuous_conversation_blind_fixture.py \
  tests/guide/tools/test_continuous_conversation_runtime.py \
  tests/guide/tools/test_run_real_continuous_conversation_gate.py \
  tests/guide/tools/test_run_real_presentation_copy_gate.py \
  tests/guide/tools/test_continuous_conversation_browser_audit.py
```

Expected: PASS.

- [ ] **Step 2: Run the complete repository suite**

Run through the bounded command wrapper:

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q
```

Expected: PASS with no new warning category.

- [ ] **Step 3: Run static checks**

Run:

```bash
git diff --check
PYTHONPATH=. .venv/bin/python -m compileall -q app tools tests
```

Expected: no error.

- [ ] **Step 4: Recheck all hashes and call counts**

Verify:

```text
fixed fixture and capture
blind fixture and final exam
copywriter packets and outputs
browser report and screenshots
source responsibility-map files
semantic/copywriter call caps
```

- [ ] **Step 5: Write the final closure**

The closure must state:

```text
what failed at each earliest layer
which issues were engine, model, fixture, data, gate, or presentation defects
semantic patch-audit classification and every removed or migrated phrase rule
fixed 20 x 5 result
copywriter 20/20 result
independent blind 20 x 5 result
whether a retake was used
browser 3 x 5 result
all zero-tolerance counters
provider calls, tokens, and reported cost when available
focused and full pytest counts
remaining limitations
no production deployment performed
```

- [ ] **Step 6: Final completion decision**

Do not mark the goal complete unless all are true:

```text
fixed trajectories = 20/20
fixed zero-API replay = 100/100
copywriter packets = 20/20 with no fallback
blind turns >= 90/100
blind complete trajectories >= 18/20
blind zero-tolerance counters = 0
browser trajectories = 3/3
browser turns = 15/15 with real semantic and real copywriter
focused tests pass
full tests pass
no required process remains running
```

If any condition fails, report the exact earliest unresolved layer and leave
the goal active unless the goal system's blocked threshold is genuinely met.

## Execution Order And Sub-Agent Policy

Execute tasks in this exact order:

```text
1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8
-> 9 -> 10 -> 11 -> 12 -> 13 -> 14
```

Allowed parallel read-only lanes:

```text
gate/fixture evidence
image/state evidence
copywriter/browser evidence
```

Allowed isolated implementation lanes after main-agent RED approval:

```text
blind fixture tooling
copywriter gate durability
frontend rose accent tests
```

The main agent personally owns:

```text
earliest-layer classification
safety authority
Router and image state changes
fixture corrections
real API budget decisions
blind exam scoring
browser acceptance
final merge and completion claim
```
