# Presentation Slot Responsibility Audit v1

## Scope

Repository: `/Users/bytedance/Desktop/xiaoro-fresh`

This audit follows approved production facts through:

```text
source asset
-> typed authority/capability
-> ProductCard or approved soft fact
-> PresentationPacket slot
-> compiled section
-> frontend renderer
```

It does not treat a field-name whitelist as evidence authority.

## Production Inventory

The machine-readable inventory is:

```text
docs/audits/continuous-conversation/presentation-fact-admission-v1.json
```

Current counts:

| Source | Count | Result |
|---|---:|---|
| Published merchant claims | 1129 across 98 products | 762 positioning, 23 direct, 240 question-only, 103 cautions, 1 excluded |
| Known Category/Canonical facts | 546 | all have source refs |
| Approved consumer reviews | 6 across products 42, 49, 55 | now eligible for `consumer_report` slots |

The only excluded published merchant claim is:

```text
product 55 / finish / "透气贴妆不闷痘"
reason = safety_guarantee
```

The normal part is covered by separate approved texture facts. The
`不闷痘` guarantee is not published as an objective fact.

Machine gates:

```text
field_whitelist_only_drop_count = 0
direct_fact_unresolved_count = 0
unexplained_drop_count = 0
missing_source_ref_count = 0
```

## Authority Policy

`presentation_fact_role()` assigns placement after upstream review:

| Role | Meaning |
|---|---|
| `narrative` | Normal approved purchase information may enter positioning. New approved field keys default here rather than disappearing. |
| `direct_fact` | Exact values such as SPF/PA and unresolved net content are rendered by code, not paraphrased. |
| `question_only` | Usage, mechanism, clinical evidence, origin, shelf life, shade families, and similar detail are available when the user asks; they do not flood ordinary recommendations. |
| `caution` | Safety transcripts remain code-owned warnings. |

This is placement policy, not a second evidence review. Upstream
`capabilities`, source refs, product ownership, and review status remain the
authority.

## Fixed Shared Defects

### ProductCard projection

Before this audit, recommendation used direct Canonical fields while
follow-up, product knowledge, image identity, image suitability, and image
comparison rebuilt thinner cards.

All production paths now use:

```python
build_product_card(
    facts,
    skin_match=...,
    matched_efficacies=...,
)
```

The shared projector merges known:

```text
efficacy
ingredients_present
suitable_skin
```

It does not decide mode, order, suitability, or winner status.

### Approved numeric facts

The validator now authorizes exact numeric fragments from any same-slot
approved fact, not only `efficacy` and `ingredients_present`.

Covered examples:

```text
24小时
35.97%
1瓶
维生素原B5
```

Changing them to `48小时`, `53.97%`, `2瓶`, or `B6` still fails.

### Direct protection facts

Known `spf_pa` is now a direct fact and never free copy. Exact specification
is combined with reference price; a matching net-content row is not repeated.

### Consumer reports

Approved review summaries previously existed only in SSE evidence. Safe,
source-bound review quotes now enter the same product's copy slot with:

```text
attribution = consumer_report
public prefix = 限定样本的用户反馈
```

The copywriter must preserve this attribution. Review text containing an
absolute safety claim or unsupported winner language remains filtered.

## Slot Ownership

| Slot | Input | Frontend responsibility |
|---|---|---|
| `summary` | Overall route/tradeoff copy | Introductory paragraph |
| `positioning` | Approved narrative atoms, including merchant and consumer attribution | Brand positioning paragraph |
| `direct_facts` | Price/spec, known ingredients/skin, SPF and other exact code-owned facts | Definition-list rows |
| `advisor_reason` | Relationship to current need, skin, budget, or scenario | `小 ro 的推荐理由：` |
| `closing` | Final choice and scenario switch | `综合推荐` |
| `pitfalls` | Typed cautions | Compact warnings after full shelf |

Product knowledge suppresses advisor reason and closing. General knowledge
has zero product slots. Medical escalation and clarification remain
deterministic.

The complete mode contract is:

```text
docs/audits/continuous-conversation/presentation-mode-matrix-v2.json
```

## Verification

Focused suites:

```text
400 passed
```

They cover:

```text
presentation contracts and compiler
text recommendation and product knowledge
follow-up cards
image identity/suitability/comparison
approved numeric and alphanumeric facts
production fact-admission audit
consumer review packet ownership
```

## Remaining Gates

This audit closes backend slot responsibility. It does not yet claim final
qualification.

Still required:

1. frontend single-owner and final G-format audit;
2. production-data copywriter v6 real gate with at least 18/20 usable and zero
   hard violations;
3. browser verification that data-rich products visibly retain at least three
   complementary approved dimensions;
4. full repository regression.
