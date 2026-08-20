# Phase 2 Day 1 Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze the shared Phase 2 foundation by fixing the five confirmed P1 defects, making backend card display authoritative, centralizing Guide/legacy ownership, and defining stable consultation/profile/multi-image contracts.

**Architecture:** Keep the clean `app.guide` and `app.guide_runtime` boundaries. The backend emits exact visible product IDs through a typed card display event; the shared frontend renders those IDs without text inference or card filling. Formal API composition becomes thread-safe, and future Phase 2 work receives strict contracts without importing old `app.services`.

**Tech Stack:** Python 3.11, FastAPI, Starlette, Pydantic v2, SQLite, vanilla JavaScript, pytest, Node.js contract probes, Playwright.

---

## Continuous Goal Contract

This file is Milestone 1 of
`docs/superpowers/plans/2026-08-09-phase2-continuous-ralph.md`.
Completing every task in this file is a checkpoint, not overall completion.
After final integration, control returns immediately to the continuous plan,
which launches the three prepared worktrees. Do not mark the Ralph Goal
`COMPLETE` at the end of this subplan.

## Execution Preconditions

Use a dedicated worktree:

```bash
cd /Users/bytedance/Desktop/xiaoro-fresh
test "$(git branch --show-current)" = "rebuild"
test -z "$(git status --porcelain)"
! git show-ref --verify --quiet refs/heads/phase2-day1-base
! git show-ref --verify --quiet refs/heads/phase2-day1-stabilization
git branch phase2-day1-base HEAD
git worktree add \
  /private/tmp/xiaoro-phase2-day1 \
  -b phase2-day1-stabilization \
  phase2-day1-base
cd /private/tmp/xiaoro-phase2-day1
```

Use the verified combined test environment for Guide and image tests:

```bash
export PYTHONPATH=/private/tmp/xiaoro-guide-runtime-venv/lib/python3.11/site-packages
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export GUIDE_PYTHON=/private/tmp/xiaoro-guide-image-venv/bin/python
```

Protected values:

```bash
test "$(shasum -a 256 app/guide/decision/deterministic_ranking.py | awk '{print $1}')" = \
  "4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f"
test -z "$(git diff --name-only phase2-day1-base -- app/services app/database data/canonical)"
```

## File Map

Create:

- `app/guide/presentation/card_display.py` — derives strict visible-card contracts.
- `app/guide/feedback/profile_contracts.py` — stable profile ownership and confirmed facts.
- `app/guide/understanding/consultation_contracts.py` — light-consultation observations and provisional conclusions.
- `app/guide/understanding/multi_image_contracts.py` — stable image ordinal and task references.
- `tests/guide/presentation/test_card_display_contracts.py` — card count and ID invariants.
- `tests/guide/runtime/test_image_http.py` — event-loop upload offload regression.
- `tests/guide/test_phase2_shared_contracts.py` — future workstream contract validation.
- `docs/audits/phase2-day1/owner_matrix.csv` — mechanical Guide/legacy routing evidence.
- `docs/audits/phase2-day1/morning_handoff.md` — Day 1 evidence and frozen interfaces.

Modify:

- `app/api/v1/chat.py` — thread-safe composition, owner routing, non-stream response fields.
- `app/guide/application/chat_api_adapter.py` — centralized owner classification and card event conversion.
- `app/guide/application/image_recommendation_flow.py` — image/text category conflict and card event.
- `app/guide/application/text_recommendation_flow.py` — backend visible-card cap and card event.
- `app/guide/presentation/contracts.py` — `CardDisplayContract`.
- `app/guide/presentation/sse_events.py` — typed card display event.
- `app/guide_runtime/image_http.py` — offload synchronous decoding/state creation.
- `app/static/chat.html` — exact card rendering and delegated favorite handling.
- `tests/guide/application/test_chat_api_adapter.py`
- `tests/guide/application/test_chat_route_wiring.py`
- `tests/guide/application/test_formal_chat_router_http.py`
- `tests/guide/application/test_image_recommendation_flow.py`
- `tests/guide/application/test_text_recommendation_flow.py`
- `tests/guide/runtime/test_frontend_scope.py`
- `tests/guide/runtime/test_runtime_http.py`
- `tools/guide_gates/runtime_browser_smoke.py`
- `tools/guide_gates/runtime_browser_adversarial.py`

## Task 1: Lock the Day 1 Baseline

**Files:**
- Create: `docs/audits/phase2-day1/morning_handoff.md`

- [ ] **Step 1: Record the exact baseline**

Create the handoff with:

```markdown
# Phase 2 Day 1 Handoff

## Baseline

- Branch: `phase2-day1-stabilization`
- Base ref: `phase2-day1-base`
- Ranking SHA-256:
  `4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`
- Protected paths: `app/services`, `app/database`, `data/canonical`
- Scope: shared stabilization only; no consultation/profile/multi-image business implementation
```

- [ ] **Step 2: Run the baseline tests**

Run:

```bash
$GUIDE_PYTHON -m pytest -c pytest-guide.ini -q
$GUIDE_PYTHON -m pytest -c pytest-guide.ini -q tests/guide/runtime
```

Expected:

```text
901 passed
105 passed
```

- [ ] **Step 3: Verify boundaries and protected paths**

Run:

```bash
$GUIDE_PYTHON app/guide/check_boundaries.py app/guide
$GUIDE_PYTHON app/guide/check_boundaries.py app/guide_runtime
git diff --check
test -z "$(git diff --name-only phase2-day1-base -- app/services app/database data/canonical)"
```

Expected: all commands exit `0`.

- [ ] **Step 4: Commit the baseline evidence**

```bash
git add docs/audits/phase2-day1/morning_handoff.md
git commit -m "docs(phase2): record day1 stabilization baseline"
```

## Task 2: Make Text Guide Composition Single-Publication

**Files:**
- Modify: `app/api/v1/chat.py:89-104`
- Test: `tests/guide/application/test_formal_chat_router_http.py`

- [ ] **Step 1: Write the concurrent cold-start regression**

Add:

```python
def test_text_guide_singleton_builds_once_under_concurrent_cold_start(
    monkeypatch,
) -> None:
    chat = _load_formal_chat_module()
    first_build_started = threading.Event()
    release_build = threading.Event()
    calls_lock = threading.Lock()
    build_calls = 0
    instance = object()

    def build(_repo_root):
        nonlocal build_calls
        with calls_lock:
            build_calls += 1
            first_build_started.set()
        assert release_build.wait(timeout=2)
        return instance

    monkeypatch.setattr(chat, "build_runtime_orchestrator", build)
    chat._slice1_guide_orchestrator = None

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(chat._get_slice1_guide_orchestrator)
        assert first_build_started.wait(timeout=2)
        second = executor.submit(chat._get_slice1_guide_orchestrator)
        time.sleep(0.05)
        release_build.set()
        results = [first.result(timeout=2), second.result(timeout=2)]

    assert results == [instance, instance]
    assert build_calls == 1
```

Import `ThreadPoolExecutor` from `concurrent.futures` and `threading`/`time` at
the top of the test module.

- [ ] **Step 2: Run the regression and verify RED**

Run:

```bash
$GUIDE_PYTHON -m pytest -c pytest-guide.ini -q \
  tests/guide/application/test_formal_chat_router_http.py \
  -k "singleton_builds_once"
```

Expected: FAIL because the current `lru_cache` may execute the builder twice on
concurrent misses.

- [ ] **Step 3: Replace `lru_cache` with locked publication**

Add to `app/api/v1/chat.py`:

```python
from threading import Lock

_slice1_guide_orchestrator = None
_slice1_guide_orchestrator_lock = Lock()


def _get_slice1_guide_orchestrator():
    global _slice1_guide_orchestrator
    current = _slice1_guide_orchestrator
    if current is not None:
        return current
    with _slice1_guide_orchestrator_lock:
        if _slice1_guide_orchestrator is None:
            _slice1_guide_orchestrator = build_runtime_orchestrator(
                _REPO_ROOT
            )
        return _slice1_guide_orchestrator
```

Keep image bundle and image runtime construction unchanged in this task.

- [ ] **Step 4: Run focused API and concurrency tests**

```bash
$GUIDE_PYTHON -m pytest -c pytest-guide.ini -q \
  tests/guide/application/test_formal_chat_router_http.py \
  tests/guide/application/test_chat_route_wiring.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/api/v1/chat.py \
  tests/guide/application/test_formal_chat_router_http.py \
  tests/guide/application/test_chat_route_wiring.py
git commit -m "fix(guide): publish text composition once"
```

## Task 3: Offload Image Validation and SQLite Creation

**Files:**
- Modify: `app/guide_runtime/image_http.py:22-53`
- Create: `tests/guide/runtime/test_image_http.py`
- Test: `tests/guide/runtime/test_runtime_http.py`

- [ ] **Step 1: Add an event-loop heartbeat regression**

Create the complete regression module:

```python
import asyncio
import time

from app.guide_runtime.image_http import (
    create_image_bundle_from_uploads,
)


class _Upload:
    filename = "product.jpg"
    content_type = "image/jpeg"

    def __init__(self) -> None:
        self._returned = False
        self.closed = False

    async def read(self, size: int) -> bytes:
        if self._returned:
            return b""
        self._returned = True
        return b"safe-bounded-content"

    async def close(self) -> None:
        self.closed = True


class _SlowBundleService:
    def create(self, *, session_id, images):
        time.sleep(0.2)
        return object()


async def _exercise_upload_create_keeps_heartbeat_alive() -> None:
    timer_fired = asyncio.Event()
    asyncio.get_running_loop().call_later(0.05, timer_fired.set)
    await create_image_bundle_from_uploads(
        _SlowBundleService(),
        session_id="heartbeat-upload",
        uploads=[_Upload()],
    )
    assert timer_fired.is_set()


def test_upload_create_keeps_event_loop_heartbeat_alive() -> None:
    asyncio.run(_exercise_upload_create_keeps_heartbeat_alive())
```

- [ ] **Step 2: Verify RED**

```bash
$GUIDE_PYTHON -m pytest -c pytest-guide.ini -q \
  tests/guide/runtime/test_image_http.py \
  -k "upload_create_keeps_heartbeat"
```

Expected: FAIL because `service.create` blocks the event loop.

- [ ] **Step 3: Offload the synchronous service call**

Modify `app/guide_runtime/image_http.py`:

```python
from starlette.concurrency import run_in_threadpool


async def create_image_bundle_from_uploads(
    service: ImageBundleService,
    *,
    session_id: str,
    uploads: Sequence[UploadStream],
) -> ImageBundleUploadReceipt:
    try:
        images = await read_bounded_uploads(uploads)
        return await run_in_threadpool(
            service.create,
            session_id=session_id,
            images=images,
        )
```

Preserve existing typed error mapping.

- [ ] **Step 4: Run upload and HTTP tests**

```bash
$GUIDE_PYTHON -m pytest -c pytest-guide.ini -q \
  tests/guide/application/test_bounded_image_upload.py \
  tests/guide/runtime/test_image_http.py \
  tests/guide/runtime/test_runtime_http.py \
  -k "upload or heartbeat"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/guide_runtime/image_http.py \
  tests/guide/runtime/test_image_http.py \
  tests/guide/runtime/test_runtime_http.py
git commit -m "fix(runtime): offload image bundle creation"
```

## Task 4: Fail Closed on Image/Text Category Conflict

**Files:**
- Modify: `app/guide/application/image_recommendation_flow.py:146-176`
- Test: `tests/guide/application/test_image_recommendation_flow.py`

- [ ] **Step 1: Add the conflict regression**

Add:

```python
def test_confirmed_image_and_text_category_conflict_clarifies() -> None:
    service, receipt, _ = _bundle()
    catalog = _catalog()
    flow = _flow_type()(
        image_bundles=service,
        identity_observer=FakeIdentityObserver(
            candidate_ids=(53, 38, 91),
        ),
        category_catalog=catalog,
        decision_facts=catalog,
        presentation_facts=catalog,
        max_results=10,
    )

    events = list(
        flow.stream(_turn(receipt, "500元内修护精华"))
    )

    assert any(event.event == "clarify" for event in events)
    assert not any(event.event == "decision_process" for event in events)
    assert not any(event.event == "products" for event in events)
    assert events[-1].event == "end"
```

- [ ] **Step 2: Verify RED**

```bash
$GUIDE_PYTHON -m pytest -c pytest-guide.ini -q \
  tests/guide/application/test_image_recommendation_flow.py \
  -k "category_conflict"
```

Expected: FAIL because serum products are currently returned for a sunscreen image.

- [ ] **Step 3: Add explicit conflict handling**

In `_stream_image`, extract the explicit category:

```python
explicit_topics = [
    item.value
    for item in understanding.exact_constraints
    if isinstance(item, CategoryDraft)
]
if explicit_topics and explicit_topics[0] is not anchor_topic:
    yield IntentEvent(data=IntentData(mode="clarify"))
    yield ClarifyEvent(
        data=ClarifyData(
            question=(
                "图片商品品类与文字指定品类不一致。"
                "请确认要找图片同品类商品，还是按文字品类推荐。"
            )
        )
    )
    yield EndEvent(
        data=EndData(
            conversation_version=turn.conversation_version
        )
    )
    return
```

Only inject `anchor_topic` when `explicit_topics` is empty.

- [ ] **Step 4: Run all image flow tests**

```bash
$GUIDE_PYTHON -m pytest -c pytest-guide.ini -q \
  tests/guide/application/test_image_recommendation_flow.py \
  tests/guide/understanding/test_image_identity_observation.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/guide/application/image_recommendation_flow.py \
  tests/guide/application/test_image_recommendation_flow.py
git commit -m "fix(guide): clarify image text category conflicts"
```

## Task 5: Restore the Non-Streaming Image Contract

**Files:**
- Modify: `app/api/v1/chat.py:287-344`
- Test: `tests/guide/application/test_formal_chat_router_http.py:1258-1311`

- [ ] **Step 1: Move assertions to the public top-level fields**

Change the test to require:

```python
assert accepted.json()["answer_contract"] == {
    "product_count": 2,
    "winner_status": "SELECTED",
    "has_unknown_skin": False,
}
assert accepted.json()["conversation_version"] == 0
```

The metadata copy may remain temporarily for compatibility, but top-level fields
are mandatory.

- [ ] **Step 2: Verify RED**

```bash
$GUIDE_PYTHON -m pytest -c pytest-guide.ini -q \
  tests/guide/application/test_formal_chat_router_http.py \
  -k "non_stream_image_chat"
```

Expected: FAIL because both top-level fields are currently `null`.

- [ ] **Step 3: Return the public fields**

Track `conversation_version` directly:

```python
conversation_version = payload.conversation_version
for event_name, event_data in iterate_in_threadpool(
    iter_slice1_guide_legacy_sse_events(
        image_orchestrator,
        turn,
    )
):
    if event_name == "message":
        content = event_data.get("content") or ""
        if content:
            text_parts.append(content)
    elif event_name == "products":
        products = list(event_data.get("products") or [])
    elif event_name == "intent":
        intent_data = event_data
    elif event_name == "decision_process":
        decision_process = event_data.get("decision_process")
    elif event_name == "answer_contract":
        answer_contract = event_data.get("answer_contract")
    elif event_name == "image_observation":
        observation = event_data.get("observation")
        if isinstance(observation, dict):
            metadata["image_observation"] = observation
    elif event_name == "end":
        conversation_version = event_data.get(
            "conversation_version",
            conversation_version,
        )
    elif event_name == "error":
        code = str(event_data.get("error") or "")
        unavailable = code in {
            "GUIDE_INTERNAL_ERROR",
            "IMAGE_RETRIEVAL_UNAVAILABLE",
        }
        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
                if unavailable
                else status.HTTP_400_BAD_REQUEST
            ),
            detail={
                "code": code,
                "message": event_data.get("message"),
            },
        )
return {
    "response": "".join(text_parts),
    "intent": intent_data or {},
    "products": products,
    "decision_process": decision_process,
    "answer_contract": answer_contract,
    "conversation_version": conversation_version,
    "metadata": metadata,
    "session_id": session_id,
}
```

- [ ] **Step 4: Run non-stream and SSE image tests**

```bash
$GUIDE_PYTHON -m pytest -c pytest-guide.ini -q \
  tests/guide/application/test_formal_chat_router_http.py \
  tests/guide/runtime/test_runtime_http.py \
  -k "image_chat or non_stream"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/api/v1/chat.py \
  tests/guide/application/test_formal_chat_router_http.py \
  tests/guide/runtime/test_runtime_http.py
git commit -m "fix(api): expose image answer contract fields"
```

## Task 6: Preserve Favorite Actions After Snapshot Sanitization

**Files:**
- Modify: `app/static/chat.html:3743-3770`
- Modify: `app/static/chat.html:5829-5909`
- Test: `tests/guide/runtime/test_frontend_scope.py`
- Test: `tools/guide_gates/runtime_browser_smoke.py`

- [ ] **Step 1: Add source-level delegation tests**

Add:

```python
def test_recommendation_favorite_uses_persistable_delegation() -> None:
    html = CHAT_HTML.read_text(encoding="utf-8")
    renderer = _javascript_function_source(
        html,
        "function displayProducts(products)",
        "\n\n        // 显示来源引用",
    )
    handler = _javascript_function_source(
        html,
        "function handleRecommendationFavorite(event)",
        "\n\n        function handleProductDetailNavigation",
    )

    assert "onclick=" not in renderer
    assert 'data-favorite-product-id="${escapeHtml(productId)}"' in renderer
    assert "'[data-favorite-product-id]'" in handler
    assert "toggleFavoriteProduct(productId)" in handler
    assert (
        "chatMessages.addEventListener("
        "'click', handleRecommendationFavorite)"
        in html
    )
```

- [ ] **Step 2: Verify RED**

```bash
$GUIDE_PYTHON -m pytest -c pytest-guide.ini -q \
  tests/guide/runtime/test_frontend_scope.py \
  -k "favorite_uses_persistable"
```

Expected: FAIL because the button uses inline `onclick`.

- [ ] **Step 3: Implement delegated favorite handling**

Add:

```javascript
function handleRecommendationFavorite(event) {
    const button = event.target?.closest(
        '[data-favorite-product-id]'
    );
    if (!button || !chatMessages.contains(button)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    const productId = button.dataset.favoriteProductId;
    toggleFavoriteProduct(productId);
    const stored = getStoredProducts().find(
        item => String(item.id) === String(productId)
    );
    button.classList.toggle('active', Boolean(stored?.favorite));
}

chatMessages.addEventListener(
    'click',
    handleRecommendationFavorite
);
```

Register this listener before `handleProductDetailNavigation`; the immediate
propagation stop prevents the enclosing product card from opening when the
favorite button is clicked.

Render:

```javascript
<button class="recommendation-save ${isFavorite ? 'active' : ''}"
        data-favorite-product-id="${escapeHtml(productId)}">
```

- [ ] **Step 4: Add a real browser snapshot-restore assertion**

Extend the smoke script:

```python
favorite = page.locator("[data-favorite-product-id]").first
product_id = await favorite.get_attribute("data-favorite-product-id")
await favorite.click()
await page.reload()
restored = page.locator(
    f'[data-favorite-product-id="{product_id}"]'
).first
await restored.click()
assert await restored.count() == 1
```

The exact navigation may use existing history helpers; the required proof is a
click after sanitized snapshot restoration changing persisted favorite state.

- [ ] **Step 5: Run frontend tests**

```bash
$GUIDE_PYTHON -m pytest -c pytest-guide.ini -q \
  tests/guide/runtime/test_frontend_scope.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/static/chat.html \
  tests/guide/runtime/test_frontend_scope.py \
  tools/guide_gates/runtime_browser_smoke.py
git commit -m "fix(frontend): delegate restored favorite actions"
```

## Task 7: Add the Backend Card Display Contract

**Files:**
- Create: `app/guide/presentation/card_display.py`
- Create: `tests/guide/presentation/test_card_display_contracts.py`
- Modify: `app/guide/presentation/contracts.py`
- Modify: `app/guide/presentation/sse_events.py`
- Modify: `app/guide/application/text_recommendation_flow.py`
- Modify: `app/guide/application/image_recommendation_flow.py`
- Modify: `app/guide/application/chat_api_adapter.py`
- Test: `tests/guide/application/test_chat_api_adapter.py`
- Test: `tests/guide/application/test_text_recommendation_flow.py`

- [ ] **Step 1: Write strict contract tests**

Create:

```python
import pytest
from pydantic import ValidationError

from app.guide.presentation.contracts import CardDisplayContract


@pytest.mark.parametrize(
    ("mode", "ids", "reason"),
    [
        ("none", [], None),
        ("single", [91], "recommendation"),
        ("recommendation", [91, 38], "recommendation"),
        ("recommendation", [55, 57, 54], "recommendation"),
        ("comparison", [53, 55], "comparison"),
        ("comparison", [53, 55, 57, 54], "comparison"),
    ],
)
def test_card_display_contract_accepts_exact_visible_ids(
    mode,
    ids,
    reason,
) -> None:
    contract = CardDisplayContract(
        mode=mode,
        visible_product_ids=ids,
        max_cards=len(ids),
        reason=reason,
    )
    assert contract.visible_product_ids == ids


@pytest.mark.parametrize(
    "payload",
    [
        {
            "mode": "none",
            "visible_product_ids": [91],
            "max_cards": 1,
            "reason": None,
        },
        {
            "mode": "single",
            "visible_product_ids": [91, 38],
            "max_cards": 2,
            "reason": "product",
        },
        {
            "mode": "recommendation",
            "visible_product_ids": [55, 55],
            "max_cards": 2,
            "reason": "recommendation",
        },
        {
            "mode": "comparison",
            "visible_product_ids": [53],
            "max_cards": 1,
            "reason": "comparison",
        },
    ],
)
def test_card_display_contract_rejects_ambiguous_shapes(payload) -> None:
    with pytest.raises(ValidationError):
        CardDisplayContract(**payload)
```

- [ ] **Step 2: Verify RED**

```bash
$GUIDE_PYTHON -m pytest -c pytest-guide.ini -q \
  tests/guide/presentation/test_card_display_contracts.py
```

Expected: collection FAIL because `CardDisplayContract` is missing.

- [ ] **Step 3: Implement the strict contract**

Add to `app/guide/presentation/contracts.py`:

```python
from typing import Self
from pydantic import Field, model_validator


class CardDisplayContract(_StrictContract):
    mode: Literal[
        "none",
        "single",
        "recommendation",
        "comparison",
    ]
    visible_product_ids: list[int] = Field(max_length=4)
    max_cards: int = Field(ge=0, le=4)
    reason: Literal[
        "product",
        "recommendation",
        "comparison",
    ] | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        count = len(self.visible_product_ids)
        if count != len(set(self.visible_product_ids)):
            raise ValueError("visible product IDs must be unique")
        if self.max_cards != count:
            raise ValueError("max_cards must equal visible product count")
        if self.mode == "none":
            if count != 0 or self.reason is not None:
                raise ValueError("none mode forbids products and reason")
            return self
        if self.mode == "single" and count != 1:
            raise ValueError("single mode requires one product")
        if self.mode == "recommendation" and not 1 <= count <= 3:
            raise ValueError("recommendation requires one to three products")
        if self.mode == "comparison" and not 2 <= count <= 4:
            raise ValueError("comparison requires two to four products")
        if self.reason is None:
            raise ValueError("visible cards require a reason")
        return self
```

- [ ] **Step 4: Add the typed SSE event**

In `sse_events.py`:

```python
from app.guide.presentation.contracts import (
    CardDisplayContract,
    ProductCard,
)


class CardDisplayContractEvent(_Strict):
    event: Literal["card_display_contract"] = "card_display_contract"
    data: CardDisplayContract
```

Add it to the `SseEvent` discriminated union immediately after
`AnswerContractEvent`.

- [ ] **Step 5: Add contract derivation**

Create `card_display.py`:

```python
from collections.abc import Sequence

from app.guide.presentation.contracts import (
    CardDisplayContract,
    ProductCard,
)


def recommendation_card_display(
    cards: Sequence[ProductCard],
) -> CardDisplayContract:
    product_ids = [card.product_id for card in cards]
    if not product_ids:
        return CardDisplayContract(
            mode="none",
            visible_product_ids=[],
            max_cards=0,
            reason=None,
        )
    return CardDisplayContract(
        mode="single" if len(product_ids) == 1 else "recommendation",
        visible_product_ids=product_ids,
        max_cards=len(product_ids),
        reason="recommendation",
    )
```

- [ ] **Step 6: Make text output backend-visible only**

In `_stream_recommendation`, derive:

```python
visible_decision = decision.model_copy(
    update={
        "ordered_product_ids": decision.ordered_product_ids[:3],
    },
    deep=True,
)
response = self._build_plan(visible_decision)
card_display = recommendation_card_display(
    response.structured_events
)
```

Use `visible_decision` for the response message, visible snapshot, decision
process, answer contract, and products event. In every success event list, insert
this exact event immediately after the existing `AnswerContractEvent` and before
the existing `ProductsEvent`:

```python
CardDisplayContractEvent(data=card_display),
```

For followups, add the previously missing answer contract and the card contract:

```python
card_display = recommendation_card_display(cards)
success_events: list[SseEvent] = [
    StageEvent(
        data=StageData(
            stage="state",
            summary="已读取最近一次展示的候选商品。",
        )
    ),
    IntentEvent(data=IntentData(mode="followup")),
    AnswerContractEvent(
        data=AnswerContractData(
            product_count=len(cards),
            winner_status=result.status.upper(),
            has_unknown_skin=any(
                card.skin_match == "unknown"
                for card in cards
            ),
        )
    ),
    CardDisplayContractEvent(data=card_display),
    ProductsEvent(data=ProductsData(cards=cards)),
    MessageEvent(data=MessageData(content=message)),
]
```

For image recommendations, compute `card_display` from
`response.structured_events` and insert `CardDisplayContractEvent` between the
existing answer and products events.

- [ ] **Step 7: Convert the event for the shared API**

In `chat_api_adapter.py`:

```python
if isinstance(event, CardDisplayContractEvent):
    return event.data.model_dump(mode="json")
```

- [ ] **Step 8: Expose the contract in non-stream responses**

Add to `ChatResponse`:

```python
card_display_contract: Optional[Dict] = None
```

In both Guide non-stream branches initialize:

```python
card_display_contract: dict[str, Any] | None = None
```

Capture and return it:

```python
elif event_name == "card_display_contract":
    card_display_contract = event_data
```

Add this key to each Guide non-stream return dictionary:

```python
"card_display_contract": card_display_contract,
```

The SSE route continues to pass the typed event through unchanged.

- [ ] **Step 9: Update tests to require exact IDs**

The sunscreen adapter test must change from eleven backend products to three:

```python
assert [
    item["id"] for item in products["products"]
] == [55, 57, 54]
card_display = next(
    data
    for name, data in events
    if name == "card_display_contract"
)
assert card_display == {
    "mode": "recommendation",
    "visible_product_ids": [55, 57, 54],
    "max_cards": 3,
    "reason": "recommendation",
}
```

Add one-card and two-card assertions for followup and serum cases.

- [ ] **Step 10: Run presentation and application suites**

```bash
$GUIDE_PYTHON -m pytest -c pytest-guide.ini -q \
  tests/guide/presentation \
  tests/guide/application/test_chat_api_adapter.py \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/application/test_image_recommendation_flow.py
```

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add app/guide/presentation/contracts.py \
  app/guide/presentation/sse_events.py \
  app/guide/presentation/card_display.py \
  app/guide/application/text_recommendation_flow.py \
  app/guide/application/image_recommendation_flow.py \
  app/guide/application/chat_api_adapter.py \
  app/api/v1/chat.py \
  tests/guide/presentation/test_card_display_contracts.py \
  tests/guide/application/test_chat_api_adapter.py \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/application/test_image_recommendation_flow.py
git commit -m "feat(guide): make card display backend authoritative"
```

## Task 8: Remove Frontend Card Inference and Filling

**Files:**
- Modify: `app/static/chat.html:5289-5368`
- Modify: `app/static/chat.html:5579-5676`
- Modify: `app/static/chat.html:5829-5909`
- Test: `tests/guide/runtime/test_frontend_scope.py`
- Test: `tools/guide_gates/runtime_browser_smoke.py`

- [ ] **Step 1: Add an executable selector test**

Extract and execute a new function:

```javascript
function selectContractProducts(products, contract) {
    const list = Array.isArray(products) ? products : [];
    if (!contract) return list.slice(0, 3);
    if (contract.mode === 'none') return [];
    const byId = new Map(
        list.map(product => [String(product.id), product])
    );
    const selected = contract.visible_product_ids.map(
        productId => byId.get(String(productId))
    );
    if (selected.some(product => !product)) {
        throw new Error('CARD_DISPLAY_CONTRACT_MISMATCH');
    }
    if (selected.length !== contract.max_cards) {
        throw new Error('CARD_DISPLAY_CONTRACT_MISMATCH');
    }
    return selected;
}
```

The Node test must prove:

```text
one visible ID -> one product
two visible IDs -> two products in backend order
none -> zero products
missing ID -> throws
no contract legacy fallback -> first three only, no text inference
```

- [ ] **Step 2: Verify RED**

```bash
$GUIDE_PYTHON -m pytest -c pytest-guide.ini -q \
  tests/guide/runtime/test_frontend_scope.py \
  -k "contract_products"
```

Expected: FAIL because the selector and card event handling are absent.

- [ ] **Step 3: Store the card contract with deferred products**

Add:

```javascript
const deferredPanels = {
    imageObservation: null,
    cardDisplayContract: null,
    products: [],
    citations: [],
    pitfalls: [],
    decisionProcess: null
};
```

Handle:

```javascript
} else if (eventName === 'card_display_contract') {
    deferredPanels.cardDisplayContract = data;
```

- [ ] **Step 4: Delete all frontend card inference**

Remove:

- `filterProductsForRenderedText` use in panel flushing;
- heading and nickname matching for card selection;
- `if (cardProducts.length < 3)` filling;
- hard-coded `slice(0, 3)` in `displayProducts`.

Replace flushing with:

```javascript
const finalProducts = selectContractProducts(
    sanitizedProducts,
    deferredPanels.cardDisplayContract
);
if (finalProducts.length) {
    displayProducts(finalProducts);
}
deferredPanels.products = [];
deferredPanels.cardDisplayContract = null;
```

- [ ] **Step 5: Add exact browser count assertions**

In the normal browser gate assert:

```text
initial sunscreen recommendation -> 3 cards
repair serum recommendation -> 2 cards
"第二款呢" -> 1 card
clarify/error -> 0 new cards
```

Use the card panel nearest the current assistant turn, not a page-global count
that includes history.

- [ ] **Step 6: Run frontend tests**

```bash
$GUIDE_PYTHON -m pytest -c pytest-guide.ini -q \
  tests/guide/runtime/test_frontend_scope.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/static/chat.html \
  tests/guide/runtime/test_frontend_scope.py \
  tools/guide_gates/runtime_browser_smoke.py
git commit -m "fix(frontend): render exact backend card contracts"
```

## Task 9: Centralize the Guide/Legacy Owner Matrix

**Files:**
- Modify: `app/guide/application/chat_api_adapter.py`
- Modify: `app/api/v1/chat.py`
- Modify: `tests/guide/application/test_chat_api_adapter.py`
- Modify: `tests/guide/application/test_chat_route_wiring.py`
- Create: `docs/audits/phase2-day1/owner_matrix.csv`

- [ ] **Step 1: Write the owner matrix test**

Add:

```python
@pytest.mark.parametrize(
    ("message", "version", "has_bundle", "legacy_image", "owner"),
    [
        ("500内油敏肌防晒", 0, False, False, "guide_text"),
        ("第二款呢", 1, False, False, "guide_text"),
        ("第二款呢", 0, False, False, "legacy"),
        ("找相似款", 0, True, False, "guide_image"),
        ("看看图片", 0, False, True, "legacy"),
        ("今天天气怎么样", 0, False, False, "legacy"),
    ],
)
def test_chat_owner_matrix(
    message,
    version,
    has_bundle,
    legacy_image,
    owner,
) -> None:
    assert classify_chat_owner(
        message=message,
        conversation_version=version,
        has_image_bundle_reference=has_bundle,
        has_legacy_image_payload=legacy_image,
    ).value == owner
```

- [ ] **Step 2: Verify RED**

```bash
$GUIDE_PYTHON -m pytest -c pytest-guide.ini -q \
  tests/guide/application/test_chat_api_adapter.py \
  -k "owner_matrix"
```

Expected: FAIL because the centralized classifier is absent.

- [ ] **Step 3: Implement the owner enum and classifier**

Add:

```python
from enum import Enum


class ChatOwner(str, Enum):
    GUIDE_TEXT = "guide_text"
    GUIDE_IMAGE = "guide_image"
    LEGACY = "legacy"


def classify_chat_owner(
    *,
    message: str,
    conversation_version: int,
    has_image_bundle_reference: bool,
    has_legacy_image_payload: bool,
) -> ChatOwner:
    if has_image_bundle_reference:
        return ChatOwner.GUIDE_IMAGE
    if has_legacy_image_payload:
        return ChatOwner.LEGACY
    if should_use_slice1_guide(
        message=message,
        image_results=None,
        conversation_version=conversation_version,
    ):
        return ChatOwner.GUIDE_TEXT
    return ChatOwner.LEGACY
```

- [ ] **Step 4: Use one owner decision in both API routes**

At the start of non-stream and stream dispatch:

```python
owner = classify_chat_owner(
    message=payload.message,
    conversation_version=payload.conversation_version,
    has_image_bundle_reference=payload.has_image_bundle_reference,
    has_legacy_image_payload=payload.has_legacy_image_payload,
)
```

Branch on `ChatOwner.GUIDE_IMAGE`, `ChatOwner.GUIDE_TEXT`, then legacy. Do not
duplicate owner predicates later in either route.

- [ ] **Step 5: Generate the CSV evidence**

Write:

```csv
case_id,message,conversation_version,image_bundle,legacy_image,expected_owner
category_text,500内油敏肌防晒,0,false,false,guide_text
owned_followup,第二款呢,1,false,false,guide_text
legacy_followup,第二款呢,0,false,false,legacy
server_bundle,找相似款,0,true,false,guide_image
legacy_image,看看图片,0,false,true,legacy
unsupported_text,今天天气怎么样,0,false,false,legacy
```

- [ ] **Step 6: Run API routing tests**

```bash
$GUIDE_PYTHON -m pytest -c pytest-guide.ini -q \
  tests/guide/application/test_chat_api_adapter.py \
  tests/guide/application/test_chat_route_wiring.py \
  tests/guide/application/test_formal_chat_router_http.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/guide/application/chat_api_adapter.py \
  app/api/v1/chat.py \
  tests/guide/application/test_chat_api_adapter.py \
  tests/guide/application/test_chat_route_wiring.py \
  tests/guide/application/test_formal_chat_router_http.py \
  docs/audits/phase2-day1/owner_matrix.csv
git commit -m "refactor(api): centralize chat ownership"
```

## Task 10: Freeze Future Phase 2 Shared Contracts

**Files:**
- Create: `app/guide/feedback/profile_contracts.py`
- Create: `app/guide/understanding/consultation_contracts.py`
- Create: `app/guide/understanding/multi_image_contracts.py`
- Create: `tests/guide/test_phase2_shared_contracts.py`

- [ ] **Step 1: Write profile contract tests**

Create the test module with these imports:

```python
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.guide.feedback.profile_contracts import (
    ConfirmedProfileFact,
    ProfileOwnerRef,
)
from app.guide.understanding.consultation_contracts import (
    ProvisionalConsultationConclusion,
)
from app.guide.understanding.image_contracts import IdentityState
from app.guide.understanding.multi_image_contracts import (
    ImageTaskReference,
    MultiImageTaskContext,
)
```

Then add:

```python
def test_confirmed_profile_fact_records_owner_source_and_version() -> None:
    fact = ConfirmedProfileFact(
        owner=ProfileOwnerRef(
            scope="local_demo",
            subject_id="profile_0123456789abcdef",
        ),
        field="skin_type",
        value="sensitive",
        source_turn_id="turn_0123456789abcdef",
        source_kind="confirmed_consultation",
        confirmed_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        profile_version=1,
    )
    assert fact.profile_version == 1


def test_unconfirmed_inference_is_not_a_profile_source() -> None:
    with pytest.raises(ValidationError):
        ConfirmedProfileFact(
            owner=ProfileOwnerRef(
                scope="local_demo",
                subject_id="profile_0123456789abcdef",
            ),
            field="skin_type",
            value="sensitive",
            source_turn_id="turn_0123456789abcdef",
            source_kind="model_inference",
            confirmed_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
            profile_version=1,
        )
```

- [ ] **Step 2: Write consultation contract tests**

Require:

```python
def test_consultation_conclusion_keeps_uncertainty_and_escalation() -> None:
    conclusion = ProvisionalConsultationConclusion(
        skin_target="sensitive",
        confidence="medium",
        evidence=["recurrent_redness"],
        uncertainties=["stinging_unknown"],
        escalation="如持续红肿、疼痛或渗出，请停止护肤建议并就医。",
        confirmed_by_user=False,
    )
    assert conclusion.confirmed_by_user is False
```

- [ ] **Step 3: Write multi-image contract tests**

Require:

```python
def test_multi_image_task_requires_unique_contiguous_ordinals() -> None:
    task = MultiImageTaskContext(
        mode="compare",
        bundle_id="bundle_" + "a" * 32,
        references=[
            ImageTaskReference(
                image_id="image_" + "b" * 32,
                ordinal=1,
                confirmed_product_id=53,
                identity_state=IdentityState.CONFIRMED,
            ),
            ImageTaskReference(
                image_id="image_" + "c" * 32,
                ordinal=2,
                confirmed_product_id=55,
                identity_state=IdentityState.CONFIRMED,
            ),
        ],
    )
    assert [item.ordinal for item in task.references] == [1, 2]
```

- [ ] **Step 4: Verify RED**

```bash
$GUIDE_PYTHON -m pytest -c pytest-guide.ini -q \
  tests/guide/test_phase2_shared_contracts.py
```

Expected: collection FAIL because the modules are missing.

- [ ] **Step 5: Implement profile contracts**

Create:

```python
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ProfileOwnerRef(_Strict):
    scope: Literal["authenticated_user", "local_demo"]
    subject_id: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=16, max_length=160),
    ]


class ConfirmedProfileFact(_Strict):
    owner: ProfileOwnerRef
    field: Literal[
        "skin_type",
        "skin_concern",
        "ingredient_exclusion",
        "preferred_brand",
        "preferred_category",
        "price_sensitivity",
    ]
    value: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
    ]
    source_turn_id: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=16, max_length=160),
    ]
    source_kind: Literal[
        "explicit_user",
        "confirmed_consultation",
    ]
    confirmed_at: datetime
    profile_version: int = Field(ge=1)
```

- [ ] **Step 6: Implement consultation contracts**

Create:

```python
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ConsultationObservation(_Strict):
    code: Literal[
        "post_cleanse_tightness",
        "t_zone_oiliness",
        "recurrent_redness",
        "stinging",
        "flaking",
    ]
    answer: Literal["yes", "no", "sometimes", "unknown"]
    source_turn_id: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=16, max_length=160),
    ]


class ProvisionalConsultationConclusion(_Strict):
    skin_target: Literal[
        "oily_sensitive",
        "oily",
        "dry",
        "combination",
        "sensitive",
        "normal",
    ] | None
    confidence: Literal["low", "medium", "high"]
    evidence: list[str] = Field(min_length=1, max_length=8)
    uncertainties: list[str] = Field(max_length=8)
    escalation: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=240),
    ]
    confirmed_by_user: bool
```

- [ ] **Step 7: Implement multi-image contracts**

Create:

```python
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.guide.understanding.contracts import OpaqueBundleId, OpaqueImageId
from app.guide.understanding.image_contracts import IdentityState


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ImageTaskReference(_Strict):
    image_id: OpaqueImageId
    ordinal: int = Field(ge=1, le=4)
    confirmed_product_id: int | None = None
    identity_state: IdentityState


class MultiImageTaskContext(_Strict):
    mode: Literal["identify", "similar", "suitability", "compare"]
    bundle_id: OpaqueBundleId
    references: list[ImageTaskReference] = Field(
        min_length=1,
        max_length=4,
    )

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        ordinals = [item.ordinal for item in self.references]
        if ordinals != list(range(1, len(ordinals) + 1)):
            raise ValueError("image ordinals must be contiguous")
        image_ids = [item.image_id for item in self.references]
        if len(image_ids) != len(set(image_ids)):
            raise ValueError("image references must be unique")
        for reference in self.references:
            if (
                reference.identity_state is IdentityState.CONFIRMED
                and reference.confirmed_product_id is None
            ):
                raise ValueError(
                    "confirmed identity requires product ID"
                )
            if (
                reference.identity_state is not IdentityState.CONFIRMED
                and reference.confirmed_product_id is not None
            ):
                raise ValueError(
                    "unconfirmed identity forbids product ID"
                )
        if self.mode == "compare" and len(self.references) < 2:
            raise ValueError("compare requires at least two images")
        return self
```

- [ ] **Step 8: Run contracts and boundaries**

```bash
$GUIDE_PYTHON -m pytest -c pytest-guide.ini -q \
  tests/guide/test_phase2_shared_contracts.py \
  tests/guide/test_public_contracts.py
$GUIDE_PYTHON app/guide/check_boundaries.py app/guide
```

Expected: PASS and zero boundary violations.

- [ ] **Step 9: Commit**

```bash
git add app/guide/feedback/profile_contracts.py \
  app/guide/understanding/consultation_contracts.py \
  app/guide/understanding/multi_image_contracts.py \
  tests/guide/test_phase2_shared_contracts.py
git commit -m "feat(guide): freeze phase2 shared contracts"
```

## Task 11: Full Verification and Independent Review

**Files:**
- Modify: `docs/audits/phase2-day1/morning_handoff.md`

- [ ] **Step 1: Run focused stabilization tests**

```bash
$GUIDE_PYTHON -m pytest -c pytest-guide.ini -q \
  tests/guide/presentation/test_card_display_contracts.py \
  tests/guide/application/test_chat_api_adapter.py \
  tests/guide/application/test_chat_route_wiring.py \
  tests/guide/application/test_formal_chat_router_http.py \
  tests/guide/application/test_image_recommendation_flow.py \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/runtime/test_frontend_scope.py \
  tests/guide/runtime/test_runtime_http.py \
  tests/guide/test_phase2_shared_contracts.py
```

Expected: PASS.

- [ ] **Step 2: Run full Guide and runtime suites**

```bash
$GUIDE_PYTHON -m pytest -c pytest-guide.ini -q
$GUIDE_PYTHON -m pytest -c pytest-guide.ini -q tests/guide/runtime
```

Expected: at least `901` Guide tests and `105` runtime tests pass, with all new
tests included and zero failures.

- [ ] **Step 3: Run static and architecture gates**

```bash
PYTHONPYCACHEPREFIX=/private/tmp/xiaoro-phase2-day1-pycache \
  $GUIDE_PYTHON -m compileall -q app/guide app/guide_runtime app/api/v1/chat.py
$GUIDE_PYTHON app/guide/check_boundaries.py app/guide
$GUIDE_PYTHON app/guide/check_boundaries.py app/guide_runtime
git diff --check phase2-day1-base..HEAD
test -z "$(git diff --name-only phase2-day1-base..HEAD -- app/services app/database data/canonical)"
test "$(shasum -a 256 app/guide/decision/deterministic_ranking.py | awk '{print $1}')" = \
  "4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f"
```

Expected: all commands exit `0`.

- [ ] **Step 4: Run normal and adversarial browser gates**

Start the runtime with the verified image environment and offline flags. Run:

```bash
$GUIDE_PYTHON tools/guide_gates/runtime_browser_smoke.py \
  --url http://127.0.0.1:8765/chat \
  --screenshot /private/tmp/xiaoro-phase2-day1-smoke.png
$GUIDE_PYTHON tools/guide_gates/runtime_browser_adversarial.py \
  --url http://127.0.0.1:8765/chat
```

Required assertions:

```text
3-card sunscreen
2-card repair serum
1-card ordinal followup
0-card clarify/error
snapshot-restored favorite works
no page errors
no failed product images
no stale-session writes
```

- [ ] **Step 5: Run independent full-file review**

Review all Day 1 production files for:

```text
logic
business semantics
security
concurrency
robustness
performance
```

Fix every confirmed P0–P2 with RED-first tests. Re-run Steps 1–4 after fixes.

- [ ] **Step 6: Complete the handoff**

Add the following fixed completion section, followed by the literal summary lines
printed by the full test commands and the literal commit SHA printed by
`git rev-parse HEAD`:

```markdown
## Completion

- Five P1 findings: fixed and regression-tested
- Card display contract: frozen
- Frontend card inference/fill: removed
- Owner matrix: frozen
- Consultation/profile/multi-image contracts: frozen
- Guide full: PASS, no fewer than 901 tests
- Runtime full: PASS, no fewer than 105 tests
- Normal browser: PASS
- Adversarial browser: PASS
- Boundary violations: 0
- Protected path diff: 0
- Ranking SHA: unchanged

## Parallel Worktree Inputs

- All three worktrees use the final clean Day 1 commit printed by
  `git rev-parse HEAD`.
```

- [ ] **Step 7: Commit final evidence**

```bash
git add docs/audits/phase2-day1/morning_handoff.md
git commit -m "docs(phase2): close day1 stabilization"
```

- [ ] **Step 8: Fast-forward the shared workspace**

Run from the Day 1 worktree:

```bash
git -C /Users/bytedance/Desktop/xiaoro-fresh status --short
git -C /Users/bytedance/Desktop/xiaoro-fresh merge \
  --ff-only phase2-day1-stabilization
```

Expected: the shared workspace is clean before the merge and `rebuild`
fast-forwards to the final Day 1 commit.

- [ ] **Step 9: Create the three parallel worktrees**

```bash
DAY1_HEAD=$(git rev-parse HEAD)
git worktree add \
  /private/tmp/xiaoro-phase2-consultation-profile \
  -b phase2-consultation-profile \
  "$DAY1_HEAD"
git worktree add \
  /private/tmp/xiaoro-phase2-multi-image-ocr \
  -b phase2-multi-image-ocr \
  "$DAY1_HEAD"
git worktree add \
  /private/tmp/xiaoro-phase2-scenario-feedback \
  -b phase2-scenario-feedback \
  "$DAY1_HEAD"
```

Expected: all three worktrees point to the same frozen Day 1 commit. Return
control to the continuous plan and immediately launch the three independent
workstreams.

- [ ] **Step 10: Verify final integration**

```bash
git -C /Users/bytedance/Desktop/xiaoro-fresh status --short
git -C /Users/bytedance/Desktop/xiaoro-fresh log \
  --oneline phase2-day1-base..HEAD
git worktree list
```

Expected: clean shared workspace, only Day 1 commits after
`phase2-day1-base`, and the three new worktrees present at the same base.

Do not push, deploy, switch production traffic, or modify Canonical. Do not
mark the overall Goal complete; continue with the next milestone in
`2026-08-09-phase2-continuous-ralph.md`.
