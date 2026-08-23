from decimal import Decimal

from app.guide.presentation.contracts import (
    DisplayCategoryFact,
    ProductCard,
)
from app.guide.presentation.copywriter_contracts import ApprovedSoftFact
from app.guide.presentation.public_fact_projection import (
    project_public_facts,
    projected_fact_to_soft_fact,
)
from app.guide.retrieval.category_profiles import CategoryProfile


def _serum_card() -> ProductCard:
    return ProductCard(
        product_id=39,
        category_profile=CategoryProfile.SKINCARE,
        category_facts=(
            DisplayCategoryFact(
                field_key="ingredients_present",
                label="确认含有成分",
                value=("海茴香精粹", "植物抗老多肽"),
                state="known",
            ),
            DisplayCategoryFact(
                field_key="suitable_skin",
                label="适用肤质",
                value=("多肤质可用", "偏油皮友好"),
                state="known",
            ),
            DisplayCategoryFact(
                field_key="texture",
                label="质地",
                value="轻盈凝露",
                state="known",
            ),
        ),
        price_specification_alignment="unresolved",
        name="赫莲娜绿宝瓶精华",
        display_name="赫莲娜绿宝瓶精华",
        brand="赫莲娜",
        category="精华",
        price=Decimal("1080"),
        specification=None,
        skin_match="unknown",
        matched_efficacies=[],
        fact_warnings=[],
    )


def test_projection_merges_category_and_product_evidence() -> None:
    projection = project_public_facts(
        card=_serum_card(),
        approved_soft_facts=(
            ApprovedSoftFact(
                fact_id="evidence:39:brand-main",
                product_id=39,
                field_key="brand_main",
                plain_meaning="轻盈修护抗老",
                attribution="merchant_claim",
                source_refs=("urn:evidence:39:brand-main",),
            ),
        ),
        requested_dimensions=("texture",),
    )

    assert [fact.field_key for fact in projection.facts] == [
        "brand_main",
        "texture",
        "ingredients_present",
        "suitable_skin",
    ]
    assert all(fact.fact_id for fact in projection.facts)
    assert all(fact.source_refs for fact in projection.facts)
    assert projection.facts[0].fact_id == "evidence:39:brand-main"
    assert projection.facts[1].fact_id == "category:39:texture"


def test_projected_soft_fact_preserves_exact_attribution() -> None:
    projection = project_public_facts(
        card=_serum_card(),
        approved_soft_facts=(
            ApprovedSoftFact(
                fact_id="review:39:skin",
                product_id=39,
                field_key="suitable_skin",
                plain_meaning="偏油肤质用户反馈更容易接受",
                attribution="consumer_report",
                source_refs=("urn:review:39:skin",),
            ),
        ),
        requested_dimensions=("suitable_skin",),
    )
    projected = next(
        fact
        for fact in projection.facts
        if fact.fact_id == "review:39:skin"
    )

    converted = projected_fact_to_soft_fact(projected)

    assert converted.attribution == "consumer_report"
    assert converted.source_refs == ("urn:review:39:skin",)
    assert converted.fact_id == "review:39:skin"


def test_brand_main_removes_only_controlled_attribution_prefixes() -> None:
    projection = project_public_facts(
        card=_serum_card(),
        approved_soft_facts=(
            ApprovedSoftFact(
                fact_id="atom:39:brand-main",
                product_id=39,
                field_key="efficacy",
                plain_meaning="品牌主打：修护；品牌主打：舒缓",
                attribution="merchant_claim",
                source_refs=("urn:atom:39:brand-main",),
            ),
        ),
        requested_dimensions=(),
    )

    brand_main = next(
        fact
        for fact in projection.facts
        if fact.field_key == "brand_main"
    )

    assert brand_main.display_value == "修护；舒缓"


def test_category_projection_replaces_legacy_category_derived_atom_id() -> None:
    projection = project_public_facts(
        card=_serum_card(),
        approved_soft_facts=(
            ApprovedSoftFact(
                fact_id="atom:legacy-category-texture",
                product_id=39,
                field_key="texture",
                plain_meaning="质地：轻盈凝露",
                attribution="verified_fact",
                source_refs=("card:39:texture",),
            ),
            ApprovedSoftFact(
                fact_id="evidence:39:usage",
                product_id=39,
                field_key="usage",
                plain_meaning="早晚在面霜前使用",
                attribution="merchant_claim",
                source_refs=("urn:evidence:39:usage",),
            ),
        ),
        requested_dimensions=("texture",),
    )

    fact_ids = {fact.fact_id for fact in projection.facts}

    assert "category:39:texture" in fact_ids
    assert "atom:legacy-category-texture" not in fact_ids
    assert "evidence:39:usage" in fact_ids
