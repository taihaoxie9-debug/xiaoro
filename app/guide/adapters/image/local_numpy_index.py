from __future__ import annotations

from collections.abc import Sequence
import hashlib
from io import BytesIO
import os
from pathlib import Path
from typing import Protocol

import numpy as np
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

from app.guide.adapters.image.index_build import (
    compute_image_index_manifest_sha256,
)
from app.guide.adapters.image.index_runtime import (
    ImageIndexHealthCheck,
    ImageRetrievalUnavailableError,
)
from app.guide.retrieval.image_contracts import (
    ApprovedImageModelLock,
    ImageIndexEntry,
    ImageIndexManifest,
    ImageIndexRuntimeLock,
    ImageIndexSource,
    ImageRetrievalCandidate,
    ImageRetrievalRequest,
    ImageRetrievalResult,
    ImageSourcePreflightReport,
    Sha256,
)


INDEX_FILE_NAME = "index.npy"
VECTOR_DIRECTORY = "vectors"
VECTOR_NORM_TOLERANCE = 1e-5


class ImageVectorEncoderPort(Protocol):
    @property
    def model_lock(self) -> ApprovedImageModelLock: ...

    def encode_paths(
        self,
        paths: Sequence[Path],
        *,
        batch_size: int,
    ) -> np.ndarray: ...

    def encode_contents(
        self,
        contents: Sequence[bytes],
        *,
        batch_size: int,
    ) -> np.ndarray: ...

    def encode_bytes(self, content: bytes) -> np.ndarray: ...


class OpenClipNumpyArtifactBuilder:
    def __init__(
        self,
        *,
        source_root: str | Path,
        encoder: ImageVectorEncoderPort,
        batch_size: int = 16,
    ) -> None:
        root = Path(source_root)
        if not root.is_absolute():
            raise ValueError("source_root must be absolute")
        try:
            root = root.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError("source_root is unavailable") from exc
        if not root.is_dir():
            raise ValueError("source_root must be a directory")
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self._source_root = root
        self._encoder = encoder
        self._batch_size = batch_size

    def build(
        self,
        *,
        source_report: ImageSourcePreflightReport,
        model: ApprovedImageModelLock,
        staging_dir: Path,
    ) -> ImageIndexManifest:
        if model != self._encoder.model_lock:
            raise ValueError("encoder model lock mismatch")
        source_contents = tuple(
            self._read_source(source) for source in source_report.sources
        )
        vectors = self._encoder.encode_contents(
            source_contents,
            batch_size=self._batch_size,
        )
        vectors = _validate_vector_matrix(
            vectors,
            row_count=len(source_report.sources),
            dimension=model.vector_dimension,
        )

        entries: list[ImageIndexEntry] = []
        for source, vector in zip(
            source_report.sources,
            vectors,
            strict=True,
        ):
            vector_path = (
                Path(VECTOR_DIRECTORY) / f"{source.product_id}.npy"
            )
            absolute_vector_path = staging_dir / vector_path
            absolute_vector_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            _write_npy(absolute_vector_path, vector)
            entries.append(
                ImageIndexEntry(
                    product_id=source.product_id,
                    source_path=source.source_path,
                    source_bytes=source.source_bytes,
                    source_sha256=source.source_sha256,
                    vector_path=vector_path.as_posix(),
                    vector_sha256=_file_sha256(absolute_vector_path),
                )
            )

        index_path = staging_dir / INDEX_FILE_NAME
        _write_npy(index_path, vectors)
        manifest = ImageIndexManifest(
            source_manifest_path=source_report.source_manifest_path,
            source_manifest_sha256=source_report.source_manifest_sha256,
            source_products_path=source_report.source_products_path,
            source_products_sha256=source_report.source_products_sha256,
            model_name=model.model_name,
            weights_sha256=model.weights_sha256,
            preprocessing_version=model.preprocessing_version,
            vector_dimension=model.vector_dimension,
            entries=tuple(entries),
            index_path=INDEX_FILE_NAME,
            index_sha256=_file_sha256(index_path),
            manifest_sha256="0" * 64,
        )
        return manifest.model_copy(
            update={
                "manifest_sha256": (
                    compute_image_index_manifest_sha256(manifest)
                )
            }
        )

    def _read_source(self, source: ImageIndexSource) -> bytes:
        try:
            path = (
                self._source_root / source.source_path
            ).resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError("source image is unavailable") from exc
        if (
            not path.is_relative_to(self._source_root)
            or not path.is_file()
        ):
            raise ValueError("source image escapes source root")
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise ValueError("source image is unavailable") from exc
        if len(content) != source.source_bytes:
            raise ValueError("source image byte size mismatch")
        if hashlib.sha256(content).hexdigest() != source.source_sha256:
            raise ValueError("source image SHA-256 mismatch")
        return content


class LocalNumpyImageIndex:
    def __init__(
        self,
        *,
        manifest_path: str | Path,
        source_root: str | Path,
        artifact_root: str | Path,
        runtime_lock: ImageIndexRuntimeLock,
        encoder: ImageVectorEncoderPort,
    ) -> None:
        health_check = ImageIndexHealthCheck(
            manifest_path=manifest_path,
            source_root=source_root,
            artifact_root=artifact_root,
            runtime_lock=runtime_lock,
        )
        health = health_check.check()
        if not health.healthy:
            raise ImageRetrievalUnavailableError(health.issues)
        if _model_identity(encoder.model_lock) != _runtime_identity(
            runtime_lock
        ):
            raise ImageRetrievalUnavailableError(
                ("model_runtime_drift",)
            )

        try:
            root = Path(artifact_root).resolve(strict=True)
            resolved_manifest_path = Path(manifest_path).resolve(
                strict=True
            )
            if not resolved_manifest_path.is_relative_to(root):
                raise ValueError("manifest escapes artifact root")
            manifest_bytes = resolved_manifest_path.read_bytes()
            manifest = ImageIndexManifest.model_validate_json(
                manifest_bytes
            )
            if (
                compute_image_index_manifest_sha256(manifest)
                != manifest.manifest_sha256
                or manifest.manifest_sha256
                != runtime_lock.manifest_sha256
            ):
                raise ValueError("manifest payload mismatch")
            matrix = _load_verified_npy(
                root=root,
                relative_path=manifest.index_path,
                expected_sha256=manifest.index_sha256,
            )
            matrix = _validate_vector_matrix(
                matrix,
                row_count=len(manifest.entries),
                dimension=manifest.vector_dimension,
            )
            for row, entry in zip(
                matrix,
                manifest.entries,
                strict=True,
            ):
                vector = _load_verified_npy(
                    root=root,
                    relative_path=entry.vector_path,
                    expected_sha256=entry.vector_sha256,
                )
                if (
                    vector.shape != (manifest.vector_dimension,)
                    or vector.dtype != np.dtype("<f4")
                    or not np.array_equal(vector, row)
                ):
                    raise ValueError("vector payload mismatch")
        except (OSError, ValueError) as exc:
            raise ImageRetrievalUnavailableError(
                ("numpy_payload_invalid",)
            ) from exc

        self._manifest = manifest
        self._matrix = matrix
        self._product_ids = np.asarray(
            [entry.product_id for entry in manifest.entries],
            dtype=np.int64,
        )
        self._runtime_lock = runtime_lock
        self._encoder = encoder

    @property
    def runtime_lock(self) -> ImageIndexRuntimeLock:
        return self._runtime_lock

    def retrieve(
        self,
        request: ImageRetrievalRequest,
    ) -> ImageRetrievalResult:
        query = np.asarray(
            self._encoder.encode_bytes(request.content),
            dtype=np.dtype("<f4"),
        )
        if (
            query.shape != (self._manifest.vector_dimension,)
            or not np.isfinite(query).all()
        ):
            raise ImageRetrievalUnavailableError(
                ("query_vector_invalid",)
            )
        norm = float(np.linalg.norm(query))
        if (
            norm <= 0.0
            or not np.isclose(
                norm,
                1.0,
                atol=VECTOR_NORM_TOLERANCE,
                rtol=0.0,
            )
        ):
            raise ImageRetrievalUnavailableError(
                ("query_vector_invalid",)
            )
        query = query / np.float32(norm)
        similarities = np.clip(
            self._matrix @ query,
            -1.0,
            1.0,
        )
        order = np.lexsort((self._product_ids, -similarities))
        selected = order[: request.max_results]
        candidates = tuple(
            ImageRetrievalCandidate(
                rank=rank,
                product_id=int(self._product_ids[index]),
                similarity=float(similarities[index]),
            )
            for rank, index in enumerate(selected, start=1)
        )
        if not candidates:
            raise ImageRetrievalUnavailableError(
                ("image_index_empty",)
            )
        return ImageRetrievalResult(
            candidates=candidates,
            model_name=self._runtime_lock.model_name,
            weights_sha256=self._runtime_lock.weights_sha256,
            preprocessing_version=(
                self._runtime_lock.preprocessing_version
            ),
            vector_dimension=self._runtime_lock.vector_dimension,
            index_sha256=self._runtime_lock.index_sha256,
        )


class ImageIndexAcceptanceReport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    source_count: int = Field(gt=0)
    original_top1_hits: int = Field(ge=0)
    transformed_top3_hits: int = Field(ge=0)
    original_top1_rate: float = Field(ge=0.0, le=1.0)
    transformed_top3_rate: float = Field(ge=0.0, le=1.0)
    ordering_stable: bool
    index_sha256: Sha256


def controlled_reencode(content: bytes) -> bytes:
    try:
        with Image.open(BytesIO(content)) as image:
            image.load()
            image = image.convert("RGB")
            size = (
                max(1, round(image.width * 0.875)),
                max(1, round(image.height * 0.875)),
            )
            transformed = image.resize(
                size,
                resample=Image.Resampling.BICUBIC,
            )
            output = BytesIO()
            transformed.save(
                output,
                format="PNG",
                optimize=False,
                compress_level=9,
            )
            return output.getvalue()
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError("controlled image reencode failed") from exc


def verify_image_index_acceptance(
    *,
    index: LocalNumpyImageIndex,
    sources: tuple[ImageIndexSource, ...],
    source_root: str | Path,
) -> ImageIndexAcceptanceReport:
    if not sources:
        raise ValueError("acceptance sources must not be empty")
    root = Path(source_root).resolve(strict=True)
    original_hits = 0
    transformed_hits = 0
    ordering_stable = True
    observed_index_sha: str | None = None
    for source in sources:
        path = (root / source.source_path).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("acceptance source escapes source root")
        content = path.read_bytes()
        if (
            len(content) != source.source_bytes
            or hashlib.sha256(content).hexdigest()
            != source.source_sha256
        ):
            raise ValueError("acceptance source integrity drift")

        original = _retrieve_acceptance(
            index=index,
            image_id=f"acceptance-source-{source.product_id}",
            content=content,
        )
        original_repeat = _retrieve_acceptance(
            index=index,
            image_id=f"acceptance-source-{source.product_id}",
            content=content,
        )
        transformed_content = controlled_reencode(content)
        transformed = _retrieve_acceptance(
            index=index,
            image_id=f"acceptance-transformed-{source.product_id}",
            content=transformed_content,
        )
        transformed_repeat = _retrieve_acceptance(
            index=index,
            image_id=f"acceptance-transformed-{source.product_id}",
            content=transformed_content,
        )
        if original.candidates[0].product_id == source.product_id:
            original_hits += 1
        if source.product_id in {
            candidate.product_id for candidate in transformed.candidates
        }:
            transformed_hits += 1
        ordering_stable = ordering_stable and (
            original.candidates == original_repeat.candidates
            and transformed.candidates == transformed_repeat.candidates
        )
        if observed_index_sha is None:
            observed_index_sha = original.index_sha256
        elif observed_index_sha != original.index_sha256:
            raise ValueError("acceptance index SHA drift")

    count = len(sources)
    return ImageIndexAcceptanceReport(
        source_count=count,
        original_top1_hits=original_hits,
        transformed_top3_hits=transformed_hits,
        original_top1_rate=original_hits / count,
        transformed_top3_rate=transformed_hits / count,
        ordering_stable=ordering_stable,
        index_sha256=observed_index_sha,
    )


def _retrieve_acceptance(
    *,
    index: LocalNumpyImageIndex,
    image_id: str,
    content: bytes,
) -> ImageRetrievalResult:
    return index.retrieve(
        ImageRetrievalRequest(
            image_id=image_id,
            content_sha256=hashlib.sha256(content).hexdigest(),
            content=content,
            max_results=3,
        )
    )


def _model_identity(
    model: ApprovedImageModelLock,
) -> tuple[str, str, str, int]:
    return (
        model.model_name,
        model.weights_sha256,
        model.preprocessing_version,
        model.vector_dimension,
    )


def _runtime_identity(
    runtime: ImageIndexRuntimeLock,
) -> tuple[str, str, str, int]:
    return (
        runtime.model_name,
        runtime.weights_sha256,
        runtime.preprocessing_version,
        runtime.vector_dimension,
    )


def _validate_vector_matrix(
    vectors: np.ndarray,
    *,
    row_count: int,
    dimension: int,
) -> np.ndarray:
    if not isinstance(vectors, np.ndarray):
        raise ValueError("encoder output must be a numpy array")
    if vectors.shape != (row_count, dimension):
        raise ValueError("encoder output shape mismatch")
    if vectors.dtype != np.dtype("<f4"):
        raise ValueError("encoder output must be little-endian float32")
    if not np.isfinite(vectors).all():
        raise ValueError("encoder output contains non-finite values")
    norms = np.linalg.norm(vectors, axis=1)
    if not np.allclose(
        norms,
        1.0,
        atol=VECTOR_NORM_TOLERANCE,
        rtol=0.0,
    ):
        raise ValueError("encoder output must be L2 normalized")
    return np.ascontiguousarray(vectors, dtype=np.dtype("<f4"))


def _write_npy(path: Path, array: np.ndarray) -> None:
    with path.open("wb") as stream:
        np.save(stream, array, allow_pickle=False)
        stream.flush()
        os.fsync(stream.fileno())


def _load_verified_npy(
    *,
    root: Path,
    relative_path: str,
    expected_sha256: str,
) -> np.ndarray:
    try:
        path = (root / relative_path).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("numpy artifact is unavailable") from exc
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("numpy artifact escapes artifact root")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise ValueError("numpy artifact SHA-256 mismatch")
    return np.load(BytesIO(content), allow_pickle=False)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
