# Guide Presentation Final Alignment Closure

Date: 2026-08-16

Repository: `/Users/bytedance/Desktop/xiaoro-fresh`

Branch: `rebuild`

Status: `FRONTEND-LOCAL-GO`

Authority:
`docs/superpowers/specs/2026-08-16-guide-presentation-final-alignment-design.md`

No production deployment, traffic switch, or production configuration change
was performed.

## Product Contract

- An explicit budget maximum remains a hard boundary and becomes only the
  final soft key among otherwise equivalent candidates.
- Approved merchant facts are merged into bounded narrative atoms.
- The copywriter must use at least 80% of each product's atoms; invalid output
  falls back locally without a retry or third model call.
- Code owns selection, order, state, safety, price, specification,
  ingredients, numeric proof points, warnings, and product/card identity.
- Recommendation and revision use the full summary, product blocks, closing,
  full-card shelf, and compact-pitfall structure.
- Missing optional facts remove their rows instead of rendering placeholders.
- Product titles are followed immediately by one inline image card during the
  structured stream.
- The thinking panel starts from typed stage events, leaves on the first answer
  character, and is removed from the DOM after 320 ms.
- Ordinary evidence walls and green change-summary chips are absent.
- Unconfirmed image identity fails closed with zero product cards.

## Regression

- Final focused presentation suite: `415 passed`.
- Final full repository suite: `7807 passed`, `5 warnings`, `0 failed`.
- Frontend browser contract: `4 passed`.
- `git diff --check`: passed.

The five warnings are pre-existing:

- one Pydantic protected-namespace warning for `model_name`;
- four invalid-escape deprecation warnings in two legacy scripts.

## Official Copywriter Gates

All runs used provider `deepseek_official`, model `deepseek-v4-pro`, and made
exactly one provider call per case.

| Run ID | Cases | Schema | Readability | Fact coverage | Internal language | Hard violations | Results SHA256 |
|---|---:|---:|---:|---:|---:|---:|---|
| `final-alignment-1-fixed` | 12/12 | 100% | 100% | 100% | 100% | 0 | `5c10ab7f3f759fc4fa21b25b1e41e7584bfd7c16edb98d2ea04240f0849677f7` |
| `final-alignment-2` | 12/12 | 100% | 100% | 100% | 100% | 0 | `24e45275adcdfaecf11a021616396458b07e1976bdf1551c79afff3ddbe72175` |
| `final-alignment-3-fixed` | 12/12 | 100% | 100% | 100% | 100% | 0 | `037e4bf1c50aefecbc6d36c0c9aaa15b51835f4805f4ccfe306d5879f06263b3` |

Each run's `SHA256SUMS` file was rechecked successfully. The non-fixed
`final-alignment-1` and `final-alignment-3` directories remain immutable
diagnostic evidence and are not counted as passing gates.

## Browser Acceptance

Local URL: `http://127.0.0.1:8780/chat`

- Desktop: 20 scenarios at `1440x900`.
- Mobile: 20 scenarios at `390x844`.
- Total mode runs: 40.
- Console errors: 0.
- Relevant network failures: 0.
- Image failures: 0.
- Horizontal overflow, overlap, and clipped-text defects: 0.
- Visual-shell drift: 0.
- Inline/full card identity mismatches or third cards: 0.
- Product 26 renders as `兰蔻（LANCOME） 防晒`, not the unusable canonical
  placeholder.

The live SSE sequence was:

```text
start -> stage -> intent -> stage -> stage -> merchant_claims
-> decision_process -> answer_contract -> card_display_contract
-> products -> product_evidence -> presentation_contract -> message
-> feedback_target -> end
```

The live recommendation bound identical inline and full card IDs:
`[101, 26, 52]`. The thinking panel started immediately and was absent after
the first answer character.

Evidence:

- `docs/audits/frontend-integration/browser_closure_v1.json`
- `docs/audits/frontend-integration/browser_closure.md`
- `docs/audits/frontend-integration/screenshots/`

The browser app uses the production FastAPI, decision, presentation, SSE, and
frontend paths with a deterministic local semantic port because no local
`GUIDE_LLM_API_KEY` is configured. Real external copywriter behavior is
covered separately by the three official gates above.

## Product Images

- Canonical products: 103.
- Approved and decodable card images: 103.
- Missing: 0.
- Broken: 0.
- Identity mismatches: 0.
- Canonical seed changed: false.

Evidence:
`docs/audits/frontend-integration/product_image_inventory_v1.json`.

## Process Boundary

- Work remains local.
- No production deployment was attempted.
- No secret value is stored in audit artifacts.
- Existing unrelated dirty-worktree changes were not reverted or staged.
