from datetime import datetime

import pytest

from app.guide.retrieval.category_fact_assets import (
    ApprovedCategoryFact,
    CategoryFactAssetIntegrityError,
    _validate_content_safety,
)
from app.guide.retrieval.category_fact_contracts import (
    SourceClass,
    category_field_registry,
)
from app.guide.retrieval.category_profiles import CategoryProfile


def _policies(profile: CategoryProfile, field_key: str):
    definition = next(
        item
        for item in category_field_registry().for_profile(profile)
        if item.key == field_key
    )
    return {
        policy.source_class: policy.capabilities
        for policy in definition.source_policies
    }


def test_full_catalog_source_vocabulary_is_explicit() -> None:
    assert {
        SourceClass.OFFICIAL_REGISTRATION.value,
        SourceClass.MERCHANT_PARAMETER.value,
        SourceClass.MERCHANT_TITLE_CLAIM.value,
        SourceClass.MERCHANT_DESCRIPTION.value,
        SourceClass.MERCHANT_DESCRIPTION_OCR.value,
        SourceClass.CONSUMER_REVIEW.value,
        SourceClass.PACKAGE_OCR.value,
        SourceClass.QA.value,
        SourceClass.PROMOTION_OR_RECOMMENDATION_BLOCK.value,
    } == {
        "official_registration",
        "merchant_parameter",
        "merchant_title_claim",
        "merchant_description",
        "merchant_description_ocr",
        "consumer_review",
        "package_ocr",
        "qa",
        "promotion_or_recommendation_block",
    }


def test_merchant_claims_are_soft_rank_only_for_ordinary_claims() -> None:
    efficacy = _policies(CategoryProfile.SKINCARE, "efficacy")

    assert efficacy[SourceClass.MERCHANT_PARAMETER] == frozenset(
        {"evidence", "display", "compare", "soft_rank"}
    )
    assert "hard_filter" not in efficacy[
        SourceClass.MERCHANT_TITLE_CLAIM
    ]


@pytest.mark.parametrize(
    ("profile", "field_key"),
    (
        (CategoryProfile.SUNCARE, "efficacy"),
        (CategoryProfile.BASE_MAKEUP, "efficacy"),
        (CategoryProfile.COLOR_MAKEUP, "efficacy"),
        (CategoryProfile.CLEANSER, "efficacy"),
        (CategoryProfile.FRAGRANCE, "target_audience"),
        (CategoryProfile.SUNCARE, "application_area"),
        (CategoryProfile.COLOR_MAKEUP, "color_family"),
    ),
)
def test_new_merchant_fields_never_gain_hard_filter(
    profile: CategoryProfile,
    field_key: str,
) -> None:
    policies = _policies(profile, field_key)

    assert "hard_filter" not in policies[SourceClass.MERCHANT_PARAMETER]
    assert "evidence" in policies[SourceClass.MERCHANT_PARAMETER]


def test_merchant_claims_cannot_author_safety_or_absence() -> None:
    forbidden = {
        SourceClass.MERCHANT_PARAMETER,
        SourceClass.MERCHANT_TITLE_CLAIM,
        SourceClass.MERCHANT_DESCRIPTION,
        SourceClass.CONSUMER_REVIEW,
    }

    for field_key in (
        "ingredients_present",
        "safety",
        "verified_absences",
    ):
        assert forbidden.isdisjoint(
            _policies(CategoryProfile.SKINCARE, field_key)
        )


def test_merchant_claimed_absence_is_soft_and_never_verified() -> None:
    policies = _policies(
        CategoryProfile.SKINCARE,
        "claimed_absences",
    )

    assert policies[SourceClass.MERCHANT_DESCRIPTION_OCR] == frozenset(
        {"evidence", "display", "compare", "soft_rank"}
    )
    assert "hard_filter" not in policies[
        SourceClass.MERCHANT_DESCRIPTION_OCR
    ]


def test_merchant_claimed_ingredient_is_soft_and_never_confirmed() -> None:
    policies = _policies(
        CategoryProfile.SKINCARE,
        "claimed_ingredients",
    )

    assert policies[SourceClass.MERCHANT_DESCRIPTION_OCR] == frozenset(
        {"evidence", "display", "compare", "soft_rank"}
    )
    assert "hard_filter" not in policies[
        SourceClass.MERCHANT_DESCRIPTION_OCR
    ]


def test_reviewed_merchant_ocr_is_soft_only_while_other_ocr_stays_private(
) -> None:
    texture = _policies(CategoryProfile.SKINCARE, "texture")

    assert texture[SourceClass.MERCHANT_DESCRIPTION_OCR] == frozenset(
        {"evidence", "display", "compare", "soft_rank"}
    )
    for source_class in (
        SourceClass.PACKAGE_OCR,
        SourceClass.QA,
        SourceClass.PROMOTION_OR_RECOMMENDATION_BLOCK,
    ):
        assert texture[source_class] == frozenset({"evidence"})


def _fact(
    source_ref: str,
    *,
    value: str = "泡沫",
) -> ApprovedCategoryFact:
    return ApprovedCategoryFact(
        fact_id="a" * 64,
        product_id=67,
        category_profile=CategoryProfile.CLEANSER,
        field_key="cleansing_form",
        value=value,
        source_class=SourceClass.MERCHANT_PARAMETER,
        source_refs=(source_ref,),
        source_sha256="b" * 64,
        reviewer="task19-verifier-consensus",
        reviewed_at=datetime.fromisoformat(
            "2026-08-14T04:00:00+08:00"
        ),
    )


def test_content_addressed_source_urn_is_not_misread_as_phone_pii() -> None:
    source_ref = (
        "urn:xiaoro:category-fact-source:sha256:"
        "8191792da4d7082b24451a63a403baf9323a185bdddd922f52ea60181ea5d5e7:"
        "b25ff55da415414f7362bde4b28ad6c47d520a39c8dd031907f9e0601040679c"
    )

    _validate_content_safety(_fact(source_ref))


def test_unstructured_source_ref_still_rejects_phone_pii() -> None:
    with pytest.raises(
        CategoryFactAssetIntegrityError,
        match="PII",
    ):
        _validate_content_safety(_fact("联系电话：010-12345678"))


def test_chinese_slash_delimited_value_is_not_an_absolute_path() -> None:
    _validate_content_safety(
        _fact(
            "urn:xiaoro:category-fact-source:sha256:"
            f"{'a' * 64}:{'b' * 64}",
            value="洁面乳/膏",
        )
    )


def test_real_absolute_path_in_value_remains_forbidden() -> None:
    with pytest.raises(
        CategoryFactAssetIntegrityError,
        match="absolute path",
    ):
        _validate_content_safety(
            _fact(
                "urn:xiaoro:category-fact-source:sha256:"
                f"{'a' * 64}:{'b' * 64}",
                value="来源：/Users/example/source.html",
            )
        )
