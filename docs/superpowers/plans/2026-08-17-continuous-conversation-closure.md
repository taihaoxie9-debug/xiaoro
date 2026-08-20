# Continuous Conversation Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking. The current user requires the main
> Agent to execute every step directly; do not create or delegate subagents.

**Goal:** Replace turn-level readiness claims with a real 20-conversation,
five-turn backend gate, repair the responsibility boundaries it exposes, and
accept three complete five-turn conversations in the browser.

**Architecture:** Keep Unified Router V1, Canonical identity, decision code,
session state, typed SSE, and presentation contracts as the production spine.
Add a strict trajectory runner around the real runtime so each committed turn
feeds the next. Evaluate every failure at its earliest layer, fix that layer
under TDD, replay captured outputs without API calls, and use the browser only
for the final 3-by-5 presentation sample.

**Tech Stack:** Python 3.11, Pydantic v2, FastAPI, SQLite WAL/CAS, pytest,
typed SSE, Playwright, DeepSeek TurnMeaning, optional presentation
copywriter.

---

## File Structure

New focused files:

```text
app/guide/presentation/public_language.py
    Public-text vocabulary and structural validation shared by every
    user-visible message and presentation section.

tools/guide_gates/continuous_conversation_gate.py
    Strict five-turn trajectory contracts, sequential executor, earliest
    distortion evaluator, and captured replay.

tools/guide_gates/continuous_conversation_fixture.py
    Frozen, seeded selection of twenty trajectories from a reviewed pool.

tools/guide_gates/run_real_continuous_conversation_gate.py
    One TurnMeaning call per real turn, no copywriter, no retry, immutable
    capture.

tools/guide_gates/continuous_conversation_browser_audit.py
    Three complete captured trajectories rendered through real SSE at desktop
    and mobile viewports.

tests/fixtures/guide/conversation/continuous_trajectory_pool_v1.jsonl
    Reviewed pool of independent natural five-turn conversations.

tests/fixtures/guide/conversation/continuous_20x5_v1.jsonl
tests/fixtures/guide/conversation/continuous_20x5_v1_manifest.json
    Frozen backend qualification set and hashes.

docs/audits/continuous-conversation/
    Real capture, replay, browser screenshots, failure ledger, and closure.
```

Existing responsibilities remain in place:

```text
app/guide/application/unified_guide_flow.py
app/guide/intent/unified_turn_router.py
app/guide/intent/reference_admission.py
app/guide/feedback/focus_state.py
app/guide/application/product_evidence_answer.py
app/guide/application/general_knowledge_answer.py
app/guide/presentation/presentation_compiler.py
app/guide/presentation/copywriter_fallback.py
app/guide/application/chat_api_adapter.py
```

Do not create a second router, second state store, or text post-processing
pipeline.

## Task 1: Withdraw The Old Product-Readiness Claim

**Files:**
- Modify: `docs/audits/unified-router/final-closure.md`
- Create: `docs/audits/continuous-conversation/baseline-live-probe.md`
- Test: `tests/guide/runtime/test_continuous_closure_status.py`

- [ ] **Step 1: Write the failing closure-status test**

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_previous_closure_is_superseded_for_product_readiness() -> None:
    text = (
        ROOT
        / "docs/audits/unified-router/final-closure.md"
    ).read_text(encoding="utf-8")

    assert "Status: Superseded for product-readiness" in text
    assert "continuous-conversation-acceptance-design.md" in text
```

- [ ] **Step 2: Run the status test and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/runtime/test_continuous_closure_status.py
```

Expected: FAIL because the old closure still claims product-readiness.

- [ ] **Step 3: Add a non-destructive supersession notice**

Insert at the top of `final-closure.md`:

```markdown
Status: Superseded for product-readiness

The component evidence below remains valid, but product-readiness now follows
`docs/superpowers/specs/2026-08-17-continuous-conversation-acceptance-design.md`.
The replacement gate requires 20 real five-turn backend conversations and a
3-conversation browser sample.
```

Do not delete or rewrite historical evidence.

- [ ] **Step 4: Record the five-turn live-probe baseline**

Create `baseline-live-probe.md` with these frozen observations:

```text
turn 1: recommendation bound products 91 and 38; public concept ID leaked
turn 2: product 38 bound; product-knowledge evidence missing and fallback thin
turn 3: general knowledge correctly zero-card; reviewed answer unavailable
turn 4: return to earlier second product clarified instead of restoring focus
turn 5: product 38 bound; public message leaked "Canonical"
semantic calls: 5
copywriter calls: 0
```

- [ ] **Step 5: Verify GREEN**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/runtime/test_continuous_closure_status.py
```

Expected: `1 passed`.

## Task 2: Build Strict Continuous-Trajectory Contracts

**Files:**
- Create: `tools/guide_gates/continuous_conversation_gate.py`
- Create: `tests/guide/tools/test_continuous_conversation_gate.py`

- [ ] **Step 1: Write RED tests for exact five-turn contracts**

```python
import pytest
from pydantic import ValidationError

from tools.guide_gates.continuous_conversation_gate import (
    ContinuousTrajectory,
)


def test_trajectory_requires_exactly_five_turns() -> None:
    payload = valid_trajectory_payload()
    payload["turns"] = payload["turns"][:4]

    with pytest.raises(ValidationError):
        ContinuousTrajectory.model_validate(payload, strict=True)


def test_trajectory_starts_from_empty_version_zero() -> None:
    payload = valid_trajectory_payload()
    payload["starting_snapshot"] = existing_snapshot().model_dump(
        mode="json"
    )

    with pytest.raises(ValidationError):
        ContinuousTrajectory.model_validate(payload, strict=True)
```

- [ ] **Step 2: Run RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/tools/test_continuous_conversation_gate.py \
  -k "exactly_five or version_zero"
```

Expected: import failure because the gate module does not exist.

- [ ] **Step 3: Add strict frozen contracts**

Implement:

```python
class ContinuousTurnExpectation(_StrictFrozen):
    turn_id: str
    message: str = Field(min_length=1, max_length=4000)
    acceptable_semantic: SemanticExpectation
    expected_bindings: tuple[ResolvedProductBinding, ...] = ()
    expected_route: RouteExpectation
    expected_snapshot_subset: dict[str, JsonValue]
    expected_task_plan_subset: dict[str, JsonValue]
    expected_card_ids: tuple[int, ...] = Field(
        default_factory=tuple,
        max_length=3,
    )
    expected_safety: bool
    expected_clarification: bool
    expected_presentation_mode: PresentationMode | None
    public_answer_policy: Literal[
        "recommendation",
        "comparison",
        "product_knowledge",
        "general_knowledge",
        "consultation",
        "clarification",
        "safety",
    ]


class ContinuousTrajectory(_StrictFrozen):
    schema_version: Literal[
        "guide-continuous-trajectory-v1"
    ] = "guide-continuous-trajectory-v1"
    trajectory_id: str
    subject_scope: Literal["self", "other", "mixed"]
    route_families: tuple[str, ...]
    turns: tuple[
        ContinuousTurnExpectation,
        ContinuousTurnExpectation,
        ContinuousTurnExpectation,
        ContinuousTurnExpectation,
        ContinuousTurnExpectation,
    ]


class ContinuousFailureLayer(str, Enum):
    MODEL_TRANSLATION = "model_translation"
    SEMANTIC_ADMISSION = "semantic_admission"
    IDENTITY_BINDING = "identity_binding"
    ROUTE_SELECTION = "route_selection"
    STATE_TRANSITION = "state_transition"
    DECISION_EXECUTION = "decision_execution"
    DATA_COVERAGE = "data_coverage"
    PUBLIC_PRESENTATION = "public_presentation"


class ContinuousTurnTrace(_StrictFrozen):
    turn_id: str
    starting_version: int = Field(ge=0)
    terminal_version: int = Field(ge=1)
    meaning: TurnMeaning
    bindings: tuple[ResolvedProductBinding, ...]
    route: UnifiedRouteDecision
    task_plan: dict[str, JsonValue]
    card_ids: tuple[int, ...]
    public_messages: tuple[str, ...]
    final_snapshot: ConversationSnapshot


class ContinuousTrajectoryTrace(_StrictFrozen):
    trajectory_id: str
    turns: tuple[
        ContinuousTurnTrace,
        ContinuousTurnTrace,
        ContinuousTurnTrace,
        ContinuousTurnTrace,
        ContinuousTurnTrace,
    ]


class ContinuousRuntime(Protocol):
    state: ConversationStatePort

    def execute(
        self,
        *,
        session_id: str,
        conversation_version: int,
        message: str,
        meaning: TurnMeaning,
    ) -> Iterator[HttpGuideEvent]: ...

    def load_snapshot(
        self,
        session_id: str,
    ) -> ConversationSnapshot: ...
```

- [ ] **Step 4: Add sequence and uniqueness validation**

Validate:

```python
@model_validator(mode="after")
def validate_turn_identity(self) -> Self:
    turn_ids = tuple(turn.turn_id for turn in self.turns)
    if len(turn_ids) != len(set(turn_ids)):
        raise ValueError("turn IDs must be unique")
    if any(
        not turn_id.startswith(f"{self.trajectory_id}-t")
        for turn_id in turn_ids
    ):
        raise ValueError("turn IDs must belong to trajectory")
    return self
```

- [ ] **Step 5: Verify contract GREEN**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/tools/test_continuous_conversation_gate.py
```

Expected: contract tests pass; executor tests remain RED until Task 3.

## Task 3: Execute Real Sequential State Instead Of Snapshot Simulation

**Files:**
- Modify: `tools/guide_gates/continuous_conversation_gate.py`
- Modify: `tests/guide/tools/test_continuous_conversation_gate.py`

- [ ] **Step 1: Write RED for committed snapshot chaining**

```python
def test_each_turn_consumes_previous_terminal_snapshot(tmp_path) -> None:
    runtime = recording_runtime(tmp_path)
    trajectory = five_turn_trajectory()

    trace = execute_continuous_trajectory(
        trajectory,
        runtime=runtime,
        meanings=five_meanings(),
    )

    assert [turn.starting_version for turn in trace.turns] == [
        0, 1, 2, 3, 4,
    ]
    assert [turn.terminal_version for turn in trace.turns] == [
        1, 2, 3, 4, 5,
    ]
    assert runtime.loaded_session_ids == [
        trajectory.trajectory_id,
    ] * 5
```

- [ ] **Step 2: Write RED for no commit before terminal delivery**

```python
def test_interrupted_turn_does_not_feed_next_turn(tmp_path) -> None:
    runtime = recording_runtime(tmp_path, interrupt_turn=3)

    with pytest.raises(ContinuousTrajectoryExecutionError):
        execute_continuous_trajectory(
            five_turn_trajectory(),
            runtime=runtime,
            meanings=five_meanings(),
        )

    stored = runtime.state.load("trajectory-session")
    assert stored is not None
    assert stored.version == 2
```

- [ ] **Step 3: Run both tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/tools/test_continuous_conversation_gate.py \
  -k "consumes_previous or interrupted_turn"
```

Expected: FAIL because the trajectory executor is absent.

- [ ] **Step 4: Implement the sequential executor**

The executor must call the existing unified flow and commit only the terminal
public event:

```python
def execute_continuous_trajectory(
    trajectory: ContinuousTrajectory,
    *,
    runtime: ContinuousRuntime,
    meanings: Sequence[TurnMeaning],
) -> ContinuousTrajectoryTrace:
    if len(meanings) != 5:
        raise ValueError("exactly five meanings are required")
    traces: list[ContinuousTurnTrace] = []
    version = 0
    for ordinal, (turn, meaning) in enumerate(
        zip(trajectory.turns, meanings, strict=True),
        start=1,
    ):
        events = tuple(runtime.execute(
            session_id=trajectory.trajectory_id,
            conversation_version=version,
            message=turn.message,
            meaning=meaning,
        ))
        terminal = require_terminal_event(events)
        commit_http_event_delivery(terminal)
        next_version = terminal.data.conversation_version
        if next_version != version + 1:
            raise ContinuousTrajectoryExecutionError(
                f"turn {ordinal} did not advance exactly once"
            )
        traces.append(build_turn_trace(
            turn=turn,
            meaning=meaning,
            events=events,
            starting_version=version,
            terminal_version=next_version,
            snapshot=runtime.load_snapshot(
                trajectory.trajectory_id
            ),
        ))
        version = next_version
    return ContinuousTrajectoryTrace(
        trajectory_id=trajectory.trajectory_id,
        turns=tuple(traces),
    )
```

Do not manually mutate snapshots inside the gate.

- [ ] **Step 5: Verify sequence GREEN**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/tools/test_continuous_conversation_gate.py
```

Expected: sequential execution and delayed-commit tests pass.

## Task 4: Make Every Public Message Structurally Safe

**Files:**
- Create: `app/guide/presentation/public_language.py`
- Modify: `app/guide/application/chat_api_adapter.py`
- Modify: `app/guide/application/product_evidence_answer.py`
- Modify: `app/guide/application/general_knowledge_answer.py`
- Modify: `app/guide/presentation/presentation_compiler.py`
- Test: `tests/guide/presentation/test_public_language.py`
- Test: `tests/guide/application/test_product_evidence_answer.py`
- Test: `tests/guide/application/test_general_knowledge_answer.py`
- Test: `tests/guide/application/test_chat_api_adapter.py`

- [ ] **Step 1: Write RED for the two observed leaks**

```python
@pytest.mark.parametrize(
    "text",
    (
        "已按审核后的 Canonical 商品事实检查该商品。",
        "这款对 texture.lightweight 有已审核证据支持。",
    ),
)
def test_public_language_rejects_internal_vocabulary(text: str) -> None:
    with pytest.raises(PublicLanguageError):
        validate_public_text(text)
```

- [ ] **Step 2: Write RED for every public message event**

```python
def test_collector_rejects_internal_language_in_message_event() -> None:
    events = valid_product_knowledge_events()
    events[-2] = MessageEvent(
        content="已按 Canonical 商品事实检查。",
        done=False,
    )

    with pytest.raises(GuideEventContractError):
        collect_guide_events(events)
```

- [ ] **Step 3: Run RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/presentation/test_public_language.py \
  tests/guide/application/test_chat_api_adapter.py \
  -k "internal_vocabulary or internal_language"
```

Expected: FAIL because public message events are not centrally validated.

- [ ] **Step 4: Implement structural public validation**

Implement:

```python
INTERNAL_PUBLIC_PATTERNS = (
    re.compile(r"\bCanonical\b", re.IGNORECASE),
    re.compile(
        r"\b(?:texture|efficacy|suitable_skin|skin_concern)"
        r"\.[a-z0-9_]+\b",
        re.IGNORECASE,
    ),
    re.compile(r"已审核证据支持"),
    re.compile(r"代码核对|硬条件|证据等级|放行"),
)


def validate_public_text(text: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise PublicLanguageError("public text must be nonempty")
    if any(pattern.search(text) for pattern in INTERNAL_PUBLIC_PATTERNS):
        raise PublicLanguageError("public text contains internal language")
    return text
```

This is a fail-closed validator, not a string replacement.

- [ ] **Step 5: Replace internal producers at their source**

In recommendation and product-evidence answer builders:

```python
def _natural_preference_label(
    requirement: RelativeRequirement,
) -> str:
    if requirement.dimension == "texture":
        return requirement.raw_text or "更贴近当前肤感偏好"
    return requirement.raw_text or "更贴近当前需求"
```

In suitability fallback, replace audit narration with:

```text
现有资料还不足以判断它一定适合你现在的状态。最近使用产品会刺痛时，
先暂停叠加新品；皮肤稳定后再少量试用，并观察是否再次出现不适。
```

The content is selected from typed safety and evidence state, not by replacing
observed words.

- [ ] **Step 6: Apply validation to all public text surfaces**

Validate:

- `message.content`;
- presentation `copy_text`;
- presentation `advisor_reason`;
- public clarification text;
- public error text.

Do not validate internal audit artifacts.

- [ ] **Step 7: Verify GREEN and regression**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/presentation/test_public_language.py \
  tests/guide/application/test_product_evidence_answer.py \
  tests/guide/application/test_general_knowledge_answer.py \
  tests/guide/application/test_chat_api_adapter.py \
  tests/guide/presentation
```

Expected: PASS with no internal-language surface.

## Task 5: Separate Product Knowledge From Recommendation Fallback

**Files:**
- Modify: `app/guide/application/product_evidence_answer.py`
- Modify: `app/guide/presentation/copywriter_fallback.py`
- Modify: `app/guide/presentation/presentation_packet.py`
- Modify: `app/guide/presentation/presentation_compiler.py`
- Test: `tests/guide/application/test_product_evidence_answer.py`
- Test: `tests/guide/presentation/test_copywriter_fallback.py`
- Test: `tests/guide/presentation/test_presentation_packet.py`

- [ ] **Step 1: Write RED for a texture-and-usage follow-up**

```python
def test_product_knowledge_missing_fields_stays_direct() -> None:
    result = answer_product_evidence(
        product_id=38,
        question_meaning="质地和用法",
        evidence=product_38_without_texture_or_usage(),
    )

    assert result.mode == "product_knowledge"
    assert result.visible_product_ids == (38,)
    assert result.missing_fields == ("texture", "usage")
    assert "当前资料没有覆盖它的质地和具体用法" in result.message
    assert "推荐理由" not in result.message
```

- [ ] **Step 2: Write RED for section duties**

```python
def test_product_knowledge_fallback_has_no_closing_or_pitfalls() -> None:
    contract = compile_product_knowledge_fallback(
        packet=missing_texture_usage_packet()
    )
    kinds = tuple(section.kind for section in contract.sections)

    assert kinds == ("product", "full_cards")
```

- [ ] **Step 3: Run RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/application/test_product_evidence_answer.py \
  tests/guide/presentation/test_copywriter_fallback.py \
  -k "missing_fields_stays_direct or no_closing"
```

Expected: FAIL on recommendation-style follow-up framing.

- [ ] **Step 4: Implement typed missing-field answers**

Add:

```python
class ProductKnowledgeCoverage(_StrictFrozen):
    requested_fields: tuple[str, ...]
    supported_fields: tuple[str, ...]
    missing_fields: tuple[str, ...]


def build_missing_evidence_copy(
    coverage: ProductKnowledgeCoverage,
) -> str:
    labels = tuple(
        PRODUCT_KNOWLEDGE_FIELD_LABELS[field]
        for field in coverage.missing_fields
    )
    joined = "和".join(labels)
    return (
        f"当前已核对资料没有覆盖它的{joined}，"
        "所以这里不凭商品名或同系列信息猜测。"
    )
```

`PRODUCT_KNOWLEDGE_FIELD_LABELS` is a closed field-label map, not a user
phrase dictionary.

- [ ] **Step 5: Compile product knowledge through its own policy**

Ensure product knowledge emits:

```text
product title
inline card
direct supported or missing-field answer
one bottom card
```

It must not emit recommendation summary, advisor reason, closing, or
pitfalls.

- [ ] **Step 6: Verify GREEN**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/application/test_product_evidence_answer.py \
  tests/guide/presentation/test_copywriter_fallback.py \
  tests/guide/presentation/test_presentation_packet.py
```

Expected: PASS.

## Task 6: Diagnose And Repair Return-To-Focus At The Earliest Layer

**Files:**
- Inspect:
  `app/guide/adapters/llm/turn_meaning_prompt.py`
- Inspect:
  `app/guide/intent/reference_admission.py`
- Inspect:
  `app/guide/intent/unified_turn_router.py`
- Inspect:
  `app/guide/feedback/focus_state.py`
- Modify: exactly the first owning file identified by Step 3
- Test: `tests/guide/application/test_unified_guide_flow.py`
- Test: `tests/guide/intent/test_reference_admission.py`
- Test: `tests/guide/intent/test_unified_turn_router.py`

- [ ] **Step 1: Freeze the exact cross-mode trajectory**

```text
turn 1: recommend repair serums
turn 2: ask about the second product
turn 3: ask unrelated general knowledge
turn 4: return to the earlier second product and ask suitability
turn 5: revise the original budget and recommend again
```

- [ ] **Step 2: Add one integration RED test**

```python
def test_general_knowledge_detour_can_return_to_prior_second_product() -> None:
    flow = unified_flow_with_meanings(
        recommendation_meaning(),
        second_product_meaning(),
        general_knowledge_meaning(),
        return_to_prior_second_meaning(),
    )

    deliver(flow, turn("推荐修护精华", version=0))
    deliver(flow, turn("第二款呢", version=1))
    deliver(flow, turn("烟酰胺是什么", version=2))
    events = deliver(
        flow,
        turn("回到刚才第二款，它适合我现在吗", version=3),
    )

    assert route(events).processor == "product_knowledge"
    assert card_ids(events) == [38]
    assert snapshot(flow).focus_state.current_product_id == 38
```

- [ ] **Step 3: Run RED and inspect the first wrong artifact**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/application/test_unified_guide_flow.py \
  -k "return_to_prior_second_product" -vv
```

Expected: FAIL. Record whether the first wrong value is:

```text
TurnMeaning.continuity_hint
admitted ReferenceDraft
UnifiedRouteDecision
FocusState.current_product_id
```

- [ ] **Step 4: Fix only the diagnosed owner**

Apply exactly one of these general corrections:

```text
model_translation:
  prompt defines return-to-focus independently from current active mode

semantic_admission:
  an admitted ordinal may target the preserved candidate batch when
  continuity is return_to_focus

route_selection:
  return_to_focus resolves preserved product focus before current knowledge
  focus

state_transition:
  general knowledge changes active_processor but does not clear preserved
  product and candidate focus
```

Do not add a branch for the observed Chinese sentence.

- [ ] **Step 5: Verify focused GREEN**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/application/test_unified_guide_flow.py \
  tests/guide/intent/test_reference_admission.py \
  tests/guide/intent/test_unified_turn_router.py \
  tests/guide/feedback/test_focus_state.py
```

Expected: PASS.

## Task 7: Admit Cross-Language Question Meaning In Knowledge Retrieval

**Files:**
- Modify: `app/guide/retrieval/general_knowledge_retrieval.py`
- Test: `tests/guide/retrieval/test_general_knowledge_retrieval.py`
- Test: `tests/guide/application/test_general_knowledge_answer.py`

- [ ] **Step 1: Prove the reviewed source assets already exist**

Run:

```bash
rg -n "烟酰胺" data/knowledge_docs/13-烟酰胺适合谁.md
rg -n "视黄醇|A醇" data/knowledge_docs/14-视黄醇A醇适合谁.md
```

Expected: both reviewed source documents contain usable explanatory content.
Do not add another knowledge document for the observed sentence.

- [ ] **Step 2: Write RED for bilingual semantic meaning**

```python
def test_chinese_question_with_english_meaning_keeps_raw_anchors() -> None:
    packet = retriever.retrieve(GeneralKnowledgeQuery(
        raw_question="烟酰胺和视黄醇是不是一回事？",
        question_meaning=(
            "Are niacinamide and retinol the same ingredient?"
        ),
        prior_knowledge_ids=(),
        safety_sensitive=False,
        top_k=5,
    ))

    source_paths = {
        hit.block.source_path
        for hit in packet.hits
    }
    assert (
        "data/knowledge_docs/13-烟酰胺适合谁.md"
        in source_paths
    )
    assert (
        "data/knowledge_docs/14-视黄醇A醇适合谁.md"
        in source_paths
    )
```

- [ ] **Step 3: Run RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/retrieval/test_general_knowledge_retrieval.py \
  -k "english_meaning_keeps_raw_anchors"
```

Expected: FAIL because `anchor_terms` currently requires exact term
intersection between Chinese `raw_question` and English
`question_meaning`.

- [ ] **Step 4: Fix the retrieval responsibility boundary**

Replace cross-language intersection gating:

```python
raw_terms = frozenset(
    general_knowledge_terms(query.raw_question)
)
meaning_terms = frozenset(
    general_knowledge_terms(query.question_meaning)
)
query_terms = raw_terms.union(meaning_terms)
anchor_terms = raw_terms
```

The source-bound raw question remains the admission anchor. A semantically
correct translation may expand retrieval, but a different output language
cannot erase raw anchors.

- [ ] **Step 5: Add a same-language regression**

```python
def test_same_language_question_meaning_keeps_existing_order() -> None:
    original = retriever.retrieve(sunscreen_reapply_query())
    expanded = retriever.retrieve(
        sunscreen_reapply_query().model_copy(
            update={"question_meaning": "防晒为什么需要补涂"},
            deep=True,
        )
    )

    assert tuple(
        hit.block.knowledge_id for hit in expanded.hits
    ) == tuple(
        hit.block.knowledge_id for hit in original.hits
    )
```

- [ ] **Step 6: Verify GREEN and broad retrieval**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/retrieval/test_general_knowledge_retrieval.py \
  tests/guide/application/test_general_knowledge_answer.py \
  tests/guide/retrieval/test_general_knowledge_assets.py
```

Expected: PASS.

## Task 8: Freeze Twenty Independent Five-Turn Trajectories

**Files:**
- Create: `tools/guide_gates/continuous_conversation_fixture.py`
- Create:
  `tests/fixtures/guide/conversation/continuous_trajectory_pool_v1.jsonl`
- Create:
  `tests/fixtures/guide/conversation/continuous_20x5_v1.jsonl`
- Create:
  `tests/fixtures/guide/conversation/continuous_20x5_v1_manifest.json`
- Create: `tests/guide/tools/test_continuous_conversation_fixture.py`

- [ ] **Step 1: Write RED for pool and frozen-set independence**

```python
def test_frozen_set_has_twenty_independent_five_turn_trajectories() -> None:
    trajectories = load_frozen_trajectories()

    assert len(trajectories) == 20
    assert all(len(item.turns) == 5 for item in trajectories)
    assert len({
        normalize_message(turn.message)
        for item in trajectories
        for turn in item.turns
    }) == 100
    assert no_simple_paraphrase_pairs(trajectories)
```

- [ ] **Step 2: Write RED for coverage**

```python
def test_frozen_set_covers_all_stateful_route_families() -> None:
    families = {
        family
        for item in load_frozen_trajectories()
        for family in item.route_families
    }
    assert {
        "recommendation_revision",
        "product_followup",
        "general_knowledge_return",
        "comparison",
        "consultation_profile",
        "other_person_isolation",
        "image_identity",
        "image_similarity",
        "clarification_recovery",
        "safety_escalation",
        "pending_turn",
    } <= families
```

- [ ] **Step 3: Run RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/tools/test_continuous_conversation_fixture.py
```

Expected: FAIL because the fixture pool does not exist.

- [ ] **Step 4: Author the reviewed pool**

Create at least thirty independent trajectories. Each trajectory contains
five full natural messages and frozen expected duties. Include the observed
live-probe route as one trajectory, but do not use its exact wording in any
other trajectory.

Required pool distribution:

```text
8 shopping/follow-up/revision trajectories
5 knowledge/product-focus-switch trajectories
5 consultation/profile trajectories
5 image/comparison trajectories
4 clarification/safety/PendingTurn trajectories
3 other-person/session-isolation trajectories
```

- [ ] **Step 5: Select twenty with a frozen seed**

Implement:

```python
BACKEND_SELECTION_SEED = 2026081701


def select_backend_trajectories(
    pool: Sequence[ContinuousTrajectory],
) -> tuple[ContinuousTrajectory, ...]:
    selected = random.Random(
        BACKEND_SELECTION_SEED
    ).sample(tuple(pool), 20)
    return tuple(sorted(
        selected,
        key=lambda item: item.trajectory_id,
    ))
```

Write canonical JSONL and a SHA-256 manifest before any provider call.

- [ ] **Step 6: Verify fixture GREEN**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/tools/test_continuous_conversation_fixture.py
```

Expected: PASS with exactly 20 trajectories and 100 unique turns.

## Task 9: Implement The Real 20-By-5 Capture And Offline Replay

**Files:**
- Create: `tools/guide_gates/run_real_continuous_conversation_gate.py`
- Modify: `tools/guide_gates/continuous_conversation_gate.py`
- Create: `tests/guide/tools/test_run_real_continuous_conversation_gate.py`
- Create:
  `docs/audits/continuous-conversation/backend-20x5-real-v1.json`
- Create:
  `docs/audits/continuous-conversation/backend-20x5-replay-v1.json`
- Create:
  `docs/audits/continuous-conversation/failure-ledger.md`

- [ ] **Step 1: Write RED for exact provider budget**

```python
def test_real_gate_calls_provider_once_per_turn_and_never_copywriter(
    tmp_path,
) -> None:
    adapter = RecordingTurnMeaningAdapter(five_meanings_per_trajectory())
    copywriter = ForbiddenCopywriter()

    report = run_real_continuous_gate(
        trajectories=two_trajectories(),
        adapter=adapter,
        copywriter=copywriter,
        state_root=tmp_path / "state",
        output_path=tmp_path / "capture.json",
    )

    assert report.turn_count == 10
    assert report.provider_call_count == 10
    assert report.copywriter_call_count == 0
    assert adapter.call_count == 10
```

- [ ] **Step 2: Write RED for captured replay**

```python
def test_captured_replay_uses_zero_provider_calls(tmp_path) -> None:
    report = replay_captured_continuous_gate(
        trajectories=two_trajectories(),
        capture_path=captured_provider_outputs(),
        state_root=tmp_path / "replay-state",
        output_path=tmp_path / "replay.json",
    )

    assert report.provider_call_count == 0
    assert report.copywriter_call_count == 0
    assert report.replayed_turn_count == 10
```

- [ ] **Step 3: Run RED**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/tools/test_run_real_continuous_conversation_gate.py
```

Expected: FAIL because the real runner is absent.

- [ ] **Step 4: Implement one-call capture**

The runner:

- loads the frozen manifest;
- creates one empty session per trajectory;
- calls only `TurnMeaningPort` once per turn;
- executes the actual Unified Router flow;
- records all per-turn artifacts;
- never retries or repairs provider output;
- never calls the copywriter;
- persists the artifact after each completed trajectory.

- [ ] **Step 5: Implement earliest-layer evaluation**

Evaluation order is fixed:

```python
LAYER_ORDER = (
    ContinuousFailureLayer.MODEL_TRANSLATION,
    ContinuousFailureLayer.SEMANTIC_ADMISSION,
    ContinuousFailureLayer.IDENTITY_BINDING,
    ContinuousFailureLayer.ROUTE_SELECTION,
    ContinuousFailureLayer.STATE_TRANSITION,
    ContinuousFailureLayer.DECISION_EXECUTION,
    ContinuousFailureLayer.DATA_COVERAGE,
    ContinuousFailureLayer.PUBLIC_PRESENTATION,
)
```

Exactly one earliest layer is stored for each failed turn.

- [ ] **Step 6: Verify runner GREEN with fakes**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/tools/test_run_real_continuous_conversation_gate.py \
  tests/guide/tools/test_continuous_conversation_gate.py
```

Expected: PASS without network access.

- [ ] **Step 7: Run the frozen real backend gate once**

Before running, report:

```text
100 semantic calls
0 copywriter calls
0 retries
```

Run:

```bash
.venv/bin/python -m \
  tools.guide_gates.run_real_continuous_conversation_gate \
  --cases \
  tests/fixtures/guide/conversation/continuous_20x5_v1.jsonl \
  --manifest \
  tests/fixtures/guide/conversation/continuous_20x5_v1_manifest.json \
  --output \
  docs/audits/continuous-conversation/backend-20x5-real-v1.json \
  --disable-copywriter
```

Do not change expected results after provider output is visible.

- [ ] **Step 8: Audit every failed turn before editing code**

Write `failure-ledger.md` with:

```text
trajectory ID and turn
raw message
first incorrect artifact
earliest layer
responsibility boundary
general fix or data correction
why a phrase patch is rejected
```

- [ ] **Step 9: Add one RED test per diagnosed responsibility**

For each new failure, add the smallest reproduction to the owning module's
test file. Do not implement until every failure has an earliest layer.

- [ ] **Step 10: Implement general corrections and replay**

After each GREEN fix, run:

```bash
.venv/bin/python -m \
  tools.guide_gates.run_real_continuous_conversation_gate \
  --replay \
  docs/audits/continuous-conversation/backend-20x5-real-v1.json \
  --cases \
  tests/fixtures/guide/conversation/continuous_20x5_v1.jsonl \
  --manifest \
  tests/fixtures/guide/conversation/continuous_20x5_v1_manifest.json \
  --output \
  docs/audits/continuous-conversation/backend-20x5-replay-v1.json
```

Required:

```text
replayed turns = 100
provider calls = 0
copywriter calls = 0
passed turns = 100
passed trajectories = 20
```

## Task 10: Render Three Complete Random Conversations In The Browser

**Files:**
- Create: `tools/guide_gates/continuous_conversation_browser_audit.py`
- Create: `tests/guide/tools/test_continuous_conversation_browser_audit.py`
- Create:
  `docs/audits/continuous-conversation/browser-3x5-v1.json`
- Create:
  `docs/audits/continuous-conversation/screenshots/`

- [ ] **Step 1: Write RED for frozen random selection**

```python
def test_browser_sample_is_three_complete_trajectories() -> None:
    selected = select_browser_trajectories(
        frozen_backend_trajectories(),
        passed_trajectory_ids=passing_backend_ids(),
    )

    assert len(selected) == 3
    assert sum(len(item.turns) for item in selected) == 15
    assert required_browser_families(selected) == {
        "general_knowledge_return",
        "consultation_profile",
        "image_or_comparison",
    }
```

- [ ] **Step 2: Implement frozen browser selection**

```python
BROWSER_SELECTION_SEED = 2026081702


def select_browser_trajectories(
    trajectories: Sequence[ContinuousTrajectory],
    *,
    passed_trajectory_ids: frozenset[str],
) -> tuple[ContinuousTrajectory, ...]:
    eligible = tuple(
        item for item in trajectories
        if item.trajectory_id in passed_trajectory_ids
    )
    required = (
        "general_knowledge_return",
        "consultation_profile",
        "image_or_comparison",
    )
    randomizer = random.Random(BROWSER_SELECTION_SEED)
    for candidate in randomizer.sample(
        list(combinations(eligible, 3)),
        k=math.comb(len(eligible), 3),
    ):
        families = {
            family
            for trajectory in candidate
            for family in trajectory.route_families
        }
        if families.intersection({
            "image_identity",
            "image_similarity",
            "image_comparison",
            "comparison",
        }):
            families.add("image_or_comparison")
        if set(required) <= families:
            return tuple(sorted(
                candidate,
                key=lambda item: item.trajectory_id,
            ))
    raise ValueError(
        "passing trajectories cannot cover browser families"
    )
```

Selection is written to the browser artifact before rendering.

- [ ] **Step 3: Write RED for real sequential browser rendering**

```python
def test_browser_audit_renders_all_fifteen_turns() -> None:
    report = load_browser_report()

    assert report.trajectory_count == 3
    assert report.turn_count == 15
    assert {
        (row.trajectory_id, row.turn_ordinal)
        for row in report.turns
    } == expected_fifteen_turn_keys()
```

- [ ] **Step 4: Implement browser execution**

Use Playwright headless Chromium:

```text
load /chat
reuse captured TurnMeaning for each turn
send through the real HTTP/SSE runtime
allow at most one copywriter call per turn
wait for activeChatRequests.size === 0
capture SSE, DOM metrics, console, network, and screenshot
advance the same browser session to the next turn
```

Render the same captured output at:

```text
desktop: 1440 x 900
mobile: 390 x 844
```

Do not make another semantic provider call.

- [ ] **Step 5: Enforce fifteen-turn acceptance**

Each turn requires:

```python
assert row.copywriter_call_count <= 1
assert row.internal_public_term_count == 0
assert row.console_errors == ()
assert row.network_failures == ()
assert row.image_failures == ()
assert row.horizontal_overflow is False
assert row.overlap_count == 0
assert row.clipped_text_count == 0
assert row.thinking_removed_after_first_character is True
assert row.inline_card_ids == row.expected_card_ids
assert row.bottom_card_ids == row.expected_card_ids
```

Zero-card modes compare against an empty tuple.

- [ ] **Step 6: Run the browser gate**

Run:

```bash
.venv/bin/python -m \
  tools.guide_gates.continuous_conversation_browser_audit \
  --backend-capture \
  docs/audits/continuous-conversation/backend-20x5-real-v1.json \
  --backend-replay \
  docs/audits/continuous-conversation/backend-20x5-replay-v1.json \
  --output \
  docs/audits/continuous-conversation/browser-3x5-v1.json
```

Required:

```text
trajectories = 3
turns = 15
semantic calls = 0
copywriter calls <= 15
passed turns = 15
desktop defects = 0
mobile defects = 0
```

Any browser failure is still assigned to the same earliest-layer taxonomy.
Do not fix CSS when the backend emitted the wrong card or text.

## Task 11: Full Regression And New Closure

**Files:**
- Create:
  `docs/audits/continuous-conversation/final-closure.md`
- Modify:
  `docs/superpowers/plans/2026-08-17-continuous-conversation-closure.md`

- [ ] **Step 1: Run focused suites**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/intent \
  tests/guide/feedback \
  tests/guide/application \
  tests/guide/presentation \
  tests/guide/retrieval \
  tests/guide/runtime \
  tests/guide/tools/test_continuous_conversation_gate.py \
  tests/guide/tools/test_run_real_continuous_conversation_gate.py \
  tests/guide/tools/test_continuous_conversation_fixture.py \
  tests/guide/tools/test_continuous_conversation_browser_audit.py
```

Expected: PASS.

- [ ] **Step 2: Run complete pytest**

Run:

```bash
.venv/bin/python -m pytest -q
```

Expected: PASS with no new warning category.

- [ ] **Step 3: Verify lifecycle invariants**

Run the existing focused lifecycle set for:

```text
refresh
cross-worker continuation
stale CAS
two-session isolation
disconnect discard
owner-scoped deletion
```

Expected: PASS.

- [ ] **Step 4: Write final closure**

Record:

```text
first-pass complete-trajectory rate
all earliest-layer classifications
zero-tolerance counters
100/100 captured replay
3/3 browser trajectories and 15/15 turns
desktop and mobile defects
semantic and copywriter call counts
focused and full pytest counts
source, fixture, capture, replay, and screenshot hashes
feature flag and rollback command
no-production-deployment statement
```

- [ ] **Step 5: Perform Final Completion Audit**

Do not declare completion unless:

```text
first pass >= 18/20 complete trajectories
all critical counters = 0
captured replay = 100/100
browser = 15/15
focused pytest passes
full pytest passes
no production deployment
```

The one-to-two-hour target is advisory. Missing evidence or an architecture
defect cannot be waived for time.

## Execution Notes

- Work only in `/Users/bytedance/Desktop/xiaoro-fresh` on `rebuild`.
- Preserve all unrelated dirty-worktree changes.
- Use `apply_patch` for manual edits.
- Main Agent executes every task; no subagents.
- Do not commit unless the user explicitly requests a commit. The worktree is
  intentionally dirty, so verification artifacts replace automatic commit
  checkpoints.
- Before each real API run, state the exact semantic and copywriter call
  budget.
- After each fix, replay captured outputs before considering another provider
  call.
