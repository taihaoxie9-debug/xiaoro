from __future__ import annotations

from collections import Counter
import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest

from app.guide.retrieval.review_reader import (
    ReviewEvidenceReader,
    ReviewProductOwnershipError,
)


ROOT = Path(__file__).resolve().parents[3]
ASSET_DIR = ROOT / "data" / "guide_review_sources"
MANIFEST_PATH = (
    ASSET_DIR / "approved_tmall_feed_reviews_v1_manifest.json"
)
SOURCES_PATH = ASSET_DIR / "approved_tmall_feed_reviews_v1.jsonl"
EXPECTED_MANIFEST_SHA256 = (
    "823c249166e93b4ab709b3423fa8a97a23e3ab3e7677e5d39d74abc21c165113"
)
EXPECTED_AUDIT_LOCATOR = (
    "docs/audits/phase2-scenario-feedback/review_source_audit.md"
)
CURRENT_AUDIT_BLOCK_START = "<!-- current-approved-catalog:start -->"
CURRENT_AUDIT_BLOCK_END = "<!-- current-approved-catalog:end -->"
HISTORICAL_BASELINE_HEADING = (
    "## Historical Pre-Reconstruction Baseline (`approved=0`)"
)
TMALL_LOCATOR_PATTERN = re.compile(
    r"^urn:tmall:ssr-html:"
    r"item:(?P<item_id>[0-9]+):"
    r"sku:(?P<sku_id>[0-9]+):"
    r"feed:(?P<feed_id>[0-9]+):"
    r"sha256:(?P<html_sha256>[0-9a-f]{64}):"
    r"ordinal:(?P<page_ordinal>[0-9]{8})$"
)

EXPECTED = {
    "1303713936059": {
        "product_id": 42,
        "item_id": "998532090974",
        "sku_id": "6153782938028",
        "html_sha256": (
            "b31206098d6839257e5dd29c1fae71495b067029568763d9a726b16fc47fd3e4"
        ),
        "page_ordinal": 1,
        "collected_at": "2026-08-09T11:35:27.456000Z",
        "content": "挺好用的回购很多次了吧 保湿控油效果：挺好",
        "content_sha256": (
            "3c8cf69b8bcb188f36b34868799297f6fa908c8dc9e4a44ea641ba51d3cc475b"
        ),
    },
    "1305316624545": {
        "product_id": 55,
        "item_id": "746513552108",
        "sku_id": "5318505666088",
        "html_sha256": (
            "56719aa64a4222a961b2ea118cf51415f25c4f88560e5de83172adc8e9c13783"
        ),
        "page_ordinal": 2,
        "collected_at": "2026-08-09T11:35:27.447000Z",
        "content": (
            "收到货了，已经开始使用了，清透不粘腻很好推开，"
            "丝滑质地柔软透气，特别好用，强烈推荐大家购买，嘎嘎好使，"
        ),
        "content_sha256": (
            "142ad1280d8c792d58b01817972d1b90947063d969896a04269b914118417925"
        ),
    },
    "1306554487880": {
        "product_id": 49,
        "item_id": "525332729369",
        "sku_id": "5214914101911",
        "html_sha256": (
            "55996a2a8207e65eb434fa376d61dc0f34d5621f51f9c3754e2369021d9a7f44"
        ),
        "page_ordinal": 1,
        "collected_at": "2026-08-09T11:35:27.430000Z",
        "content": (
            "玉泽保湿霜收到了，用着很滋润。 "
            "用完脸水润润的，补水效果真不错。"
        ),
        "content_sha256": (
            "b789a25cba933b657bc85fdd3d3c26e4cf66eb7dbaf61417886555cc18005bf4"
        ),
    },
    "1307612064428": {
        "product_id": 55,
        "item_id": "746513552108",
        "sku_id": "5318505666088",
        "html_sha256": (
            "56719aa64a4222a961b2ea118cf51415f25c4f88560e5de83172adc8e9c13783"
        ),
        "page_ordinal": 1,
        "collected_at": "2026-08-09T11:35:27.447000Z",
        "content": "涂上脸部不过敏，清爽不黏腻，就是有点小贵。",
        "content_sha256": (
            "18e3e47b0f2fb7eb20b88666950ecb5ce6870c58764e275563f1ba02333acd42"
        ),
    },
    "1307660701413": {
        "product_id": 42,
        "item_id": "998532090974",
        "sku_id": "6153782938028",
        "html_sha256": (
            "b31206098d6839257e5dd29c1fae71495b067029568763d9a726b16fc47fd3e4"
        ),
        "page_ordinal": 2,
        "collected_at": "2026-08-09T11:35:27.456000Z",
        "content": (
            "好大一个盒子呀，包装超级高级 "
            "黄色和蓝色次抛搭配使用，维稳效果还不错"
        ),
        "content_sha256": (
            "d14f4f2dab7217b38d7fdd04e7e8f5def41ee7ff72398455301f476802ce8e1d"
        ),
    },
    "1308815628363": {
        "product_id": 49,
        "item_id": "525332729369",
        "sku_id": "5214914101911",
        "html_sha256": (
            "55996a2a8207e65eb434fa376d61dc0f34d5621f51f9c3754e2369021d9a7f44"
        ),
        "page_ordinal": 2,
        "collected_at": "2026-08-09T11:35:27.430000Z",
        "content": (
            "换季干敏肌全靠玉泽维稳，修护面霜质地润而不油，"
            "上脸很好推开吸收快。坚持用能缓解脸颊泛红、起皮干燥，"
            "补水舒缓效果看得见，没有刺鼻香精，成分温和。"
            "洗完薄涂一层，皮肤稳定很多，敏感肌换季必备，"
            "无限空瓶的修护好物。"
        ),
        "content_sha256": (
            "9b47534561acb1387de63e78de7760af12fbb0554a9a4e75eb0ba77355326b61"
        ),
    },
}


def _asset_api():
    try:
        from app.guide.retrieval.approved_review_assets import (
            ApprovedReviewAssetIntegrityError,
            load_approved_review_assets,
        )
    except ModuleNotFoundError:
        pytest.fail("approved review asset loader is missing")
    return ApprovedReviewAssetIntegrityError, load_approved_review_assets


def _load():
    return _load_paths(
        manifest_path=MANIFEST_PATH,
        sources_path=SOURCES_PATH,
    )


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _manifest_digest(payload: dict[str, object]) -> str:
    unsigned = {
        key: value
        for key, value in payload.items()
        if key != "manifest_sha256"
    }
    return hashlib.sha256(
        _canonical_json(unsigned).encode("utf-8")
    ).hexdigest()


def _copy_assets(tmp_path: Path) -> tuple[Path, Path]:
    manifest_path = tmp_path / MANIFEST_PATH.name
    sources_path = tmp_path / SOURCES_PATH.name
    shutil.copy2(MANIFEST_PATH, manifest_path)
    shutil.copy2(SOURCES_PATH, sources_path)
    return manifest_path, sources_path


def _load_paths(
    *,
    manifest_path: Path,
    sources_path: Path,
    expected_manifest_sha256: str = EXPECTED_MANIFEST_SHA256,
):
    _, load_approved_review_assets = _asset_api()
    return load_approved_review_assets(
        manifest_path=manifest_path,
        sources_path=sources_path,
        expected_manifest_sha256=expected_manifest_sha256,
    )


def _rewrite_source_snapshot(
    *,
    manifest_path: Path,
    sources_path: Path,
    rows: list[dict[str, object]],
) -> str:
    sources_path.write_text(
        "".join(f"{_canonical_json(row)}\n" for row in rows),
        encoding="utf-8",
    )
    source_sha256 = hashlib.sha256(sources_path.read_bytes()).hexdigest()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sources_sha256"] = source_sha256
    manifest["catalog_version"] = (
        f"approved-tmall-feed-reviews-v1:sha256:{source_sha256}"
    )
    manifest["manifest_sha256"] = _manifest_digest(manifest)
    manifest_path.write_text(
        _canonical_json(manifest) + "\n",
        encoding="utf-8",
    )
    return str(manifest["manifest_sha256"])


def _rewrite_manifest(
    manifest_path: Path,
    **updates: object,
) -> str:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(updates)
    manifest["manifest_sha256"] = _manifest_digest(manifest)
    manifest_path.write_text(
        _canonical_json(manifest) + "\n",
        encoding="utf-8",
    )
    return str(manifest["manifest_sha256"])


def _rewrite_stable_source_ids(
    rows: list[dict[str, object]],
) -> None:
    for row in rows:
        locator = str(row["source_locator"])
        match = re.fullmatch(
            r"(?P<prefix>urn:tmall:ssr-html:"
            r"item:(?P<item_id>[0-9]+):"
            r"sku:(?P<sku_id>[0-9]+):"
            r"feed:(?P<feed_id>[0-9]+):"
            r"sha256:(?P<html_sha256>[0-9a-f]{64}))"
            r"(?::ordinal:[0-9]{8})?",
            locator,
        )
        assert match is not None
        feed_id = match.group("feed_id")
        expected = EXPECTED[feed_id]
        assert match.group("item_id") == expected["item_id"]
        assert match.group("html_sha256") == expected["html_sha256"]
        ordinal = f"{int(expected['page_ordinal']):08d}"
        row["source_locator"] = (
            f"{match.group('prefix')}:ordinal:{ordinal}"
        )
        row["source_id"] = _stable_source_id(
            item_id=str(expected["item_id"]),
            html_sha256=str(expected["html_sha256"]),
            page_ordinal=int(expected["page_ordinal"]),
        )


def _stable_source_id(
    *,
    item_id: str,
    html_sha256: str,
    page_ordinal: int,
) -> str:
    return (
        f"review_tmall_item_{item_id}_"
        f"html_{html_sha256}_"
        f"ordinal_{page_ordinal:08d}"
    )


def _expected_source_id(feed_id: str) -> str:
    expected = EXPECTED[feed_id]
    return _stable_source_id(
        item_id=str(expected["item_id"]),
        html_sha256=str(expected["html_sha256"]),
        page_ordinal=int(expected["page_ordinal"]),
    )


def test_production_review_assets_are_exact_hash_locked_and_sorted() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    loaded = _load()

    assert loaded.catalog.approved_source_count == 6
    assert loaded.catalog.approved_source_count == len(loaded.evidence)
    assert manifest["approved_source_count"] == len(loaded.evidence)
    assert manifest["sources_sha256"] == hashlib.sha256(
        SOURCES_PATH.read_bytes()
    ).hexdigest()
    assert manifest["manifest_sha256"] == _manifest_digest(manifest)
    assert manifest["manifest_sha256"] == EXPECTED_MANIFEST_SHA256
    assert manifest["audit_locator"] == EXPECTED_AUDIT_LOCATOR
    assert manifest["product_bindings"] == [
        {
            "product_id": product_id,
            "item_id": item_id,
            "sku_id": sku_id,
            "html_sha256": html_sha256,
        }
        for product_id, item_id, sku_id, html_sha256 in (
            (
                42,
                "998532090974",
                "6153782938028",
                "b31206098d6839257e5dd29c1fae71495b067029568763d9a726b16fc47fd3e4",
            ),
            (
                49,
                "525332729369",
                "5214914101911",
                "55996a2a8207e65eb434fa376d61dc0f34d5621f51f9c3754e2369021d9a7f44",
            ),
            (
                55,
                "746513552108",
                "5318505666088",
                "56719aa64a4222a961b2ea118cf51415f25c4f88560e5de83172adc8e9c13783",
            ),
        )
    ]

    source_ids = [item.source_id for item in loaded.evidence]
    assert source_ids == sorted(source_ids)
    assert source_ids == sorted(
        _expected_source_id(feed_id) for feed_id in EXPECTED
    )
    assert [row["source_id"] for row in _source_rows()] == source_ids

    expected_by_source_id = {
        _expected_source_id(feed_id): (feed_id, expected)
        for feed_id, expected in EXPECTED.items()
    }
    for item in loaded.evidence:
        feed_id, expected = expected_by_source_id[item.source_id]
        html_sha256 = expected["html_sha256"]
        page_ordinal = int(expected["page_ordinal"])
        assert item.product_id == expected["product_id"]
        assert item.source_kind == "platform_consumer_review"
        assert item.source_locator == (
            f"urn:tmall:ssr-html:item:{expected['item_id']}:"
            f"sku:{expected['sku_id']}:feed:{feed_id}:"
            f"sha256:{html_sha256}:"
            f"ordinal:{page_ordinal:08d}"
        )
        assert item.content_kind == "verbatim"
        assert item.content == expected["content"]
        assert item.content_sha256 == expected["content_sha256"]
        assert item.content_sha256 == hashlib.sha256(
            item.content.encode("utf-8")
        ).hexdigest()
        assert (
            item.collected_at.isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
            == expected["collected_at"]
        )
        assert item.collection_version == (
            f"tmall-ssr-html-sha256:{html_sha256}"
        )


def test_review_source_audit_matches_current_approved_catalog() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    loaded = _load()
    audit_path = ROOT / str(manifest["audit_locator"])
    audit_text = audit_path.read_text(encoding="utf-8")

    current_prefix, historical = audit_text.split(
        HISTORICAL_BASELINE_HEADING,
        maxsplit=1,
    )
    assert "approved=0" not in current_prefix
    assert "Approved review source count: `0`" in historical

    block = current_prefix.split(
        CURRENT_AUDIT_BLOCK_START,
        maxsplit=1,
    )[1].split(CURRENT_AUDIT_BLOCK_END, maxsplit=1)[0]
    current = json.loads(
        block.removeprefix("\n```json\n").removesuffix("```\n")
    )
    source_counts = Counter(
        item.product_id for item in loaded.evidence
    )

    assert current == {
        "approved_product_count": len(source_counts),
        "approved_product_counts": {
            str(product_id): count
            for product_id, count in sorted(source_counts.items())
        },
        "approved_source_count": loaded.catalog.approved_source_count,
        "audit_locator": loaded.catalog.audit_locator,
        "catalog_id": loaded.catalog.catalog_id,
        "catalog_version": loaded.catalog.catalog_version,
        "manifest_file": str(MANIFEST_PATH.relative_to(ROOT)),
        "manifest_file_sha256": hashlib.sha256(
            MANIFEST_PATH.read_bytes()
        ).hexdigest(),
        "manifest_file_sha256_semantics": (
            "raw-file-bytes:includes-manifest_sha256:"
            "includes-trailing-newline"
        ),
        "manifest_sha256": manifest["manifest_sha256"],
        "manifest_sha256_semantics": (
            "canonical-json:exclude-manifest_sha256:utf-8:"
            "sorted-keys:compact:no-trailing-newline"
        ),
        "sources_file": str(SOURCES_PATH.relative_to(ROOT)),
        "sources_sha256": hashlib.sha256(
            SOURCES_PATH.read_bytes()
        ).hexdigest(),
    }
    assert current["approved_source_count"] == 6
    assert current["approved_product_counts"] == {
        "42": 2,
        "49": 2,
        "55": 2,
    }
    assert current["manifest_sha256"] == _manifest_digest(manifest)
    assert current["sources_sha256"] == manifest["sources_sha256"]


def test_loaded_sources_keep_reader_order_and_duplicate_idempotency() -> None:
    loaded = _load()
    duplicated = [
        *reversed(loaded.evidence),
        loaded.evidence[0].model_copy(deep=True),
    ]
    reader = ReviewEvidenceReader(
        catalog=loaded.catalog,
        evidence=duplicated,
    )

    result = reader.read(product_id=49)

    assert [item.source_id for item in result.evidence] == [
        _expected_source_id("1306554487880"),
        _expected_source_id("1308815628363"),
    ]
    assert result.verified_absence is None


def test_loaded_sources_reject_cross_product_selection() -> None:
    loaded = _load()
    reader = ReviewEvidenceReader(
        catalog=loaded.catalog,
        evidence=loaded.evidence,
    )

    with pytest.raises(
        ReviewProductOwnershipError,
        match=_expected_source_id("1306554487880"),
    ):
        reader.read(
            product_id=55,
            source_ids=[_expected_source_id("1306554487880")],
        )


def test_loader_rejects_source_file_hash_drift(tmp_path: Path) -> None:
    ApprovedReviewAssetIntegrityError, _ = _asset_api()
    manifest_path, sources_path = _copy_assets(tmp_path)
    sources_path.write_bytes(sources_path.read_bytes() + b"\n")

    with pytest.raises(
        ApprovedReviewAssetIntegrityError,
        match="source asset SHA-256 mismatch",
    ):
        _load_paths(
            manifest_path=manifest_path,
            sources_path=sources_path,
        )


def test_loader_accepts_item_html_hash_and_page_ordinal_source_ids(
    tmp_path: Path,
) -> None:
    manifest_path, sources_path = _copy_assets(tmp_path)
    rows = _source_rows(sources_path)
    _rewrite_stable_source_ids(rows)
    rewritten_manifest_sha256 = _rewrite_source_snapshot(
        manifest_path=manifest_path,
        sources_path=sources_path,
        rows=rows,
    )

    loaded = _load_paths(
        manifest_path=manifest_path,
        sources_path=sources_path,
        expected_manifest_sha256=rewritten_manifest_sha256,
    )

    assert [item.source_id for item in loaded.evidence] == sorted(
        str(row["source_id"]) for row in rows
    )


def test_loader_rejects_feed_only_source_ids(tmp_path: Path) -> None:
    ApprovedReviewAssetIntegrityError, _ = _asset_api()
    manifest_path, sources_path = _copy_assets(tmp_path)
    rows = _source_rows(sources_path)
    _rewrite_stable_source_ids(rows)
    for row in rows:
        match = TMALL_LOCATOR_PATTERN.fullmatch(
            str(row["source_locator"])
        )
        assert match is not None
        row["source_id"] = (
            f"review_tmall_feed_{match.group('feed_id')}"
        )
    rewritten_manifest_sha256 = _rewrite_source_snapshot(
        manifest_path=manifest_path,
        sources_path=sources_path,
        rows=rows,
    )

    with pytest.raises(
        ApprovedReviewAssetIntegrityError,
        match="stable Tmall review source ID",
    ):
        _load_paths(
            manifest_path=manifest_path,
            sources_path=sources_path,
            expected_manifest_sha256=rewritten_manifest_sha256,
        )


def test_loader_keeps_exact_duplicate_source_idempotent(
    tmp_path: Path,
) -> None:
    manifest_path, sources_path = _copy_assets(tmp_path)
    rows = _source_rows(sources_path)
    _rewrite_stable_source_ids(rows)
    rows.append(dict(rows[0]))
    rewritten_manifest_sha256 = _rewrite_source_snapshot(
        manifest_path=manifest_path,
        sources_path=sources_path,
        rows=rows,
    )

    loaded = _load_paths(
        manifest_path=manifest_path,
        sources_path=sources_path,
        expected_manifest_sha256=rewritten_manifest_sha256,
    )

    assert len(loaded.evidence) == 6
    assert len({item.source_id for item in loaded.evidence}) == 6


def test_loader_treats_feed_id_as_auxiliary_locator_metadata(
    tmp_path: Path,
) -> None:
    manifest_path, sources_path = _copy_assets(tmp_path)
    rows = _source_rows(sources_path)
    _rewrite_stable_source_ids(rows)
    row = next(
        item
        for item in rows
        if "feed:1306554487880" in str(item["source_locator"])
    )
    source_id = row["source_id"]
    row["source_locator"] = str(row["source_locator"]).replace(
        "feed:1306554487880",
        "feed:9999999999999",
    )
    rewritten_manifest_sha256 = _rewrite_source_snapshot(
        manifest_path=manifest_path,
        sources_path=sources_path,
        rows=rows,
    )

    loaded = _load_paths(
        manifest_path=manifest_path,
        sources_path=sources_path,
        expected_manifest_sha256=rewritten_manifest_sha256,
    )

    assert next(
        item
        for item in loaded.evidence
        if item.source_id == source_id
    ).source_id == source_id


def test_loader_rejects_conflicting_stable_source_identity(
    tmp_path: Path,
) -> None:
    ApprovedReviewAssetIntegrityError, _ = _asset_api()
    manifest_path, sources_path = _copy_assets(tmp_path)
    rows = _source_rows(sources_path)
    _rewrite_stable_source_ids(rows)
    conflicting = dict(rows[0])
    conflicting["content"] = f"{conflicting['content']} 冲突"
    conflicting["content_sha256"] = hashlib.sha256(
        str(conflicting["content"]).encode("utf-8")
    ).hexdigest()
    rows.append(conflicting)
    rewritten_manifest_sha256 = _rewrite_source_snapshot(
        manifest_path=manifest_path,
        sources_path=sources_path,
        rows=rows,
    )

    with pytest.raises(
        ApprovedReviewAssetIntegrityError,
        match="conflicting approved review source",
    ):
        _load_paths(
            manifest_path=manifest_path,
            sources_path=sources_path,
            expected_manifest_sha256=rewritten_manifest_sha256,
        )


def test_loader_rejects_source_id_page_ordinal_mismatch(
    tmp_path: Path,
) -> None:
    ApprovedReviewAssetIntegrityError, _ = _asset_api()
    manifest_path, sources_path = _copy_assets(tmp_path)
    rows = _source_rows(sources_path)
    _rewrite_stable_source_ids(rows)
    rows[0]["source_id"] = str(rows[0]["source_id"]).replace(
        "ordinal_00000001",
        "ordinal_00000002",
    )
    rewritten_manifest_sha256 = _rewrite_source_snapshot(
        manifest_path=manifest_path,
        sources_path=sources_path,
        rows=rows,
    )

    with pytest.raises(
        ApprovedReviewAssetIntegrityError,
        match="stable Tmall review source ID mismatch",
    ):
        _load_paths(
            manifest_path=manifest_path,
            sources_path=sources_path,
            expected_manifest_sha256=rewritten_manifest_sha256,
        )


def test_loader_rejects_manifest_self_hash_drift(tmp_path: Path) -> None:
    ApprovedReviewAssetIntegrityError, _ = _asset_api()
    manifest_path, sources_path = _copy_assets(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["catalog_version"] = "tampered-version"
    manifest_path.write_text(
        _canonical_json(manifest) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ApprovedReviewAssetIntegrityError,
        match="manifest SHA-256 mismatch",
    ):
        _load_paths(
            manifest_path=manifest_path,
            sources_path=sources_path,
        )


def test_loader_rejects_manifest_catalog_count_drift(
    tmp_path: Path,
) -> None:
    ApprovedReviewAssetIntegrityError, _ = _asset_api()
    manifest_path, sources_path = _copy_assets(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["approved_source_count"] = 7
    manifest["manifest_sha256"] = _manifest_digest(manifest)
    manifest_path.write_text(
        _canonical_json(manifest) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ApprovedReviewAssetIntegrityError,
        match="approved source count mismatch",
    ):
        _load_paths(
            manifest_path=manifest_path,
            sources_path=sources_path,
            expected_manifest_sha256=manifest["manifest_sha256"],
        )


def test_loader_rejects_coordinated_source_and_manifest_tampering(
    tmp_path: Path,
) -> None:
    ApprovedReviewAssetIntegrityError, _ = _asset_api()
    manifest_path, sources_path = _copy_assets(tmp_path)
    rows = _source_rows(sources_path)
    rows[0]["content"] = f"{rows[0]['content']} 篡改"
    rows[0]["content_sha256"] = hashlib.sha256(
        str(rows[0]["content"]).encode("utf-8")
    ).hexdigest()
    _rewrite_source_snapshot(
        manifest_path=manifest_path,
        sources_path=sources_path,
        rows=rows,
    )

    with pytest.raises(
        ApprovedReviewAssetIntegrityError,
        match="manifest lock mismatch",
    ):
        _load_paths(
            manifest_path=manifest_path,
            sources_path=sources_path,
        )


@pytest.mark.parametrize(
    "rebound_field",
    ["product_id", "item_id", "sku_id", "html_sha256"],
)
def test_loader_rejects_cross_product_source_rebinding(
    tmp_path: Path,
    rebound_field: str,
) -> None:
    ApprovedReviewAssetIntegrityError, _ = _asset_api()
    manifest_path, sources_path = _copy_assets(tmp_path)
    rows = _source_rows(sources_path)
    row = next(item for item in rows if item["product_id"] == 49)
    locator_match = TMALL_LOCATOR_PATTERN.fullmatch(
        str(row["source_locator"])
    )
    assert locator_match is not None
    feed_id = locator_match.group("feed_id")
    original = EXPECTED[feed_id]
    other = EXPECTED["1305316624545"]
    identity = {
        "item_id": original["item_id"],
        "sku_id": original["sku_id"],
        "html_sha256": original["html_sha256"],
    }
    if rebound_field == "product_id":
        row["product_id"] = other["product_id"]
    else:
        identity[rebound_field] = other[rebound_field]
    row["source_locator"] = (
        f"urn:tmall:ssr-html:item:{identity['item_id']}:"
        f"sku:{identity['sku_id']}:feed:{feed_id}:"
        f"sha256:{identity['html_sha256']}:"
        f"ordinal:{int(original['page_ordinal']):08d}"
    )
    row["source_id"] = _stable_source_id(
        item_id=str(identity["item_id"]),
        html_sha256=str(identity["html_sha256"]),
        page_ordinal=int(original["page_ordinal"]),
    )
    row["collection_version"] = (
        f"tmall-ssr-html-sha256:{identity['html_sha256']}"
    )
    rewritten_manifest_sha256 = _rewrite_source_snapshot(
        manifest_path=manifest_path,
        sources_path=sources_path,
        rows=rows,
    )

    with pytest.raises(
        ApprovedReviewAssetIntegrityError,
        match="Tmall product binding mismatch",
    ):
        _load_paths(
            manifest_path=manifest_path,
            sources_path=sources_path,
            expected_manifest_sha256=rewritten_manifest_sha256,
        )


@pytest.mark.parametrize(
    ("unsafe_content", "message"),
    [
        ('<a href="/detail">批准正文</a>', "raw HTML"),
        ("联系电话：010-12345678", "PII"),
        ("微信号：xiaoro_123", "PII"),
        ("收货地址：北京市朝阳区建国路88号", "PII"),
    ],
)
def test_loader_rejects_html_and_obvious_pii_bypasses(
    tmp_path: Path,
    unsafe_content: str,
    message: str,
) -> None:
    ApprovedReviewAssetIntegrityError, _ = _asset_api()
    manifest_path, sources_path = _copy_assets(tmp_path)
    rows = _source_rows(sources_path)
    rows[0]["content"] = unsafe_content
    rows[0]["content_sha256"] = hashlib.sha256(
        unsafe_content.encode("utf-8")
    ).hexdigest()
    rewritten_manifest_sha256 = _rewrite_source_snapshot(
        manifest_path=manifest_path,
        sources_path=sources_path,
        rows=rows,
    )

    with pytest.raises(
        ApprovedReviewAssetIntegrityError,
        match=message,
    ):
        _load_paths(
            manifest_path=manifest_path,
            sources_path=sources_path,
            expected_manifest_sha256=rewritten_manifest_sha256,
        )


def test_loader_rejects_collection_after_catalog_audit(
    tmp_path: Path,
) -> None:
    ApprovedReviewAssetIntegrityError, _ = _asset_api()
    manifest_path, sources_path = _copy_assets(tmp_path)
    rows = _source_rows(sources_path)
    rows[0]["collected_at"] = "2026-08-09T11:38:24.001Z"
    rewritten_manifest_sha256 = _rewrite_source_snapshot(
        manifest_path=manifest_path,
        sources_path=sources_path,
        rows=rows,
    )

    with pytest.raises(
        ApprovedReviewAssetIntegrityError,
        match="collected_at must not be after audited_at",
    ):
        _load_paths(
            manifest_path=manifest_path,
            sources_path=sources_path,
            expected_manifest_sha256=rewritten_manifest_sha256,
        )


@pytest.mark.parametrize(
    "audit_locator",
    [
        "/tmp/review_source_audit.md",
        "file://docs/audits/review_source_audit.md",
        "https://example.com/review_source_audit.md",
        "docs/audits/../review_source_audit.md",
        "data/guide_review_sources/manifest.json",
    ],
)
def test_loader_rejects_untrusted_audit_locator(
    tmp_path: Path,
    audit_locator: str,
) -> None:
    ApprovedReviewAssetIntegrityError, _ = _asset_api()
    manifest_path, sources_path = _copy_assets(tmp_path)
    rewritten_manifest_sha256 = _rewrite_manifest(
        manifest_path,
        audit_locator=audit_locator,
    )

    with pytest.raises(
        ApprovedReviewAssetIntegrityError,
        match="audit_locator must be a repository-relative docs path",
    ):
        _load_paths(
            manifest_path=manifest_path,
            sources_path=sources_path,
            expected_manifest_sha256=rewritten_manifest_sha256,
        )


def test_loader_resolves_manifest_generation_from_legacy_sources_path(
    tmp_path: Path,
) -> None:
    manifest_path, sources_path = _copy_assets(tmp_path)
    source_bytes = sources_path.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    generation_path = sources_path.with_name(
        f"{sources_path.stem}.{source_sha256}{sources_path.suffix}"
    )
    generation_path.write_bytes(source_bytes)
    rewritten_manifest_sha256 = _rewrite_manifest(
        manifest_path,
        sources_file=generation_path.name,
    )

    loaded = _load_paths(
        manifest_path=manifest_path,
        sources_path=sources_path,
        expected_manifest_sha256=rewritten_manifest_sha256,
    )

    assert len(loaded.evidence) == 6
    assert [item.source_id for item in loaded.evidence] == [
        row["source_id"] for row in _source_rows(generation_path)
    ]


def test_loader_validates_manifest_lock_before_generation_resolution(
    tmp_path: Path,
) -> None:
    ApprovedReviewAssetIntegrityError, _ = _asset_api()
    manifest_path, sources_path = _copy_assets(tmp_path)
    _rewrite_manifest(
        manifest_path,
        sources_file=(
            f"{sources_path.stem}.{'0' * 64}{sources_path.suffix}"
        ),
    )

    with pytest.raises(
        ApprovedReviewAssetIntegrityError,
        match="manifest lock mismatch",
    ):
        _load_paths(
            manifest_path=manifest_path,
            sources_path=sources_path,
            expected_manifest_sha256=EXPECTED_MANIFEST_SHA256,
        )


@pytest.mark.parametrize(
    "sources_file",
    [
        "/tmp/approved.jsonl",
        "../approved.jsonl",
        r"nested\approved.jsonl",
        "C:approved.jsonl",
        ".",
        "..",
    ],
)
def test_loader_rejects_unsafe_manifest_sources_basename(
    tmp_path: Path,
    sources_file: str,
) -> None:
    ApprovedReviewAssetIntegrityError, _ = _asset_api()
    manifest_path, sources_path = _copy_assets(tmp_path)
    rewritten_manifest_sha256 = _rewrite_manifest(
        manifest_path,
        sources_file=sources_file,
    )

    with pytest.raises(
        ApprovedReviewAssetIntegrityError,
        match="sources_file must be a safe basename",
    ):
        _load_paths(
            manifest_path=manifest_path,
            sources_path=sources_path,
            expected_manifest_sha256=rewritten_manifest_sha256,
        )


def test_loader_rejects_wrong_generation_name_for_declared_hash(
    tmp_path: Path,
) -> None:
    ApprovedReviewAssetIntegrityError, _ = _asset_api()
    manifest_path, sources_path = _copy_assets(tmp_path)
    wrong_name = (
        f"{sources_path.stem}.{'0' * 64}{sources_path.suffix}"
    )
    (sources_path.parent / wrong_name).write_bytes(sources_path.read_bytes())
    rewritten_manifest_sha256 = _rewrite_manifest(
        manifest_path,
        sources_file=wrong_name,
    )

    with pytest.raises(
        ApprovedReviewAssetIntegrityError,
        match="generation filename does not match sources_sha256",
    ):
        _load_paths(
            manifest_path=manifest_path,
            sources_path=sources_path,
            expected_manifest_sha256=rewritten_manifest_sha256,
        )


def test_loader_rejects_missing_declared_generation(
    tmp_path: Path,
) -> None:
    ApprovedReviewAssetIntegrityError, _ = _asset_api()
    manifest_path, sources_path = _copy_assets(tmp_path)
    source_sha256 = hashlib.sha256(sources_path.read_bytes()).hexdigest()
    generation_name = (
        f"{sources_path.stem}.{source_sha256}{sources_path.suffix}"
    )
    rewritten_manifest_sha256 = _rewrite_manifest(
        manifest_path,
        sources_file=generation_name,
    )

    with pytest.raises(
        ApprovedReviewAssetIntegrityError,
        match="cannot read approved review source asset generation",
    ):
        _load_paths(
            manifest_path=manifest_path,
            sources_path=sources_path,
            expected_manifest_sha256=rewritten_manifest_sha256,
        )


def test_loader_rejects_symlink_declared_generation(
    tmp_path: Path,
) -> None:
    ApprovedReviewAssetIntegrityError, _ = _asset_api()
    manifest_path, sources_path = _copy_assets(tmp_path)
    source_sha256 = hashlib.sha256(sources_path.read_bytes()).hexdigest()
    generation_path = sources_path.with_name(
        f"{sources_path.stem}.{source_sha256}{sources_path.suffix}"
    )
    generation_path.symlink_to(sources_path)
    rewritten_manifest_sha256 = _rewrite_manifest(
        manifest_path,
        sources_file=generation_path.name,
    )

    with pytest.raises(
        ApprovedReviewAssetIntegrityError,
        match="generation cannot be a symlink",
    ):
        _load_paths(
            manifest_path=manifest_path,
            sources_path=sources_path,
            expected_manifest_sha256=rewritten_manifest_sha256,
        )


def test_loader_rejects_conflicting_declared_generation_content(
    tmp_path: Path,
) -> None:
    ApprovedReviewAssetIntegrityError, _ = _asset_api()
    manifest_path, sources_path = _copy_assets(tmp_path)
    source_sha256 = hashlib.sha256(sources_path.read_bytes()).hexdigest()
    generation_path = sources_path.with_name(
        f"{sources_path.stem}.{source_sha256}{sources_path.suffix}"
    )
    generation_path.write_bytes(b"conflicting generation content\n")
    rewritten_manifest_sha256 = _rewrite_manifest(
        manifest_path,
        sources_file=generation_path.name,
    )

    with pytest.raises(
        ApprovedReviewAssetIntegrityError,
        match="source asset SHA-256 mismatch",
    ):
        _load_paths(
            manifest_path=manifest_path,
            sources_path=sources_path,
            expected_manifest_sha256=rewritten_manifest_sha256,
        )


def test_review_asset_contains_no_raw_html_or_pii() -> None:
    loaded = _load()
    rows = _source_rows(SOURCES_PATH)
    expected_keys = {
        "source_id",
        "product_id",
        "source_kind",
        "source_locator",
        "content_kind",
        "content",
        "content_sha256",
        "collected_at",
        "collection_version",
    }

    assert rows
    assert all(set(row) == expected_keys for row in rows)
    assert all(
        "<html" not in item.content.lower()
        for item in loaded.evidence
    )
    assert all(
        "<!doctype" not in item.content.lower()
        for item in loaded.evidence
    )
    assert all(
        re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", item.content) is None
        for item in loaded.evidence
    )
    assert all(
        re.search(r"(?<!\d)1[3-9]\d{9}(?!\d)", item.content) is None
        for item in loaded.evidence
    )
    assert all(
        re.search(r"(?<!\d)\d{17}[\dXx](?!\d)", item.content) is None
        for item in loaded.evidence
    )
    raw_asset = SOURCES_PATH.read_text(encoding="utf-8").lower()
    for forbidden_key in (
        "raw_html",
        "html_body",
        "nickname",
        "username",
        "buyer_id",
        "member_id",
        "avatar",
        "email",
        "phone",
        "mobile",
        "id_card",
    ):
        assert f'"{forbidden_key}"' not in raw_asset


def _source_rows(
    path: Path = SOURCES_PATH,
) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
