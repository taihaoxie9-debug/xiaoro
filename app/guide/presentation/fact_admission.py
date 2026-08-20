from typing import Literal


PresentationFactRole = Literal[
    "narrative",
    "direct_fact",
    "question_only",
    "caution",
]


_DIRECT_FACT_FIELDS = frozenset({
    "net_content",
    "spf_pa",
    "sun_protection_claim",
})

_QUESTION_ONLY_FIELDS = frozenset({
    "brand_research",
    "claimed_absences",
    "clinical_evidence",
    "color_count",
    "mechanism",
    "origin",
    "package_quantity",
    "reapplication",
    "shade",
    "shelf_life",
    "usage",
    "variant_option",
    "verified_absences",
})

_CAUTION_FIELDS = frozenset({
    "safety",
    "safety_claim",
})


def presentation_fact_role(field_key: str) -> PresentationFactRole:
    if not isinstance(field_key, str) or not field_key:
        raise ValueError("presentation fact field key must be nonempty")
    if field_key in _CAUTION_FIELDS:
        return "caution"
    if field_key in _DIRECT_FACT_FIELDS:
        return "direct_fact"
    if field_key in _QUESTION_ONLY_FIELDS:
        return "question_only"
    return "narrative"


__all__ = ["PresentationFactRole", "presentation_fact_role"]
