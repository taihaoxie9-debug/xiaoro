from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import stat

import pytest

from tools.guide_data.find_locked_review_sources import (
    LockedSourceLookupError,
    find_locked_sources,
    locked_hashes_from_manifest,
)


LOCKED = {
    "b31206098d6839257e5dd29c1fae71495b067029568763d9a726b16fc47fd3e4",
    "55996a2a8207e65eb434fa376d61dc0f34d5621f51f9c3754e2369021d9a7f44",
    "56719aa64a4222a961b2ea118cf51415f25c4f88560e5de83172adc8e9c13783",
}
ROOT_ID = "a" * 64
SOURCE_LOCATOR_PATTERN = re.compile(
    r"^urn:xiaoro:local-source:sha256:[0-9a-f]{64}$"
)


def _source_locator(relative_name: str) -> str:
    digest = hashlib.sha256(
        (
            "guide-locked-source-locator-v1"
            f"\0{ROOT_ID}\0{relative_name}"
        ).encode("utf-8")
    ).hexdigest()
    return f"urn:xiaoro:local-source:sha256:{digest}"


def _write_inventory(
    path: Path,
    rows: list[dict[str, object]],
) -> Path:
    path.write_text(
        "".join(
            json.dumps(row, sort_keys=True) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    return path


def _row(
    sha256: str,
    relative_name: str,
    *,
    content_type: str = "html",
) -> dict[str, object]:
    return {
        "content_type": content_type,
        "relative_name": relative_name,
        "sha256": sha256,
        "size_bytes": 123,
        "source_root_id": ROOT_ID,
    }


def test_lookup_reports_found_missing_and_duplicate_by_full_sha_only(
    tmp_path: Path,
) -> None:
    first, second, missing = sorted(LOCKED)
    near_match = first[:-1] + ("0" if first[-1] != "0" else "1")
    inventory = _write_inventory(
        tmp_path / "inventory.jsonl",
        [
            _row(first, "one/source.html"),
            _row(first, "copy/source.html"),
            _row(second, "two/source.htm"),
            _row(near_match, "near/source.html"),
        ],
    )

    result = find_locked_sources(
        inventory,
        locked_hashes=LOCKED,
    )

    assert result.found_count == 1
    assert result.missing_count == 1
    assert result.duplicate_count == 1
    assert [row["html_sha256"] for row in result.rows] == sorted(LOCKED)
    by_hash = {row["html_sha256"]: row for row in result.rows}
    assert by_hash[first]["status"] == "duplicate"
    assert by_hash[first]["matches"] == [
        {"source_locator": locator}
        for locator in sorted(
            {
                _source_locator("copy/source.html"),
                _source_locator("one/source.html"),
            }
        )
    ]
    assert by_hash[second]["status"] == "found"
    assert by_hash[missing] == {
        "html_sha256": missing,
        "matches": [],
        "status": "missing",
    }


def test_lookup_ignores_non_html_rows_even_with_exact_hash(
    tmp_path: Path,
) -> None:
    locked = min(LOCKED)
    inventory = _write_inventory(
        tmp_path / "inventory.jsonl",
        [_row(locked, "ocr.json", content_type="json")],
    )

    result = find_locked_sources(
        inventory,
        locked_hashes={locked},
    )

    assert result.missing_count == 1
    assert result.rows[0]["status"] == "missing"


def test_lookup_private_output_contains_relative_metadata_only(
    tmp_path: Path,
) -> None:
    locked = min(LOCKED)
    inventory = _write_inventory(
        tmp_path / "inventory.jsonl",
        [_row(locked, "nested/source.html")],
    )
    output = tmp_path / "result" / "locked-sources.json"

    result = find_locked_sources(
        inventory,
        locked_hashes={locked},
        output_path=output,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload == {
        "duplicate_count": 0,
        "found_count": 1,
        "missing_count": 0,
        "results": list(result.rows),
        "schema_version": "locked-review-source-lookup-v1",
    }
    serialized = output.read_text(encoding="utf-8")
    assert str(tmp_path) not in serialized
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_lookup_never_reports_sensitive_relative_file_names(
    tmp_path: Path,
) -> None:
    locked = min(LOCKED)
    sensitive_names = [
        "exports/alice@example.test/review.html",
        "tokens/api_token_test_1234567890.html",
        "keys/api_key_test_0987654321.html",
    ]
    inventory = _write_inventory(
        tmp_path / "inventory.jsonl",
        [_row(locked, name) for name in sensitive_names],
    )
    output = tmp_path / "result" / "locked-sources.json"

    result = find_locked_sources(
        inventory,
        locked_hashes={locked},
        output_path=output,
    )

    assert result.found_count == 0
    assert result.duplicate_count == 1
    matches = result.rows[0]["matches"]
    assert len(matches) == 3
    assert all(
        set(match) == {"source_locator"}
        and SOURCE_LOCATOR_PATTERN.fullmatch(match["source_locator"])
        for match in matches
    )
    serialized = output.read_text(encoding="utf-8")
    assert all(name not in serialized for name in sensitive_names)
    assert "alice@example.test" not in serialized
    assert "api_token_test_1234567890" not in serialized
    assert "api_key_test_0987654321" not in serialized


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("relative_name", "/private/source.html"),
        ("relative_name", "../source.html"),
        ("sha256", "a" * 63),
        ("source_root_id", "root-one"),
        ("size_bytes", -1),
    ],
)
def test_lookup_rejects_malformed_inventory_metadata(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    row = _row(min(LOCKED), "source.html")
    row[field] = value
    inventory = _write_inventory(
        tmp_path / "inventory.jsonl",
        [row],
    )

    with pytest.raises(
        LockedSourceLookupError,
        match="invalid inventory",
    ):
        find_locked_sources(inventory, locked_hashes=LOCKED)


def test_locked_hashes_must_be_complete_sha256_values(
    tmp_path: Path,
) -> None:
    inventory = _write_inventory(
        tmp_path / "inventory.jsonl",
        [],
    )

    with pytest.raises(
        LockedSourceLookupError,
        match="locked hashes must be full SHA-256 values",
    ):
        find_locked_sources(
            inventory,
            locked_hashes={min(LOCKED)[:16]},
        )


def test_approved_manifest_exposes_exactly_three_locked_hashes() -> None:
    manifest = Path(
        "data/guide_review_sources/"
        "approved_tmall_feed_reviews_v1_manifest.json"
    )

    assert locked_hashes_from_manifest(manifest) == frozenset(LOCKED)
