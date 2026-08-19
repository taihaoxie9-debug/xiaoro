# Product Alias, Pending Turn, And Session Closure

Date: 2026-08-16

Repository: `/Users/bytedance/Desktop/xiaoro-fresh`

Branch: `rebuild`

Local release status: `GO`

Production deployment: `not performed`

## Scope Closed

This closure covers:

- full-catalog product nickname and alias review;
- exact product, exact variant, and ambiguous family binding;
- durable `PendingTurn` clarification resumption;
- confirmation, rejection, correction, supplementation, ambiguity, and
  task-replacement transitions;
- cross-worker CAS recovery and session isolation;
- owner-scoped backend session deletion and transactional browser deletion;
- comparison terminal UI cleanup;
- real-model, full-test, and desktop/mobile browser gates.

Long-term profile opt-in, account identity, and multi-person profile
management remain explicit non-goals.

## Full-Catalog Alias Audit

The runtime asset is generated from reviewed records rather than a hand-built
popular-product dictionary.

```text
Canonical products:             103
accepted evidence alias blocks:  30
legacy review candidates:        95
reviewed alias decisions:       155
published runtime aliases:      118
```

Reviewed decisions:

```text
approved_exact_product: 80
approved_exact_variant: 17
ambiguous_family:       21
ingredient_nickname:     7
marketing_phrase:        1
unavailable_product:    16
unresolved_candidate:   13
```

The 21 ambiguous family records are recognized but never select a convenient
SKU. Examples include `B5`, `菁纯`, `粉水`, `琥珀`, `小白管`, `金盏花水`,
`菌菇水`, `子弹头`, and `五号香水`.

The 13 unresolved candidates and 16 products absent from the Canonical
catalog are not published. Marketing and ingredient terms such as
`油皮救星`, `冰川蛋白`, `律波肽`, and `玻色因` are explicitly excluded from
product identity.

```text
unresolved:
377, ANR, CE, DW, DW持妆, DW粉底, Orgasm, 大哥大, 大哥大防晒,
安耐晒, 理肤泉大哥大, 红气垫, 黑气垫

absent from Canonical catalog:
AI乳, DUO+, K乳, 兰蔻粉水, 净痘, 大师, 大师粉底, 大师粉底液,
大粉水, 大红瓶, 安心霜, 特安霜, 白泥, 白泥面膜, 蓝朋友,
金盏花面膜
```

Runtime asset:

```text
full 155-row review ledger:
data/canonical/product_alias_reviews_v1.jsonl

machine-readable audit report:
docs/audits/semantic-transitions/product_alias_audit_v1.json

published 118-row runtime subset:
data/canonical/controlled_product_aliases_v1.jsonl
records: 118
SHA-256: 6726fdcb372f47f677143a5bc6c841ea9b56d02186148882ffac1ca579f2bcdd
Canonical SHA-256:
0ba95df8c38d39f5bc0d73a32c318b157903abb64778c3e7b0acebfb75e95734
```

## Last Earliest-Failure Repair

The final real-model failure was:

```text
帮我对比兰蔻小黑瓶和小棕瓶
```

The model already returned two correctly grounded `product_mentions`, and
the controlled resolver already bound them to Canonical IDs `129` and `33`.
The remaining error was in task-planning reconciliation: the model's stale
`ambiguous_reference` issue survived after both names had been proven
resolvable.

The repair clears that issue only when:

```text
product resolution has no issue
all product mentions have resolved IDs
the message spans still match
there are no unresolved ReferenceDraft values
```

The opposite boundary is locked by a regression test:

```text
帮我对比这款和小棕瓶
```

This still clarifies because `这款` is a real unresolved reference.

The traced layers were:

```text
semantic translation:
  two name-bound ProductMentionDraft values with valid source spans
controlled resolver:
  兰蔻小黑瓶 -> 129
  小棕瓶 -> 33
task planning before repair:
  stale ambiguous_reference -> clarify
task planning after repair:
  no remaining issue -> comparison [129, 33]
```

Implementation and regression locks:

```text
app/guide/intent/task_planning.py
tests/guide/intent/test_task_planning.py::
  test_resolved_product_mentions_clear_false_reference_uncertainty
  test_resolved_name_does_not_clear_unresolved_reference_uncertainty
```

## Pending Turn And Session State

`ConversationSnapshot.pending_turn` now preserves the original source turn,
source version, expected response, proposed budget, and structured resume
context. It is committed only after terminal public-event delivery.

Verified transitions:

```text
是的 / 对 / 没错       -> accept and resume
不是                   -> reject proposal and ask for a value
改成800到1000          -> correct and resume
是的，而且不要酒精     -> supplement and resume
改看防晒吧             -> cancel old pending task and replace it
差不多吧               -> preserve pending state and ask again
```

SQLite WAL/CAS tests prove restart and cross-worker recovery, stale-version
rejection, one-time consumption, and isolation between independent sessions.
An executed task with no matching products stores `empty_result=true` and
clears the completed pending turn.

`DELETE /api/v1/chat/sessions/{session_id}` atomically deletes only the
matching owner's short-term snapshot. Missing and foreign sessions do not
leak existence. The browser removes local history, conversation version, and
feedback target only after backend `204`. Long-term profile state is not
deleted or otherwise changed.

Primary implementation and test artifacts:

```text
app/guide/application/pending_turn.py
app/guide/application/text_recommendation_flow.py
app/guide/feedback/contracts.py
app/guide/adapters/state/sqlite_conversation_state.py
app/guide_runtime/app.py
app/static/chat.html

tests/guide/application/test_pending_turn.py
tests/guide/application/test_text_recommendation_flow.py
tests/guide/application/test_cross_worker_text_state.py
tests/guide/adapters/state/test_sqlite_conversation_state.py
tests/guide/runtime/test_runtime_http.py
tests/guide/runtime/test_frontend_presentation_history.py
```

## Current Real-Model Evidence

The current `8011` runtime used provider `deepseek_official`, model
`deepseek-v4-pro`, and the official `https://api.deepseek.com` endpoint.
No credential is stored in the report. It returned:

```text
input: 帮我对比兰蔻小黑瓶和小棕瓶
intent: comparison
product IDs: [129, 33]
terminal card IDs: [129, 33]
clarification: none
conversation version: 1
```

Both products rendered with their Canonical names, prices, inline image
cards, and terminal product cards:

```text
129 兰蔻肌底焕活修护精华液 50ml
33  雅诗兰黛特润修护肌活精华露
```

Machine-readable current-run evidence:

```text
docs/audits/semantic-transitions/alias-comparison-final-v1.json
docs/audits/semantic-transitions/screenshots/alias-comparison-final.png
```

The locked official TurnMeaning evidence remains above the production gate:

```text
119 / 128 end-to-end passed
rate: 92.97%
wrong product selections: 0
unauthorized state transitions: 0
hard safety overrides: 0
```

The gate requires 128 provider calls, at least 90% end-to-end success, and
zero hard state, safety, product, and source violations. The remaining nine
cases were eight schema-invalid responses that failed closed plus the known
`rec-007-paraphrase-serum` translation miss. No failed case selected a wrong
product or changed stored state. Evidence:

```text
docs/audits/semantic-turn-meaning/official_gate_replay_v1.json
docs/audits/semantic-turn-meaning/closure_report.md
```

The official presentation-copy gate passed `12 / 12` with zero hard
violations:

```text
docs/audits/frontend-integration/copywriter-gates/
  official-final-v3-1/summary.json
```

## Browser Evidence

The final Playwright audit used the current real-model URL:

```text
http://127.0.0.1:8011/chat
```

Results:

```text
40 mode/viewport runs
desktop: 1440 x 900
mobile: 390 x 844
defects: 0
console errors: 0
network failures: 0
image failures: 0
horizontal overflow: 0
overlap or clipped-text defects: 0
```

The live SSE browser case was the separate input
`500 元内适合油敏肌的防晒`. It emitted 15 typed events.
`presentation_contract` arrived before the first message text, the thinking
panel started immediately and was removed on the first character, and both
inline and terminal card IDs were `[101, 26, 52]`.

The nickname comparison was additionally executed through the current real
HTTP runtime and interactive browser. Its separate evidence records
Canonical IDs `[129, 33]`, two inline images, two terminal cards, and no
terminal decision panel:

```text
docs/audits/semantic-transitions/alias-comparison-final-v1.json
```

Comparison terminal output contains no `对比判断` or `推荐思路` panel.

Evidence:

```text
docs/audits/frontend-integration/browser_closure_v1.json
docs/audits/frontend-integration/browser_closure.md
docs/audits/frontend-integration/screenshots/
```

## Automated Verification

Focused regression layers:

```text
alias / resolver / task planning: 551 passed
application / PendingTurn / SSE:  461 passed
runtime / HTTP / composition:      97 passed
```

Final full Guide suite:

```text
7876 passed
5 pre-existing warnings
507.85 seconds
```

Commands:

```bash
# Start the same local real-model runtime. The key file is local-only.
GUIDE_LLM_API_KEY="$(cat /private/tmp/xiaoro-deepseek-api-key)" \
GUIDE_LLM_BASE_URL=https://api.deepseek.com \
GUIDE_LLM_MODEL=deepseek-v4-pro \
GUIDE_COPY_LLM_API_KEY="$(cat /private/tmp/xiaoro-deepseek-api-key)" \
GUIDE_COPY_LLM_BASE_URL=https://api.deepseek.com \
GUIDE_COPY_LLM_MODEL=deepseek-v4-pro \
XIAORO_GUIDE_STATE_DIR=/tmp/xiaoro-fresh-real-model-state \
.venv/bin/uvicorn app.guide_runtime.app:app \
  --host 127.0.0.1 --port 8011

# Reproduce the current nickname comparison response.
curl --fail-with-body --silent --show-error --max-time 90 \
  -H 'Content-Type: application/json' \
  -d '{
    "message":"帮我对比兰蔻小黑瓶和小棕瓶",
    "session_id":"real-alias-comparison-replay",
    "conversation_version":0
  }' \
  http://127.0.0.1:8011/api/v1/chat/message \
  | jq '{
      intent:.intent.intent,
      product_ids:[.products[].product_id],
      visible_product_ids:.card_display_contract.visible_product_ids,
      conversation_version
    }'

# Reproduce the 128-case official TurnMeaning gate.
PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/run_real_turn_meaning_gate.py \
  --key-path /private/tmp/xiaoro-deepseek-api-key \
  --output-dir /tmp/xiaoro-turn-meaning-final

# Reproduce the 12-case presentation-copy gate.
PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/run_real_presentation_copy_gate.py \
  --key-path /private/tmp/xiaoro-deepseek-api-key \
  --run-id closure-replay \
  --output-dir /tmp/xiaoro-copywriter-final

# Focused alias, state-machine, persistence, HTTP, and frontend suites.
PYTHONPATH=. .venv/bin/pytest -q -c pytest-guide.ini \
  tests/guide/intent/test_task_planning.py \
  tests/guide/retrieval/test_controlled_product_aliases.py \
  tests/guide/retrieval/test_product_name_resolver.py \
  tests/guide/application/test_pending_turn.py \
  tests/guide/application/test_text_recommendation_flow.py \
  tests/guide/application/test_cross_worker_text_state.py \
  tests/guide/adapters/state/test_sqlite_conversation_state.py \
  tests/guide/runtime/test_runtime_http.py \
  tests/guide/runtime/test_frontend_presentation_history.py

# Recompute the 155-row alias review coverage and 118-row runtime subset.
PYTHONPATH=. .venv/bin/python \
  tools/guide_data/audit_product_aliases.py \
  --canonical data/canonical/core_products_v1.jsonl \
  --evidence \
    data/guide_product_evidence/product_evidence_v1.f3872a84388c7d5abfe73f8512d327f8294988daa46ed97823f961122370cb04.jsonl \
  --reviews data/canonical/product_alias_reviews_v1.jsonl \
  --legacy \
    /Users/bytedance/Desktop/xiaoro-shopping-master/app/services/intent.py \
  --legacy \
    /Users/bytedance/Desktop/xiaoro-shopping-master/app/services/agent.py \
  --legacy \
    /Users/bytedance/Desktop/xiaoro-shopping-master/app/services/v2/turn_parser.py \
  | jq '.report'

# Full, browser, compile, and diff gates used for this closure.
PYTHONPATH=. .venv/bin/pytest -q -c pytest-guide.ini tests/guide
PYTHONPATH=. .venv/bin/python \
  tools/guide_gates/frontend_presentation_browser_audit.py \
  --url http://127.0.0.1:8011/chat
PYTHONPATH=. .venv/bin/python -m compileall -q app tools
git diff --check
```

`compileall` and `git diff --check` passed. This is a dirty local worktree
closure, not a commit-based release record. No production deployment,
commit, push, or unrelated-worktree rollback was performed.

## Verdict

The nickname issue is closed as a catalog-wide reviewed identity system, not
as a two-word keyword patch. The final stale-reference defect was repaired
at the earliest remaining failure layer while preserving genuine reference
ambiguity.

```text
alias coverage: CLOSED
PendingTurn lifecycle: CLOSED
session deletion lifecycle: CLOSED
local real-model runtime: GREEN
desktop/mobile browser gate: GREEN
production deployment: NOT RUN
```
