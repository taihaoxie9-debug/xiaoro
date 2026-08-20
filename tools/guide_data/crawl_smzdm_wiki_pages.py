"""Capture complete SMZDM wiki detail pages as review-only raw evidence."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
from io import BytesIO
import json
from pathlib import Path
from typing import Sequence
import urllib.request
from urllib.parse import urlparse

from PIL import Image

from tools.guide_data.crawl_smzdm_product_pages import (
    SmzdmCaptureBlocked,
    is_smzdm_capture_blocked,
)
from tools.guide_data.smzdm_category_policy import build_review_packet


_AIGC_MARKERS = (
    "powered by zdm-aigc",
    "zdm-aigc engine",
)
_EXCLUDED_SECTIONS = (
    "Powered by ZDM-AIGC Engine v0.3",
    "优势",
    "建议",
)
_WIKI_URL_PREFIX = "https://wiki.smzdm.com/p/"


class SmzdmWikiCaptureError(RuntimeError):
    """Raised when a wiki page cannot produce auditable raw evidence."""


@dataclass(frozen=True, slots=True)
class WikiDetailImage:
    source_url: str
    content: bytes
    width: int
    height: int


def build_smzdm_wiki_raw_page_record(
    *,
    canonical_product_id: int,
    page_url: str,
    captured_at: str,
    page_title: str,
    product_title: str,
    product_introduction: str,
    parameter_text: str,
    body_text: str,
    script_urls: Sequence[str],
    detail_images: Sequence[WikiDetailImage],
) -> dict[str, object]:
    """Build a hash-bound wiki capture without extracting product facts."""
    if is_smzdm_capture_blocked(
        body_text=body_text,
        script_urls=script_urls,
    ):
        raise SmzdmCaptureBlocked("smzdm wiki page is challenge blocked")
    if type(canonical_product_id) is not int or canonical_product_id < 1:
        raise SmzdmWikiCaptureError(
            "canonical_product_id must be a positive integer"
        )
    if not page_url.startswith(_WIKI_URL_PREFIX):
        raise SmzdmWikiCaptureError(
            "page_url must be an SMZDM wiki URL"
        )
    for key, value in (
        ("captured_at", captured_at),
        ("page_title", page_title),
        ("product_title", product_title),
        ("body_text", body_text),
    ):
        if not isinstance(value, str) or not value.strip():
            raise SmzdmWikiCaptureError(f"{key} must be non-empty text")
    for key, value in (
        ("product_introduction", product_introduction),
        ("parameter_text", parameter_text),
    ):
        if not isinstance(value, str):
            raise SmzdmWikiCaptureError(f"{key} must be text")
    if _contains_aigc(product_introduction):
        raise SmzdmWikiCaptureError(
            "product_introduction must exclude AIGC content"
        )
    normalized_images = _normalize_detail_images(detail_images)
    review_packet = build_review_packet(
        parameter_text=parameter_text,
        introduction_text=product_introduction,
        detail_images=normalized_images,
    )
    return {
        "source_kind": "smzdm_wiki",
        "canonical_product_id": canonical_product_id,
        "page_url": page_url.strip(),
        "captured_at": captured_at.strip(),
        "page_title": page_title.strip(),
        "product_title": product_title.strip(),
        "product_introduction": product_introduction.strip(),
        "parameter_text": parameter_text.strip(),
        "excluded_sections": list(_EXCLUDED_SECTIONS),
        "raw_page_text_sha256": hashlib.sha256(
            body_text.encode("utf-8")
        ).hexdigest(),
        "detail_image_count": review_packet.detail_image_count,
        "detail_image_status": review_packet.detail_image_status,
        "review_sources": list(review_packet.review_sources),
        "detail_images": normalized_images,
    }


def crawl_smzdm_wiki_page(
    *,
    canonical_product_id: int,
    page_url: str,
) -> tuple[dict[str, object], tuple[WikiDetailImage, ...]]:
    """Read one rendered wiki page and download its full detail sequence."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Mobile Safari/537.36"
            ),
            viewport={"width": 390, "height": 844},
            locale="zh-CN",
        )
        page = context.new_page()
        try:
            page.goto(
                page_url,
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            page.wait_for_timeout(3_000)
            snapshot = page.evaluate(
                """() => {
                    const describe = document.querySelector(
                        '.commodity-describe'
                    );
                    const parameters = document.querySelector(
                        '.spesc-detail'
                    );
                    const productTitleNode = document.querySelector(
                        '.pd-title'
                    ) || document.querySelector(
                        '.commodity-detail h1, .commodity-detail .title'
                    );
                    const productTitleDirectText = productTitleNode
                        ? Array.from(productTitleNode.childNodes)
                            .filter(node =>
                                node.nodeType === Node.TEXT_NODE
                            )
                            .map(node => node.textContent?.trim() || '')
                            .filter(Boolean)
                            .join(' ')
                        : '';
                    const productTitle = productTitleDirectText
                        || productTitleNode?.textContent?.trim()
                        || document.title
                        || '';
                    return {
                        bodyText: document.body?.innerText || '',
                        detailImages: Array.from(
                            describe?.querySelectorAll(
                                '.des-contain img'
                            ) || []
                        ).map(image => ({
                            src: image.currentSrc || image.src || '',
                            width: image.naturalWidth || 0,
                            height: image.naturalHeight || 0,
                        })),
                        parameterText: parameters?.innerText?.trim() || '',
                        productIntroduction:
                            describe?.innerText?.trim() || '',
                        productTitle,
                        scripts: Array.from(document.scripts)
                            .map(script => script.src)
                            .filter(Boolean),
                        title: document.title || '',
                    };
                }"""
            )
        finally:
            page.close()
            context.close()
            browser.close()

    raw_body_text = snapshot.get("bodyText")
    body_text = raw_body_text if isinstance(raw_body_text, str) else ""
    script_urls = tuple(
        value
        for value in snapshot.get("scripts", ())
        if isinstance(value, str)
    )
    ensure_smzdm_wiki_capture_unblocked(
        body_text=body_text,
        script_urls=script_urls,
    )
    image_rows = snapshot.get("detailImages")
    if not isinstance(image_rows, list):
        raise SmzdmWikiCaptureError(
            "smzdm wiki detail images are unavailable"
        )
    detail_images = tuple(
        _download_detail_image(row, referer=page_url)
        for row in image_rows
        if isinstance(row, dict)
    )
    raw = build_smzdm_wiki_raw_page_record(
        canonical_product_id=canonical_product_id,
        page_url=page_url,
        captured_at=datetime.now(UTC).isoformat(),
        page_title=_snapshot_text(snapshot, "title"),
        product_title=_snapshot_text(snapshot, "productTitle"),
        product_introduction=_snapshot_optional_text(
            snapshot,
            "productIntroduction",
        ),
        parameter_text=_snapshot_optional_text(snapshot, "parameterText"),
        body_text=body_text,
        script_urls=script_urls,
        detail_images=detail_images,
    )
    return raw, detail_images


def ensure_smzdm_wiki_capture_unblocked(
    *,
    body_text: str,
    script_urls: Sequence[str],
) -> None:
    """Fail before extraction when the wiki page is a challenge document."""
    if is_smzdm_capture_blocked(
        body_text=body_text,
        script_urls=script_urls,
    ):
        raise SmzdmCaptureBlocked("smzdm wiki page is challenge blocked")


def write_smzdm_wiki_capture(
    *,
    raw: dict[str, object],
    detail_images: Sequence[WikiDetailImage],
    raw_output: str | Path,
    image_output_dir: str | Path,
) -> None:
    """Persist raw capture and source images without creating a review."""
    output = Path(raw_output)
    destination = Path(image_output_dir)
    product_id = raw.get("canonical_product_id")
    if type(product_id) is not int or product_id < 1:
        raise SmzdmWikiCaptureError(
            "raw capture must contain a positive canonical product ID"
        )
    if len(detail_images) != raw.get("detail_image_count"):
        raise SmzdmWikiCaptureError(
            "raw capture detail image count does not match image files"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir(parents=True, exist_ok=True)
    for ordinal, image in enumerate(detail_images, start=1):
        digest = hashlib.sha256(image.content).hexdigest()
        suffix = _image_suffix(image.source_url, image.content)
        target = destination / f"{ordinal:03d}_{digest[:16]}{suffix}"
        target.write_bytes(image.content)
    output.write_text(
        json.dumps(raw, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _normalize_detail_images(
    detail_images: Sequence[WikiDetailImage],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    seen_urls: set[str] = set()
    for ordinal, image in enumerate(detail_images, start=1):
        if not isinstance(image, WikiDetailImage):
            raise SmzdmWikiCaptureError(
                "detail_images must contain WikiDetailImage values"
            )
        if (
            not image.source_url.startswith("https://")
            or image.source_url in seen_urls
            or not image.content
            or image.width < 1
            or image.height < 1
        ):
            raise SmzdmWikiCaptureError(
                "detail image is invalid or duplicated"
            )
        seen_urls.add(image.source_url)
        rows.append({
            "ordinal": ordinal,
            "source_url": image.source_url,
            "sha256": hashlib.sha256(image.content).hexdigest(),
            "width": image.width,
            "height": image.height,
        })
    return rows


def _download_detail_image(
    row: dict[str, object],
    *,
    referer: str,
) -> WikiDetailImage:
    source_url = row.get("src")
    if not isinstance(source_url, str) or not source_url.startswith("https://"):
        raise SmzdmWikiCaptureError(
            "smzdm wiki detail image URL is unavailable"
        )
    request = urllib.request.Request(
        source_url,
        headers={
            "Referer": referer,
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
                "AppleWebKit/537.36 Chrome/124.0 Mobile Safari/537.36"
            ),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            content = response.read()
    except OSError as exc:
        raise SmzdmWikiCaptureError(
            "smzdm wiki detail image download failed"
        ) from exc
    if not content:
        raise SmzdmWikiCaptureError(
            "smzdm wiki detail image is empty"
        )
    try:
        with Image.open(BytesIO(content)) as image:
            width, height = image.size
    except OSError as exc:
        raise SmzdmWikiCaptureError(
            "smzdm wiki detail image is invalid"
        ) from exc
    return WikiDetailImage(
        source_url=source_url,
        content=content,
        width=width,
        height=height,
    )


def _snapshot_text(snapshot: dict[str, object], key: str) -> str:
    value = snapshot.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SmzdmWikiCaptureError(f"smzdm wiki {key} is unavailable")
    return value.strip()


def _snapshot_optional_text(
    snapshot: dict[str, object],
    key: str,
) -> str:
    value = snapshot.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise SmzdmWikiCaptureError(
            f"smzdm wiki {key} must be text"
        )
    return value.strip()


def _contains_aigc(value: str) -> bool:
    normalized = value.casefold()
    return any(marker in normalized for marker in _AIGC_MARKERS)


def _image_suffix(url: str, content: bytes) -> str:
    suffix = Path(urlparse(url).path).suffix.casefold()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".avif"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    try:
        with Image.open(BytesIO(content)) as image:
            format_name = (image.format or "").casefold()
    except OSError as exc:
        raise SmzdmWikiCaptureError(
            "smzdm wiki detail image is invalid"
        ) from exc
    return {
        "jpeg": ".jpg",
        "png": ".png",
        "webp": ".webp",
        "avif": ".avif",
    }.get(format_name, ".img")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--product-id", type=int, required=True)
    parser.add_argument("--raw-output", type=Path, required=True)
    parser.add_argument("--image-output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        raw, detail_images = crawl_smzdm_wiki_page(
            canonical_product_id=args.product_id,
            page_url=args.url,
        )
    except SmzdmCaptureBlocked as error:
        print(json.dumps({
            "status": "capture_blocked",
            "reason": str(error),
        }))
        return 4
    write_smzdm_wiki_capture(
        raw=raw,
        detail_images=detail_images,
        raw_output=args.raw_output,
        image_output_dir=args.image_output_dir,
    )
    print(json.dumps({
        "status": "captured",
        "canonical_product_id": args.product_id,
        "detail_image_count": raw["detail_image_count"],
        "raw_output": str(args.raw_output),
        "image_output_dir": str(args.image_output_dir),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
