from __future__ import annotations

import hashlib

import pytest

from tools.guide_data.crawl_smzdm_product_pages import (
    SmzdmCaptureBlocked,
    SmzdmCaptureError,
    build_raw_page_record,
    is_smzdm_capture_blocked,
)


def test_captcha_page_is_blocked_without_becoming_product_content() -> None:
    assert is_smzdm_capture_blocked(
        body_text="",
        script_urls=("https://ssl.captcha.qq.com/TCaptcha.js",),
    )

    with pytest.raises(SmzdmCaptureBlocked):
        build_raw_page_record(
            canonical_product_id=33,
            page_url="https://www.smzdm.com/p/180595258/",
            captured_at="2026-08-19T00:00:00+00:00",
            page_title="",
            product_title="",
            page_specification="",
            main_image_url="",
            main_image_bytes=b"",
            raw_product_introduction="",
            body_text="",
            script_urls=(
                "https://ssl.captcha.qq.com/TCaptcha.js",
            ),
        )


def test_raw_capture_is_hash_bound_and_excludes_aigc_sections() -> None:
    image = b"smzdm-main-image"
    raw = build_raw_page_record(
        canonical_product_id=33,
        page_url="https://www.smzdm.com/p/180595258/",
        captured_at="2026-08-19T00:00:00+00:00",
        page_title="雅诗兰黛小棕瓶第七代 100ml",
        product_title="雅诗兰黛小棕瓶第七代 100ml",
        page_specification="100ml",
        main_image_url="https://qny.smzdm.com/image.jpg",
        main_image_bytes=image,
        raw_product_introduction="主打成分：三肽-32；核心技术：Chronolux。",
        body_text=(
            "商品介绍 主打成分：三肽-32；核心技术：Chronolux。"
            " Powered by ZDM-AIGC Engine v0.3 优势 建议"
        ),
        script_urls=(),
    )

    assert raw["main_image_sha256"] == hashlib.sha256(image).hexdigest()
    assert raw["raw_page_text_sha256"] == hashlib.sha256(
        (
            "商品介绍 主打成分：三肽-32；核心技术：Chronolux。"
            " Powered by ZDM-AIGC Engine v0.3 优势 建议"
        ).encode("utf-8")
    ).hexdigest()
    assert raw["excluded_sections"] == [
        "Powered by ZDM-AIGC Engine v0.3",
        "优势",
        "建议",
    ]


def test_raw_capture_rejects_aigc_text_as_product_introduction() -> None:
    with pytest.raises(
        SmzdmCaptureError,
        match="raw_product_introduction must exclude AIGC content",
    ):
        build_raw_page_record(
            canonical_product_id=33,
            page_url="https://www.smzdm.com/p/180595258/",
            captured_at="2026-08-19T00:00:00+00:00",
            page_title="雅诗兰黛小棕瓶第七代 100ml",
            product_title="雅诗兰黛小棕瓶第七代 100ml",
            page_specification="100ml",
            main_image_url="https://qny.smzdm.com/image.jpg",
            main_image_bytes=b"image",
            raw_product_introduction=(
                "Powered by ZDM-AIGC Engine v0.3 的建议"
            ),
            body_text="商品介绍",
            script_urls=(),
        )
