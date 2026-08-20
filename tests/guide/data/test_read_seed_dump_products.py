from __future__ import annotations

from pathlib import Path

import pytest

from tools.guide_data.read_seed_dump_products import (
    SeedDumpError,
    read_seed_dump_products,
)


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).parent / "fixtures/products_copy.sql"
TARGET_PRODUCT_IDS = (
    38,
    42,
    49,
    53,
    55,
    57,
    69,
    79,
    80,
    86,
    91,
    103,
    114,
    120,
    121,
)


def test_reads_only_products_copy_and_decodes_copy_escapes() -> None:
    rows = read_seed_dump_products(FIXTURE, product_ids=(42,))

    assert len(rows) == 1
    assert rows[0].product_id == 42
    assert rows[0].name == "示例\t商品"
    assert rows[0].description == "描述\n第二行"
    assert rows[0].detail_url.endswith("id=998532090974")
    assert rows[0].skincare_info["texture"] == "水液"
    assert rows[0].source_line == 6


def test_returns_requested_rows_sorted_by_product_id() -> None:
    rows = read_seed_dump_products(FIXTURE, product_ids=(49, 42))

    assert [row.product_id for row in rows] == [42, 49]


@pytest.mark.parametrize("product_ids", [(42, 42), (999,)])
def test_rejects_duplicate_or_missing_requested_ids(
    product_ids: tuple[int, ...],
) -> None:
    with pytest.raises(SeedDumpError):
        read_seed_dump_products(FIXTURE, product_ids=product_ids)


def test_rejects_unknown_copy_escape(tmp_path: Path) -> None:
    content = FIXTURE.read_text(encoding="utf-8").replace(
        "示例\\t商品",
        "示例\\x商品",
    )
    malformed = tmp_path / "unknown-escape.sql"
    malformed.write_text(content, encoding="utf-8")

    with pytest.raises(SeedDumpError, match="unknown COPY escape"):
        read_seed_dump_products(malformed, product_ids=(42,))


def test_rejects_unknown_escape_in_unrequested_product_row(
    tmp_path: Path,
) -> None:
    content = FIXTURE.read_text(encoding="utf-8").replace(
        "示例面霜",
        "示例\\x面霜",
    )
    malformed = tmp_path / "unrequested-unknown-escape.sql"
    malformed.write_text(content, encoding="utf-8")

    with pytest.raises(SeedDumpError, match="unknown COPY escape"):
        read_seed_dump_products(malformed, product_ids=(42,))


def test_real_seed_dump_binds_exactly_fifteen_product_ids() -> None:
    rows = read_seed_dump_products(
        ROOT / "data/seed_dump.sql",
        product_ids=TARGET_PRODUCT_IDS,
    )

    assert tuple(row.product_id for row in rows) == TARGET_PRODUCT_IDS
