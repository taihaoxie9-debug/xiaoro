from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from tools.guide_data.crawl_smzdm_wiki_pages import (
    SmzdmWikiCaptureError,
    WikiDetailImage,
    build_smzdm_wiki_raw_page_record,
    crawl_smzdm_wiki_page,
    ensure_smzdm_wiki_capture_unblocked,
)
from tools.guide_data.crawl_smzdm_product_pages import (
    SmzdmCaptureBlocked,
)


def _detail_image(
    suffix: str,
) -> WikiDetailImage:
    return WikiDetailImage(
        source_url=(
            "https://y.zdmimg.com/202406/19/"
            f"detail-{suffix}.jpg_e600.jpg"
        ),
        content=f"detail-image-{suffix}".encode("ascii"),
        width=600,
        height=734,
    )


def test_wiki_raw_record_preserves_full_ordered_detail_sequence() -> None:
    detail_images = (_detail_image("1"), _detail_image("2"))

    raw = build_smzdm_wiki_raw_page_record(
        canonical_product_id=34,
        page_url="https://wiki.smzdm.com/p/qxpxgwd/",
        captured_at="2026-08-19T00:00:00+00:00",
        page_title="修丽可 CE复合修护精华液 30ml",
        product_title="SKINCEUTICALS 修丽可 CE复合修护精华液 30ml",
        product_introduction="维生素CE复合修护精华液商品介绍。",
        parameter_text="规格 30ml 质地 液体",
        body_text="完整百科页面正文",
        script_urls=(),
        detail_images=detail_images,
    )

    assert raw["source_kind"] == "smzdm_wiki"
    assert raw["detail_image_count"] == 2
    assert raw["detail_image_status"] == "present"
    assert raw["review_sources"] == [
        "parameter_table",
        "product_introduction",
        "detail_images",
    ]
    assert raw["detail_images"] == [
        {
            "ordinal": 1,
            "source_url": detail_images[0].source_url,
            "sha256": hashlib.sha256(detail_images[0].content).hexdigest(),
            "width": 600,
            "height": 734,
        },
        {
            "ordinal": 2,
            "source_url": detail_images[1].source_url,
            "sha256": hashlib.sha256(detail_images[1].content).hexdigest(),
            "width": 600,
            "height": 734,
        },
    ]


def test_wiki_raw_record_accepts_a_page_without_detail_images() -> None:
    raw = build_smzdm_wiki_raw_page_record(
        canonical_product_id=66,
        page_url="https://wiki.smzdm.com/p/2j5jr7/",
        captured_at="2026-08-19T00:00:00+00:00",
        page_title="珂润润浸保湿洁颜泡沫 150ml",
        product_title="珂润润浸保湿洁颜泡沫 150ml",
        product_introduction="按压式泡沫洁面。",
        parameter_text="净含量 150ml",
        body_text="完整百科页面正文",
        script_urls=(),
        detail_images=(),
    )

    assert raw["detail_image_count"] == 0
    assert raw["detail_image_status"] == "absent"
    assert raw["detail_images"] == []
    assert raw["review_sources"] == [
        "parameter_table",
        "product_introduction",
    ]


def test_wiki_raw_record_rejects_aigc_from_product_introduction() -> None:
    with pytest.raises(
        SmzdmWikiCaptureError,
        match="product_introduction must exclude AIGC content",
    ):
        build_smzdm_wiki_raw_page_record(
            canonical_product_id=34,
            page_url="https://wiki.smzdm.com/p/qxpxgwd/",
            captured_at="2026-08-19T00:00:00+00:00",
            page_title="修丽可 CE复合修护精华液 30ml",
            product_title="SKINCEUTICALS 修丽可 CE复合修护精华液 30ml",
            product_introduction="Powered by ZDM-AIGC Engine v0.3",
            parameter_text="规格 30ml",
            body_text="完整百科页面正文",
            script_urls=(),
            detail_images=(_detail_image("1"),),
        )


def test_wiki_raw_record_rejects_non_wiki_page_url() -> None:
    with pytest.raises(
        SmzdmWikiCaptureError,
        match="page_url must be an SMZDM wiki URL",
    ):
        build_smzdm_wiki_raw_page_record(
            canonical_product_id=34,
            page_url="https://www.smzdm.com/p/177322866/",
            captured_at="2026-08-19T00:00:00+00:00",
            page_title="修丽可 CE复合修护精华液 30ml",
            product_title="SKINCEUTICALS 修丽可 CE复合修护精华液 30ml",
            product_introduction="维生素CE复合修护精华液商品介绍。",
            parameter_text="规格 30ml",
            body_text="完整百科页面正文",
            script_urls=(),
            detail_images=(_detail_image("1"),),
        )


def test_wiki_capture_stops_before_body_validation_on_tcaptcha() -> None:
    with pytest.raises(SmzdmCaptureBlocked):
        ensure_smzdm_wiki_capture_unblocked(
            body_text="",
            script_urls=("https://ssl.captcha.qq.com/TCaptcha.js",),
        )


def test_wiki_crawler_fails_closed_when_challenge_has_no_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Page:
        def goto(self, *args, **kwargs) -> None:
            return None

        def wait_for_timeout(self, timeout: int) -> None:
            return None

        def evaluate(self, script: str) -> dict[str, object]:
            assert "document.body?.innerText" in script
            return {
                "bodyText": "",
                "detailImages": [],
                "parameterText": "",
                "productIntroduction": "",
                "productTitle": "",
                "scripts": [
                    "https://ssl.captcha.qq.com/TCaptcha.js"
                ],
                "title": "",
            }

        def close(self) -> None:
            return None

    class Context:
        def new_page(self) -> Page:
            return Page()

        def close(self) -> None:
            return None

    class Browser:
        def new_context(self, **kwargs) -> Context:
            return Context()

        def close(self) -> None:
            return None

    class Playwright:
        chromium = SimpleNamespace(launch=lambda **kwargs: Browser())

        def __enter__(self) -> Playwright:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setitem(
        __import__("sys").modules,
        "playwright.sync_api",
        SimpleNamespace(sync_playwright=lambda: Playwright()),
    )

    with pytest.raises(SmzdmCaptureBlocked):
        crawl_smzdm_wiki_page(
            canonical_product_id=33,
            page_url="https://wiki.smzdm.com/p/60q4dyz/",
        )


def test_wiki_crawler_reads_pd_title_direct_text_without_page_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clean_title = "阿玛尼权力PRO粉底液 #1.6"

    class Page:
        def goto(self, *args, **kwargs) -> None:
            return None

        def wait_for_timeout(self, timeout: int) -> None:
            return None

        def evaluate(self, script: str) -> dict[str, object]:
            assert "'.pd-title'" in script
            assert "Node.TEXT_NODE" in script
            return {
                "bodyText": "百科商品正文",
                "detailImages": [],
                "parameterText": "规格 30ml",
                "productIntroduction": "",
                "productTitle": clean_title,
                "scripts": [],
                "title": (
                    clean_title
                    + "【报价 价格 评测 怎么样】 -什么值得买"
                ),
            }

        def close(self) -> None:
            return None

    class Context:
        def new_page(self) -> Page:
            return Page()

        def close(self) -> None:
            return None

    class Browser:
        def new_context(self, **kwargs) -> Context:
            return Context()

        def close(self) -> None:
            return None

    class Playwright:
        chromium = SimpleNamespace(launch=lambda **kwargs: Browser())

        def __enter__(self) -> Playwright:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setitem(
        __import__("sys").modules,
        "playwright.sync_api",
        SimpleNamespace(sync_playwright=lambda: Playwright()),
    )

    raw, images = crawl_smzdm_wiki_page(
        canonical_product_id=80,
        page_url="https://wiki.smzdm.com/p/pgnnyp7/",
    )

    assert images == ()
    assert raw["product_title"] == clean_title
