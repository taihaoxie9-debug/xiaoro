from __future__ import annotations

import hashlib
import json
from pathlib import Path
import socket
import threading
import time
import urllib.request

import pytest

from tools.guide_data.capture_smzdm_browser_snapshot import (
    SmzdmBrowserSnapshotCaptureError,
    capture_browser_snapshot,
    serve_one_browser_snapshot,
)
from tools.guide_data.crawl_smzdm_wiki_pages import WikiDetailImage


def _payload(product_id: int = 33) -> dict[str, object]:
    return {
        "canonical_product_id": product_id,
        "page_url": "https://wiki.smzdm.com/p/60q4dyz/",
        "captured_at": "2026-08-20T00:00:00+00:00",
        "page_title": "雅诗兰黛小棕瓶 50ml",
        "product_title": "雅诗兰黛小棕瓶 50ml",
        "product_introduction": "液体质地，使用后注意保湿。",
        "parameter_text": "规格 50ml",
        "body_text": "完整百科正文",
        "script_urls": [],
        "detail_images": [
            {
                "src": "https://y.zdmimg.com/detail.jpg",
                "width": 600,
                "height": 800,
            }
        ],
    }


def test_browser_snapshot_capture_writes_review_only_hash_bound_raw(
    tmp_path: Path,
) -> None:
    content = b"detail-image"

    def load_images(
        rows: tuple[dict[str, object], ...],
        *,
        referer: str,
    ) -> tuple[WikiDetailImage, ...]:
        assert referer == "https://wiki.smzdm.com/p/60q4dyz/"
        assert rows[0]["src"] == "https://y.zdmimg.com/detail.jpg"
        return (
            WikiDetailImage(
                source_url=str(rows[0]["src"]),
                content=content,
                width=600,
                height=800,
            ),
        )

    raw_path = tmp_path / "product-33-browser-raw-v1.json"
    image_dir = tmp_path / "source-images"
    result = capture_browser_snapshot(
        payload=_payload(),
        expected_product_id=33,
        raw_output=raw_path,
        image_output_dir=image_dir,
        image_loader=load_images,
    )

    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(content).hexdigest()
    assert result["canonical_product_id"] == 33
    assert raw["review_status"] == "human_review_required"
    assert raw["candidate_facts"] == []
    assert raw["source_match_status"] == "pending_human_review"
    assert raw["detail_images"] == [
        {
            "ordinal": 1,
            "source_url": "https://y.zdmimg.com/detail.jpg",
            "sha256": digest,
            "width": 600,
            "height": 800,
        }
    ]
    assert (
        image_dir / f"001_{digest[:16]}.jpg"
    ).read_bytes() == content


def test_browser_snapshot_capture_rejects_wrong_queue_product(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        SmzdmBrowserSnapshotCaptureError,
        match="expected product",
    ):
        capture_browser_snapshot(
            payload=_payload(product_id=34),
            expected_product_id=33,
            raw_output=tmp_path / "raw.json",
            image_output_dir=tmp_path / "images",
            image_loader=lambda rows, referer: (),
        )


def test_browser_snapshot_capture_deduplicates_repeated_dom_images(
    tmp_path: Path,
) -> None:
    payload = _payload()
    payload["detail_images"] = [
        payload["detail_images"][0],
        dict(payload["detail_images"][0]),
    ]

    def load_images(
        rows: tuple[dict[str, object], ...],
        *,
        referer: str,
    ) -> tuple[WikiDetailImage, ...]:
        assert len(rows) == 1
        return (
            WikiDetailImage(
                source_url=str(rows[0]["src"]),
                content=b"one-image",
                width=600,
                height=800,
            ),
        )

    result = capture_browser_snapshot(
        payload=payload,
        expected_product_id=33,
        raw_output=tmp_path / "raw.json",
        image_output_dir=tmp_path / "images",
        image_loader=load_images,
    )

    assert result["detail_image_count"] == 1


def test_local_receiver_accepts_cors_preflight_before_snapshot(
    tmp_path: Path,
) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    payload = _payload()
    payload["detail_images"] = []
    outcome: dict[str, object] = {}

    def receive() -> None:
        try:
            outcome["result"] = serve_one_browser_snapshot(
                expected_product_id=33,
                raw_output=tmp_path / "raw.json",
                image_output_dir=tmp_path / "images",
                port=port,
                timeout_seconds=2,
            )
        except BaseException as exc:
            outcome["error"] = exc

    thread = threading.Thread(target=receive)
    thread.start()
    time.sleep(0.05)
    url = f"http://127.0.0.1:{port}/capture"
    with urllib.request.urlopen(
        urllib.request.Request(
            url,
            method="OPTIONS",
            headers={
                "Origin": "https://wiki.smzdm.com",
                "Access-Control-Request-Method": "POST",
            },
        ),
        timeout=2,
    ) as response:
        assert response.status == 204
    body = json.dumps(payload).encode("utf-8")
    with urllib.request.urlopen(
        urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Origin": "https://wiki.smzdm.com",
                "Content-Type": "application/json",
            },
        ),
        timeout=2,
    ) as response:
        assert response.status == 200
    thread.join(timeout=2)

    assert "error" not in outcome
    assert outcome["result"]["canonical_product_id"] == 33


def _assert_category_has_hash_bound_review_only_raw(
    category_profile: str,
) -> None:
    root = Path(__file__).resolve().parents[3]
    queue = json.loads(
        (
            root / "docs/audits/smzdm-data/capture_queue_v1.json"
        ).read_text(encoding="utf-8")
    )
    target_ids = {
        row["canonical_product_id"]
        for row in queue["targets"]
        if row["category_profile"] == category_profile
    }
    all_target_ids = {
        row["canonical_product_id"]
        for row in queue["targets"]
    }
    raw_dir = root / "docs/audits/smzdm-data/browser-captures"
    raw_by_id = {
        int(path.name.split("-", 2)[1]): json.loads(
            path.read_text(encoding="utf-8")
        )
        for path in raw_dir.glob("product-*-browser-raw-v1.json")
    }

    assert set(raw_by_id) <= all_target_ids
    assert not target_ids - set(raw_by_id)
    for product_id in target_ids:
        raw = raw_by_id[product_id]
        assert raw["candidate_facts"] == []
        assert raw["review_status"] == "human_review_required"
        assert raw["source_match_status"] == "pending_human_review"
        assert raw["detail_image_count"] == len(raw["detail_images"])
        image_dir = (
            root
            / "data/guide_merchant_claims/smzdm_wiki_v1/source_images"
            / str(product_id)
        )
        files = tuple(sorted(image_dir.glob("*"))) if image_dir.exists() else ()
        assert len(files) == raw["detail_image_count"]
        for row in raw["detail_images"]:
            prefix = f"{row['ordinal']:03d}_{row['sha256'][:16]}"
            matches = tuple(
                path for path in files if path.name.startswith(prefix)
            )
            assert len(matches) == 1
            assert (
                hashlib.sha256(matches[0].read_bytes()).hexdigest()
                == row["sha256"]
            )


def test_every_skincare_target_has_hash_bound_review_only_raw() -> None:
    _assert_category_has_hash_bound_review_only_raw("skincare")


def test_every_suncare_target_has_hash_bound_review_only_raw() -> None:
    _assert_category_has_hash_bound_review_only_raw("suncare")


def test_every_cleanser_target_has_hash_bound_review_only_raw() -> None:
    _assert_category_has_hash_bound_review_only_raw("cleanser")


def test_every_base_makeup_target_has_hash_bound_review_only_raw() -> None:
    _assert_category_has_hash_bound_review_only_raw("base_makeup")


def test_every_color_makeup_target_has_hash_bound_review_only_raw() -> None:
    _assert_category_has_hash_bound_review_only_raw("color_makeup")


def test_every_fragrance_target_has_hash_bound_review_only_raw() -> None:
    _assert_category_has_hash_bound_review_only_raw("fragrance")
