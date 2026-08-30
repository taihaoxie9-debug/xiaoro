from __future__ import annotations

import pytest

from tools.guide_data.smzdm_category_policy import (
    SmzdmCategoryPolicyError,
    build_review_packet,
    fields_for_profile,
)


def test_skincare_review_does_not_extract_suncare_fields() -> None:
    fields = fields_for_profile("skincare")

    assert fields == (
        "net_content",
        "ingredients_present",
        "texture",
        "efficacy",
        "usage",
    )
    assert "spf_pa" not in fields


def test_each_supported_profile_has_a_distinct_review_policy() -> None:
    policies = {
        profile: fields_for_profile(profile)
        for profile in (
            "skincare",
            "suncare",
            "cleanser",
            "base_makeup",
            "color_makeup",
            "fragrance",
        )
    }

    assert len(set(policies.values())) == len(policies)
    assert policies["suncare"] == (
        "net_content",
        "spf_pa",
        "texture",
        "film_speed",
        "water_resistance",
        "reapplication",
        "cleansing_requirement",
    )
    assert policies["fragrance"] == (
        "net_content",
        "concentration",
        "fragrance_family",
        "top_notes",
        "heart_notes",
        "base_notes",
        "longevity",
        "sillage",
    )


def test_unknown_profile_is_rejected() -> None:
    with pytest.raises(
        SmzdmCategoryPolicyError,
        match="unsupported category profile",
    ):
        fields_for_profile("haircare")


def test_absent_detail_images_remain_a_valid_review_packet() -> None:
    packet = build_review_packet(
        parameter_text="净含量 50ml",
        introduction_text="柔润乳液质地",
        detail_images=(),
    )

    assert packet.detail_image_count == 0
    assert packet.detail_image_status == "absent"
    assert packet.review_sources == (
        "parameter_table",
        "product_introduction",
    )


def test_present_detail_images_are_added_after_text_sources() -> None:
    packet = build_review_packet(
        parameter_text="",
        introduction_text="商品介绍",
        detail_images=("001.jpg", "002.jpg"),
    )

    assert packet.detail_image_count == 2
    assert packet.detail_image_status == "present"
    assert packet.review_sources == (
        "product_introduction",
        "detail_images",
    )
