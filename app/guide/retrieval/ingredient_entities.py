from __future__ import annotations

import unicodedata


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold().strip()


_INGREDIENT_ENTITY_ALIASES = {
    "酒精": frozenset({"酒精", "乙醇", "alcohol"}),
    "香精": frozenset({"香精", "fragrance", "parfum", "perfume"}),
    "色素": frozenset({"色素", "colorant", "colourant"}),
    "矿油": frozenset({"矿油", "矿物油", "mineral oil"}),
    "尼泊金酯类防腐剂": frozenset({
        "尼泊金酯类防腐剂",
        "paraben",
        "parabens",
    }),
    "防腐剂": frozenset({"防腐剂", "preservative", "preservatives"}),
}

_CANONICAL_BY_ALIAS = {
    _normalize(alias): canonical
    for canonical, aliases in _INGREDIENT_ENTITY_ALIASES.items()
    for alias in aliases
}


def normalize_ingredient_entity(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("ingredient entity must be nonempty")
    normalized = _normalize(value)
    return _CANONICAL_BY_ALIAS.get(normalized, normalized)


def ingredient_entities_match(left: str, right: str) -> bool:
    return normalize_ingredient_entity(left) == normalize_ingredient_entity(
        right
    )


__all__ = [
    "ingredient_entities_match",
    "normalize_ingredient_entity",
]
