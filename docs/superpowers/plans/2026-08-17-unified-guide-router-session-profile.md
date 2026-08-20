# Unified Guide Router And Session Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a reversible unified Guide router, dynamic light
consultation, session-only profile, complete specification projection, and
mode-specific presentation, then prove them with independent real-model and
browser gates.

**Architecture:** Keep Canonical identity, `SelectionFact`, ranking,
`PendingTurn`, SQLite CAS, and typed SSE as the decision spine. Add strict
admission, focus, session-profile, and route contracts around the existing
processors. Put the new router behind one environment flag; keep product data
and presentation fixes independent so they remain valid if the flag is off.

**Tech Stack:** Python 3.11, Pydantic v2, FastAPI, SQLite WAL/CAS, pytest,
typed SSE, vanilla JavaScript, Playwright, DeepSeek-compatible JSON API.

---

## File Structure

New focused modules:

```text
app/guide/retrieval/card_specification.py
    SKU-aware specification selection from reviewed SelectionFacts.

app/guide/feedback/session_profile.py
    Session-only profile contracts and source-aware reducer.

app/guide/feedback/focus_state.py
    Independent product, batch, image, knowledge, and processor focus.

app/guide/intent/semantic_admission.py
    Auditable admitted/retained/deferred/rejected outcomes.

app/guide/intent/unified_turn_router.py
    Pure local processor, continuity, and focus decision.

app/guide/application/unified_guide_flow.py
    One-call semantic orchestration and delegation to existing processors.

app/guide/application/dynamic_consultation.py
    Observation reducer, provisional assessment gate, and next-gap choice.

tools/guide_gates/unified_router_gate.py
    Offline end-to-end replay and earliest-distortion classification.

tools/guide_gates/run_real_unified_router_gate.py
    One-call real-model capture with no copywriter call.
```

Existing modules remain responsible for their established behavior. Do not
move ranking or hard-filter code into the router.

## Task 1: Freeze Baseline And Add The Reversible Flag

**Files:**
- Modify: `app/guide_runtime/llm_config.py`
- Modify: `app/guide_runtime/app.py`
- Modify: `app/guide_runtime/composition.py`
- Test: `tests/guide/runtime/test_llm_config.py`
- Test: `tests/guide/runtime/test_runtime_http.py`

- [ ] **Step 1: Capture the current focused baseline**

Run:

```bash
pytest -q \
  tests/guide/runtime/test_llm_config.py \
  tests/guide/runtime/test_runtime_http.py \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/application/test_consultation_chat_flow.py \
  tests/guide/application/test_image_recommendation_flow.py
```

Expected: existing tests pass. Save the output under
`docs/audits/unified-router/baseline.txt`.

- [ ] **Step 2: Write failing flag tests**

Add tests asserting:

```python
def test_unified_router_defaults_disabled(monkeypatch):
    monkeypatch.delenv("GUIDE_UNIFIED_ROUTER_ENABLED", raising=False)
    assert GuideRuntimeFlags.from_environment().unified_router is False


def test_unified_router_accepts_explicit_true(monkeypatch):
    monkeypatch.setenv("GUIDE_UNIFIED_ROUTER_ENABLED", "true")
    assert GuideRuntimeFlags.from_environment().unified_router is True


def test_unified_router_rejects_unknown_boolean(monkeypatch):
    monkeypatch.setenv("GUIDE_UNIFIED_ROUTER_ENABLED", "sometimes")
    with pytest.raises(ValueError, match="GUIDE_UNIFIED_ROUTER_ENABLED"):
        GuideRuntimeFlags.from_environment()
```

- [ ] **Step 3: Run the tests and verify RED**

Run:

```bash
pytest -q tests/guide/runtime/test_llm_config.py -k unified_router
```

Expected: FAIL because `GuideRuntimeFlags` does not exist.

- [ ] **Step 4: Implement strict runtime flags**

Add:

```python
@dataclass(frozen=True, slots=True)
class GuideRuntimeFlags:
    unified_router: bool

    @classmethod
    def from_environment(cls) -> Self:
        return cls(
            unified_router=_read_bool(
                "GUIDE_UNIFIED_ROUTER_ENABLED",
                default=False,
            )
        )


def _read_bool(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(f"{name} must be true or false")
```

Expose the active router name in `/health` without exposing credentials.

- [ ] **Step 5: Verify GREEN and old-path parity**

Run:

```bash
pytest -q \
  tests/guide/runtime/test_llm_config.py \
  tests/guide/runtime/test_runtime_http.py
```

Expected: PASS with the flag absent and explicitly false.

- [ ] **Step 6: Commit the isolated flag**

```bash
git add \
  app/guide_runtime/llm_config.py \
  app/guide_runtime/app.py \
  app/guide_runtime/composition.py \
  tests/guide/runtime/test_llm_config.py \
  tests/guide/runtime/test_runtime_http.py \
  docs/audits/unified-router/baseline.txt
git commit -m "feat(guide): add reversible unified router flag"
```

## Task 2: Preserve Exact Variant Identity And Resolve Card Specifications

**Files:**
- Create: `app/guide/retrieval/card_specification.py`
- Modify: `app/guide/retrieval/product_name_resolver.py`
- Modify: `app/guide/retrieval/controlled_product_aliases.py`
- Modify: `app/guide/presentation/contracts.py`
- Modify: `app/guide/presentation/response_planning.py`
- Modify: `app/guide/application/text_recommendation_flow.py`
- Modify: `app/guide/application/image_recommendation_flow.py`
- Test: `tests/guide/retrieval/test_product_name_resolver.py`
- Test: `tests/guide/retrieval/test_card_specification.py`
- Test: `tests/guide/presentation/test_response_planning.py`
- Test: `tests/guide/runtime/test_frontend_card_binding.py`

- [ ] **Step 1: Write RED tests for variant preservation**

Add:

```python
def test_exact_variant_alias_preserves_variant_scope(registry, resolver):
    result = resolver.resolve(
        message="看看高潮腮红",
        mentions=(
            SemanticProductMention(
                text="高潮腮红",
                start=2,
                end=6,
            ),
        ),
    )
    assert result.bindings == (
        ResolvedProductBinding(
            product_id=117,
            variant_scope="4013色号",
            source_text="高潮腮红",
        ),
    )
```

Also assert exact-product aliases have `variant_scope=None`, ambiguous-family
aliases remain clarification, and duplicate product IDs with different
variants are not silently collapsed.

- [ ] **Step 2: Run the resolver RED test**

Run:

```bash
pytest -q \
  tests/guide/retrieval/test_product_name_resolver.py \
  -k "variant_scope or ambiguous_family"
```

Expected: FAIL because the current resolver returns only `product_ids`.

- [ ] **Step 3: Add a typed resolved binding**

Implement:

```python
class ResolvedProductBinding(_StrictFrozen):
    product_id: int = Field(gt=0)
    variant_scope: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
    )
    source_text: str = Field(min_length=1, max_length=160)


class ProductMentionResolution(_StrictFrozen):
    bindings: tuple[ResolvedProductBinding, ...]
    issue: ProductResolutionIssue | None = None

    @property
    def product_ids(self) -> tuple[int, ...]:
        return tuple(dict.fromkeys(item.product_id for item in self.bindings))
```

Use `ControlledProductAliasRecord.variant_scope` when an exact-variant alias
is the admitted surface. Preserve compatibility through the `product_ids`
property while migrating consumers.

- [ ] **Step 4: Write RED tests for specification selection**

Cover:

```python
def test_exact_product_specification_is_used():
    assert resolve_card_specification(
        facts=(exact_product("50ml"),),
        variant_scope=None,
    ) == "50ml"


def test_matching_exact_variant_wins():
    assert resolve_card_specification(
        facts=(
            exact_product("50ml"),
            exact_variant("30ml", scope="travel"),
        ),
        variant_scope="travel",
    ) == "30ml"


def test_conflicting_unbound_variants_are_omitted():
    assert resolve_card_specification(
        facts=(
            exact_variant("50ml", scope="regular"),
            exact_variant("30ml", scope="travel"),
        ),
        variant_scope=None,
    ) is None
```

Include real product assertions for product `33` (`50ml`), product `129`
(`50ml`), and every accepted product with a unique reviewed `net_content`.

- [ ] **Step 5: Implement `resolve_card_specification`**

```python
def resolve_card_specification(
    facts: Sequence[SelectionFact],
    *,
    variant_scope: str | None,
) -> str | None:
    candidates = tuple(
        fact
        for fact in facts
        if fact.field_key == "net_content"
        and "compare" in fact.capabilities
        and fact.safety_role == "ordinary"
    )
    if variant_scope is not None:
        exact = {
            fact.normalized_value
            for fact in candidates
            if (
                fact.subject_scope == "exact_variant"
                and fact.variant_scope == variant_scope
            )
        }
        if len(exact) == 1:
            return next(iter(exact))
        if len(exact) > 1:
            return None
    product_values = {
        fact.normalized_value
        for fact in candidates
        if (
            fact.subject_scope == "exact_product"
            and fact.variant_scope is None
        )
    }
    return (
        next(iter(product_values))
        if len(product_values) == 1
        else None
    )
```

Do not parse capacity from product names or evidence prose.

- [ ] **Step 6: Audit missing reviewed specifications**

Add a test-driven audit that reports accepted `product_specification` blocks
whose explicit capacity relation has no `net_content` selection projection.
Manually review each report row. Add projections only where the source
already binds a unique product or exact variant. Regenerate content-addressed
product-evidence and selection assets with the existing build scripts.

Run:

```bash
python -m tools.guide_data.audit_product_evidence_uses \
  --repo-root /Users/bytedance/Desktop/xiaoro-fresh
pytest -q tests/guide/data/test_evidence_use_baseline.py
```

Expected: zero unreviewed unique specification gaps.

- [ ] **Step 7: Project one specification into all card forms**

Add `variant_scope` and `specification` to `ProductCardFacts` and
`ProductCard`. Populate them before public projection. Ensure
`presentation_packet._locked_facts` uses `card.specification`, so inline
cards, direct facts, and full cards cannot disagree.

- [ ] **Step 8: Run specification and card suites**

```bash
pytest -q \
  tests/guide/retrieval/test_product_name_resolver.py \
  tests/guide/retrieval/test_card_specification.py \
  tests/guide/presentation/test_response_planning.py \
  tests/guide/runtime/test_frontend_card_binding.py
```

Expected: PASS; no specification appears for an ambiguous SKU.

- [ ] **Step 9: Commit identity and specification projection**

```bash
git add \
  app/guide/retrieval/card_specification.py \
  app/guide/retrieval/product_name_resolver.py \
  app/guide/retrieval/controlled_product_aliases.py \
  app/guide/presentation/contracts.py \
  app/guide/presentation/response_planning.py \
  app/guide/application/text_recommendation_flow.py \
  app/guide/application/image_recommendation_flow.py \
  tests/guide/retrieval/test_product_name_resolver.py \
  tests/guide/retrieval/test_card_specification.py \
  tests/guide/presentation/test_response_planning.py \
  tests/guide/runtime/test_frontend_card_binding.py \
  data/guide_product_evidence \
  data/guide_selection_concepts
git commit -m "fix(guide): preserve variants and project card specifications"
```

## Task 3: Enforce Mode-Specific Presentation Duties

**Files:**
- Modify: `app/guide/presentation/copywriter_contracts.py`
- Modify: `app/guide/presentation/copywriter_prompt.py`
- Modify: `app/guide/presentation/copywriter_fallback.py`
- Modify: `app/guide/presentation/copywriter_validation.py`
- Modify: `app/guide/presentation/presentation_packet.py`
- Modify: `app/guide/presentation/presentation_compiler.py`
- Modify: `app/guide/application/product_evidence_answer.py`
- Modify: `app/guide/application/text_recommendation_flow.py`
- Modify: `app/static/guide-presentation.js`
- Modify: `app/static/chat.html`
- Test: `tests/guide/presentation/test_copywriter_fallback.py`
- Test: `tests/guide/presentation/test_copywriter_validation.py`
- Test: `tests/guide/presentation/test_presentation_packet.py`
- Test: `tests/guide/application/test_product_evidence_answer.py`
- Test: `tests/guide/runtime/test_frontend_mode_rendering.py`

- [ ] **Step 1: Write section-duty RED tests**

Freeze:

```python
@pytest.mark.parametrize(
    ("mode", "required", "forbidden"),
    (
        (
            "recommendation",
            {"summary", "products", "closing", "full_cards", "pitfalls"},
            set(),
        ),
        (
            "product_knowledge",
            {"products", "full_cards"},
            {"advisor_reason", "closing", "pitfalls"},
        ),
        (
            "general_knowledge",
            {"general_knowledge"},
            {"products", "full_cards", "pitfalls"},
        ),
        (
            "comparison",
            {"summary", "comparison", "products", "closing", "full_cards"},
            set(),
        ),
    ),
)
def test_mode_section_duties(mode, required, forbidden):
    packet = packet_for(mode)
    kinds = {section.kind for section in packet.sections}
    assert required <= kinds
    assert not forbidden & kinds
```

Add comparison max-three, product-knowledge single-card, and
product-mentioned-general-question card tests.

- [ ] **Step 2: Add public-language RED tests**

Validate final fallback and copywriter output does not contain:

```python
INTERNAL_PUBLIC_TERMS = (
    "候选",
    "代码核对",
    "硬条件",
    "证据等级",
    "放行",
    "页面记录版本",
    "本轮筛选",
)
```

Also reject duplicated prefixes such as `品牌主打：品牌主打`.

- [ ] **Step 3: Run RED tests**

```bash
pytest -q \
  tests/guide/presentation/test_presentation_packet.py \
  tests/guide/presentation/test_copywriter_fallback.py \
  tests/guide/presentation/test_copywriter_validation.py \
  tests/guide/application/test_product_evidence_answer.py
```

Expected: FAIL on current shared recommendation framing.

- [ ] **Step 4: Implement explicit presentation policies**

Add one policy per mode family. Product knowledge uses:

```text
product title
inline card
direct answer sections
single full card
```

Recommendation keeps summary, product routes, closing, full cards, and
pitfalls. Comparison uses two or three products and includes a horizontal
table. General knowledge remains zero-card unless an explicit product is
bound, in which case it becomes product knowledge.

- [ ] **Step 5: Make fallback fact-rich and mode-specific**

Use approved narrative atoms and locked facts. Recommendation fallback covers
at least 80% of required high-value atoms. Product knowledge renders the
requested fields only. Caution follow-up renders the caution only.

Natural merchant attribution is:

```text
品牌主打轻薄、不粘腻，跟妆更服帖。
```

Do not produce:

```text
页面证据显示……
商家宣称……商家宣称……
该结果比一句宣传更有参考价值……
```

- [ ] **Step 6: Update product-shelf titles and frontend contracts**

Render:

```text
recommendation -> 为你挑到这些
single explicit product -> 本轮提到的商品
image identity -> 本轮识别到的商品
comparison -> 本次对比商品
```

Use the same `visible_product_ids` in inline and full cards.

- [ ] **Step 7: Run presentation and frontend suites**

```bash
pytest -q \
  tests/guide/presentation \
  tests/guide/application/test_product_evidence_answer.py \
  tests/guide/runtime/test_frontend_mode_rendering.py \
  tests/guide/runtime/test_frontend_card_binding.py \
  tests/guide/runtime/test_frontend_evidence_rendering.py
```

Expected: PASS; product knowledge has no recommendation closing.

- [ ] **Step 8: Commit presentation duties**

```bash
git add \
  app/guide/presentation \
  app/guide/application/product_evidence_answer.py \
  app/guide/application/text_recommendation_flow.py \
  app/static/guide-presentation.js \
  app/static/chat.html \
  tests/guide/presentation \
  tests/guide/application/test_product_evidence_answer.py \
  tests/guide/runtime/test_frontend_mode_rendering.py \
  tests/guide/runtime/test_frontend_card_binding.py \
  tests/guide/runtime/test_frontend_evidence_rendering.py
git commit -m "fix(guide): separate presentation duties by mode"
```

## Task 4: Add Session-Only Profile Contracts And Reducer

**Files:**
- Create: `app/guide/feedback/session_profile.py`
- Modify: `app/guide/feedback/contracts.py`
- Modify: `app/guide/application/query_context.py`
- Modify: `app/guide/application/consultation_coordinator.py`
- Test: `tests/guide/feedback/test_session_profile.py`
- Test: `tests/guide/feedback/test_conversation_state_contracts.py`
- Test: `tests/guide/application/test_query_context.py`
- Test: `tests/guide/application/test_consultation_chat_flow.py`

- [ ] **Step 1: Write RED contract tests**

Cover direct self-report, provisional report, current condition, friend
scope, corrections, and deletion:

```python
def test_explicit_self_sensitive_is_confirmed_session_tendency():
    result = reduce_session_profile(
        previous=SessionProfile(),
        updates=(stable("sensitivity", confirmed=True),),
        subject_scope="self",
        source_turn_id="turn_1234567890abcdef",
    )
    assert result.profile.stable_tendencies[0].value == "sensitivity"


def test_friend_fact_does_not_modify_self_profile():
    result = reduce_session_profile(
        previous=existing_profile(),
        updates=(stable("sensitivity", confirmed=True),),
        subject_scope="other",
        source_turn_id="turn_1234567890abcdef",
    )
    assert result.profile == existing_profile()
```

- [ ] **Step 2: Implement immutable session profile**

Define:

```python
class SessionProfile(_StrictFrozen):
    base_skin: SessionBaseSkin | None = None
    stable_tendencies: tuple[SessionProfileFact, ...] = ()
    current_conditions: tuple[SessionConditionFact, ...] = ()
    explicit_restrictions: tuple[SessionRestriction, ...] = ()


class SessionProfileFact(_StrictFrozen):
    value: StableTendency
    confirmation: Literal["provisional", "confirmed"]
    source_turn_id: str


class SessionConditionFact(_StrictFrozen):
    value: CurrentCondition
    active: bool
    source_turn_id: str
    recorded_at_version: int
```

Reject duplicate or contradictory active facts.

- [ ] **Step 3: Implement source-aware projection**

Project:

```text
current explicit skin > confirmed session base skin
current explicit restrictions > confirmed session restrictions
active damage -> safety gate
```

Do not project provisional profile facts into ranking.

- [ ] **Step 4: Disable automatic long-term writes**

Remove automatic consultation writes to `profile_state` from the default
path. Confirmation updates `ConversationSnapshot.session_profile` only.
Leave the long-term store code intact but unreachable without a future
explicit opt-in policy.

- [ ] **Step 5: Run profile suites**

```bash
pytest -q \
  tests/guide/feedback/test_session_profile.py \
  tests/guide/feedback/test_conversation_state_contracts.py \
  tests/guide/application/test_query_context.py \
  tests/guide/application/test_consultation_chat_flow.py
```

Expected: PASS; no test expects an automatic long-term write.

- [ ] **Step 6: Commit session profile**

```bash
git add \
  app/guide/feedback/session_profile.py \
  app/guide/feedback/contracts.py \
  app/guide/application/query_context.py \
  app/guide/application/consultation_coordinator.py \
  tests/guide/feedback/test_session_profile.py \
  tests/guide/feedback/test_conversation_state_contracts.py \
  tests/guide/application/test_query_context.py \
  tests/guide/application/test_consultation_chat_flow.py
git commit -m "feat(guide): add session-only shopping profile"
```

## Task 5: Add Independent Focus State And Persistence

**Files:**
- Create: `app/guide/feedback/focus_state.py`
- Modify: `app/guide/feedback/contracts.py`
- Modify: `app/guide/adapters/state/in_memory_conversation_state.py`
- Modify: `app/guide/adapters/state/sqlite_conversation_state.py`
- Modify: `app/guide/application/chat_api_adapter.py`
- Test: `tests/guide/feedback/test_focus_state.py`
- Test: `tests/guide/adapters/state/test_in_memory_conversation_state.py`
- Test: `tests/guide/adapters/state/test_sqlite_conversation_state.py`
- Test: `tests/guide/application/test_cross_worker_text_state.py`

- [ ] **Step 1: Write focus RED tests**

Freeze this sequence:

```text
recommend products 51, 55, 101
-> focus candidate 2
-> switch to general knowledge
-> return to candidate 2
```

Assert the candidate batch survives while `active_processor` changes.
Also test confirmed image focus, deletion, refresh, owner isolation, and stale
CAS rejection.

- [ ] **Step 2: Implement focus contracts**

```python
class ConfirmedImageProductRef(_StrictFrozen):
    image_ordinal: int = Field(ge=1, le=4)
    product_id: int = Field(gt=0)
    variant_scope: str | None = None


class FocusState(_StrictFrozen):
    active_processor: ProcessorKind | None = None
    current_product_id: int | None = Field(default=None, gt=0)
    confirmed_image_products: tuple[ConfirmedImageProductRef, ...] = ()
    current_knowledge_topic: str | None = None
    last_question_meaning: str | None = None
```

Candidate batches remain in existing `ConversationSnapshot.candidates`.

- [ ] **Step 3: Persist focus with existing snapshot transaction**

Add optional `focus_state` to `ConversationSnapshot`. Keep existing rows
readable through the model default. Validate focused products against either
current candidates or confirmed image products.

- [ ] **Step 4: Run state suites**

```bash
pytest -q \
  tests/guide/feedback/test_focus_state.py \
  tests/guide/adapters/state/test_in_memory_conversation_state.py \
  tests/guide/adapters/state/test_sqlite_conversation_state.py \
  tests/guide/application/test_cross_worker_text_state.py
```

Expected: PASS across two state adapters and two runtime workers.

- [ ] **Step 5: Commit focus state**

```bash
git add \
  app/guide/feedback/focus_state.py \
  app/guide/feedback/contracts.py \
  app/guide/adapters/state/in_memory_conversation_state.py \
  app/guide/adapters/state/sqlite_conversation_state.py \
  app/guide/application/chat_api_adapter.py \
  tests/guide/feedback/test_focus_state.py \
  tests/guide/adapters/state/test_in_memory_conversation_state.py \
  tests/guide/adapters/state/test_sqlite_conversation_state.py \
  tests/guide/application/test_cross_worker_text_state.py
git commit -m "feat(guide): persist independent conversation focus"
```

## Task 6: Upgrade Turn Meaning And Auditable Semantic Admission

**Files:**
- Create: `app/guide/intent/semantic_admission.py`
- Modify: `app/guide/understanding/turn_meaning_contracts.py`
- Modify: `app/guide/adapters/llm/turn_meaning_prompt.py`
- Modify: `app/guide/intent/executable_intent_compiler.py`
- Modify: `app/guide/intent/concept_preferences.py`
- Test: `tests/guide/intent/test_semantic_admission.py`
- Test: `tests/guide/understanding/test_turn_meaning_contracts.py`
- Test: `tests/guide/adapters/test_turn_meaning_prompt.py`
- Test: `tests/guide/intent/test_executable_intent_compiler.py`

- [ ] **Step 1: Write RED schema tests**

Require source-bound:

```text
continuity_hint
subject_scope_hint
expanded observation candidates
provisional consultation hypothesis
next observation gap
```

Reject product IDs, state operations, scores, and invented concept IDs.

- [ ] **Step 2: Define admission outcomes**

```python
class AdmissionOutcome(_StrictFrozen):
    atom_kind: str
    raw_text: str
    disposition: Literal[
        "admitted",
        "retained_free",
        "deferred_until_topic",
        "rejected_protocol",
    ]
    normalized_value: str | None = None
    reason: str
```

All outcomes are internal audit data and never public copy.

- [ ] **Step 3: Preserve correct meaning across topic uncertainty**

If a source-bound ordinary preference has a valid reviewed concept but topic
is unknown, return `deferred_until_topic`; do not drop it. If it is not in the
reviewed concept catalog, retain the exact source phrase as
`retained_free`. Only malformed protocol data is rejected.

- [ ] **Step 4: Update the prompt**

The prompt translates once and includes no user-facing answer. It explicitly
requires all consultation observations in the current message and forbids
inventing locations or triggers. Keep the reviewed 48 concept IDs as the only
allowed concept identities.

- [ ] **Step 5: Run admission and prompt suites**

```bash
pytest -q \
  tests/guide/intent/test_semantic_admission.py \
  tests/guide/understanding/test_turn_meaning_contracts.py \
  tests/guide/adapters/test_turn_meaning_prompt.py \
  tests/guide/intent/test_executable_intent_compiler.py
```

Expected: PASS with no silent candidate loss.

- [ ] **Step 6: Commit semantic admission**

```bash
git add \
  app/guide/intent/semantic_admission.py \
  app/guide/understanding/turn_meaning_contracts.py \
  app/guide/adapters/llm/turn_meaning_prompt.py \
  app/guide/intent/executable_intent_compiler.py \
  app/guide/intent/concept_preferences.py \
  tests/guide/intent/test_semantic_admission.py \
  tests/guide/understanding/test_turn_meaning_contracts.py \
  tests/guide/adapters/test_turn_meaning_prompt.py \
  tests/guide/intent/test_executable_intent_compiler.py
git commit -m "feat(guide): add auditable semantic admission"
```

## Task 7: Implement The Pure Unified Router

**Files:**
- Create: `app/guide/intent/unified_turn_router.py`
- Create: `tests/guide/intent/test_unified_turn_router.py`
- Modify: `app/guide/intent/reference_admission.py`
- Modify: `app/guide/intent/transition_planning.py`
- Test: `tests/guide/intent/test_reference_admission.py`
- Test: `tests/guide/intent/test_constraint_transitions.py`

- [ ] **Step 1: Write table-driven router RED tests**

Cover:

```text
recommendation -> second product knowledge
product knowledge -> caution
general knowledge -> recommendation
recommendation -> consultation
consultation -> new sunscreen task
knowledge -> return to earlier second product
image identity -> suitability
image similarity -> constrained recommendation
comparison -> add third product
comparison -> reject fourth product
correct constraint
withdraw constraint
replace task
pending affirmation
pending rejection
```

- [ ] **Step 2: Define the route contract**

```python
class UnifiedRouteDecision(_StrictFrozen):
    processor: ProcessorKind
    continuity: ContinuityKind
    focus_source: FocusSource
    product_bindings: tuple[ResolvedProductBinding, ...] = ()
    clarification: str | None = None
    clarification_code: ClarificationCode | None = None
```

Validate processor/cardinality pairs, such as comparison requiring two or
three products.

- [ ] **Step 3: Implement deterministic route priority**

Use explicit current-turn meaning, admitted references, `PendingTurn`,
`FocusState`, and snapshot state. Do not call retrieval or a model.

An explicit new task wins over active consultation. A current-item question
may use `current_product_id`; an ordinal uses the preserved candidate batch.
Ambiguous references clarify instead of choosing the most recent object.

- [ ] **Step 4: Run pure-router suites**

```bash
pytest -q \
  tests/guide/intent/test_unified_turn_router.py \
  tests/guide/intent/test_reference_admission.py \
  tests/guide/intent/test_constraint_transitions.py
```

Expected: PASS with zero state writes in router tests.

- [ ] **Step 5: Commit pure router**

```bash
git add \
  app/guide/intent/unified_turn_router.py \
  app/guide/intent/reference_admission.py \
  app/guide/intent/transition_planning.py \
  tests/guide/intent/test_unified_turn_router.py \
  tests/guide/intent/test_reference_admission.py \
  tests/guide/intent/test_constraint_transitions.py
git commit -m "feat(guide): add pure unified turn router"
```

## Task 8: Integrate One-Call Unified Flow

**Files:**
- Create: `app/guide/application/unified_guide_flow.py`
- Modify: `app/guide/application/chat_api_adapter.py`
- Modify: `app/guide_runtime/composition.py`
- Modify: `app/guide_runtime/app.py`
- Test: `tests/guide/application/test_unified_guide_flow.py`
- Test: `tests/guide/runtime/test_composition.py`
- Test: `tests/guide/runtime/test_runtime_http.py`

- [ ] **Step 1: Write integration RED trajectories**

Use fake one-call `TurnMeaningPort` responses and real local processors. Assert
one semantic call per user turn and zero copywriter calls.

Freeze at least:

```text
recommend -> product knowledge -> consultation -> general knowledge
-> return to product -> budget revision
```

Assert all terminal SSE sequences validate and snapshots commit only after
terminal delivery.

- [ ] **Step 2: Implement `UnifiedGuideFlow`**

For each turn:

```text
load snapshot and owner
-> one semantic translation
-> exact parsing and admission
-> product/reference binding
-> pure route decision
-> delegate to existing processor
-> stage focus/profile/snapshot update
-> emit existing typed SSE
```

Do not copy processor decision logic into the flow.

- [ ] **Step 3: Wire the flag**

When `GUIDE_UNIFIED_ROUTER_ENABLED=true`, `iter_http_events` uses the unified
flow for text and consultation and uses image identity as a pre-routing input.
When false, preserve current `classify_chat_owner` behavior.

- [ ] **Step 4: Run integration and parity suites**

```bash
pytest -q \
  tests/guide/application/test_unified_guide_flow.py \
  tests/guide/application/test_chat_api_adapter.py \
  tests/guide/runtime/test_composition.py \
  tests/guide/runtime/test_runtime_http.py
```

Expected: PASS in both flag states.

- [ ] **Step 5: Commit unified integration**

```bash
git add \
  app/guide/application/unified_guide_flow.py \
  app/guide/application/chat_api_adapter.py \
  app/guide_runtime/composition.py \
  app/guide_runtime/app.py \
  tests/guide/application/test_unified_guide_flow.py \
  tests/guide/application/test_chat_api_adapter.py \
  tests/guide/runtime/test_composition.py \
  tests/guide/runtime/test_runtime_http.py
git commit -m "feat(guide): integrate reversible unified flow"
```

## Task 9: Replace Fixed Consultation With Dynamic Consultation

**Files:**
- Create: `app/guide/application/dynamic_consultation.py`
- Modify: `app/guide/understanding/consultation_contracts.py`
- Modify: `app/guide/feedback/consultation_state.py`
- Modify: `app/guide/application/consultation_coordinator.py`
- Modify: `app/guide/application/consultation_chat_flow.py`
- Test: `tests/guide/application/test_dynamic_consultation.py`
- Test: `tests/guide/application/test_consultation_chat_flow.py`
- Test: `tests/guide/feedback/test_conversation_state_contracts.py`

- [ ] **Step 1: Write multi-turn RED tests**

Freeze:

```text
U: 一会油一会干，换季还红
A: asks where oiliness and dryness occur
U: 下午鼻子额头油，两颊洗完紧
A: provisional combination direction, asks trigger/tolerance
U: 平时保湿不痛，换季和用酸会红刺
A: asks active-damage risk
U: 偶尔起皮，没有红肿破损
A: provisional profile and confirmation
U: 差不多，不过鼻子比额头更油
A: corrects location, asks for confirmation
```

Also test "先看防晒" exits consultation, "昨天新精华后一直火辣辣"
does not become permanent sensitive skin, and active breakage escalates.

- [ ] **Step 2: Replace ordered observations**

Use unordered, source-bound observations:

```python
class ConsultationObservation(_StrictFrozen):
    observation_id: str
    dimension: ObservationDimension
    state: Literal["present", "absent", "sometimes", "unknown"]
    location: ObservationLocation | None = None
    trigger: ObservationTrigger | None = None
    source_text: str
    source_turn_id: str
```

Remove `_validate_observation_order`.

- [ ] **Step 3: Implement assessment gates**

Accept a displayed base-skin direction only when at least two compatible
observations support it. Preserve sensitivity as a separate tendency. A
single active-risk observation triggers safety behavior.

- [ ] **Step 4: Select one next gap**

Implement deterministic validation of the model-proposed next gap:

```text
missing location
missing trigger/persistence
missing ordinary-product tolerance
missing active-risk status
confirmation
```

If the proposed gap is already answered or unrelated, choose the highest
remaining gap. Render one natural question.

- [ ] **Step 5: Run dynamic consultation suites**

```bash
pytest -q \
  tests/guide/application/test_dynamic_consultation.py \
  tests/guide/application/test_consultation_chat_flow.py \
  tests/guide/feedback/test_conversation_state_contracts.py
```

Expected: PASS; natural multi-observation turns no longer require "会/不会".

- [ ] **Step 6: Commit dynamic consultation**

```bash
git add \
  app/guide/application/dynamic_consultation.py \
  app/guide/understanding/consultation_contracts.py \
  app/guide/feedback/consultation_state.py \
  app/guide/application/consultation_coordinator.py \
  app/guide/application/consultation_chat_flow.py \
  tests/guide/application/test_dynamic_consultation.py \
  tests/guide/application/test_consultation_chat_flow.py \
  tests/guide/feedback/test_conversation_state_contracts.py
git commit -m "feat(guide): add dynamic light consultation"
```

## Task 10: Route Confirmed Images Into Existing Processors

**Files:**
- Modify: `app/guide/application/image_recommendation_flow.py`
- Modify: `app/guide/application/unified_guide_flow.py`
- Modify: `app/guide/intent/unified_turn_router.py`
- Modify: `app/guide/presentation/contracts.py`
- Test: `tests/guide/application/test_image_recommendation_flow.py`
- Test: `tests/guide/application/test_unified_guide_flow.py`
- Test: `tests/guide/application/test_image_presentation_integration.py`

- [ ] **Step 1: Write image-routing RED tests**

Cover:

```text
image only -> identity plus concise product profile
image + sensitive question -> product suitability
image + similar -> alternatives with similarity/difference explanation
image + similar + 100 max + refreshing -> constrained recommendation
two images -> standard two-product comparison
three images -> standard three-product comparison
four images -> clarification
low confidence -> zero cards
OCR conflict -> zero cards
```

- [ ] **Step 2: Persist confirmed identity only**

Convert confirmed image results into `ConfirmedImageProductRef`. Do not
persist vector candidates or ambiguous OCR output.

- [ ] **Step 3: Reuse standard processors**

After identity:

- product questions use product knowledge/suitability;
- constrained similarity uses recommendation;
- multiple images use comparison;
- pure similarity excludes the source product from alternative slots and
  states where each alternative is similar and different.

- [ ] **Step 4: Cap comparisons at three**

Change `CardDisplayContract` comparison cardinality from two-to-four to
two-to-three and update all fixtures.

- [ ] **Step 5: Run image and presentation suites**

```bash
pytest -q \
  tests/guide/application/test_image_recommendation_flow.py \
  tests/guide/application/test_unified_guide_flow.py \
  tests/guide/application/test_image_presentation_integration.py \
  tests/guide/runtime/test_frontend_card_binding.py
```

Expected: PASS; the source image product does not consume an alternative slot.

- [ ] **Step 6: Commit image routing**

```bash
git add \
  app/guide/application/image_recommendation_flow.py \
  app/guide/application/unified_guide_flow.py \
  app/guide/intent/unified_turn_router.py \
  app/guide/presentation/contracts.py \
  tests/guide/application/test_image_recommendation_flow.py \
  tests/guide/application/test_unified_guide_flow.py \
  tests/guide/application/test_image_presentation_integration.py \
  tests/guide/runtime/test_frontend_card_binding.py
git commit -m "feat(guide): route images through standard guide modes"
```

## Task 11: Build Offline Replay And Earliest-Distortion Diagnostics

**Files:**
- Create: `tools/guide_gates/unified_router_gate.py`
- Create: `tests/guide/tools/test_unified_router_gate.py`
- Create: `tests/fixtures/guide/intent/unified_router_offline_v1.jsonl`
- Create: `tests/fixtures/guide/intent/unified_router_offline_v1_manifest.json`

- [ ] **Step 1: Write evaluator RED tests**

Assert failures classify to exactly one earliest layer:

```python
class FailureLayer(str, Enum):
    MODEL_TRANSLATION = "model_translation"
    SEMANTIC_ADMISSION = "semantic_admission"
    IDENTITY_BINDING = "identity_binding"
    ROUTE_SELECTION = "route_selection"
    STATE_TRANSITION = "state_transition"
    DECISION_EXECUTION = "decision_execution"
    PRESENTATION = "presentation"
```

The evaluator must distinguish "model output reasonable but code rejected"
from model misunderstanding.

- [ ] **Step 2: Implement replay artifacts**

Each case stores:

```text
case_id
message
typed starting snapshot
raw TurnMeaning JSON
acceptable semantic range
expected bindings
expected route
expected final snapshot
expected TaskPlan
expected card IDs
expected safety/clarification
```

Hash the JSONL and manifest.

- [ ] **Step 3: Seed from saved real outputs**

Import existing `turn_meaning` gate outputs and add cross-mode trajectories.
Do not call an API.

- [ ] **Step 4: Run the offline gate**

```bash
python -m tools.guide_gates.unified_router_gate \
  --cases tests/fixtures/guide/intent/unified_router_offline_v1.jsonl \
  --manifest tests/fixtures/guide/intent/unified_router_offline_v1_manifest.json
```

Expected:

```text
wrong_product_selection_count=0
unauthorized_state_transition_count=0
unsafe_downgrade_count=0
cross_session_leak_count=0
```

- [ ] **Step 5: Commit replay gate**

```bash
git add \
  tools/guide_gates/unified_router_gate.py \
  tests/guide/tools/test_unified_router_gate.py \
  tests/fixtures/guide/intent/unified_router_offline_v1.jsonl \
  tests/fixtures/guide/intent/unified_router_offline_v1_manifest.json
git commit -m "test(guide): add unified router replay gate"
```

## Task 12: Run Real Intent Smoke And Two Independent Blind Batches

**Files:**
- Create: `tools/guide_gates/run_real_unified_router_gate.py`
- Create: `tests/guide/tools/test_run_real_unified_router_gate.py`
- Create: `tests/fixtures/guide/intent/unified_router_smoke_v1.jsonl`
- Create: `tests/fixtures/guide/intent/unified_router_blind_a_v1.jsonl`
- Create: `tests/fixtures/guide/intent/unified_router_blind_b_v1.jsonl`
- Create: `docs/audits/unified-router/real-smoke-v1.json`
- Create: `docs/audits/unified-router/blind-a-v1.json`
- Create: `docs/audits/unified-router/blind-b-v1.json`

- [ ] **Step 1: Freeze the approximately 40-case smoke set**

Include all processors, schema fields, focus returns, profile statements,
consultation observations, aliases, ordinals, corrections, withdrawals,
image contexts, and safety language. Freeze expectations before API calls.

- [ ] **Step 2: Implement one-call capture**

The runner:

- calls only the turn-meaning model;
- disables the copywriter;
- performs no retry or repair call;
- saves raw provider output once;
- completes the local backend path;
- records prompt, model, input, context, output, route, final state, hashes,
  token usage, and failure layer.

- [ ] **Step 3: Run real smoke**

Run with the existing local credential environment:

```bash
python -m tools.guide_gates.run_real_unified_router_gate \
  --cases tests/fixtures/guide/intent/unified_router_smoke_v1.jsonl \
  --output docs/audits/unified-router/real-smoke-v1.json \
  --disable-copywriter
```

If a case fails, freeze its output, locate the earliest incorrect layer,
implement a general fix under TDD, and replay all captured outputs offline
before making another API call.

- [ ] **Step 4: Freeze blind batch A**

Create exactly 100 independent cases with:

- 55 fresh no-history questions;
- 45 independent contextual trajectories;
- colloquial language, typos, ellipsis, mixed tasks, references, aliases,
  corrections, withdrawals, topic switches, profile statements, consultation
  observations, and safety constraints.

- [ ] **Step 5: Run blind batch A once**

```bash
python -m tools.guide_gates.run_real_unified_router_gate \
  --cases tests/fixtures/guide/intent/unified_router_blind_a_v1.jsonl \
  --output docs/audits/unified-router/blind-a-v1.json \
  --disable-copywriter
```

Required:

```text
end_to_end_rate >= 0.90
each_major_category_rate >= 0.80
wrong_product_selection_count = 0
unauthorized_state_transition_count = 0
hard_condition_override_count = 0
unsafe_downgrade_count = 0
cross_session_leak_count = 0
```

- [ ] **Step 6: Freeze independent blind batch B**

Create exactly 100 unseen cases. Do not reuse batch A text or use simple
synonym substitutions. Freeze code, prompt, fixture, and manifest before the
run.

- [ ] **Step 7: Run blind batch B once**

```bash
python -m tools.guide_gates.run_real_unified_router_gate \
  --cases tests/fixtures/guide/intent/unified_router_blind_b_v1.jsonl \
  --output docs/audits/unified-router/blind-b-v1.json \
  --disable-copywriter
```

Apply the same thresholds. Do not edit expected results after seeing output.

- [ ] **Step 8: Commit gate code and immutable evidence**

```bash
git add \
  tools/guide_gates/run_real_unified_router_gate.py \
  tests/guide/tools/test_run_real_unified_router_gate.py \
  tests/fixtures/guide/intent/unified_router_smoke_v1.jsonl \
  tests/fixtures/guide/intent/unified_router_blind_a_v1.jsonl \
  tests/fixtures/guide/intent/unified_router_blind_b_v1.jsonl \
  docs/audits/unified-router/real-smoke-v1.json \
  docs/audits/unified-router/blind-a-v1.json \
  docs/audits/unified-router/blind-b-v1.json
git commit -m "test(guide): prove unified router with blind model gates"
```

## Task 13: Full Regression And Browser Closure

**Files:**
- Modify: `tools/guide_gates/frontend_presentation_browser_audit.py`
- Modify: `tests/fixtures/guide/presentation/frontend_mode_matrix_v1.jsonl`
- Create: `docs/audits/unified-router/browser-closure-v1.json`
- Create: `docs/audits/unified-router/final-closure.md`

- [ ] **Step 1: Run all focused suites**

```bash
pytest -q \
  tests/guide/intent \
  tests/guide/feedback \
  tests/guide/application \
  tests/guide/presentation \
  tests/guide/runtime
```

Expected: PASS.

- [ ] **Step 2: Run the complete test suite**

```bash
pytest -q
```

Expected: PASS with no newly introduced warning category.

- [ ] **Step 3: Start the real local runtime**

Use an unused port and the real semantic provider with the unified flag:

```bash
GUIDE_UNIFIED_ROUTER_ENABLED=true \
python -m uvicorn app.guide_runtime.app:app \
  --host 127.0.0.1 \
  --port 8011
```

Keep the session alive through browser acceptance.

- [ ] **Step 4: Run desktop and mobile mode matrices**

Cover recommendation, revision, comparison, product knowledge, general
knowledge, all image routes, consultation entry/provisional/correction/
confirmation/exit, clarification, no match, safety escalation, and public
error.

Verify at `1440px` and `390px`:

- no overlap or horizontal overflow;
- all referenced images load;
- specification consistency;
- horizontal comparison table works;
- product knowledge has no recommendation closing;
- every explicitly bound product appears in the bottom shelf;
- general knowledge without a product has zero cards;
- thinking disappears on first answer character;
- no stale cards after mode switch;
- no console or relevant network error.

- [ ] **Step 5: Verify lifecycle invariants**

Exercise:

```text
refresh
cross-worker continuation
stale version conflict
two-session isolation
disconnect before terminal SSE
delete session
wrong-owner delete
```

Confirm session profile, focus, consultation, and `PendingTurn` follow the
same delayed-commit and deletion behavior.

- [ ] **Step 6: Write closure evidence**

Record:

- source and asset hashes;
- focused and full test counts;
- offline, smoke, blind A, and blind B rates;
- zero-violation counts;
- browser viewport matrix;
- screenshots;
- console/network results;
- active feature flag;
- rollback command;
- explicit statement that no production deployment occurred.

- [ ] **Step 7: Commit closure**

```bash
git add \
  tools/guide_gates/frontend_presentation_browser_audit.py \
  tests/fixtures/guide/presentation/frontend_mode_matrix_v1.jsonl \
  docs/audits/unified-router/browser-closure-v1.json \
  docs/audits/unified-router/final-closure.md
git commit -m "docs(guide): close unified router acceptance"
```

## Final Completion Audit

Before declaring completion, inspect authoritative current-state evidence for
every item:

```text
specification projection
variant binding
mode-specific presentation
session-only profile
focus switching
router flag parity
dynamic consultation
image routing
offline replay
real smoke
blind batch A
blind batch B
full pytest
desktop browser
mobile browser
SSE lifecycle
owner/session isolation
session deletion
no deployment
```

Missing, indirect, stale, or merely plausible evidence is not completion.
