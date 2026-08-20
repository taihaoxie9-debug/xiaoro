import pytest

from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.retrieval.category_taxonomy import (
    canonical_categories_for,
    category_profile_for_topic,
    raw_category_mapping,
)
from app.guide.understanding.contracts import TopicCode


def test_sunscreen_family_is_explicit_and_versioned() -> None:
    values = canonical_categories_for(TopicCode.SUNSCREEN)
    assert values == frozenset({
        "防晒",
        "防晒隔离",
        "防晒乳液",
        "防晒霜",
        "防晒乳",
    })


def test_serum_family_excludes_adjacent_categories() -> None:
    values = canonical_categories_for(TopicCode.SERUM)
    assert values == frozenset({"精华", "精华液"})
    assert "精华水" not in values
    assert "眼部精华" not in values


@pytest.mark.parametrize(
    ("topic", "profile"),
    [
        (TopicCode.SERUM, CategoryProfile.SKINCARE),
        (TopicCode.SUNSCREEN, CategoryProfile.SUNCARE),
        (TopicCode.SKINCARE, CategoryProfile.SKINCARE),
        (TopicCode.BASE_MAKEUP, CategoryProfile.BASE_MAKEUP),
        (TopicCode.COLOR_MAKEUP, CategoryProfile.COLOR_MAKEUP),
        (TopicCode.CLEANSER, CategoryProfile.CLEANSER),
        (TopicCode.FRAGRANCE, CategoryProfile.FRAGRANCE),
    ],
)
def test_topic_profile_semantics_are_explicit(
    topic: TopicCode,
    profile: CategoryProfile,
) -> None:
    assert category_profile_for_topic(topic) is profile


PROFILE_TOPICS = (
    TopicCode.SKINCARE,
    TopicCode.SUNSCREEN,
    TopicCode.BASE_MAKEUP,
    TopicCode.COLOR_MAKEUP,
    TopicCode.CLEANSER,
    TopicCode.FRAGRANCE,
)


def test_six_profile_topic_families_cover_all_39_categories_once() -> None:
    families = [
        canonical_categories_for(topic)
        for topic in PROFILE_TOPICS
    ]

    assert sum(len(family) for family in families) == 39
    assert set().union(*families) == set(raw_category_mapping())
    for index, family in enumerate(families):
        assert family.isdisjoint(set().union(*families[index + 1:]))


def test_topic_families_match_raw_category_profiles() -> None:
    mapping = raw_category_mapping()

    for topic in PROFILE_TOPICS:
        profile = category_profile_for_topic(topic)
        assert canonical_categories_for(topic) == frozenset(
            raw_category
            for raw_category, raw_profile in mapping.items()
            if raw_profile is profile
        )


def test_serum_specificity_precedes_broad_skincare_topic() -> None:
    topics = list(TopicCode)

    assert topics.index(TopicCode.SERUM) < topics.index(TopicCode.SKINCARE)
