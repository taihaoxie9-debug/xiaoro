# Guide Intent And Cutover Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the missing parallel semantic-intent path, validate it with real SiliconFlow models, make Guide the only public runtime with cross-worker state, and remove the obsolete V1/V2 chat chain.

**Architecture:** Exact parsing, constrained LLM proposals, and typed session/profile context produce independent signals that a single merger reconciles. The existing deterministic retrieval/decision/presentation chain remains authoritative. After real-model and cross-worker gates pass, the clean Guide runtime becomes the default entry; only then are unreachable legacy chat modules physically removed.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, httpx, SQLite CAS, pytest, Playwright, SiliconFlow OpenAI-compatible API

---

## Authority And Conflict Resolution

Read these documents before any implementation:

1. `docs/superpowers/specs/2026-08-10-guide-intent-cutover-and-pragmatic-data-recovery-design.md`
2. `docs/superpowers/specs/2026-08-06-xiaoro-clean-growth-architecture-design.md`
3. This plan
4. `.trae/specs/complete-phase2-continuously/**`
5. `.trae/specs/complete-category-aware-guide-data-foundation/**`

When they conflict:

- The 2026-08-10 design overrides the old `overall COMPLETE` wording.
- The project gets one opening formal full-file audit, not per-capability or final repeat audits.
- `unsupported -> legacy` is superseded by `unsupported -> 1–2 Guide clarifications -> explicit scope notice`.
- Old `app/services/**` protection remains in force through Tasks 0–8. Task 9 alone is authorized to delete proven-unreachable legacy chat files; it must not edit or rehabilitate them.
- Canonical assets and deterministic ranking remain immutable for the entire plan.
- Old plans that disabled LLM were slice-specific offline gates; they do not override the new real-model requirement.

## File Responsibility Map

### New intent files

- `app/guide/understanding/semantic_contracts.py`: strict model proposal, semantic context, trace and failure contracts.
- `app/guide/understanding/parallel_understanding.py`: launch exact and semantic lanes and return independent signals.
- `app/guide/intent/signal_merger.py`: the only place that merges exact, model and state signals.
- `app/guide/adapters/llm/siliconflow_intent.py`: HTTP adapter, response parsing and provider failure mapping.
- `app/guide/adapters/llm/intent_cache.py`: bounded SQLite cache for validated proposals only.
- `app/guide/adapters/llm/intent_prompt.py`: versioned prompt text and JSON-mode messages.
- `app/guide_runtime/llm_config.py`: environment-only Guide LLM configuration.
- `tools/guide_gates/intent_model_ab.py`: deterministic A/B runner and report writer.
- `tests/fixtures/guide/intent/semantic_intent_ab_v1.jsonl`: frozen expected cases.

### Modified shared files

- `app/guide/understanding/contracts.py`: store typed semantic proposal and merge trace.
- `app/guide/understanding/ports.py`: semantic and understanding protocols.
- `app/guide/understanding/text_understanding.py`: exact-only implementation remains available for no-model tests.
- `app/guide/intent/task_planning.py`: compile merged goal/topic while preserving hard exact constraints.
- `app/guide/application/text_recommendation_flow.py`: inject understanding port; no provider import.
- `app/guide_runtime/composition.py`: build semantic adapter/cache, durable conversation state and orchestrator.
- `app/guide_runtime/sse.py`: route only typed Guide outcomes.
- `app/guide_runtime/app.py`: expose clean Guide-only message and stream endpoints.
- `requirements-guide-runtime.txt`: add `httpx==0.27.2`.
- `Dockerfile`, `docker-compose.yml`, `docker-compose.prod.yml`, `start.sh`, `README.md`, `DEPLOY.md`: default to `app.guide_runtime.app:app`.

### Protected throughout

- `data/canonical/**`
- `app/guide/decision/deterministic_ranking.py`
- all approved category/review assets
- product/card order contracts

## Task 0: Freeze Baseline And Perform The Single Formal Audit

**Files:**
- Create: `docs/audits/guide-closure/progress.md`
- Create: `docs/audits/guide-closure/audit_ledger.csv`
- Create: `docs/audits/guide-closure/production_scope.txt`
- Create: `docs/audits/guide-closure/baseline_manifest.json`
- Test: `tests/guide/test_closure_baseline.py`

- [ ] **Step 1: Write the baseline test**

```python
from hashlib import sha256
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RANKING = ROOT / "app/guide/decision/deterministic_ranking.py"


def test_closure_baseline_keeps_ranking_and_canonical_locked() -> None:
    assert sha256(RANKING.read_bytes()).hexdigest() == (
        "4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f"
    )
    assert not (ROOT / "data/canonical/core_products_v1.jsonl").stat().st_size == 0
```

- [ ] **Step 2: Run the baseline test**

Run:

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q tests/guide/test_closure_baseline.py
```

Expected: PASS.

- [ ] **Step 3: Freeze the production scope**

Run:

```bash
mkdir -p docs/audits/guide-closure
git ls-files \
  'app/guide/**/*.py' \
  'app/guide_runtime/*.py' \
  'app/api/v1/chat.py' \
  'Dockerfile' \
  'docker-compose*.yml' \
  'start.sh' \
  'requirements-guide-runtime*.txt' \
  | LC_ALL=C sort > docs/audits/guide-closure/production_scope.txt
```

Write `baseline_manifest.json` from the current exact SHA:

```bash
python3 - <<'PY'
import json
from pathlib import Path
import subprocess

base_commit = subprocess.check_output(
    ["git", "rev-parse", "HEAD"],
    text=True,
).strip()
if len(base_commit) != 40:
    raise SystemExit("base commit must be a full SHA")
payload = {
    "schema_version": "guide-closure-baseline-v1",
    "base_commit": base_commit,
    "ranking_sha256": (
        "4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f"
    ),
    "formal_full_file_audit_limit": 1,
    "push_deploy_traffic_switch": False,
}
Path("docs/audits/guide-closure/baseline_manifest.json").write_text(
    json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
PY
python3 -m json.tool \
  docs/audits/guide-closure/baseline_manifest.json >/dev/null
```

- [ ] **Step 4: Invoke the only formal full-file audit**

Freeze one audit key from:

```text
audit_profile = guide-closure-full-file-v1
base_commit = baseline_manifest.base_commit
scope = production_scope.txt sorted paths and Git blob IDs
```

Record exactly one invocation row in `audit_ledger.csv`:

```csv
audited_at,audit_profile,audit_key,base_commit,scope_sha256,status,findings,report_path,real_invocations
```

Expected: `real_invocations=1`. No later task may invoke another formal full-file audit.

- [ ] **Step 5: Convert every confirmed finding to a RED node**

For each P0–P2 finding, add a focused test under the owning layer. Do not fix findings in the audit worktree. Record test node IDs in `progress.md`.

- [ ] **Step 6: Commit baseline evidence**

```bash
git add tests/guide/test_closure_baseline.py docs/audits/guide-closure
git commit -m "test(guide): freeze closure audit baseline"
```

## Task 1: Define Strict Semantic Intent Contracts

**Files:**
- Create: `app/guide/understanding/semantic_contracts.py`
- Modify: `app/guide/understanding/contracts.py`
- Modify: `app/guide/understanding/ports.py`
- Test: `tests/guide/understanding/test_semantic_intent_contracts.py`

- [ ] **Step 1: Write strict contract RED tests**

```python
import pytest
from pydantic import ValidationError

from app.guide.understanding.semantic_contracts import (
    SemanticContext,
    SemanticGoal,
    SemanticIntentProposal,
)
from app.guide.understanding.contracts import TopicCode


def test_semantic_proposal_accepts_only_closed_enums() -> None:
    proposal = SemanticIntentProposal(
        goal=SemanticGoal.RECOMMENDATION,
        topic=TopicCode.FRAGRANCE,
        concerns=["light_texture"],
        observations=[],
        references=[],
        confidence=0.96,
        clarification_hint=None,
    )
    assert proposal.schema_version == "guide-semantic-intent-v1"


@pytest.mark.parametrize(
    "forbidden",
    ("product_ids", "candidate_ids", "product_facts", "score", "winner", "sql"),
)
def test_semantic_proposal_rejects_forbidden_fields(forbidden: str) -> None:
    payload = {
        "goal": "recommendation",
        "topic": "fragrance",
        "concerns": [],
        "observations": [],
        "references": [],
        "confidence": 1.0,
        "clarification_hint": None,
        forbidden: [],
    }
    with pytest.raises(ValidationError):
        SemanticIntentProposal.model_validate(payload, strict=True)


def test_semantic_context_contains_no_product_facts() -> None:
    context = SemanticContext(
        conversation_version=2,
        active_topic="suncare",
        visible_candidate_count=3,
        confirmed_profile_fields={"skin_type": "dry"},
    )
    assert "product" not in context.model_dump_json().casefold()
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/understanding/test_semantic_intent_contracts.py
```

Expected: collection error because `semantic_contracts.py` does not exist.

- [ ] **Step 3: Implement the contracts**

```python
from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from app.guide.understanding.contracts import (
    TopicCode,
    UnderstandingGoal,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


SemanticGoal = UnderstandingGoal


class SemanticReference(_StrictModel):
    kind: str = Field(pattern=r"^(candidate_ordinal|image_ordinal|current_topic)$")
    ordinal: int | None = Field(default=None, ge=1, le=4)


class SemanticIntentProposal(_StrictModel):
    schema_version: ClassVar[str] = "guide-semantic-intent-v1"
    goal: SemanticGoal
    topic: TopicCode | None
    concerns: tuple[str, ...]
    observations: tuple[str, ...]
    references: tuple[SemanticReference, ...]
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    clarification_hint: str | None = Field(default=None, max_length=160)


class SemanticContext(_StrictModel):
    conversation_version: int = Field(ge=0)
    active_topic: TopicCode | None
    visible_candidate_count: int = Field(ge=0, le=4)
    confirmed_profile_fields: dict[str, str]


```

Extend `ports.py`:

```python
class SemanticIntentPort(Protocol):
    def propose(
        self,
        message: str,
        context: SemanticContext,
    ) -> SemanticIntentProposal: ...
```

Add these shared types to `contracts.py` before `StructuredUnderstanding`:

```python
class UnderstandingGoal(str, Enum):
    RECOMMENDATION = "recommendation"
    COMPARISON = "comparison"
    SUITABILITY = "suitability"
    IMAGE_SIMILARITY = "image_similarity"
    KNOWLEDGE = "knowledge"
    ASSESSMENT = "assessment"
    FOLLOWUP = "followup"
    CLARIFICATION = "clarification"


class SignalTrace(_StrictContract):
    field: str
    exact_value: str | None
    semantic_value: str | None
    resolution: Literal[
        "agree",
        "exact_wins",
        "semantic_fills",
        "clarify",
        "semantic_unavailable",
    ]
```

Change the `StructuredUnderstanding` field to
`goal: UnderstandingGoal = UnderstandingGoal.RECOMMENDATION`, keep
`semantic_proposals: list[str]` as redacted audit summaries, and add
`signal_trace: list[SignalTrace]`. Update exact-only `understand_text()` to emit
`UnderstandingGoal.RECOMMENDATION`. This direction avoids a circular import:
`semantic_contracts` may import shared types from `contracts`, but `contracts`
must never import `semantic_contracts`.

- [ ] **Step 4: Run contract and public contract tests**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/understanding/test_semantic_intent_contracts.py \
  tests/guide/test_public_contracts.py \
  tests/guide/understanding/test_text_understanding.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/guide/understanding tests/guide/understanding/test_semantic_intent_contracts.py tests/guide/test_public_contracts.py
git commit -m "feat(intent): define semantic proposal contracts"
```

## Task 2: Add Environment-Only SiliconFlow Adapter

**Files:**
- Create: `app/guide_runtime/llm_config.py`
- Create: `app/guide/adapters/llm/intent_prompt.py`
- Create: `app/guide/adapters/llm/siliconflow_intent.py`
- Modify: `requirements-guide-runtime.txt`
- Test: `tests/guide/adapters/test_siliconflow_intent.py`
- Test: `tests/guide/runtime/test_llm_config.py`

- [ ] **Step 1: Write configuration and adapter RED tests**

```python
import httpx
import pytest

from app.guide.adapters.llm.siliconflow_intent import SiliconFlowIntentAdapter
from app.guide.understanding.semantic_contracts import SemanticContext


def test_adapter_requests_json_without_sending_product_facts() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read().decode()
        return httpx.Response(
            200,
            json={
                "choices": [{
                    "message": {
                        "content": (
                            '{"goal":"recommendation","topic":"sunscreen",'
                            '"concerns":[],"observations":[],"references":[],'
                            '"confidence":0.97,"clarification_hint":null}'
                        )
                    }
                }],
                "usage": {"prompt_tokens": 50, "completion_tokens": 30},
            },
        )

    adapter = SiliconFlowIntentAdapter(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        model="deepseek-ai/DeepSeek-V3.2",
        timeout_seconds=2.0,
        transport=httpx.MockTransport(handler),
    )
    result = adapter.propose(
        "我想买夏天涂的防止晒黑的东西",
        SemanticContext(
            conversation_version=0,
            active_topic=None,
            visible_candidate_count=0,
            confirmed_profile_fields={},
        ),
    )
    assert result.topic.value == "sunscreen"
    assert "product_facts" not in captured["body"]
    assert "test-key" not in captured["body"]


@pytest.mark.parametrize("status", (401, 429, 500))
def test_adapter_maps_provider_failures(status: int) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status, json={"error": "private"})
    )
    adapter = SiliconFlowIntentAdapter(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        model="deepseek-ai/DeepSeek-V3.2",
        timeout_seconds=2.0,
        transport=transport,
    )
    with pytest.raises(RuntimeError, match="semantic provider unavailable"):
        adapter.propose(
            "推荐防晒",
            SemanticContext(
                conversation_version=0,
                active_topic=None,
                visible_candidate_count=0,
                confirmed_profile_fields={},
            ),
        )
```

- [ ] **Step 2: Verify RED**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/adapters/test_siliconflow_intent.py \
  tests/guide/runtime/test_llm_config.py
```

Expected: collection errors for missing modules.

- [ ] **Step 3: Implement environment configuration**

```python
from dataclasses import dataclass
import os


@dataclass(frozen=True, slots=True)
class GuideLlmConfig:
    api_key: str | None
    base_url: str
    model: str
    timeout_seconds: float
    max_tokens: int

    @classmethod
    def from_environment(cls) -> "GuideLlmConfig":
        raw_key = os.environ.get("GUIDE_LLM_API_KEY")
        return cls(
            api_key=raw_key.strip() if raw_key and raw_key.strip() else None,
            base_url=os.environ.get(
                "GUIDE_LLM_BASE_URL",
                "https://api.siliconflow.cn/v1",
            ).rstrip("/"),
            model=os.environ.get(
                "GUIDE_LLM_MODEL",
                "deepseek-ai/DeepSeek-V4-Flash",
            ),
            timeout_seconds=float(
                os.environ.get("GUIDE_LLM_TIMEOUT_SECONDS", "8")
            ),
            max_tokens=int(os.environ.get("GUIDE_LLM_MAX_TOKENS", "256")),
        )
```

Validate timeout `0.5..30` and max tokens `64..512`; invalid environment must raise
`ValueError` without including the key.

- [ ] **Step 4: Implement the prompt and adapter**

Use a constant prompt version:

```python
INTENT_PROMPT_VERSION = "guide-intent-v1"
SYSTEM_PROMPT = """Return one JSON object matching guide-semantic-intent-v1.
Interpret goal, topic, concerns, observations and references only.
Never return product IDs, candidates, product facts, prices, scores, winner, SQL,
or storage mutations. Use null for an unknown topic. Do not answer the user."""
```

The adapter must:

- use `httpx.Client`;
- call `/chat/completions`;
- set `response_format={"type": "json_object"}`;
- set `temperature=0`;
- set `stream=False`;
- parse only `choices[0].message.content`;
- validate with `SemanticIntentProposal.model_validate_json(..., strict=True)`;
- log provider/model/trace ID/usage only;
- never log message, full response, profile, key or provider error body.

- [ ] **Step 5: Add runtime dependency and run tests**

Append exactly:

```text
httpx==0.27.2
```

Run:

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/adapters/test_siliconflow_intent.py \
  tests/guide/runtime/test_llm_config.py \
  tests/guide/runtime/test_import_boundary.py
```

Expected: PASS and no legacy imports.

- [ ] **Step 6: Commit**

```bash
git add app/guide/adapters/llm app/guide_runtime/llm_config.py requirements-guide-runtime.txt tests/guide/adapters tests/guide/runtime/test_llm_config.py
git commit -m "feat(intent): add constrained SiliconFlow adapter"
```

## Task 3: Implement The Single Signal Merger

**Files:**
- Create: `app/guide/intent/signal_merger.py`
- Modify: `app/guide/intent/task_planning.py`
- Test: `tests/guide/intent/test_signal_merger.py`
- Test: `tests/guide/intent/test_task_planning.py`

- [ ] **Step 1: Write RED cases for precedence and clarification**

```python
from app.guide.intent.signal_merger import merge_intent_signals
from app.guide.understanding.contracts import BudgetDraft, CategoryDraft, TopicCode
from app.guide.understanding.semantic_contracts import (
    SemanticGoal,
    SemanticIntentProposal,
)


def proposal(*, goal="recommendation", topic="fragrance", confidence=0.95):
    return SemanticIntentProposal(
        goal=SemanticGoal(goal),
        topic=TopicCode(topic) if topic else None,
        concerns=[],
        observations=[],
        references=[],
        confidence=confidence,
        clarification_hint=None,
    )


def test_semantic_topic_fills_missing_exact_topic() -> None:
    merged = merge_intent_signals(
        message="夏天涂的防止晒黑的东西",
        exact_constraints=[],
        exact_issues=[],
        semantic=proposal(topic="sunscreen"),
    )
    assert merged.topic is TopicCode.SUNSCREEN
    assert merged.signal_trace[0].resolution == "semantic_fills"


def test_exact_topic_conflict_clarifies_instead_of_model_override() -> None:
    merged = merge_intent_signals(
        message="推荐防晒",
        exact_constraints=[CategoryDraft(value=TopicCode.SUNSCREEN)],
        exact_issues=[],
        semantic=proposal(topic="fragrance"),
    )
    assert merged.topic is TopicCode.SUNSCREEN
    assert merged.uncertainties
    assert merged.signal_trace[0].resolution == "clarify"


def test_low_confidence_semantic_proposal_only_clarifies() -> None:
    merged = merge_intent_signals(
        message="给我来点那个",
        exact_constraints=[],
        exact_issues=[],
        semantic=proposal(topic=None, confidence=0.3),
    )
    assert merged.uncertainties
```

- [ ] **Step 2: Verify RED**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q tests/guide/intent/test_signal_merger.py
```

Expected: missing module failure.

- [ ] **Step 3: Implement merger rules**

`merge_intent_signals()` must:

1. preserve all exact `BudgetDraft`, `SkinDraft`, `ExclusionDraft` and
   `EfficacyDraft` values byte-for-byte;
2. use semantic topic only when exact topic is absent and append exactly one
   `CategoryDraft(value=semantic.topic)` to `exact_constraints`;
3. turn conflicting exact/model topics into `UnderstandingIssue`;
4. turn confidence `<0.70` into clarification;
5. map semantic observations into `observations`, never exact constraints;
6. keep one trace row per merged field;
7. accept no unvalidated dict.

The implementation must not import retrieval, decision, product or adapter modules.

- [ ] **Step 4: Extend task planning**

`plan_task()` continues to produce only `recommend` or `clarify` for the current
text recommendation flow. Semantic goals not yet owned by that flow must produce a
typed clarification rather than legacy fallback:

```python
if understanding.goal not in {
    SemanticGoal.RECOMMENDATION,
    SemanticGoal.FOLLOWUP,
}:
    return TaskPlan(
        mode="clarify",
        referenced_image_ids=[],
        constraints=constraints,
        required_evidence=[],
        clarification="我理解了你的目标，但当前这条文字流程还需要你确认具体商品或品类。",
    )
```

Knowledge/assessment routing is handled before this planner by the existing
consultation vertical.

- [ ] **Step 5: Run merger, planning and Round 9 regressions**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/intent/test_signal_merger.py \
  tests/guide/intent/test_task_planning.py \
  tests/guide/understanding/test_category_profile_parsing.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/guide/intent tests/guide/intent tests/guide/understanding/test_category_profile_parsing.py
git commit -m "feat(intent): merge exact model and context signals"
```

## Task 4: Add Parallel Understanding And Validated Cache

**Files:**
- Create: `app/guide/understanding/parallel_understanding.py`
- Create: `app/guide/adapters/llm/intent_cache.py`
- Test: `tests/guide/understanding/test_parallel_understanding.py`
- Test: `tests/guide/adapters/test_intent_cache.py`

- [ ] **Step 1: Write concurrency and failure RED tests**

```python
from app.guide.understanding.semantic_contracts import (
    SemanticContext,
    SemanticIntentProposal,
)
from app.guide.understanding.parallel_understanding import ParallelUnderstanding


class FailingSemanticPort:
    def propose(
        self,
        message: str,
        context: SemanticContext,
    ) -> SemanticIntentProposal:
        del message, context
        raise RuntimeError("semantic provider unavailable")


def empty_context() -> SemanticContext:
    return SemanticContext(
        conversation_version=0,
        active_topic=None,
        visible_candidate_count=0,
        confirmed_profile_fields={},
    )


def test_exact_lane_survives_provider_failure() -> None:
    semantic = FailingSemanticPort()
    result = ParallelUnderstanding(semantic=semantic).understand(
        "500元内推荐防晒",
        context=empty_context(),
    )
    assert result.topic.value == "sunscreen"
    assert any(
        item.resolution == "semantic_unavailable"
        for item in result.signal_trace
    )


def test_complex_request_clarifies_when_provider_fails() -> None:
    result = ParallelUnderstanding(
        semantic=FailingSemanticPort()
    ).understand("给我来点那个适合夏天的", context=empty_context())
    assert result.uncertainties
```

Add this barrier fake to prove the semantic future starts before the exact lane
completes:

```python
from threading import Barrier, Event


class BarrierSemanticPort:
    def __init__(self, proposal: SemanticIntentProposal) -> None:
        self.proposal = proposal
        self.started = Event()
        self.release = Barrier(2)

    def propose(
        self,
        message: str,
        context: SemanticContext,
    ) -> SemanticIntentProposal:
        del message, context
        self.started.set()
        self.release.wait(timeout=2)
        return self.proposal
```

- [ ] **Step 2: Verify RED**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/understanding/test_parallel_understanding.py \
  tests/guide/adapters/test_intent_cache.py
```

Expected: missing module failures.

- [ ] **Step 3: Implement bounded parallel coordinator**

Use one semantic future:

```python
with ThreadPoolExecutor(max_workers=1, thread_name_prefix="guide-intent") as pool:
    semantic_future = pool.submit(self._semantic.propose, text, context)
    exact_constraints, exact_issues = parse_exact_constraints(text)
    try:
        semantic = semantic_future.result()
    except Exception:
        semantic = None
return merge_intent_signals(
    message=text,
    exact_constraints=exact_constraints,
    exact_issues=exact_issues,
    semantic=semantic,
)
```

The coordinator must not create a future for typed protocol operations that the
caller marks `semantic_required=False`.

- [ ] **Step 4: Implement validated SQLite cache**

Cache table:

```sql
CREATE TABLE IF NOT EXISTS intent_cache (
    fingerprint TEXT PRIMARY KEY,
    entry_json TEXT NOT NULL,
    created_at_epoch INTEGER NOT NULL,
    last_access_epoch INTEGER NOT NULL
)
```

Rules:

- only `LLMCacheEntry.from_validated_result()` results are stored;
- max 512 entries;
- TTL 24 hours using monotonic process time for in-process expiry and epoch only
  for persisted age;
- LRU eviction by `last_access_epoch`;
- key fingerprint includes provider, model, prompt/schema versions, context hash
  and generation parameters;
- key and message content never appear in logs.

- [ ] **Step 5: Run tests**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/understanding/test_parallel_understanding.py \
  tests/guide/adapters/test_intent_cache.py \
  tests/guide/adapters/test_llm_cache_contract.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/guide/understanding/parallel_understanding.py app/guide/adapters/llm/intent_cache.py tests/guide/understanding/test_parallel_understanding.py tests/guide/adapters/test_intent_cache.py
git commit -m "feat(intent): run parallel understanding with validated cache"
```

## Task 5: Inject Understanding Without Provider Leakage

**Files:**
- Modify: `app/guide/understanding/ports.py`
- Modify: `app/guide/application/text_recommendation_flow.py`
- Modify: `app/guide_runtime/composition.py`
- Test: `tests/guide/application/test_text_recommendation_flow.py`
- Test: `tests/guide/runtime/test_composition.py`

- [ ] **Step 1: Write injection RED tests**

```python
from pathlib import Path

from app.guide.understanding.contracts import (
    CategoryDraft,
    StructuredUnderstanding,
    TopicCode,
)
from app.guide.understanding.semantic_contracts import (
    SemanticContext,
    SemanticGoal,
)


class RecordingUnderstandingPort:
    def __init__(self, result: StructuredUnderstanding) -> None:
        self.result = result
        self.calls = 0

    def understand(
        self,
        message: str,
        *,
        context: SemanticContext,
        semantic_required: bool = True,
    ) -> StructuredUnderstanding:
        del message, context, semantic_required
        self.calls += 1
        return self.result.model_copy(deep=True)


def test_text_flow_consumes_injected_understanding_once(
    real_reader,
    real_product_assets,
    conversation_state,
) -> None:
    understanding = RecordingUnderstandingPort(
        result=StructuredUnderstanding(
            goal=SemanticGoal.RECOMMENDATION,
            topic=TopicCode.FRAGRANCE,
            observations=[],
            exact_constraints=[
                CategoryDraft(value=TopicCode.FRAGRANCE)
            ],
            semantic_proposals=[],
            signal_trace=[],
            image_references=[],
            uncertainties=[],
            confidence=1.0,
        )
    )
    orchestrator = compose_text_recommendation_orchestrator(
        real_reader,
        product_assets=real_product_assets,
        conversation_state=conversation_state,
        understanding=understanding,
    )
    events = list(
        orchestrator.stream(_turn("帮我买点闻起来清爽的"))
    )
    assert understanding.calls == 1
    assert next(
        event.data.category_profile.value
        for event in events
        if event.event == "intent"
    ) == "fragrance"


def test_application_layer_does_not_import_siliconflow_adapter() -> None:
    source = Path(
        "app/guide/application/text_recommendation_flow.py"
    ).read_text()
    assert "siliconflow" not in source.casefold()
    assert "httpx" not in source.casefold()
```

- [ ] **Step 2: Verify RED**

Run:

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/runtime/test_composition.py
```

Expected: the recording port assertion fails because the flow calls
`understand_text()` directly.

- [ ] **Step 3: Add the understanding protocol**

```python
class TextUnderstandingPort(Protocol):
    def understand(
        self,
        message: str,
        *,
        context: SemanticContext,
        semantic_required: bool = True,
    ) -> StructuredUnderstanding: ...
```

Inject it into `TextRecommendationOrchestrator.__init__`. Build `SemanticContext`
from the loaded snapshot without product facts:

```python
def _semantic_context(
    turn: UserTurn,
    snapshot: ConversationSnapshot | None,
) -> SemanticContext:
    query = snapshot.query_context if snapshot is not None else None
    confirmed: dict[str, str] = {}
    if query is not None and query.skin is not None:
        confirmed["skin_type"] = query.skin
    return SemanticContext(
        conversation_version=turn.conversation_version,
        active_topic=(
            TopicCode(query.category)
            if query is not None
            else None
        ),
        visible_candidate_count=(
            len(snapshot.candidates)
            if snapshot is not None
            else 0
        ),
        confirmed_profile_fields=confirmed,
    )
```

- [ ] **Step 4: Compose exact-only or SiliconFlow implementation**

In `composition.py`:

- no key: compose exact-only understanding;
- key present: compose SiliconFlow adapter + cache + `ParallelUnderstanding`;
- tests inject fake semantic port;
- never import old LLM service.

- [ ] **Step 5: Run focused and boundary tests**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/runtime/test_composition.py \
  tests/guide/test_architecture_boundaries.py \
  tests/guide/runtime/test_import_boundary.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/guide/understanding/ports.py app/guide/application/text_recommendation_flow.py app/guide_runtime/composition.py tests/guide/application/test_text_recommendation_flow.py tests/guide/runtime/test_composition.py
git commit -m "feat(application): inject parallel understanding"
```

## Task 6: Build The Frozen Real-Model A/B Gate

**Files:**
- Create: `tests/fixtures/guide/intent/semantic_intent_ab_v1.jsonl`
- Create: `tools/guide_gates/intent_model_ab.py`
- Create: `tests/guide/tools/test_intent_model_ab.py`
- Create during execution: `docs/audits/guide-closure/model_selection.md`

- [ ] **Step 1: Create the frozen case schema and seed cases**

Each JSONL row:

```json
{"case_id":"positive-fragrance-adverb","message":"不考虑防晒并非常想买香水","context":{"conversation_version":0,"active_topic":null,"visible_candidate_count":0,"confirmed_profile_fields":{}},"expected":{"goal":"recommendation","topic":"fragrance","must_clarify":false},"critical":true}
```

Include at least:

- all five confirmed Round 9 counterexamples;
- eight semantic goals;
- category paraphrases without literal category names;
- candidate/image ordinals;
- assessment observations;
- contradictory requests;
- prompt-injection attempts;
- out-of-scope requests;
- low-information requests.

The committed dataset must contain at least 120 deterministic cases. Do not
generate expected labels with an LLM.

- [ ] **Step 2: Write runner RED tests**

```python
from pathlib import Path

from app.guide.understanding.semantic_contracts import (
    SemanticGoal,
    SemanticIntentProposal,
)
from app.guide.understanding.contracts import TopicCode
from tools.guide_gates.intent_model_ab import load_cases, run_ab


def valid_recommendation_proposal() -> SemanticIntentProposal:
    return SemanticIntentProposal(
        goal=SemanticGoal.RECOMMENDATION,
        topic=TopicCode.SUNSCREEN,
        concerns=[],
        observations=[],
        references=[],
        confidence=0.99,
        clarification_hint=None,
    )


class StaticIntentAdapter:
    def __init__(
        self,
        *,
        proposal: SemanticIntentProposal,
        api_key_marker: str,
    ) -> None:
        self.proposal = proposal
        self.api_key_marker = api_key_marker

    def propose(self, message, context):
        del message, context
        return self.proposal.model_copy(deep=True)


def test_runner_never_persists_api_key_or_full_headers(tmp_path) -> None:
    cases = load_cases(
        Path(
            "tests/fixtures/guide/intent/"
            "semantic_intent_ab_v1.jsonl"
        )
    )
    report = run_ab(
        cases=cases,
        adapters={
            "model-a": StaticIntentAdapter(
                proposal=valid_recommendation_proposal(),
                api_key_marker="test-secret-key",
            )
        },
        output_dir=tmp_path,
    )
    blob = "\n".join(path.read_text() for path in tmp_path.iterdir())
    assert "test-secret-key" not in blob
    assert report.case_count >= 120
```

- [ ] **Step 3: Implement the runner**

The runner writes:

- normalized result JSONL;
- summary JSON;
- SHA256SUMS;
- per-model counts for schema validity, goal/topic/reference accuracy,
  critical failures, latency and usage;
- no raw authorization header;
- no full profile or product facts.

Exit codes:

```text
0 = at least one model passes all hard gates
2 = configuration/key unavailable
3 = no model passes hard gates
```

- [ ] **Step 4: Run offline runner tests**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q tests/guide/tools/test_intent_model_ab.py
```

Expected: PASS.

- [ ] **Step 5: Run real A/B with the local environment**

Precondition: a fresh, non-disclosed key exists in `GUIDE_LLM_API_KEY`.

Run:

```bash
PYTHONPATH=. /private/tmp/xiaoro-guide-runtime-venv/bin/python \
  tools/guide_gates/intent_model_ab.py \
  --cases tests/fixtures/guide/intent/semantic_intent_ab_v1.jsonl \
  --model deepseek-ai/DeepSeek-V4-Flash \
  --model deepseek-ai/DeepSeek-V3.2 \
  --output-dir /private/tmp/xiaoro-guide-intent-ab
```

Hard gates:

- critical hard-constraint override count = 0;
- forbidden-field acceptance count = 0;
- invalid output reaching TaskPlan count = 0;
- fallback-to-legacy count = 0;
- every failed case becomes clarification or typed provider failure.

If both pass, choose V4-Flash. If Flash fails and V3.2 passes, choose V3.2. If
both fail, do not cut over; add generalizable prompt/schema RED cases, not
phrase-specific production regexes.

- [ ] **Step 6: Record selection and commit**

Record model IDs, prompt/schema versions, case manifest SHA, result SHA,
latency, usage and actual billed cost in `model_selection.md`.

```bash
git add tests/fixtures/guide/intent tools/guide_gates/intent_model_ab.py tests/guide/tools/test_intent_model_ab.py docs/audits/guide-closure/model_selection.md
git commit -m "test(intent): gate real semantic model selection"
```

## Task 7: Make Normal Text State Cross-Worker

**Files:**
- Modify: `app/guide_runtime/composition.py`
- Test: `tests/guide/runtime/test_composition.py`
- Test: `tests/guide/application/test_cross_worker_text_state.py`

- [ ] **Step 1: Write two-orchestrator RED**

```python
from app.guide.application.contracts import UserTurn
from app.guide.understanding.contracts import TopicCode
from app.guide.understanding.semantic_contracts import (
    SemanticContext,
    SemanticGoal,
    SemanticIntentProposal,
)
from app.guide_runtime.composition import build_runtime_orchestrator


class StaticSemanticPort:
    def propose(
        self,
        message: str,
        context: SemanticContext,
    ) -> SemanticIntentProposal:
        del message, context
        return SemanticIntentProposal(
            goal=SemanticGoal.RECOMMENDATION,
            topic=TopicCode.SUNSCREEN,
            concerns=[],
            observations=[],
            references=[],
            confidence=0.99,
            clarification_hint=None,
        )


def _turn(message: str, *, version: int) -> UserTurn:
    return UserTurn(
        session_id="cross-worker-session",
        message=message,
        image_bundle_id=None,
        conversation_version=version,
    )


def test_followup_survives_different_orchestrator_instances(tmp_path) -> None:
    first = build_runtime_orchestrator(
        state_dir=tmp_path,
        semantic_intent=StaticSemanticPort(),
    )
    second = build_runtime_orchestrator(
        state_dir=tmp_path,
        semantic_intent=StaticSemanticPort(),
    )
    initial = list(first.stream(_turn("推荐防晒", version=0)))
    assert initial[-1].event == "end"
    assert initial[-1].data.conversation_version == 1
    followup = list(second.stream(_turn("第二款呢", version=1)))
    assert next(
        event.data.mode
        for event in followup
        if event.event == "intent"
    ) == "followup"
    assert followup[-1].event == "end"
    assert followup[-1].data.conversation_version == 2
```

- [ ] **Step 2: Verify RED**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/application/test_cross_worker_text_state.py
```

Expected: second orchestrator clarifies that no recent candidates exist.

- [ ] **Step 3: Use existing SQLite CAS**

Add:

```python
def conversation_database_path() -> Path:
    return guide_state_directory() / "conversations.sqlite3"
```

Change `build_runtime_orchestrator()` to accept `state_dir` and construct:

```python
state_root = Path(state_dir or guide_state_directory()).expanduser()
conversation_state = SqliteConversationState(
    state_root / "conversations.sqlite3",
    trusted_state_root=state_root,
)
```

Pass the same state root to consultation/profile/image composition. Do not add
another state authority.

- [ ] **Step 4: Run state and delivery tests**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/application/test_cross_worker_text_state.py \
  tests/guide/adapters/state/test_sqlite_conversation_state.py \
  tests/guide/feedback/test_feedback_delivery.py \
  tests/guide/runtime/test_sse.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/guide_runtime/composition.py tests/guide/application/test_cross_worker_text_state.py tests/guide/runtime/test_composition.py
git commit -m "fix(runtime): persist text state across workers"
```

## Task 8: Switch The Default Public Runtime To Guide Only

**Files:**
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`
- Modify: `docker-compose.prod.yml`
- Modify: `start.sh`
- Modify: `README.md`
- Modify: `DEPLOY.md`
- Modify: `app/guide_runtime/sse.py`
- Modify: `app/guide_runtime/app.py`
- Test: `tests/guide/runtime/test_guide_only_entrypoint.py`
- Test: `tests/guide/runtime/test_runtime_http.py`

- [ ] **Step 1: Write default-entry RED**

```python
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[3]


def test_all_default_launchers_use_guide_runtime() -> None:
    paths = [
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.prod.yml",
        "start.sh",
        "README.md",
        "DEPLOY.md",
    ]
    for path in paths:
        text = (ROOT / path).read_text()
        assert "app.guide_runtime.app:app" in text
        assert "app.main:app" not in text


def test_default_runtime_imports_no_legacy_modules() -> None:
    script = """
import sys
before = set(sys.modules)
import app.guide_runtime.app
loaded = set(sys.modules) - before
forbidden = ("app.services", "app.database", "pymilvus", "redis")
unexpected = sorted(
    name
    for name in loaded
    if any(name == item or name.startswith(item + ".") for item in forbidden)
)
if unexpected:
    raise RuntimeError(unexpected)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
```

The subprocess must fail if any loaded module starts with `app.services` or
`app.database`.

- [ ] **Step 2: Verify RED**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q tests/guide/runtime/test_guide_only_entrypoint.py
```

Expected: launch target assertions fail.

- [ ] **Step 3: Update launch targets**

Replace every default launch target with:

```text
app.guide_runtime.app:app
```

Keep worker counts unchanged. Do not push or deploy.

- [ ] **Step 4: Remove public fallback semantics**

`app.guide_runtime` already owns the clean endpoints. Add a typed unsupported
flow in `iter_http_events()`:

```python
def iter_unsupported_events(
    *,
    session_id: str,
    conversation_version: int,
    clarification_question: str,
):
    yield "start", {"session_id": session_id}
    yield "intent", {"intent": "clarify", "guide": True}
    yield "message", {
        "content": clarification_question,
        "done": False,
        "clarify": True,
    }
    yield "end", {
        "conversation_version": conversation_version,
    }
```

After two unresolved turns, return a scope notice. Never import or call
`app.api.v1.chat`, `app.services.agent`, or `app.services.v2.agent`.

- [ ] **Step 5: Run runtime and browser gates**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q tests/guide/runtime tests/guide/application
```

Then run the existing normal and adversarial browser gate scripts against:

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/uvicorn \
  app.guide_runtime.app:app --host 127.0.0.1 --port 8765
```

Expected: zero page, SSE, XSS, cross-session, late-event and unexpected 5xx
errors.

- [ ] **Step 6: Commit**

```bash
git add Dockerfile docker-compose.yml docker-compose.prod.yml start.sh README.md DEPLOY.md app/guide_runtime tests/guide/runtime
git commit -m "feat(runtime): make Guide the only public entry"
```

## Task 9: Prove Unreachability And Delete The Legacy Chat Chain

**Files:**
- Create: `tools/guide_gates/legacy_dependency_inventory.py`
- Create: `tests/guide/runtime/test_legacy_chat_removed.py`
- Delete after proof:
  - `app/services/v2/`
  - `app/services/agent.py`
  - `app/services/intent.py`
  - legacy-only tests listed by the inventory
  - legacy-only scripts listed by the inventory
- Modify after proof:
  - `app/main.py`
  - `app/services/__init__.py`
  - `app/services/conversation.py`
  - `app/tasks/product/tasks.py`
  - `app/tasks/worker.py`

- [ ] **Step 1: Write an inventory tool**

The tool parses Python AST for:

```text
app.services.agent
app.services.intent
app.services.v2
```

It outputs sorted JSON with `importers`, `runtime_importers`, `test_importers`
and `script_importers`. It must detect `import`, `from`, literal
`importlib.import_module()` and literal `__import__()`.

- [ ] **Step 2: Write removal RED**

```python
from pathlib import Path


def test_legacy_chat_modules_are_absent() -> None:
    root = Path(__file__).resolve().parents[3]
    assert not (root / "app/services/v2").exists()
    assert not (root / "app/services/agent.py").exists()
    assert not (root / "app/services/intent.py").exists()
```

- [ ] **Step 3: Generate and review the dependency report**

Run:

```bash
PYTHONPATH=. /private/tmp/xiaoro-guide-runtime-venv/bin/python \
  tools/guide_gates/legacy_dependency_inventory.py \
  --root . \
  --output /private/tmp/xiaoro-legacy-dependency-inventory.json
```

Do not delete files while `runtime_importers` is non-empty.

- [ ] **Step 4: Remove or rewrite remaining importers at their owning boundary**

- `app/services/conversation.py`: replace the `IntentResult` type dependency with
  a local protocol or Guide contract only if the module remains needed.
- background tasks: either call a Guide application port or delete the task if
  no default runtime/worker registration reaches it.
- tests/scripts: migrate behavior assertions to `tests/guide/**` or delete them
  when they only exercise removed legacy internals.
- replace `app/main.py` with a compatibility export that has no old imports:

```python
from app.guide_runtime.app import app

__all__ = ["app"]
```

Do not copy legacy functions into Guide.

- [ ] **Step 5: Delete proven-unreachable legacy modules**

Use `git rm`, not a `legacy/` move:

```bash
git rm -r app/services/v2
git rm app/services/agent.py app/services/intent.py
```

Delete only inventory-confirmed legacy-only tests and scripts in the same
logical commits.

- [ ] **Step 6: Run removal and import gates**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/runtime/test_legacy_chat_removed.py \
  tests/guide/runtime/test_import_boundary.py \
  tests/guide/test_architecture_boundaries.py

PYTHONPATH=. /private/tmp/xiaoro-guide-runtime-venv/bin/python \
  tools/guide_gates/legacy_dependency_inventory.py \
  --root . \
  --assert-empty-runtime
```

Expected: PASS and zero runtime importers.

- [ ] **Step 7: Commit in deletion-sized batches**

```bash
git add -A
git commit -m "refactor(guide): remove unreachable legacy chat chain"
```

## Task 10: Final Mechanical Closure Without A Second Full Audit

**Files:**
- Modify: `docs/audits/guide-closure/progress.md`
- Modify: `docs/audits/guide-closure/audit_ledger.csv`
- Create: `docs/audits/guide-closure/final_handoff.md`
- Test: all Guide/runtime suites

- [ ] **Step 1: Run focused semantic and state suites**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q \
  tests/guide/understanding \
  tests/guide/intent \
  tests/guide/adapters/test_siliconflow_intent.py \
  tests/guide/adapters/test_intent_cache.py \
  tests/guide/application/test_cross_worker_text_state.py
```

Expected: PASS.

- [ ] **Step 2: Run full Guide/runtime suites**

```bash
/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q

/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -c pytest-guide.ini -q tests/guide/runtime

/private/tmp/xiaoro-guide-runtime-venv/bin/python -m pytest \
  -q tests
```

Expected: PASS with no new warning class.

- [ ] **Step 3: Run static and protection gates**

```bash
python3 -m compileall -q app/guide app/guide_runtime tools/guide_gates
python3 -m app.guide.check_boundaries
git diff --check
shasum -a 256 app/guide/decision/deterministic_ranking.py
git diff --exit-code 2199164 -- data/canonical app/guide/decision/deterministic_ranking.py
```

Expected: ranking SHA
`4737c18964f2be3502f036a87dd50e06965a214a87aa967c586d08e7c741f59f`
and zero protected diff.

- [ ] **Step 4: Run browser and model gates**

Run:

- normal browser matrix;
- adversarial/XSS matrix;
- session switch/late-event matrix;
- cross-worker text followup;
- frozen real-model A/B replay.

Expected: all pass; zero fallback-to-legacy and zero hard-constraint override.

- [ ] **Step 5: Perform targeted read-only verification**

Independent verifiers inspect only changed files and confirmed opening-audit
findings. They must not invoke another formal full-file audit or create a new
audit key.

Record:

```text
formal_full_file_audit_invocations=1
repeat_full_file_audit_invocations=0
targeted_verification=PASS
```

- [ ] **Step 6: Write final handoff**

`final_handoff.md` must include:

- start/end SHA;
- one audit key and invocation count;
- model selected and A/B evidence hash;
- exact/model/merge failure counts;
- state database path contract;
- legacy deletion inventory;
- focused/full/runtime/browser results;
- protected hashes;
- data recovery status;
- no push/deploy/traffic switch;
- unresolved blockers, or `none`.

- [ ] **Step 7: Commit closure**

```bash
git add docs/audits/guide-closure
git commit -m "docs(guide): close intent and cutover program"
```
