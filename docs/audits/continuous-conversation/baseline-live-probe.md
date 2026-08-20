# Continuous Conversation Live-Probe Baseline

Date: 2026-08-17

Repository: `/Users/bytedance/Desktop/xiaoro-fresh`

Branch: `rebuild`

Runtime:

```text
GUIDE_UNIFIED_ROUTER_ENABLED=true
real TurnMeaning provider=true
semantic calls=5
copywriter calls=0
format repair or retry=0
production deployment=false
```

## Five-Turn Trace

### Turn 1

The user described tight cheeks after cleansing, afternoon nose oiliness,
seasonal redness, a CNY 500 budget, a repair-serum goal, and a preference
against heavy texture.

Observed:

```text
processor=recommendation
card_ids=[91, 38]
terminal_version=1
```

Failure:

```text
public message exposed "texture.lightweight" and audit-style evidence wording
earliest layer=public_presentation
```

### Turn 2

The user asked for the second product's route, texture, and usage.

Observed:

```text
processor=followup
card_ids=[38]
terminal_version=2
```

Failure:

```text
the product was bound correctly, but reviewed texture and usage evidence was
missing; fallback was thin and retained recommendation-like closing duties
earliest layer=data_coverage, followed by public_presentation
```

### Turn 3

The user asked whether niacinamide and retinol were the same ingredient.

Observed:

```text
processor=general_knowledge
card_ids=[]
terminal_version=3
```

Failure:

```text
reviewed source documents existed, but retrieval returned no answer
earliest suspected layer=decision_execution
```

The implementation plan must reproduce the cross-language question-meaning
path before assigning the final earliest layer.

### Turn 4

The user asked to return to the earlier second product and judge suitability
given occasional stinging.

Observed:

```text
processor=clarification
card_ids=[]
terminal_version=4
```

Failure:

```text
the earlier product focus was not restored
earliest layer must be determined from TurnMeaning, admission, route, and
FocusState artifacts before editing code
```

### Turn 5

The user supplied the full product name and repeated the suitability question.

Observed:

```text
processor=product_knowledge/suitability
card_ids=[38]
terminal_version=5
```

Failure:

```text
public message exposed "Canonical" and did not directly answer the active
stinging condition
earliest layer=public_presentation
```

## Baseline Conclusion

The five turns proved that session versions advanced and several bindings and
mode switches worked. They also proved that component-level gates were not
sufficient for product-readiness. This baseline is frozen as the first
continuous-conversation regression and must not be repaired with observed
sentence branches or final string replacement.
