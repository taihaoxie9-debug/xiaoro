from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tools.guide_data.extract_saved_page_evidence import (
    SavedPageError,
    extract_saved_page_evidence,
)


FIXTURES = Path(__file__).parent / "fixtures"
TMALL = FIXTURES / "tmall_saved_page.html"
JD = FIXTURES / "jd_saved_page.html"
JD_REAL_SHAPE = FIXTURES / "jd_saved_page_real_shape.html"
JD_SPEC_TABLE = FIXTURES / "jd_saved_page_spec_table.html"


def test_extracts_tmall_embedded_item_sku_parameters_and_reviews() -> None:
    evidence = extract_saved_page_evidence(TMALL)

    assert evidence.platform == "tmall"
    assert evidence.item_id == "998532090974"
    assert evidence.sku_ids == ("6153782938028",)
    assert evidence.title == "示例精华"
    assert evidence.parameters["适用肤质"] == ("干性",)
    assert evidence.parameters["净含量"] == ("30ml",)
    assert evidence.review_count == 1
    assert evidence.reviews[0].feed_id == "1"


def test_extracts_jd_ld_json_identity_and_explicit_parameter_nodes() -> None:
    evidence = extract_saved_page_evidence(JD)

    assert evidence.platform == "jd"
    assert evidence.item_id == "100012345678"
    assert evidence.sku_ids == ("100012345678",)
    assert evidence.title == "示例防晒"
    assert evidence.parameters == {
        "商品名称": ("示例防晒",),
        "适用肤质": ("敏感肌",),
        "防晒指数": ("SPF50+",),
    }
    assert "用户说 SPF30" not in str(evidence.parameters)
    assert "其他商品" not in str(evidence.parameters)


def test_extracts_jd_real_saved_shape_without_adjacent_content_pollution() -> None:
    evidence = extract_saved_page_evidence(JD_REAL_SHAPE)

    assert evidence.platform == "jd"
    assert evidence.item_id == "100098765432"
    assert evidence.sku_ids == ("100098765432",)
    assert evidence.title == "真实形状示例精华"
    assert evidence.parameters == {
        "系列品": ("清爽系列",),
        "规格": ("30ml",),
    }
    assert "用户说是 50ml" not in str(evidence.parameters)
    assert "其他商品 60ml" not in str(evidence.parameters)


def test_extracts_jd_attribute_spec_table_rows() -> None:
    evidence = extract_saved_page_evidence(JD_SPEC_TABLE)

    assert evidence.platform == "jd"
    assert evidence.item_id == "100055667788"
    assert evidence.title == "规格表示例精华"
    assert evidence.parameters["品牌"] == ("示例品牌",)
    assert evidence.parameters["功效"] == ("保湿,修护",)
    assert evidence.parameters["适合肤质"] == ("敏感肌适用",)
    assert evidence.parameters["系列品"] == ("星品系列",)
    assert "其他商品功效" not in str(evidence.parameters)


def test_source_hash_is_bound_to_the_parsed_bytes() -> None:
    evidence = extract_saved_page_evidence(TMALL)

    assert evidence.source_sha256 == hashlib.sha256(
        TMALL.read_bytes()
    ).hexdigest()


def test_saved_page_without_numeric_identity_fails_closed(
    tmp_path: Path,
) -> None:
    source = tmp_path / "unknown.html"
    source.write_text(
        """
        <html><body>
          <section><h2>规格参数</h2>
            <dl><dt>商品名称</dt><dd>无绑定商品</dd></dl>
          </section>
        </body></html>
        """,
        encoding="utf-8",
    )

    with pytest.raises(SavedPageError, match="item identity"):
        extract_saved_page_evidence(source)


def test_saved_page_symlink_is_rejected(tmp_path: Path) -> None:
    link = tmp_path / "linked.html"
    link.symlink_to(TMALL)

    with pytest.raises(SavedPageError, match="regular file"):
        extract_saved_page_evidence(link)
