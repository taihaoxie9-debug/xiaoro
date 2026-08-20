from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.guide.adapters.catalog import CanonicalProductReader
from app.guide.retrieval.category_fact_contracts import (
    SourceClass,
    category_field_registry,
)
from app.guide.retrieval.category_profiles import (
    CategoryProfile,
    category_profile_for,
)
from app.guide.retrieval.merchant_claim_assets import (
    MerchantClaim,
    load_merchant_claim_assets,
    merchant_claim_id,
)
from tools.guide_data.selection_concept_audit import (
    load_selection_concept_audit,
    project_merchant_identity,
)


_SOURCE_NAME = re.compile(r"^detail_(?P<pid>[1-9][0-9]*)_ocr.json$")


class OcrMerchantClaimBuildError(RuntimeError):
    pass


class _ReviewCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    product_id: int = Field(gt=0)
    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    normalized_value: str = Field(min_length=1, max_length=128)
    display_claim: str = Field(min_length=1, max_length=160)
    claim_scope: Literal["ordinary", "safety_transcript"]
    source_file: str = Field(min_length=1, max_length=255)
    image_file: str = Field(min_length=1, max_length=512)
    image_index: int = Field(ge=0)
    rationale: str = Field(min_length=1, max_length=512)


@dataclass(frozen=True, slots=True)
class OcrMerchantClaimBuildResult:
    manifest_path: Path
    claims_path: Path
    claim_count: int
    product_count: int
    source_file_count: int


@dataclass(frozen=True, slots=True)
class _Source:
    pid: int
    sha256: str
    images: tuple[dict[str, object], ...]


def build_ocr_merchant_claims(
    *,
    source_root: str | Path,
    review_paths: tuple[Path, ...],
    output_root: str | Path,
    product_profiles: dict[int, CategoryProfile],
    concept_audit_path: str | Path | None = None,
) -> OcrMerchantClaimBuildResult:
    source_directory = Path(source_root)
    destination = Path(output_root)
    if not source_directory.is_dir():
        raise OcrMerchantClaimBuildError("OCR source root is unavailable")
    sources = _load_sources(source_directory, product_profiles)
    concept_audit = load_selection_concept_audit(concept_audit_path)
    review_hashes: set[str] = set()
    if concept_audit is not None:
        review_hashes.add(concept_audit.sha256)
    candidates: list[tuple[_ReviewCandidate, str]] = []
    for review_path in sorted(review_paths, key=lambda item: str(item)):
        try:
            review_bytes = Path(review_path).read_bytes()
        except OSError as exc:
            raise OcrMerchantClaimBuildError(
                "review candidate file is unavailable"
            ) from exc
        review_sha = hashlib.sha256(review_bytes).hexdigest()
        review_hashes.add(review_sha)
        for line_number, line in enumerate(
            review_bytes.decode("utf-8").splitlines(),
            start=1,
        ):
            if not line:
                continue
            try:
                candidate = _ReviewCandidate.model_validate_json(
                    line,
                    strict=True,
                )
            except ValueError as exc:
                raise OcrMerchantClaimBuildError(
                    f"invalid review candidate line {line_number}"
                ) from exc
            candidates.append((candidate, review_sha))

    registry = category_field_registry()
    definitions = {item.key: item for item in registry.definitions}
    claims_by_semantic_key: dict[
        tuple[int, str, str, str, str], MerchantClaim
    ] = {}
    for candidate, review_sha in candidates:
        projected_identity = project_merchant_identity(
            audit=concept_audit,
            product_id=candidate.product_id,
            field_key=candidate.field_key,
            value=candidate.normalized_value,
        )
        if projected_identity is None:
            continue
        candidate = candidate.model_copy(
            update={
                "field_key": projected_identity[0],
                "normalized_value": projected_identity[1],
            },
            deep=True,
        )
        source = sources.get(candidate.source_file)
        if source is None or source.pid != candidate.product_id:
            raise OcrMerchantClaimBuildError(
                "review candidate source binding is invalid"
            )
        profile = product_profiles.get(candidate.product_id)
        if profile is None:
            raise OcrMerchantClaimBuildError("unknown canonical product")
        if candidate.image_index >= len(source.images):
            raise OcrMerchantClaimBuildError(
                "review candidate image index is invalid"
            )
        image = source.images[candidate.image_index]
        if image.get("file") != candidate.image_file:
            raise OcrMerchantClaimBuildError(
                "review candidate image file is invalid"
            )
        ocr_text = image.get("ocr_text")
        if (
            not isinstance(ocr_text, str)
            or candidate.display_claim not in ocr_text
        ):
            raise OcrMerchantClaimBuildError(
                "review claim is not an exact OCR substring"
            )
        definition = None
        if candidate.claim_scope == "ordinary":
            definition = definitions.get(candidate.field_key)
            if definition is None or profile not in definition.profiles:
                raise OcrMerchantClaimBuildError(
                    "review claim field is not applicable to category"
                )
        elif candidate.field_key != "safety_claim":
            raise OcrMerchantClaimBuildError(
                "safety transcript requires safety_claim field"
            )

        record_sha = hashlib.sha256(
            _canonical_json(image).encode("utf-8")
        ).hexdigest()
        locator = (
            "urn:xiaoro:merchant-description-ocr:"
            f"pid:{candidate.product_id}:"
            f"source-sha256:{source.sha256}:"
            f"record-sha256:{record_sha}"
        )
        if candidate.claim_scope == "ordinary":
            assert definition is not None
            policy = next(
                (
                    item
                    for item in definition.source_policies
                    if item.source_class
                    is SourceClass.MERCHANT_DESCRIPTION_OCR
                ),
                None,
            )
            if policy is None or "display" not in policy.capabilities:
                raise OcrMerchantClaimBuildError(
                    "review claim field does not authorize OCR display"
                )
            capabilities = sorted(policy.capabilities - {"hard_filter"})
        else:
            capabilities = ["display", "evidence"]
        payload: dict[str, object] = {
            "product_id": candidate.product_id,
            "category_profile": profile.value,
            "field_key": candidate.field_key,
            "normalized_value": candidate.normalized_value.strip(),
            "display_claim": candidate.display_claim.strip(),
            "claim_scope": candidate.claim_scope,
            "source_class": SourceClass.MERCHANT_DESCRIPTION_OCR.value,
            "source_sha256": source.sha256,
            "record_sha256": record_sha,
            "source_locator": locator,
            "review_source_sha256": review_sha,
            "review_rationale": candidate.rationale.strip(),
            "capabilities": capabilities,
        }
        claim = MerchantClaim.model_validate(
            {"claim_id": merchant_claim_id(payload), **payload},
            strict=True,
        )
        key = (
            claim.product_id,
            claim.field_key,
            claim.normalized_value,
            claim.display_claim,
            claim.claim_scope,
        )
        previous = claims_by_semantic_key.get(key)
        if previous is None or claim.claim_id < previous.claim_id:
            claims_by_semantic_key[key] = claim

    claims = sorted(
        claims_by_semantic_key.values(),
        key=lambda item: item.claim_id,
    )
    claims_bytes = b"".join(
        (
            _canonical_json(_claim_payload(claim)) + "\n"
        ).encode("utf-8")
        for claim in claims
    )
    claims_sha = hashlib.sha256(claims_bytes).hexdigest()
    claims_name = f"merchant_claims_v1.{claims_sha}.jsonl"
    source_hashes = sorted(source.sha256 for source in sources.values())
    unsigned_manifest: dict[str, object] = {
        "schema_version": "merchant-ocr-claims-v1",
        "asset_id": "guide-merchant-ocr-claims-v1",
        "asset_version": f"merchant-ocr-claims-v1:sha256:{claims_sha}",
        "claims_file": claims_name,
        "claims_sha256": claims_sha,
        "claim_count": len(claims),
        "product_count": len({claim.product_id for claim in claims}),
        "source_file_count": len(source_hashes),
        "source_file_sha256s": source_hashes,
        "review_file_count": len(review_hashes),
        "review_file_sha256s": sorted(review_hashes),
    }
    manifest_payload = {
        **unsigned_manifest,
        "manifest_sha256": hashlib.sha256(
            _canonical_json(unsigned_manifest).encode("utf-8")
        ).hexdigest(),
    }
    destination.mkdir(parents=True, exist_ok=True)
    claims_path = destination / claims_name
    manifest_path = destination / "merchant_claims_v1_manifest.json"
    _atomic_write(claims_path, claims_bytes)
    _atomic_write(
        manifest_path,
        _canonical_json(manifest_payload).encode("utf-8"),
    )
    load_merchant_claim_assets(
        manifest_path=manifest_path,
        claims_path=claims_path,
    )
    return OcrMerchantClaimBuildResult(
        manifest_path=manifest_path,
        claims_path=claims_path,
        claim_count=len(claims),
        product_count=len({claim.product_id for claim in claims}),
        source_file_count=len(source_hashes),
    )


def _load_sources(
    source_root: Path,
    product_profiles: dict[int, CategoryProfile],
) -> dict[str, _Source]:
    sources: dict[str, _Source] = {}
    paths = sorted(source_root.glob("detail_*_ocr.json"))
    if not paths:
        raise OcrMerchantClaimBuildError("OCR source inventory is empty")
    for path in paths:
        match = _SOURCE_NAME.fullmatch(path.name)
        if match is None:
            continue
        pid = int(match.group("pid"))
        if pid not in product_profiles:
            raise OcrMerchantClaimBuildError("unknown canonical product")
        try:
            raw = path.read_bytes()
            payload = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OcrMerchantClaimBuildError("OCR source is invalid") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("pid") != pid
            or not isinstance(payload.get("images"), list)
        ):
            raise OcrMerchantClaimBuildError(
                "OCR source product binding is invalid"
            )
        images: list[dict[str, object]] = []
        for image in payload["images"]:
            if (
                not isinstance(image, dict)
                or not isinstance(image.get("file"), str)
                or not isinstance(image.get("ocr_text"), str)
            ):
                raise OcrMerchantClaimBuildError(
                    "OCR image record is invalid"
                )
            images.append(image)
        sources[path.name] = _Source(
            pid=pid,
            sha256=hashlib.sha256(raw).hexdigest(),
            images=tuple(images),
        )
    return sources


def canonical_product_profiles(
    reader: CanonicalProductReader,
) -> dict[int, CategoryProfile]:
    profiles: dict[int, CategoryProfile] = {}
    for product_id in reader.product_ids:
        product = reader.get(product_id)
        field = product.fields.get("category")
        if (
            field is None
            or field.resolved_state != "known"
            or not isinstance(field.value, str)
        ):
            continue
        profiles[product_id] = category_profile_for(field.value)
    return profiles


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


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _claim_payload(claim: MerchantClaim) -> dict[str, object]:
    payload = claim.model_dump(mode="json")
    payload["capabilities"] = sorted(claim.capabilities)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--review", action="append", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--concept-audit")
    parser.add_argument("--canonical-manifest", required=True)
    parser.add_argument("--canonical-products", required=True)
    args = parser.parse_args()
    reader = CanonicalProductReader.from_files(
        manifest_path=args.canonical_manifest,
        products_path=args.canonical_products,
    )
    result = build_ocr_merchant_claims(
        source_root=args.source_root,
        review_paths=tuple(Path(value) for value in args.review),
        output_root=args.output_root,
        product_profiles=canonical_product_profiles(reader),
        concept_audit_path=args.concept_audit,
    )
    print(
        _canonical_json(
            {
                "claim_count": result.claim_count,
                "product_count": result.product_count,
                "source_file_count": result.source_file_count,
                "manifest_path": str(result.manifest_path),
                "claims_path": str(result.claims_path),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "OcrMerchantClaimBuildError",
    "OcrMerchantClaimBuildResult",
    "build_ocr_merchant_claims",
    "canonical_product_profiles",
]
