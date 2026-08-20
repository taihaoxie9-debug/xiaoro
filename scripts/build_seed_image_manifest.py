from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any


JSONL_NAME = "seed_product_images_v1.jsonl"
MANIFEST_NAME = "seed_product_images_v1_manifest.json"
SCHEMA_VERSION = "seed-product-images-v1"
MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def product_image_rows(
    *,
    root: Path,
    seed_dump: Path,
) -> list[dict[str, Any]]:
    columns: list[str] | None = None
    in_products = False
    rows: list[dict[str, Any]] = []

    for raw_line in seed_dump.read_text(
        encoding="utf-8"
    ).splitlines():
        if raw_line.startswith("COPY public.products ("):
            column_text = raw_line.split("(", 1)[1].split(
                ") FROM stdin;",
                1,
            )[0]
            columns = [
                item.strip()
                for item in column_text.split(",")
            ]
            in_products = True
            continue
        if not in_products:
            continue
        if raw_line == r"\.":
            break
        assert columns is not None
        values = next(csv.reader(
            [raw_line],
            delimiter="\t",
            quoting=csv.QUOTE_NONE,
        ))
        if len(values) != len(columns):
            raise ValueError("invalid products COPY row width")
        record = dict(zip(columns, values))
        product_id = int(record["id"])
        image_url = record["image_url"].strip()
        if not image_url.startswith("/static/images/products/"):
            raise ValueError(
                f"invalid product image URL: {product_id}"
            )
        relative_path = f"app{image_url}"
        image_path = root / relative_path
        if not image_path.is_file():
            raise FileNotFoundError(
                f"missing product image: {product_id}"
            )
        media_type = MEDIA_TYPES.get(
            image_path.suffix.lower()
        )
        if media_type is None:
            raise ValueError(
                f"unsupported image type: {product_id}"
            )
        rows.append({
            "product_id": product_id,
            "image_url": image_url,
            "relative_path": relative_path,
            "media_type": media_type,
            "bytes": image_path.stat().st_size,
            "source_image_sha256": sha256_path(image_path),
        })

    rows.sort(key=lambda item: item["product_id"])
    if len(rows) != 103:
        raise ValueError(
            f"expected 103 product images, got {len(rows)}"
        )
    if len({item["product_id"] for item in rows}) != 103:
        raise ValueError("duplicate product ID")
    if len({item["image_url"] for item in rows}) != 103:
        raise ValueError("duplicate product image URL")
    return rows


def build_seed_image_manifest(
    *,
    root: Path,
    seed_dump: Path,
    output_dir: Path,
) -> dict[str, Any]:
    rows = product_image_rows(
        root=root,
        seed_dump=seed_dump,
    )
    jsonl_text = "\n".join(
        canonical_json(row)
        for row in rows
    ) + "\n"
    jsonl_path = output_dir / JSONL_NAME
    atomic_write(jsonl_path, jsonl_text)

    source_digest_text = "\n".join(
        (
            f"{row['product_id']}\t"
            f"{row['source_image_sha256']}"
        )
        for row in rows
    )
    manifest_base = {
        "schema_version": SCHEMA_VERSION,
        "products_file": JSONL_NAME,
        "product_count": len(rows),
        "seed_dump_sha256": sha256_path(seed_dump),
        "products_sha256": hashlib.sha256(
            jsonl_text.encode("utf-8")
        ).hexdigest(),
        "source_images_sha256": hashlib.sha256(
            source_digest_text.encode("utf-8")
        ).hexdigest(),
    }
    manifest = {
        **manifest_base,
        "manifest_sha256": hashlib.sha256(
            canonical_json(manifest_base).encode("utf-8")
        ).hexdigest(),
    }
    atomic_write(
        output_dir / MANIFEST_NAME,
        canonical_json(manifest) + "\n",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument(
        "--seed-dump",
        type=Path,
        default=Path("data/seed_dump.sql"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/canonical"),
    )
    args = parser.parse_args()
    manifest = build_seed_image_manifest(
        root=args.root.resolve(),
        seed_dump=args.seed_dump.resolve(),
        output_dir=args.output_dir.resolve(),
    )
    print(canonical_json(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
