# Copywriter Architecture Checkpoint

Date: 2026-08-16

## Status

The checkpoint was triggered after two consecutive official gate reports did
not meet admission.

The first report had no hard violation. Two concise but useful product
positioning lines were rejected by a per-field length threshold. Replaying
the saved output proved the rubric was too strict; the affected threshold
was reduced without changing the Prompt.

The next report exposed two architecture issues:

1. a package caution was copied verbatim into free-form closing copy, while
   the production validator only checked generic numeric, ingredient, and
   safety patterns;
2. product and knowledge packets required a closing section, but the Prompt
   did not expose section order and globally said `closing_copy` could be
   null.

Classification:

- fixture truth: valid;
- `PresentationPacket`: complete, but its required section shape was omitted
  from the copywriter payload;
- validator: incomplete for exact locked facts and caution text;
- copywriter responsibility: unchanged;
- provider schema stability: acceptable.

Approved general fix:

- expose required section shape to the copywriter;
- require closing copy whenever the packet contains a closing section;
- reject exact locked facts and caution text in every free-form copy field.
- preserve consumer attribution in the packet's Chinese `plain_meaning`
  (`限定样本的用户反馈：...`) instead of relying on an English enum alone.
- treat the ordinary marketing verb `主打` as merchant attribution while
  continuing to reject unqualified objective claims.

No product-specific or sentence-specific Prompt patch is permitted.

## Locked Responsibility Boundary

- `TurnMeaning` remains the only semantic translation call.
- Code owns product binding, state, retrieval, filtering, safety, ranking,
  product order, card visibility, and hard facts.
- The presentation copywriter receives only the approved
  `PresentationPacket`.
- Every eligible case permits exactly one copywriter request.
- Invalid schema, provider failure, or factual overreach goes directly to the
  deterministic fallback. There is no repair, reviewer, retry, or third
  model call.

## Gate Interpretation

The gate separates:

1. schema validity;
2. slot and approved-fact grounding;
3. hard-atom, winner-language, and attribution violations;
4. basic readability and usefulness.

Wording, punctuation, sentence order, and ordinary advisor paraphrases are
explicitly don't-care dimensions. No exact paragraph is used as a golden
answer.

## Escalation Rule

If two official runs fail in the same layer, stop prompt tuning and classify
the failure as one of:

- fixture truth is false;
- `PresentationPacket` lacks an approved fact;
- the validator is too strict;
- the copywriter owns too much;
- provider schema stability is insufficient.

Only one general architectural fix may follow that classification. Saved
provider output must be replayed offline before another paid run.
