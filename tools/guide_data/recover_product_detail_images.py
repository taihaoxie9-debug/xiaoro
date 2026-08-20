from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PIL import Image


RecoveryStatus = Literal[
    "existing_local",
    "recovered_exact",
    "recovered_from_html",
    "current_new_version",
    "blocked",
]
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".avif"}


class ProductDetailImageRecoveryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProductDetailImageRecoveryResult:
    output_path: Path
    image_count: int
    status_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class _Candidate:
    path: Path
    source: Literal["old_asset", "saved_html", "current_source"]
    file_name: str
    source_url: str | None = None
    historical_file: str | None = None


def recover_product_detail_images(
    *,
    source_root: str | Path,
    image_root: str | Path,
    old_asset_roots: tuple[Path, ...],
    saved_html_roots: tuple[Path, ...],
    current_source_root: str | Path | None,
    output_path: str | Path,
) -> ProductDetailImageRecoveryResult:
    source_directory = Path(source_root)
    image_directory = Path(image_root)
    destination = Path(output_path)
    if not source_directory.is_dir():
        raise ProductDetailImageRecoveryError(
            "OCR source root is unavailable"
        )
    image_directory.mkdir(parents=True, exist_ok=True)
    old_index = _index_images(old_asset_roots, "old_asset")
    html_index = _index_saved_html_images(saved_html_roots)
    current_sources = _load_current_sources(current_source_root)

    rows: list[dict[str, object]] = []
    for source_path in sorted(
        source_directory.glob("detail_*_ocr.json")
    ):
        source_bytes, source = _load_source(source_path)
        product_id = source["pid"]
        images = source["images"]
        source_sha = hashlib.sha256(source_bytes).hexdigest()
        for image_index, image in enumerate(images):
            if not isinstance(image, dict):
                raise ProductDetailImageRecoveryError(
                    "OCR source image row is invalid"
                )
            historical_file = image.get("file")
            if not isinstance(historical_file, str) or not historical_file:
                raise ProductDetailImageRecoveryError(
                    "OCR source image file is invalid"
                )
            attempts = ["existing_local"]
            existing = _existing_local_candidate(
                image_directory=image_directory,
                product_id=product_id,
                image=image,
            )
            if existing is not None:
                rows.append(
                    _successful_row(
                        product_id=product_id,
                        source_file=source_path.name,
                        source_sha256=source_sha,
                        image_index=image_index,
                        historical_file=historical_file,
                        status="existing_local",
                        candidate=existing,
                        image_directory=image_directory,
                        attempts=attempts,
                        copy=False,
                    )
                )
                continue

            attempts.append("old_asset")
            old_candidate = _select_candidate(
                old_index.get(historical_file, ()),
                expected_size=image.get("size"),
            )
            if old_candidate is not None:
                rows.append(
                    _successful_row(
                        product_id=product_id,
                        source_file=source_path.name,
                        source_sha256=source_sha,
                        image_index=image_index,
                        historical_file=historical_file,
                        status="recovered_exact",
                        candidate=old_candidate,
                        image_directory=image_directory,
                        attempts=attempts,
                        copy=True,
                    )
                )
                continue

            attempts.append("saved_html")
            html_candidate = _select_candidate(
                html_index.get(historical_file, ()),
                expected_size=image.get("size"),
            )
            if html_candidate is not None:
                rows.append(
                    _successful_row(
                        product_id=product_id,
                        source_file=source_path.name,
                        source_sha256=source_sha,
                        image_index=image_index,
                        historical_file=historical_file,
                        status="recovered_from_html",
                        candidate=html_candidate,
                        image_directory=image_directory,
                        attempts=attempts,
                        copy=True,
                    )
                )
                continue

            attempts.append("current_source")
            current_candidate, is_same_file = _current_candidate(
                product_id=product_id,
                image_index=image_index,
                historical_file=historical_file,
                current_sources=current_sources,
            )
            if current_candidate is not None:
                rows.append(
                    _successful_row(
                        product_id=product_id,
                        source_file=source_path.name,
                        source_sha256=source_sha,
                        image_index=image_index,
                        historical_file=historical_file,
                        status=(
                            "recovered_exact"
                            if is_same_file
                            else "current_new_version"
                        ),
                        candidate=current_candidate,
                        image_directory=image_directory,
                        attempts=attempts,
                        copy=True,
                    )
                )
                continue

            rows.append(
                {
                    "product_id": product_id,
                    "source_file": source_path.name,
                    "source_sha256": source_sha,
                    "image_index": image_index,
                    "historical_file": historical_file,
                    "status": "blocked",
                    "recovery_source": None,
                    "recovered_file": None,
                    "image_sha256": None,
                    "local_image": None,
                    "source_url": image.get("source_url"),
                    "attempts": attempts,
                    "reason": "no identity-bound source image was recoverable",
                }
            )

    rows.sort(
        key=lambda item: (
            int(item["product_id"]),
            str(item["source_file"]),
            int(item["image_index"]),
        )
    )
    _atomic_write(destination, _jsonl_bytes(rows))
    status_counts = dict(
        sorted(Counter(str(row["status"]) for row in rows).items())
    )
    return ProductDetailImageRecoveryResult(
        output_path=destination,
        image_count=len(rows),
        status_counts=status_counts,
    )


def _index_images(
    roots: tuple[Path, ...],
    source: Literal["old_asset"],
) -> dict[str, tuple[_Candidate, ...]]:
    by_name: dict[str, list[_Candidate]] = defaultdict(list)
    for root in sorted((Path(item) for item in roots), key=lambda item: str(item)):
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES:
                by_name[path.name].append(
                    _Candidate(
                        path=path,
                        source=source,
                        file_name=path.name,
                    )
                )
    return {
        name: tuple(candidates)
        for name, candidates in by_name.items()
    }


def _index_saved_html_images(
    roots: tuple[Path, ...],
) -> dict[str, tuple[_Candidate, ...]]:
    by_name: dict[str, list[_Candidate]] = defaultdict(list)
    for root in sorted((Path(item) for item in roots), key=lambda item: str(item)):
        if not root.is_dir():
            continue
        html_stems = {
            path.stem
            for path in root.rglob("*.html")
            if path.is_file()
        }
        html_stems.update(
            path.stem for path in root.rglob("*.htm") if path.is_file()
        )
        for path in sorted(root.rglob("*")):
            if (
                not path.is_file()
                or path.suffix.lower() not in _IMAGE_SUFFIXES
            ):
                continue
            parent_name = path.parent.name
            if not parent_name.endswith("_files"):
                continue
            page_stem = parent_name.removesuffix("_files")
            if page_stem not in html_stems:
                continue
            by_name[path.name].append(
                _Candidate(
                    path=path,
                    source="saved_html",
                    file_name=path.name,
                )
            )
    return {
        name: tuple(candidates)
        for name, candidates in by_name.items()
    }


def _load_current_sources(
    root: str | Path | None,
) -> dict[int, tuple[_Candidate, ...]]:
    if root is None:
        return {}
    directory = Path(root)
    if not directory.is_dir():
        return {}
    by_product: dict[int, list[_Candidate]] = defaultdict(list)
    for path in sorted(directory.glob("detail_*_ocr.json")):
        _, payload = _load_source(path)
        for image in payload["images"]:
            if not isinstance(image, dict):
                continue
            file_name = image.get("file")
            local_image = image.get("local_image")
            if not isinstance(file_name, str) or not isinstance(
                local_image,
                str,
            ):
                continue
            local_path = Path(local_image)
            if not local_path.is_absolute():
                local_path = directory / local_path
            local_path = local_path.resolve()
            if not local_path.is_file():
                alternate = directory.parent / local_image
                if alternate.is_file():
                    local_path = alternate.resolve()
                else:
                    continue
            by_product[int(payload["pid"])].append(
                _Candidate(
                    path=local_path,
                    source="current_source",
                    file_name=file_name,
                    source_url=(
                        image.get("source_url")
                        if isinstance(image.get("source_url"), str)
                        else None
                    ),
                    historical_file=(
                        image.get("historical_file")
                        if isinstance(
                            image.get("historical_file"),
                            str,
                        )
                        else None
                    ),
                )
            )
    return {
        product_id: tuple(candidates)
        for product_id, candidates in by_product.items()
    }


def _existing_local_candidate(
    *,
    image_directory: Path,
    product_id: int,
    image: dict[str, object],
) -> _Candidate | None:
    local_image = image.get("local_image")
    if isinstance(local_image, str) and local_image:
        candidate = image_directory.parent / local_image
    else:
        file_name = image.get("file")
        if not isinstance(file_name, str):
            return None
        candidate = image_directory / str(product_id) / file_name
    if not candidate.is_file():
        return None
    recorded_sha = image.get("image_sha256")
    actual_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
    if isinstance(recorded_sha, str) and recorded_sha != actual_sha:
        raise ProductDetailImageRecoveryError(
            "existing local image SHA mismatch"
        )
    return _Candidate(
        path=candidate,
        source="old_asset",
        file_name=candidate.name,
        source_url=(
            image.get("source_url")
            if isinstance(image.get("source_url"), str)
            else None
        ),
    )


def _select_candidate(
    candidates: tuple[_Candidate, ...],
    *,
    expected_size: object,
) -> _Candidate | None:
    if not candidates:
        return None
    expected = _size_tuple(expected_size)
    valid = [
        candidate
        for candidate in candidates
        if _valid_image(candidate.path)
        and (expected is None or _image_size(candidate.path) == expected)
    ]
    if not valid:
        return None
    by_sha: dict[str, _Candidate] = {}
    for candidate in valid:
        digest = hashlib.sha256(candidate.path.read_bytes()).hexdigest()
        by_sha.setdefault(digest, candidate)
    if len(by_sha) != 1:
        return None
    return next(iter(by_sha.values()))


def _current_candidate(
    *,
    product_id: int,
    image_index: int,
    historical_file: str,
    current_sources: dict[int, tuple[_Candidate, ...]],
) -> tuple[_Candidate | None, bool]:
    candidates = current_sources.get(product_id, ())
    exact = [
        candidate
        for candidate in candidates
        if (
            candidate.file_name == historical_file
            or candidate.historical_file == historical_file
        )
    ]
    if len(exact) == 1:
        return (
            exact[0],
            exact[0].file_name == historical_file,
        )
    if image_index < len(candidates):
        return candidates[image_index], False
    return None, False


def _successful_row(
    *,
    product_id: int,
    source_file: str,
    source_sha256: str,
    image_index: int,
    historical_file: str,
    status: RecoveryStatus,
    candidate: _Candidate,
    image_directory: Path,
    attempts: list[str],
    copy: bool,
) -> dict[str, object]:
    content = candidate.path.read_bytes()
    image_sha = hashlib.sha256(content).hexdigest()
    if not _valid_image(candidate.path):
        raise ProductDetailImageRecoveryError(
            "recovered source image is invalid"
        )
    if copy:
        suffix = candidate.path.suffix.lower()
        if suffix == ".jpeg":
            suffix = ".jpg"
        target_name = f"{image_index:03d}_{image_sha[:16]}{suffix}"
        target = image_directory / str(product_id) / target_name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copyfile(candidate.path, target)
        if hashlib.sha256(target.read_bytes()).hexdigest() != image_sha:
            raise ProductDetailImageRecoveryError(
                "recovered image copy SHA mismatch"
            )
    else:
        target = candidate.path
    try:
        local_image = str(target.relative_to(image_directory.parent))
    except ValueError as exc:
        raise ProductDetailImageRecoveryError(
            "recovered image is outside the asset root"
        ) from exc
    return {
        "product_id": product_id,
        "source_file": source_file,
        "source_sha256": source_sha256,
        "image_index": image_index,
        "historical_file": historical_file,
        "status": status,
        "recovery_source": candidate.source,
        "recovered_file": candidate.file_name,
        "image_sha256": image_sha,
        "local_image": local_image,
        "source_url": candidate.source_url,
        "attempts": list(attempts),
        "reason": None,
    }


def _load_source(path: Path) -> tuple[bytes, dict[str, object]]:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductDetailImageRecoveryError(
            "OCR source is invalid"
        ) from exc
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("pid"), int)
        or isinstance(payload.get("pid"), bool)
        or int(payload["pid"]) <= 0
        or not isinstance(payload.get("images"), list)
    ):
        raise ProductDetailImageRecoveryError(
            "OCR source contract is invalid"
        )
    return raw, payload


def _size_tuple(value: object) -> tuple[int, int] | None:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(
            not isinstance(item, int)
            or isinstance(item, bool)
            or item <= 0
            for item in value
        )
    ):
        return None
    return int(value[0]), int(value[1])


def _valid_image(path: Path) -> bool:
    try:
        with Image.open(path) as image:
            image.verify()
        return True
    except OSError:
        return False


def _image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


def _jsonl_bytes(rows: list[dict[str, object]]) -> bytes:
    return b"".join(
        (
            json.dumps(
                row,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        for row in rows
    )


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--image-root", required=True)
    parser.add_argument("--old-root", action="append", default=[])
    parser.add_argument("--saved-html-root", action="append", default=[])
    parser.add_argument("--current-source-root")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = recover_product_detail_images(
        source_root=args.source_root,
        image_root=args.image_root,
        old_asset_roots=tuple(Path(item) for item in args.old_root),
        saved_html_roots=tuple(
            Path(item) for item in args.saved_html_root
        ),
        current_source_root=args.current_source_root,
        output_path=args.output,
    )
    print(
        json.dumps(
            {
                "output_path": str(result.output_path),
                "image_count": result.image_count,
                "status_counts": result.status_counts,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ProductDetailImageRecoveryError",
    "ProductDetailImageRecoveryResult",
    "recover_product_detail_images",
]
