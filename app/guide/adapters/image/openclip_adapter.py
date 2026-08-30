from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
from importlib import metadata as importlib_metadata
from io import BytesIO
import os
from pathlib import Path
import stat
import tempfile
from threading import RLock
from typing import Any, Literal

import numpy as np
from PIL import Image, UnidentifiedImageError

from app.guide.adapters.image.inference_limiter import (
    image_inference_slot,
)
from app.guide.retrieval.image_contracts import (
    ApprovedImageModelLock,
)


LOCKED_MODEL_NAME = "ViT-B-32"
LOCKED_PRETRAINED_TAG = "laion2b_s34b_b79k"
LOCKED_REVISION = "1a25a446712ba5ee05982a381eed697ef9b435cf"
LOCKED_WEIGHT_BYTES = 605143316
LOCKED_WEIGHT_SHA256 = (
    "ac4f8c4b88af6d963118cbf40ad93176d092abbedfcb752601ae1866352656e6"
)
LOCKED_VECTOR_DIMENSION = 512
LOCKED_ARTIFACT_MODEL_NAME = (
    f"OpenCLIP:{LOCKED_MODEL_NAME}:{LOCKED_PRETRAINED_TAG}@"
    f"{LOCKED_REVISION}"
)
LOCKED_APPROVAL_ID = "slice2.0-model-gate-2026-08-08"
LOCKED_PREPROCESS_VERSION = (
    "openclip-3.3.0|ViT-B-32|laion2b_s34b_b79k@"
    "1a25a446712ba5ee05982a381eed697ef9b435cf|rgb|"
    "resize-shortest-224-bicubic-antialias|center-crop-224|"
    "mean-0.48145466,0.4578275,0.40821073|"
    "std-0.26862954,0.26130258,0.27577711|tensor-fp32"
)


class OpenClipModelError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class OpenClipModelSpec:
    weight_path: Path
    device: Literal["mps", "cpu"] = "mps"
    model_name: str = LOCKED_MODEL_NAME
    pretrained_tag: str = LOCKED_PRETRAINED_TAG
    revision: str = LOCKED_REVISION
    preprocessing_version: str = LOCKED_PREPROCESS_VERSION
    vector_dimension: int = LOCKED_VECTOR_DIMENSION

    def validate_static_contract(self) -> None:
        expected = (
            ("model_name", self.model_name, LOCKED_MODEL_NAME),
            (
                "pretrained_tag",
                self.pretrained_tag,
                LOCKED_PRETRAINED_TAG,
            ),
            ("model_revision", self.revision, LOCKED_REVISION),
            (
                "preprocessing_version",
                self.preprocessing_version,
                LOCKED_PREPROCESS_VERSION,
            ),
            (
                "vector_dimension",
                self.vector_dimension,
                LOCKED_VECTOR_DIMENSION,
            ),
        )
        for label, actual, locked in expected:
            if actual != locked:
                raise OpenClipModelError(f"{label}_drift")
        if self.device not in ("mps", "cpu"):
            raise OpenClipModelError("device_not_allowed")


class OpenClipImageEncoder:
    def __init__(self, spec: OpenClipModelSpec) -> None:
        spec.validate_static_contract()
        with _validated_weight_snapshot(spec.weight_path) as load_path:
            _validate_safetensors_metadata(load_path)
            if spec.device == "mps" and not _mps_is_built_and_available():
                raise OpenClipModelError("mps_unavailable")
            try:
                model, preprocess = _load_locked_runtime(spec, load_path)
            except OpenClipModelError:
                raise
            except Exception as exc:
                raise OpenClipModelError("model_load_failed") from exc
        _validate_loaded_model(model, spec)
        self._spec = spec
        self._model = model.eval()
        self._preprocess = preprocess
        self._model_lock = ApprovedImageModelLock(
            approval_id=LOCKED_APPROVAL_ID,
            model_name=LOCKED_ARTIFACT_MODEL_NAME,
            weights_sha256=LOCKED_WEIGHT_SHA256,
            preprocessing_version=LOCKED_PREPROCESS_VERSION,
            vector_dimension=LOCKED_VECTOR_DIMENSION,
        )

    @property
    def model_lock(self) -> ApprovedImageModelLock:
        return self._model_lock

    def encode_paths(
        self,
        paths: Sequence[Path],
        *,
        batch_size: int,
    ) -> np.ndarray:
        if not paths:
            raise OpenClipModelError("image_batch_empty")
        if batch_size < 1:
            raise OpenClipModelError("batch_size_invalid")
        vectors: list[np.ndarray] = []
        for offset in range(0, len(paths), batch_size):
            tensors = [
                self._preprocess(_decode_image_path(path))
                for path in paths[offset : offset + batch_size]
            ]
            vectors.append(self._encode_tensors(tensors))
        return np.ascontiguousarray(
            np.concatenate(vectors, axis=0),
            dtype=np.dtype("<f4"),
        )

    def encode_bytes(self, content: bytes) -> np.ndarray:
        image = _decode_image_bytes(content)
        return self._encode_tensors([self._preprocess(image)])[0]

    def encode_contents(
        self,
        contents: Sequence[bytes],
        *,
        batch_size: int,
    ) -> np.ndarray:
        if not contents:
            raise OpenClipModelError("image_batch_empty")
        if batch_size < 1:
            raise OpenClipModelError("batch_size_invalid")
        vectors: list[np.ndarray] = []
        for offset in range(0, len(contents), batch_size):
            tensors = [
                self._preprocess(_decode_image_bytes(content))
                for content in contents[offset : offset + batch_size]
            ]
            vectors.append(self._encode_tensors(tensors))
        return np.ascontiguousarray(
            np.concatenate(vectors, axis=0),
            dtype=np.dtype("<f4"),
        )

    def _encode_tensors(self, tensors: Sequence[Any]) -> np.ndarray:
        try:
            import torch

            batch = torch.stack(tuple(tensors)).to(
                self._spec.device,
                dtype=torch.float32,
            )
            with image_inference_slot():
                with torch.inference_mode():
                    output = self._model.encode_image(batch)
            if (
                output.ndim != 2
                or output.shape[1] != LOCKED_VECTOR_DIMENSION
                or output.shape[0] != len(tensors)
            ):
                raise OpenClipModelError("model_output_dimension_drift")
            output = output.float()
            if not bool(torch.isfinite(output).all().item()):
                raise OpenClipModelError("model_output_nonfinite")
            norms = torch.linalg.vector_norm(output, dim=1, keepdim=True)
            if bool((norms <= 0).any().item()):
                raise OpenClipModelError("model_output_zero_norm")
            normalized = output / norms
            return np.ascontiguousarray(
                normalized.cpu().numpy(),
                dtype=np.dtype("<f4"),
            )
        except OpenClipModelError:
            raise
        except Exception as exc:
            raise OpenClipModelError("model_inference_failed") from exc


class DeferredOpenClipImageEncoder:
    """Keep the approved model identity fixed while loading weights on use."""

    def __init__(self, spec: OpenClipModelSpec) -> None:
        spec.validate_static_contract()
        self._spec = spec
        self._model_lock = ApprovedImageModelLock(
            approval_id=LOCKED_APPROVAL_ID,
            model_name=LOCKED_ARTIFACT_MODEL_NAME,
            weights_sha256=LOCKED_WEIGHT_SHA256,
            preprocessing_version=LOCKED_PREPROCESS_VERSION,
            vector_dimension=LOCKED_VECTOR_DIMENSION,
        )
        self._encoder: OpenClipImageEncoder | None = None
        self._failure_code: str | None = None
        self._lock = RLock()

    @property
    def model_lock(self) -> ApprovedImageModelLock:
        return self._model_lock

    def ensure_ready(self) -> None:
        self._loaded_encoder()

    def encode_paths(
        self,
        paths: Sequence[Path],
        *,
        batch_size: int,
    ) -> np.ndarray:
        return self._loaded_encoder().encode_paths(
            paths,
            batch_size=batch_size,
        )

    def encode_bytes(self, content: bytes) -> np.ndarray:
        return self._loaded_encoder().encode_bytes(content)

    def encode_contents(
        self,
        contents: Sequence[bytes],
        *,
        batch_size: int,
    ) -> np.ndarray:
        return self._loaded_encoder().encode_contents(
            contents,
            batch_size=batch_size,
        )

    def _loaded_encoder(self) -> OpenClipImageEncoder:
        if self._encoder is not None:
            return self._encoder
        if self._failure_code is not None:
            raise OpenClipModelError(self._failure_code)
        with self._lock:
            if self._encoder is not None:
                return self._encoder
            if self._failure_code is not None:
                raise OpenClipModelError(self._failure_code)
            try:
                encoder = OpenClipImageEncoder(self._spec)
            except OpenClipModelError as exc:
                self._failure_code = exc.code
                raise
            except Exception as exc:
                self._failure_code = "model_load_failed"
                raise OpenClipModelError("model_load_failed") from exc
            self._encoder = encoder
            return encoder


@contextmanager
def _validated_weight_snapshot(weight_path: Path) -> Iterator[Path]:
    if weight_path.suffix != ".safetensors":
        raise OpenClipModelError("weight_format_prohibited")
    try:
        resolved = weight_path.resolve(strict=True)
    except OSError as exc:
        raise OpenClipModelError("weight_unavailable") from exc
    try:
        with tempfile.TemporaryDirectory(
            prefix="xiaoro-openclip-weight-"
        ) as directory:
            snapshot = Path(directory) / "open_clip_model.safetensors"
            source_descriptor = _open_weight_source(resolved)
            try:
                snapshot_descriptor = _create_private_snapshot(snapshot)
                try:
                    observed_size, observed_sha256 = (
                        _copy_weight_to_snapshot(
                            source_descriptor,
                            snapshot_descriptor,
                        )
                    )
                finally:
                    _close_descriptor(
                        snapshot_descriptor,
                        code="weight_snapshot_failed",
                    )
            finally:
                _close_descriptor(
                    source_descriptor,
                    code="weight_unavailable",
                )
            if observed_size != LOCKED_WEIGHT_BYTES:
                raise OpenClipModelError("weight_size_drift")
            if observed_sha256 != LOCKED_WEIGHT_SHA256:
                raise OpenClipModelError("weight_sha_drift")
            yield snapshot
    except OpenClipModelError:
        raise
    except OSError as exc:
        raise OpenClipModelError("weight_snapshot_failed") from exc


def _open_weight_source(resolved: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(resolved, flags)
        metadata = os.fstat(descriptor)
    except OSError as exc:
        if "descriptor" in locals():
            os.close(descriptor)
        raise OpenClipModelError("weight_unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode):
        os.close(descriptor)
        raise OpenClipModelError("weight_not_regular")
    if metadata.st_size != LOCKED_WEIGHT_BYTES:
        os.close(descriptor)
        raise OpenClipModelError("weight_size_drift")
    return descriptor


def _create_private_snapshot(snapshot: Path) -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(snapshot, flags, 0o600)
        os.fchmod(descriptor, 0o600)
        return descriptor
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise OpenClipModelError("weight_snapshot_failed") from exc


def _copy_weight_to_snapshot(
    source_descriptor: int,
    snapshot_descriptor: int,
) -> tuple[int, str]:
    digest = hashlib.sha256()
    observed_size = 0
    while True:
        try:
            chunk = os.read(source_descriptor, 1024 * 1024)
        except OSError as exc:
            raise OpenClipModelError("weight_unavailable") from exc
        if not chunk:
            break
        digest.update(chunk)
        observed_size += len(chunk)
        remaining = memoryview(chunk)
        while remaining:
            try:
                written = os.write(snapshot_descriptor, remaining)
            except OSError as exc:
                raise OpenClipModelError(
                    "weight_snapshot_failed"
                ) from exc
            if written < 1:
                raise OpenClipModelError("weight_snapshot_failed")
            remaining = remaining[written:]
    return observed_size, digest.hexdigest()


def _close_descriptor(descriptor: int, *, code: str) -> None:
    try:
        os.close(descriptor)
    except OSError as exc:
        raise OpenClipModelError(code) from exc


def _validate_safetensors_metadata(weight_path: Path) -> None:
    try:
        from safetensors import safe_open

        with safe_open(
            weight_path,
            framework="pt",
            device="cpu",
        ) as tensors:
            if tensors.metadata() != {"format": "pt"}:
                raise OpenClipModelError("weight_metadata_drift")
            keys = tensors.keys()
            if len(keys) != 302:
                raise OpenClipModelError("weight_tensor_count_drift")
            if tensors.get_slice("visual.proj").get_shape() != [768, 512]:
                raise OpenClipModelError("weight_projection_drift")
    except OpenClipModelError:
        raise
    except Exception as exc:
        raise OpenClipModelError("weight_safetensors_invalid") from exc


def _mps_is_built_and_available() -> bool:
    try:
        import torch

        return bool(
            torch.backends.mps.is_built()
            and torch.backends.mps.is_available()
        )
    except Exception:
        return False


def _load_locked_runtime(
    spec: OpenClipModelSpec,
    weight_path: Path,
) -> tuple[Any, Any]:
    try:
        if importlib_metadata.version("open_clip_torch") != "3.3.0":
            raise OpenClipModelError("openclip_version_drift")
        import open_clip

        model, _, preprocess = open_clip.create_model_and_transforms(
            spec.model_name,
            pretrained=str(weight_path),
            precision="fp32",
            device=spec.device,
            force_image_size=224,
            image_mean=(0.48145466, 0.4578275, 0.40821073),
            image_std=(0.26862954, 0.26130258, 0.27577711),
            image_interpolation="bicubic",
            image_resize_mode="shortest",
            weights_only=True,
        )
        _validate_preprocess(preprocess)
        return model, preprocess
    except OpenClipModelError:
        raise
    except Exception as exc:
        raise OpenClipModelError("model_load_failed") from exc


def _validate_preprocess(preprocess: Any) -> None:
    transforms = tuple(getattr(preprocess, "transforms", ()))
    names = tuple(type(transform).__name__ for transform in transforms)
    if names != (
        "Resize",
        "CenterCrop",
        "MaybeConvertMode",
        "MaybeToTensor",
        "Normalize",
    ):
        raise OpenClipModelError("preprocess_transform_drift")
    resize, crop, convert, _, normalize = transforms
    interpolation = getattr(resize, "interpolation", None)
    if (
        getattr(resize, "size", None) != 224
        or str(interpolation).lower().split(".")[-1] != "bicubic"
        or getattr(resize, "antialias", None) is not True
        or tuple(getattr(crop, "size", ())) != (224, 224)
        or getattr(convert, "mode", None) != "RGB"
        or tuple(getattr(normalize, "mean", ()))
        != (0.48145466, 0.4578275, 0.40821073)
        or tuple(getattr(normalize, "std", ()))
        != (0.26862954, 0.26130258, 0.27577711)
    ):
        raise OpenClipModelError("preprocess_parameter_drift")


def _validate_loaded_model(model: Any, spec: OpenClipModelSpec) -> None:
    try:
        import torch

        output_dim = model.visual.output_dim
        image_size = tuple(model.visual.image_size)
        parameter_dtype = next(model.parameters()).dtype
    except Exception as exc:
        raise OpenClipModelError("model_structure_drift") from exc
    if output_dim != spec.vector_dimension:
        raise OpenClipModelError("model_output_dimension_drift")
    if image_size != (224, 224):
        raise OpenClipModelError("model_input_dimension_drift")
    if parameter_dtype is not torch.float32:
        raise OpenClipModelError("model_dtype_drift")


def _decode_image_path(path: Path) -> Image.Image:
    try:
        with Image.open(path) as image:
            image.load()
            return image.convert("RGB")
    except (OSError, UnidentifiedImageError) as exc:
        raise OpenClipModelError("image_decode_failed") from exc


def _decode_image_bytes(content: bytes) -> Image.Image:
    if not content:
        raise OpenClipModelError("image_decode_failed")
    try:
        with Image.open(BytesIO(content)) as image:
            image.load()
            return image.convert("RGB")
    except (OSError, UnidentifiedImageError) as exc:
        raise OpenClipModelError("image_decode_failed") from exc
