from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from app.guide.adapters.image.index_build import (
    compute_image_index_manifest_sha256,
)
from app.guide.adapters.image.index_source_preflight import (
    DEFAULT_CANONICAL_IMAGE_COUNT,
    ImageSourcePreflightError,
    preflight_image_sources,
)
from app.guide.retrieval.image_contracts import (
    ImageIndexManifest,
    ImageIndexRuntimeLock,
    ImageRetrievalRequest,
    ImageRetrievalResult,
)
from app.guide.retrieval.ports import ImageRetrievalPort


class ImageIndexHealth(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    healthy: bool
    issues: tuple[str, ...]
    manifest_sha256: str | None = None
    index_sha256: str | None = None


class ImageRetrievalUnavailableError(RuntimeError):
    def __init__(self, issues: tuple[str, ...]) -> None:
        self.code = "image_index_unhealthy"
        self.issues = issues
        super().__init__(
            f"{self.code}: image retrieval is unavailable "
            f"({','.join(issues)})"
        )


class ImageIndexHealthCheck:
    def __init__(
        self,
        *,
        manifest_path: str | Path,
        source_root: str | Path,
        artifact_root: str | Path,
        runtime_lock: ImageIndexRuntimeLock,
    ) -> None:
        self._manifest_path = Path(manifest_path)
        self._source_root = Path(source_root)
        self._artifact_root = Path(artifact_root)
        self._runtime_lock = runtime_lock

    def check(self) -> ImageIndexHealth:
        try:
            manifest = self._load_trusted_manifest()
        except (OSError, UnicodeDecodeError, ValidationError, ValueError):
            return ImageIndexHealth(
                healthy=False,
                issues=("manifest_integrity_drift",),
            )

        issues: list[str] = []
        lock = self._runtime_lock
        if manifest.manifest_sha256 != lock.manifest_sha256:
            issues.append("manifest_lock_drift")
        if manifest.model_name != lock.model_name:
            issues.append("model_name_drift")
        if manifest.weights_sha256 != lock.weights_sha256:
            issues.append("weights_sha_drift")
        if (
            manifest.preprocessing_version
            != lock.preprocessing_version
        ):
            issues.append("preprocessing_version_drift")
        if manifest.vector_dimension != lock.vector_dimension:
            issues.append("vector_dimension_drift")
        if manifest.index_sha256 != lock.index_sha256:
            issues.append("index_lock_drift")

        if not self._sources_match(manifest):
            issues.append("source_integrity_drift")
        if not self._vectors_match(manifest):
            issues.append("vector_integrity_drift")
        if not _file_matches(
            root=self._artifact_root,
            relative_path=manifest.index_path,
            expected_sha256=manifest.index_sha256,
        ):
            issues.append("index_integrity_drift")

        return ImageIndexHealth(
            healthy=not issues,
            issues=tuple(issues),
            manifest_sha256=manifest.manifest_sha256,
            index_sha256=manifest.index_sha256,
        )

    def result_matches_lock(
        self,
        result: ImageRetrievalResult,
    ) -> bool:
        lock = self._runtime_lock
        return (
            result.model_name,
            result.weights_sha256,
            result.preprocessing_version,
            result.vector_dimension,
            result.index_sha256,
        ) == (
            lock.model_name,
            lock.weights_sha256,
            lock.preprocessing_version,
            lock.vector_dimension,
            lock.index_sha256,
        )

    def _load_trusted_manifest(self) -> ImageIndexManifest:
        artifact_root = self._artifact_root.resolve(strict=True)
        manifest_path = self._manifest_path.resolve(strict=True)
        if not manifest_path.is_relative_to(artifact_root):
            raise ValueError("manifest escapes artifact root")
        manifest = ImageIndexManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        if (
            compute_image_index_manifest_sha256(manifest)
            != manifest.manifest_sha256
        ):
            raise ValueError("manifest SHA-256 mismatch")
        return manifest

    def _sources_match(self, manifest: ImageIndexManifest) -> bool:
        if len(manifest.entries) != DEFAULT_CANONICAL_IMAGE_COUNT:
            return False
        try:
            report = preflight_image_sources(
                manifest_path=(
                    self._source_root / manifest.source_manifest_path
                ),
                products_path=(
                    self._source_root / manifest.source_products_path
                ),
                source_root=self._source_root,
                expected_count=DEFAULT_CANONICAL_IMAGE_COUNT,
            )
        except (ImageSourcePreflightError, OSError, RuntimeError):
            return False

        if (
            report.source_manifest_path
            != manifest.source_manifest_path
            or report.source_manifest_sha256
            != manifest.source_manifest_sha256
            or report.source_products_path
            != manifest.source_products_path
            or report.source_products_sha256
            != manifest.source_products_sha256
        ):
            return False
        return all(
            (
                source.product_id,
                source.source_path,
                source.source_bytes,
                source.source_sha256,
            )
            == (
                entry.product_id,
                entry.source_path,
                entry.source_bytes,
                entry.source_sha256,
            )
            for source, entry in zip(
                report.sources,
                manifest.entries,
                strict=True,
            )
        )

    def _vectors_match(self, manifest: ImageIndexManifest) -> bool:
        return all(
            _file_matches(
                root=self._artifact_root,
                relative_path=entry.vector_path,
                expected_sha256=entry.vector_sha256,
            )
            for entry in manifest.entries
        )


class HealthGuardedImageRetrieval:
    def __init__(
        self,
        *,
        retrieval: ImageRetrievalPort,
        health_check: ImageIndexHealthCheck,
    ) -> None:
        self._retrieval = retrieval
        self._health_check = health_check

    def retrieve(
        self,
        request: ImageRetrievalRequest,
    ) -> ImageRetrievalResult:
        health = self._health_check.check()
        if not health.healthy:
            raise ImageRetrievalUnavailableError(health.issues)
        result = self._retrieval.retrieve(request)
        health = self._health_check.check()
        if not health.healthy:
            raise ImageRetrievalUnavailableError(health.issues)
        if not self._health_check.result_matches_lock(result):
            raise ImageRetrievalUnavailableError(
                ("retrieval_result_drift",)
            )
        return result


def _file_matches(
    *,
    root: Path,
    relative_path: str,
    expected_sha256: str,
) -> bool:
    try:
        resolved_root = root.resolve(strict=True)
        path = (resolved_root / relative_path).resolve(strict=True)
        if not path.is_relative_to(resolved_root) or not path.is_file():
            return False
        content = path.read_bytes()
    except (OSError, RuntimeError):
        return False
    return bool(content) and (
        hashlib.sha256(content).hexdigest() == expected_sha256
    )
