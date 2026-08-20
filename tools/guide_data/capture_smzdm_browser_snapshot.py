"""Persist an authorized-browser SMZDM snapshot as review-only raw data."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
from time import monotonic
from typing import Any

from tools.guide_data.crawl_smzdm_wiki_pages import (
    WikiDetailImage,
    _download_detail_image,
    build_smzdm_wiki_raw_page_record,
    write_smzdm_wiki_capture,
)


ImageLoader = Callable[
    [tuple[dict[str, object], ...]],
    tuple[WikiDetailImage, ...],
]


class SmzdmBrowserSnapshotCaptureError(RuntimeError):
    """Raised when a browser snapshot cannot become auditable raw data."""


def capture_browser_snapshot(
    *,
    payload: Mapping[str, object],
    expected_product_id: int,
    raw_output: str | Path,
    image_output_dir: str | Path,
    image_loader: Callable[..., tuple[WikiDetailImage, ...]] | None = None,
) -> dict[str, object]:
    """Validate one browser DOM snapshot and persist no-approval evidence."""
    if any(
        key in payload
        for key in (
            "candidate_facts",
            "review_status",
            "source_match_status",
        )
    ):
        raise SmzdmBrowserSnapshotCaptureError(
            "browser snapshot cannot submit review decisions"
        )
    product_id = _positive_int(
        payload.get("canonical_product_id"),
        "canonical_product_id",
    )
    if product_id != expected_product_id:
        raise SmzdmBrowserSnapshotCaptureError(
            "browser snapshot does not match expected product"
        )
    page_url = _text(payload.get("page_url"), "page_url")
    image_rows = _image_rows(payload.get("detail_images"))
    loader = image_loader or _load_detail_images
    detail_images = loader(image_rows, referer=page_url)
    raw = build_smzdm_wiki_raw_page_record(
        canonical_product_id=product_id,
        page_url=page_url,
        captured_at=_text(payload.get("captured_at"), "captured_at"),
        page_title=_text(payload.get("page_title"), "page_title"),
        product_title=_text(
            payload.get("product_title"),
            "product_title",
        ),
        product_introduction=_text(
            payload.get("product_introduction"),
            "product_introduction",
            allow_empty=True,
        ),
        parameter_text=_text(
            payload.get("parameter_text"),
            "parameter_text",
            allow_empty=True,
        ),
        body_text=_text(payload.get("body_text"), "body_text"),
        script_urls=_text_sequence(
            payload.get("script_urls"),
            "script_urls",
        ),
        detail_images=detail_images,
    )
    raw.update({
        "candidate_facts": [],
        "review_status": "human_review_required",
        "source_match_status": "pending_human_review",
    })
    write_smzdm_wiki_capture(
        raw=raw,
        detail_images=detail_images,
        raw_output=raw_output,
        image_output_dir=image_output_dir,
    )
    return raw


def serve_one_browser_snapshot(
    *,
    expected_product_id: int,
    raw_output: str | Path,
    image_output_dir: str | Path,
    host: str = "127.0.0.1",
    port: int = 8871,
    timeout_seconds: float = 120.0,
) -> dict[str, object]:
    """Accept one CORS-authorized snapshot from the local browser."""
    state: dict[str, Any] = {
        "result": None,
        "error": None,
    }

    class Handler(BaseHTTPRequestHandler):
        def _cors_headers(self) -> None:
            self.send_header(
                "Access-Control-Allow-Origin",
                "https://wiki.smzdm.com",
            )
            self.send_header(
                "Access-Control-Allow-Methods",
                "POST, OPTIONS",
            )
            self.send_header(
                "Access-Control-Allow-Headers",
                "Content-Type",
            )
            self.send_header(
                "Access-Control-Allow-Private-Network",
                "true",
            )

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self._cors_headers()
            self.end_headers()

        def do_POST(self) -> None:
            if self.path != "/capture":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 8_000_000:
                    raise SmzdmBrowserSnapshotCaptureError(
                        "browser snapshot payload size is invalid"
                    )
                value = json.loads(
                    self.rfile.read(length).decode("utf-8")
                )
                if not isinstance(value, dict):
                    raise SmzdmBrowserSnapshotCaptureError(
                        "browser snapshot payload must be an object"
                    )
                state["result"] = capture_browser_snapshot(
                    payload=value,
                    expected_product_id=expected_product_id,
                    raw_output=raw_output,
                    image_output_dir=image_output_dir,
                )
                body = json.dumps({
                    "status": "captured",
                    "canonical_product_id": expected_product_id,
                    "detail_image_count": state["result"][
                        "detail_image_count"
                    ],
                }).encode("utf-8")
                self.send_response(200)
            except (
                json.JSONDecodeError,
                UnicodeDecodeError,
                ValueError,
                RuntimeError,
            ) as exc:
                state["error"] = str(exc)
                body = json.dumps({
                    "status": "rejected",
                    "reason": str(exc),
                }).encode("utf-8")
                self.send_response(400)
            self._cors_headers()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return None

    server = HTTPServer((host, port), Handler)
    server.timeout = min(0.25, timeout_seconds)
    deadline = monotonic() + timeout_seconds
    try:
        while state["result"] is None and state["error"] is None:
            server.handle_request()
            if (
                state["result"] is None
                and state["error"] is None
                and monotonic() >= deadline
            ):
                raise SmzdmBrowserSnapshotCaptureError(
                    "timed out waiting for authorized browser snapshot"
                )
    finally:
        server.server_close()
    if state["error"] is not None:
        raise SmzdmBrowserSnapshotCaptureError(str(state["error"]))
    result = state["result"]
    if not isinstance(result, dict):
        raise SmzdmBrowserSnapshotCaptureError(
            "browser snapshot capture did not produce raw data"
        )
    return result


def _load_detail_images(
    rows: tuple[dict[str, object], ...],
    *,
    referer: str,
) -> tuple[WikiDetailImage, ...]:
    return tuple(
        _download_detail_image(row, referer=referer)
        for row in rows
    )


def _image_rows(value: object) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list):
        raise SmzdmBrowserSnapshotCaptureError(
            "detail_images must be a list"
        )
    rows: list[dict[str, object]] = []
    seen_urls: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise SmzdmBrowserSnapshotCaptureError(
                "detail image row must be an object"
            )
        row = dict(item)
        source_url = _text(row.get("src"), "detail image src")
        if not source_url.startswith("https://"):
            raise SmzdmBrowserSnapshotCaptureError(
                "detail image src must use https"
            )
        if source_url in seen_urls:
            continue
        seen_urls.add(source_url)
        _positive_int(row.get("width"), "detail image width")
        _positive_int(row.get("height"), "detail image height")
        rows.append(row)
    return tuple(rows)


def _positive_int(value: object, label: str) -> int:
    if type(value) is not int or value < 1:
        raise SmzdmBrowserSnapshotCaptureError(
            f"{label} must be a positive integer"
        )
    return value


def _text(
    value: object,
    label: str,
    *,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise SmzdmBrowserSnapshotCaptureError(
            f"{label} must be text"
        )
    normalized = value.strip()
    if not normalized and not allow_empty:
        raise SmzdmBrowserSnapshotCaptureError(
            f"{label} must be non-empty text"
        )
    return normalized


def _text_sequence(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise SmzdmBrowserSnapshotCaptureError(
            f"{label} must be a text list"
        )
    return tuple(_text(item, label) for item in value)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Receive one authorized SMZDM browser snapshot."
    )
    parser.add_argument("--product-id", type=int, required=True)
    parser.add_argument("--raw-output", type=Path, required=True)
    parser.add_argument("--image-output-dir", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8871)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    args = parser.parse_args(argv)
    result = serve_one_browser_snapshot(
        expected_product_id=args.product_id,
        raw_output=args.raw_output,
        image_output_dir=args.image_output_dir,
        host=args.host,
        port=args.port,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps({
        "status": "captured",
        "canonical_product_id": result["canonical_product_id"],
        "detail_image_count": result["detail_image_count"],
        "raw_output": str(args.raw_output),
        "image_output_dir": str(args.image_output_dir),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
