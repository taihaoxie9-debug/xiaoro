from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.guide.understanding.image_contracts import CanonicalIdentity
from app.guide.retrieval.controlled_product_aliases import (
    ControlledProductAliasRecord,
    ControlledProductAliasRegistry,
)
from app.guide.understanding.semantic_contracts import (
    SemanticProductMention,
)
from app.guide.understanding.contracts import SourceSpan


REPO_ROOT = Path(__file__).resolve().parents[3]


class FakeIdentityCatalog:
    def __init__(
        self,
        identities: dict[int, CanonicalIdentity],
    ) -> None:
        self._identities = identities

    @property
    def product_ids(self) -> frozenset[int]:
        return frozenset(self._identities)

    def get_identity(
        self,
        product_id: int,
    ) -> CanonicalIdentity | None:
        return self._identities.get(product_id)


def _mention(message: str, text: str) -> SemanticProductMention:
    start = message.index(text)
    return SemanticProductMention(
        text=text,
        start=start,
        end=start + len(text),
    )


def _resolver_module():
    return importlib.import_module(
        "app.guide.retrieval.product_name_resolver"
    )


def test_resolved_binding_requires_typed_source_metadata() -> None:
    module = _resolver_module()

    with pytest.raises(ValidationError):
        module.ResolvedProductBinding(
            product_id=53,
            source_text="image_ordinal:2",
        )

    binding = module.ResolvedProductBinding(
        product_id=53,
        source_kind="image_ordinal",
        source_ordinal=2,
        source_text="arbitrary provenance label",
    )

    assert binding.source_kind == "image_ordinal"
    assert binding.source_ordinal == 2


def test_unique_full_names_resolve_two_to_four_canonical_products() -> None:
    module = _resolver_module()
    catalog = FakeIdentityCatalog({
        51: CanonicalIdentity(
            product_id=51,
            brand="安热沙",
            product_name="安热沙智感倍护防晒乳液GB",
        ),
        53: CanonicalIdentity(
            product_id=53,
            brand="理肤泉",
            product_name="理肤泉特护清盈防晒乳 SPF50 PA++++",
        ),
    })
    message = (
        "对比安热沙智感倍护防晒乳液GB和"
        "理肤泉特护清盈防晒乳 SPF50 PA++++"
    )

    resolution = module.ProductNameResolver(catalog).resolve(
        message=message,
        mentions=(
            _mention(message, "安热沙智感倍护防晒乳液GB"),
            _mention(
                message,
                "理肤泉特护清盈防晒乳 SPF50 PA++++",
            ),
        ),
    )

    assert resolution.product_ids == (51, 53)
    assert resolution.issue is None


def test_resolver_rejects_unbound_ambiguous_or_unknown_mentions() -> None:
    module = _resolver_module()
    catalog = FakeIdentityCatalog({
        32: CanonicalIdentity(
            product_id=32,
            brand="兰蔻",
            product_name="兰蔻肌底焕活修护精华液 50ml",
        ),
        129: CanonicalIdentity(
            product_id=129,
            brand="兰蔻",
            product_name="兰蔻肌底焕活修护精华液 50ml",
        ),
    })
    resolver = module.ProductNameResolver(catalog)

    ambiguous_message = "对比兰蔻肌底焕活修护精华液 50ml"
    ambiguous = resolver.resolve(
        message=ambiguous_message,
        mentions=(
            _mention(
                ambiguous_message,
                "兰蔻肌底焕活修护精华液 50ml",
            ),
        ),
    )
    unknown_message = "这个不存在的产品适合我吗"
    unknown = resolver.resolve(
        message=unknown_message,
        mentions=(
            _mention(unknown_message, "不存在的产品"),
        ),
    )
    invalid_span = resolver.resolve(
        message="兰蔻肌底焕活修护精华液 50ml",
        mentions=(
            SemanticProductMention(
                text="兰蔻肌底焕活修护精华液 50ml",
                start=1,
                end=18,
            ),
        ),
    )

    assert ambiguous.product_ids == ()
    assert ambiguous.issue == "ambiguous_reference"
    assert unknown.product_ids == ()
    assert unknown.issue == "missing_reference"
    assert invalid_span.product_ids == ()
    assert invalid_span.issue == "invalid_source_span"


def test_controlled_alias_resolves_without_model_product_id() -> None:
    module = _resolver_module()
    catalog = FakeIdentityCatalog({
        51: CanonicalIdentity(
            product_id=51,
            brand="安热沙",
            product_name="安热沙智感倍护防晒乳液GB",
        ),
    })
    message = "安耐晒小金瓶适合油敏肌吗"

    resolution = module.ProductNameResolver(
        catalog,
        aliases={"安耐晒小金瓶": 51},
    ).resolve(
        message=message,
        mentions=(_mention(message, "安耐晒小金瓶"),),
    )

    assert resolution.product_ids == (51,)
    assert resolution.issue is None


def test_brand_qualified_controlled_aliases_resolve_exact_products() -> None:
    module = _resolver_module()
    catalog = FakeIdentityCatalog({
        34: CanonicalIdentity(
            product_id=34,
            brand="修丽可（SKINCEUTICALS）",
            product_name="修丽可维生素CE复合修护精华液",
        ),
        38: CanonicalIdentity(
            product_id=38,
            brand="理肤泉（LA ROCHE-POSAY）",
            product_name="理肤泉新B5多效修护精华",
        ),
    })
    aliases = ControlledProductAliasRegistry((
        ControlledProductAliasRecord(
            alias="CE精华",
            identity_scope="exact_product",
            product_ids=(34,),
            default_product_id=34,
            source_refs=("a" * 64,),
            review_status="approved",
            review_rationale="审核别名唯一绑定 CE 精华。",
        ),
        ControlledProductAliasRecord(
            alias="B5精华",
            identity_scope="exact_product",
            product_ids=(38,),
            default_product_id=38,
            source_refs=("b" * 64,),
            review_status="approved",
            review_rationale="审核别名唯一绑定 B5 精华。",
        ),
    ))
    resolver = module.ProductNameResolver(
        catalog,
        controlled_aliases=aliases,
    )
    message = "修丽可CE精华和理肤泉B5精华的路线差在哪"

    resolution = resolver.resolve(
        message=message,
        mentions=(
            _mention(message, "修丽可CE精华"),
            _mention(message, "理肤泉B5精华"),
        ),
    )

    assert resolution.product_ids == (34, 38)
    assert resolution.issue is None


def test_brand_qualified_alias_rejects_mismatched_brand() -> None:
    module = _resolver_module()
    catalog = FakeIdentityCatalog({
        34: CanonicalIdentity(
            product_id=34,
            brand="修丽可（SKINCEUTICALS）",
            product_name="修丽可维生素CE复合修护精华液",
        ),
    })
    aliases = ControlledProductAliasRegistry((
        ControlledProductAliasRecord(
            alias="CE精华",
            identity_scope="exact_product",
            product_ids=(34,),
            default_product_id=34,
            source_refs=("a" * 64,),
            review_status="approved",
            review_rationale="审核别名唯一绑定 CE 精华。",
        ),
    ))
    resolver = module.ProductNameResolver(
        catalog,
        controlled_aliases=aliases,
    )
    message = "理肤泉CE精华适合我吗"

    resolution = resolver.resolve(
        message=message,
        mentions=(_mention(message, "理肤泉CE精华"),),
    )

    assert resolution.product_ids == ()
    assert resolution.issue == "missing_reference"


def test_exact_variant_alias_preserves_reviewed_variant_scope() -> None:
    module = _resolver_module()
    catalog = FakeIdentityCatalog({
        118: CanonicalIdentity(
            product_id=118,
            brand="NARS",
            product_name="NARS腮红",
        ),
    })
    aliases = ControlledProductAliasRegistry((
        ControlledProductAliasRecord(
            alias="高潮腮红",
            identity_scope="exact_variant",
            product_ids=(118,),
            default_product_id=118,
            variant_scope="4013色号",
            source_refs=("a" * 64,),
            review_status="approved",
            review_rationale="色号昵称由商品图人工确认。",
        ),
    ))
    message = "看看高潮腮红"

    resolution = module.ProductNameResolver(
        catalog,
        controlled_aliases=aliases,
    ).resolve(
        message=message,
        mentions=(_mention(message, "高潮腮红"),),
    )

    assert resolution.bindings == (
        module.ResolvedProductBinding(
            product_id=118,
            variant_scope="4013色号",
            source_text="高潮腮红",
            source_span=SourceSpan(start=2, end=6),
            source_kind="explicit_product",
        ),
    )
    assert resolution.product_ids == (118,)
    assert resolution.variant_scope_for(118) == "4013色号"
    assert resolution.issue is None


def test_two_variants_of_one_product_are_not_silently_collapsed() -> None:
    module = _resolver_module()
    catalog = FakeIdentityCatalog({
        117: CanonicalIdentity(
            product_id=117,
            brand="Urban Decay",
            product_name="Urban Decay单色眼影",
        ),
    })
    aliases = ControlledProductAliasRegistry((
        ControlledProductAliasRecord(
            alias="茶牛郎",
            identity_scope="exact_variant",
            product_ids=(117,),
            default_product_id=117,
            variant_scope="茶牛郎色",
            source_refs=("a" * 64,),
            review_status="approved",
            review_rationale="色号昵称由商品图人工确认。",
        ),
        ControlledProductAliasRecord(
            alias="冰织女",
            identity_scope="exact_variant",
            product_ids=(117,),
            default_product_id=117,
            variant_scope="冰织女色",
            source_refs=("b" * 64,),
            review_status="approved",
            review_rationale="色号昵称由商品图人工确认。",
        ),
    ))
    message = "对比茶牛郎和冰织女"
    resolver = module.ProductNameResolver(
        catalog,
        controlled_aliases=aliases,
    )

    resolution = resolver.resolve(
        message=message,
        mentions=resolver.find_explicit_mentions(message),
    )

    assert [
        (binding.product_id, binding.variant_scope)
        for binding in resolution.bindings
    ] == [
        (117, "茶牛郎色"),
        (117, "冰织女色"),
    ]
    assert resolution.product_ids == (117,)
    assert resolution.variant_scope_for(117) is None
    assert resolution.issue is None


def test_unique_canonical_prefix_resolves_without_model_product_id() -> None:
    module = _resolver_module()
    catalog = FakeIdentityCatalog({
        56: CanonicalIdentity(
            product_id=56,
            brand="资生堂",
            product_name="蓝胖子防晒霜50ml",
        ),
        57: CanonicalIdentity(
            product_id=57,
            brand="碧柔",
            product_name="碧柔Biore水活防晒水润凝蜜",
        ),
    })
    resolver = module.ProductNameResolver(catalog)
    message = "蓝胖子防晒霜包装上写防水吗"

    resolution = resolver.resolve(
        message=message,
        mentions=(_mention(message, "蓝胖子防晒霜"),),
    )

    assert resolution.product_ids == (56,)
    assert resolution.issue is None


@pytest.mark.parametrize(
    ("brand", "canonical_name", "mention_text"),
    (
        (
            "Biore/碧柔",
            "碧柔Biore水活防晒水润凝蜜",
            "碧柔水活防晒水润凝蜜",
        ),
        (
            "ARMANI/阿玛尼",
            "阿玛尼（ARMANI）权力持妆PRO粉底液#2",
            "阿玛尼权力持妆PRO",
        ),
        (
            "CHANEL/香奈儿",
            "香奈儿五号香水（经典）",
            "香奈儿五号香水经典版",
        ),
    ),
)
def test_canonical_identity_surfaces_allow_brand_and_version_forms(
    brand: str,
    canonical_name: str,
    mention_text: str,
) -> None:
    module = _resolver_module()
    catalog = FakeIdentityCatalog({
        1: CanonicalIdentity(
            product_id=1,
            brand=brand,
            product_name=canonical_name,
        ),
    })
    message = f"请核对{mention_text}的资料"

    resolution = module.ProductNameResolver(catalog).resolve(
        message=message,
        mentions=(_mention(message, mention_text),),
    )

    assert resolution.product_ids == (1,)
    assert resolution.issue is None


def test_derived_identity_surface_stays_ambiguous_for_two_products() -> None:
    module = _resolver_module()
    catalog = FakeIdentityCatalog({
        1: CanonicalIdentity(
            product_id=1,
            brand="Biore/碧柔",
            product_name="碧柔Biore水活防晒水润凝蜜70ml",
        ),
        2: CanonicalIdentity(
            product_id=2,
            brand="Biore/碧柔",
            product_name="碧柔Biore水活防晒水润凝蜜90ml",
        ),
    })
    message = "碧柔水活防晒水润凝蜜怎么选"

    resolution = module.ProductNameResolver(catalog).resolve(
        message=message,
        mentions=(
            _mention(message, "碧柔水活防晒水润凝蜜"),
        ),
    )

    assert resolution.product_ids == ()
    assert resolution.issue == "ambiguous_reference"


def test_finds_explicit_full_canonical_name_when_model_omits_mention() -> None:
    module = _resolver_module()
    catalog = FakeIdentityCatalog({
        56: CanonicalIdentity(
            product_id=56,
            brand="资生堂",
            product_name="蓝胖子防晒霜50ml",
        ),
    })
    resolver = module.ProductNameResolver(catalog)
    name = "蓝胖子防晒霜50ml"
    message = f"{name}包装上到底写没写防水？"

    mentions = resolver.find_explicit_mentions(message)
    resolution = resolver.resolve(
        message=message,
        mentions=mentions,
    )

    assert [(item.text, item.start, item.end) for item in mentions] == [
        (name, 0, len(name)),
    ]
    assert resolution.product_ids == (56,)
    assert resolution.issue is None


def test_canonical_name_prefix_of_longer_mention_resolves() -> None:
    module = _resolver_module()
    name = "阿玛尼权力持妆PRO粉底液#2 暖调白皙30ml遮瑕控油"
    catalog = FakeIdentityCatalog({
        80: CanonicalIdentity(
            product_id=80,
            brand="阿玛尼",
            product_name=name,
        ),
    })
    resolver = module.ProductNameResolver(catalog)
    mention_text = f"{name}新版2号"
    message = f"{mention_text}对应老版哪个色号"

    resolution = resolver.resolve(
        message=message,
        mentions=(_mention(message, mention_text),),
    )

    assert resolution.product_ids == (80,)
    assert resolution.issue is None


def test_two_alias_mentions_for_one_product_collapse_to_one_identity() -> None:
    module = _resolver_module()
    catalog = FakeIdentityCatalog({
        67: CanonicalIdentity(
            product_id=67,
            brand="Elta MD",
            product_name=(
                "Elta MD 氨基酸泡沫洁面乳 / 安妍科泡沫洁面乳"
            ),
        ),
    })
    resolver = module.ProductNameResolver(catalog)
    message = (
        "Elta MD 氨基酸泡沫洁面乳 / "
        "安妍科泡沫洁面乳提亮有人测过吗"
    )

    resolution = resolver.resolve(
        message=message,
        mentions=(
            _mention(message, "Elta MD 氨基酸泡沫洁面乳"),
            _mention(message, "安妍科泡沫洁面乳"),
        ),
    )

    assert resolution.product_ids == (67,)
    assert resolution.issue is None


def test_nonexact_prefix_resolution_stays_fail_closed() -> None:
    module = _resolver_module()
    catalog = FakeIdentityCatalog({
        1: CanonicalIdentity(
            product_id=1,
            brand="兰蔻",
            product_name="兰蔻防晒30ml",
        ),
        2: CanonicalIdentity(
            product_id=2,
            brand="兰蔻",
            product_name="兰蔻防晒50ml",
        ),
    })
    resolver = module.ProductNameResolver(catalog)
    ambiguous_message = "兰蔻防晒哪个好"
    short_message = "兰蔻怎么样"

    ambiguous = resolver.resolve(
        message=ambiguous_message,
        mentions=(_mention(ambiguous_message, "兰蔻防晒"),),
    )
    too_short = resolver.resolve(
        message=short_message,
        mentions=(_mention(short_message, "兰蔻"),),
    )

    assert ambiguous.issue == "ambiguous_reference"
    assert too_short.issue == "missing_reference"


def test_real_catalog_resolver_reads_all_103_canonical_identities() -> None:
    catalog_module = importlib.import_module(
        "app.guide.adapters.catalog"
    )
    module = _resolver_module()
    reader = catalog_module.CanonicalProductReader.from_files(
        manifest_path=(
            REPO_ROOT
            / "data/canonical/core_products_v1_manifest.json"
        ),
        products_path=(
            REPO_ROOT / "data/canonical/core_products_v1.jsonl"
        ),
    )
    catalog = catalog_module.CanonicalIdentityCatalog(reader)
    resolver = module.ProductNameResolver(catalog)
    message = "理肤泉特护清盈防晒乳 SPF50 PA++++适合我吗"

    resolution = resolver.resolve(
        message=message,
        mentions=(
            _mention(
                message,
                "理肤泉特护清盈防晒乳 SPF50 PA++++",
            ),
        ),
    )

    assert len(reader) == 103
    assert resolution.product_ids == (53,)
    assert resolution.issue is None
