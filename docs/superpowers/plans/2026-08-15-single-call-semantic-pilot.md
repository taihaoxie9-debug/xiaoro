# Single-Call Semantic Translation Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task. The main
> agent executes all work; sub-agents are forbidden by the user.

**Goal:** Run an isolated eight-case official-model experiment for a
single-call, source-grounded semantic translation contract.

**Architecture:** Define strict pilot-only Pydantic contracts and a
deterministic equivalence-aware evaluator. Reuse the existing protected
DeepSeek key reader and JSON client, call V4-Pro exactly once per case, and
write redacted content-addressed evidence outside the repository.

**Tech Stack:** Python 3.11, Pydantic v2, pytest, httpx, existing DeepSeek
official JSON transport.

---

## Constraints

- Do not modify production semantic, runtime, RAG, ranking, state, or frontend
  code.
- Do not add a repair call. Invalid JSON is one failed case.
- Do not send product data or long conversation context.
- Do not lower the existing official gate or change its fixtures.
- Do not stage, commit, push, or deploy the shared dirty implementation.

## Task 1: Freeze Pilot Cases

**Files:**

- Create:
  `tests/fixtures/guide/intent/single_call_semantic_pilot_v1.jsonl`
- Test: `tests/guide/tools/test_single_call_semantic_pilot.py`

- [ ] Add exactly eight rows named in the design.
- [ ] Store current message, code-derived binding authority, required goal,
  allowed topics, and required resolved semantic atoms.
- [ ] Add a RED test that imports the not-yet-existing pilot loader and asserts
  eight unique cases and all eight business families.
- [ ] Run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/tools/test_single_call_semantic_pilot.py
```

Expected: collection failure because
`tools.guide_gates.single_call_semantic_pilot` does not exist.

## Task 2: Implement Strict Contracts and Grounding

**Files:**

- Create: `tools/guide_gates/single_call_semantic_pilot.py`
- Test: `tests/guide/tools/test_single_call_semantic_pilot.py`

- [ ] Add strict frozen translation, fixture, grounded-reference, row-result,
  and summary contracts.
- [ ] Add unique-substring grounding.
- [ ] Parse Chinese ordinal reference text deterministically.
- [ ] Admit references only against the fixture binding authority.
- [ ] Add tests proving `第一张` and `第一张图` resolve to the same image while
  invented or ambiguous text is rejected.
- [ ] Run the focused test and expect PASS.

## Task 3: Implement Meaning-Aware Evaluation

**Files:**

- Modify: `tools/guide_gates/single_call_semantic_pilot.py`
- Test: `tests/guide/tools/test_single_call_semantic_pilot.py`

- [ ] Add required-atom evaluation for goals, allowed topics, references,
  observations, preference fields, and budget values.
- [ ] Treat unspecified fields as `don't care`, not as required empty values.
- [ ] Reject any model raw text that cannot uniquely bind the current message.
- [ ] Add RED tests for a valid extra sensitivity preference and a missing
  required assessment observation.
- [ ] Implement the minimal evaluator and run focused tests to PASS.

## Task 4: Implement One-Call Official Runner

**Files:**

- Modify: `tools/guide_gates/single_call_semantic_pilot.py`
- Test: `tests/guide/tools/test_single_call_semantic_pilot.py`

- [ ] Build one universal system prompt and one compact user payload.
- [ ] Inject a completion callable for unit tests.
- [ ] Assert exactly one completion invocation per case.
- [ ] Reuse `OpenAIJsonClient` and the protected `0600` key reader for CLI
  execution.
- [ ] Write `results.jsonl`, `summary.json`, and `SHA256SUMS` without the API
  key, request headers, or hidden reasoning.
- [ ] Test an eight-case fake completion run and verify exactly eight calls.
- [ ] Run focused tests to PASS.

## Task 5: Execute and Compare

- [ ] Confirm no prior pilot process exists.
- [ ] Run once:

```bash
.venv/bin/python -m tools.guide_gates.single_call_semantic_pilot \
  --cases tests/fixtures/guide/intent/single_call_semantic_pilot_v1.jsonl \
  --output-dir /private/tmp/xiaoro-single-call-semantic-pilot-20260815
```

- [ ] Read the typed summary and compare each row with official run 2
  `normalized_results.jsonl`.
- [ ] Write:
  `docs/audits/semantic-transitions/single_call_pilot_report.md`.
- [ ] Run:

```bash
.venv/bin/python -m pytest -q \
  tests/guide/tools/test_single_call_semantic_pilot.py
git diff --check
```

- [ ] Stop without changing the production semantic contract.

