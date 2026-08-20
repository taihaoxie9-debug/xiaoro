"""Locate locked historical review HTML bytes in an anonymous inventory."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import Iterable, Sequence

from tools.guide_data.inventory_local_sources import (
    SourceInventoryError,
    atomic_write_private,
)


_SCHEMA_VERSION = "locked-review-source-lookup-v1"
_SOURCE_LOCATOR_DOMAIN = "guide-locked-source-locator-v1"
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_INVENTORY_FIELDS = {
    "content_type",
    "relative_name",
    "sha256",
    "size_bytes",
    "source_root_id",
}
_CONTENT_TYPES = {
    "html",
    "jpeg",
    "json",
    "jsonl",
    "png",
    "webp",
}


class LockedSourceLookupError(ValueError):
    """Raised when locked hashes or inventory metadata are invalid."""


@dataclass(frozen=True, slots=True)
class LockedSourceResult:
    rows: tuple[dict[str, object], ...]
    found_count: int
    missing_count: int
    duplicate_count: int
    report_sha256: str


def find_locked_sources(
    inventory_path: str | Path,
    *,
    locked_hashes: Iterable[str],
    output_path: str | Path | None = None,
) -> LockedSourceResult:
    """Return one deterministic found/missing/duplicate row per full hash."""

    normalized_hashes = _validate_locked_hashes(locked_hashes)
    inventory = _read_inventory(Path(inventory_path))
    html_by_hash: dict[str, list[dict[str, object]]] = {}
    for row in inventory:
        if row["content_type"] != "html":
            continue
        html_by_hash.setdefault(str(row["sha256"]), []).append(
            {
                "source_locator": _anonymous_source_locator(row),
            }
        )

    rows: list[dict[str, object]] = []
    found_count = 0
    missing_count = 0
    duplicate_count = 0
    for locked_hash in normalized_hashes:
        matches = sorted(
            html_by_hash.get(locked_hash, []),
            key=lambda match: (
                str(match["source_locator"]),
            ),
        )
        if not matches:
            status = "missing"
            missing_count += 1
        elif len(matches) == 1:
            status = "found"
            found_count += 1
        else:
            status = "duplicate"
            duplicate_count += 1
        rows.append(
            {
                "html_sha256": locked_hash,
                "matches": matches,
                "status": status,
            }
        )

    payload = {
        "duplicate_count": duplicate_count,
        "found_count": found_count,
        "missing_count": missing_count,
        "results": rows,
        "schema_version": _SCHEMA_VERSION,
    }
    report_bytes = (
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    if output_path is not None:
        try:
            atomic_write_private(output_path, report_bytes)
        except SourceInventoryError as exc:
            raise LockedSourceLookupError(
                "locked source output could not be published"
            ) from exc
    return LockedSourceResult(
        rows=tuple(rows),
        found_count=found_count,
        missing_count=missing_count,
        duplicate_count=duplicate_count,
        report_sha256=hashlib.sha256(report_bytes).hexdigest(),
    )


def locked_hashes_from_manifest(
    manifest_path: str | Path,
) -> frozenset[str]:
    """Read the locked HTML hashes from the approved review manifest."""

    payload = _read_json_object(
        Path(manifest_path),
        label="approved review manifest",
    )
    if payload.get("schema_version") != "approved-review-sources-v1":
        raise LockedSourceLookupError(
            "approved review manifest schema is invalid"
        )
    _validate_manifest_digest(payload)
    bindings = payload.get("product_bindings")
    if not isinstance(bindings, list) or len(bindings) != 3:
        raise LockedSourceLookupError(
            "approved review manifest must lock three HTML sources"
        )

    hashes: list[str] = []
    for binding in bindings:
        if not isinstance(binding, dict):
            raise LockedSourceLookupError(
                "approved review manifest binding is invalid"
            )
        value = binding.get("html_sha256")
        if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(
            value
        ):
            raise LockedSourceLookupError(
                "approved review manifest hash is invalid"
            )
        hashes.append(value)
    if len(set(hashes)) != 3:
        raise LockedSourceLookupError(
            "approved review manifest hashes must be unique"
        )
    return frozenset(hashes)


def _validate_locked_hashes(
    locked_hashes: Iterable[str],
) -> tuple[str, ...]:
    try:
        values = tuple(locked_hashes)
    except TypeError as exc:
        raise LockedSourceLookupError(
            "locked hashes must be full SHA-256 values"
        ) from exc
    if (
        not values
        or any(
            not isinstance(value, str)
            or not _SHA256_PATTERN.fullmatch(value)
            for value in values
        )
        or len(values) != len(set(values))
    ):
        raise LockedSourceLookupError(
            "locked hashes must be full SHA-256 values"
        )
    return tuple(sorted(values))


def _read_inventory(path: Path) -> tuple[dict[str, object], ...]:
    content = _read_regular_bytes(path, label="inventory")
    if not content:
        return ()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LockedSourceLookupError(
            "invalid inventory: expected UTF-8 JSONL"
        ) from exc

    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line:
            raise LockedSourceLookupError(
                f"invalid inventory row {line_number}"
            )
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LockedSourceLookupError(
                f"invalid inventory row {line_number}"
            ) from exc
        _validate_inventory_row(row, line_number=line_number)
        rows.append(row)
    return tuple(rows)


def _validate_inventory_row(
    row: object,
    *,
    line_number: int,
) -> None:
    if not isinstance(row, dict) or set(row) != _INVENTORY_FIELDS:
        raise LockedSourceLookupError(
            f"invalid inventory row {line_number}"
        )
    content_type = row["content_type"]
    relative_name = row["relative_name"]
    sha256 = row["sha256"]
    size_bytes = row["size_bytes"]
    source_root_id = row["source_root_id"]
    if (
        not isinstance(content_type, str)
        or content_type not in _CONTENT_TYPES
        or not _safe_relative_name(relative_name)
        or not isinstance(sha256, str)
        or not _SHA256_PATTERN.fullmatch(sha256)
        or type(size_bytes) is not int
        or size_bytes < 0
        or not isinstance(source_root_id, str)
        or not _SHA256_PATTERN.fullmatch(source_root_id)
    ):
        raise LockedSourceLookupError(
            f"invalid inventory row {line_number}"
        )


def _safe_relative_name(value: object) -> bool:
    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or "\\" in value
    ):
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and path.parts
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _anonymous_source_locator(row: dict[str, object]) -> str:
    digest = hashlib.sha256(
        (
            f"{_SOURCE_LOCATOR_DOMAIN}\0"
            f"{row['source_root_id']}\0{row['relative_name']}"
        ).encode("utf-8")
    ).hexdigest()
    return f"urn:xiaoro:local-source:sha256:{digest}"


def _read_json_object(
    path: Path,
    *,
    label: str,
) -> dict[str, object]:
    content = _read_regular_bytes(path, label=label)
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LockedSourceLookupError(f"{label} is invalid") from exc
    if not isinstance(payload, dict):
        raise LockedSourceLookupError(f"{label} is invalid")
    return payload


def _read_regular_bytes(path: Path, *, label: str) -> bytes:
    descriptor = -1
    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(
            metadata.st_mode
        ):
            raise LockedSourceLookupError(
                f"{label} must be a regular file"
            )
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != metadata.st_dev
            or opened.st_ino != metadata.st_ino
        ):
            raise LockedSourceLookupError(
                f"{label} must be a stable regular file"
            )
        with os.fdopen(descriptor, "rb") as source:
            descriptor = -1
            return source.read()
    except LockedSourceLookupError:
        raise
    except OSError as exc:
        raise LockedSourceLookupError(f"{label} could not be read") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _validate_manifest_digest(payload: dict[str, object]) -> None:
    expected = payload.get("manifest_sha256")
    if not isinstance(expected, str) or not _SHA256_PATTERN.fullmatch(
        expected
    ):
        raise LockedSourceLookupError(
            "approved review manifest digest is invalid"
        )
    unsigned = {
        key: value
        for key, value in payload.items()
        if key != "manifest_sha256"
    }
    actual = hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    if actual != expected:
        raise LockedSourceLookupError(
            "approved review manifest digest is invalid"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Find three locked historical review HTML files by exact "
            "SHA-256 only."
        )
    )
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--approved-manifest", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = find_locked_sources(
            args.inventory,
            locked_hashes=locked_hashes_from_manifest(
                args.approved_manifest
            ),
            output_path=args.output,
        )
    except LockedSourceLookupError:
        print(
            json.dumps(
                {"status": "error", "type": "locked_source_lookup_error"},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "duplicate_count": result.duplicate_count,
                "found_count": result.found_count,
                "missing_count": result.missing_count,
                "report_sha256": result.report_sha256,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
