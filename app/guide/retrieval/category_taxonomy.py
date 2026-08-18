from types import MappingProxyType

from app.guide.retrieval.category_profiles import (
    RAW_CATEGORY_PROFILES,
    CategoryProfile,
)
from app.guide.understanding.contracts import TopicCode

CATEGORY_TAXONOMY_VERSION = "phase3a-category-v3"

_TOPIC_PROFILES = MappingProxyType({
    TopicCode.SUNSCREEN: CategoryProfile.SUNCARE,
    TopicCode.SERUM: CategoryProfile.SKINCARE,
    TopicCode.SKINCARE: CategoryProfile.SKINCARE,
    TopicCode.BASE_MAKEUP: CategoryProfile.BASE_MAKEUP,
    TopicCode.COLOR_MAKEUP: CategoryProfile.COLOR_MAKEUP,
    TopicCode.CLEANSER: CategoryProfile.CLEANSER,
    TopicCode.FRAGRANCE: CategoryProfile.FRAGRANCE,
})
_SERUM_CATEGORIES = frozenset({"精华", "精华液"})
_CATEGORY_FAMILIES = MappingProxyType({
    topic: (
        _SERUM_CATEGORIES
        if topic is TopicCode.SERUM
        else frozenset(
            raw_category
            for raw_category, category_profile in RAW_CATEGORY_PROFILES.items()
            if category_profile is profile
        )
    )
    for topic, profile in _TOPIC_PROFILES.items()
})


def canonical_categories_for(topic: TopicCode) -> frozenset[str]:
    return _CATEGORY_FAMILIES[topic]


def category_profile_for_topic(topic: TopicCode) -> CategoryProfile:
    return _TOPIC_PROFILES[topic]


def raw_category_mapping() -> MappingProxyType[str, CategoryProfile]:
    return RAW_CATEGORY_PROFILES
