from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.guide.adapters.catalog import CanonicalProductReader
from app.guide.adapters.catalog.canonical_identity_catalog import (
    CanonicalIdentityCatalog,
)
from app.guide.retrieval.controlled_product_aliases import (
    ControlledProductAliasRegistry,
    load_controlled_product_aliases,
)
from app.guide.retrieval.product_name_resolver import ProductNameResolver


ROOT = Path(__file__).resolve().parents[3]
CANONICAL = ROOT / "data" / "canonical"


def _resolver() -> tuple[
    ProductNameResolver,
    ControlledProductAliasRegistry,
]:
    reader = CanonicalProductReader.from_files(
        manifest_path=CANONICAL / "core_products_v1_manifest.json",
        products_path=CANONICAL / "core_products_v1.jsonl",
    )
    aliases = load_controlled_product_aliases(
        manifest_path=(
            CANONICAL / "controlled_product_aliases_v1_manifest.json"
        ),
        aliases_path=(
            CANONICAL / "controlled_product_aliases_v1.jsonl"
        ),
        catalog=CanonicalIdentityCatalog(reader),
        canonical_sha256=json.loads(
            (
                CANONICAL / "core_products_v1_manifest.json"
            ).read_text(encoding="utf-8")
        )["products_sha256"],
    )
    return (
        ProductNameResolver(
            CanonicalIdentityCatalog(reader),
            controlled_aliases=aliases,
        ),
        aliases,
    )


def test_flagship_nicknames_bind_current_serum_products() -> None:
    resolver, _ = _resolver()
    message = "帮我对比兰蔻小黑瓶和小棕瓶"

    mentions = resolver.find_explicit_mentions(message)
    resolution = resolver.resolve(
        message=message,
        mentions=mentions,
    )

    assert [item.text for item in mentions] == [
        "兰蔻小黑瓶",
        "小棕瓶",
    ]
    assert resolution.product_ids == (129, 33)
    assert resolution.issue is None


def test_specific_nicknames_override_product_family_defaults() -> None:
    resolver, _ = _resolver()
    serum_message = "超修小黑瓶适合我吗"
    eye_message = "小棕瓶眼霜适合我吗"

    serum = resolver.resolve(
        message=serum_message,
        mentions=resolver.find_explicit_mentions(serum_message),
    )
    eye = resolver.resolve(
        message=eye_message,
        mentions=resolver.find_explicit_mentions(eye_message),
    )

    assert serum.product_ids == (129,)
    assert serum.issue is None
    assert eye.product_ids == (135,)
    assert eye.issue is None


def test_generic_black_bottle_requires_version_for_formula_or_safety() -> None:
    resolver, _ = _resolver()

    for message in (
        "小黑瓶含酒精吗",
        "小黑瓶配方适合敏感肌吗",
        "小黑瓶经典版和超修版有什么区别",
    ):
        resolution = resolver.resolve(
            message=message,
            mentions=resolver.find_explicit_mentions(message),
        )

        assert resolution.product_ids == ()
        assert resolution.issue == "ambiguous_reference"


def test_alias_records_are_reviewed_and_bind_existing_products() -> None:
    _, aliases = _resolver()

    assert aliases.default_product_id("小黑瓶") == 129
    assert aliases.default_product_id("小棕瓶") == 33
    assert aliases.default_product_id("小棕瓶眼霜") == 135
    assert all(
        record.review_status == "approved"
        and record.source_refs
        and all(len(source_ref) == 64 for source_ref in record.source_refs)
        for record in aliases.records
    )


@pytest.mark.parametrize(
    ("alias", "product_id"),
    (
        ("神仙水", 59),
        ("健康水", 106),
        ("樱花水", 62),
        ("前男友面膜", 76),
        ("三色遮瑕", 111),
        ("菁纯气垫", 109),
        ("CPB长管", 112),
        ("夜胶原霜", 47),
        ("传奇洁颜霜", 104),
        ("红腰子", 37),
        ("双抗精华", 41),
        ("CE精华", 34),
        ("玉泽屏障修护精华", 91),
        ("小白瓶", 36),
        ("小金瓶", 51),
        ("绿宝瓶", 39),
        ("紫米精华", 35),
        ("蓝胖子", 56),
        ("紫熨斗", 73),
        ("大白饼", 81),
        ("小方瓶", 83),
    ),
)
def test_reviewed_catalog_aliases_resolve_exact_products(
    alias: str,
    product_id: int,
) -> None:
    resolver, aliases = _resolver()
    message = f"{alias}适合我吗"

    resolution = resolver.resolve(
        message=message,
        mentions=resolver.find_explicit_mentions(message),
    )

    assert aliases.default_product_id(alias) == product_id
    assert resolution.product_ids == (product_id,)
    assert resolution.issue is None


@pytest.mark.parametrize(
    "alias",
    (
        "B5",
        "菁纯",
        "粉水",
        "琥珀",
        "小白管",
        "金盏花水",
        "菌菇水",
    ),
)
def test_multi_sku_family_aliases_always_require_clarification(
    alias: str,
) -> None:
    resolver, aliases = _resolver()
    message = f"{alias}适合我吗"

    mentions = resolver.find_explicit_mentions(message)
    resolution = resolver.resolve(
        message=message,
        mentions=mentions,
    )

    assert [item.text for item in mentions] == [alias]
    assert aliases.default_product_id(alias) is None
    assert len(aliases.candidate_product_ids(alias)) >= 2
    assert resolution.product_ids == ()
    assert resolution.issue == "ambiguous_reference"


@pytest.mark.parametrize(
    ("alias", "product_id", "variant_scope"),
    (
        (
            "茶牛郎",
            117,
            "茶牛郎 / CRUSHIN' HARD / 坠落银河",
        ),
        (
            "冰织女",
            117,
            "冰织女 / COSMIC COWGIRL / 星际牧女",
        ),
        (
            "钻石狗",
            117,
            "钻石狗 / DIAMOND DOG / 钻石犬",
        ),
        (
            "牛郎色",
            117,
            "牛郎色 / SPACE COWBOY / 银河牛仔",
        ),
        (
            "高潮腮红",
            118,
            "4013色号",
        ),
    ),
)
def test_variant_aliases_retain_reviewed_scope(
    alias: str,
    product_id: int,
    variant_scope: str,
) -> None:
    resolver, aliases = _resolver()
    message = f"{alias}是什么颜色"
    record = aliases.record_for(alias)

    resolution = resolver.resolve(
        message=message,
        mentions=resolver.find_explicit_mentions(message),
    )

    assert record is not None
    assert record.identity_scope == "exact_variant"
    assert record.variant_scope == variant_scope
    assert resolution.product_ids == (product_id,)
    assert resolution.issue is None


def test_marketing_and_ingredient_nicknames_are_not_product_mentions() -> None:
    resolver, aliases = _resolver()

    for excluded in ("油皮救星", "冰川蛋白", "律波肽"):
        assert aliases.record_for(excluded) is None
        assert resolver.find_explicit_mentions(
            f"{excluded}到底是什么"
        ) == ()
