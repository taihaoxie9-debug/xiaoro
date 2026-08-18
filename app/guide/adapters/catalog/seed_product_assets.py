from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field


class SeedProductAsset(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    product_id: int
    image_url: str = Field(min_length=1)
    relative_path: str = Field(min_length=1)
    media_type: str = Field(min_length=1)
    source_image_sha256: str = Field(min_length=64, max_length=64)
    bytes: int = Field(ge=0)
    platform: str | None = None
    detail_url: str | None = None


class SeedProductAssetIntegrityError(RuntimeError):
    pass


def load_seed_product_assets(
    *,
    manifest_path: str | Path,
    products_path: str | Path,
    asset_root: str | Path,
) -> Mapping[int, SeedProductAsset]:
    root = Path(asset_root)
    if not root.is_absolute():
        raise SeedProductAssetIntegrityError(
            "seed product asset root must be absolute"
        )
    root = root.resolve()

    manifest = _read_manifest(Path(manifest_path))
    products_path = Path(products_path)
    _validate_manifest(manifest, products_path)
    try:
        products_bytes = products_path.read_bytes()
    except OSError as exc:
        raise SeedProductAssetIntegrityError(
            f"cannot read seed product assets: {products_path}"
        ) from exc

    expected_sha = _require_string(manifest, "products_sha256")
    actual_sha = hashlib.sha256(products_bytes).hexdigest()
    if actual_sha != expected_sha:
        raise SeedProductAssetIntegrityError(
            "seed product assets SHA-256 mismatch"
        )

    assets = _parse_assets(products_bytes)
    expected_count = _require_integer(manifest, "product_count")
    if len(assets) != expected_count:
        raise SeedProductAssetIntegrityError(
            "seed product asset count mismatch: "
            f"manifest={expected_count}, loaded={len(assets)}"
        )
    _validate_asset_files(assets, root)
    return MappingProxyType(assets)


def _read_manifest(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SeedProductAssetIntegrityError(
            f"invalid seed product asset manifest: {path}"
        ) from exc
    if not isinstance(payload, dict):
        raise SeedProductAssetIntegrityError(
            "invalid seed product asset manifest: expected object"
        )

    expected_digest = _require_string(payload, "manifest_sha256")
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
    actual_digest = hashlib.sha256(
        canonical_json.encode("utf-8")
    ).hexdigest()
    if actual_digest != expected_digest:
        raise SeedProductAssetIntegrityError(
            "manifest SHA-256 mismatch"
        )
    return payload


def _validate_manifest(
    manifest: dict[str, object],
    products_path: Path,
) -> None:
    if _require_string(manifest, "schema_version") != "seed-product-images-v1":
        raise SeedProductAssetIntegrityError(
            "unsupported seed product asset schema version"
        )
    products_file = _require_string(manifest, "products_file")
    if products_file != products_path.name:
        raise SeedProductAssetIntegrityError(
            "seed product asset products_file mismatch"
        )


def _parse_assets(
    products_bytes: bytes,
) -> dict[int, SeedProductAsset]:
    if not products_bytes:
        raise SeedProductAssetIntegrityError(
            "seed product assets JSONL is empty"
        )
    try:
        text = products_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SeedProductAssetIntegrityError(
            "seed product assets JSONL is not valid UTF-8"
        ) from exc

    assets: dict[int, SeedProductAsset] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise SeedProductAssetIntegrityError(
                f"blank seed product asset line {line_number}"
            )
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SeedProductAssetIntegrityError(
                f"invalid seed product asset JSONL at line {line_number}"
            ) from exc
        if not isinstance(payload, dict):
            raise SeedProductAssetIntegrityError(
                f"invalid seed product asset at line {line_number}"
            )
        platform, detail_url = _derive_link(payload.get("image_url"))
        asset = SeedProductAsset.model_validate({
            **payload,
            "platform": platform,
            "detail_url": detail_url,
        })
        if asset.product_id in assets:
            raise SeedProductAssetIntegrityError(
                f"duplicate seed product asset {asset.product_id}"
            )
        assets[asset.product_id] = asset
    return assets


def _validate_asset_files(
    assets: Mapping[int, SeedProductAsset],
    asset_root: Path,
) -> None:
    for asset in assets.values():
        try:
            image_path = (asset_root / asset.relative_path).resolve()
        except (OSError, RuntimeError) as exc:
            raise SeedProductAssetIntegrityError(
                "cannot resolve seed product image: "
                f"{asset.product_id}"
            ) from exc
        if not image_path.is_relative_to(asset_root):
            raise SeedProductAssetIntegrityError(
                "seed product image escapes asset root: "
                f"{asset.product_id}"
            )
        if not image_path.is_file():
            raise SeedProductAssetIntegrityError(
                f"missing seed product image: {asset.product_id}"
            )
        try:
            payload = image_path.read_bytes()
        except OSError as exc:
            raise SeedProductAssetIntegrityError(
                f"cannot read seed product image: {asset.product_id}"
            ) from exc
        if len(payload) != asset.bytes:
            raise SeedProductAssetIntegrityError(
                "seed product image size mismatch: "
                f"{asset.product_id}"
            )
        if (
            hashlib.sha256(payload).hexdigest()
            != asset.source_image_sha256
        ):
            raise SeedProductAssetIntegrityError(
                "seed product image SHA-256 mismatch: "
                f"{asset.product_id}"
            )


def _derive_link(value: object) -> tuple[str | None, str | None]:
    if not isinstance(value, str):
        return None, None
    filename = Path(value).stem
    parts = filename.split("_")
    if len(parts) < 2:
        return None, None
    item_id = parts[-1]
    if not item_id.isdigit():
        return None, None
    if filename.startswith("tmall_"):
        return "天猫", f"https://detail.tmall.com/item.htm?id={item_id}"
    if filename.startswith("taobao_"):
        return "淘宝", f"https://item.taobao.com/item.htm?id={item_id}"
    if filename.startswith("jd_"):
        return "京东", f"https://item.jd.com/{item_id}.html"
    return None, None


def _require_string(
    payload: dict[str, object],
    key: str,
) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise SeedProductAssetIntegrityError(
            f"manifest field {key} must be a non-empty string"
        )
    return value


def _require_integer(
    payload: dict[str, object],
    key: str,
) -> int:
    value = payload.get(key)
    if not isinstance(value, int):
        raise SeedProductAssetIntegrityError(
            f"manifest field {key} must be an integer"
        )
    return value
