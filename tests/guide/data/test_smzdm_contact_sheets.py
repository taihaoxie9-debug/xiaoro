from __future__ import annotations

from pathlib import Path

from PIL import Image

from tools.guide_data.build_smzdm_contact_sheets import (
    build_contact_sheets,
)


def test_contact_sheets_preserve_every_ordered_source_image(
    tmp_path: Path,
) -> None:
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    for ordinal in range(1, 5):
        Image.new(
            "RGB",
            (300 + ordinal, 500 + ordinal),
            color=(ordinal * 20, 80, 120),
        ).save(image_dir / f"{ordinal:03d}_source.jpg")

    outputs = build_contact_sheets(
        product_id=33,
        image_dir=image_dir,
        output_dir=tmp_path / "sheets",
    )

    assert [path.name for path in outputs] == [
        "product-33-sheet-1.png",
        "product-33-sheet-2.png",
    ]
    assert all(path.is_file() for path in outputs)
    with Image.open(outputs[0]) as first:
        assert first.size == (1800, 960)
    with Image.open(outputs[1]) as second:
        assert second.size == (1800, 960)
