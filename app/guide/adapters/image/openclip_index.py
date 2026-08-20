"""Locked OpenCLIP image-index adapter."""

from app.guide.adapters.image.local_numpy_index import (
    ImageIndexAcceptanceReport,
    LocalNumpyImageIndex,
    OpenClipNumpyArtifactBuilder,
    controlled_reencode,
    verify_image_index_acceptance,
)
from app.guide.adapters.image.openclip_adapter import (
    OpenClipImageEncoder,
    OpenClipModelError,
    OpenClipModelSpec,
)

__all__ = [
    "ImageIndexAcceptanceReport",
    "LocalNumpyImageIndex",
    "OpenClipImageEncoder",
    "OpenClipModelError",
    "OpenClipModelSpec",
    "OpenClipNumpyArtifactBuilder",
    "controlled_reencode",
    "verify_image_index_acceptance",
]
