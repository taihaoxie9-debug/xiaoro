from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from hashlib import sha256
import json
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.guide.retrieval.selection_parent_concept_contracts import (
    SelectionConceptProjection,
    SelectionConceptReview,
)


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        protected_namespaces=(),
    )


class SelectionConceptManifest(_StrictFrozenModel):
    schema_version: Literal["guide-selection-concept-asset-v1"] = (
        "guide-selection-concept-asset-v1"
    )
    asset_id: Literal["guide-selection-concepts"] = (
        "guide-selection-concepts"
    )
    asset_version: Literal["v1"] = "v1"
    inventory_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    projections_file: str = Field(
        pattern=r"^selection_concepts_v1\.[0-9a-f]{64}\.jsonl$"
    )
    projections_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_count: int = Field(gt=0)
    projection_count: int = Field(gt=0)
    concept_count: int = Field(gt=0)
    decision_counts: dict[str, int]
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        if self.projections_file != (
            f"selection_concepts_v1.{self.projections_sha256}.jsonl"
        ):
            raise ValueError("projections file hash binding mismatch")
        expected = _manifest_hash(
            self.model_dump(
                mode="json",
                exclude={"manifest_sha256"},
            )
        )
        if self.manifest_sha256 != expected:
            raise ValueError("manifest self-hash mismatch")
        if sum(self.decision_counts.values()) != self.review_count:
            raise ValueError("decision counts mismatch review count")
        if self.decision_counts.get("map") != self.projection_count:
            raise ValueError(
                "map count mismatch projection count"
            )
        return self


class SelectionConceptAssets(_StrictFrozenModel):
    manifest: SelectionConceptManifest
    projections: tuple[SelectionConceptProjection, ...]


def publish_selection_concept_assets(
    *,
    reviews: Sequence[SelectionConceptReview],
    inventory_path: Path,
    review_path: Path,
    output_dir: Path,
) -> Path:
    normalized = _validate_reviews(reviews)
    projections = tuple(
        SelectionConceptProjection.from_review(review)
        for review in normalized
        if review.decision == "map"
    )
    projection_bytes = b"".join(
        _canonical_json(item.model_dump(mode="json")) + b"\n"
        for item in projections
    )
    projection_hash = sha256(projection_bytes).hexdigest()
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    projections_file = (
        f"selection_concepts_v1.{projection_hash}.jsonl"
    )
    (output / projections_file).write_bytes(projection_bytes)

    decision_counts = dict(
        sorted(Counter(item.decision for item in normalized).items())
    )
    payload = {
        "schema_version": "guide-selection-concept-asset-v1",
        "asset_id": "guide-selection-concepts",
        "asset_version": "v1",
        "inventory_sha256": _file_hash(inventory_path),
        "review_sha256": _file_hash(review_path),
        "projections_file": projections_file,
        "projections_sha256": projection_hash,
        "review_count": len(normalized),
        "projection_count": len(projections),
        "concept_count": len({
            item.concept_id for item in projections
        }),
        "decision_counts": decision_counts,
    }
    payload["manifest_sha256"] = _manifest_hash(payload)
    manifest = SelectionConceptManifest.model_validate(
        payload,
        strict=True,
    )
    manifest_path = output / "selection_concepts_v1_manifest.json"
    manifest_path.write_bytes(
        _canonical_json(manifest.model_dump(mode="json")) + b"\n"
    )
    return manifest_path


def load_selection_concept_assets(
    manifest_path: Path,
    *,
    expected_manifest_sha256: str,
    inventory_path: Path,
    review_path: Path,
) -> SelectionConceptAssets:
    manifest = SelectionConceptManifest.model_validate_json(
        Path(manifest_path).read_text(encoding="utf-8"),
        strict=True,
    )
    if manifest.manifest_sha256 != expected_manifest_sha256:
        raise ValueError(
            "selection concept runtime manifest lock mismatch"
        )
    if _file_hash(inventory_path) != manifest.inventory_sha256:
        raise ValueError("selection concept inventory SHA mismatch")
    if _file_hash(review_path) != manifest.review_sha256:
        raise ValueError("selection concept review SHA mismatch")

    projection_path = Path(manifest_path).parent / (
        manifest.projections_file
    )
    projection_bytes = projection_path.read_bytes()
    if sha256(projection_bytes).hexdigest() != (
        manifest.projections_sha256
    ):
        raise ValueError("selection concept projection JSONL SHA mismatch")
    projections = tuple(
        SelectionConceptProjection.model_validate_json(line, strict=True)
        for line in projection_bytes.decode("utf-8").splitlines()
        if line.strip()
    )
    if len(projections) != manifest.projection_count:
        raise ValueError("selection concept projection count mismatch")
    if len({item.candidate_id for item in projections}) != len(
        projections
    ):
        raise ValueError("duplicate selection concept projection")
    if len({item.concept_id for item in projections}) != (
        manifest.concept_count
    ):
        raise ValueError("selection concept concept count mismatch")

    reviews = tuple(
        SelectionConceptReview.model_validate_json(line, strict=True)
        for line in Path(review_path).read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    )
    normalized_reviews = _validate_reviews(reviews)
    expected_projections = tuple(
        SelectionConceptProjection.from_review(review)
        for review in normalized_reviews
        if review.decision == "map"
    )
    if projections != expected_projections:
        raise ValueError(
            "selection concept projections do not match reviews"
        )
    if len(normalized_reviews) != manifest.review_count:
        raise ValueError("selection concept review count mismatch")
    if dict(
        sorted(
            Counter(
                item.decision for item in normalized_reviews
            ).items()
        )
    ) != manifest.decision_counts:
        raise ValueError("selection concept decision counts mismatch")
    return SelectionConceptAssets(
        manifest=manifest,
        projections=projections,
    )


def _validate_reviews(
    reviews: Sequence[SelectionConceptReview],
) -> tuple[SelectionConceptReview, ...]:
    normalized = tuple(reviews)
    if not normalized:
        raise ValueError("selection concept reviews cannot be empty")
    if any(
        not isinstance(item, SelectionConceptReview)
        for item in normalized
    ):
        raise TypeError(
            "reviews must contain SelectionConceptReview"
        )
    expected = tuple(
        sorted(
            normalized,
            key=lambda item: (
                item.profile.value,
                item.field_key,
                item.normalized_value.casefold(),
            ),
        )
    )
    if normalized != expected:
        raise ValueError("selection concept reviews must be sorted")
    ids = tuple(item.candidate_id for item in normalized)
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate selection concept review")
    return normalized


def _manifest_hash(payload: object) -> str:
    return sha256(_canonical_json(payload)).hexdigest()


def _file_hash(path: Path) -> str:
    return sha256(Path(path).read_bytes()).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


__all__ = [
    "SelectionConceptAssets",
    "SelectionConceptManifest",
    "load_selection_concept_assets",
    "publish_selection_concept_assets",
]
