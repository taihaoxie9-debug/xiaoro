"""Build fixed-format contact sheets for manual SMZDM image review."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw


class SmzdmContactSheetError(ValueError):
    """Raised when source images cannot form an ordered review sheet."""


def build_contact_sheets(
    *,
    product_id: int,
    image_dir: str | Path,
    output_dir: str | Path,
) -> tuple[Path, ...]:
    if type(product_id) is not int or product_id < 1:
        raise SmzdmContactSheetError(
            "product_id must be a positive integer"
        )
    source_dir = Path(image_dir)
    rows = _ordered_images(source_dir)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for sheet_index, offset in enumerate(
        range(0, len(rows), 3),
        start=1,
    ):
        canvas = Image.new("RGB", (1800, 960), color="white")
        draw = ImageDraw.Draw(canvas)
        for column, (ordinal, path) in enumerate(
            rows[offset:offset + 3]
        ):
            with Image.open(path) as source:
                rendered = source.convert("RGB")
                rendered.thumbnail((580, 900))
            left = (
                column * 600
                + (600 - rendered.width) // 2
            )
            top = 40 + (900 - rendered.height) // 2
            canvas.paste(rendered, (left, top))
            draw.text(
                (column * 600 + 8, 8),
                f"product {product_id}/{ordinal:03d}",
                fill="black",
            )
        output = (
            destination
            / f"product-{product_id}-sheet-{sheet_index}.png"
        )
        canvas.save(output)
        outputs.append(output)
    return tuple(outputs)


def _ordered_images(
    image_dir: Path,
) -> tuple[tuple[int, Path], ...]:
    if not image_dir.is_dir():
        raise SmzdmContactSheetError(
            "image directory is unavailable"
        )
    rows: list[tuple[int, Path]] = []
    for path in sorted(image_dir.iterdir()):
        if not path.is_file():
            continue
        prefix = path.stem.split("_", 1)[0]
        if not prefix.isdigit():
            continue
        rows.append((int(prefix), path))
    if not rows:
        raise SmzdmContactSheetError(
            "image directory contains no ordered images"
        )
    ordinals = [ordinal for ordinal, _ in rows]
    if ordinals != list(range(1, len(rows) + 1)):
        raise SmzdmContactSheetError(
            "source image ordinals must be consecutive"
        )
    return tuple(rows)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--product-id", type=int, required=True)
    parser.add_argument("--image-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    outputs = build_contact_sheets(
        product_id=args.product_id,
        image_dir=args.image_dir,
        output_dir=args.output_dir,
    )
    for output in outputs:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
