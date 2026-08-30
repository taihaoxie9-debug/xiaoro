from __future__ import annotations

from dataclasses import dataclass
import unicodedata

from app.guide.understanding.knowledge_relation_contracts import (
    KnowledgeRelationIntent,
)


@dataclass(frozen=True, slots=True)
class KnowledgeAliasMatch:
    identifier: str
    raw_text: str
    start: int
    end: int


_ENTITY_ALIASES: dict[str, tuple[str, ...]] = {
    "ingredient.niacinamide": (
        "烟酰胺",
        "维生素B3",
        "niacinamide",
    ),
    "ingredient.retinol": (
        "A 醇",
        "维A醇",
        "视黄醇",
        "retinol",
        "维A",
        "A醇",
    ),
    "ingredient.vitamin_c": (
        "ascorbic acid",
        "vitamin C",
        "抗坏血酸",
        "维生素C",
        "维 C",
        "维C",
        "VC",
    ),
    "ingredient.salicylic_acid": (
        "salicylic acid",
        "水杨酸",
        "BHA",
    ),
    "ingredient.acid": (
        "酸类",
        "刷酸",
        "果酸",
        "AHA",
    ),
    "ingredient.proxylane": (
        "羟丙基四氢吡喃三醇",
        "pro-xylane",
        "玻色因",
    ),
    "ingredient.peptide": (
        "peptides",
        "peptide",
        "多肽",
        "胜肽",
        "肽类",
        "肽",
    ),
}

_CONCEPT_ALIASES: dict[str, tuple[str, ...]] = {
    "skin.sensitive": ("敏感肤质", "敏感皮肤", "敏感肌", "干敏肌", "油敏肌"),
    "skin.oily": ("混油皮", "大油田", "油性皮肤", "油皮"),
    "skin.dry": ("干性皮肤", "干敏肌", "干皮"),
    "skin.acne_prone": ("痘痘肌", "痘肌", "闭口", "爆痘"),
    "skin.barrier_damaged": (
        "皮肤屏障受损",
        "屏障受损",
        "屏障损伤",
    ),
    "category.sunscreen": ("防晒霜", "防晒乳", "防晒"),
    "category.serum": ("精华液", "精华"),
    "category.moisturizer": ("保湿霜", "乳液", "面霜"),
    "category.cleanser": ("洗面奶", "洁面"),
    "category.makeup_remover": (
        "卸妆油",
        "卸妆水",
        "卸妆膏",
        "卸妆",
    ),
    "category.eye_care": ("眼部精华", "眼霜"),
    "category.mask": ("医用敷料", "敷料", "面膜"),
    "category.base_makeup": ("粉底液", "气垫", "底妆", "粉底"),
    "category.setting_makeup": (
        "定妆喷雾",
        "散粉",
        "粉饼",
        "定妆",
    ),
    "category.lip_makeup": (
        "口红",
        "唇膏",
        "唇釉",
        "唇泥",
        "唇妆",
    ),
    "category.fragrance": ("香水", "香氛"),
    "concern.anti_aging": ("抗初老", "抗衰老", "抗老", "淡纹", "抗皱"),
    **_ENTITY_ALIASES,
}

_CONCEPT_PARENTS = {
    identifier: identifier.split(".", 1)[0]
    for identifier in _CONCEPT_ALIASES
}

_RELATION_MARKERS: dict[
    KnowledgeRelationIntent,
    tuple[str, ...],
] = {
    "difference": ("区别", "差别", "一回事"),
    "compatibility": (
        "一起使用",
        "一起用",
        "早C晚A",
        "同用",
        "叠加",
        "搭配",
        "冲突",
    ),
    "mechanism": ("为什么", "作用", "原理", "是什么"),
    "usage": (
        "怎么修护",
        "如何修护",
        "怎么安排",
        "怎么用",
        "白天",
        "晚上",
        "顺序",
        "频率",
        "补涂",
        "耐受",
    ),
    "selection": ("如何选择", "怎么选", "选择", "适合"),
    "identification": ("如何判断", "怎么判断"),
    "safety": (
        "哺乳期",
        "孕期",
        "刺痛",
        "爆皮",
        "破皮",
        "严重",
        "避开",
        "避雷",
        "注意",
    ),
}


def _compact_with_spans(value: str) -> tuple[str, tuple[tuple[int, int], ...]]:
    compact: list[str] = []
    spans: list[tuple[int, int]] = []
    for index, character in enumerate(value):
        normalized = unicodedata.normalize("NFKC", character).casefold()
        for item in normalized:
            if item.isspace():
                continue
            compact.append(item)
            spans.append((index, index + 1))
    return "".join(compact), tuple(spans)


def _compact(value: str) -> str:
    return _compact_with_spans(value)[0]


def _has_ascii_boundary(
    text: str,
    *,
    start: int,
    end: int,
    alias: str,
) -> bool:
    if not alias.isascii():
        return True
    before = text[start - 1] if start else ""
    after = text[end] if end < len(text) else ""
    return not (
        (before.isascii() and before.isalnum())
        or (after.isascii() and after.isalnum())
    )


def _match_aliases(
    value: str,
    aliases_by_id: dict[str, tuple[str, ...]],
) -> tuple[KnowledgeAliasMatch, ...]:
    if not isinstance(value, str):
        raise TypeError("knowledge alias source must be a string")
    compact, spans = _compact_with_spans(value)
    selected: dict[str, KnowledgeAliasMatch] = {}
    for identifier, aliases in aliases_by_id.items():
        candidates: list[KnowledgeAliasMatch] = []
        for alias in aliases:
            normalized_alias = _compact(alias)
            start = compact.find(normalized_alias)
            if start < 0:
                continue
            end = start + len(normalized_alias)
            raw_start = spans[start][0]
            raw_end = spans[end - 1][1]
            if not _has_ascii_boundary(
                compact,
                start=start,
                end=end,
                alias=normalized_alias,
            ):
                continue
            candidates.append(
                KnowledgeAliasMatch(
                    identifier=identifier,
                    raw_text=value[raw_start:raw_end],
                    start=raw_start,
                    end=raw_end,
                )
            )
        if candidates:
            selected[identifier] = min(
                candidates,
                key=lambda item: (
                    item.start,
                    -(item.end - item.start),
                    item.raw_text.casefold(),
                ),
            )
    return tuple(
        sorted(
            selected.values(),
            key=lambda item: (
                item.start,
                -(item.end - item.start),
                item.identifier,
            ),
        )
    )


def match_knowledge_entities(
    value: str,
) -> tuple[KnowledgeAliasMatch, ...]:
    return _match_aliases(value, _ENTITY_ALIASES)


def match_knowledge_concepts(
    value: str,
) -> tuple[KnowledgeAliasMatch, ...]:
    return _match_aliases(value, _CONCEPT_ALIASES)


def concept_lineage(concept_id: str) -> tuple[str, ...]:
    if not isinstance(concept_id, str) or not concept_id:
        raise ValueError("knowledge concept ID must be nonempty")
    parent = _CONCEPT_PARENTS.get(concept_id)
    if parent is None:
        if "." not in concept_id:
            return (concept_id,)
        raise ValueError(f"unknown knowledge concept ID: {concept_id}")
    return (parent, concept_id)


def explicit_knowledge_relations(
    value: str,
) -> tuple[KnowledgeRelationIntent, ...]:
    if not isinstance(value, str):
        raise TypeError("knowledge relation source must be a string")
    normalized = unicodedata.normalize("NFKC", value).casefold()
    matches: list[tuple[int, KnowledgeRelationIntent]] = []
    for relation, markers in _RELATION_MARKERS.items():
        positions = [
            normalized.find(
                unicodedata.normalize("NFKC", marker).casefold()
            )
            for marker in markers
        ]
        found = [position for position in positions if position >= 0]
        if found:
            matches.append((min(found), relation))
    return tuple(
        relation
        for _, relation in sorted(
            matches,
            key=lambda item: (item[0], item[1]),
        )
    )


__all__ = [
    "KnowledgeAliasMatch",
    "concept_lineage",
    "explicit_knowledge_relations",
    "match_knowledge_concepts",
    "match_knowledge_entities",
]
