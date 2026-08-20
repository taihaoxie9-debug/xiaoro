from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

import app.guide.adapters.image.index_build as index_build_module
from app.guide.adapters.image.index_build import (
    ImageIndexBuildService,
    compute_image_index_manifest_sha256,
)
from app.guide.retrieval.image_contracts import (
    ApprovedImageModelLock,
    ImageIndexBuildInput,
    ImageIndexEntry,
    ImageIndexManifest,
    UnapprovedImageModel,
)


ROOT = Path(__file__).resolve().parents[4]
CANONICAL = ROOT / "data" / "canonical"
CANONICAL_MANIFEST = (
    CANONICAL / "seed_product_images_v1_manifest.json"
)
CANONICAL_PRODUCTS = CANONICAL / "seed_product_images_v1.jsonl"
WEIGHTS_SHA = "a" * 64


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _write_one_source_snapshot(
    tmp_path: Path,
) -> tuple[Path, Path, Path]:
    source_root = (tmp_path / "source-root").resolve()
    canonical = source_root / "data" / "canonical"
    canonical.mkdir(parents=True)
    manifest_path = canonical / CANONICAL_MANIFEST.name
    products_path = canonical / CANONICAL_PRODUCTS.name

    row = json.loads(
        CANONICAL_PRODUCTS.read_text(encoding="utf-8").splitlines()[0]
    )
    source_image = ROOT / row["relative_path"]
    target_image = source_root / row["relative_path"]
    target_image.parent.mkdir(parents=True)
    shutil.copy2(source_image, target_image)

    products_text = _canonical_json(row) + "\n"
    products_path.write_text(products_text, encoding="utf-8")
    source_digest = hashlib.sha256(
        (
            f"{row['product_id']}\t"
            f"{row['source_image_sha256']}"
        ).encode("utf-8")
    ).hexdigest()
    manifest = json.loads(
        CANONICAL_MANIFEST.read_text(encoding="utf-8")
    )
    manifest["product_count"] = 1
    manifest["products_sha256"] = hashlib.sha256(
        products_text.encode("utf-8")
    ).hexdigest()
    manifest["source_images_sha256"] = source_digest
    unsigned = {
        key: value
        for key, value in manifest.items()
        if key != "manifest_sha256"
    }
    manifest["manifest_sha256"] = hashlib.sha256(
        _canonical_json(unsigned).encode("utf-8")
    ).hexdigest()
    manifest_path.write_text(
        _canonical_json(manifest) + "\n",
        encoding="utf-8",
    )
    return manifest_path, products_path, source_root


def _approved_model() -> ApprovedImageModelLock:
    return ApprovedImageModelLock(
        approval_id="user-decision-1",
        model_name="approved-model",
        weights_sha256=WEIGHTS_SHA,
        preprocessing_version="preprocess-v1",
        vector_dimension=4,
    )


def _request(
    *,
    tmp_path: Path,
    model=None,
) -> ImageIndexBuildInput:
    manifest_path, products_path, source_root = (
        _write_one_source_snapshot(tmp_path)
    )
    return ImageIndexBuildInput(
        source_manifest_path=manifest_path,
        source_products_path=products_path,
        source_root=source_root,
        output_dir=(tmp_path / "published-index").resolve(),
        model=model,
    )


def _staging_paths(tmp_path: Path) -> list[Path]:
    return list(tmp_path.glob(".published-index.staging-*"))


class _MustNotRunBuilder:
    def __init__(self) -> None:
        self.called = False

    def build(self, **kwargs):
        self.called = True
        raise AssertionError("builder must not run")


class _FailingBuilder:
    def build(self, *, staging_dir: Path, **kwargs):
        (staging_dir / "partial.bin").write_bytes(b"partial")
        raise RuntimeError("encoder failed")


class _PermissionLockedFailingBuilder:
    def build(self, *, staging_dir: Path, **kwargs):
        locked = staging_dir / "locked"
        locked.mkdir()
        (locked / "partial.bin").write_bytes(b"partial")
        locked.chmod(0)
        raise RuntimeError("encoder failed")


class _CompleteFixtureBuilder:
    def __init__(
        self,
        output_dir: Path,
        *,
        index_path: str = "index.bin",
        vector_path: str | None = None,
    ) -> None:
        self.output_dir = output_dir
        self.index_path = index_path
        self.vector_path = vector_path
        self.saw_private_staging = False

    def build(
        self,
        *,
        source_report,
        model: ApprovedImageModelLock,
        staging_dir: Path,
    ) -> ImageIndexManifest:
        assert not self.output_dir.exists()
        assert staging_dir.parent == self.output_dir.parent
        self.saw_private_staging = staging_dir.is_dir()

        source = source_report.sources[0]
        vector_path = Path(
            self.vector_path
            or f"vectors/{source.product_id}.bin"
        )
        vector_payload = b"nonzero-vector-fixture"
        (staging_dir / vector_path).parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        (staging_dir / vector_path).write_bytes(vector_payload)
        index_payload = b"nonzero-index-fixture"
        (staging_dir / self.index_path).write_bytes(index_payload)

        manifest = ImageIndexManifest(
            source_manifest_path=source_report.source_manifest_path,
            source_manifest_sha256=(
                source_report.source_manifest_sha256
            ),
            source_products_path=source_report.source_products_path,
            source_products_sha256=(
                source_report.source_products_sha256
            ),
            model_name=model.model_name,
            weights_sha256=model.weights_sha256,
            preprocessing_version=model.preprocessing_version,
            vector_dimension=model.vector_dimension,
            entries=(
                ImageIndexEntry(
                    product_id=source.product_id,
                    source_path=source.source_path,
                    source_bytes=source.source_bytes,
                    source_sha256=source.source_sha256,
                    vector_path=vector_path.as_posix(),
                    vector_sha256=hashlib.sha256(
                        vector_payload
                    ).hexdigest(),
                ),
            ),
            index_path=self.index_path,
            index_sha256=hashlib.sha256(index_payload).hexdigest(),
            manifest_sha256="0" * 64,
        )
        return manifest.model_copy(
            update={
                "manifest_sha256": (
                    compute_image_index_manifest_sha256(manifest)
                )
            }
        )


class _LateOutputDirectoryBuilder(_CompleteFixtureBuilder):
    def build(self, **kwargs) -> ImageIndexManifest:
        manifest = super().build(**kwargs)
        self.output_dir.mkdir()
        return manifest


def test_missing_model_lock_is_no_go_without_artifacts(
    tmp_path: Path,
) -> None:
    builder = _MustNotRunBuilder()
    request = _request(tmp_path=tmp_path)

    result = ImageIndexBuildService(
        artifact_builder=builder,
        expected_source_count=1,
    ).build(request)

    assert result.status == "no_go"
    assert result.code == "model_lock_missing"
    assert result.source_count == 1
    assert not builder.called
    assert not request.output_dir.exists()
    assert _staging_paths(tmp_path) == []


def test_unapproved_model_is_no_go_without_artifacts(
    tmp_path: Path,
) -> None:
    builder = _MustNotRunBuilder()
    request = _request(
        tmp_path=tmp_path,
        model=UnapprovedImageModel(reason="awaiting user decision"),
    )

    result = ImageIndexBuildService(
        artifact_builder=builder,
        expected_source_count=1,
    ).build(request)

    assert result.status == "no_go"
    assert result.code == "model_not_approved"
    assert not builder.called
    assert not request.output_dir.exists()
    assert _staging_paths(tmp_path) == []


def test_approved_lock_without_real_builder_is_no_go(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path=tmp_path, model=_approved_model())

    result = ImageIndexBuildService(
        expected_source_count=1,
    ).build(request)

    assert result.status == "no_go"
    assert result.code == "vector_builder_unavailable"
    assert not request.output_dir.exists()
    assert _staging_paths(tmp_path) == []


def test_failed_builder_removes_private_staging_and_output(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path=tmp_path, model=_approved_model())

    result = ImageIndexBuildService(
        artifact_builder=_FailingBuilder(),
        expected_source_count=1,
    ).build(request)

    assert result.status == "no_go"
    assert result.code == "index_build_failed"
    assert not request.output_dir.exists()
    assert _staging_paths(tmp_path) == []


def test_failed_builder_repairs_permissions_before_staging_cleanup(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path=tmp_path, model=_approved_model())

    try:
        result = ImageIndexBuildService(
            artifact_builder=_PermissionLockedFailingBuilder(),
            expected_source_count=1,
        ).build(request)

        assert result.status == "no_go"
        assert result.code == "index_build_failed"
        assert not request.output_dir.exists()
        assert _staging_paths(tmp_path) == []
    finally:
        for staging_dir in _staging_paths(tmp_path):
            locked = staging_dir / "locked"
            if locked.exists():
                locked.chmod(0o700)
            shutil.rmtree(staging_dir)


def test_persistent_staging_cleanup_failure_is_explicit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path=tmp_path, model=_approved_model())
    real_rmtree = shutil.rmtree

    def fail_cleanup(*args, **kwargs):
        raise PermissionError("simulated persistent cleanup failure")

    monkeypatch.setattr(index_build_module.shutil, "rmtree", fail_cleanup)

    try:
        result = ImageIndexBuildService(
            artifact_builder=_FailingBuilder(),
            expected_source_count=1,
        ).build(request)
        residual = _staging_paths(tmp_path)

        assert result.status == "no_go"
        assert result.code == "index_cleanup_failed"
        assert len(residual) == 1
        assert str(residual[0]) in result.detail
        assert not request.output_dir.exists()
    finally:
        for staging_dir in _staging_paths(tmp_path):
            real_rmtree(staging_dir)


def test_cleanup_refuses_staging_path_outside_output_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path=tmp_path, model=_approved_model())
    output_parent = tmp_path / "artifacts"
    output_parent.mkdir()
    request = request.model_copy(
        update={"output_dir": output_parent / "published-index"}
    )
    outside_staging = tmp_path / ".published-index.staging-outside"
    outside_staging.mkdir()
    outside_marker = outside_staging / "must-remain.txt"
    outside_marker.write_text("outside cleanup boundary", encoding="utf-8")
    monkeypatch.setattr(
        index_build_module.tempfile,
        "mkdtemp",
        lambda **kwargs: str(outside_staging),
    )

    try:
        result = ImageIndexBuildService(
            artifact_builder=_FailingBuilder(),
            expected_source_count=1,
        ).build(request)

        assert result.status == "no_go"
        assert result.code == "index_cleanup_failed"
        assert str(outside_staging) in result.detail
        assert outside_marker.is_file()
        assert not request.output_dir.exists()
    finally:
        if outside_staging.exists():
            shutil.rmtree(outside_staging)


def test_complete_build_is_published_by_single_directory_replace(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path=tmp_path, model=_approved_model())
    builder = _CompleteFixtureBuilder(request.output_dir)

    result = ImageIndexBuildService(
        artifact_builder=builder,
        expected_source_count=1,
    ).build(request)

    assert result.status == "built"
    assert builder.saw_private_staging
    assert result.output_dir == request.output_dir
    assert result.manifest_path == request.output_dir / "manifest.json"
    assert result.index_path == request.output_dir / "index.bin"
    assert result.product_ids == (24,)
    assert request.output_dir.is_dir()
    assert _staging_paths(tmp_path) == []
    manifest = ImageIndexManifest.model_validate_json(
        result.manifest_path.read_text(encoding="utf-8")
    )
    assert manifest.manifest_sha256 == result.manifest_sha256
    assert manifest.index_sha256 == result.index_sha256


def test_output_directory_created_during_build_is_not_clobbered(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path=tmp_path, model=_approved_model())
    builder = _LateOutputDirectoryBuilder(request.output_dir)

    result = ImageIndexBuildService(
        artifact_builder=builder,
        expected_source_count=1,
    ).build(request)

    assert result.status == "no_go"
    assert result.code == "output_already_exists"
    assert request.output_dir.is_dir()
    assert list(request.output_dir.iterdir()) == []
    assert _staging_paths(tmp_path) == []


def test_output_directory_created_at_publication_is_not_clobbered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path=tmp_path, model=_approved_model())
    builder = _CompleteFixtureBuilder(request.output_dir)
    original_publish = (
        index_build_module._rename_directory_no_replace
    )

    def race_publication(
        source_dir: Path,
        output_dir: Path,
    ) -> None:
        output_dir.mkdir()
        original_publish(source_dir, output_dir)

    monkeypatch.setattr(
        index_build_module,
        "_rename_directory_no_replace",
        race_publication,
    )

    result = ImageIndexBuildService(
        artifact_builder=builder,
        expected_source_count=1,
    ).build(request)

    assert result.status == "no_go"
    assert result.code == "output_already_exists"
    assert request.output_dir.is_dir()
    assert list(request.output_dir.iterdir()) == []
    assert _staging_paths(tmp_path) == []


@pytest.mark.parametrize(
    ("index_path", "vector_path"),
    [
        ("manifest.json", None),
        ("index.bin", "manifest.json"),
    ],
)
def test_reserved_manifest_path_fails_without_published_artifacts(
    tmp_path: Path,
    index_path: str,
    vector_path: str | None,
) -> None:
    request = _request(tmp_path=tmp_path, model=_approved_model())
    builder = _CompleteFixtureBuilder(
        request.output_dir,
        index_path=index_path,
        vector_path=vector_path,
    )

    result = ImageIndexBuildService(
        artifact_builder=builder,
        expected_source_count=1,
    ).build(request)

    assert result.status == "no_go"
    assert result.code == "index_build_failed"
    assert not request.output_dir.exists()
    assert _staging_paths(tmp_path) == []
