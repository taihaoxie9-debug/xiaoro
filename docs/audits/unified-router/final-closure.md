# Unified Guide Router Final Closure

Status: Superseded for product-readiness

The component evidence below remains valid, but product-readiness now follows
`docs/superpowers/specs/2026-08-17-continuous-conversation-acceptance-design.md`.
The replacement gate requires 20 real five-turn backend conversations and a
3-conversation browser sample.

Date: 2026-08-17

Repository: `/Users/bytedance/Desktop/xiaoro-fresh`

Branch: `rebuild`

## Result

The local pre-launch closure passes. Unified Router V1 remains reversible,
all zero-tolerance counters are zero, the latest complete test suite passes,
and the desktop/mobile browser matrix has no recorded defect.

No production deployment occurred.

## Automated Evidence

| Gate | Current result | Evidence |
|---|---:|---|
| Focused Guide regression | 4,759 passed | `tests/guide/{intent,feedback,application,presentation,runtime}` |
| Complete pytest | 8,174 passed, 5 existing warnings | `.venv/bin/python -m pytest -q` |
| Lifecycle invariants | 10 passed | restart, cross-worker, CAS, isolation, disconnect, delete |
| Offline replay | 16/16, 100% | `unified_router_offline_v1.jsonl` |
| Captured real smoke replay | 39/40, 97.5% | `real-smoke-v10-final-replay.json` |
| Captured blind A replay | 97/100, 97% | `blind-a-v4-prompt-v10-final-replay.json` |
| Captured blind B replay | 99/100, 99% | `blind-b-v5-prompt-v10-final-replay.json` |
| Browser mode matrix | 40/40, 0 defects | `browser-closure-v1.json` |
| Browser report contract | 4 passed | `test_frontend_browser_contract.py` |

The five existing warnings are one Pydantic protected-namespace warning and
four invalid `\d` escape warnings in legacy scripts. No new warning category
was introduced.

## Model Gates

The accepted real-model captures used TurnMeaning Prompt V10 and no
copywriter:

| Gate | Provider calls in capture | Rate | Lowest category | Zero-tolerance violations |
|---|---:|---:|---:|---:|
| Smoke | 40 | 97.5% | 85.7% | 0 |
| Blind A | 100 | 97% | 85.7% | 0 |
| Blind B | 100 | 99% | 92.3% | 0 |

The final replays used the captured provider outputs with:

```text
provider_call_count = 0
copywriter_call_count = 0
```

Remaining misses are all classified at `model_translation`:

- smoke: `offline-return-product-focus-001`;
- blind A: `blind-a4-nh-friend-005`, `blind-a4-nh-safety-007`,
  `blind-a4-ctx-return-004`;
- blind B: `blind-b5-nh-product-007`.

No narrow phrase patch was added for these misses. All accepted thresholds
remain satisfied.

## Zero-Tolerance Counters

Every final captured replay records:

```text
wrong_product_selection_count = 0
unauthorized_state_transition_count = 0
hard_condition_override_count = 0
unsafe_downgrade_count = 0
cross_session_leak_count = 0
```

## Browser Closure

The refreshed local matrix covers 20 modes at both `1440x900` and `390x844`.
It records zero console errors, network failures, image failures, horizontal
overflow, overlaps, clipped text, extra cards, or comparison-table
mismatches.

The local SSE audit confirms:

```text
one semantic translation
zero copywriter calls
zero third-model calls
presentation contract before message
thinking visible immediately
thinking removed on the first answer character
```

Separate Unified Router probes cover pure and constrained image similarity,
two- and three-image comparison, dynamic consultation correction and
confirmation, consultation exit, clarification, no match, active-damage
escalation, and unconfirmed image identity. See
`docs/audits/unified-router/browser-closure-v1.json`.

## Lifecycle Closure

The focused lifecycle run proves:

- SQLite restart preserves focus;
- a second worker continues the first worker's conversation;
- stale focus and terminal commits are rejected by CAS;
- `PendingTurn` is isolated between two sessions;
- disconnect before terminal delivery does not commit;
- wrong-owner deletion changes nothing;
- valid deletion removes the complete session snapshot;
- deletion is idempotent in both SQLite and memory adapters.

## Feature Flag And Rollback

Acceptance configuration:

```bash
GUIDE_UNIFIED_ROUTER_ENABLED=true
```

Local rollback:

```bash
GUIDE_UNIFIED_ROUTER_ENABLED=false \
  .venv/bin/python -m uvicorn app.guide_runtime.app:app \
  --host 127.0.0.1 --port 8011
```

Disabling the flag returns routing to the established owner flows. Canonical
identity, specification projection, product data, and presentation fixes
remain shared.

## Authoritative Hashes

| Artifact | SHA-256 |
|---|---|
| `app/guide/application/unified_guide_flow.py` | `f5d808d20c3690aae06ba0c70198a14bc4144a09820d4d32051b956296327c5b` |
| `app/guide/intent/unified_turn_router.py` | `0fea50ec08024cc8e992ff231244ee3434ef39ac0d55614e6e97f90f933b5a55` |
| `app/guide/application/dynamic_consultation.py` | `3eeb06037b150ee94309852bc9c1ecdd7f3f2743be49476ccf16672a65b0a658` |
| `app/guide/application/image_recommendation_flow.py` | `9233984362168b68f7dda1a237c43ec0895c61a0a993a8eb46c72eb1d5e6ba06` |
| `app/static/guide-presentation.js` | `ed426696cf737dbdf4b70976c4fef65926de0873b4c36575d849c1079cbbec56` |
| `app/static/chat.html` | `4d71a2ddbf0072eeac32f314e628af47067e338891a32c1577a6893b3a9b14cf` |
| `core_products_v1_manifest.json` | `e0430a244af451a3fa73642295c4a79128e1622dfeed19ff8140eda9f2df0c69` |
| `controlled_product_aliases_v1_manifest.json` | `a0a2aa7e128bb01c4bc6a6b99e6cef5f4bc841cee105a73e0f07bf7a32df8e1a` |
| `product_evidence_v1_manifest.json` | `65346adce169291f74acab6d3c9c31b2e98c6db960a6901d4c6b426f6a4f0b47` |
| `selection_concepts_v1_manifest.json` | `216db6ee39e0a05d50483e1f38f90d723fca6eb9191bcbabe8c0cf73738af0df` |
| `browser_closure_v1.json` | `b280d067ee7262b67dff40e02133743f15a4d4fbed7391c5dde46bcdd96a1552` |

## Final Completion Audit

| Required item | Status | Direct evidence |
|---|---|---|
| Specification projection | PASS | card specification suites and full pytest |
| Exact variant binding | PASS | resolver/specification suites and full pytest |
| Mode-specific presentation | PASS | 40-run browser matrix |
| Session-only profile | PASS | profile, consultation, deletion suites |
| Focus switching | PASS | router replay and cross-worker focus tests |
| Router flag parity | PASS | runtime flag suites and rollback command |
| Dynamic consultation | PASS | focused regression and browser trajectory |
| Image routing | PASS | image suites and browser probes |
| Offline replay | PASS | 16/16 |
| Real smoke | PASS | 39/40, 97.5% |
| Blind batch A | PASS | 97/100 |
| Blind batch B | PASS | 99/100 |
| Full pytest | PASS | 8,174 passed |
| Desktop browser | PASS | 20/20 mode runs |
| Mobile browser | PASS | 20/20 mode runs |
| SSE lifecycle | PASS | terminal delivery and disconnect tests |
| Owner/session isolation | PASS | focused lifecycle run |
| Session deletion | PASS | runtime, SQLite, and memory deletion tests |
| No deployment | PASS | local-only execution; production untouched |
