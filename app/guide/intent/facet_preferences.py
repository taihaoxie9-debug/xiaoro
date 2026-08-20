from __future__ import annotations

import unicodedata

from app.guide.understanding.contracts import PreferenceDraft
from app.guide.understanding.semantic_contracts import (
    SemanticPreferenceCandidate,
    SemanticPreferenceField,
)


_FIELD_KEY = {
    SemanticPreferenceField.TEXTURE: "texture",
    SemanticPreferenceField.FRAGRANCE_DESCRIPTION: "fragrance_description",
    SemanticPreferenceField.FINISH: "finish",
    SemanticPreferenceField.BRAND: "brand",
    SemanticPreferenceField.EFFICACY: "efficacy",
    SemanticPreferenceField.SUITABLE_SKIN: "suitable_skin",
    SemanticPreferenceField.SKIN_CONCERN: "skin_concern",
    SemanticPreferenceField.USAGE_CONTEXT: "usage_context",
    SemanticPreferenceField.INGREDIENT_PRESENCE: "ingredients_present",
    SemanticPreferenceField.INGREDIENT_EXCLUSION: "verified_absences",
}

_VALUE_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "finish": {
        "哑光": ("哑光", "雾面", "柔雾", "丝绒", "磨砂"),
        "自然": ("自然", "裸妆", "清透", "通透", "贴肤", "不假面"),
        "光泽": ("光泽", "水光", "奶油肌", "玻璃肌", "柔光"),
    },
    "texture": {
        "清爽": ("清爽", "不油腻", "不闷", "轻薄", "水感"),
        "滋润": ("滋润", "水润", "润泽"),
        "霜状": ("霜状", "乳霜", "膏状"),
        "油状": ("油状", "精华油", "洁颜油"),
    },
}
_INGREDIENT_OPERATION_PREFIXES = (
    "绝对不能有",
    "严禁含有",
    "不能有",
    "不可含",
    "不要含",
    "不要有",
    "不含",
    "排除",
)
_INGREDIENT_OPERATION_SUFFIXES = ("不耐受", "过敏")


def preference_draft_for_candidate(
    candidate: SemanticPreferenceCandidate,
) -> PreferenceDraft | None:
    field_key = _FIELD_KEY[candidate.field]
    raw_value = _normalize(candidate.raw_text)
    if candidate.field is SemanticPreferenceField.INGREDIENT_EXCLUSION:
        raw_value = _strip_ingredient_operation(raw_value)
    if not raw_value:
        return None
    if field_key in _VALUE_ALIASES:
        canonical = canonical_facet_values(field_key, raw_value)
        if len(canonical) != 1:
            return None
        raw_value = next(iter(canonical))
    return PreferenceDraft(field_key=field_key, value=raw_value)


def canonical_facet_values(
    field_key: str,
    value: str,
) -> frozenset[str]:
    normalized = _normalize(value)
    aliases = _VALUE_ALIASES.get(field_key)
    if aliases is None:
        return frozenset({normalized})
    matched = {
        canonical
        for canonical, values in aliases.items()
        if any(_normalize(alias) in normalized for alias in values)
    }
    return frozenset(matched or {normalized})


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold().strip()


def _strip_ingredient_operation(value: str) -> str:
    for prefix in _INGREDIENT_OPERATION_PREFIXES:
        if value.startswith(prefix):
            value = value[len(prefix):].strip()
            break
    for suffix in _INGREDIENT_OPERATION_SUFFIXES:
        if value.endswith(suffix):
            value = value[:-len(suffix)].strip()
            break
    return value


__all__ = [
    "canonical_facet_values",
    "preference_draft_for_candidate",
]
