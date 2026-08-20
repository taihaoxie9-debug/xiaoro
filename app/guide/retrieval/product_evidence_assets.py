from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.guide.retrieval.category_fact_contracts import (
    category_field_registry,
)


_SCHEMA_VERSION = "product-evidence-v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_LOCATOR = re.compile(
    r"^urn:xiaoro:product-detail-image:"
    r"pid:[1-9][0-9]*:"
    r"source-sha256:[0-9a-f]{64}:"
    r"image-sha256:[0-9a-f]{64}$"
)

EvidenceStatus = Literal[
    "accepted",
    "ambiguous",
    "irrelevant",
    "expired",
    "cross_product",
    "duplicate",
    "blocked",
]
ManagementLabel = Literal[
    "merchant_claim",
    "consumer_self_report",
    "merchant_cited_test",
    "packaging_information",
    "faq",
    "usage",
    "safety_transcript",
    "brand_research",
    "product_specification",
    "unclassified",
]
EvidenceUse = Literal[
    "answer",
    "display",
    "compare",
    "weak_soft_rank",
    "soft_rank",
    "hard_filter",
    "safety_gate",
]
ForbiddenUse = Literal[
    "hard_filter",
    "safety_guarantee",
    "clinical_effectiveness",
    "cross_product_attribution",
]
SubjectScope = Literal[
    "exact_product",
    "exact_variant",
    "brand",
    "gift",
    "bundle",
    "other_product",
]
SelectionUse = Literal[
    "compare",
    "soft_rank",
    "hard_filter",
    "safety_gate",
]
SelectionSafetyRole = Literal[
    "ordinary",
    "merchant_positive_safety",
    "verified_warning",
]


class ProductEvidenceAssetIntegrityError(RuntimeError):
    pass


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class EvidenceRelation(_StrictFrozenModel):
    subject: str = Field(min_length=1, max_length=256)
    predicate: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]{1,63}$",
    )
    object: str = Field(min_length=1, max_length=512)


class EvidenceQualifiers(_StrictFrozenModel):
    sample_size: int | None = Field(default=None, gt=0)
    population: str | None = Field(default=None, min_length=1, max_length=256)
    method: str | None = Field(default=None, min_length=1, max_length=256)
    baseline: str | None = Field(default=None, min_length=1, max_length=256)
    duration: str | None = Field(default=None, min_length=1, max_length=128)
    disclaimer: str | None = Field(default=None, min_length=1, max_length=512)
    footnotes: tuple[str, ...] = Field(default_factory=tuple, max_length=32)

    @field_validator("footnotes", mode="before")
    @classmethod
    def freeze_footnotes(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_footnotes(self) -> Self:
        if (
            len(self.footnotes) != len(set(self.footnotes))
            or any(not value.strip() or len(value) > 512 for value in self.footnotes)
        ):
            raise ValueError("evidence footnotes must be unique nonempty text")
        return self


class EvidenceSource(_StrictFrozenModel):
    source_file: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^detail_[1-9][0-9]*_ocr\.json$",
    )
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    image_file: str = Field(min_length=1, max_length=512)
    image_index: int = Field(ge=0)
    image_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_locator: str = Field(min_length=1, max_length=512)
    source_url: str | None = Field(default=None, min_length=1, max_length=2048)
    recovery_status: Literal[
        "source_record",
        "existing_local",
        "recovered_exact",
        "recovered_from_html",
        "current_new_version",
    ]
    resolved_image_file: str = Field(min_length=1, max_length=512)
    image_region: tuple[int, int, int, int]

    @field_validator("image_region", mode="before")
    @classmethod
    def freeze_region(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        if _SOURCE_LOCATOR.fullmatch(self.source_locator) is None:
            raise ValueError("product evidence source locator is invalid")
        if (
            self.recovery_status == "current_new_version"
            and self.source_url is None
        ):
            raise ValueError(
                "current source version requires a public source URL"
            )
        x1, y1, x2, y2 = self.image_region
        if x1 < 0 or y1 < 0 or x2 <= x1 or y2 <= y1:
            raise ValueError("product evidence image region is invalid")
        return self


class SelectionProjection(_StrictFrozenModel):
    field_key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    normalized_value: str = Field(min_length=1, max_length=128)
    capabilities: frozenset[SelectionUse] = Field(min_length=1)
    rank_strength: Literal[1, 2] | None = None
    safety_role: SelectionSafetyRole = "ordinary"

    @field_validator("capabilities", mode="before")
    @classmethod
    def freeze_capabilities(cls, value: object) -> object:
        if isinstance(value, (list, tuple, set)):
            return frozenset(value)
        return value

    @model_validator(mode="after")
    def validate_projection(self) -> Self:
        if self.normalized_value != self.normalized_value.strip():
            raise ValueError("selection value must be trimmed")
        if "soft_rank" in self.capabilities:
            if self.rank_strength is None:
                raise ValueError("soft projection requires rank strength")
        elif self.rank_strength is not None:
            raise ValueError(
                "selection rank strength requires soft projection"
            )
        definitions = {
            definition.key
            for definition in category_field_registry().definitions
        }
        if self.field_key not in definitions:
            raise ValueError("unknown selection projection field")
        return self


class EvidenceSelectionReview(_StrictFrozenModel):
    decision: Literal[
        "projected",
        "answer_only",
        "comparison_only",
        "safety_gate",
    ]
    visual_confirmed: Literal[True]
    rationale: str = Field(min_length=1, max_length=1000)
    projections: tuple[SelectionProjection, ...] = Field(
        default_factory=tuple,
        max_length=128,
    )

    @field_validator("projections", mode="before")
    @classmethod
    def freeze_projections(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_review(self) -> Self:
        projection_keys = tuple(
            (
                item.field_key,
                item.normalized_value.casefold(),
            )
            for item in self.projections
        )
        if len(projection_keys) != len(set(projection_keys)):
            raise ValueError("selection review has duplicate projections")
        if self.decision in {"answer_only", "comparison_only"}:
            if self.projections:
                raise ValueError(
                    "nonprojected review forbids selection projections"
                )
        elif not self.projections:
            raise ValueError(
                "projected selection review requires projections"
            )
        if (
            self.decision == "safety_gate"
            and any(
                "safety_gate" not in item.capabilities
                for item in self.projections
            )
        ):
            raise ValueError(
                "safety-gate review requires safety projections"
            )
        return self


class ProductEvidenceBlock(_StrictFrozenModel):
    evidence_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    product_id: int = Field(gt=0)
    subject_scope: SubjectScope
    variant_scope: str | None = Field(default=None, min_length=1, max_length=160)
    management_label: ManagementLabel
    transcription_basis: Literal[
        "ocr_exact",
        "visual_transcription",
    ] = "ocr_exact"
    exact_text: str = Field(min_length=1, max_length=4000)
    plain_meaning: str = Field(min_length=1, max_length=1000)
    relations: tuple[EvidenceRelation, ...] = Field(
        default_factory=tuple,
        max_length=32,
    )
    qualifiers: EvidenceQualifiers
    free_descriptors: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=32,
    )
    review_status: EvidenceStatus
    allowed_uses: frozenset[EvidenceUse]
    forbidden_uses: frozenset[ForbiddenUse]
    review_rationale: str = Field(min_length=1, max_length=1000)
    selection_review: EvidenceSelectionReview | None = None
    source: EvidenceSource
    supporting_sources: tuple[EvidenceSource, ...] = Field(
        default_factory=tuple,
        max_length=16,
    )

    @field_validator(
        "relations",
        "free_descriptors",
        "supporting_sources",
        mode="before",
    )
    @classmethod
    def freeze_sequences(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @field_validator("allowed_uses", "forbidden_uses", mode="before")
    @classmethod
    def freeze_use_sets(cls, value: object) -> object:
        if isinstance(value, (list, tuple, set)):
            return frozenset(value)
        return value

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        if self.subject_scope == "exact_variant" and self.variant_scope is None:
            raise ValueError("exact variant evidence requires variant scope")
        if (
            len(self.free_descriptors) != len(set(self.free_descriptors))
            or any(
                not value.strip() or len(value) > 128
                for value in self.free_descriptors
            )
        ):
            raise ValueError(
                "free descriptors must be unique nonempty short text"
            )
        supporting_locators = [
            item.source_locator for item in self.supporting_sources
        ]
        if (
            len(supporting_locators) != len(set(supporting_locators))
            or self.source.source_locator in supporting_locators
        ):
            raise ValueError(
                "supporting evidence sources must be distinct"
            )
        if self.review_status == "accepted":
            if "answer" not in self.allowed_uses:
                raise ValueError("accepted evidence must be answerable")
            if self.selection_review is None:
                raise ValueError(
                    "accepted evidence requires selection use review"
                )
        elif self.allowed_uses:
            raise ValueError("nonaccepted evidence forbids allowed uses")
        elif self.selection_review is not None:
            raise ValueError(
                "nonaccepted evidence forbids selection use review"
            )
        if (
            "hard_filter" in self.allowed_uses
            and "hard_filter" in self.forbidden_uses
        ):
            raise ValueError("evidence use conflicts with forbidden use")
        if self.management_label == "safety_transcript":
            if "hard_filter" in self.allowed_uses:
                raise ValueError("safety transcript cannot hard filter")
            if "safety_guarantee" not in self.forbidden_uses:
                raise ValueError(
                    "safety transcript must forbid safety guarantee"
                )
        if self.management_label == "consumer_self_report":
            if "clinical_effectiveness" not in self.forbidden_uses:
                raise ValueError(
                    "consumer self-report must forbid clinical effectiveness"
                )
            if "hard_filter" not in self.forbidden_uses:
                raise ValueError(
                    "consumer self-report must forbid hard filter"
                )
        if (
            self.management_label in {"merchant_claim", "merchant_cited_test"}
            and "hard_filter" in self.allowed_uses
        ):
            raise ValueError("merchant evidence cannot hard filter")
        if self.selection_review is not None:
            for projection in self.selection_review.projections:
                if (
                    "compare" in projection.capabilities
                    and "compare" not in self.allowed_uses
                ):
                    raise ValueError(
                        "selection compare exceeds evidence use"
                    )
                if (
                    "soft_rank" in projection.capabilities
                    and not {
                        "soft_rank",
                        "weak_soft_rank",
                    }.intersection(self.allowed_uses)
                ):
                    raise ValueError(
                        "selection soft rank exceeds evidence use"
                    )
                if (
                    "hard_filter" in projection.capabilities
                    and "hard_filter" not in self.allowed_uses
                ):
                    raise ValueError(
                        "selection hard filter exceeds evidence use"
                    )
                if (
                    "safety_gate" in projection.capabilities
                    and "safety_gate" not in self.allowed_uses
                ):
                    raise ValueError(
                        "selection safety gate exceeds evidence use"
                    )
                if (
                    "weak_soft_rank" in self.allowed_uses
                    and projection.rank_strength == 2
                ):
                    raise ValueError(
                        "weak soft evidence cannot use strong rank"
                    )
                if (
                    self.management_label
                    in {
                        "merchant_claim",
                        "consumer_self_report",
                        "safety_transcript",
                    }
                    and projection.rank_strength == 2
                ):
                    raise ValueError(
                        "merchant or consumer evidence is weak rank only"
                    )
        expected_id = product_evidence_id(
            self.model_dump(mode="json", exclude={"evidence_id"})
        )
        if self.evidence_id != expected_id:
            raise ValueError("product evidence ID mismatch")
        return self


class ImageAuditRecord(_StrictFrozenModel):
    audit_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    product_id: int = Field(gt=0)
    source_file: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"^detail_[1-9][0-9]*_ocr\.json$",
    )
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    image_file: str = Field(min_length=1, max_length=512)
    image_index: int = Field(ge=0)
    image_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    local_image: str | None = Field(default=None, min_length=1, max_length=512)
    review_status: EvidenceStatus
    rationale: str = Field(min_length=1, max_length=1000)
    recovery_attempts: tuple[str, ...] = Field(
        default_factory=tuple,
        max_length=16,
    )
    evidence_ids: tuple[str, ...] = Field(default_factory=tuple)
    duplicate_of_image_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )

    @field_validator("recovery_attempts", "evidence_ids", mode="before")
    @classmethod
    def freeze_audit_sequences(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value

    @model_validator(mode="after")
    def validate_audit(self) -> Self:
        if len(self.recovery_attempts) != len(set(self.recovery_attempts)):
            raise ValueError("recovery attempts must be unique")
        if (
            len(self.evidence_ids) != len(set(self.evidence_ids))
            or any(_SHA256.fullmatch(value) is None for value in self.evidence_ids)
        ):
            raise ValueError("audit evidence IDs are invalid")
        if (
            self.review_status == "duplicate"
            and self.duplicate_of_image_sha256 is None
        ):
            raise ValueError("duplicate audit requires duplicate image SHA")
        if self.review_status == "blocked":
            if not self.recovery_attempts:
                raise ValueError("blocked audit requires recovery attempts")
            if self.evidence_ids:
                raise ValueError("blocked audit forbids evidence IDs")
        else:
            if self.image_sha256 is None or self.local_image is None:
                raise ValueError("available audit requires local image and SHA")
        if (
            self.review_status != "duplicate"
            and self.duplicate_of_image_sha256 is not None
        ):
            raise ValueError("nonduplicate audit forbids duplicate image SHA")
        if self.review_status == "accepted" and not self.evidence_ids:
            raise ValueError("accepted audit requires evidence IDs")
        if (
            self.review_status in {"irrelevant", "duplicate", "blocked"}
            and self.evidence_ids
        ):
            raise ValueError(
                "noncontent audit status forbids evidence IDs"
            )
        return self


class ProductEvidenceManifest(_StrictFrozenModel):
    schema_version: Literal["product-evidence-v1"] = _SCHEMA_VERSION
    asset_id: Literal[
        "guide-product-evidence-v1"
    ] = "guide-product-evidence-v1"
    asset_version: str = Field(min_length=1, max_length=255)
    evidence_file: str = Field(min_length=1, max_length=255)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    audit_file: str = Field(min_length=1, max_length=255)
    audit_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_count: int = Field(ge=0)
    product_count: int = Field(ge=0)
    image_count: int = Field(ge=0)
    status_counts: dict[str, int]
    allowed_use_counts: dict[str, int]
    selection_concept_audit_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        if (
            any(value < 0 for value in self.status_counts.values())
            or sum(self.status_counts.values()) != self.image_count
            or any(value < 0 for value in self.allowed_use_counts.values())
        ):
            raise ValueError("product evidence manifest counts are invalid")
        return self


class ProductEvidenceAssets(_StrictFrozenModel):
    manifest: ProductEvidenceManifest
    evidence: tuple[ProductEvidenceBlock, ...]
    audit: tuple[ImageAuditRecord, ...]

    @field_validator("evidence", "audit", mode="before")
    @classmethod
    def freeze_assets(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(value)
        return value


def product_evidence_id(payload: dict[str, object]) -> str:
    normalized = _normalize_sets(payload)
    if isinstance(normalized, dict):
        normalized.setdefault("supporting_sources", [])
        normalized.setdefault("transcription_basis", "ocr_exact")
    return hashlib.sha256(
        _canonical_json(normalized).encode("utf-8")
    ).hexdigest()


def load_product_evidence_assets(
    *,
    manifest_path: str | Path,
    evidence_path: str | Path,
    audit_path: str | Path,
    expected_manifest_sha256: str | None = None,
) -> ProductEvidenceAssets:
    manifest_file = Path(manifest_path)
    evidence_file = Path(evidence_path)
    audit_file = Path(audit_path)
    try:
        manifest_payload = json.loads(
            manifest_file.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductEvidenceAssetIntegrityError(
            "product evidence manifest is invalid"
        ) from exc
    if not isinstance(manifest_payload, dict):
        raise ProductEvidenceAssetIntegrityError(
            "product evidence manifest must be an object"
        )
    unsigned = {
        key: value
        for key, value in manifest_payload.items()
        if key != "manifest_sha256"
    }
    actual_manifest_sha = hashlib.sha256(
        _canonical_json(unsigned).encode("utf-8")
    ).hexdigest()
    if manifest_payload.get("manifest_sha256") != actual_manifest_sha:
        raise ProductEvidenceAssetIntegrityError(
            "product evidence manifest SHA mismatch"
        )
    if (
        expected_manifest_sha256 is not None
        and (
            _SHA256.fullmatch(expected_manifest_sha256) is None
            or expected_manifest_sha256 != actual_manifest_sha
        )
    ):
        raise ProductEvidenceAssetIntegrityError(
            "product evidence manifest lock mismatch"
        )
    try:
        manifest = ProductEvidenceManifest.model_validate(
            manifest_payload,
            strict=True,
        )
    except ValueError as exc:
        raise ProductEvidenceAssetIntegrityError(
            "product evidence manifest contract is invalid"
        ) from exc
    if (
        manifest.evidence_file != evidence_file.name
        or manifest.audit_file != audit_file.name
    ):
        raise ProductEvidenceAssetIntegrityError(
            "product evidence manifest file binding mismatch"
        )
    evidence_bytes = _read_bytes(
        evidence_file,
        "product evidence JSONL is unavailable",
    )
    audit_bytes = _read_bytes(
        audit_file,
        "product evidence audit JSONL is unavailable",
    )
    if hashlib.sha256(evidence_bytes).hexdigest() != manifest.evidence_sha256:
        raise ProductEvidenceAssetIntegrityError(
            "product evidence JSONL SHA mismatch"
        )
    if hashlib.sha256(audit_bytes).hexdigest() != manifest.audit_sha256:
        raise ProductEvidenceAssetIntegrityError(
            "product evidence audit JSONL SHA mismatch"
        )
    if evidence_file.name != (
        f"product_evidence_v1.{manifest.evidence_sha256}.jsonl"
    ):
        raise ProductEvidenceAssetIntegrityError(
            "product evidence JSONL is not content addressed"
        )
    if audit_file.name != f"image_audit_v1.{manifest.audit_sha256}.jsonl":
        raise ProductEvidenceAssetIntegrityError(
            "product evidence audit JSONL is not content addressed"
        )
    evidence = _parse_jsonl(
        evidence_bytes,
        ProductEvidenceBlock,
        "product evidence",
    )
    audit = _parse_jsonl(
        audit_bytes,
        ImageAuditRecord,
        "product evidence audit",
    )
    _validate_asset_inventory(manifest, evidence, audit)
    return ProductEvidenceAssets(
        manifest=manifest,
        evidence=tuple(evidence),
        audit=tuple(audit),
    )


def _validate_asset_inventory(
    manifest: ProductEvidenceManifest,
    evidence: list[ProductEvidenceBlock],
    audit: list[ImageAuditRecord],
) -> None:
    evidence_ids = [item.evidence_id for item in evidence]
    audit_keys = [
        (item.product_id, item.source_file, item.image_index)
        for item in audit
    ]
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
    referenced_ids = {
        evidence_id
        for item in audit
        for evidence_id in item.evidence_ids
    }
    if (
        len(evidence) != manifest.evidence_count
        or evidence_ids != sorted(evidence_ids)
        or len(evidence_ids) != len(set(evidence_ids))
        or len({item.product_id for item in evidence})
        != manifest.product_count
        or len(audit) != manifest.image_count
        or audit_keys != sorted(audit_keys)
        or len(audit_keys) != len(set(audit_keys))
        or status_counts != manifest.status_counts
        or allowed_use_counts != manifest.allowed_use_counts
        or referenced_ids != set(evidence_ids)
    ):
        raise ProductEvidenceAssetIntegrityError(
            "product evidence manifest counts or ordering mismatch"
        )


def _parse_jsonl(data: bytes, model, label: str):
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ProductEvidenceAssetIntegrityError(
            f"{label} JSONL is not UTF-8"
        ) from exc
    parsed = []
    for line_number, line in enumerate(lines, start=1):
        if not line:
            raise ProductEvidenceAssetIntegrityError(
                f"blank {label} JSONL line {line_number}"
            )
        try:
            parsed.append(model.model_validate_json(line, strict=True))
        except ValueError as exc:
            raise ProductEvidenceAssetIntegrityError(
                f"invalid {label} line {line_number}"
            ) from exc
    return parsed


def _read_bytes(path: Path, message: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ProductEvidenceAssetIntegrityError(message) from exc


def _normalize_sets(value: object) -> object:
    if isinstance(value, dict):
        normalized: dict[str, object] = {}
        unordered_keys = {
            "allowed_uses",
            "capabilities",
            "forbidden_uses",
            "free_descriptors",
            "footnotes",
        }
        for key, item in value.items():
            normalized_item = _normalize_sets(item)
            if key in unordered_keys and isinstance(normalized_item, list):
                normalized_item = sorted(normalized_item)
            normalized[key] = normalized_item
        return normalized
    if isinstance(value, (set, frozenset)):
        return sorted(_normalize_sets(item) for item in value)
    if isinstance(value, (list, tuple)):
        return [_normalize_sets(item) for item in value]
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


__all__ = [
    "EvidenceSelectionReview",
    "EvidenceQualifiers",
    "EvidenceRelation",
    "EvidenceSource",
    "ImageAuditRecord",
    "ProductEvidenceAssetIntegrityError",
    "ProductEvidenceAssets",
    "ProductEvidenceBlock",
    "ProductEvidenceManifest",
    "SelectionProjection",
    "SelectionSafetyRole",
    "SelectionUse",
    "SubjectScope",
    "load_product_evidence_assets",
    "product_evidence_id",
]
