from __future__ import annotations

from app.guide.retrieval.card_specification import (
    resolve_card_specification,
)
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.retrieval.selection_fact_contracts import SelectionFact


def _net_content(
    value: str,
    *,
    subject_scope: str = "exact_product",
    variant_scope: str | None = None,
    capabilities: frozenset[str] = frozenset({"compare"}),
    safety_role: str = "ordinary",
) -> SelectionFact:
    return SelectionFact.model_validate(
        {
            "product_id": 33,
            "category_profile": CategoryProfile.SKINCARE,
            "subject_scope": subject_scope,
            "variant_scope": variant_scope,
            "field_key": "net_content",
            "normalized_value": value,
            "rank_strength": None,
            "safety_role": safety_role,
            "capabilities": capabilities,
            "source_refs": (f"source:{value}:{variant_scope}",),
            "attributions": frozenset({"verified_fact"}),
        },
        strict=True,
    )


def test_unique_exact_product_specification_is_used() -> None:
    assert resolve_card_specification(
        facts=(_net_content("50ml"),),
        variant_scope=None,
    ) == "50ml"


def test_matching_exact_variant_wins_over_product_specification() -> None:
    assert resolve_card_specification(
        facts=(
            _net_content("50ml"),
            _net_content(
                "30ml",
                subject_scope="exact_variant",
                variant_scope="旅行装",
            ),
        ),
        variant_scope="旅行装",
    ) == "30ml"


def test_unknown_variant_falls_back_to_unique_product_specification() -> None:
    assert resolve_card_specification(
        facts=(
            _net_content("50ml"),
            _net_content(
                "30ml",
                subject_scope="exact_variant",
                variant_scope="旅行装",
            ),
        ),
        variant_scope="限定版",
    ) == "50ml"


def test_conflicting_unbound_variants_are_omitted() -> None:
    assert resolve_card_specification(
        facts=(
            _net_content(
                "50ml",
                subject_scope="exact_variant",
                variant_scope="常规装",
            ),
            _net_content(
                "30ml",
                subject_scope="exact_variant",
                variant_scope="旅行装",
            ),
        ),
        variant_scope=None,
    ) is None


def test_aggregate_product_value_does_not_mask_variant_conflict() -> None:
    assert resolve_card_specification(
        facts=(
            _net_content("50ml 100ml 200ml"),
            _net_content(
                "50ml",
                subject_scope="exact_variant",
                variant_scope="50ml主品",
            ),
            _net_content(
                "100ml",
                subject_scope="exact_variant",
                variant_scope="100ml主品",
            ),
            _net_content(
                "200ml",
                subject_scope="exact_variant",
                variant_scope="200ml主品",
            ),
        ),
        variant_scope=None,
    ) is None


def test_aggregate_exact_product_text_is_not_a_card_specification() -> None:
    for aggregate in (
        "30ml 72ml 102ml",
        "125ml,50ml",
        "50g 50ml",
    ):
        assert resolve_card_specification(
            facts=(_net_content(aggregate),),
            variant_scope=None,
        ) is None


def test_conflicting_exact_product_values_are_omitted() -> None:
    assert resolve_card_specification(
        facts=(
            _net_content("50ml"),
            _net_content("30ml"),
        ),
        variant_scope=None,
    ) is None


def test_non_comparable_or_nonordinary_facts_are_ignored() -> None:
    assert resolve_card_specification(
        facts=(
            _net_content(
                "50ml",
                capabilities=frozenset({"hard_filter"}),
            ),
            _net_content(
                "30ml",
                safety_role="merchant_positive_safety",
            ),
        ),
        variant_scope=None,
    ) is None


def test_production_cards_project_every_unambiguous_specification() -> None:
    from app.guide.retrieval.category_profiles import (
        category_profile_for,
    )
    from app.guide_runtime.composition import (
        build_consultation_vertical_runtime,
    )

    catalog = (
        build_consultation_vertical_runtime()
        .recommendation
        ._presentation_facts
    )
    projected: dict[int, str] = {}
    for product_id in sorted(catalog._reader.product_ids):
        product = catalog._reader.get(product_id)
        profile = category_profile_for(
            product.fields["category"].value
        )
        selection_facts = catalog._selection_fact_port.read(
            product_id=product_id,
            profile=profile,
        )
        expected = resolve_card_specification(
            selection_facts,
            variant_scope=None,
        )
        binding = catalog._product_display_bindings.get_optional(
            product_id
        )
        if binding is not None:
            expected = (
                catalog._product_display_bindings
                .price_bound_specification(product_id)
            )
        card_facts = catalog.get_presentation_facts(product_id)

        assert card_facts.specification == expected
        if expected is not None:
            projected[product_id] = expected

    assert len(projected) == 25
    assert projected[32] == "50ml"
    assert projected[43] == "50ml"
    assert projected[65] == "100g"
    assert projected[70] == "500ml"
    assert projected[71] == "100ml"
    assert projected[81] == "10g"
    assert projected[130] == "50ml"
    assert all(
        product_id not in projected
        for product_id in (
            24,
            33,
            35,
            36,
            38,
            54,
            57,
            63,
            64,
            68,
            73,
            102,
            104,
            129,
        )
    )
