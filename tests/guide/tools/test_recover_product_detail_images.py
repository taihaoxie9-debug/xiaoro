from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from tools.guide_data.recover_product_detail_images import (
    recover_product_detail_images,
)


def _image(path: Path, color: tuple[int, int, int]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (20, 30), color).save(path, format="JPEG")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_recovery_uses_strict_precedence_and_versions_current_images(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source_ocr"
    image_root = tmp_path / "source_images"
    old_root = tmp_path / "old"
    html_root = tmp_path / "saved"
    current_root = tmp_path / "current"
    current_images = tmp_path / "current_images"
    source_root.mkdir()
    image_root.mkdir()
    old_root.mkdir()
    html_root.mkdir()
    current_root.mkdir()
    current_images.mkdir()

    exact_name = "historical-exact.jpg"
    html_name = "historical-html.jpg"
    changed_name = "historical-changed.jpg"
    blocked_name = "historical-blocked.jpg"
    exact_path = old_root / exact_name
    exact_sha = _image(exact_path, (255, 0, 0))

    companion = html_root / "product_files" / html_name
    html_sha = _image(companion, (0, 255, 0))
    (html_root / "product.html").write_text(
        f'<img src="product_files/{html_name}">',
        encoding="utf-8",
    )

    current_path = current_images / "current-new.jpg"
    current_sha = _image(current_path, (0, 0, 255))
    (current_root / "detail_78_ocr.json").write_text(
        json.dumps(
            {
                "pid": 78,
                "name": "当前商品",
                "images": [
                    {
                        "file": "current-new.jpg",
                        "historical_file": changed_name,
                        "image_sha256": current_sha,
                        "local_image": "../current_images/current-new.jpg",
                        "ocr_text": "当前版本详情",
                        "size": [20, 30],
                        "size_kb": 1.0,
                        "source_url": "https://example.com/current-new.jpg",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    (source_root / "detail_78_ocr.json").write_text(
        json.dumps(
            {
                "pid": 78,
                "name": "历史商品",
                "source_origin": "https://item.example.com/78",
                "images": [
                    {
                        "file": exact_name,
                        "ocr_text": "历史精确图",
                        "size": [20, 30],
                        "size_kb": 1.0,
                    },
                    {
                        "file": html_name,
                        "ocr_text": "保存页图片",
                        "size": [20, 30],
                        "size_kb": 1.0,
                    },
                    {
                        "file": changed_name,
                        "ocr_text": "历史图已变化",
                        "size": [20, 30],
                        "size_kb": 1.0,
                    },
                    {
                        "file": blocked_name,
                        "ocr_text": "无法恢复",
                        "size": [20, 30],
                        "size_kb": 1.0,
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    output_path = tmp_path / "recovery.jsonl"
    result = recover_product_detail_images(
        source_root=source_root,
        image_root=image_root,
        old_asset_roots=(old_root,),
        saved_html_roots=(html_root,),
        current_source_root=current_root,
        output_path=output_path,
    )

    assert result.image_count == 4
    rows = [
        json.loads(line)
        for line in output_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [row["status"] for row in rows] == [
        "recovered_exact",
        "recovered_from_html",
        "current_new_version",
        "blocked",
    ]
    assert rows[0]["image_sha256"] == exact_sha
    assert rows[1]["image_sha256"] == html_sha
    assert rows[2]["image_sha256"] == current_sha
    assert rows[2]["historical_file"] == changed_name
    assert rows[2]["recovered_file"] == "current-new.jpg"
    assert rows[2]["image_sha256"] != rows[0]["image_sha256"]
    assert rows[3]["local_image"] is None
    assert rows[3]["attempts"] == [
        "existing_local",
        "old_asset",
        "saved_html",
        "current_source",
    ]

    for row in rows[:3]:
        local_path = tmp_path / row["local_image"]
        assert local_path.is_file()
        assert hashlib.sha256(local_path.read_bytes()).hexdigest() == (
            row["image_sha256"]
        )


def test_existing_local_image_wins_without_copying_a_replacement(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source_ocr"
    image_root = tmp_path / "source_images"
    source_root.mkdir()
    local = image_root / "78" / "local.jpg"
    local_sha = _image(local, (10, 20, 30))
    old_root = tmp_path / "old"
    old_root.mkdir()
    _image(old_root / "local.jpg", (200, 200, 200))
    (source_root / "detail_78_ocr.json").write_text(
        json.dumps(
            {
                "pid": 78,
                "images": [
                    {
                        "file": "local.jpg",
                        "image_sha256": local_sha,
                        "local_image": "source_images/78/local.jpg",
                        "ocr_text": "本地图",
                        "size": [20, 30],
                        "size_kb": 1.0,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    output_path = tmp_path / "recovery.jsonl"
    recover_product_detail_images(
        source_root=source_root,
        image_root=image_root,
        old_asset_roots=(old_root,),
        saved_html_roots=(),
        current_source_root=None,
        output_path=output_path,
    )
    row = json.loads(output_path.read_text(encoding="utf-8"))

    assert row["status"] == "existing_local"
    assert row["image_sha256"] == local_sha
    assert row["attempts"] == ["existing_local"]
