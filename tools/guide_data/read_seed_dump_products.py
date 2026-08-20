"""Read selected products from the exact PostgreSQL COPY text section."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Sequence


PRODUCT_COLUMNS = (
    "id",
    "name",
    "category",
    "brand",
    "price",
    "original_price",
    "description",
    "specifications",
    "image_url",
    "detail_url",
    "platform",
    "stock",
    "sales_count",
    "rating",
    "review_count",
    "created_at",
    "updated_at",
    "specs",
    "tags",
    "skincare_info",
)
_PRODUCT_COPY_HEADER = (
    f"COPY public.products ({', '.join(PRODUCT_COLUMNS)}) FROM stdin;"
)
_COPY_ESCAPES = {
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
    "\\": "\\",
}
_NULLABLE_COLUMNS = frozenset(
    {
        "category",
        "brand",
        "price",
        "original_price",
        "description",
        "specifications",
        "image_url",
        "detail_url",
        "platform",
        "rating",
        "specs",
        "tags",
        "skincare_info",
    }
)


class SeedDumpError(ValueError):
    """Raised when the trusted products COPY section is malformed."""


@dataclass(frozen=True, slots=True)
class SeedProductRow:
    product_id: int
    name: str
    category: str
    brand: str
    price: Decimal
    description: str
    specifications: dict[str, object]
    detail_url: str | None
    platform: str
    specs: dict[str, object] | None
    skincare_info: dict[str, object]
    source_sha256: str
    source_line: int


def read_seed_dump_products(
    path: str | Path,
    *,
    product_ids: Sequence[int],
) -> tuple[SeedProductRow, ...]:
    """Return exactly the requested rows from ``public.products``."""

    requested = _validate_product_ids(product_ids)
    content = _read_regular_bytes(Path(path))
    source_sha256 = hashlib.sha256(content).hexdigest()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SeedDumpError("seed dump must be UTF-8") from exc

    lines = text.splitlines()
    header_indexes = [
        index
        for index, line in enumerate(lines)
        if line == _PRODUCT_COPY_HEADER
    ]
    if len(header_indexes) != 1:
        raise SeedDumpError(
            "seed dump must contain one exact products COPY section"
        )

    selected: dict[int, SeedProductRow] = {}
    found_terminator = False
    for index in range(header_indexes[0] + 1, len(lines)):
        raw_line = lines[index]
        if raw_line == r"\.":
            found_terminator = True
            break
        raw_columns = raw_line.split("\t")
        if len(raw_columns) != len(PRODUCT_COLUMNS):
            raise SeedDumpError(
                f"products COPY row {index + 1} must contain 20 columns"
            )
        values = {
            column: _decode_copy_value(
                raw_value,
                column=column,
                line_number=index + 1,
            )
            for column, raw_value in zip(PRODUCT_COLUMNS, raw_columns)
        }
        product_id = _parse_product_id(
            values["id"],
            line_number=index + 1,
        )
        if product_id not in requested:
            continue
        if product_id in selected:
            raise SeedDumpError(
                f"duplicate products COPY row for product {product_id}"
            )
        selected[product_id] = _build_product_row(
            values,
            source_sha256=source_sha256,
            source_line=index + 1,
        )

    if not found_terminator:
        raise SeedDumpError("products COPY section is not terminated")
    missing = sorted(set(requested) - set(selected))
    if missing:
        raise SeedDumpError(
            "products COPY section is missing requested IDs: "
            + ",".join(str(product_id) for product_id in missing)
        )
    return tuple(selected[product_id] for product_id in sorted(selected))


def _validate_product_ids(product_ids: Sequence[int]) -> frozenset[int]:
    values = tuple(product_ids)
    if (
        not values
        or any(type(value) is not int or value <= 0 for value in values)
        or len(values) != len(set(values))
    ):
        raise SeedDumpError(
            "product_ids must be unique positive integers"
        )
    return frozenset(values)


def _decode_copy_value(
    raw_value: str,
    *,
    column: str,
    line_number: int,
) -> str | None:
    if raw_value == r"\N":
        if column not in _NULLABLE_COLUMNS:
            raise SeedDumpError(
                f"products COPY row {line_number} has null {column}"
            )
        return None

    decoded: list[str] = []
    index = 0
    while index < len(raw_value):
        character = raw_value[index]
        if character != "\\":
            decoded.append(character)
            index += 1
            continue
        if index + 1 >= len(raw_value):
            raise SeedDumpError(
                f"products COPY row {line_number} has trailing escape"
            )
        escaped = raw_value[index + 1]
        replacement = _COPY_ESCAPES.get(escaped)
        if replacement is None:
            raise SeedDumpError(
                f"products COPY row {line_number} has unknown COPY escape"
            )
        decoded.append(replacement)
        index += 2
    return "".join(decoded)


def _parse_product_id(
    value: str | None,
    *,
    line_number: int,
) -> int:
    try:
        product_id = int(value) if value is not None else 0
    except ValueError as exc:
        raise SeedDumpError(
            f"products COPY row {line_number} has invalid id"
        ) from exc
    if product_id <= 0 or str(product_id) != value:
        raise SeedDumpError(
            f"products COPY row {line_number} has invalid id"
        )
    return product_id


def _build_product_row(
    values: dict[str, str | None],
    *,
    source_sha256: str,
    source_line: int,
) -> SeedProductRow:
    product_id = _parse_product_id(
        values["id"],
        line_number=source_line,
    )
    price_text = _required(
        values["price"],
        column="price",
        line_number=source_line,
    )
    try:
        price = Decimal(price_text)
    except InvalidOperation as exc:
        raise SeedDumpError(
            f"products COPY row {source_line} has invalid price"
        ) from exc
    if not price.is_finite():
        raise SeedDumpError(
            f"products COPY row {source_line} has invalid price"
        )

    return SeedProductRow(
        product_id=product_id,
        name=_required(
            values["name"],
            column="name",
            line_number=source_line,
        ),
        category=_required(
            values["category"],
            column="category",
            line_number=source_line,
        ),
        brand=_required(
            values["brand"],
            column="brand",
            line_number=source_line,
        ),
        price=price,
        description=values["description"] or "",
        specifications=_json_object(
            values["specifications"],
            column="specifications",
            line_number=source_line,
            nullable=False,
        ),
        detail_url=values["detail_url"],
        platform=_required(
            values["platform"],
            column="platform",
            line_number=source_line,
        ),
        specs=_json_object(
            values["specs"],
            column="specs",
            line_number=source_line,
            nullable=True,
        ),
        skincare_info=_json_object(
            values["skincare_info"],
            column="skincare_info",
            line_number=source_line,
            nullable=False,
        ),
        source_sha256=source_sha256,
        source_line=source_line,
    )


def _required(
    value: str | None,
    *,
    column: str,
    line_number: int,
) -> str:
    if value is None or not value:
        raise SeedDumpError(
            f"products COPY row {line_number} has empty {column}"
        )
    return value


def _json_object(
    value: str | None,
    *,
    column: str,
    line_number: int,
    nullable: bool,
) -> dict[str, object] | None:
    if value is None:
        if nullable:
            return None
        raise SeedDumpError(
            f"products COPY row {line_number} has null {column}"
        )
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SeedDumpError(
            f"products COPY row {line_number} has invalid {column}"
        ) from exc
    if not isinstance(parsed, dict):
        raise SeedDumpError(
            f"products COPY row {line_number} has non-object {column}"
        )
    return parsed


def _read_regular_bytes(path: Path) -> bytes:
    descriptor = -1
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(
            metadata.st_mode
        ):
            raise SeedDumpError("seed dump must be a regular file")
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != metadata.st_dev
            or opened.st_ino != metadata.st_ino
        ):
            raise SeedDumpError("seed dump changed while opening")
        with os.fdopen(descriptor, "rb") as source:
            descriptor = -1
            content = source.read()
        observed = path.lstat()
        if (
            observed.st_dev != metadata.st_dev
            or observed.st_ino != metadata.st_ino
            or observed.st_size != metadata.st_size
            or observed.st_mtime_ns != metadata.st_mtime_ns
        ):
            raise SeedDumpError("seed dump changed while reading")
        return content
    except SeedDumpError:
        raise
    except OSError as exc:
        raise SeedDumpError("seed dump could not be read") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
