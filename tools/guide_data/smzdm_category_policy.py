"""Category-specific source policy for manual SMZDM review."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Sequence

from app.guide.retrieval.category_profiles import CategoryProfile


DetailImageStatus = Literal["present", "absent"]


class SmzdmCategoryPolicyError(ValueError):
    """Raised when review input does not match a supported category."""


CATEGORY_REVIEW_FIELDS = MappingProxyType({
    CategoryProfile.SKINCARE: (
        "net_content",
        "ingredients_present",
        "texture",
        "efficacy",
        "usage",
    ),
    CategoryProfile.SUNCARE: (
        "net_content",
        "spf_pa",
        "texture",
        "film_speed",
        "water_resistance",
        "reapplication",
        "cleansing_requirement",
    ),
    CategoryProfile.CLEANSER: (
        "net_content",
        "surfactant_type",
        "cleansing_power",
        "rinse_behavior",
        "texture",
    ),
    CategoryProfile.BASE_MAKEUP: (
        "net_content",
        "shade",
        "finish",
        "coverage",
        "longevity",
        "texture",
    ),
    CategoryProfile.COLOR_MAKEUP: (
        "shade",
        "color_family",
        "finish",
        "color_payoff",
        "longevity",
    ),
    CategoryProfile.FRAGRANCE: (
        "net_content",
        "concentration",
        "fragrance_family",
        "top_notes",
        "heart_notes",
        "base_notes",
        "longevity",
        "sillage",
    ),
})


@dataclass(frozen=True, slots=True)
class SmzdmReviewPacketSources:
    detail_image_count: int
    detail_image_status: DetailImageStatus
    review_sources: tuple[str, ...]


def fields_for_profile(
    profile: CategoryProfile | str,
) -> tuple[str, ...]:
    """Return the only fields a reviewer should inspect for a profile."""
    try:
        normalized = (
            profile
            if isinstance(profile, CategoryProfile)
            else CategoryProfile(profile)
        )
    except (TypeError, ValueError) as exc:
        raise SmzdmCategoryPolicyError(
            f"unsupported category profile: {profile}"
        ) from exc
    return CATEGORY_REVIEW_FIELDS[normalized]


def build_review_packet(
    *,
    parameter_text: str,
    introduction_text: str,
    detail_images: Sequence[object],
) -> SmzdmReviewPacketSources:
    """Describe available review sources without extracting any facts."""
    if not isinstance(parameter_text, str):
        raise SmzdmCategoryPolicyError(
            "parameter_text must be text"
        )
    if not isinstance(introduction_text, str):
        raise SmzdmCategoryPolicyError(
            "introduction_text must be text"
        )
    if isinstance(detail_images, (str, bytes)) or not isinstance(
        detail_images,
        Sequence,
    ):
        raise SmzdmCategoryPolicyError(
            "detail_images must be a sequence"
        )

    image_count = len(detail_images)
    sources: list[str] = []
    if parameter_text.strip():
        sources.append("parameter_table")
    if introduction_text.strip():
        sources.append("product_introduction")
    if image_count:
        sources.append("detail_images")
    return SmzdmReviewPacketSources(
        detail_image_count=image_count,
        detail_image_status="present" if image_count else "absent",
        review_sources=tuple(sources),
    )
