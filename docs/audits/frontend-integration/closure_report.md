# Frontend Local Closure Report

Date: 2026-08-16

Status: `SUPERSEDED`

This report records the earlier frontend contract. It verified 18 modes,
older copywriter runs, visible evidence behavior, and the pre-alignment card
order. Those conclusions are historical evidence only.

Use
`docs/audits/frontend-integration/final-alignment-closure.md`
for the final user-approved contract and current verification results.

## Verdict

`SUPERSEDED-HISTORICAL-ONLY`

No production deployment or traffic switch was performed.

## Architecture

- Translator requests per semantic turn: at most 1.
- Presentation copywriter requests per eligible turn: at most 1.
- Repair, reviewer, retry, or third model request: 0.
- Ranking, product order, card visibility, state, safety, and hard facts
  remain code-owned.
- Copywriter failure or validation failure uses deterministic fallback.
- DeepSeek official and SiliconFlow translator/copywriter adapters are
  selected by their independent base URL configuration.

## Historical Copywriter Gates

Final immutable official runs:

| Run | Cases | Schema | Readability | Hard violations | Results SHA256 |
|---|---:|---:|---:|---:|---|
| `official-final-v3-1` | 12/12 | 100% | 100% | 0 | `cac49a3764a0912cc303792245062ac0bd233b8032cc90a2bdb7c13cecfae60d` |
| `official-final-v3-2` | 12/12 | 100% | 100% | 0 | `db857b9e48f474155088dc29e3958c7cd5c22368b7cd69778e77b0fe2bd15b17` |
| `official-final-v3-3` | 12/12 | 100% | 100% | 0 | `4965f58cfe3c2c55f679c5f8609fab8de2cdf968d89be4d373ee8cd0707d63da` |

All three outputs were replayed with the final validator and their
`SHA256SUMS` files were rechecked successfully.

## Product Images

- Canonical products: 103.
- Approved local card images: 103.
- Missing: 0.
- Broken: 0.
- Mismatched: 0.
- Canonical seed changed: false.

Evidence:
`docs/audits/frontend-integration/product_image_inventory_v1.json`.

## Historical Browser Closure

- Mode runs: 36 (`18 modes x 2 viewports`).
- Desktop viewport: `1440x900`.
- Mobile viewport: `390x844`.
- Console errors: 0.
- Network failures: 0.
- Required image failures: 0.
- Horizontal overflow defects: 0.
- Sibling overlap defects: 0.
- Clipped text defects: 0.
- Card mismatch, omission, or third duplicate: 0.
- Thinking pipeline started immediately and was removed after the first
  answer character.
- Locked visual-shell drift: 0.

The live configured recommendation emitted:

```text
start -> stage -> intent -> stage -> stage -> merchant_claims
-> review_evidence -> decision_process -> answer_contract
-> card_display_contract -> products -> product_evidence
-> presentation_contract -> message -> feedback_target -> end
```

Visible inline/full card IDs were identical: `[55, 57, 54]`.

Evidence:

- `docs/audits/frontend-integration/browser_closure.md`
- `docs/audits/frontend-integration/browser_closure_v1.json`
- `docs/audits/frontend-integration/screenshots/`

## Historical Regression

- Focused presentation/frontend suites: `192 passed`.
- Runtime/application/state/presentation suite: `1561 passed`.
- Final Guide full suite: `7775 passed`, 5 pre-existing warnings.
- Architecture/import boundaries: `25 passed`.
- `python -m compileall -q app tools`: passed.
- `git diff --check`: passed.

The full-suite failures found during the first run were fixed and replayed
before the final green run:

- exact locked-text validation no longer treats ordinary verified category
  words as global bans;
- official DeepSeek translator configuration selects the DeepSeek adapter;
- frontend category fields validate against the backend registry while
  rendering a bounded profile-specific subset;
- referenced follow-up and product-knowledge turns bind exactly the named
  product rather than suppressing all cards.

## Process Boundary

- Local-only audit URL during verification:
  `http://127.0.0.1:8772/chat`.
- No production configuration was modified.
- No secret value is stored in repository artifacts.
- No unrelated dirty file was staged.
