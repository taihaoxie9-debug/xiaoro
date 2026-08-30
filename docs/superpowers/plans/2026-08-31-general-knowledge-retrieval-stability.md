# General Knowledge Retrieval Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the reviewed 22-topic general-knowledge corpus achieve deterministic `Recall@3 = 100%`, zero wrong-topic citations, safe multi-entity coverage, and two consecutive real DeepSeek/browser acceptance runs.

**Architecture:** Extend the existing single TurnMeaning and TaskPlan path with typed knowledge-relation hints, compile raw-text-authoritative concepts and entities into `KnowledgeQuerySpec`, and keep `GeneralKnowledgeRetriever` as the only knowledge retriever. Publish reviewed concept/entity/relation metadata with the v2 content-addressed asset, then apply deterministic eligibility, reranking, evidence assembly, and coverage checks before the existing code-owned answer renderer.

**Tech Stack:** Python 3.11, Pydantic v2, FastAPI, pytest, DeepSeek V4 Pro, SSE, vanilla JavaScript, Playwright

---

## Execution Policy

Implement only in:

```text
/Users/bytedance/Desktop/xiaoro-fresh/.tmp-task11-r5-seal-worktree
```

Do not modify:

```text
/Users/bytedance/Desktop/xiaoro-shopping-master
```

Execution is autonomous for ordinary failures. On a failed unit test,
deterministic recall case, real backend probe, browser contract, or screenshot:

1. preserve the failing evidence;
2. identify the earliest shared owner;
3. add or tighten a class-level regression;
4. repair that owner;
5. rerun the focused suite;
6. rerun the complete deterministic matrix;
7. restart the two-run real acceptance sequence.

Do not stop for ordinary failures and do not repeatedly sample the provider to
obtain a lucky green result. Stop only for missing credentials, a persistent
external outage, a destructive operation requiring approval, or a repair that
would leave this approved scope.

Before each commit, inspect `git status --short` and stage only files named in
that task. The worktree already contains unrelated untracked audit artifacts;
do not stage, delete, or rewrite them.

## Scope And File Ownership

**Semantic relation contract**

- Create:
  `app/guide/understanding/knowledge_relation_contracts.py`
- Modify:
  `app/guide/understanding/turn_meaning_contracts.py`
- Modify:
  `app/guide/adapters/llm/turn_meaning_prompt.py`
- Modify:
  `app/guide/intent/executable_intent_compiler.py`
- Modify:
  `app/guide/intent/signal_merger.py`
- Modify:
  `app/guide/understanding/contracts.py`
- Modify:
  `app/guide/intent/contracts.py`
- Modify:
  `app/guide/intent/task_planning.py`

**Knowledge query and ontology**

- Create:
  `app/guide/retrieval/general_knowledge_ontology.py`
- Create:
  `app/guide/retrieval/general_knowledge_query.py`
- Modify:
  `app/guide/retrieval/general_knowledge_contracts.py`

**Reviewed retrieval metadata and build**

- Create:
  `docs/audits/general-knowledge/retrieval_profiles_v1.jsonl`
- Modify:
  `tools/guide_data/build_general_knowledge.py`
- Modify:
  `tools/guide_data/audit_general_knowledge.py`
- Modify:
  `app/guide/retrieval/general_knowledge_assets.py`
- Generate:
  `data/guide_general_knowledge/general_knowledge_v2_manifest.json`
- Generate:
  `data/guide_general_knowledge/general_knowledge_v2.<sha256>.jsonl`
- Modify:
  `app/guide_runtime/composition.py`

**Retrieval and answer**

- Modify:
  `app/guide/retrieval/general_knowledge_retrieval.py`
- Modify:
  `app/guide/application/general_knowledge_answer.py`
- Modify:
  `app/guide/application/text_recommendation_flow.py`
- Modify:
  `app/guide/presentation/sse_events.py`

**Frontend**

- Modify:
  `app/static/chat.html`

**Deterministic and real acceptance**

- Create:
  `tests/fixtures/guide/general_knowledge/general_knowledge_recall_v1.jsonl`
- Create:
  `tools/guide_gates/run_general_knowledge_recall_gate.py`
- Modify:
  `tools/guide_gates/run_mainline_contract_browser_audit.py`
- Generate:
  `docs/audits/general-knowledge/retrieval-stability/`

**Tests**

- Modify:
  `tests/guide/understanding/test_turn_meaning_contracts.py`
- Modify:
  `tests/guide/adapters/test_turn_meaning_prompt.py`
- Modify:
  `tests/guide/adapters/test_deepseek_turn_meaning.py`
- Modify:
  `tests/guide/intent/test_executable_intent_compiler.py`
- Modify:
  `tests/guide/intent/test_signal_merger.py`
- Modify:
  `tests/guide/intent/test_task_planning.py`
- Create:
  `tests/guide/retrieval/test_general_knowledge_ontology.py`
- Create:
  `tests/guide/retrieval/test_general_knowledge_query.py`
- Modify:
  `tests/guide/retrieval/test_general_knowledge_contracts.py`
- Modify:
  `tests/guide/retrieval/test_general_knowledge_assets.py`
- Modify:
  `tests/guide/retrieval/test_general_knowledge_retrieval.py`
- Modify:
  `tests/guide/tools/test_build_general_knowledge.py`
- Modify:
  `tests/guide/tools/test_audit_general_knowledge.py`
- Create:
  `tests/guide/tools/test_run_general_knowledge_recall_gate.py`
- Modify:
  `tests/guide/application/test_general_knowledge_answer.py`
- Modify:
  `tests/guide/application/test_text_recommendation_flow.py`
- Modify:
  `tests/guide/runtime/test_runtime_http.py`
- Modify:
  `tests/guide/runtime/test_frontend_scope.py`
- Modify:
  `tests/guide/runtime/test_frontend_presentation_stream.py`
- Modify:
  `tests/guide/tools/test_run_mainline_contract_browser_audit.py`

No production question sentence, test case ID, source block ID, or knowledge ID
may be used as a branch condition.

### Task 1: Add Typed Knowledge Relation Hints To The Single Semantic Path

**Files:**
- Create:
  `app/guide/understanding/knowledge_relation_contracts.py`
- Modify:
  `app/guide/understanding/turn_meaning_contracts.py`
- Modify:
  `app/guide/understanding/contracts.py`
- Modify:
  `app/guide/intent/contracts.py`
- Modify:
  `app/guide/intent/executable_intent_compiler.py`
- Modify:
  `app/guide/intent/signal_merger.py`
- Modify:
  `app/guide/intent/task_planning.py`
- Test:
  `tests/guide/understanding/test_turn_meaning_contracts.py`
- Test:
  `tests/guide/intent/test_executable_intent_compiler.py`
- Test:
  `tests/guide/intent/test_signal_merger.py`
- Test:
  `tests/guide/intent/test_task_planning.py`

- [x] **Step 1: Write failing contract propagation tests**

Add tests proving that a knowledge relation survives the complete typed path:

```python
meaning = TurnMeaning(
    operation_hint="knowledge",
    topic_hint="serum",
    continuity_hint="new_task",
    subject_scope_hint="self",
    reference_mentions=(),
    product_mentions=(),
    budget_candidates=(),
    observation_candidates=(),
    preference_candidates=(),
    relative_candidates=(),
    knowledge_relation_hints=("difference", "compatibility"),
    question_meaning="比较烟酰胺和视黄醇并询问能否叠加",
    safety_language="ordinary",
)

understanding = compile_turn_meaning(
    message="烟酰胺和A醇有什么区别，能一起用吗？",
    meaning=meaning,
    context=_empty_context(),
)
task = plan_task(understanding, message="烟酰胺和A醇有什么区别，能一起用吗？")

assert understanding.knowledge_relation_hints == (
    "difference",
    "compatibility",
)
assert task.knowledge_relation_hints == (
    "difference",
    "compatibility",
)
```

Also assert:

- non-knowledge modes may carry only an empty tuple;
- values are ordered unique;
- unknown values are rejected;
- list input is frozen to a tuple;
- existing constructors that omit the field remain valid with `()`.

- [x] **Step 2: Run the focused tests and verify RED**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/understanding/test_turn_meaning_contracts.py \
  tests/guide/intent/test_executable_intent_compiler.py \
  tests/guide/intent/test_signal_merger.py \
  tests/guide/intent/test_task_planning.py \
  -k "knowledge_relation"
```

Expected: collection or assertions fail because the typed relation field does
not exist.

- [x] **Step 3: Add the shared literal and strict fields**

Create the shared type:

```python
from typing import Literal

KnowledgeRelationIntent = Literal[
    "overview",
    "mechanism",
    "difference",
    "compatibility",
    "usage",
    "selection",
    "identification",
    "safety",
]

__all__ = ["KnowledgeRelationIntent"]
```

Add this field with tuple freezing and ordered-unique validation to
`TurnMeaning`, `StructuredUnderstanding`, and `TaskPlan`:

```python
knowledge_relation_hints: tuple[KnowledgeRelationIntent, ...] = Field(
    default_factory=tuple,
    max_length=8,
)
```

The validator must reject duplicates instead of silently changing model
output. Propagate the exact tuple through `executable_intent_compiler`,
`signal_merger`, and `_plan_semantic_task`. Clear it for non-knowledge task
modes.

- [x] **Step 4: Run focused GREEN tests**

Run the command from Step 2.

Expected: all selected tests pass.

- [x] **Step 5: Commit**

```bash
git add \
  app/guide/understanding/knowledge_relation_contracts.py \
  app/guide/understanding/turn_meaning_contracts.py \
  app/guide/understanding/contracts.py \
  app/guide/intent/contracts.py \
  app/guide/intent/executable_intent_compiler.py \
  app/guide/intent/signal_merger.py \
  app/guide/intent/task_planning.py \
  tests/guide/understanding/test_turn_meaning_contracts.py \
  tests/guide/intent/test_executable_intent_compiler.py \
  tests/guide/intent/test_signal_merger.py \
  tests/guide/intent/test_task_planning.py
git commit -m "feat(guide): type knowledge relation intent"
```

### Task 2: Teach TurnMeaning To Translate Knowledge Relations And Routing Boundaries

**Files:**
- Modify:
  `app/guide/adapters/llm/turn_meaning_prompt.py`
- Modify:
  `app/guide/adapters/llm/deepseek_turn_meaning.py`
- Test:
  `tests/guide/adapters/test_turn_meaning_prompt.py`
- Test:
  `tests/guide/adapters/test_deepseek_turn_meaning.py`

- [x] **Step 1: Write failing prompt and strict-schema tests**

Assert that:

```python
assert "knowledge_relation_hints" in system_prompt
assert (
    "overview|mechanism|difference|compatibility|usage|selection|"
    "identification|safety"
) in system_prompt
assert "category guidance" in system_prompt
assert "current symptom or reaction" in system_prompt
```

Validate the strict tool schema:

```python
schema = _strict_turn_meaning_schema()
field = schema["properties"]["knowledge_relation_hints"]
assert field["type"] == "array"
assert set(field["items"]["enum"]) == {
    "overview",
    "mechanism",
    "difference",
    "compatibility",
    "usage",
    "selection",
    "identification",
    "safety",
}
```

Add provider-response tests for multiple relations and an empty relation list.

- [x] **Step 2: Run the adapter tests and verify RED**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/adapters/test_turn_meaning_prompt.py \
  tests/guide/adapters/test_deepseek_turn_meaning.py \
  -k "knowledge_relation or category_guidance"
```

Expected: the prompt and strict schema lack the new field.

- [x] **Step 3: Update the one semantic prompt**

Bump:

```python
TURN_MEANING_PROMPT_VERSION = "guide-turn-meaning-prompt-v38"
```

Add `knowledge_relation_hints` to the exact-key list and instruct:

```text
knowledge_relation_hints is always a JSON array.
Use only overview, mechanism, difference, compatibility, usage, selection,
identification, safety.
Emit all independently requested relations in user order.
A category guidance question asking how to choose, use, or understand a
category is knowledge unless the user asks to recommend, find, or show
specific products.
A current symptom or reaction asking what to do is assessment, even when
ingredient words are present.
Do not emit entity IDs, knowledge IDs, source paths, citations, or answers.
```

The DeepSeek strict-schema builder should consume the Pydantic field directly;
do not add a second provider call or special response parser.

- [x] **Step 4: Run focused GREEN tests**

Run the command from Step 2.

Expected: all selected tests pass.

- [x] **Step 5: Commit**

```bash
git add \
  app/guide/adapters/llm/turn_meaning_prompt.py \
  app/guide/adapters/llm/deepseek_turn_meaning.py \
  tests/guide/adapters/test_turn_meaning_prompt.py \
  tests/guide/adapters/test_deepseek_turn_meaning.py
git commit -m "feat(guide): translate knowledge relations"
```

### Task 3: Build Raw-Text-Authoritative Knowledge Queries

**Files:**
- Create:
  `app/guide/retrieval/general_knowledge_ontology.py`
- Create:
  `app/guide/retrieval/general_knowledge_query.py`
- Modify:
  `app/guide/retrieval/general_knowledge_contracts.py`
- Test:
  `tests/guide/retrieval/test_general_knowledge_ontology.py`
- Test:
  `tests/guide/retrieval/test_general_knowledge_query.py`
- Test:
  `tests/guide/retrieval/test_general_knowledge_contracts.py`

- [x] **Step 1: Write failing ontology and query tests**

Cover normalization and raw authority:

```python
@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        ("A醇怎么用", ("ingredient.retinol",)),
        ("A 醇怎么用", ("ingredient.retinol",)),
        ("retinol怎么用", ("ingredient.retinol",)),
        ("维C白天能不能用", ("ingredient.vitamin_c",)),
        ("VC白天能不能用", ("ingredient.vitamin_c",)),
        ("抗坏血酸白天能不能用", ("ingredient.vitamin_c",)),
        ("烟酰胺有什么作用", ("ingredient.niacinamide",)),
    ),
)
def test_raw_aliases_resolve_canonical_entities(raw, expected):
    assert tuple(
        item.entity_id for item in match_knowledge_entities(raw)
    ) == expected
```

Prove model prose cannot invent or remove entities:

```python
spec = build_knowledge_query_spec(
    raw_query="烟酰胺能做什么",
    question_meaning="Compare retinol and vitamin C",
    topic=TopicCode.SERUM,
    relation_hints=("mechanism",),
    safety_sensitive=False,
    prior_knowledge_ids=(),
)
assert tuple(
    item.entity_id for item in spec.entity_mentions
) == ("ingredient.niacinamide",)
```

Prove explicit raw relation markers are unioned with model hints:

```python
spec = build_knowledge_query_spec(
    raw_query="烟酰胺和A醇有什么区别，能一起用吗？",
    question_meaning="比较两种活性成分",
    topic=TopicCode.SERUM,
    relation_hints=("difference",),
    safety_sensitive=False,
    prior_knowledge_ids=(),
)
assert spec.relation_intents == ("difference", "compatibility")
```

- [x] **Step 2: Run tests and verify RED**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/retrieval/test_general_knowledge_ontology.py \
  tests/guide/retrieval/test_general_knowledge_query.py \
  tests/guide/retrieval/test_general_knowledge_contracts.py \
  -k "ontology or alias or query_spec or relation"
```

Expected: imports fail because the ontology and query spec do not exist.

- [x] **Step 3: Add the strict query and coverage contracts**

Replace `GeneralKnowledgeQuery` at the retrieval boundary with:

```python
class KnowledgeEntityMention(_StrictFrozenModel):
    entity_id: str = Field(
        pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$"
    )
    raw_text: str = Field(min_length=1, max_length=128)


class KnowledgeQuerySpec(_StrictFrozenModel):
    raw_query: str = Field(min_length=1, max_length=4000)
    question_meaning: str = Field(min_length=1, max_length=512)
    concept_ids: tuple[str, ...] = Field(max_length=16)
    entity_mentions: tuple[KnowledgeEntityMention, ...] = Field(max_length=8)
    relation_intents: tuple[KnowledgeRelationIntent, ...] = Field(max_length=8)
    safety_sensitive: bool
    prior_knowledge_ids: tuple[str, ...] = Field(max_length=16)
    top_k: int = Field(default=3, ge=1, le=5)
```

Add `GeneralKnowledgeCoverage` with required, covered, and missing concept,
entity, and relation tuples plus a validated `complete` flag. Keep all tuple
fields ordered unique.

- [x] **Step 4: Add the canonical ontology**

Define immutable alias entries and longest-alias-first matching. Required
entity aliases are:

```python
_ENTITY_ALIASES = {
    "ingredient.niacinamide": (
        "烟酰胺", "维生素B3", "niacinamide",
    ),
    "ingredient.retinol": (
        "A醇", "A 醇", "维A", "维A醇", "视黄醇", "retinol",
    ),
    "ingredient.vitamin_c": (
        "维C", "维 C", "VC", "维生素C", "抗坏血酸",
        "vitamin C", "ascorbic acid",
    ),
    "ingredient.salicylic_acid": (
        "水杨酸", "BHA", "salicylic acid",
    ),
    "ingredient.acid": ("酸类", "刷酸", "果酸", "AHA"),
    "ingredient.proxylane": (
        "玻色因", "羟丙基四氢吡喃三醇", "pro-xylane",
    ),
    "ingredient.peptide": (
        "肽", "肽类", "胜肽", "多肽", "peptide", "peptides",
    ),
}
```

Add concept aliases for all source-topic children defined in Task 4.
Normalize with NFKC and case folding. Match domain aliases, never full
acceptance sentences.

- [x] **Step 5: Implement query compilation**

`build_knowledge_query_spec()` must:

1. extract entity and concept mentions only from `raw_query`;
2. preserve exact matched raw substrings;
3. add parent concepts for matching but retain child concepts for coverage;
4. parse generic explicit relation markers;
5. merge explicit relations before model relation hints;
6. map `TopicCode` only as a fallback parent concept;
7. copy the existing safety and prior-evidence authority;
8. return a strict `KnowledgeQuerySpec`.

Use generic marker tables:

```python
_RELATION_MARKERS = {
    "difference": ("区别", "差别", "不同", "一回事"),
    "compatibility": ("一起用", "同用", "叠加", "搭配", "冲突"),
    "mechanism": ("作用", "原理", "为什么", "是什么"),
    "usage": ("怎么用", "白天", "晚上", "顺序", "频率", "补涂"),
    "selection": ("怎么选", "如何选择"),
    "identification": ("怎么判断", "如何判断"),
    "safety": ("孕期", "哺乳期", "刺痛", "爆皮", "破皮", "严重"),
}
```

- [x] **Step 6: Run focused GREEN tests**

Run the command from Step 2.

Expected: all selected tests pass.

- [x] **Step 7: Commit**

```bash
git add \
  app/guide/retrieval/general_knowledge_ontology.py \
  app/guide/retrieval/general_knowledge_query.py \
  app/guide/retrieval/general_knowledge_contracts.py \
  tests/guide/retrieval/test_general_knowledge_ontology.py \
  tests/guide/retrieval/test_general_knowledge_query.py \
  tests/guide/retrieval/test_general_knowledge_contracts.py
git commit -m "feat(guide): compile typed knowledge queries"
```

### Task 4: Publish Reviewed Retrieval Profiles In A V2 Asset

**Files:**
- Create:
  `docs/audits/general-knowledge/retrieval_profiles_v1.jsonl`
- Modify:
  `tools/guide_data/audit_general_knowledge.py`
- Modify:
  `tools/guide_data/build_general_knowledge.py`
- Modify:
  `app/guide/retrieval/general_knowledge_contracts.py`
- Modify:
  `app/guide/retrieval/general_knowledge_assets.py`
- Modify:
  `app/guide_runtime/composition.py`
- Generate:
  `data/guide_general_knowledge/general_knowledge_v2_manifest.json`
- Generate:
  `data/guide_general_knowledge/general_knowledge_v2.<sha256>.jsonl`
- Test:
  `tests/guide/tools/test_audit_general_knowledge.py`
- Test:
  `tests/guide/tools/test_build_general_knowledge.py`
- Test:
  `tests/guide/retrieval/test_general_knowledge_assets.py`
- Test:
  `tests/guide/runtime/test_composition.py`

- [x] **Step 1: Write failing profile-integrity tests**

Test these failures:

- missing source profile;
- unknown source profile;
- missing section relation mapping;
- unknown section title;
- duplicate or unsorted concept/entity/relation IDs;
- stale profile SHA in the manifest;
- a published block without typed metadata;
- runtime still pinned to v1.

Add a positive assertion:

```python
assert assets.manifest.schema_version == "guide-general-knowledge-v2"
assert len(assets.blocks) == 209
assert all(block.primary_concept_ids for block in assets.blocks)
assert all(block.relation_intents for block in assets.blocks)
```

- [x] **Step 2: Run the asset suites and verify RED**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/tools/test_audit_general_knowledge.py \
  tests/guide/tools/test_build_general_knowledge.py \
  tests/guide/retrieval/test_general_knowledge_assets.py \
  tests/guide/runtime/test_composition.py \
  -k "general_knowledge"
```

Expected: v2 profile and manifest assertions fail.

- [x] **Step 3: Add the retrieval-profile contract**

Use one reviewed row per source document:

```python
class GeneralKnowledgeRetrievalProfile(_StrictFrozenModel):
    source_path: str
    primary_concept_ids: tuple[str, ...]
    primary_entity_ids: tuple[str, ...]
    section_relations: dict[
        str,
        tuple[KnowledgeRelationIntent, ...],
    ]
```

The catalog must cover these exact source concepts:

| Source prefix | Primary child concept | Primary entity |
|---|---|---|
| 01 | `skin.sensitive` | none |
| 02 | `skin.oily` | none |
| 03 | `skin.dry` | none |
| 04 | `skin.acne_prone` | none |
| 05 | `skin.barrier_damaged` | none |
| 06 | `category.sunscreen` | none |
| 07 | `category.serum` | none |
| 08 | `category.moisturizer` | none |
| 09 | `category.cleanser` | none |
| 10 | `category.makeup_remover` | none |
| 11 | `category.eye_care` | none |
| 12 | `category.mask` | none |
| 13 | `ingredient.niacinamide` | `ingredient.niacinamide` |
| 14 | `ingredient.retinol` | `ingredient.retinol` |
| 15 | `ingredient.acid`, `ingredient.salicylic_acid` | both |
| 16 | `ingredient.proxylane`, `ingredient.peptide` | both |
| 17 | `ingredient.vitamin_c` | `ingredient.vitamin_c` |
| 18 | `category.base_makeup` | none |
| 19 | `category.setting_makeup` | none |
| 20 | `category.lip_makeup`, `category.fragrance` | none |
| 21 | `routine.sensitive_anti_aging` | none |
| 22 | `assessment.sensitive_skin` | none |

Each row also includes the root parent (`skin`, `category`, `ingredient`,
`routine`, or `assessment`).

Use these section relations:

```text
document H1/intro -> overview
适合谁 -> overview, selection
怎么选 -> selection, usage
关键成分/原理 -> mechanism
避雷与注意 -> compatibility, usage, safety
可以考虑的商品类型 -> selection
叠加顺序与可以考虑的商品类型 -> compatibility, usage, selection
面霜与乳液的区别 -> difference
清洁误区 -> usage, safety
二次清洁 -> usage
相关彩妆怎么避雷 -> selection, safety
香水怎么顺手选 -> selection, usage, safety
怎么判断是不是敏感肌 -> identification, safety
看商品/商品图怎么判断它敏感肌友好 -> identification, selection
敏感肌护理原则 -> usage, safety
怎么选（几款热门对比） -> difference, selection
```

- [x] **Step 4: Join profiles during publication**

The audit/build path must:

1. load the profile JSONL strictly;
2. require exact equality with the 22 parsed source paths;
3. require every parsed section title to exist in its source profile;
4. derive `mentioned_concept_ids` and `mentioned_entity_ids` from each exact
   block using the canonical ontology;
5. attach primary and mentioned IDs plus section relations to every audited
   block;
6. publish `guide-general-knowledge-v2`;
7. include `retrieval_profile_sha256` in the v2 manifest.

Do not add metadata to `_block_identity()`. Keep existing knowledge IDs bound
to source content, while the v2 blocks SHA and manifest hash bind metadata.

- [x] **Step 5: Build and pin the v2 asset**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m tools.guide_data.build_general_knowledge \
  --source-dir data/knowledge_docs \
  --review-dir data/guide_general_knowledge/reviews \
  --retrieval-profile \
  docs/audits/general-knowledge/retrieval_profiles_v1.jsonl \
  --output-dir data/guide_general_knowledge \
  --asset-version 2026-08-31
```

Expected JSON:

```text
candidate_count=241
block_count=209
```

Update `GUIDE_GENERAL_KNOWLEDGE_RELATIVE_PATH` and
`GUIDE_GENERAL_KNOWLEDGE_MANIFEST_SHA256` to the generated v2 manifest. Retain
the v1 files as immutable historical evidence; runtime must load v2 once.

- [x] **Step 6: Run focused GREEN tests**

Run the command from Step 2 without `-k`.

Expected: all tests pass.

- [x] **Step 7: Commit**

```bash
git add \
  docs/audits/general-knowledge/retrieval_profiles_v1.jsonl \
  tools/guide_data/audit_general_knowledge.py \
  tools/guide_data/build_general_knowledge.py \
  app/guide/retrieval/general_knowledge_contracts.py \
  app/guide/retrieval/general_knowledge_assets.py \
  app/guide_runtime/composition.py \
  data/guide_general_knowledge/general_knowledge_v2_manifest.json \
  data/guide_general_knowledge/general_knowledge_v2.*.jsonl \
  tests/guide/tools/test_audit_general_knowledge.py \
  tests/guide/tools/test_build_general_knowledge.py \
  tests/guide/retrieval/test_general_knowledge_assets.py \
  tests/guide/runtime/test_composition.py
git commit -m "feat(guide): publish typed knowledge metadata"
```

### Task 5: Replace Weak Anchor Selection With Typed Retrieval And Coverage

**Files:**
- Modify:
  `app/guide/retrieval/general_knowledge_retrieval.py`
- Modify:
  `app/guide/retrieval/general_knowledge_contracts.py`
- Modify:
  `tests/guide/retrieval/test_general_knowledge_retrieval.py`

- [x] **Step 1: Add RED tests for the observed retrieval failures**

Add these assertions:

```python
def test_multi_entity_difference_covers_both_ingredients_without_face_cream():
    packet = _retriever().retrieve(
        _spec(
            "烟酰胺和A醇有什么区别，能一起用吗？",
            relations=("difference", "compatibility"),
        )
    )
    assert {
        "ingredient.niacinamide",
        "ingredient.retinol",
    } <= set(packet.coverage.covered_entity_ids)
    assert {
        hit.block.source_path for hit in packet.hits
    } <= {
        "data/knowledge_docs/13-烟酰胺适合谁.md",
        "data/knowledge_docs/14-视黄醇A醇适合谁.md",
    }
    assert "difference" in packet.coverage.covered_relation_intents
    assert "compatibility" in packet.coverage.missing_relation_intents
```

Also add:

- `维C白天到底能不能用？` returns source 17 in rank 1;
- `怎么判断自己是不是敏感肌？` returns source 22 identification in rank 1;
- `防晒为什么过几个小时还要补涂？` returns only source 06;
- English model meaning cannot replace raw Chinese aliases;
- an unrelated weather query returns no hits;
- repeated retrieval produces byte-identical JSON;
- a compatibility relation is complete only when one reviewed block mentions
  all required entities;
- every selected hit contributes typed or lexical coverage.

- [x] **Step 2: Run retrieval tests and verify RED**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q tests/guide/retrieval/test_general_knowledge_retrieval.py
```

Expected: the current face-cream mismatch and vitamin-C no-hit reproduce.

- [x] **Step 3: Implement typed candidate eligibility**

Precompute per-block primary/mentioned concepts and entities. Apply:

```python
def _eligible(block, spec):
    entity_ids = {
        item.entity_id for item in spec.entity_mentions
    }
    block_entities = set(block.primary_entity_ids).union(
        block.mentioned_entity_ids
    )
    block_concepts = set(block.primary_concept_ids).union(
        block.mentioned_concept_ids
    )
    if entity_ids:
        return bool(entity_ids.intersection(block_entities))
    if spec.concept_ids:
        return bool(set(spec.concept_ids).intersection(block_concepts))
    return bool(_literal_anchor_terms(spec))
```

Raw literal anchors must be unioned with shared raw/model terms. Remove the
current either/or selection:

```python
anchor_terms = literal_anchors.union(shared_anchors)
```

Model-only terms may affect score after eligibility but cannot authorize a
candidate.

- [x] **Step 4: Implement typed scoring**

Use named constants:

```python
PRIMARY_ENTITY_BOOST = 20.0
MENTIONED_ENTITY_BOOST = 10.0
CHILD_CONCEPT_BOOST = 8.0
RELATION_MATCH_BOOST = 6.0
RELATION_MISMATCH_PENALTY = 8.0
DIRECT_MULTI_ENTITY_BOOST = 12.0
```

Keep current IDF/body/title/section, prior, redirect, escalation, and intro
rules. Add typed boosts only from validated metadata. A relation mismatch
cannot create a negative hit; the existing minimum score still applies after
all terms.

- [x] **Step 5: Assemble evidence before truncating to top_k**

Build the packet in this order:

1. for `difference`, reserve the best mechanism/overview hit for each entity;
2. for `compatibility`, reserve a direct block only when its
   `mentioned_entity_ids` cover every requested entity;
3. for concept queries, reserve the best relation-matching hit for each
   required child concept;
4. fill remaining slots by deterministic score;
5. remove hits that add no concept, entity, relation, safety, or related-prior
   coverage;
6. compute `GeneralKnowledgeCoverage`;
7. sort the final tuple by the packet's deterministic order contract.

If required entities exceed `top_k`, fail closed instead of silently dropping
an entity.

- [x] **Step 6: Run focused GREEN tests**

Run the command from Step 2.

Expected: all retrieval tests pass, including no unrelated source paths.

- [x] **Step 7: Commit**

```bash
git add \
  app/guide/retrieval/general_knowledge_retrieval.py \
  app/guide/retrieval/general_knowledge_contracts.py \
  tests/guide/retrieval/test_general_knowledge_retrieval.py
git commit -m "fix(guide): enforce typed knowledge coverage"
```

### Task 6: Render Partial Evidence Gaps And Publish Coverage In SSE

**Files:**
- Modify:
  `app/guide/application/general_knowledge_answer.py`
- Modify:
  `app/guide/presentation/sse_events.py`
- Test:
  `tests/guide/application/test_general_knowledge_answer.py`

- [x] **Step 1: Write failing renderer and SSE tests**

Construct a packet with both ingredient mechanism hits and missing
compatibility. Assert:

```python
rendered = render_general_knowledge_answer(packet)

assert "烟酰胺" in rendered.message
assert "A醇" in rendered.message or "视黄醇" in rendered.message
assert "一起使用" in rendered.message
assert "缺少直接审核证据" in rendered.message
assert rendered.data.coverage.complete is False
assert rendered.data.coverage.missing_relation_intents == [
    "compatibility"
]
assert len(rendered.data.citations) == 2
```

Add tests proving:

- a missing entity prevents a difference conclusion;
- complete single-entity usage evidence has `coverage.complete=True`;
- no hit returns the explicit evidence gap and empty citations;
- unknown SSE coverage fields are rejected;
- citation order equals packet hit order.

- [x] **Step 2: Run tests and verify RED**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q tests/guide/application/test_general_knowledge_answer.py
```

Expected: coverage is absent and the current renderer cannot describe a
partial relation gap.

- [x] **Step 3: Add the public coverage contract**

Add strict list fields mirroring `GeneralKnowledgeCoverage`:

```python
class GeneralKnowledgeCoverageData(_Strict):
    required_concept_ids: list[str]
    covered_concept_ids: list[str]
    required_entity_ids: list[str]
    covered_entity_ids: list[str]
    required_relation_intents: list[KnowledgeRelationIntent]
    covered_relation_intents: list[KnowledgeRelationIntent]
    missing_concept_ids: list[str]
    missing_entity_ids: list[str]
    missing_relation_intents: list[KnowledgeRelationIntent]
    complete: bool
```

Add `coverage` to `GeneralKnowledgeData`.

- [x] **Step 4: Make the renderer fail closed per requested relation**

Use reviewed `public_text` only. Render covered blocks, then add deterministic
gap copy using a fixed label map:

```python
_RELATION_LABELS = {
    "overview": "基础说明",
    "mechanism": "作用原理",
    "difference": "区别",
    "compatibility": "能否一起使用",
    "usage": "使用方法",
    "selection": "选择方法",
    "identification": "判断方法",
    "safety": "安全边界",
}
```

For missing compatibility, emit:

```text
现有审核资料缺少这组对象能否一起使用的直接证据，
这里不根据各自介绍推导兼容性结论。
```

For a missing entity in a difference request, do not claim a difference.
Keep the existing medical escalation and product redirect behavior.

- [x] **Step 5: Run focused GREEN tests**

Run the command from Step 2.

Expected: all renderer and SSE tests pass.

- [x] **Step 6: Commit**

```bash
git add \
  app/guide/application/general_knowledge_answer.py \
  app/guide/presentation/sse_events.py \
  tests/guide/application/test_general_knowledge_answer.py
git commit -m "fix(guide): expose knowledge evidence gaps"
```

### Task 7: Wire The Query Spec Into The Existing Processor

**Files:**
- Modify:
  `app/guide/application/text_recommendation_flow.py`
- Modify:
  `tests/guide/application/test_text_recommendation_flow.py`
- Modify:
  `tests/guide/runtime/test_runtime_http.py`

- [x] **Step 1: Write failing processor and HTTP tests**

Capture the argument passed to the existing retriever and assert:

```python
assert type(captured) is KnowledgeQuerySpec
assert tuple(
    item.entity_id for item in captured.entity_mentions
) == ("ingredient.niacinamide", "ingredient.retinol")
assert captured.relation_intents == (
    "difference",
    "compatibility",
)
```

Add HTTP cases for all six observed probes with these expected modes:

```python
(
    ("烟酰胺和A醇有什么区别，能一起用吗？", "general_knowledge"),
    ("怎么判断自己是不是敏感肌？", "general_knowledge"),
    ("刷酸后爆皮刺痛应该怎么办？", "consultation"),
    ("防晒为什么过几个小时还要补涂？", "general_knowledge"),
    ("维C白天到底能不能用？", "general_knowledge"),
    ("油皮夏天应该怎么选面霜？", "general_knowledge"),
)
```

Use injected typed TurnMeaning in unit/HTTP tests. Real provider behavior is
covered in Task 10.

- [x] **Step 2: Run tests and verify RED**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/runtime/test_runtime_http.py \
  -k "general_knowledge or acid_flaking"
```

Expected: the processor still creates `GeneralKnowledgeQuery`, and new
coverage assertions fail.

- [x] **Step 3: Replace only the query construction**

Inside `_execute_general_knowledge_task()`, replace direct
`GeneralKnowledgeQuery(...)` construction with:

```python
query = build_knowledge_query_spec(
    raw_query=execution_input.routing_evidence.query.value.strip(),
    question_meaning=(
        task.question_meaning
        or execution_input.routing_evidence.query.value.strip()
    ),
    topic=topic,
    relation_hints=task.knowledge_relation_hints,
    safety_sensitive=task.safety_sensitive,
    prior_knowledge_ids=prior_ids,
    top_k=3,
)
packet = self._general_knowledge.retrieve(query)
```

Do not add another processor, dispatcher, provider call, or retrieval bypass.
Keep state writes bound to selected packet knowledge IDs.

- [x] **Step 4: Run focused GREEN tests**

Run the command from Step 2.

Expected: all selected tests pass.

- [x] **Step 5: Commit**

```bash
git add \
  app/guide/application/text_recommendation_flow.py \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/runtime/test_runtime_http.py
git commit -m "feat(guide): execute typed knowledge queries"
```

### Task 8: Add The 22-Topic Deterministic Recall Gate

**Files:**
- Create:
  `tests/fixtures/guide/general_knowledge/general_knowledge_recall_v1.jsonl`
- Create:
  `tools/guide_gates/run_general_knowledge_recall_gate.py`
- Create:
  `tests/guide/tools/test_run_general_knowledge_recall_gate.py`

- [x] **Step 1: Write failing gate tests**

Define a strict case model:

```python
class GeneralKnowledgeRecallCase(_StrictFrozenModel):
    case_id: str
    query: str
    question_meaning: str
    topic: TopicCode | None
    relation_hints: tuple[KnowledgeRelationIntent, ...]
    expected_source_paths: tuple[str, ...]
    allowed_source_paths: tuple[str, ...]
    expected_section_titles: tuple[str, ...]
    allowed_section_titles: tuple[str, ...]
    expected_missing_relations: tuple[KnowledgeRelationIntent, ...] = ()
    expected_no_hit: bool = False
```

The report must expose:

```python
class GeneralKnowledgeRecallReport(_StrictFrozenModel):
    schema_version: Literal["guide-general-knowledge-recall-v1"]
    passed: bool
    case_count: int
    represented_source_count: int
    recall_at_3: float
    wrong_topic_citation_count: int
    wrong_section_citation_count: int
    entity_coverage_failure_count: int
    relation_coverage_failure_count: int
    deterministic_mismatch_count: int
```

Test rejection of duplicate case IDs, missing source-topic representation,
unlisted citation paths, and non-byte-identical repeated retrieval.

- [x] **Step 2: Create the exact source-topic matrix**

Include these 22 required common questions:

| Source | Query | Required section |
|---|---|---|
| 01 | 敏感肌护肤品应该怎么选？ | 怎么选 |
| 02 | 混油皮日常护肤怎么安排？ | 怎么选 |
| 03 | 干皮怎么做好保湿和修护？ | 怎么选 |
| 04 | 痘肌选护肤品要避开什么？ | 避雷与注意 |
| 05 | 皮肤屏障受损后怎么修护？ | 怎么选 |
| 06 | 防晒为什么过几个小时还要补涂？ | 避雷与注意 |
| 07 | 不同功效的精华应该怎么选？ | 怎么选 |
| 08 | 油皮夏天应该怎么选面霜？ | 怎么选 |
| 09 | 洁面产品应该怎么选？ | 怎么选 |
| 10 | 卸妆油和卸妆水怎么选？ | 怎么选 |
| 11 | 眼霜怎么按眼周问题选择？ | 怎么选 |
| 12 | 补水面膜和医用敷料有什么区别？ | 怎么选 |
| 13 | 烟酰胺有什么作用？ | 关键成分/原理 |
| 14 | A醇怎么建立耐受？ | 避雷与注意 |
| 15 | 水杨酸适合什么人？ | 适合谁 |
| 16 | 玻色因和肽类有什么区别？ | 关键成分/原理 |
| 17 | 维C白天到底能不能用？ | 避雷与注意 |
| 18 | 油皮应该怎么选粉底液？ | 怎么选 |
| 19 | 散粉、粉饼和定妆喷雾怎么选？ | 怎么选 |
| 20 | 日常通勤口红怎么选？ | 怎么选 |
| 21 | 干敏肌怎么温和抗初老？ | 适合谁 |
| 22 | 怎么判断自己是不是敏感肌？ | 怎么判断是不是敏感肌 |

Add these required variants:

```text
烟酰胺和A醇有什么区别，能一起用吗？
niacinamide 和 retinol 是一回事吗，能叠加吗？
VC 早上可以用吗？
抗坏血酸白天怎么用？
明天上海天气怎么样？
```

Each fixture row explicitly lists expected and allowed source paths. The
multi-entity rows allow only sources 13 and 14. The weather row expects no hit.

- [x] **Step 3: Implement the deterministic gate**

For every case:

1. build a real `KnowledgeQuerySpec`;
2. call the production `GeneralKnowledgeRetriever`;
3. call it again and compare `model_dump_json()` bytes;
4. require every expected source in top three;
5. require every expected section in top three;
6. reject every citation outside `allowed_source_paths` or
   `allowed_section_titles`;
7. validate expected missing relations;
8. aggregate the report;
9. exit nonzero unless all thresholds pass.

The pass condition is exactly:

```python
passed = (
    represented_source_count == 22
    and recall_at_3 == 1.0
    and wrong_topic_citation_count == 0
    and wrong_section_citation_count == 0
    and entity_coverage_failure_count == 0
    and relation_coverage_failure_count == 0
    and deterministic_mismatch_count == 0
)
```

- [x] **Step 4: Run the gate tests and production matrix**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/tools/test_run_general_knowledge_recall_gate.py

PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/run_general_knowledge_recall_gate.py \
  --cases \
  tests/fixtures/guide/general_knowledge/general_knowledge_recall_v1.jsonl \
  --output \
  docs/audits/general-knowledge/retrieval-stability/deterministic
```

Expected:

```text
represented_source_count=22
recall_at_3=1.0
wrong_topic_citation_count=0
wrong_section_citation_count=0
entity_coverage_failure_count=0
relation_coverage_failure_count=0
deterministic_mismatch_count=0
passed=true
```

- [x] **Step 5: Commit**

```bash
git add \
  tests/fixtures/guide/general_knowledge/general_knowledge_recall_v1.jsonl \
  tools/guide_gates/run_general_knowledge_recall_gate.py \
  tests/guide/tools/test_run_general_knowledge_recall_gate.py \
  docs/audits/general-knowledge/retrieval-stability/deterministic
git commit -m "test(guide): gate general knowledge recall"
```

### Task 9: Render And Validate Real General-Knowledge Citations

**Files:**
- Modify:
  `app/static/chat.html`
- Modify:
  `tests/guide/runtime/test_frontend_scope.py`
- Modify:
  `tests/guide/runtime/test_frontend_presentation_stream.py`

- [x] **Step 1: Write failing frontend contract tests**

Add static/runtime tests requiring:

```javascript
validateGeneralKnowledgePayload(deferredPanels.generalKnowledge);
displayGeneralKnowledgeCitations(
    deferredPanels.generalKnowledge.citations
);
```

Validate:

- citation IDs are unique 64-character lowercase hex;
- title, section title, source path, review decision, and public excerpt have
  valid types;
- a `general_answer` citation has nonempty `public_excerpt`;
- a non-answer citation has no `public_excerpt`;
- coverage lists are unique and internally consistent;
- citations render once through the existing citation visual surface;
- zero citations render no empty heading or container;
- final auto-scroll still occurs after citations are added.

- [x] **Step 2: Run frontend tests and verify RED**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/runtime/test_frontend_scope.py \
  tests/guide/runtime/test_frontend_presentation_stream.py \
  -k "general_knowledge or citation"
```

Expected: Guide mode currently stores the event but clears evidence panels
without rendering general-knowledge citations.

- [x] **Step 3: Add strict citation rendering**

Add a dedicated validator and map reviewed citations to the existing display
shape:

```javascript
function displayGeneralKnowledgeCitations(citations) {
    const rows = citations.map(citation => ({
        id: citation.knowledge_id,
        title: `${citation.title} / ${citation.section_title}`,
        snippet: citation.public_excerpt || '仅用于边界提示',
        type: 'guide'
    }));
    displayCitations(rows);
}
```

Call it only after `validateGuideTerminalPayload()` accepts the
`general_knowledge` event and structured presentation. Keep citations outside
the answer card, deduplicate by knowledge ID, and call
`autoScrollToBottom(true)` after rendering.

- [x] **Step 4: Run focused GREEN tests**

Run the command from Step 2.

Expected: all selected tests pass.

- [x] **Step 5: Commit**

```bash
git add \
  app/static/chat.html \
  tests/guide/runtime/test_frontend_scope.py \
  tests/guide/runtime/test_frontend_presentation_stream.py
git commit -m "feat(guide): display reviewed knowledge citations"
```

### Task 10: Add And Run The Real DeepSeek Browser Acceptance

**Files:**
- Modify:
  `tools/guide_gates/run_mainline_contract_browser_audit.py`
- Modify:
  `tests/guide/tools/test_run_mainline_contract_browser_audit.py`
- Generate:
  `docs/audits/general-knowledge/retrieval-stability/real-run-01/`
- Generate:
  `docs/audits/general-knowledge/retrieval-stability/real-run-02/`

- [x] **Step 1: Write failing trajectory and usefulness tests**

Add `GENERAL_KNOWLEDGE_TRAJECTORIES` containing the six observed probes. Extend
`BoundedBrowserTurn` with:

```python
expected_knowledge_sources: tuple[str, ...] = ()
allowed_knowledge_sources: tuple[str, ...] = ()
expected_knowledge_sections: tuple[str, ...] = ()
allowed_knowledge_sections: tuple[str, ...] = ()
expected_missing_relations: tuple[str, ...] = ()
```

Test that the runner rejects:

- missing expected source;
- missing expected section;
- a citation outside the allowed sources;
- a citation outside the allowed sections;
- duplicate citation IDs;
- a coverage mismatch;
- an unsupported compatibility conclusion;
- a general-knowledge event on the consultation case;
- a missing visible citation panel for a knowledge answer.

- [x] **Step 2: Run the browser-runner tests and verify RED**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/tools/test_run_mainline_contract_browser_audit.py \
  -k "general_knowledge"
```

Expected: the trajectory set and citation usefulness validation are absent.

- [x] **Step 3: Extend the existing browser runner**

Add CLI choice `general_knowledge` and dispatch it through the existing
`run_bounded_browser_audit()`. Do not create a second browser execution stack.

The six exact expected outcomes are:

```text
gk-multi-ingredient:
  mode=general_knowledge
  sources={13,14}
  missing_relations={compatibility}

gk-sensitive-identification:
  mode=general_knowledge
  sources={22}

gk-acid-active-reaction:
  mode=consultation
  no general_knowledge event

gk-sunscreen-reapplication:
  mode=general_knowledge
  sources={06}

gk-vitamin-c-daytime:
  mode=general_knowledge
  sources={17}

gk-oily-summer-moisturizer:
  mode=general_knowledge
  sources limited to {02,08}
```

Capture the existing request, exact SSE, presentation contract, terminal DOM,
console, network, and screenshot files for every turn.

- [x] **Step 4: Run focused GREEN tests**

Run the command from Step 2.

Expected: all selected tests pass.

- [x] **Step 5: Start a clean real runtime**

Use the existing credential file without printing or committing its value:

```bash
export GUIDE_LLM_API_KEY="$(
  cat /Users/bytedance/Desktop/deepseek-key.txt
)"
export GUIDE_LLM_BASE_URL="https://api.deepseek.com"
export GUIDE_LLM_MODEL="deepseek-v4-pro"
export GUIDE_LLM_FORMAT_REPAIR_ATTEMPTS="0"
export GUIDE_COPY_LLM_API_KEY="$GUIDE_LLM_API_KEY"
export GUIDE_COPY_LLM_BASE_URL="$GUIDE_LLM_BASE_URL"
export GUIDE_COPY_LLM_MODEL="$GUIDE_LLM_MODEL"
export XIAORO_GUIDE_STATE_DIR="/tmp/xiaoro-general-knowledge-stability"

/Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/uvicorn \
  app.guide_runtime.app:app \
  --host 127.0.0.1 \
  --port 8842
```

- [x] **Step 6: Run two consecutive real browser passes**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/run_mainline_contract_browser_audit.py \
  --base-url http://127.0.0.1:8842 \
  --trajectory-set general_knowledge \
  --viewport desktop \
  --output \
  docs/audits/general-knowledge/retrieval-stability/real-run-01

PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  tools/guide_gates/run_mainline_contract_browser_audit.py \
  --base-url http://127.0.0.1:8842 \
  --trajectory-set general_knowledge \
  --viewport desktop \
  --output \
  docs/audits/general-knowledge/retrieval-stability/real-run-02
```

Expected for each run:

```text
trajectory_count=6
turn_count=6
passed_turn_count=6
wrong responsibility=0
wrong knowledge source=0
wrong knowledge section=0
coverage mismatch=0
frontend contract violation=0
console error=0
passed=true
```

Do not accept one green run after one semantic/citation failure. Repair the
earliest owner, rerun focused tests and the deterministic gate, delete only
the rejected output directories, then restart both runs from `real-run-01`.

- [x] **Step 7: Commit**

```bash
git add \
  tools/guide_gates/run_mainline_contract_browser_audit.py \
  tests/guide/tools/test_run_mainline_contract_browser_audit.py \
  docs/audits/general-knowledge/retrieval-stability/real-run-01 \
  docs/audits/general-knowledge/retrieval-stability/real-run-02
git commit -m "test(guide): verify real knowledge retrieval"
```

### Task 11: Run Full Regression, Audit The Diff, And Push

**Files:**
- Modify:
  `docs/audits/general-knowledge/retrieval-stability/report.md`
- Modify only the earliest owner of any reproducible regression.

- [x] **Step 1: Run the complete focused knowledge suite**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/understanding/test_turn_meaning_contracts.py \
  tests/guide/adapters/test_turn_meaning_prompt.py \
  tests/guide/adapters/test_deepseek_turn_meaning.py \
  tests/guide/intent/test_executable_intent_compiler.py \
  tests/guide/intent/test_signal_merger.py \
  tests/guide/intent/test_task_planning.py \
  tests/guide/retrieval/test_general_knowledge_ontology.py \
  tests/guide/retrieval/test_general_knowledge_query.py \
  tests/guide/retrieval/test_general_knowledge_contracts.py \
  tests/guide/retrieval/test_general_knowledge_assets.py \
  tests/guide/retrieval/test_general_knowledge_retrieval.py \
  tests/guide/tools/test_build_general_knowledge.py \
  tests/guide/tools/test_audit_general_knowledge.py \
  tests/guide/tools/test_run_general_knowledge_recall_gate.py \
  tests/guide/application/test_general_knowledge_answer.py \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/runtime/test_runtime_http.py \
  tests/guide/runtime/test_frontend_scope.py \
  tests/guide/runtime/test_frontend_presentation_stream.py \
  tests/guide/tools/test_run_mainline_contract_browser_audit.py
```

Expected: all tests pass.

- [x] **Step 2: Run architecture and anti-patch gates**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q \
  tests/guide/tools/test_no_sentence_patch.py \
  tests/guide/tools/test_single_path_architecture.py
```

Expected:

```text
no sentence-specific branch
one Guide routing path
one general-knowledge processor
one GeneralKnowledgeRetriever
no legacy RAG import
no text-vector dependency
```

- [x] **Step 3: Run the full regression and static checks**

```bash
PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m pytest -q

PYTHONPATH=. /Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/python \
  -m compileall -q app tools

git diff --check
```

Expected: all tests and static checks pass.

- [x] **Step 4: Write the final stability report**

Create `docs/audits/general-knowledge/retrieval-stability/report.md` with:

```text
v2 manifest SHA-256
source documents: 22
published reviewed blocks: 209
deterministic case count
Recall@3
wrong-topic citation count
wrong-section citation count
entity coverage failures
relation coverage failures
expected no-hit results
real-run-01 result and evidence path
real-run-02 result and evidence path
full pytest result
remaining corpus gaps
```

State explicitly that missing direct compatibility evidence is an honest
corpus gap, not a retrieval failure, and that no text vector path was added.

- [x] **Step 5: Inspect the final diff and staged files**

```bash
git status --short
git diff --stat
git diff -- \
  app/guide \
  app/guide_runtime/composition.py \
  app/static/chat.html \
  tools/guide_data \
  tools/guide_gates \
  tests/guide \
  data/guide_general_knowledge \
  docs/audits/general-knowledge \
  docs/superpowers/specs/2026-08-31-general-knowledge-retrieval-stability-design.md \
  docs/superpowers/plans/2026-08-31-general-knowledge-retrieval-stability.md
```

Verify that no credential, `.dbg` file, temporary state, old-worktree file, or
unrelated audit directory is staged.

- [x] **Step 6: Commit the report and any final test-only changes**

```bash
git add \
  docs/audits/general-knowledge/retrieval-stability/report.md \
  docs/superpowers/specs/2026-08-31-general-knowledge-retrieval-stability-design.md \
  docs/superpowers/plans/2026-08-31-general-knowledge-retrieval-stability.md
git commit -m "docs(guide): close knowledge retrieval stability"
```

- [x] **Step 7: Push the completed branch**

```bash
git push -u origin HEAD:wip/general-knowledge-retrieval-stability
```

If normal push reproduces the remote object-pack failure, use the already
proven tree-preserving snapshot method and verify:

```bash
git rev-parse HEAD^{tree}
git ls-remote origin refs/heads/wip/general-knowledge-retrieval-stability
```

The remote terminal commit must have the same tree hash as local `HEAD`.

## Completion Criteria

The work is complete only when all are true:

- runtime loads the pinned v2 typed knowledge asset;
- all 22 source topics are represented in the deterministic matrix;
- deterministic `Recall@3 = 100%`;
- wrong-topic citation count is zero;
- wrong-section citation count is zero;
- explicit entity coverage is 100%;
- unsupported compatibility claims are zero;
- expected no-hit behavior is exact;
- repeated deterministic retrieval is byte-identical;
- the six observed real probes pass twice consecutively;
- reviewed citations are visible in the shipped frontend;
- focused, architecture, anti-patch, and full regression suites pass;
- no text-vector path, sentence branch, second dispatcher, or unreviewed
  knowledge answer was introduced;
- local and remote terminal tree hashes match.
