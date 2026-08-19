from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image


_JD_DETAIL_IMAGE = re.compile(
    r"(?:https?:)?//img[0-9]+\.360buyimg\.com/sku/"
    r"[^)'\"\s;]+",
    re.IGNORECASE,
)
_JD_DESCRIPTION_RESPONSE = re.compile(
    r"^\s*showdesc\((?P<payload>\{.*\})\)\s*;?\s*$",
    re.DOTALL,
)
_SKU = re.compile(r"^[1-9][0-9]{4,19}$")


class JdDetailCrawlError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CrawlTarget:
    product_id: int
    sku: str
    canonical_name: str


def extract_jd_detail_image_urls(detail_html: str) -> tuple[str, ...]:
    if not isinstance(detail_html, str):
        raise TypeError("detail_html must be a string")
    ordered: list[str] = []
    seen: set[str] = set()
    for match in _JD_DETAIL_IMAGE.finditer(detail_html):
        value = match.group(0)
        url = value if value.startswith("http") else f"https:{value}"
        if url in seen:
            continue
        seen.add(url)
        ordered.append(url)
    return tuple(ordered)


def validate_jd_page_identity(
    payload: dict[str, object],
    *,
    expected_sku: str,
) -> str:
    if payload.get("sku") != expected_sku:
        raise JdDetailCrawlError("JD detail page SKU mismatch")
    title = payload.get("title")
    if not isinstance(title, str) or not title.strip():
        raise JdDetailCrawlError("JD detail page title is unavailable")
    return title.strip()


def parse_jd_description_response(response_text: str) -> str:
    if not isinstance(response_text, str):
        raise TypeError("response_text must be a string")
    match = _JD_DESCRIPTION_RESPONSE.fullmatch(response_text)
    if match is None:
        raise JdDetailCrawlError("JD description response is invalid")
    try:
        payload = json.loads(match.group("payload"))
    except json.JSONDecodeError as exc:
        raise JdDetailCrawlError(
            "JD description response is invalid"
        ) from exc
    if not isinstance(payload, dict):
        raise JdDetailCrawlError("JD description response is invalid")
    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        raise JdDetailCrawlError(
            "JD description content is unavailable"
        )
    return content


def crawl_targets(
    *,
    targets: tuple[CrawlTarget, ...],
    source_root: Path,
    image_root: Path,
    overwrite: bool = False,
) -> list[dict[str, object]]:
    from playwright.sync_api import sync_playwright
    from rapidocr_onnxruntime import RapidOCR

    source_root.mkdir(parents=True, exist_ok=True)
    image_root.mkdir(parents=True, exist_ok=True)
    ocr = RapidOCR()
    results: list[dict[str, object]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Mobile Safari/537.36"
            ),
            viewport={"width": 390, "height": 844},
        )
        try:
            for target in targets:
                results.append(
                    _crawl_one(
                        context=context,
                        target=target,
                        source_root=source_root,
                        image_root=image_root,
                        ocr=ocr,
                        overwrite=overwrite,
                    )
                )
        finally:
            context.close()
            browser.close()
    return results


def _crawl_one(
    *,
    context,
    target: CrawlTarget,
    source_root: Path,
    image_root: Path,
    ocr,
    overwrite: bool,
) -> dict[str, object]:
    output_path = source_root / f"detail_{target.product_id}_ocr.json"
    if output_path.exists() and not overwrite:
        raise JdDetailCrawlError(
            f"OCR source already exists for product {target.product_id}"
        )
    page_url = f"https://item.m.jd.com/product/{target.sku}.html"
    page = context.new_page()
    try:
        page.goto(page_url, wait_until="domcontentloaded", timeout=45_000)
        page.wait_for_function(
            "() => Boolean(window.itemObj?.skuId)",
            timeout=30_000,
        )
        page_payload = page.evaluate(
            """() => ({
                sku: window.itemObj?.skuId,
                title: window.itemObj?.detail?.itemInfo?.skuName,
            })"""
        )
    except Exception as exc:
        raise JdDetailCrawlError(
            f"JD detail page unavailable for product {target.product_id}"
        ) from exc
    finally:
        page.close()

    title = validate_jd_page_identity(
        page_payload,
        expected_sku=target.sku,
    )
    detail_html = _fetch_jd_detail_html(
        target.sku,
        referer=page_url,
    )
    image_urls = extract_jd_detail_image_urls(detail_html)
    if not image_urls:
        raise JdDetailCrawlError(
            f"JD detail images unavailable for product {target.product_id}"
        )

    product_image_root = image_root / str(target.product_id)
    product_image_root.mkdir(parents=True, exist_ok=True)
    images: list[dict[str, object]] = []
    for index, url in enumerate(image_urls):
        content = _download_image(url, referer=page_url)
        digest = hashlib.sha256(content).hexdigest()
        suffix = _image_suffix(url, content)
        filename = f"{index:03d}_{digest[:16]}{suffix}"
        image_path = product_image_root / filename
        _atomic_write(image_path, content)
        width, height = _image_size(content)
        ocr_text = _recognize_ocr(ocr, content)
        images.append(
            {
                "file": filename,
                "size": [width, height],
                "size_kb": round(len(content) / 1024, 1),
                "ocr_text": ocr_text,
                "image_sha256": digest,
                "source_url": url,
                "local_image": str(
                    Path("source_images")
                    / str(target.product_id)
                    / filename
                ),
            }
        )

    payload = {
        "pid": target.product_id,
        "name": target.canonical_name,
        "crawled_title": title,
        "source_origin": page_url,
        "crawled_at": datetime.now(UTC).isoformat(),
        "images": images,
    }
    _atomic_write(
        output_path,
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8"),
    )
    return {
        "product_id": target.product_id,
        "sku": target.sku,
        "page_title": title,
        "image_count": len(images),
        "ocr_nonempty_count": sum(
            bool(item["ocr_text"]) for item in images
        ),
        "ocr_character_count": sum(
            len(str(item["ocr_text"])) for item in images
        ),
        "source_path": str(output_path),
    }


def _download_image(url: str, *, referer: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Referer": referer,
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 13) "
                "AppleWebKit/537.36 Chrome/124.0 Mobile Safari/537.36"
            ),
        },
    )
    content = b""
    last_error: OSError | None = None
    for _attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                content = response.read()
            break
        except OSError as exc:
            last_error = exc
    else:
        assert last_error is not None
        raise JdDetailCrawlError(
            f"JD detail image download failed: {url}"
        ) from last_error
    if not content:
        raise JdDetailCrawlError("JD detail image is empty")
    return content


def _fetch_jd_detail_html(sku: str, *, referer: str) -> str:
    request = urllib.request.Request(
        f"https://dx.3.cn/desc/{sku}?cdn=2",
        headers={
            "Referer": referer,
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 13) "
                "AppleWebKit/537.36 Chrome/124.0 Mobile Safari/537.36"
            ),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response_text = response.read().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise JdDetailCrawlError(
            f"JD description download failed for SKU {sku}"
        ) from exc
    return parse_jd_description_response(response_text)


def _image_suffix(url: str, content: bytes) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".avif"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    try:
        with Image.open(BytesIO(content)) as image:
            format_name = (image.format or "").lower()
    except OSError as exc:
        raise JdDetailCrawlError("downloaded detail image is invalid") from exc
    return {
        "jpeg": ".jpg",
        "png": ".png",
        "webp": ".webp",
        "avif": ".avif",
    }.get(format_name, ".img")


def _image_size(content: bytes) -> tuple[int, int]:
    try:
        with Image.open(BytesIO(content)) as image:
            return image.size
    except OSError as exc:
        raise JdDetailCrawlError("downloaded detail image is invalid") from exc


def _recognize_ocr(ocr, content: bytes) -> str:
    result, _ = ocr(content)
    if not result:
        return ""
    return "\n".join(
        str(item[1]).strip()
        for item in result
        if (
            isinstance(item, (list, tuple))
            and len(item) >= 2
            and str(item[1]).strip()
        )
    )


def _atomic_write(path: Path, content: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _load_targets(path: Path) -> tuple[CrawlTarget, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JdDetailCrawlError("crawl target file is invalid") from exc
    if not isinstance(payload, list) or not payload:
        raise JdDetailCrawlError("crawl target file must be a nonempty list")
    targets: list[CrawlTarget] = []
    for row in payload:
        if (
            not isinstance(row, dict)
            or set(row) != {"product_id", "sku", "canonical_name"}
            or not isinstance(row["product_id"], int)
            or isinstance(row["product_id"], bool)
            or row["product_id"] <= 0
            or not isinstance(row["sku"], str)
            or _SKU.fullmatch(row["sku"]) is None
            or not isinstance(row["canonical_name"], str)
            or not row["canonical_name"].strip()
        ):
            raise JdDetailCrawlError("crawl target row is invalid")
        targets.append(
            CrawlTarget(
                product_id=row["product_id"],
                sku=row["sku"],
                canonical_name=row["canonical_name"].strip(),
            )
        )
    if len({item.product_id for item in targets}) != len(targets):
        raise JdDetailCrawlError("crawl target product IDs must be unique")
    return tuple(targets)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--targets", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--image-root", required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    results = crawl_targets(
        targets=_load_targets(Path(args.targets)),
        source_root=Path(args.source_root),
        image_root=Path(args.image_root),
        overwrite=args.overwrite,
    )
    print(
        json.dumps(
            results,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CrawlTarget",
    "JdDetailCrawlError",
    "crawl_targets",
    "extract_jd_detail_image_urls",
    "parse_jd_description_response",
    "validate_jd_page_identity",
]
