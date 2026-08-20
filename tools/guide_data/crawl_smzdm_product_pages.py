"""Capture one SMZDM product page without promoting any product fact."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Sequence
import urllib.request


_AIGC_MARKERS = (
    "powered by zdm-aigc",
    "zdm-aigc engine",
)
_EXCLUDED_SECTIONS = (
    "Powered by ZDM-AIGC Engine v0.3",
    "优势",
    "建议",
)


class SmzdmCaptureError(RuntimeError):
    """Raised when a page cannot produce auditable source evidence."""


class SmzdmCaptureBlocked(SmzdmCaptureError):
    """Raised when SMZDM presents a CAPTCHA or access challenge."""


def is_smzdm_capture_blocked(
    *,
    body_text: str,
    script_urls: Sequence[str],
) -> bool:
    """Identify challenge pages before any field is extracted."""
    values = "\n".join((body_text, *script_urls)).casefold()
    return "tcaptcha" in values or "captcha.qq.com" in values


def build_raw_page_record(
    *,
    canonical_product_id: int,
    page_url: str,
    captured_at: str,
    page_title: str,
    product_title: str,
    page_specification: str,
    main_image_url: str,
    main_image_bytes: bytes,
    raw_product_introduction: str,
    body_text: str,
    script_urls: Sequence[str],
) -> dict[str, object]:
    """Create a hash-bound raw page row with no claim promotion."""
    if is_smzdm_capture_blocked(
        body_text=body_text,
        script_urls=script_urls,
    ):
        raise SmzdmCaptureBlocked("smzdm page is challenge blocked")
    if type(canonical_product_id) is not int or canonical_product_id < 1:
        raise SmzdmCaptureError(
            "canonical_product_id must be a positive integer"
        )
    for key, value in (
        ("page_url", page_url),
        ("captured_at", captured_at),
        ("page_title", page_title),
        ("product_title", product_title),
        ("page_specification", page_specification),
        ("main_image_url", main_image_url),
        ("raw_product_introduction", raw_product_introduction),
        ("body_text", body_text),
    ):
        if not isinstance(value, str) or not value.strip():
            raise SmzdmCaptureError(f"{key} must be non-empty text")
    if not page_url.startswith("https://"):
        raise SmzdmCaptureError("page_url must use https")
    if not main_image_url.startswith("https://"):
        raise SmzdmCaptureError("main_image_url must use https")
    if not isinstance(main_image_bytes, bytes) or not main_image_bytes:
        raise SmzdmCaptureError("main_image_bytes must be non-empty")
    if _contains_aigc(raw_product_introduction):
        raise SmzdmCaptureError(
            "raw_product_introduction must exclude AIGC content"
        )
    return {
        "canonical_product_id": canonical_product_id,
        "page_url": page_url.strip(),
        "captured_at": captured_at.strip(),
        "page_title": page_title.strip(),
        "product_title": product_title.strip(),
        "page_specification": page_specification.strip(),
        "main_image_url": main_image_url.strip(),
        "main_image_sha256": hashlib.sha256(
            main_image_bytes
        ).hexdigest(),
        "raw_product_introduction": raw_product_introduction.strip(),
        "excluded_sections": list(_EXCLUDED_SECTIONS),
        "raw_page_text_sha256": hashlib.sha256(
            body_text.encode("utf-8")
        ).hexdigest(),
    }


def crawl_smzdm_page(
    *,
    canonical_product_id: int,
    page_url: str,
) -> tuple[dict[str, object], bytes]:
    """Read one browser-rendered SMZDM page or fail closed on a challenge."""
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
                    const description = document.querySelector(
                        'meta[name="description"]'
                    )?.content?.trim() || '';
                    const images = Array.from(document.images)
                        .filter(image => image.currentSrc || image.src)
                        .map(image => ({
                            src: image.currentSrc || image.src,
                            alt: image.alt || '',
                            width: image.naturalWidth || 0,
                            height: image.naturalHeight || 0,
                        }))
                        .filter(image => image.width > 0);
                    const main = images
                        .filter(image => image.alt)
                        .sort((left, right) =>
                            right.width * right.height
                            - left.width * left.height
                        )[0] || images[0] || null;
                    return {
                        bodyText: document.body.innerText || '',
                        description,
                        mainImage: main,
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

    body_text = str(snapshot["bodyText"])
    script_urls = tuple(str(value) for value in snapshot["scripts"])
    if is_smzdm_capture_blocked(
        body_text=body_text,
        script_urls=script_urls,
    ):
        raise SmzdmCaptureBlocked("smzdm page is challenge blocked")
    main_image = snapshot["mainImage"]
    if not isinstance(main_image, dict):
        raise SmzdmCaptureError("smzdm main image is unavailable")
    title = str(snapshot["title"]).strip()
    description = str(snapshot["description"]).strip()
    product_title = str(main_image.get("alt") or title).strip()
    specification = _extract_specification(product_title)
    if not specification:
        specification = _extract_specification(title)
    if not specification:
        raise SmzdmCaptureError(
            "smzdm page specification is unavailable"
        )
    image_url = str(main_image.get("src") or "").strip()
    image_bytes = _download_image(image_url, referer=page_url)
    raw = build_raw_page_record(
        canonical_product_id=canonical_product_id,
        page_url=page_url,
        captured_at=datetime.now(UTC).isoformat(),
        page_title=title,
        product_title=product_title,
        page_specification=specification,
        main_image_url=image_url,
        main_image_bytes=image_bytes,
        raw_product_introduction=description,
        body_text=body_text,
        script_urls=script_urls,
    )
    return raw, image_bytes


def _extract_specification(value: str) -> str | None:
    import re

    match = re.search(
        r"\b\d+(?:\.\d+)?\s*(?:ml|mL|ML|g|G)\b",
        value,
    )
    return match.group(0).replace(" ", "") if match else None


def _download_image(url: str, *, referer: str) -> bytes:
    request = urllib.request.Request(
        url,
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
            return response.read()
    except OSError as exc:
        raise SmzdmCaptureError(
            "smzdm main image download failed"
        ) from exc


def _contains_aigc(value: str) -> bool:
    normalized = value.casefold()
    return any(marker in normalized for marker in _AIGC_MARKERS)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Capture one SMZDM product page as raw evidence."
    )
    parser.add_argument("--url", required=True)
    parser.add_argument("--product-id", type=int, required=True)
    parser.add_argument("--raw-output", type=Path, required=True)
    parser.add_argument("--image-output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        raw, image = crawl_smzdm_page(
            canonical_product_id=args.product_id,
            page_url=args.url,
        )
    except SmzdmCaptureBlocked as error:
        print(json.dumps({
            "status": "capture_blocked",
            "reason": str(error),
        }))
        return 4
    args.raw_output.parent.mkdir(parents=True, exist_ok=True)
    args.image_output.parent.mkdir(parents=True, exist_ok=True)
    args.raw_output.write_text(
        json.dumps(raw, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.image_output.write_bytes(image)
    print(json.dumps({
        "status": "captured",
        "canonical_product_id": args.product_id,
        "raw_output": str(args.raw_output),
        "image_output": str(args.image_output),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
