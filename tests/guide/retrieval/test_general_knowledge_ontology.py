from __future__ import annotations

import pytest

from app.guide.retrieval.general_knowledge_ontology import (
    concept_lineage,
    explicit_knowledge_relations,
    match_knowledge_concepts,
    match_knowledge_entities,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        ("A醇怎么用", ("ingredient.retinol",)),
        ("A 醇怎么用", ("ingredient.retinol",)),
        ("retinol怎么用", ("ingredient.retinol",)),
        ("维C白天能不能用", ("ingredient.vitamin_c",)),
        ("VC白天能不能用", ("ingredient.vitamin_c",)),
        ("抗坏血酸白天能不能用", ("ingredient.vitamin_c",)),
        ("烟酰胺有什么作用", ("ingredient.niacinamide",)),
    ),
)
def test_raw_aliases_resolve_canonical_entities(
    raw: str,
    expected: tuple[str, ...],
) -> None:
    matches = match_knowledge_entities(raw)

    assert tuple(item.identifier for item in matches) == expected
    assert all(item.raw_text in raw for item in matches)


def test_entity_matches_preserve_user_order_and_longest_alias() -> None:
    raw = "先看维生素C，再比较烟酰胺和A 醇"

    matches = match_knowledge_entities(raw)

    assert tuple(item.identifier for item in matches) == (
        "ingredient.vitamin_c",
        "ingredient.niacinamide",
        "ingredient.retinol",
    )
    assert tuple(item.raw_text for item in matches) == (
        "维生素C",
        "烟酰胺",
        "A 醇",
    )


def test_concept_aliases_cover_skin_category_and_concern() -> None:
    matches = match_knowledge_concepts(
        "油皮夏天想选面霜，也在意抗初老"
    )

    assert tuple(item.identifier for item in matches) == (
        "skin.oily",
        "category.moisturizer",
        "concern.anti_aging",
    )
    assert concept_lineage("category.moisturizer") == (
        "category",
        "category.moisturizer",
    )


def test_explicit_relations_are_generic_and_follow_source_order() -> None:
    assert explicit_knowledge_relations(
        "烟酰胺和A醇有什么区别，能一起用吗？"
    ) == ("difference", "compatibility")
    assert explicit_knowledge_relations(
        "维C白天怎么用，为什么要配防晒？"
    ) == ("usage", "mechanism")


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        ("痘肌选品要避开什么？", ("safety",)),
        ("屏障受损后如何修护？", ("usage",)),
        ("不同功效的精华应该怎么选？", ("selection",)),
        ("水杨酸适合什么人？", ("selection",)),
        ("眼霜怎么按眼周问题选择？", ("selection",)),
    ),
)
def test_relation_markers_classify_general_guidance_without_false_difference(
    raw: str,
    expected: tuple[str, ...],
) -> None:
    assert explicit_knowledge_relations(raw) == expected
