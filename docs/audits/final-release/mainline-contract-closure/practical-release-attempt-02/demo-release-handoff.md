# XiaoRo Guide Demo Handoff

## Decision

```text
Demo delivery: GO
Strict production release: NO_GO
```

The current candidate is suitable for a controlled product demonstration. It
is not approved as a zero-degradation production release.

## Candidate

```text
/Users/bytedance/Desktop/xiaoro-fresh/
  .tmp-task11-r5-seal-worktree
```

`/Users/bytedance/Desktop/xiaoro-shopping-master` is not this candidate and
was not modified.

## Verified Product Paths

- Real DeepSeek browser acceptance: 21/21 turns across seven three-turn
  trajectories.
- Exact-SSE mobile replay: 7/7 terminal streams match the accepted desktop
  bytes.
- Manual desktop/mobile screenshot review: 14/14 passed.
- Final affected regression after debug cleanup: 1129/1129.
- Text recommendation, comparison, product knowledge, image identity, image
  recommendation, and image comparison are connected through the unified
  route with preserved follow-up state.
- No sentence-specific, case-ID, or product-ID production branch was added.
- No retained `demo-runtime-error` or `image-fit-no-candidate` instrumentation
  remains in the shipped frontend or Guide application flow.

## Demo Policy

- Deterministic copywriter fallback is acceptable during a demo.
- The accepted 21-turn run used six fact-backed deterministic copy fallbacks;
  all six retained valid products, facts, and terminal contracts.
- A model-generated clarification may be answered or the request may be
  restated; it is not treated as data corruption.
- Wrong product binding, cross-session state leakage, unsafe advice, internal
  errors, or broken rendering remain stop conditions.
- Do not present this build as meeting the strict 14/14 zero-fallback
  production gate.

## Start

From the candidate directory:

```bash
export GUIDE_LLM_API_KEY="$(cat /Users/bytedance/Desktop/deepseek-key.txt)"
export GUIDE_LLM_BASE_URL="https://api.deepseek.com"
export GUIDE_LLM_MODEL="deepseek-v4-pro"
export GUIDE_LLM_FORMAT_REPAIR_ATTEMPTS="0"

export GUIDE_COPY_LLM_API_KEY="$GUIDE_LLM_API_KEY"
export GUIDE_COPY_LLM_BASE_URL="$GUIDE_LLM_BASE_URL"
export GUIDE_COPY_LLM_MODEL="$GUIDE_LLM_MODEL"

export XIAORO_GUIDE_STATE_DIR="/tmp/xiaoro-guide-demo-state"

/Users/bytedance/Desktop/xiaoro-fresh/.venv/bin/uvicorn \
  app.guide_runtime.app:app \
  --host 127.0.0.1 \
  --port 8835
```

Open `http://127.0.0.1:8835/chat`.

## Evidence

- Demo acceptance report:
  `../demo-real-acceptance/report.json`
- Real 21-turn desktop run:
  `../demo-real-acceptance/browser-desktop-final-08/summary.json`
- Exact-SSE mobile replay:
  `../demo-real-acceptance/browser-mobile-final-08/summary.json`
- Hash-bound 14-row visual review:
  `../demo-real-acceptance/manual-screenshot-review.json`
- Desktop contact sheet:
  `../demo-real-acceptance/desktop-terminal-contact-sheet-final-08.png`
- Mobile contact sheet:
  `../demo-real-acceptance/mobile-terminal-contact-sheet-final-08.png`
- Strict report: `practical-release-report.json`
- Translation: `real-translation/summary.json`
- Current backend replay:
  `real-backend-after-browser-contract-repair/summary.json`
- Final focused regression: `demo-final-focused.xml`
