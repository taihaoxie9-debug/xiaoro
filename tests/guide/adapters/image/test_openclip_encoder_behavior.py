from __future__ import annotations

from contextlib import nullcontext
import errno
import hashlib
from pathlib import Path
import stat
from types import SimpleNamespace

import numpy as np
from PIL import Image
import pytest
import torch

import app.guide.adapters.image.openclip_adapter as adapter


class _FakePreprocess:
    def __call__(self, image: Image.Image) -> torch.Tensor:
        value = float(image.getpixel((0, 0))[0]) + 1.0
        return torch.full((3, 224, 224), value, dtype=torch.float32)


class _FakeModel:
    def __init__(self, *, output_dim: int = 512) -> None:
        self.visual = SimpleNamespace(
            output_dim=output_dim,
            image_size=(224, 224),
        )
        self._parameter = torch.zeros(1, dtype=torch.float32)
        self.eval_called = False

    def parameters(self):
        yield self._parameter

    def eval(self):
        self.eval_called = True
        return self

    def encode_image(self, batch: torch.Tensor) -> torch.Tensor:
        first = batch[:, 0, 0, 0].reshape(-1, 1)
        return first.repeat(1, self.visual.output_dim)


def _patch_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    model: _FakeModel | None = None,
) -> _FakeModel:
    runtime_model = model or _FakeModel()
    monkeypatch.setattr(
        adapter,
        "_validated_weight_snapshot",
        lambda path: nullcontext(Path(path)),
        raising=False,
    )
    monkeypatch.setattr(
        adapter,
        "_validate_safetensors_metadata",
        lambda path: None,
    )
    monkeypatch.setattr(
        adapter,
        "_load_locked_runtime",
        lambda spec, path: (runtime_model, _FakePreprocess()),
        raising=False,
    )
    monkeypatch.setattr(
        adapter,
        "image_inference_slot",
        lambda: nullcontext(),
        raising=False,
    )
    return runtime_model


def _write_png(path: Path, color: tuple[int, int, int]) -> bytes:
    image = Image.new("RGB", (8, 6), color)
    image.save(path, format="PNG")
    return path.read_bytes()


def _patch_small_locked_weight(
    monkeypatch: pytest.MonkeyPatch,
    content: bytes,
) -> None:
    monkeypatch.setattr(adapter, "LOCKED_WEIGHT_BYTES", len(content))
    monkeypatch.setattr(
        adapter,
        "LOCKED_WEIGHT_SHA256",
        hashlib.sha256(content).hexdigest(),
    )


def test_cpu_encoder_batches_fp32_512_and_l2_normalizes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _patch_runtime(monkeypatch)
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first_bytes = _write_png(first, (10, 20, 30))
    _write_png(second, (30, 20, 10))
    encoder = adapter.OpenClipImageEncoder(
        adapter.OpenClipModelSpec(
            weight_path=tmp_path / "open_clip_model.safetensors",
            device="cpu",
        )
    )

    vectors = encoder.encode_paths((first, second), batch_size=2)
    content_vectors = encoder.encode_contents(
        (first_bytes,),
        batch_size=1,
    )
    query = encoder.encode_bytes(first_bytes)

    assert model.eval_called
    assert vectors.shape == (2, 512)
    assert content_vectors.shape == (1, 512)
    assert query.shape == (512,)
    assert vectors.dtype == np.dtype("<f4")
    assert query.dtype == np.dtype("<f4")
    assert np.isfinite(vectors).all()
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-6)
    assert np.isclose(np.linalg.norm(query), 1.0, atol=1e-6)
    assert encoder.model_lock.vector_dimension == 512
    assert encoder.model_lock.preprocessing_version == (
        adapter.LOCKED_PREPROCESS_VERSION
    )


def test_mps_unavailable_fails_without_loading_or_cpu_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        adapter,
        "_validated_weight_snapshot",
        lambda path: nullcontext(Path(path)),
        raising=False,
    )
    monkeypatch.setattr(
        adapter,
        "_validate_safetensors_metadata",
        lambda path: None,
    )
    monkeypatch.setattr(
        adapter,
        "_mps_is_built_and_available",
        lambda: False,
        raising=False,
    )
    monkeypatch.setattr(
        adapter,
        "_load_locked_runtime",
        lambda spec, path: calls.append(spec.device),
        raising=False,
    )

    with pytest.raises(adapter.OpenClipModelError) as caught:
        adapter.OpenClipImageEncoder(
            adapter.OpenClipModelSpec(
                weight_path=tmp_path / "open_clip_model.safetensors",
                device="mps",
            )
        )

    assert caught.value.code == "mps_unavailable"
    assert calls == []


def test_loaded_model_dimension_drift_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_runtime(monkeypatch, model=_FakeModel(output_dim=768))

    with pytest.raises(adapter.OpenClipModelError) as caught:
        adapter.OpenClipImageEncoder(
            adapter.OpenClipModelSpec(
                weight_path=tmp_path / "open_clip_model.safetensors",
                device="cpu",
            )
        )

    assert caught.value.code == "model_output_dimension_drift"


def test_source_path_change_during_load_does_not_invalidate_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    locked_content = b"locked-weight-before-load"
    replacement_content = b"replacement-after-loading"
    assert len(replacement_content) == len(locked_content)
    _patch_small_locked_weight(monkeypatch, locked_content)
    source = tmp_path / "open_clip_model.safetensors"
    original_inode = tmp_path / "original-inode.safetensors"
    source.write_bytes(locked_content)
    loaded_content: list[bytes] = []
    monkeypatch.setattr(
        adapter,
        "_validate_safetensors_metadata",
        lambda path: None,
    )

    def load_runtime(spec, path):
        loaded_content.append(path.read_bytes())
        source.replace(original_inode)
        source.write_bytes(replacement_content)
        return _FakeModel(), _FakePreprocess()

    monkeypatch.setattr(adapter, "_load_locked_runtime", load_runtime)

    adapter.OpenClipImageEncoder(
        adapter.OpenClipModelSpec(
            weight_path=source,
            device="cpu",
        )
    )

    assert loaded_content == [locked_content]
    assert source.read_bytes() == replacement_content


def test_model_load_uses_private_copy_of_validated_resolved_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    locked_content = b"validated-weight"
    _patch_small_locked_weight(monkeypatch, locked_content)
    supplied_path = tmp_path / "snapshot" / "open_clip_model.safetensors"
    validated_target = tmp_path / "blobs" / adapter.LOCKED_WEIGHT_SHA256
    supplied_path.parent.mkdir()
    validated_target.parent.mkdir()
    validated_target.write_bytes(locked_content)
    supplied_path.symlink_to(validated_target)
    load_observations: list[tuple[str, bool, bool, int, bytes]] = []
    monkeypatch.setattr(
        adapter,
        "_validate_safetensors_metadata",
        lambda path: None,
    )

    def load_runtime(spec, path):
        load_observations.append(
            (
                path.suffix,
                path != supplied_path and path != validated_target,
                path.stat().st_ino != validated_target.stat().st_ino,
                stat.S_IMODE(path.stat().st_mode),
                path.read_bytes(),
            )
        )
        return _FakeModel(), _FakePreprocess()

    monkeypatch.setattr(
        adapter,
        "_load_locked_runtime",
        load_runtime,
    )

    adapter.OpenClipImageEncoder(
        adapter.OpenClipModelSpec(
            weight_path=supplied_path,
            device="cpu",
        )
    )

    assert load_observations == [
        (".safetensors", True, True, 0o600, locked_content)
    ]


def test_source_path_replacement_cannot_change_verified_load_inode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    locked_content = b"locked-and-validated-weight"
    replacement_content = b"attacker-controlled-weight!"
    assert len(replacement_content) == len(locked_content)
    _patch_small_locked_weight(monkeypatch, locked_content)
    source = tmp_path / "open_clip_model.safetensors"
    validated_inode = tmp_path / "validated-inode.safetensors"
    source.write_bytes(locked_content)
    load_observations: list[tuple[bytes, int, bool]] = []

    def replace_source_after_validation(path: Path) -> None:
        source.replace(validated_inode)
        source.write_bytes(replacement_content)

    def load_runtime(spec, path):
        load_observations.append(
            (
                path.read_bytes(),
                stat.S_IMODE(path.stat().st_mode),
                path.stat().st_ino != validated_inode.stat().st_ino,
            )
        )
        return _FakeModel(), _FakePreprocess()

    monkeypatch.setattr(
        adapter,
        "_validate_safetensors_metadata",
        replace_source_after_validation,
    )
    monkeypatch.setattr(adapter, "_load_locked_runtime", load_runtime)

    adapter.OpenClipImageEncoder(
        adapter.OpenClipModelSpec(weight_path=source, device="cpu")
    )

    assert source.read_bytes() == replacement_content
    assert load_observations == [(locked_content, 0o600, True)]


def test_weight_snapshot_does_not_depend_on_cross_filesystem_hardlinks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    locked_content = b"locked-weight"
    _patch_small_locked_weight(monkeypatch, locked_content)
    source = tmp_path / "open_clip_model.safetensors"
    source.write_bytes(locked_content)
    loaded_content: list[bytes] = []
    monkeypatch.setattr(
        adapter,
        "_validate_safetensors_metadata",
        lambda path: None,
    )
    monkeypatch.setattr(
        adapter,
        "_load_locked_runtime",
        lambda spec, path: (
            loaded_content.append(path.read_bytes()) or _FakeModel(),
            _FakePreprocess(),
        ),
    )

    def fail_cross_filesystem_link(*args, **kwargs) -> None:
        raise OSError(errno.EXDEV, "cross-device link")

    monkeypatch.setattr(adapter.os, "link", fail_cross_filesystem_link)

    adapter.OpenClipImageEncoder(
        adapter.OpenClipModelSpec(weight_path=source, device="cpu")
    )

    assert loaded_content == [locked_content]


def test_invalid_query_image_fails_instead_of_returning_empty_vector(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_runtime(monkeypatch)
    encoder = adapter.OpenClipImageEncoder(
        adapter.OpenClipModelSpec(
            weight_path=tmp_path / "open_clip_model.safetensors",
            device="cpu",
        )
    )

    with pytest.raises(adapter.OpenClipModelError) as caught:
        encoder.encode_bytes(b"not-an-image")

    assert caught.value.code == "image_decode_failed"
