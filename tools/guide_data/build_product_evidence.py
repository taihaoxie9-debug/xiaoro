from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from app.guide.retrieval.product_evidence_assets import (
    ImageAuditRecord,
    ProductEvidenceBlock,
    load_product_evidence_assets,
    product_evidence_id,
)
from tools.guide_data.selection_concept_audit import (
    load_selection_concept_audit,
    project_evidence_selection_review,
)


class ProductEvidenceBuildError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProductEvidenceBuildResult:
    manifest_path: Path
    evidence_path: Path
    audit_path: Path
    evidence_count: int
    product_count: int
    image_count: int


@dataclass(frozen=True, slots=True)
class _Source:
    product_id: int
    source_file: str
    source_sha256: str
    images: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class _ResolvedImage:
    image_sha256: str | None
    local_image: str | None
    recovery_status: str | None
    resolved_image_file: str | None
    source_url: str | None


def build_product_evidence(
    *,
    source_root: str | Path,
    image_root: str | Path,
    audit_paths: tuple[Path, ...],
    review_paths: tuple[Path, ...],
    output_root: str | Path,
    recovery_paths: tuple[Path, ...] = (),
    concept_audit_path: str | Path | None = None,
) -> ProductEvidenceBuildResult:
    source_directory = Path(source_root)
    image_directory = Path(image_root)
    destination = Path(output_root)
    if not source_directory.is_dir():
        raise ProductEvidenceBuildError("OCR source root is unavailable")
    if not image_directory.is_dir():
        raise ProductEvidenceBuildError("source image root is unavailable")
    if not audit_paths:
        raise ProductEvidenceBuildError("image audit inventory is empty")

    concept_audit = load_selection_concept_audit(concept_audit_path)
    sources = _load_sources(source_directory)
    source_images = {
        (source.product_id, source.source_file, index): image
        for source in sources.values()
        for index, image in enumerate(source.images)
    }
    recovery_by_key = _load_recovery_rows(
        paths=recovery_paths,
        sources=sources,
        source_images=source_images,
    )
    audit_inputs = _load_rows(audit_paths, "image audit")
    audit_by_key: dict[tuple[int, str, int], dict[str, object]] = {}
    for row in audit_inputs:
        key = _row_key(row)
        if key in audit_by_key:
            raise ProductEvidenceBuildError(
                "duplicate image audit decision"
            )
        image = source_images.get(key)
        if image is None:
            raise ProductEvidenceBuildError(
                "image audit does not bind a source image"
            )
        if _required_string(row, "image_file") != image.get("file"):
            raise ProductEvidenceBuildError(
                "image audit file binding is invalid"
            )
        audit_by_key[key] = row
    missing_audits = sorted(set(source_images) - set(audit_by_key))
    if missing_audits:
        raise ProductEvidenceBuildError(
            "source image is missing an audit decision"
        )

    evidence: list[ProductEvidenceBlock] = []
    evidence_ids_by_audit: dict[
        tuple[int, str, int], list[str]
    ] = defaultdict(list)
    primary_statuses_by_audit: dict[
        tuple[int, str, int], list[str]
    ] = defaultdict(list)
    for row in _load_rows(review_paths, "evidence review"):
        key = _row_key(row)
        source = sources.get(key[1])
        image = source_images.get(key)
        audit_row = audit_by_key.get(key)
        if source is None or image is None or audit_row is None:
            raise ProductEvidenceBuildError(
                "review does not bind an audited source image"
            )
        if (
            _required_string(row, "image_file") != image.get("file")
            or _required_string(audit_row, "image_file")
            != image.get("file")
        ):
            raise ProductEvidenceBuildError(
                "review image binding is invalid"
            )
        review_status = _required_string(row, "review_status")
        audit_status = _required_string(audit_row, "review_status")
        mixed_statuses = {
            "accepted",
            "ambiguous",
            "expired",
            "cross_product",
        }
        if (
            review_status != audit_status
            and not (
                audit_status == "accepted"
                and review_status in mixed_statuses
            )
        ):
            raise ProductEvidenceBuildError(
                "review status is incompatible with image audit"
            )
        exact_text = _required_string(row, "exact_text")
        transcription_basis = row.get(
            "transcription_basis",
            "ocr_exact",
        )
        if transcription_basis not in {
            "ocr_exact",
            "visual_transcription",
        }:
            raise ProductEvidenceBuildError(
                "transcription basis is invalid"
            )
        ocr_text = image.get("ocr_text")
        if (
            transcription_basis == "ocr_exact"
            and (
                not isinstance(ocr_text, str)
                or exact_text not in ocr_text
            )
        ):
            raise ProductEvidenceBuildError(
                "review exact text is not an OCR substring: "
                f"product={source.product_id} "
                f"source={source.source_file} "
                f"image_index={key[2]} "
                f"text={exact_text[:80]!r}"
            )
        resolved_image = _resolve_local_image(
            image_directory=image_directory,
            source=source,
            image=image,
            image_index=key[2],
            recovery_by_key=recovery_by_key,
            require_available=True,
        )
        assert resolved_image.image_sha256 is not None
        assert resolved_image.recovery_status is not None
        assert resolved_image.resolved_image_file is not None
        source_locator = (
            "urn:xiaoro:product-detail-image:"
            f"pid:{source.product_id}:"
            f"source-sha256:{source.source_sha256}:"
            f"image-sha256:{resolved_image.image_sha256}"
        )
        supporting_sources, supporting_keys = _resolve_supporting_sources(
            row=row,
            sources=sources,
            source_images=source_images,
            audit_by_key=audit_by_key,
            image_directory=image_directory,
            recovery_by_key=recovery_by_key,
        )
        subject_scope = row.get("subject_scope")
        variant_scope = row.get("variant_scope")
        selection_review = project_evidence_selection_review(
            audit=concept_audit,
            product_id=source.product_id,
            subject_scope=str(subject_scope),
            variant_scope=(
                variant_scope
                if isinstance(variant_scope, str)
                else None
            ),
            selection_review=row.get("selection_review"),
        )
        payload: dict[str, object] = {
            "product_id": source.product_id,
            "subject_scope": subject_scope,
            "variant_scope": variant_scope,
            "management_label": row.get("management_label"),
            "transcription_basis": transcription_basis,
            "exact_text": exact_text.strip(),
            "plain_meaning": _required_string(
                row,
                "plain_meaning",
            ).strip(),
            "relations": row.get("relations", []),
            "qualifiers": _qualifiers(row.get("qualifiers")),
            "free_descriptors": row.get("free_descriptors", []),
            "review_status": review_status,
            "allowed_uses": row.get("allowed_uses", []),
            "forbidden_uses": row.get("forbidden_uses", []),
            "review_rationale": _required_string(
                row,
                "review_rationale",
            ).strip(),
            "selection_review": selection_review,
            "source": {
                "source_file": source.source_file,
                "source_sha256": source.source_sha256,
                "image_file": image["file"],
                "image_index": key[2],
                "image_sha256": resolved_image.image_sha256,
                "source_locator": source_locator,
                "source_url": resolved_image.source_url,
                "recovery_status": resolved_image.recovery_status,
                "resolved_image_file": (
                    resolved_image.resolved_image_file
                ),
                "image_region": row.get("image_region"),
            },
            "supporting_sources": supporting_sources,
        }
        try:
            block = ProductEvidenceBlock.model_validate(
                {
                    "evidence_id": product_evidence_id(payload),
                    **payload,
                },
                strict=True,
            )
        except ValueError as exc:
            raise ProductEvidenceBuildError(
                "review evidence contract is invalid"
            ) from exc
        evidence.append(block)
        evidence_ids_by_audit[key].append(block.evidence_id)
        primary_statuses_by_audit[key].append(block.review_status)
        for supporting_key in supporting_keys:
            evidence_ids_by_audit[supporting_key].append(
                block.evidence_id
            )

    evidence_by_id = {item.evidence_id: item for item in evidence}
    if len(evidence_by_id) != len(evidence):
        raise ProductEvidenceBuildError(
            "duplicate evidence block requires an explicit duplicate audit"
        )
    evidence = sorted(evidence_by_id.values(), key=lambda item: item.evidence_id)

    audit: list[ImageAuditRecord] = []
    for key in sorted(audit_by_key):
        row = audit_by_key[key]
        source = sources[key[1]]
        image = source_images[key]
        status = _required_string(row, "review_status")
        if (
            status == "accepted"
            and "accepted" not in primary_statuses_by_audit.get(key, [])
        ):
            raise ProductEvidenceBuildError(
                "accepted image audit requires accepted evidence"
            )
        require_available = status != "blocked"
        resolved_image = _resolve_local_image(
            image_directory=image_directory,
            source=source,
            image=image,
            image_index=key[2],
            recovery_by_key=recovery_by_key,
            require_available=require_available,
        )
        payload = {
            "product_id": source.product_id,
            "source_file": source.source_file,
            "source_sha256": source.source_sha256,
            "image_file": image["file"],
            "image_index": key[2],
            "image_sha256": resolved_image.image_sha256,
            "local_image": resolved_image.local_image,
            "review_status": status,
            "rationale": _required_string(row, "rationale").strip(),
            "recovery_attempts": row.get("recovery_attempts", []),
            "evidence_ids": sorted(evidence_ids_by_audit.get(key, [])),
            "duplicate_of_image_sha256": row.get(
                "duplicate_of_image_sha256"
            ),
        }
        audit_id = hashlib.sha256(
            _canonical_json(payload).encode("utf-8")
        ).hexdigest()
        try:
            audit.append(
                ImageAuditRecord.model_validate(
                    {"audit_id": audit_id, **payload},
                    strict=True,
                )
            )
        except ValueError as exc:
            raise ProductEvidenceBuildError(
                "image audit contract is invalid"
            ) from exc

    evidence_bytes = _jsonl_bytes(
        [item.model_dump(mode="json") for item in evidence]
    )
    audit_bytes = _jsonl_bytes(
        [item.model_dump(mode="json") for item in audit]
    )
    evidence_sha = hashlib.sha256(evidence_bytes).hexdigest()
    audit_sha = hashlib.sha256(audit_bytes).hexdigest()
    evidence_name = f"product_evidence_v1.{evidence_sha}.jsonl"
    audit_name = f"image_audit_v1.{audit_sha}.jsonl"
    status_counts = dict(
        sorted(Counter(item.review_status for item in audit).items())
    )
    allowed_use_counts = dict(
        sorted(
            Counter(
                capability
                for item in evidence
                for capability in item.allowed_uses
            ).items()
        )
    )
    unsigned_manifest: dict[str, object] = {
        "schema_version": "product-evidence-v1",
        "asset_id": "guide-product-evidence-v1",
        "asset_version": (
            f"product-evidence-v1:sha256:{evidence_sha}"
        ),
        "evidence_file": evidence_name,
        "evidence_sha256": evidence_sha,
        "audit_file": audit_name,
        "audit_sha256": audit_sha,
        "evidence_count": len(evidence),
        "product_count": len({item.product_id for item in evidence}),
        "image_count": len(audit),
        "status_counts": status_counts,
        "allowed_use_counts": allowed_use_counts,
    }
    if concept_audit is not None:
        unsigned_manifest["selection_concept_audit_sha256"] = (
            concept_audit.sha256
        )
    manifest_payload = {
        **unsigned_manifest,
        "manifest_sha256": hashlib.sha256(
            _canonical_json(unsigned_manifest).encode("utf-8")
        ).hexdigest(),
    }
    destination.mkdir(parents=True, exist_ok=True)
    evidence_path = destination / evidence_name
    audit_path = destination / audit_name
    manifest_path = destination / "product_evidence_v1_manifest.json"
    _atomic_write(evidence_path, evidence_bytes)
    _atomic_write(audit_path, audit_bytes)
    _atomic_write(
        manifest_path,
        _canonical_json(manifest_payload).encode("utf-8"),
    )
    load_product_evidence_assets(
        manifest_path=manifest_path,
        evidence_path=evidence_path,
        audit_path=audit_path,
    )
    return ProductEvidenceBuildResult(
        manifest_path=manifest_path,
        evidence_path=evidence_path,
        audit_path=audit_path,
        evidence_count=len(evidence),
        product_count=len({item.product_id for item in evidence}),
        image_count=len(audit),
    )


def _load_sources(source_directory: Path) -> dict[str, _Source]:
    sources: dict[str, _Source] = {}
    for path in sorted(source_directory.glob("detail_*_ocr.json")):
        try:
            raw = path.read_bytes()
            payload = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProductEvidenceBuildError(
                "OCR source is invalid"
            ) from exc
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("pid"), int)
            or isinstance(payload.get("pid"), bool)
            or int(payload["pid"]) <= 0
            or not isinstance(payload.get("images"), list)
        ):
            raise ProductEvidenceBuildError(
                "OCR source contract is invalid"
            )
        source = _Source(
            product_id=int(payload["pid"]),
            source_file=path.name,
            source_sha256=hashlib.sha256(raw).hexdigest(),
            images=tuple(payload["images"]),
        )
        if path.name in sources:
            raise ProductEvidenceBuildError(
                "duplicate OCR source file"
            )
        sources[path.name] = source
    if not sources:
        raise ProductEvidenceBuildError("OCR source inventory is empty")
    return sources


def _load_rows(paths: tuple[Path, ...], label: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted((Path(item) for item in paths), key=lambda item: str(item)):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            raise ProductEvidenceBuildError(
                f"{label} file is unavailable"
            ) from exc
        for line_number, line in enumerate(lines, start=1):
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ProductEvidenceBuildError(
                    f"invalid {label} line {line_number}"
                ) from exc
            if not isinstance(row, dict):
                raise ProductEvidenceBuildError(
                    f"{label} row must be an object"
                )
            rows.append(row)
    return rows


def _row_key(row: dict[str, object]) -> tuple[int, str, int]:
    product_id = row.get("product_id")
    source_file = row.get("source_file")
    image_index = row.get("image_index")
    if (
        not isinstance(product_id, int)
        or isinstance(product_id, bool)
        or product_id <= 0
        or not isinstance(source_file, str)
        or not source_file
        or not isinstance(image_index, int)
        or isinstance(image_index, bool)
        or image_index < 0
    ):
        raise ProductEvidenceBuildError("review row key is invalid")
    return product_id, source_file, image_index


def _load_recovery_rows(
    *,
    paths: tuple[Path, ...],
    sources: dict[str, _Source],
    source_images: dict[
        tuple[int, str, int],
        dict[str, object],
    ],
) -> dict[tuple[int, str, int], dict[str, object]]:
    rows: dict[tuple[int, str, int], dict[str, object]] = {}
    if not paths:
        return rows
    for row in _load_rows(paths, "image recovery"):
        source_file = row.get("source_file")
        if not isinstance(source_file, str) or source_file not in sources:
            continue
        key = _row_key(row)
        if key in rows:
            raise ProductEvidenceBuildError(
                "duplicate image recovery decision"
            )
        source = sources[source_file]
        image = source_images.get(key)
        if image is None or source.product_id != key[0]:
            raise ProductEvidenceBuildError(
                "image recovery does not bind a source image"
            )
        if (
            row.get("source_sha256") != source.source_sha256
            or row.get("historical_file") != image.get("file")
        ):
            raise ProductEvidenceBuildError(
                "image recovery source binding is invalid"
            )
        rows[key] = row
    return rows


def _resolve_local_image(
    *,
    image_directory: Path,
    source: _Source,
    image: dict[str, object],
    image_index: int,
    recovery_by_key: dict[
        tuple[int, str, int],
        dict[str, object],
    ],
    require_available: bool,
) -> _ResolvedImage:
    image_file = image.get("file")
    if not isinstance(image_file, str) or not image_file:
        raise ProductEvidenceBuildError("source image file is invalid")
    recovery = recovery_by_key.get(
        (source.product_id, source.source_file, image_index)
    )
    if recovery is not None:
        recovery_status = _required_string(recovery, "status")
        if recovery_status == "blocked":
            if require_available:
                raise ProductEvidenceBuildError(
                    "audited source image is unavailable"
                )
            return _ResolvedImage(
                image_sha256=None,
                local_image=None,
                recovery_status=None,
                resolved_image_file=None,
                source_url=None,
            )
        if recovery_status not in {
            "existing_local",
            "recovered_exact",
            "recovered_from_html",
            "current_new_version",
        }:
            raise ProductEvidenceBuildError(
                "image recovery status is invalid"
            )
        relative = _required_string(recovery, "local_image")
        _required_string(recovery, "recovered_file")
        candidate = image_directory.parent / relative
        source_url = recovery.get("source_url")
        if source_url is not None and (
            not isinstance(source_url, str) or not source_url
        ):
            raise ProductEvidenceBuildError(
                "image recovery source URL is invalid"
            )
    else:
        local_image = image.get("local_image")
        if isinstance(local_image, str) and local_image:
            candidate = image_directory.parent / local_image
            relative = local_image
        else:
            candidate = (
                image_directory / str(source.product_id) / image_file
            )
            relative = (
                f"{image_directory.name}/{source.product_id}/{image_file}"
            )
        recovery_status = "source_record"
        source_url = image.get("source_url")
    if not candidate.is_file():
        if require_available:
            raise ProductEvidenceBuildError(
                "audited source image is unavailable"
            )
        return _ResolvedImage(
            image_sha256=None,
            local_image=None,
            recovery_status=None,
            resolved_image_file=None,
            source_url=None,
        )
    actual_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
    if (
        recovery is not None
        and recovery.get("image_sha256") != actual_sha
    ):
        raise ProductEvidenceBuildError(
            "image recovery SHA mismatch"
        )
    recorded_sha = image.get("image_sha256")
    if isinstance(recorded_sha, str) and recorded_sha != actual_sha:
        raise ProductEvidenceBuildError(
            "source image SHA mismatch"
        )
    return _ResolvedImage(
        image_sha256=actual_sha,
        local_image=relative,
        recovery_status=recovery_status,
        resolved_image_file=candidate.name,
        source_url=source_url if isinstance(source_url, str) else None,
    )


def _resolve_supporting_sources(
    *,
    row: dict[str, object],
    sources: dict[str, _Source],
    source_images: dict[
        tuple[int, str, int],
        dict[str, object],
    ],
    audit_by_key: dict[
        tuple[int, str, int],
        dict[str, object],
    ],
    image_directory: Path,
    recovery_by_key: dict[
        tuple[int, str, int],
        dict[str, object],
    ],
) -> tuple[list[dict[str, object]], list[tuple[int, str, int]]]:
    raw_sources = row.get("supporting_sources", [])
    if not isinstance(raw_sources, list):
        raise ProductEvidenceBuildError(
            "supporting sources must be a list"
        )
    resolved: list[dict[str, object]] = []
    keys: list[tuple[int, str, int]] = []
    product_id = row.get("product_id")
    assert isinstance(product_id, int)
    for raw_source in raw_sources:
        if not isinstance(raw_source, dict):
            raise ProductEvidenceBuildError(
                "supporting source must be an object"
            )
        source_file = _required_string(raw_source, "source_file")
        image_index = raw_source.get("image_index")
        if (
            not isinstance(image_index, int)
            or isinstance(image_index, bool)
            or image_index < 0
        ):
            raise ProductEvidenceBuildError(
                "supporting source image index is invalid"
            )
        key = (product_id, source_file, image_index)
        source = sources.get(source_file)
        image = source_images.get(key)
        audit = audit_by_key.get(key)
        if source is None or image is None or audit is None:
            raise ProductEvidenceBuildError(
                "supporting source does not bind an audited image"
            )
        if (
            source.product_id != product_id
            or _required_string(raw_source, "image_file")
            != image.get("file")
        ):
            raise ProductEvidenceBuildError(
                "supporting source image binding is invalid"
            )
        if _required_string(audit, "review_status") in {
            "blocked",
            "irrelevant",
            "duplicate",
        }:
            raise ProductEvidenceBuildError(
                "supporting source audit status is not usable"
            )
        resolved_image = _resolve_local_image(
            image_directory=image_directory,
            source=source,
            image=image,
            image_index=image_index,
            recovery_by_key=recovery_by_key,
            require_available=True,
        )
        assert resolved_image.image_sha256 is not None
        assert resolved_image.recovery_status is not None
        assert resolved_image.resolved_image_file is not None
        resolved.append(
            {
                "source_file": source.source_file,
                "source_sha256": source.source_sha256,
                "image_file": image["file"],
                "image_index": image_index,
                "image_sha256": resolved_image.image_sha256,
                "source_locator": (
                    "urn:xiaoro:product-detail-image:"
                    f"pid:{product_id}:"
                    f"source-sha256:{source.source_sha256}:"
                    "image-sha256:"
                    f"{resolved_image.image_sha256}"
                ),
                "source_url": resolved_image.source_url,
                "recovery_status": resolved_image.recovery_status,
                "resolved_image_file": (
                    resolved_image.resolved_image_file
                ),
                "image_region": raw_source.get("image_region"),
            }
        )
        keys.append(key)
    return resolved, keys


def _qualifiers(value: object) -> dict[str, object]:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ProductEvidenceBuildError(
            "evidence qualifiers must be an object"
        )
    return {
        "sample_size": value.get("sample_size"),
        "population": value.get("population"),
        "method": value.get("method"),
        "baseline": value.get("baseline"),
        "duration": value.get("duration"),
        "disclaimer": value.get("disclaimer"),
        "footnotes": value.get("footnotes", []),
    }


def _required_string(
    row: dict[str, object],
    key: str,
) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProductEvidenceBuildError(f"{key} must be nonempty text")
    return value


def _jsonl_bytes(rows: list[dict[str, object]]) -> bytes:
    return b"".join(
        (_canonical_json(_normalize_unordered_sequences(row)) + "\n").encode(
            "utf-8"
        )
        for row in rows
    )


def _normalize_unordered_sequences(value: object) -> object:
    if isinstance(value, dict):
        unordered_keys = {
            "allowed_uses",
            "capabilities",
            "forbidden_uses",
            "free_descriptors",
            "footnotes",
        }
        normalized: dict[str, object] = {}
        for key, item in value.items():
            normalized_item = _normalize_unordered_sequences(item)
            if key in unordered_keys and isinstance(normalized_item, list):
                normalized_item = sorted(normalized_item)
            normalized[key] = normalized_item
        return normalized
    if isinstance(value, (list, tuple)):
        return [
            _normalize_unordered_sequences(item)
            for item in value
        ]
    if isinstance(value, (set, frozenset)):
        return sorted(
            _normalize_unordered_sequences(item)
            for item in value
        )
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--image-root", required=True)
    parser.add_argument("--audit", action="append", required=True)
    parser.add_argument("--review", action="append", required=True)
    parser.add_argument("--recovery-manifest", action="append", default=[])
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--concept-audit")
    args = parser.parse_args()
    result = build_product_evidence(
        source_root=args.source_root,
        image_root=args.image_root,
        audit_paths=tuple(Path(item) for item in args.audit),
        review_paths=tuple(Path(item) for item in args.review),
        output_root=args.output_root,
        recovery_paths=tuple(
            Path(item) for item in args.recovery_manifest
        ),
        concept_audit_path=args.concept_audit,
    )
    print(
        json.dumps(
            {
                "manifest_path": str(result.manifest_path),
                "evidence_path": str(result.evidence_path),
                "audit_path": str(result.audit_path),
                "evidence_count": result.evidence_count,
                "product_count": result.product_count,
                "image_count": result.image_count,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ProductEvidenceBuildError",
    "ProductEvidenceBuildResult",
    "build_product_evidence",
]
