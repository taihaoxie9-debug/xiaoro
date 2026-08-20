from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.guide.retrieval.product_display_assets import (
    ProductDisplayBinding,
    ProductDisplayBindingReader,
    load_product_display_assets,
)
from tools.guide_data.publish_reviewed_product_displays import (
    publish_reviewed_product_display_assets,
)


ROOT = Path(__file__).resolve().parents[3]
DISPLAY_REVIEW = (
    ROOT
    / "docs/audits/smzdm-data/reviewed-product-displays-v1.jsonl"
)


def test_aligned_binding_requires_exact_same_sku_on_all_three_axes() -> None:
    with pytest.raises(ValueError, match="exact SKU equality"):
        ProductDisplayBinding(
            product_id=1,
            display_name="测试商品",
            identity_status="exact_product",
            source_sku="30ml",
            canonical_sku="30ml",
            reference_price_sku="50ml",
            display_specification="30ml",
            price_specification_alignment="aligned",
            source_review_sha256="1" * 64,
            display_review_sha256="2" * 64,
        )


def test_published_display_fields_come_from_main_agent_review(
    tmp_path: Path,
) -> None:
    result = publish_reviewed_product_display_assets(
        review_paths=tuple(sorted(
            (
                ROOT / "docs/audits/smzdm-data/reviewed-products"
            ).glob("product-*-v1.json")
        )),
        display_review_path=DISPLAY_REVIEW,
        output_dir=tmp_path / "display-bindings",
    )
    manifest = json.loads(
        result.manifest_path.read_text(encoding="utf-8")
    )
    reader = ProductDisplayBindingReader(
        load_product_display_assets(
            manifest_path=result.manifest_path,
            expected_manifest_sha256=manifest["manifest_sha256"],
        )
    )

    assert reader.get(80).display_name == "阿玛尼权力持妆PRO粉底液"
    assert reader.get(84).display_name == "花西子玉养空气散粉"
    assert reader.get(115).display_name == "迪奥烈艳蓝金唇膏"
    assert reader.get(115).display_specification == "999丝绒 / 3.5g"


def test_publish_all_reviewed_product_display_bindings(
    tmp_path: Path,
) -> None:
    result = publish_reviewed_product_display_assets(
        review_paths=tuple(sorted(
            (
                ROOT / "docs/audits/smzdm-data/reviewed-products"
            ).glob("product-*-v1.json")
        )),
        display_review_path=DISPLAY_REVIEW,
        output_dir=tmp_path / "display-bindings",
    )
    manifest = json.loads(
        result.manifest_path.read_text(encoding="utf-8")
    )
    assets = load_product_display_assets(
        manifest_path=result.manifest_path,
        expected_manifest_sha256=manifest["manifest_sha256"],
    )

    assert result.record_count == 79
    assert len(assets.records) == 79
    assert result.records_path.name == (
        "product_display_bindings_v1."
        + manifest["records_sha256"]
        + ".jsonl"
    )


def test_conflicted_sku_separates_name_but_not_price_specification(
    tmp_path: Path,
) -> None:
    result = publish_reviewed_product_display_assets(
        review_paths=tuple(sorted(
            (
                ROOT / "docs/audits/smzdm-data/reviewed-products"
            ).glob("product-*-v1.json")
        )),
        display_review_path=DISPLAY_REVIEW,
        output_dir=tmp_path / "display-bindings",
    )
    manifest = json.loads(
        result.manifest_path.read_text(encoding="utf-8")
    )
    reader = ProductDisplayBindingReader(
        load_product_display_assets(
            manifest_path=result.manifest_path,
            expected_manifest_sha256=manifest["manifest_sha256"],
        )
    )

    binding = reader.get(91)

    assert binding.display_name == "玉泽皮肤屏障修护精华乳"
    assert binding.source_sku == "50ml title / 100ml parameters"
    assert binding.canonical_sku == "50ml"
    assert binding.reference_price_sku == "unresolved"
    assert binding.display_specification == "50ml"
    assert binding.price_specification_alignment == "conflict"
    assert reader.price_bound_specification(91) is None


def test_aligned_sku_allows_price_bound_specification(
    tmp_path: Path,
) -> None:
    result = publish_reviewed_product_display_assets(
        review_paths=tuple(sorted(
            (
                ROOT / "docs/audits/smzdm-data/reviewed-products"
            ).glob("product-*-v1.json")
        )),
        display_review_path=DISPLAY_REVIEW,
        output_dir=tmp_path / "display-bindings",
    )
    manifest = json.loads(
        result.manifest_path.read_text(encoding="utf-8")
    )
    reader = ProductDisplayBindingReader(
        load_product_display_assets(
            manifest_path=result.manifest_path,
            expected_manifest_sha256=manifest["manifest_sha256"],
        )
    )

    assert reader.price_bound_specification(52) == "30ml"
