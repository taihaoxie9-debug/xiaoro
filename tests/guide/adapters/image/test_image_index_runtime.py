from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.guide.adapters.image.index_build import (
    compute_image_index_manifest_sha256,
)
from app.guide.adapters.image.index_runtime import (
    HealthGuardedImageRetrieval,
    ImageIndexHealthCheck,
    ImageRetrievalUnavailableError,
)
from app.guide.retrieval.image_contracts import (
    ImageIndexEntry,
    ImageIndexManifest,
    ImageIndexRuntimeLock,
    ImageRetrievalCandidate,
    ImageRetrievalRequest,
    ImageRetrievalResult,
)

WEIGHTS_SHA = "a" * 64
CANONICAL_SOURCE_COUNT = 103


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


@dataclass(frozen=True)
class _RuntimeFixture:
    manifest_path: Path
    source_root: Path
    artifact_root: Path
    runtime_lock: ImageIndexRuntimeLock
    source_image_path: Path
    vector_path: Path
    index_path: Path


def _write_runtime_fixture(
    tmp_path: Path,
    *,
    source_count: int = CANONICAL_SOURCE_COUNT,
) -> _RuntimeFixture:
    source_root = (tmp_path / "source-root").resolve()
    canonical = source_root / "data" / "canonical"
    canonical.mkdir(parents=True)
    source_manifest_path = canonical / "seed_product_images_v1_manifest.json"
    source_products_path = canonical / "seed_product_images_v1.jsonl"

    rows: list[dict[str, object]] = []
    for product_id in range(1, source_count + 1):
        relative_path = f"app/static/images/products/{product_id}.png"
        content = f"source-image-{product_id}".encode()
        source_image_path = source_root / relative_path
        source_image_path.parent.mkdir(parents=True, exist_ok=True)
        source_image_path.write_bytes(content)
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
    source_products_path.write_text(products_text, encoding="utf-8")
    source_manifest = {
        "schema_version": "seed-product-images-v1",
        "product_count": source_count,
        "products_file": source_products_path.name,
        "products_sha256": hashlib.sha256(
            products_text.encode("utf-8")
        ).hexdigest(),
        "source_images_sha256": hashlib.sha256(
            "\n".join(
                f"{row['product_id']}\t{row['source_image_sha256']}"
                for row in rows
            ).encode("utf-8")
        ).hexdigest(),
    }
    source_manifest["manifest_sha256"] = hashlib.sha256(
        _canonical_json(source_manifest).encode("utf-8")
    ).hexdigest()
    source_manifest_path.write_text(
        _canonical_json(source_manifest) + "\n",
        encoding="utf-8",
    )

    artifact_root = (tmp_path / "image-index").resolve()
    entries: list[ImageIndexEntry] = []
    vector_path: Path | None = None
    for row in rows:
        current_vector_path = (
            artifact_root / "vectors" / f"{row['product_id']}.bin"
        )
        current_vector_path.parent.mkdir(parents=True, exist_ok=True)
        vector_payload = (
            f"nonzero-runtime-vector-{row['product_id']}".encode()
        )
        current_vector_path.write_bytes(vector_payload)
        if vector_path is None:
            vector_path = current_vector_path
        entries.append(
            ImageIndexEntry(
                product_id=row["product_id"],
                source_path=row["relative_path"],
                source_bytes=row["bytes"],
                source_sha256=row["source_image_sha256"],
                vector_path=current_vector_path.relative_to(
                    artifact_root
                ).as_posix(),
                vector_sha256=hashlib.sha256(
                    vector_payload
                ).hexdigest(),
            )
        )
    index_path = artifact_root / "index.bin"
    index_payload = b"nonzero-runtime-index-fixture"
    index_path.write_bytes(index_payload)

    manifest = ImageIndexManifest(
        source_manifest_path=source_manifest_path.relative_to(
            source_root
        ).as_posix(),
        source_manifest_sha256=source_manifest["manifest_sha256"],
        source_products_path=source_products_path.relative_to(
            source_root
        ).as_posix(),
        source_products_sha256=source_manifest["products_sha256"],
        model_name="approved-model",
        weights_sha256=WEIGHTS_SHA,
        preprocessing_version="preprocess-v1",
        vector_dimension=4,
        entries=tuple(entries),
        index_path="index.bin",
        index_sha256=hashlib.sha256(index_payload).hexdigest(),
        manifest_sha256="0" * 64,
    )
    manifest = manifest.model_copy(
        update={
            "manifest_sha256": (
                compute_image_index_manifest_sha256(manifest)
            )
        }
    )
    manifest_path = artifact_root / "manifest.json"
    manifest_path.write_text(
        _canonical_json(manifest.model_dump(mode="json")) + "\n",
        encoding="utf-8",
    )
    runtime_lock = ImageIndexRuntimeLock(
        manifest_sha256=manifest.manifest_sha256,
        model_name=manifest.model_name,
        weights_sha256=manifest.weights_sha256,
        preprocessing_version=manifest.preprocessing_version,
        vector_dimension=manifest.vector_dimension,
        index_sha256=manifest.index_sha256,
    )
    return _RuntimeFixture(
        manifest_path=manifest_path,
        source_root=source_root,
        artifact_root=artifact_root,
        runtime_lock=runtime_lock,
        source_image_path=(
            source_root / str(rows[0]["relative_path"])
        ),
        vector_path=vector_path,
        index_path=index_path,
    )


def _health(
    fixture: _RuntimeFixture,
    *,
    runtime_lock: ImageIndexRuntimeLock | None = None,
):
    return ImageIndexHealthCheck(
        manifest_path=fixture.manifest_path,
        source_root=fixture.source_root,
        artifact_root=fixture.artifact_root,
        runtime_lock=runtime_lock or fixture.runtime_lock,
    ).check()


def _change_first_byte(path: Path) -> None:
    content = path.read_bytes()
    path.write_bytes(bytes([content[0] ^ 0xFF]) + content[1:])


def _retrieval_request() -> ImageRetrievalRequest:
    content = b"validated-image"
    return ImageRetrievalRequest(
        image_id="opaque-image",
        content_sha256=hashlib.sha256(content).hexdigest(),
        content=content,
        max_results=3,
    )


def test_complete_runtime_fixture_is_healthy(tmp_path: Path) -> None:
    fixture = _write_runtime_fixture(tmp_path)

    health = _health(fixture)

    assert health.healthy
    assert health.issues == ()
    assert health.manifest_sha256 == fixture.runtime_lock.manifest_sha256
    assert health.index_sha256 == fixture.runtime_lock.index_sha256


@pytest.mark.parametrize("source_count", [102, 104])
def test_noncanonical_source_count_is_unhealthy_and_blocks_retrieval(
    tmp_path: Path,
    source_count: int,
) -> None:
    fixture = _write_runtime_fixture(
        tmp_path,
        source_count=source_count,
    )
    delegate = _RecordingRetriever(fixture.runtime_lock)
    guard = HealthGuardedImageRetrieval(
        retrieval=delegate,
        health_check=ImageIndexHealthCheck(
            manifest_path=fixture.manifest_path,
            source_root=fixture.source_root,
            artifact_root=fixture.artifact_root,
            runtime_lock=fixture.runtime_lock,
        ),
    )

    health = _health(fixture)

    assert not health.healthy
    assert "source_integrity_drift" in health.issues
    with pytest.raises(
        ImageRetrievalUnavailableError,
        match="source_integrity_drift",
    ):
        guard.retrieve(_retrieval_request())
    assert delegate.calls == 0


def test_duplicate_manifest_entry_is_unhealthy_and_blocks_retrieval(
    tmp_path: Path,
) -> None:
    fixture = _write_runtime_fixture(tmp_path)
    payload = json.loads(
        fixture.manifest_path.read_text(encoding="utf-8")
    )
    payload["entries"][1]["product_id"] = payload["entries"][0][
        "product_id"
    ]
    unsigned = {
        key: value
        for key, value in payload.items()
        if key != "manifest_sha256"
    }
    payload["manifest_sha256"] = hashlib.sha256(
        _canonical_json(unsigned).encode("utf-8")
    ).hexdigest()
    fixture.manifest_path.write_text(
        _canonical_json(payload) + "\n",
        encoding="utf-8",
    )
    runtime_lock = fixture.runtime_lock.model_copy(
        update={"manifest_sha256": payload["manifest_sha256"]}
    )
    delegate = _RecordingRetriever(runtime_lock)
    guard = HealthGuardedImageRetrieval(
        retrieval=delegate,
        health_check=ImageIndexHealthCheck(
            manifest_path=fixture.manifest_path,
            source_root=fixture.source_root,
            artifact_root=fixture.artifact_root,
            runtime_lock=runtime_lock,
        ),
    )

    health = _health(fixture, runtime_lock=runtime_lock)

    assert not health.healthy
    assert health.issues == ("manifest_integrity_drift",)
    with pytest.raises(
        ImageRetrievalUnavailableError,
        match="manifest_integrity_drift",
    ):
        guard.retrieve(_retrieval_request())
    assert delegate.calls == 0


@pytest.mark.parametrize(
    ("field", "value", "issue"),
    [
        ("manifest_sha256", "b" * 64, "manifest_lock_drift"),
        ("model_name", "different-model", "model_name_drift"),
        ("weights_sha256", "b" * 64, "weights_sha_drift"),
        (
            "preprocessing_version",
            "preprocess-v2",
            "preprocessing_version_drift",
        ),
        ("vector_dimension", 8, "vector_dimension_drift"),
        ("index_sha256", "b" * 64, "index_lock_drift"),
    ],
)
def test_runtime_lock_drift_is_unhealthy(
    tmp_path: Path,
    field: str,
    value: object,
    issue: str,
) -> None:
    fixture = _write_runtime_fixture(tmp_path)
    drifted_lock = fixture.runtime_lock.model_copy(
        update={field: value}
    )

    health = _health(fixture, runtime_lock=drifted_lock)

    assert not health.healthy
    assert issue in health.issues


@pytest.mark.parametrize(
    ("path_name", "issue"),
    [
        ("source_image_path", "source_integrity_drift"),
        ("vector_path", "vector_integrity_drift"),
        ("index_path", "index_integrity_drift"),
    ],
)
def test_artifact_sha_drift_is_unhealthy(
    tmp_path: Path,
    path_name: str,
    issue: str,
) -> None:
    fixture = _write_runtime_fixture(tmp_path)
    _change_first_byte(getattr(fixture, path_name))

    health = _health(fixture)

    assert not health.healthy
    assert issue in health.issues


def test_manifest_content_drift_is_unhealthy(tmp_path: Path) -> None:
    fixture = _write_runtime_fixture(tmp_path)
    payload = json.loads(
        fixture.manifest_path.read_text(encoding="utf-8")
    )
    payload["model_name"] = "tampered-model"
    fixture.manifest_path.write_text(
        _canonical_json(payload) + "\n",
        encoding="utf-8",
    )

    health = _health(fixture)

    assert not health.healthy
    assert health.issues == ("manifest_integrity_drift",)


class _RecordingRetriever:
    def __init__(
        self,
        runtime_lock: ImageIndexRuntimeLock,
        *,
        result_model_name: str | None = None,
    ) -> None:
        self.calls = 0
        self._runtime_lock = runtime_lock
        self._result_model_name = result_model_name

    def retrieve(
        self,
        request: ImageRetrievalRequest,
    ) -> ImageRetrievalResult:
        self.calls += 1
        return ImageRetrievalResult(
            candidates=(
                ImageRetrievalCandidate(
                    rank=1,
                    product_id=24,
                    similarity=1.0,
                ),
            ),
            model_name=(
                self._result_model_name
                or self._runtime_lock.model_name
            ),
            weights_sha256=self._runtime_lock.weights_sha256,
            preprocessing_version=(
                self._runtime_lock.preprocessing_version
            ),
            vector_dimension=self._runtime_lock.vector_dimension,
            index_sha256=self._runtime_lock.index_sha256,
        )


def test_guard_blocks_retrieval_before_delegate_when_unhealthy(
    tmp_path: Path,
) -> None:
    fixture = _write_runtime_fixture(tmp_path)
    _change_first_byte(fixture.vector_path)
    delegate = _RecordingRetriever(fixture.runtime_lock)
    guard = HealthGuardedImageRetrieval(
        retrieval=delegate,
        health_check=ImageIndexHealthCheck(
            manifest_path=fixture.manifest_path,
            source_root=fixture.source_root,
            artifact_root=fixture.artifact_root,
            runtime_lock=fixture.runtime_lock,
        ),
    )
    request = _retrieval_request()

    with pytest.raises(
        ImageRetrievalUnavailableError,
        match="image_index_unhealthy",
    ):
        guard.retrieve(request)

    assert delegate.calls == 0


def test_guard_allows_healthy_retrieval(tmp_path: Path) -> None:
    fixture = _write_runtime_fixture(tmp_path)
    delegate = _RecordingRetriever(fixture.runtime_lock)
    guard = HealthGuardedImageRetrieval(
        retrieval=delegate,
        health_check=ImageIndexHealthCheck(
            manifest_path=fixture.manifest_path,
            source_root=fixture.source_root,
            artifact_root=fixture.artifact_root,
            runtime_lock=fixture.runtime_lock,
        ),
    )
    request = _retrieval_request()

    result = guard.retrieve(request)

    assert delegate.calls == 1
    assert result.candidates[0].product_id == 24


def test_guard_rejects_result_from_drifted_model(
    tmp_path: Path,
) -> None:
    fixture = _write_runtime_fixture(tmp_path)
    delegate = _RecordingRetriever(
        fixture.runtime_lock,
        result_model_name="different-loaded-model",
    )
    guard = HealthGuardedImageRetrieval(
        retrieval=delegate,
        health_check=ImageIndexHealthCheck(
            manifest_path=fixture.manifest_path,
            source_root=fixture.source_root,
            artifact_root=fixture.artifact_root,
            runtime_lock=fixture.runtime_lock,
        ),
    )
    request = _retrieval_request()

    with pytest.raises(
        ImageRetrievalUnavailableError,
        match="retrieval_result_drift",
    ):
        guard.retrieve(request)

    assert delegate.calls == 1


class _MutatingRetriever(_RecordingRetriever):
    def __init__(
        self,
        runtime_lock: ImageIndexRuntimeLock,
        vector_path: Path,
    ) -> None:
        super().__init__(runtime_lock)
        self._vector_path = vector_path

    def retrieve(
        self,
        request: ImageRetrievalRequest,
    ) -> ImageRetrievalResult:
        result = super().retrieve(request)
        _change_first_byte(self._vector_path)
        return result


def test_guard_rechecks_health_after_retrieval(
    tmp_path: Path,
) -> None:
    fixture = _write_runtime_fixture(tmp_path)
    delegate = _MutatingRetriever(
        fixture.runtime_lock,
        fixture.vector_path,
    )
    guard = HealthGuardedImageRetrieval(
        retrieval=delegate,
        health_check=ImageIndexHealthCheck(
            manifest_path=fixture.manifest_path,
            source_root=fixture.source_root,
            artifact_root=fixture.artifact_root,
            runtime_lock=fixture.runtime_lock,
        ),
    )
    request = _retrieval_request()

    with pytest.raises(
        ImageRetrievalUnavailableError,
        match="vector_integrity_drift",
    ):
        guard.retrieve(request)

    assert delegate.calls == 1


def test_path_resolution_failure_is_unhealthy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _write_runtime_fixture(tmp_path)
    original_resolve = Path.resolve

    def fail_vector_resolve(path: Path, *args, **kwargs):
        if path == fixture.vector_path:
            raise RuntimeError("simulated symlink loop")
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", fail_vector_resolve)

    health = _health(fixture)

    assert not health.healthy
    assert "vector_integrity_drift" in health.issues


@pytest.mark.parametrize(
    "failure",
    [
        OSError("secret filesystem detail"),
        RuntimeError("secret symlink detail"),
    ],
)
def test_source_root_resolution_failure_is_sanitized_unhealthy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    fixture = _write_runtime_fixture(tmp_path)
    original_resolve = Path.resolve

    def fail_source_root_resolve(path: Path, *args, **kwargs):
        if path == fixture.source_root:
            raise failure
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", fail_source_root_resolve)

    health = _health(fixture)

    assert not health.healthy
    assert health.issues == ("source_integrity_drift",)
    assert "secret" not in repr(health)
    assert str(fixture.source_root) not in repr(health)


def test_source_root_symlink_loop_is_sanitized_unhealthy(
    tmp_path: Path,
) -> None:
    fixture = _write_runtime_fixture(tmp_path)
    source_loop = tmp_path / "source-loop"
    source_loop.symlink_to(source_loop, target_is_directory=True)
    health_check = ImageIndexHealthCheck(
        manifest_path=fixture.manifest_path,
        source_root=source_loop,
        artifact_root=fixture.artifact_root,
        runtime_lock=fixture.runtime_lock,
    )

    health = health_check.check()

    assert not health.healthy
    assert health.issues == ("source_integrity_drift",)
    assert str(source_loop) not in repr(health)
