from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

import pytest

from app.guide.retrieval.category_profiles import CategoryProfile


FIXTURES = Path(__file__).parent / "fixtures"


def _module():
    try:
        return importlib.import_module(
            "tools.guide_data.build_full_catalog_closure"
        )
    except ModuleNotFoundError:
        pytest.fail("full catalog closure builder is missing")


@pytest.mark.parametrize(
    ("profile", "parameter_name", "field_key"),
    (
        (CategoryProfile.SKINCARE, "核心功效", "efficacy"),
        (CategoryProfile.SKINCARE, "肤质问题", "skin_concern"),
        (CategoryProfile.SKINCARE, "面膜分类", "product_form"),
        (CategoryProfile.SKINCARE, "膜布材质", "mask_material"),
        (CategoryProfile.SKINCARE, "香味", "fragrance_description"),
        (CategoryProfile.SUNCARE, "功效", "efficacy"),
        (CategoryProfile.SUNCARE, "防晒指数", "spf_pa"),
        (CategoryProfile.SUNCARE, "成膜速度", "film_speed"),
        (
            CategoryProfile.SUNCARE,
            "防晒光谱",
            "sun_protection_spectrum",
        ),
        (CategoryProfile.BASE_MAKEUP, "遮瑕分类", "product_form"),
        (
            CategoryProfile.BASE_MAKEUP,
            "遮瑕部位",
            "application_area",
        ),
        (
            CategoryProfile.BASE_MAKEUP,
            "颜色分类",
            "variant_option",
        ),
        (CategoryProfile.BASE_MAKEUP, "功效", "efficacy"),
        (CategoryProfile.BASE_MAKEUP, "色号", "shade"),
        (CategoryProfile.BASE_MAKEUP, "防晒指数", "spf_pa"),
        (
            CategoryProfile.COLOR_MAKEUP,
            "颜色分类",
            "variant_option",
        ),
        (CategoryProfile.COLOR_MAKEUP, "色号", "shade"),
        (CategoryProfile.COLOR_MAKEUP, "功效", "efficacy"),
        (
            CategoryProfile.COLOR_MAKEUP,
            "适用肤质",
            "suitable_skin",
        ),
        (CategoryProfile.COLOR_MAKEUP, "色系", "color_family"),
        (CategoryProfile.COLOR_MAKEUP, "颜色数", "color_count"),
        (CategoryProfile.CLEANSER, "卸妆效果", "cleansing_power"),
        (CategoryProfile.CLEANSER, "功效", "efficacy"),
        (
            CategoryProfile.CLEANSER,
            "香型",
            "fragrance_description",
        ),
        (CategoryProfile.FRAGRANCE, "香调", "fragrance_family"),
        (
            CategoryProfile.FRAGRANCE,
            "适用场合",
            "usage_context",
        ),
        (
            CategoryProfile.FRAGRANCE,
            "适用性别",
            "target_audience",
        ),
        (CategoryProfile.SKINCARE, "净含量", "net_content"),
        (CategoryProfile.SUNCARE, "保质期", "shelf_life"),
        (CategoryProfile.FRAGRANCE, "产地", "origin"),
        (
            CategoryProfile.SUNCARE,
            "适用部位",
            "application_area",
        ),
        (
            CategoryProfile.CLEANSER,
            "适用人群",
            "target_audience",
        ),
    ),
)
def test_each_profile_has_its_own_parameter_registry(
    profile: CategoryProfile,
    parameter_name: str,
    field_key: str,
) -> None:
    module = _module()

    rule = module.parameter_rule_for(profile, parameter_name)

    assert rule is not None
    assert rule.field_key == field_key
    assert set(module.parameter_registries()) == set(CategoryProfile)


@pytest.mark.parametrize(
    ("parameter_name", "raw_values", "field_key"),
    (
        ("针对肤质问题", ("干燥缺水",), "skin_concern"),
        (
            "针对肤质问题",
            ("多种肤质（敏感肌除外）",),
            "suitable_skin",
        ),
        ("产品产地", ("法国",), "origin"),
        ("针对肤质问题", ("其他",), None),
        ("产地", ("其他/other",), None),
        (
            "产品产地",
            ("产品批次不同，产品产地以实物为准",),
            None,
        ),
    ),
)
def test_value_sensitive_parameter_routing(
    parameter_name: str,
    raw_values: tuple[str, ...],
    field_key: str | None,
) -> None:
    module = _module()

    rule = module.parameter_rule_for(
        CategoryProfile.SKINCARE,
        parameter_name,
        raw_values,
    )

    assert (rule.field_key if rule is not None else None) == field_key


def test_exact_item_merchant_parameter_has_complete_provenance() -> None:
    module = _module()

    row = module.classify_parameter_group(
        product_id=41,
        category_profile=CategoryProfile.SKINCARE,
        binding_status="exact_item",
        source_sha256="a" * 64,
        item_id="100135988092",
        sku_ids=("100135988092",),
        parameter_name="核心功效",
        raw_values=("美白", "提亮"),
        ordinal=7,
    )

    assert row.disposition == "pending"
    assert row.source_class == "merchant_parameter"
    assert row.field_key == "efficacy"
    assert row.item_id == "100135988092"
    assert row.sku_ids == ("100135988092",)
    assert row.source_locator.startswith(
        f"urn:xiaoro:saved-page:sha256:{'a' * 64}:"
    )
    assert row.raw_value_sha256 == hashlib.sha256(
        b'["\\u7f8e\\u767d","\\u63d0\\u4eae"]'
    ).hexdigest()
    assert len(row.normalized_value_sha256) == 64
    assert "hard_filter" not in row.capability_ceiling


def test_merchant_safety_parameter_is_quarantined() -> None:
    module = _module()

    row = module.classify_parameter_group(
        product_id=41,
        category_profile=CategoryProfile.SKINCARE,
        binding_status="exact_item",
        source_sha256="b" * 64,
        item_id="100135988092",
        sku_ids=("100135988092",),
        parameter_name="是否为特殊用途化妆品",
        raw_values=("否",),
        ordinal=1,
    )

    assert row.disposition == "quarantine"
    assert row.field_key == "safety"
    assert row.reasons == ("insufficient_safety_authority",)


@pytest.mark.parametrize(
    ("parameter_name", "field_key"),
    (
        ("批准文号/备案编号", "safety"),
        ("是否特殊化妆品", "safety"),
        ("禁忌症", "safety"),
        ("结构及组成", "ingredients_present"),
    ),
)
def test_additional_sensitive_parameters_remain_quarantined(
    parameter_name: str,
    field_key: str,
) -> None:
    module = _module()

    row = module.classify_parameter_group(
        product_id=41,
        category_profile=CategoryProfile.SKINCARE,
        binding_status="exact_item",
        source_sha256="b" * 64,
        item_id="100135988092",
        sku_ids=("100135988092",),
        parameter_name=parameter_name,
        raw_values=("商家参数值",),
        ordinal=1,
    )

    assert row.disposition == "quarantine"
    assert row.field_key == field_key
    assert row.reasons == ("insufficient_safety_authority",)


def test_alternate_equivalent_parameter_is_not_auto_promotable() -> None:
    module = _module()

    row = module.classify_parameter_group(
        product_id=36,
        category_profile=CategoryProfile.SKINCARE,
        binding_status="alternate_equivalent",
        source_sha256="c" * 64,
        item_id="100092327970",
        sku_ids=("100092327970",),
        parameter_name="功效",
        raw_values=("美白",),
        ordinal=1,
    )

    assert row.disposition == "quarantine"
    assert row.reasons == ("alternate_equivalent_requires_review",)


def test_unregistered_parameter_is_explicitly_not_applicable() -> None:
    module = _module()

    row = module.classify_parameter_group(
        product_id=41,
        category_profile=CategoryProfile.SKINCARE,
        binding_status="exact_item",
        source_sha256="d" * 64,
        item_id="100135988092",
        sku_ids=("100135988092",),
        parameter_name="生产厂家地址",
        raw_values=("某地址",),
        ordinal=1,
    )

    assert row.disposition == "not_applicable"
    assert row.field_key is None
    assert row.reasons == ("outside_recommendation_registry",)


def test_special_product_bindings_are_explicit() -> None:
    module = _module()

    assert {
        product_id: (binding.status, binding.alternate_item_id)
        for product_id, binding
        in module.special_product_bindings().items()
    } == {
        36: ("alternate_equivalent", "100092327970"),
        53: ("source_gap", None),
        70: ("alternate_equivalent", "100238733259"),
        106: ("source_gap", None),
        144: ("alternate_equivalent", "2387902"),
    }


def test_promotion_candidate_is_content_addressed_and_hash_bound() -> None:
    module = _module()
    classification = module.classify_parameter_group(
        product_id=41,
        category_profile=CategoryProfile.SKINCARE,
        binding_status="exact_item",
        source_sha256="e" * 64,
        item_id="100135988092",
        sku_ids=("100135988092",),
        parameter_name="核心功效",
        raw_values=("美白",),
        ordinal=1,
    )

    candidate = module.promotion_candidate_row(classification)

    assert len(candidate["candidate_id"]) == 64
    assert candidate["value_sha256"] == (
        classification.normalized_value_sha256
    )
    assert classification.raw_value_sha256 in candidate["source_locator"]
    assert (
        classification.normalized_value_sha256
        in candidate["source_locator"]
    )
    assert candidate["source_class"] == "merchant_parameter"
    assert candidate["status"] == "pending"


def test_product_matrix_preserves_every_state_and_readiness() -> None:
    module = _module()
    classification = module.classify_parameter_group(
        product_id=41,
        category_profile=CategoryProfile.SKINCARE,
        binding_status="exact_item",
        source_sha256="f" * 64,
        item_id="100135988092",
        sku_ids=("100135988092",),
        parameter_name="核心功效",
        raw_values=("美白",),
        ordinal=1,
    )
    canonical = {
        "product_id": 41,
        "fields": {
            "product_identity": {
                "resolved_state": "known",
                "value": "示例精华",
            },
            "brand": {"resolved_state": "known", "value": "示例品牌"},
            "category": {"resolved_state": "known", "value": "精华液"},
            "price": {"resolved_state": "known", "value": 299},
            "efficacy": {"resolved_state": "unknown", "value": None},
        },
    }

    row = module.build_product_state_row(
        canonical_product=canonical,
        category_profile=CategoryProfile.SKINCARE,
        binding_status="exact_item",
        classifications=(classification,),
    )

    assert row["field_states"]["product_identity"] == "known"
    assert row["field_states"]["efficacy"] == "pending"
    assert row["field_states"]["mechanism"] == "unknown"
    assert row["field_states"]["spf_pa"] == "not_applicable"
    assert row["state_counts"]["pending"] == 1
    assert row["state_counts"]["not_applicable"] > 0
    assert row["readiness"] == "ready"


def test_rendered_jsonl_is_byte_stable() -> None:
    module = _module()
    classification = module.classify_parameter_group(
        product_id=41,
        category_profile=CategoryProfile.SKINCARE,
        binding_status="exact_item",
        source_sha256="1" * 64,
        item_id="100135988092",
        sku_ids=("100135988092",),
        parameter_name="核心功效",
        raw_values=("提亮", "美白"),
        ordinal=2,
    )

    first = module.render_classifications((classification,))
    second = module.render_classifications((classification,))

    assert first == second
    assert hashlib.sha256(first).hexdigest() == hashlib.sha256(
        second
    ).hexdigest()


def test_small_frozen_inventory_build_is_complete_and_repeatable(
    tmp_path: Path,
) -> None:
    module = _module()
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    inventory_rows = []
    root_id = hashlib.sha256(
        b"guide-source-root-v1\0approved-root-0001"
    ).hexdigest()
    for index, fixture_name in enumerate(
        ("tmall_saved_page.html", "jd_saved_page.html"),
        start=1,
    ):
        content = (FIXTURES / fixture_name).read_bytes()
        relative_name = f"saved-{index}.html"
        (downloads / relative_name).write_bytes(content)
        inventory_rows.append(
            {
                "content_type": "html",
                "relative_name": relative_name,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
                "source_root_id": root_id,
            }
        )
    inventory = tmp_path / "inventory.jsonl"
    inventory_bytes = b"".join(
        (
            json.dumps(
                row,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        for row in sorted(
            inventory_rows,
            key=lambda row: (
                row["sha256"],
                row["relative_name"],
            ),
        )
    )
    inventory.write_bytes(inventory_bytes)
    arguments = {
        "inventory_path": inventory,
        "downloads_root": downloads,
        "seed_dump_path": FIXTURES / "products_copy.sql",
        "canonical_products_path": (
            FIXTURES / "canonical_products.jsonl"
        ),
        "expected_inventory_sha256": hashlib.sha256(
            inventory_bytes
        ).hexdigest(),
        "expected_inventory_count": 2,
        "expected_saved_page_count": 2,
        "expected_parseable_page_count": 2,
        "expected_parameter_group_count": 7,
        "expected_canonical_product_count": 2,
        "expected_exact_item_product_count": 2,
    }

    first = module.build_full_catalog_closure(
        output_dir=tmp_path / "first",
        **arguments,
    )
    second = module.build_full_catalog_closure(
        output_dir=tmp_path / "second",
        **arguments,
    )

    assert first.inventory_count == 2
    assert first.saved_page_count == 2
    assert first.parseable_page_count == 2
    assert first.parameter_group_count == 7
    assert first.silently_skipped == 0
    assert first.canonical_product_count == 2
    assert first.exact_item_product_count == 2
    assert first.product_matrix_count == 2
    assert first.pending_candidate_count == 4
    assert first.artifact_sha256 == second.artifact_sha256
