from __future__ import annotations

from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from app.guide.adapters.image.index_build import ImageIndexBuildService
from app.guide.adapters.image.index_runtime import (
    ImageIndexHealthCheck,
    ImageRetrievalUnavailableError,
)
from app.guide.adapters.image.index_source_preflight import (
    preflight_image_sources,
)
from app.guide.adapters.image.local_numpy_index import (
    LocalNumpyImageIndex,
    OpenClipNumpyArtifactBuilder,
    controlled_reencode,
    verify_image_index_acceptance,
)
from app.guide.retrieval.image_contracts import (
    ApprovedImageModelLock,
    ImageIndexBuildInput,
    ImageIndexManifest,
    ImageIndexRuntimeLock,
    ImageIndexSource,
    ImageRetrievalCandidate,
    ImageRetrievalRequest,
    ImageRetrievalResult,
)


WEIGHTS_SHA = "a" * 64
MODEL_LOCK = ApprovedImageModelLock(
    approval_id="test-approval",
    model_name="test-model",
    weights_sha256=WEIGHTS_SHA,
    preprocessing_version="test-preprocess-v1",
    vector_dimension=4,
)


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class _FakeEncoder:
    def __init__(
        self,
        *,
        model_lock: ApprovedImageModelLock = MODEL_LOCK,
        invalid: str | None = None,
    ) -> None:
        self.model_lock = model_lock
        self.invalid = invalid

    def encode_paths(
        self,
        paths: tuple[Path, ...],
        *,
        batch_size: int,
    ) -> np.ndarray:
        assert batch_size > 0
        return self._vectors_for_ids(
            tuple(int(path.stem) for path in paths)
        )

    def encode_contents(
        self,
        contents: tuple[bytes, ...],
        *,
        batch_size: int,
    ) -> np.ndarray:
        assert batch_size > 0
        return self._vectors_for_ids(
            tuple(
                int(content.decode("ascii").rsplit("-", 1)[1])
                for content in contents
            )
        )

    def _vectors_for_ids(
        self,
        product_ids: tuple[int, ...],
    ) -> np.ndarray:
        vectors = []
        for product_id in product_ids:
            if product_id in (1, 2):
                vectors.append([1.0, 0.0, 0.0, 0.0])
            else:
                vectors.append([0.0, 1.0, 0.0, 0.0])
        result = np.asarray(vectors, dtype=np.float32)
        if self.invalid == "zero":
            result[0] = 0.0
        elif self.invalid == "nonfinite":
            result[0, 0] = np.nan
        elif self.invalid == "dimension":
            result = result[:, :3]
        return result

    def encode_bytes(self, content: bytes) -> np.ndarray:
        return np.asarray([1.0, 0.0, 0.0, 0.0], dtype=np.float32)


@dataclass(frozen=True)
class _BuiltFixture:
    source_root: Path
    output_dir: Path
    manifest: ImageIndexManifest
    runtime_lock: ImageIndexRuntimeLock
    encoder: _FakeEncoder


def _write_source_snapshot(
    tmp_path: Path,
    *,
    source_count: int = 103,
) -> tuple[Path, Path, Path]:
    source_root = (tmp_path / "source-root").resolve()
    canonical = source_root / "data" / "canonical"
    canonical.mkdir(parents=True)
    products_path = canonical / "seed_product_images_v1.jsonl"
    manifest_path = canonical / "seed_product_images_v1_manifest.json"
    rows = []
    for product_id in range(1, source_count + 1):
        relative_path = f"images/{product_id}.png"
        content = f"source-image-{product_id}".encode()
        image_path = source_root / relative_path
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(content)
        rows.append(
            {
                "product_id": product_id,
                "relative_path": relative_path,
                "bytes": len(content),
                "source_image_sha256": hashlib.sha256(content).hexdigest(),
                "media_type": "image/png",
            }
        )
    products_text = "".join(f"{_canonical_json(row)}\n" for row in rows)
    products_path.write_text(products_text, encoding="utf-8")
    source_images_sha256 = hashlib.sha256(
        "\n".join(
            f"{row['product_id']}\t{row['source_image_sha256']}"
            for row in rows
        ).encode("utf-8")
    ).hexdigest()
    manifest = {
        "schema_version": "seed-product-images-v1",
        "product_count": source_count,
        "products_file": products_path.name,
        "products_sha256": hashlib.sha256(
            products_text.encode("utf-8")
        ).hexdigest(),
        "source_images_sha256": source_images_sha256,
    }
    manifest["manifest_sha256"] = hashlib.sha256(
        _canonical_json(manifest).encode("utf-8")
    ).hexdigest()
    manifest_path.write_text(
        _canonical_json(manifest) + "\n",
        encoding="utf-8",
    )
    return manifest_path, products_path, source_root


def _build_fixture(
    tmp_path: Path,
    *,
    output_name: str = "published-index",
    encoder: _FakeEncoder | None = None,
) -> _BuiltFixture:
    manifest_path, products_path, source_root = _write_source_snapshot(
        tmp_path
    )
    actual_encoder = encoder or _FakeEncoder()
    output_dir = (tmp_path / output_name).resolve()
    result = ImageIndexBuildService(
        artifact_builder=OpenClipNumpyArtifactBuilder(
            source_root=source_root,
            encoder=actual_encoder,
            batch_size=16,
        )
    ).build(
        ImageIndexBuildInput(
            source_manifest_path=manifest_path,
            source_products_path=products_path,
            source_root=source_root,
            output_dir=output_dir,
            model=MODEL_LOCK,
        )
    )
    assert result.status == "built"
    manifest = ImageIndexManifest.model_validate_json(
        result.manifest_path.read_text(encoding="utf-8")
    )
    runtime_lock = ImageIndexRuntimeLock(
        manifest_sha256=manifest.manifest_sha256,
        model_name=manifest.model_name,
        weights_sha256=manifest.weights_sha256,
        preprocessing_version=manifest.preprocessing_version,
        vector_dimension=manifest.vector_dimension,
        index_sha256=manifest.index_sha256,
    )
    return _BuiltFixture(
        source_root=source_root,
        output_dir=output_dir,
        manifest=manifest,
        runtime_lock=runtime_lock,
        encoder=actual_encoder,
    )


def _request(max_results: int = 3) -> ImageRetrievalRequest:
    content = b"query"
    return ImageRetrievalRequest(
        image_id="query-image",
        content_sha256=hashlib.sha256(content).hexdigest(),
        content=content,
        max_results=max_results,
    )


def test_numpy_builder_writes_reproducible_l2_artifacts(
    tmp_path: Path,
) -> None:
    first = _build_fixture(tmp_path / "first")
    second = _build_fixture(tmp_path / "second")

    assert first.manifest.manifest_sha256 == second.manifest.manifest_sha256
    assert first.manifest.index_sha256 == second.manifest.index_sha256
    assert tuple(
        entry.vector_sha256 for entry in first.manifest.entries
    ) == tuple(entry.vector_sha256 for entry in second.manifest.entries)
    matrix = np.load(
        first.output_dir / first.manifest.index_path,
        allow_pickle=False,
    )
    first_vector = np.load(
        first.output_dir / first.manifest.entries[0].vector_path,
        allow_pickle=False,
    )
    assert matrix.shape == (103, 4)
    assert matrix.dtype == np.dtype("<f4")
    assert first_vector.shape == (4,)
    assert first_vector.dtype == np.dtype("<f4")
    assert np.allclose(np.linalg.norm(matrix, axis=1), 1.0, atol=1e-6)
    assert np.array_equal(matrix[0], first_vector)


@pytest.mark.parametrize("invalid", ["zero", "nonfinite", "dimension"])
def test_numpy_builder_rejects_invalid_encoder_output_atomically(
    tmp_path: Path,
    invalid: str,
) -> None:
    manifest_path, products_path, source_root = _write_source_snapshot(
        tmp_path
    )
    output_dir = tmp_path / "published-index"
    result = ImageIndexBuildService(
        artifact_builder=OpenClipNumpyArtifactBuilder(
            source_root=source_root,
            encoder=_FakeEncoder(invalid=invalid),
            batch_size=16,
        )
    ).build(
        ImageIndexBuildInput(
            source_manifest_path=manifest_path,
            source_products_path=products_path,
            source_root=source_root,
            output_dir=output_dir,
            model=MODEL_LOCK,
        )
    )

    assert result.status == "no_go"
    assert result.code == "index_build_failed"
    assert not output_dir.exists()


def test_numpy_builder_rejects_source_changed_after_preflight(
    tmp_path: Path,
) -> None:
    manifest_path, products_path, source_root = _write_source_snapshot(
        tmp_path
    )
    report = preflight_image_sources(
        manifest_path=manifest_path,
        products_path=products_path,
        source_root=source_root,
    )
    source_path = source_root / report.sources[0].source_path
    content = source_path.read_bytes()
    source_path.write_bytes(bytes([content[0] ^ 0xFF]) + content[1:])
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()

    with pytest.raises(ValueError, match="source image SHA-256"):
        OpenClipNumpyArtifactBuilder(
            source_root=source_root,
            encoder=_FakeEncoder(),
            batch_size=16,
        ).build(
            source_report=report,
            model=MODEL_LOCK,
            staging_dir=staging_dir,
        )


def test_local_numpy_index_uses_cosine_and_numeric_tie_break(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path)
    index = LocalNumpyImageIndex(
        manifest_path=fixture.output_dir / "manifest.json",
        source_root=fixture.source_root,
        artifact_root=fixture.output_dir,
        runtime_lock=fixture.runtime_lock,
        encoder=fixture.encoder,
    )

    result = index.retrieve(_request())

    assert [candidate.product_id for candidate in result.candidates] == [
        1,
        2,
        3,
    ]
    assert result.candidates[0].similarity == pytest.approx(1.0)
    assert result.candidates[1].similarity == pytest.approx(1.0)
    assert result.candidates[2].similarity == pytest.approx(0.0)
    assert result.index_sha256 == fixture.runtime_lock.index_sha256


@pytest.mark.parametrize("target", ["manifest", "vector", "index"])
def test_local_numpy_index_rejects_corrupt_artifacts_at_startup(
    tmp_path: Path,
    target: str,
) -> None:
    fixture = _build_fixture(tmp_path)
    if target == "manifest":
        path = fixture.output_dir / "manifest.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["model_name"] = "tampered-model"
        path.write_text(_canonical_json(payload) + "\n", encoding="utf-8")
    elif target == "vector":
        path = fixture.output_dir / fixture.manifest.entries[0].vector_path
        content = path.read_bytes()
        path.write_bytes(bytes([content[0] ^ 0xFF]) + content[1:])
    else:
        path = fixture.output_dir / fixture.manifest.index_path
        content = path.read_bytes()
        path.write_bytes(bytes([content[0] ^ 0xFF]) + content[1:])

    with pytest.raises(ImageRetrievalUnavailableError):
        LocalNumpyImageIndex(
            manifest_path=fixture.output_dir / "manifest.json",
            source_root=fixture.source_root,
            artifact_root=fixture.output_dir,
            runtime_lock=fixture.runtime_lock,
            encoder=fixture.encoder,
        )


def test_local_numpy_index_rejects_loaded_model_drift(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path)
    drifted_encoder = _FakeEncoder(
        model_lock=MODEL_LOCK.model_copy(
            update={"weights_sha256": "b" * 64}
        )
    )

    with pytest.raises(
        ImageRetrievalUnavailableError,
        match="model_runtime_drift",
    ):
        LocalNumpyImageIndex(
            manifest_path=fixture.output_dir / "manifest.json",
            source_root=fixture.source_root,
            artifact_root=fixture.output_dir,
            runtime_lock=fixture.runtime_lock,
            encoder=drifted_encoder,
        )


def test_local_numpy_index_rejects_artifacts_swapped_after_health_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _build_fixture(tmp_path)
    real_check = ImageIndexHealthCheck.check
    swapped = False

    def check_then_swap(health_check: ImageIndexHealthCheck):
        nonlocal swapped
        health = real_check(health_check)
        if health.healthy and not swapped:
            swapped = True
            matrix = np.load(
                fixture.output_dir / fixture.manifest.index_path,
                allow_pickle=False,
            )
            replacement = np.roll(matrix, 1, axis=0)
            with (
                fixture.output_dir / fixture.manifest.index_path
            ).open("wb") as stream:
                np.save(stream, replacement, allow_pickle=False)
            for row, entry in zip(
                replacement,
                fixture.manifest.entries,
                strict=True,
            ):
                with (
                    fixture.output_dir / entry.vector_path
                ).open("wb") as stream:
                    np.save(stream, row, allow_pickle=False)
        return health

    monkeypatch.setattr(ImageIndexHealthCheck, "check", check_then_swap)

    with pytest.raises(
        ImageRetrievalUnavailableError,
        match="numpy_payload_invalid",
    ):
        LocalNumpyImageIndex(
            manifest_path=fixture.output_dir / "manifest.json",
            source_root=fixture.source_root,
            artifact_root=fixture.output_dir,
            runtime_lock=fixture.runtime_lock,
            encoder=fixture.encoder,
        )


def test_controlled_reencode_is_deterministic_scaled_png() -> None:
    source = BytesIO()
    Image.new("RGB", (40, 24), (90, 80, 70)).save(
        source,
        format="PNG",
    )

    first = controlled_reencode(source.getvalue())
    second = controlled_reencode(source.getvalue())

    assert first == second
    assert first != source.getvalue()
    with Image.open(BytesIO(first)) as transformed:
        assert transformed.format == "PNG"
        assert transformed.size == (35, 21)
        assert transformed.mode == "RGB"


class _AcceptanceIndex:
    def __init__(self) -> None:
        self.runtime_lock = ImageIndexRuntimeLock(
            manifest_sha256="b" * 64,
            model_name=MODEL_LOCK.model_name,
            weights_sha256=MODEL_LOCK.weights_sha256,
            preprocessing_version=MODEL_LOCK.preprocessing_version,
            vector_dimension=MODEL_LOCK.vector_dimension,
            index_sha256="c" * 64,
        )

    def retrieve(
        self,
        request: ImageRetrievalRequest,
    ) -> ImageRetrievalResult:
        product_id = int(request.image_id.rsplit("-", 1)[1])
        return ImageRetrievalResult(
            candidates=(
                ImageRetrievalCandidate(
                    rank=1,
                    product_id=product_id,
                    similarity=1.0,
                ),
            ),
            model_name=self.runtime_lock.model_name,
            weights_sha256=self.runtime_lock.weights_sha256,
            preprocessing_version=self.runtime_lock.preprocessing_version,
            vector_dimension=self.runtime_lock.vector_dimension,
            index_sha256=self.runtime_lock.index_sha256,
        )


def test_acceptance_report_counts_original_transformed_and_stability(
    tmp_path: Path,
) -> None:
    sources = []
    for product_id in range(1, 4):
        relative_path = f"images/{product_id}.png"
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (40, 24), (product_id, 2, 3)).save(
            path,
            format="PNG",
        )
        content = path.read_bytes()
        sources.append(
            ImageIndexSource(
                product_id=product_id,
                source_path=relative_path,
                source_bytes=len(content),
                source_sha256=hashlib.sha256(content).hexdigest(),
                media_type="image/png",
            )
        )

    report = verify_image_index_acceptance(
        index=_AcceptanceIndex(),
        sources=tuple(sources),
        source_root=tmp_path,
    )

    assert report.source_count == 3
    assert report.original_top1_hits == 3
    assert report.transformed_top3_hits == 3
    assert report.ordering_stable
    assert report.index_sha256 == "c" * 64
