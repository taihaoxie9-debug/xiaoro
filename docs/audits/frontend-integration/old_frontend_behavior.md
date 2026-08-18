# Old Frontend Behavior Audit

Date: 2026-08-16

Reference repository:
`/Users/bytedance/Desktop/xiaoro-shopping-master`

Target repository:
`/Users/bytedance/Desktop/xiaoro-fresh`

## Audit Rule

When target rendering behavior is unclear, inspect the exact old code, its
tests, and a browser screenshot. The old implementation is behavioral and
visual evidence, not business-logic authority.

## Superseded Presentation Conclusions

The previous closure verified the old contract rather than the final
user-approved product behavior. The final authority is
`docs/superpowers/specs/2026-08-16-guide-presentation-final-alignment-design.md`.

The final implementation corrects the historical assumptions:

- budget or skin revision reruns retrieval and remains product-bearing;
- ordinary merchant, review, citation, and product-evidence walls stay hidden;
- inline cards appear directly below product titles during structured output;
- full cards precede compact pitfalls;
- merged narrative atoms are covered at 80% or more;
- green change-summary chips do not appear in the answer.

## Preserve

### Visual shell

- rose, muted green-gray, and warm neutral palette;
- left history/collection sidebar;
- compact header and centered chat surface;
- user and assistant bubble alignment;
- fixed composer with image upload;
- recommendation-card visual language;
- inline product image/name/price component;
- typewriter answer effect;
- mobile sidebar and stacked card behavior.

### Answer rhythm

The old presenter uses:

```text
human conclusion
bounded product blocks
final how-to-choose advice
```

This rhythm remains the recommendation reference.

### Two product-card representations

The old page intentionally supports:

1. `buildInlineProductNode()` below the first primary product mention;
2. `displayProducts()` as the complete card shelf after the answer.

Both representations must bind the same product identity and image. They are
not an accidental duplicate.

### Pitfalls and evidence

`displayPitfalls()` keeps high-severity items distinct and renders ordinary
items compactly. Ordinary citations and detailed evidence remain in typed
audit state rather than rendering as a visible wall in the main answer.

## Preserve With Refinement

### Thinking process

The old `displayDecisionProcess()` establishes the transient pipeline idea,
but its nested step cards are visually heavy. The target keeps the same
palette, radius, type, and motion language while using one compact stable
container with a current-stage sentence and quiet progress markers.

The panel disappears at the first answer character and is not persisted.

### Non-recommendation layouts

Comparison, knowledge, consultation, and image flows reuse the same visual
grammar but receive mode-specific information architecture. They do not
reuse recommendation prose blindly.

### Structured section order

The old `display_sections` and `primary_product_ids` establish explicit
ordering and card identity. The target replaces loose dictionaries with a
strict mode-specific `presentation_contract`.

## Replace With Typed Contract

- `getProductsInContractOrder()` becomes exact
  `CardDisplayContract.visible_product_ids` binding.
- Markdown product-name discovery becomes explicit product slots.
- loose `display_sections` strings become a discriminated section union.
- old answer text plus `inline_images` becomes structured copy plus inline
  mini-card intents.
- event arrival order becomes validated typed SSE order.
- history snapshots persist typed presentation sections and card IDs.

## Reject

- default `78%` or other frontend-invented match scores;
- frontend ranking or winner inference;
- cards for products mentioned only in evidence/history;
- raw merchant OCR in main prose;
- old phrase dictionaries as the source of product decisions;
- duplicated full shelves or a third card for a later product mention;
- `innerHTML` rendering of model content;
- stale cards on clarification, error, consultation, or state-only turns.

## Mode/Card Summary

```text
recommendation: 1-3 inline mini cards + same final full cards
comparison: 2-4 compared inline mini cards + same final full cards
single product: 1 inline mini card + 1 final full card
product knowledge: bound product only
general knowledge: zero cards
focused follow-up: focused products only
budget or skin revision: complete rerun with 1-3 products
state-only follow-up: zero cards
image identity/recommendation: confirmed result products only
image suitability: one image-bound product
image comparison: image ordinal product order
consultation/clarification/error/medical escalation: zero cards
```

Later mentions of an already-rendered product become safe clickable
references that focus the existing card; they do not render another card.
