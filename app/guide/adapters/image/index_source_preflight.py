from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import ValidationError

from app.guide.retrieval.image_contracts import (
    ImageIndexSource,
    ImageSourcePreflightReport,
)


CANONICAL_IMAGE_SCHEMA_VERSION = "seed-product-images-v1"
DEFAULT_CANONICAL_IMAGE_COUNT = 103


class ImageSourcePreflightError(RuntimeError):
    pass


def preflight_image_sources(
    *,
    manifest_path: str | Path,
    products_path: str | Path,
    source_root: str | Path,
    expected_count: int = DEFAULT_CANONICAL_IMAGE_COUNT,
) -> ImageSourcePreflightReport:
    root = Path(source_root)
    if not root.is_absolute():
        raise ImageSourcePreflightError("source root must be absolute")
    try:
        root = root.resolve()
        root_is_directory = root.is_dir()
    except (OSError, RuntimeError) as exc:
        raise ImageSourcePreflightError(
            "cannot resolve source root"
        ) from exc
    if not root_is_directory:
        raise ImageSourcePreflightError("source root is not a directory")
    if expected_count < 1:
        raise ImageSourcePreflightError(
            "expected image count must be positive"
        )

    resolved_manifest = _resolve_metadata_path(
        Path(manifest_path),
        root=root,
        label="source manifest",
    )
    resolved_products = _resolve_metadata_path(
        Path(products_path),
        root=root,
        label="source products",
    )
    manifest = _read_manifest(resolved_manifest)
    _validate_manifest(
        manifest,
        products_path=resolved_products,
        expected_count=expected_count,
    )

    products_bytes = _read_bytes(
        resolved_products,
        label="source products",
    )
    products_sha256 = hashlib.sha256(products_bytes).hexdigest()
    if products_sha256 != _require_string(
        manifest,
        "products_sha256",
    ):
        raise ImageSourcePreflightError(
            "source products SHA-256 mismatch"
        )

    sources = _parse_sources(products_bytes)
    if len(sources) != expected_count:
        raise ImageSourcePreflightError(
            "source image count mismatch: "
            f"expected={expected_count}, loaded={len(sources)}"
        )

    source_digest = hashlib.sha256(
        "\n".join(
            f"{source.product_id}\t{source.source_sha256}"
            for source in sources
        ).encode("utf-8")
    ).hexdigest()
    if source_digest != _require_string(
        manifest,
        "source_images_sha256",
    ):
        raise ImageSourcePreflightError(
            "source image aggregate SHA-256 mismatch"
        )

    _validate_source_files(sources, root)
    return ImageSourcePreflightReport(
        source_manifest_path=resolved_manifest.relative_to(root).as_posix(),
        source_manifest_sha256=_require_string(
            manifest,
            "manifest_sha256",
        ),
        source_products_path=resolved_products.relative_to(root).as_posix(),
        source_products_sha256=products_sha256,
        sources=sources,
    )


def _resolve_metadata_path(
    path: Path,
    *,
    root: Path,
    label: str,
) -> Path:
    if not path.is_absolute():
        raise ImageSourcePreflightError(f"{label} path must be absolute")
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError) as exc:
        raise ImageSourcePreflightError(
            f"cannot resolve {label}: {path}"
        ) from exc
    if not resolved.is_relative_to(root):
        raise ImageSourcePreflightError(f"{label} escapes source root")
    return resolved


def _read_bytes(path: Path, *, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ImageSourcePreflightError(
            f"cannot read {label}: {path}"
        ) from exc


def _read_manifest(path: Path) -> dict[str, object]:
    manifest_bytes = _read_bytes(path, label="source manifest")
    try:
        payload = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ImageSourcePreflightError(
            f"invalid source manifest: {path}"
        ) from exc
    if not isinstance(payload, dict):
        raise ImageSourcePreflightError(
            "invalid source manifest: expected object"
        )

    unsigned = {
        key: value
        for key, value in payload.items()
        if key != "manifest_sha256"
    }
    canonical_json = json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    actual_sha256 = hashlib.sha256(
        canonical_json.encode("utf-8")
    ).hexdigest()
    if actual_sha256 != _require_string(payload, "manifest_sha256"):
        raise ImageSourcePreflightError(
            "source manifest SHA-256 mismatch"
        )
    return payload


def _validate_manifest(
    manifest: dict[str, object],
    *,
    products_path: Path,
    expected_count: int,
) -> None:
    if (
        _require_string(manifest, "schema_version")
        != CANONICAL_IMAGE_SCHEMA_VERSION
    ):
        raise ImageSourcePreflightError(
            "unsupported source image manifest schema"
        )
    if _require_string(manifest, "products_file") != products_path.name:
        raise ImageSourcePreflightError(
            "source manifest products_file mismatch"
        )
    manifest_count = _require_integer(manifest, "product_count")
    if manifest_count != expected_count:
        raise ImageSourcePreflightError(
            "source manifest product_count mismatch: "
            f"expected={expected_count}, manifest={manifest_count}"
        )


def _parse_sources(
    products_bytes: bytes,
) -> tuple[ImageIndexSource, ...]:
    if not products_bytes:
        raise ImageSourcePreflightError("source products JSONL is empty")
    try:
        text = products_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ImageSourcePreflightError(
            "source products JSONL is not valid UTF-8"
        ) from exc

    sources: list[ImageIndexSource] = []
    seen_ids: set[int] = set()
    seen_paths: set[str] = set()
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise ImageSourcePreflightError(
                f"blank source products line {line_number}"
            )
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ImageSourcePreflightError(
                f"invalid source products JSON at line {line_number}"
            ) from exc
        if not isinstance(payload, dict):
            raise ImageSourcePreflightError(
                f"invalid source product at line {line_number}"
            )
        try:
            source = ImageIndexSource(
                product_id=payload.get("product_id"),
                source_path=payload.get("relative_path"),
                source_bytes=payload.get("bytes"),
                source_sha256=payload.get("source_image_sha256"),
                media_type=payload.get("media_type"),
            )
        except ValidationError as exc:
            raise ImageSourcePreflightError(
                f"invalid source product at line {line_number}"
            ) from exc

        if source.product_id in seen_ids:
            raise ImageSourcePreflightError(
                f"duplicate product_id {source.product_id}"
            )
        if source.source_path in seen_paths:
            raise ImageSourcePreflightError(
                f"duplicate source path {source.source_path}"
            )
        seen_ids.add(source.product_id)
        seen_paths.add(source.source_path)
        sources.append(source)

    product_ids = tuple(source.product_id for source in sources)
    if product_ids != tuple(sorted(product_ids)):
        raise ImageSourcePreflightError(
            "source rows must use stable numeric product_id order"
        )
    return tuple(sources)


def _validate_source_files(
    sources: tuple[ImageIndexSource, ...],
    root: Path,
) -> None:
    for source in sources:
        try:
            image_path = (root / source.source_path).resolve()
        except (OSError, RuntimeError) as exc:
            raise ImageSourcePreflightError(
                "cannot resolve source image for product_id "
                f"{source.product_id}"
            ) from exc
        if not image_path.is_relative_to(root):
            raise ImageSourcePreflightError(
                "source image escapes source root for product_id "
                f"{source.product_id}"
            )
        if not image_path.is_file():
            raise ImageSourcePreflightError(
                f"missing source image for product_id {source.product_id}"
            )
        content = _read_bytes(image_path, label="source image")
        if len(content) != source.source_bytes:
            raise ImageSourcePreflightError(
                "source image bytes mismatch for product_id "
                f"{source.product_id}"
            )
        if hashlib.sha256(content).hexdigest() != source.source_sha256:
            raise ImageSourcePreflightError(
                "source image SHA-256 mismatch for product_id "
                f"{source.product_id}"
            )


def _require_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ImageSourcePreflightError(
            f"source manifest field {key} must be a non-empty string"
        )
    return value


def _require_integer(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ImageSourcePreflightError(
            f"source manifest field {key} must be an integer"
        )
    return value
