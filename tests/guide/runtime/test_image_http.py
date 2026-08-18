import asyncio
import time

from app.guide_runtime.image_http import (
    create_image_bundle_from_uploads,
)


class _Upload:
    filename = "product.jpg"
    content_type = "image/jpeg"

    def __init__(self) -> None:
        self._returned = False
        self.closed = False

    async def read(self, size: int) -> bytes:
        if self._returned:
            return b""
        self._returned = True
        return b"safe-bounded-content"

    async def close(self) -> None:
        self.closed = True


class _SlowBundleService:
    def create(self, *, session_id, images):
        time.sleep(0.2)
        return object()


async def _exercise_upload_create_keeps_heartbeat_alive() -> None:
    timer_fired = asyncio.Event()
    asyncio.get_running_loop().call_later(0.05, timer_fired.set)
    await create_image_bundle_from_uploads(
        _SlowBundleService(),
        session_id="heartbeat-upload",
        uploads=[_Upload()],
    )
    assert timer_fired.is_set()


def test_upload_create_keeps_event_loop_heartbeat_alive() -> None:
    asyncio.run(_exercise_upload_create_keeps_heartbeat_alive())
