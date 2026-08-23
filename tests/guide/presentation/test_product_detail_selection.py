from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.guide.intent.responsibility_matrix import Responsibility
from app.guide.presentation.contracts import (
    DisplayCategoryFact,
    ProductCard,
)
from app.guide.presentation.copywriter_contracts import (
    ApprovedSoftFact,
    CopySlot,
)
from app.guide.presentation.product_detail_selection import (
    select_product_detail_facts,
)
from app.guide.presentation.public_fact_contracts import (
    ProductPublicFactProjection,
    ProjectedPublicFact,
)
from app.guide.presentation.public_fact_projection import (
    project_public_facts,
)
from app.guide.retrieval.category_profiles import CategoryProfile


def _fact(
    product_id: int,
    field_key: str,
    *,
    source_kind: str = "category",
) -> ProjectedPublicFact:
    return ProjectedPublicFact(
        fact_id=f"{source_kind}:{product_id}:{field_key}",
        product_id=product_id,
        field_key=field_key,
        label={
            "brand_main": "品牌主打",
            "texture": "质地",
            "ingredients_present": "核心成分",
            "efficacy": "功效方向",
            "usage": "使用方式",
            "suitable_skin": "适合肤质",
        }.get(field_key, field_key),
        display_value=f"{field_key}-value",
        source_refs=(f"urn:{source_kind}:{product_id}:{field_key}",),
        source_kind=source_kind,
        attribution=(
            "merchant_claim"
            if source_kind == "merchant"
            else "verified_fact"
        ),
    )


def _projection(product_id: int) -> ProductPublicFactProjection:
    return ProductPublicFactProjection(
        product_id=product_id,
        facts=(
            _fact(product_id, "brand_main", source_kind="merchant"),
            _fact(product_id, "texture"),
            _fact(product_id, "ingredients_present"),
            _fact(product_id, "efficacy"),
            _fact(product_id, "usage"),
            _fact(product_id, "suitable_skin"),
        ),
    )


@pytest.mark.parametrize("product_id", [39, 999])
def test_detail_selector_uses_product_facts_not_product_id(
    product_id: int,
) -> None:
    selected = select_product_detail_facts(
        projection=_projection(product_id),
        responsibility=Responsibility.RECOMMENDATION,
        requested_dimensions=("texture",),
    )

    assert [item.field_key for item in selected] == [
        "brand_main",
        "texture",
        "ingredients_present",
    ]


def test_product_knowledge_prioritizes_requested_fact() -> None:
    selected = select_product_detail_facts(
        projection=_projection(39),
        responsibility=Responsibility.PRODUCT_KNOWLEDGE,
        requested_dimensions=("usage",),
    )

    assert [item.field_key for item in selected] == [
        "usage",
        "brand_main",
        "ingredients_present",
    ]


def test_image_identity_uses_only_identity_safe_category_facts() -> None:
    selected = select_product_detail_facts(
        projection=_projection(39),
        responsibility=Responsibility.IMAGE_IDENTITY,
        requested_dimensions=(),
    )

    assert [item.field_key for item in selected] == [
        "brand_main",
        "ingredients_present",
        "texture",
    ]
    assert all(
        item.field_key == "brand_main"
        or item.source_kind == "category"
        for item in selected
    )


def test_comparison_body_has_no_product_detail_facts() -> None:
    assert select_product_detail_facts(
        projection=_projection(39),
        responsibility=Responsibility.COMPARISON,
        requested_dimensions=("texture",),
    ) == ()


def test_recommendation_detail_never_repeats_price_or_specification() -> None:
    projection = ProductPublicFactProjection(
        product_id=39,
        facts=(
            _fact(39, "net_content"),
            _fact(39, "texture"),
            _fact(39, "efficacy"),
        ),
    )

    selected = select_product_detail_facts(
        projection=projection,
        responsibility=Responsibility.RECOMMENDATION,
        requested_dimensions=("net_content",),
    )

    assert "net_content" not in {
        item.field_key for item in selected
    }


@pytest.mark.parametrize(
    ("facts", "requested", "expected"),
    [
        (
            (
                ("ingredients_present", "核心成分", ("泛醇",)),
                ("texture", "质地", "清润精华"),
                ("efficacy", "功效", ("修护", "舒缓")),
            ),
            ("ingredients_present",),
            ("ingredients_present", "texture", "efficacy"),
        ),
        (
            (
                ("spf_pa", "防晒指数", "SPF50 PA++++"),
                ("texture", "质地", "水感轻薄"),
                ("usage_context", "使用场景", ("通勤", "户外")),
            ),
            ("spf_pa",),
            ("spf_pa", "texture", "usage_context"),
        ),
        (
            (
                ("usage", "使用方式", "晚间作为面霜使用"),
                ("texture", "质地", "丰润乳霜"),
                ("efficacy", "功效", ("保湿", "修护")),
            ),
            ("usage",),
            ("usage", "texture", "efficacy"),
        ),
    ],
)
def test_detail_fields_change_with_projected_category_facts(
    facts,
    requested,
    expected,
) -> None:
    card = ProductCard(
        product_id=77,
        category_profile=CategoryProfile.SKINCARE,
        category_facts=tuple(
            DisplayCategoryFact(
                field_key=field_key,
                label=label,
                value=value,
                state="known",
            )
            for field_key, label, value in sorted(facts)
        ),
        price_specification_alignment="unresolved",
        name="测试商品",
        display_name="测试商品",
        brand="测试品牌",
        category="护肤",
        price=Decimal("299"),
        specification=None,
        skin_match="unknown",
        matched_efficacies=[],
        fact_warnings=[],
    )
    projection = project_public_facts(
        card=card,
        approved_soft_facts=(),
        requested_dimensions=requested,
    )

    selected = select_product_detail_facts(
        projection=projection,
        responsibility=Responsibility.RECOMMENDATION,
        requested_dimensions=requested,
    )

    assert tuple(item.field_key for item in selected) == expected


def test_copy_slot_detail_facts_require_approved_fact_ids() -> None:
    detail = _fact(39, "texture")

    with pytest.raises(
        ValidationError,
        match="detail facts must belong to approved soft facts",
    ):
        CopySlot(
            slot_id="p1",
            product_id=39,
            name="测试精华",
            category_profile="skincare",
            approved_soft_facts=(
                ApprovedSoftFact(
                    fact_id="different-fact",
                    product_id=39,
                    field_key="texture",
                    plain_meaning="轻盈凝露",
                    attribution="verified_fact",
                    source_refs=("urn:different-fact",),
                ),
            ),
            detail_facts=(detail,),
        )
