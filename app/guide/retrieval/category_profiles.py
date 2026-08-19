from enum import Enum
from types import MappingProxyType


class CategoryProfile(str, Enum):
    SKINCARE = "skincare"
    SUNCARE = "suncare"
    BASE_MAKEUP = "base_makeup"
    COLOR_MAKEUP = "color_makeup"
    CLEANSER = "cleanser"
    FRAGRANCE = "fragrance"


RAW_CATEGORY_PROFILES = MappingProxyType({
    "乳液": CategoryProfile.SKINCARE,
    "乳霜": CategoryProfile.SKINCARE,
    "爽肤水": CategoryProfile.SKINCARE,
    "眼部精华": CategoryProfile.SKINCARE,
    "眼霜": CategoryProfile.SKINCARE,
    "精华": CategoryProfile.SKINCARE,
    "精华水": CategoryProfile.SKINCARE,
    "精华液": CategoryProfile.SKINCARE,
    "面膜": CategoryProfile.SKINCARE,
    "面霜": CategoryProfile.SKINCARE,
    "防晒": CategoryProfile.SUNCARE,
    "防晒乳": CategoryProfile.SUNCARE,
    "防晒乳液": CategoryProfile.SUNCARE,
    "防晒隔离": CategoryProfile.SUNCARE,
    "防晒霜": CategoryProfile.SUNCARE,
    "妆前乳": CategoryProfile.BASE_MAKEUP,
    "散粉": CategoryProfile.BASE_MAKEUP,
    "气垫": CategoryProfile.BASE_MAKEUP,
    "气垫粉底": CategoryProfile.BASE_MAKEUP,
    "气垫粉底液": CategoryProfile.BASE_MAKEUP,
    "粉底液": CategoryProfile.BASE_MAKEUP,
    "蜜粉": CategoryProfile.BASE_MAKEUP,
    "遮瑕膏": CategoryProfile.BASE_MAKEUP,
    "单色眼影": CategoryProfile.COLOR_MAKEUP,
    "口红": CategoryProfile.COLOR_MAKEUP,
    "唇膏": CategoryProfile.COLOR_MAKEUP,
    "腮红": CategoryProfile.COLOR_MAKEUP,
    "卸妆": CategoryProfile.CLEANSER,
    "卸妆水/洁肤液": CategoryProfile.CLEANSER,
    "卸妆洁肤液/卸妆水": CategoryProfile.CLEANSER,
    "卸妆膏": CategoryProfile.CLEANSER,
    "洁面/清洁": CategoryProfile.CLEANSER,
    "洁面乳/泡沫洁面乳": CategoryProfile.CLEANSER,
    "洁面乳/洁面泡沫": CategoryProfile.CLEANSER,
    "洁面泡沫": CategoryProfile.CLEANSER,
    "洁面霜/洁面": CategoryProfile.CLEANSER,
    "洁颜油/卸妆油": CategoryProfile.CLEANSER,
    "洁颜霜/卸妆膏": CategoryProfile.CLEANSER,
    "香水": CategoryProfile.FRAGRANCE,
})


def category_profile_for(raw_category: str) -> CategoryProfile:
    return RAW_CATEGORY_PROFILES[raw_category]
