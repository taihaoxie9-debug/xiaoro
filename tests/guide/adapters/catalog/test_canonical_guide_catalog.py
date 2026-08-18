from decimal import Decimal
from pathlib import Path

import pytest

from app.guide.adapters.catalog import CanonicalProductReader
from app.guide.adapters.catalog.canonical_guide_catalog import (
    CanonicalGuideCatalog,
)
from app.guide.adapters.catalog.seed_product_assets import (
    load_seed_product_assets,
)
from app.guide.decision.contracts import FactState
from app.guide.retrieval.category_fact_contracts import (
    AuthorizedCategoryFact,
    SourceClass,
)
from app.guide.retrieval.category_profiles import CategoryProfile
from app.guide.retrieval.contracts import CanonicalField, CanonicalProduct
from app.guide.retrieval.selection_fact_contracts import SelectionFact
from app.guide.understanding.contracts import TopicCode

ROOT = Path(__file__).resolve().parents[4]


def canonical_field(
    key: str,
    value,
    *,
    state: str = "known",
) -> CanonicalField:
    return CanonicalField(
        key=key,
        value=value,
        field_origin="test",
        resolved_state=state,
        source_classes=["test"],
        source_refs=["test"],
        evidence_status=None,
    )


class FakeReader:
    def __init__(self, product: CanonicalProduct) -> None:
        self.product_ids = frozenset({product.product_id})
        self._product = product

    def get(self, product_id: int) -> CanonicalProduct:
        assert product_id == self._product.product_id
        return self._product.model_copy(deep=True)


class RecordingCategoryFactReader:
    def __init__(
        self,
        facts: tuple[AuthorizedCategoryFact, ...],
    ) -> None:
        self.facts = facts
        self.calls: list[tuple[int, CategoryProfile]] = []

    def read(
        self,
        *,
        product_id: int,
        profile: CategoryProfile,
    ) -> tuple[AuthorizedCategoryFact, ...]:
        self.calls.append((product_id, profile))
        return self.facts


class RecordingSelectionFactReader:
    def __init__(self, facts: tuple[SelectionFact, ...]) -> None:
        self.facts = facts
        self.calls: list[tuple[int, CategoryProfile]] = []

    def read(
        self,
        *,
        product_id: int,
        profile: CategoryProfile,
    ) -> tuple[SelectionFact, ...]:
        self.calls.append((product_id, profile))
        return self.facts


def _selection_specification(
    value: str,
    *,
    subject_scope: str,
    variant_scope: str | None,
) -> SelectionFact:
    return SelectionFact(
        product_id=1,
        category_profile=CategoryProfile.SUNCARE,
        subject_scope=subject_scope,
        variant_scope=variant_scope,
        field_key="net_content",
        normalized_value=value,
        capabilities=frozenset({"compare"}),
        source_refs=(f"spec:{value}:{variant_scope}",),
        attributions=frozenset({"verified_fact"}),
    )


def fake_reader_factory(
    *,
    price,
    price_state: str = "known",
) -> FakeReader:
    product = CanonicalProduct(
        product_id=1,
        schema_version="canonical-decision-product-v1",
        fields={
            "category": canonical_field("category", "防晒"),
            "price": canonical_field(
                "price",
                price,
                state=price_state,
            ),
            "suitable_skin": canonical_field(
                "suitable_skin",
                None,
                state="unknown",
            ),
            "ingredients_present": canonical_field(
                "ingredients_present",
                None,
                state="unknown",
            ),
            "verified_absences": canonical_field(
                "verified_absences",
                None,
                state="unknown",
            ),
            "product_identity": canonical_field(
                "product_identity",
                "测试商品",
            ),
            "brand": canonical_field("brand", "测试品牌"),
        },
    )
    return FakeReader(product)


def make_catalog(reader) -> CanonicalGuideCatalog:
    return CanonicalGuideCatalog(reader)


@pytest.fixture
def real_catalog() -> CanonicalGuideCatalog:
    canonical = ROOT / "data" / "canonical"
    reader = CanonicalProductReader.from_files(
        manifest_path=canonical / "core_products_v1_manifest.json",
        products_path=canonical / "core_products_v1.jsonl",
    )
    return CanonicalGuideCatalog(reader)


def test_boolean_price_is_conflict_not_one() -> None:
    catalog = make_catalog(fake_reader_factory(price=True))
    facts = catalog.get_decision_facts(1)
    assert facts.price_state is FactState.CONFLICT
    assert facts.price is None


def test_unknown_price_stays_unknown() -> None:
    catalog = make_catalog(
        fake_reader_factory(price=None, price_state="unknown")
    )
    facts = catalog.get_decision_facts(1)
    assert facts.price_state is FactState.UNKNOWN
    assert facts.price is None


def test_known_price_is_decimal(real_catalog) -> None:
    facts = real_catalog.get_decision_facts(55)
    assert facts.price == Decimal("88.11")
    assert facts.price_state is FactState.KNOWN
    assert facts.price_source_refs == (
        "data/seed_dump.sql#product=55",
    )


def test_repair_efficacy_is_read_from_authorized_field(real_catalog) -> None:
    facts = real_catalog.get_decision_facts(38)
    assert facts.efficacy == ("修护", "补水保湿", "舒缓")
    assert facts.efficacy_state is FactState.KNOWN


def test_suitable_skin_keeps_auditable_canonical_source_refs(
    real_catalog,
) -> None:
    facts = real_catalog.get_decision_facts(38)

    assert facts.suitable_skin_source_refs == (
        "30c5674860482a2e7a543c6a0d564355af737e31ab05b251cff2150ef4d230a3",
    )


def test_unusable_source_name_is_preserved_and_flagged(real_catalog) -> None:
    facts = real_catalog.get_presentation_facts(26)
    assert facts.name == "无"
    assert "product_identity_unusable" in facts.fact_warnings


def test_presentation_facts_preserve_canonical_category(
    real_catalog,
) -> None:
    facts = real_catalog.get_presentation_facts(38)
    assert facts.category == "精华"


def test_catalog_derives_profile_from_raw_category_with_strict_empty_default(
    real_catalog,
) -> None:
    decision_facts = real_catalog.get_decision_facts(38)
    presentation_facts = real_catalog.get_presentation_facts(38)

    assert decision_facts.category_profile is CategoryProfile.SKINCARE
    assert presentation_facts.category_profile is CategoryProfile.SKINCARE
    assert decision_facts.category_profile is not TopicCode.SERUM
    assert all(
        item.resolved_state == "unknown"
        for item in decision_facts.category_fields
    )
    assert (
        presentation_facts.category_fields
        == decision_facts.category_fields
    )


def test_catalog_injects_typed_category_fact_port_for_both_fact_views() -> None:
    category_fact = AuthorizedCategoryFact(
        category_profile=CategoryProfile.SUNCARE,
        field_key="spf_pa",
        value="SPF50+ / PA++++",
        resolved_state="known",
        source_classes=(SourceClass.OFFICIAL_PACKAGING,),
        source_refs=("urn:task9:spf-pa",),
        capabilities=frozenset({"evidence", "display", "compare"}),
    )
    port = RecordingCategoryFactReader((category_fact,))
    catalog = CanonicalGuideCatalog(
        fake_reader_factory(price="100"),
        category_fact_port=port,
    )

    decision_facts = catalog.get_decision_facts(1)
    presentation_facts = catalog.get_presentation_facts(1)

    assert decision_facts.category_profile is CategoryProfile.SUNCARE
    assert decision_facts.category_fields == (category_fact,)
    assert presentation_facts.category_profile is CategoryProfile.SUNCARE
    assert presentation_facts.category_fields == (category_fact,)
    assert port.calls == [
        (1, CategoryProfile.SUNCARE),
        (1, CategoryProfile.SUNCARE),
    ]


def test_catalog_resolves_card_specification_for_bound_variant() -> None:
    selection = RecordingSelectionFactReader((
        _selection_specification(
            "50ml",
            subject_scope="exact_product",
            variant_scope=None,
        ),
        _selection_specification(
            "30ml",
            subject_scope="exact_variant",
            variant_scope="旅行装",
        ),
    ))
    catalog = CanonicalGuideCatalog(
        fake_reader_factory(price="100"),
        selection_fact_port=selection,
    )

    facts = catalog.get_presentation_facts(
        1,
        variant_scope="旅行装",
    )

    assert facts.variant_scope == "旅行装"
    assert facts.specification == "30ml"
    assert selection.calls == [(1, CategoryProfile.SUNCARE)]


def test_presentation_facts_include_seed_image_asset(real_catalog) -> None:
    canonical = ROOT / "data" / "canonical"
    reader = CanonicalProductReader.from_files(
        manifest_path=canonical / "core_products_v1_manifest.json",
        products_path=canonical / "core_products_v1.jsonl",
    )
    assets = load_seed_product_assets(
        manifest_path=canonical / "seed_product_images_v1_manifest.json",
        products_path=canonical / "seed_product_images_v1.jsonl",
        asset_root=ROOT,
    )
    catalog = CanonicalGuideCatalog(reader, product_assets=assets)

    facts = catalog.get_presentation_facts(55)

    assert facts.image_url == "/static/images/products/tmall_v3_746513552108.png"
    assert facts.detail_url == "https://detail.tmall.com/item.htm?id=746513552108"
    assert "image_missing" not in facts.fact_warnings


def test_catalog_projects_scenario_evidence_without_promoting_unknown(
    real_catalog,
) -> None:
    from app.guide.retrieval.scenario_rules import (
        compile_scenario_requirements,
    )
    from app.guide.understanding.scenario_parsing import (
        parse_scenarios,
    )

    requirements = compile_scenario_requirements(
        parse_scenarios("长时间户外防晒")
    ).evidence_requirements

    evidence = real_catalog.get_scenario_evidence(
        55,
        requirements,
    )

    assert [item.field.value for item in evidence] == [
        "spf_pa",
        "water_resistance",
        "usage",
    ]
    assert all(item.product_id == 55 for item in evidence)
    assert [item.state.value for item in evidence] == [
        "unknown",
        "unknown",
        "unknown",
    ]
    assert all(item.value is None for item in evidence)
