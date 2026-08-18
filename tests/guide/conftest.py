from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_image_upload_rate_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "XIAORO_IMAGE_UPLOAD_RATE_STATE_PATH",
        str(
            tmp_path
            / "image-upload-rate-state"
            / "image_upload_rate.sqlite3"
        ),
    )
