from __future__ import annotations

import pytest

from tools.guide_data import crawl_jd_detail_ocr


JdDetailCrawlError = crawl_jd_detail_ocr.JdDetailCrawlError
extract_jd_detail_image_urls = (
    crawl_jd_detail_ocr.extract_jd_detail_image_urls
)
validate_jd_page_identity = crawl_jd_detail_ocr.validate_jd_page_identity


def test_extracts_ordered_unique_jd_detail_images_only() -> None:
    html = """
    <style>
    .a { background-image:url(//img30.360buyimg.com/sku/a.jpg); }
    .b { background-image: url("//img30.360buyimg.com/sku/b.png"); }
    .dup { background-image:url(//img30.360buyimg.com/sku/a.jpg); }
    .ad { background-image:url(//img30.360buyimg.com/jdphoto/ad.jpg); }
    </style>
    <img src="//img30.360buyimg.com/sku/c.webp">
    """

    assert extract_jd_detail_image_urls(html) == (
        "https://img30.360buyimg.com/sku/a.jpg",
        "https://img30.360buyimg.com/sku/b.png",
        "https://img30.360buyimg.com/sku/c.webp",
    )


def test_page_identity_requires_exact_sku_and_nonempty_title() -> None:
    assert validate_jd_page_identity(
        {
            "sku": "100314852272",
            "title": "薇诺娜舒敏保湿丝滑面贴膜6片",
        },
        expected_sku="100314852272",
    ) == "薇诺娜舒敏保湿丝滑面贴膜6片"

    with pytest.raises(JdDetailCrawlError, match="SKU mismatch"):
        validate_jd_page_identity(
            {"sku": "100314852273", "title": "其他商品"},
            expected_sku="100314852272",
        )

    with pytest.raises(JdDetailCrawlError, match="title"):
        validate_jd_page_identity(
            {"sku": "100314852272", "title": ""},
            expected_sku="100314852272",
        )


def test_parses_strict_jd_description_jsonp_and_rejects_empty_data() -> None:
    parse_response = getattr(
        crawl_jd_detail_ocr,
        "parse_jd_description_response",
        None,
    )
    assert callable(parse_response), (
        "crawl must parse the public JD description response"
    )

    assert parse_response(
        'showdesc({"content":"<img '
        'src=\\"//img30.360buyimg.com/sku/a.jpg\\">"});'
    ) == '<img src="//img30.360buyimg.com/sku/a.jpg">'

    with pytest.raises(
        JdDetailCrawlError,
        match="description content",
    ):
        parse_response('showdesc({"code":601,"content":""})')

    with pytest.raises(
        JdDetailCrawlError,
        match="description response",
    ):
        parse_response('otherCallback({"content":"wrong SKU channel"})')


def test_detail_image_download_retries_one_transient_timeout(
    monkeypatch,
) -> None:
    attempts = 0

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return b"image-bytes"

    def urlopen(_request, *, timeout):
        nonlocal attempts
        attempts += 1
        assert timeout == 30
        if attempts == 1:
            raise TimeoutError("transient read timeout")
        return Response()

    monkeypatch.setattr(
        crawl_jd_detail_ocr.urllib.request,
        "urlopen",
        urlopen,
    )

    content = crawl_jd_detail_ocr._download_image(
        "https://img30.360buyimg.com/sku/retry.jpg",
        referer="https://item.m.jd.com/product/1.html",
    )

    assert content == b"image-bytes"
    assert attempts == 2
