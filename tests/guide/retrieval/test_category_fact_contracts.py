from __future__ import annotations

from typing import get_args

import pytest
from pydantic import ValidationError

from app.guide.retrieval.category_fact_contracts import (
    Capability,
    CategoryFieldDefinition,
    CategoryFieldRegistry,
    SourceClass,
    SourcePolicy,
    category_field_registry,
)
from app.guide.retrieval.category_profiles import CategoryProfile


COMMON_FIELDS = {
    "product_identity",
    "brand",
    "category",
    "price",
    "ingredients_present",
    "claimed_ingredients",
    "claimed_absences",
    "verified_absences",
    "safety",
    "usage",
    "net_content",
    "shelf_life",
    "origin",
    "target_audience",
    "usage_context",
}

PROFILE_FIELDS = {
    CategoryProfile.SKINCARE: {
        "efficacy",
        "suitable_skin",
        "skin_concern",
        "texture",
        "mechanism",
        "clinical_evidence",
        "application_area",
        "product_form",
        "mask_material",
        "package_quantity",
        "fragrance_description",
    },
    CategoryProfile.SUNCARE: {
        "efficacy",
        "skin_concern",
        "mechanism",
        "spf_pa",
        "water_resistance",
        "reapplication",
        "finish",
        "texture",
        "suitable_skin",
        "application_area",
        "product_form",
        "film_speed",
        "sun_protection_spectrum",
        "tone_effect",
        "cleansing_requirement",
        "friction_resistance",
        "variant_option",
    },
    CategoryProfile.BASE_MAKEUP: {
        "efficacy",
        "skin_concern",
        "mechanism",
        "spf_pa",
        "shade",
        "finish",
        "coverage",
        "longevity",
        "texture",
        "suitable_skin",
        "application_area",
        "product_form",
        "makeup_effect",
        "sun_protection_claim",
        "variant_option",
    },
    CategoryProfile.COLOR_MAKEUP: {
        "efficacy",
        "skin_concern",
        "mechanism",
        "suitable_skin",
        "shade",
        "finish",
        "texture",
        "longevity",
        "application_area",
        "product_form",
        "color_count",
        "color_family",
        "color_payoff",
        "makeup_effect",
        "makeup_style",
        "variant_option",
    },
    CategoryProfile.CLEANSER: {
        "efficacy",
        "skin_concern",
        "mechanism",
        "cleansing_form",
        "cleansing_power",
        "surfactant_type",
        "rinse_behavior",
        "double_cleanse",
        "texture",
        "suitable_skin",
        "application_area",
        "product_form",
        "fragrance_description",
    },
    CategoryProfile.FRAGRANCE: {
        "concentration",
        "fragrance_family",
        "top_notes",
        "heart_notes",
        "base_notes",
        "longevity",
        "sillage",
    },
}

CORE_FIELDS = {"product_identity", "brand", "category", "price"}
OBSERVATION_ONLY_SOURCES = {
    SourceClass.UNKNOWN,
    SourceClass.OCR_PACKAGING,
    SourceClass.OCR_INGREDIENT_LIST,
}
EXPERIENTIAL_REVIEW_FIELDS = {
    "texture",
    "finish",
    "coverage",
    "longevity",
    "cleansing_power",
    "rinse_behavior",
    "sillage",
    "film_speed",
    "fragrance_description",
    "color_payoff",
    "makeup_effect",
    "makeup_style",
    "cleansing_requirement",
    "friction_resistance",
}


def _field(
    key: str,
    *,
    aliases: list[str] | None = None,
    source_policies: list[SourcePolicy] | None = None,
) -> CategoryFieldDefinition:
    return CategoryFieldDefinition(
        key=key,
        label=key,
        aliases=aliases or [f"{key}别名"],
        value_type="string",
        profiles=[CategoryProfile.SKINCARE],
        source_policies=source_policies
        or [
            SourcePolicy(
                source_class=SourceClass.STRUCTURED_OFFICIAL,
                capabilities=["evidence", "display"],
            )
        ],
        unknown_policy="preserve_unknown",
        conflict_policy="record",
    )


def test_strict_models_accept_legal_list_inputs_and_freeze_containers() -> None:
    policy = SourcePolicy(
        source_class=SourceClass.STRUCTURED_OFFICIAL,
        capabilities=["evidence", "display", "compare"],
    )
    definition = CategoryFieldDefinition(
        key="shade",
        label="色号",
        aliases=["颜色", "色彩编号"],
        value_type="string_list",
        profiles=[
            CategoryProfile.BASE_MAKEUP,
            CategoryProfile.COLOR_MAKEUP,
        ],
        source_policies=[policy],
        unknown_policy="preserve_unknown",
        conflict_policy="record",
    )

    assert policy.capabilities == frozenset(
        {"evidence", "display", "compare"}
    )
    assert definition.aliases == ("颜色", "色彩编号")
    assert definition.profiles == frozenset(
        {
            CategoryProfile.BASE_MAKEUP,
            CategoryProfile.COLOR_MAKEUP,
        }
    )
    assert definition.source_policies == (policy,)


def test_unknown_authority_fails_after_container_normalization() -> None:
    with pytest.raises(
        ValidationError,
        match="unknown source is evidence-only",
    ):
        SourcePolicy(
            source_class=SourceClass.UNKNOWN,
            capabilities=["evidence", "compare"],
        )


@pytest.mark.parametrize(
    "source_class",
    [
        SourceClass.OCR_PACKAGING,
        SourceClass.OCR_INGREDIENT_LIST,
    ],
)
def test_raw_ocr_authority_is_observation_only(
    source_class: SourceClass,
) -> None:
    with pytest.raises(
        ValidationError,
        match="OCR sources are evidence-only",
    ):
        SourcePolicy(
            source_class=source_class,
            capabilities=["evidence", "display"],
        )


def test_approved_review_authority_cannot_filter_compare_or_rank() -> None:
    with pytest.raises(
        ValidationError,
        match="approved consumer review is evidence/display-only",
    ):
        SourcePolicy(
            source_class=SourceClass.APPROVED_CONSUMER_REVIEW,
            capabilities=["evidence", "compare"],
        )


def test_capability_vocabulary_is_closed() -> None:
    assert set(get_args(Capability)) == {
        "evidence",
        "display",
        "compare",
        "hard_filter",
        "soft_rank",
    }


def test_registry_defines_exact_design_fields_once() -> None:
    registry = category_field_registry()
    definitions = registry.definitions
    keys = [definition.key for definition in definitions]

    assert len(keys) == len(set(keys)) == 56
    assert set(keys) == COMMON_FIELDS | set().union(*PROFILE_FIELDS.values())

    aliases = [
        alias
        for definition in definitions
        for alias in definition.aliases
    ]
    assert len(aliases) == len(set(aliases))


@pytest.mark.parametrize("profile", list(CategoryProfile))
def test_registry_returns_exact_applicable_fields(
    profile: CategoryProfile,
) -> None:
    keys = {
        definition.key
        for definition in category_field_registry().for_profile(profile)
    }

    assert keys == COMMON_FIELDS | PROFILE_FIELDS[profile]


def test_canonical_core_fields_have_exclusive_authority() -> None:
    definitions = {
        definition.key: definition
        for definition in category_field_registry().definitions
    }

    for key in CORE_FIELDS:
        assert tuple(
            policy.source_class
            for policy in definitions[key].source_policies
        ) == (SourceClass.CANONICAL_CORE,)

    for key, definition in definitions.items():
        if key not in CORE_FIELDS:
            assert all(
                policy.source_class is not SourceClass.CANONICAL_CORE
                for policy in definition.source_policies
            )


def test_each_source_policy_keeps_its_own_capabilities() -> None:
    definitions = {
        definition.key: definition
        for definition in category_field_registry().definitions
    }
    texture_policies = {
        policy.source_class: policy.capabilities
        for policy in definitions["texture"].source_policies
    }

    assert "soft_rank" in texture_policies[
        SourceClass.STRUCTURED_OFFICIAL
    ]
    assert texture_policies[SourceClass.APPROVED_CONSUMER_REVIEW] == (
        frozenset({"evidence", "display"})
    )
    assert texture_policies[SourceClass.OCR_PACKAGING] == frozenset(
        {"evidence"}
    )
    assert texture_policies[SourceClass.UNKNOWN] == frozenset(
        {"evidence"}
    )


def test_claimed_absence_is_soft_while_verified_absence_stays_strong() -> None:
    definitions = {
        definition.key: definition
        for definition in category_field_registry().definitions
    }
    claimed = {
        policy.source_class: policy.capabilities
        for policy in definitions["claimed_absences"].source_policies
    }
    verified = {
        policy.source_class: policy.capabilities
        for policy in definitions["verified_absences"].source_policies
    }

    assert claimed[SourceClass.MERCHANT_DESCRIPTION_OCR] == frozenset(
        {"evidence", "display", "compare", "soft_rank"}
    )
    assert SourceClass.MERCHANT_DESCRIPTION_OCR not in verified
    assert "hard_filter" not in claimed[
        SourceClass.MERCHANT_DESCRIPTION_OCR
    ]


def test_claimed_ingredient_is_soft_while_confirmed_presence_stays_strong(
) -> None:
    definitions = {
        definition.key: definition
        for definition in category_field_registry().definitions
    }
    claimed = {
        policy.source_class: policy.capabilities
        for policy in definitions["claimed_ingredients"].source_policies
    }
    confirmed = {
        policy.source_class: policy.capabilities
        for policy in definitions["ingredients_present"].source_policies
    }

    assert claimed[SourceClass.MERCHANT_DESCRIPTION_OCR] == frozenset(
        {"evidence", "display", "compare", "soft_rank"}
    )
    assert SourceClass.MERCHANT_DESCRIPTION_OCR not in confirmed
    assert "hard_filter" not in claimed[
        SourceClass.MERCHANT_DESCRIPTION_OCR
    ]
    assert confirmed[SourceClass.OFFICIAL_PACKAGING] == frozenset(
        {
            "evidence",
            "display",
            "compare",
            "hard_filter",
            "soft_rank",
        }
    )


def test_verified_absence_supports_soft_preference_and_hard_exclusion(
) -> None:
    definition = next(
        item
        for item in category_field_registry().definitions
        if item.key == "verified_absences"
    )
    policies = {
        policy.source_class: policy.capabilities
        for policy in definition.source_policies
    }

    assert policies[SourceClass.OFFICIAL_PACKAGING] == frozenset(
        {
            "evidence",
            "display",
            "compare",
            "hard_filter",
            "soft_rank",
        }
    )


def test_ocr_and_review_policies_match_their_evidence_boundaries() -> None:
    observed_sources: set[SourceClass] = set()
    review_fields: set[str] = set()

    for definition in category_field_registry().definitions:
        for policy in definition.source_policies:
            observed_sources.add(policy.source_class)
            assert "evidence" in policy.capabilities
            if policy.source_class in OBSERVATION_ONLY_SOURCES:
                assert policy.capabilities == frozenset({"evidence"})
            if policy.source_class is SourceClass.OCR_INGREDIENT_LIST:
                assert definition.key == "ingredients_present"
            if policy.source_class is SourceClass.APPROVED_CONSUMER_REVIEW:
                review_fields.add(definition.key)
                assert policy.capabilities == frozenset(
                    {"evidence", "display"}
                )

    assert OBSERVATION_ONLY_SOURCES <= observed_sources
    assert review_fields
    assert review_fields <= EXPERIENTIAL_REVIEW_FIELDS


def test_all_fields_preserve_unknown_and_record_conflict() -> None:
    for definition in category_field_registry().definitions:
        assert definition.unknown_policy == "preserve_unknown"
        assert definition.conflict_policy == "record"


def test_duplicate_field_key_is_rejected() -> None:
    definition = _field("texture")

    with pytest.raises(ValueError, match="duplicate field key"):
        CategoryFieldRegistry(definitions=(definition, definition))


def test_duplicate_alias_is_rejected_across_fields() -> None:
    with pytest.raises(ValueError, match="duplicate field alias"):
        CategoryFieldRegistry(
            definitions=(
                _field("first_field", aliases=["共享别名"]),
                _field("second_field", aliases=["共享别名"]),
            )
        )


def test_duplicate_source_policy_is_rejected() -> None:
    policy = SourcePolicy(
        source_class=SourceClass.STRUCTURED_OFFICIAL,
        capabilities=["evidence", "display"],
    )

    with pytest.raises(ValidationError, match="duplicate source policy"):
        _field(
            "texture",
            source_policies=[policy, policy],
        )


def test_ocr_ingredient_list_cannot_author_non_ingredient_fields() -> None:
    with pytest.raises(
        ValidationError,
        match="OCR ingredient list may only observe ingredients_present",
    ):
        _field(
            "safety",
            source_policies=[
                SourcePolicy(
                    source_class=SourceClass.OCR_INGREDIENT_LIST,
                    capabilities=["evidence"],
                )
            ],
        )


def test_approved_review_cannot_author_formula_or_safety_fields() -> None:
    with pytest.raises(
        ValidationError,
        match="approved consumer review may only author experiential fields",
    ):
        _field(
            "verified_absences",
            source_policies=[
                SourcePolicy(
                    source_class=SourceClass.APPROVED_CONSUMER_REVIEW,
                    capabilities=["evidence", "display"],
                )
            ],
        )
