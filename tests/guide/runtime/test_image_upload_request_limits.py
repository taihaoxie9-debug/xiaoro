from __future__ import annotations

import asyncio
import json
import multiprocessing
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import os
from pathlib import Path
import shutil
import sys
from threading import Event, Lock
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.guide.adapters.image.inference_limiter import image_inference_slot
from app.guide.adapters.image.safe_image_input import MAX_BATCH_BYTES
from app.guide.adapters.state.in_memory_image_bundle_state import (
    InMemoryImageBundleState,
)
from app.guide.application.image_bundle_service import ImageBundleService
from app.guide_runtime.app import create_app
from app.guide_runtime import request_limits


REQUEST_BODY_LIMIT = MAX_BATCH_BYTES + 64 * 1024
PUBLIC_LIMIT_ERROR = {
    "detail": {
        "code": "image_upload_request_too_large",
        "message": "图片上传请求超过安全限制。",
        "ordinal": None,
    }
}
PUBLIC_BUSY_ERROR = {
    "detail": {
        "code": "image_upload_busy",
        "message": "图片上传繁忙，请稍后重试。",
        "ordinal": None,
    }
}
PUBLIC_RATE_ERROR = {
    "detail": {
        "code": "image_upload_rate_limited",
        "message": "图片上传过于频繁，请稍后重试。",
        "ordinal": None,
    }
}
PUBLIC_UNAVAILABLE_ERROR = {
    "detail": {
        "code": "image_upload_unavailable",
        "message": "图片上传服务暂时不可用，请稍后重试。",
        "ordinal": None,
    }
}


class RecordingBundleService:
    def __init__(self) -> None:
        self.create_calls = 0

    def create(self, **kwargs: Any):
        self.create_calls += 1
        raise AssertionError("request limit must run before bundle creation")

    public_error_for_safe_input = staticmethod(
        ImageBundleService.public_error_for_safe_input
    )


class BlockingBundleService:
    def __init__(self) -> None:
        self._delegate = ImageBundleService(
            state=InMemoryImageBundleState(max_bundles=8)
        )
        self._lock = Lock()
        self.release = Event()
        self.active = 0
        self.maximum_active = 0
        self.create_calls = 0

    def create(self, **kwargs: Any):
        with self._lock:
            self.active += 1
            self.create_calls += 1
            self.maximum_active = max(self.maximum_active, self.active)
        try:
            self.release.wait(timeout=3)
            return self._delegate.create(**kwargs)
        finally:
            with self._lock:
                self.active -= 1

    public_error_for_safe_input = staticmethod(
        ImageBundleService.public_error_for_safe_input
    )


class CountingBundleService:
    def __init__(self) -> None:
        self._delegate = ImageBundleService(
            state=InMemoryImageBundleState(max_bundles=32)
        )
        self.create_calls = 0

    def create(self, **kwargs: Any):
        self.create_calls += 1
        return self._delegate.create(**kwargs)

    public_error_for_safe_input = staticmethod(
        ImageBundleService.public_error_for_safe_input
    )


def _jpeg() -> bytes:
    image = Image.new("RGB", (4, 3), color=(23, 67, 101))
    output = BytesIO()
    image.save(output, format="JPEG")
    image.close()
    return output.getvalue()


def _multiprocess_rate_uploads(
    rate_state_path: str,
    lock_dir: str,
    request_count: int,
    start,
    result_queue,
    window_seconds: float = (
        request_limits.IMAGE_UPLOAD_RATE_WINDOW_SECONDS
    ),
) -> None:
    request_limits.IMAGE_UPLOAD_RATE_WINDOW_SECONDS = window_seconds
    request_limits.IMAGE_UPLOAD_RATE_ENTRY_TTL_SECONDS = (
        window_seconds * 2
    )
    os.environ[
        request_limits.IMAGE_UPLOAD_RATE_STATE_PATH_ENV
    ] = rate_state_path
    os.environ[
        request_limits.IMAGE_UPLOAD_LOCK_DIR_ENV
    ] = lock_dir
    service = CountingBundleService()
    client = TestClient(
        create_app(
            image_bundle_service=service,
        )
    )
    if not start.wait(timeout=10):
        raise RuntimeError("rate-limit process start timed out")

    results = []
    content = _jpeg()
    for index in range(request_count):
        response = client.post(
            "/api/v1/chat/image-bundles",
            data={
                "session_id": (
                    f"rate-process-{os.getpid()}-{index}"
                )
            },
            files=[
                (
                    "images",
                    ("product.jpg", content, "image/jpeg"),
                )
            ],
        )
        results.append(
            (
                response.status_code,
                response.json().get("detail", {}).get("code"),
            )
        )
    result_queue.put((results, service.create_calls))


def _multipart(
    *,
    boundary: str,
    files: Iterable[tuple[str, bytes, Iterable[tuple[str, str]]]],
    fields: Iterable[tuple[str, str]] = (("session_id", "upload-owner"),),
) -> bytes:
    body = bytearray()
    for name, value in fields:
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            (
                f'Content-Disposition: form-data; name="{name}"'
                "\r\n\r\n"
            ).encode()
        )
        body.extend(value.encode())
        body.extend(b"\r\n")
    for filename, content, extra_headers in files:
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            (
                "Content-Disposition: form-data; "
                f'name="images"; filename="{filename}"\r\n'
                "Content-Type: image/jpeg\r\n"
            ).encode()
        )
        for header_name, header_value in extra_headers:
            body.extend(f"{header_name}: {header_value}\r\n".encode())
        body.extend(b"\r\n")
        body.extend(content)
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    return bytes(body)


async def _asgi_post(
    app,
    *,
    body: bytes,
    headers: list[tuple[bytes, bytes]],
    chunk_size: int = 64 * 1024,
) -> tuple[int, dict[str, Any], int, int]:
    chunks = [
        body[offset:offset + chunk_size]
        for offset in range(0, len(body), chunk_size)
    ]
    receive_calls = 0
    consumed_bytes = 0
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        nonlocal receive_calls, consumed_bytes
        index = receive_calls
        receive_calls += 1
        if index >= len(chunks):
            return {
                "type": "http.request",
                "body": b"",
                "more_body": False,
            }
        chunk = chunks[index]
        consumed_bytes += len(chunk)
        return {
            "type": "http.request",
            "body": chunk,
            "more_body": index < len(chunks) - 1,
        }

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/chat/image-bundles",
        "raw_path": b"/api/v1/chat/image-bundles",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 43210),
        "server": ("testserver", 80),
        "root_path": "",
        "app": app,
    }
    await app(scope, receive, send)
    status_code = next(
        message["status"]
        for message in sent
        if message["type"] == "http.response.start"
    )
    response_body = b"".join(
        message.get("body", b"")
        for message in sent
        if message["type"] == "http.response.body"
    )
    return (
        status_code,
        json.loads(response_body),
        receive_calls,
        consumed_bytes,
    )


def test_declared_oversized_multipart_is_rejected_before_receive() -> None:
    service = RecordingBundleService()
    app = create_app(
        image_bundle_service=service,
    )
    boundary = "declared-limit"
    body = _multipart(
        boundary=boundary,
        files=[("product.jpg", _jpeg(), ())],
    )

    status_code, payload, receive_calls, consumed_bytes = asyncio.run(
        _asgi_post(
            app,
            body=body,
            headers=[
                (
                    b"content-type",
                    f"multipart/form-data; boundary={boundary}".encode(),
                ),
                (
                    b"content-length",
                    str(REQUEST_BODY_LIMIT + 1).encode(),
                ),
            ],
        )
    )

    assert status_code == 413
    assert payload == PUBLIC_LIMIT_ERROR
    assert receive_calls == 0
    assert consumed_bytes == 0
    assert service.create_calls == 0


def test_chunked_oversized_multipart_stops_before_full_stream() -> None:
    service = RecordingBundleService()
    app = create_app(
        image_bundle_service=service,
    )
    boundary = "chunked-limit"
    body = _multipart(
        boundary=boundary,
        files=[
            (
                "oversized.jpg",
                b"\xff\xd8\xff" + b"x" * (REQUEST_BODY_LIMIT + 1024 * 1024),
                (),
            )
        ],
    )

    status_code, payload, receive_calls, consumed_bytes = asyncio.run(
        _asgi_post(
            app,
            body=body,
            headers=[
                (
                    b"content-type",
                    f"multipart/form-data; boundary={boundary}".encode(),
                ),
                (b"transfer-encoding", b"chunked"),
            ],
        )
    )

    assert status_code == 413
    assert payload == PUBLIC_LIMIT_ERROR
    assert consumed_bytes <= REQUEST_BODY_LIMIT + 64 * 1024
    assert consumed_bytes < len(body)
    assert receive_calls < (len(body) + 64 * 1024 - 1) // (64 * 1024)
    assert service.create_calls == 0


def test_chunked_limit_closes_all_spooled_multipart_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import starlette.formparsers as formparsers

    created_files = []
    real_spooled_file = formparsers.SpooledTemporaryFile

    def recording_spooled_file(*args: Any, **kwargs: Any):
        file = real_spooled_file(*args, **kwargs)
        created_files.append(file)
        return file

    monkeypatch.setattr(
        formparsers,
        "SpooledTemporaryFile",
        recording_spooled_file,
    )
    boundary = "spooled-file-limit"
    body = _multipart(
        boundary=boundary,
        files=[
            (
                "oversized.jpg",
                b"\xff\xd8\xff" + b"x" * (REQUEST_BODY_LIMIT + 1024),
                (),
            )
        ],
    )

    status_code, _, _, _ = asyncio.run(
        _asgi_post(
            create_app(),
            body=body,
            headers=[
                (
                    b"content-type",
                    f"multipart/form-data; boundary={boundary}".encode(),
                ),
                (b"transfer-encoding", b"chunked"),
            ],
        )
    )

    assert status_code == 413
    assert created_files
    assert all(file.closed for file in created_files)


@pytest.mark.parametrize(
    ("files", "fields"),
    [
        (
            [
                (f"product-{index}.jpg", _jpeg(), ())
                for index in range(5)
            ],
            [("session_id", "file-count-owner")],
        ),
        (
            [("product.jpg", _jpeg(), ())],
            [
                ("session_id", "field-count-owner"),
                ("unexpected", "not-allowed"),
            ],
        ),
        (
            [("x" * 256 + ".jpg", _jpeg(), ())],
            [("session_id", "filename-owner")],
        ),
        (
            [("product.jpg", _jpeg(), (("X-Long", "x" * 1025),))],
            [("session_id", "header-owner")],
        ),
    ],
)
def test_multipart_structure_limits_are_public_413_errors(
    files: list[tuple[str, bytes, Iterable[tuple[str, str]]]],
    fields: list[tuple[str, str]],
) -> None:
    boundary = "structure-limit"
    response = TestClient(create_app()).post(
        "/api/v1/chat/image-bundles",
        content=_multipart(
            boundary=boundary,
            files=files,
            fields=fields,
        ),
        headers={
            "content-type": (
                f"multipart/form-data; boundary={boundary}"
            )
        },
    )

    assert response.status_code == 413
    assert response.json() == PUBLIC_LIMIT_ERROR


def test_upload_rate_limit_runs_before_bundle_creation() -> None:
    service = CountingBundleService()
    app = create_app(
        image_bundle_service=service,
    )
    client = TestClient(app)
    content = _jpeg()

    for index in range(12):
        response = client.post(
            "/api/v1/chat/image-bundles",
            data={"session_id": f"rate-owner-{index}"},
            files=[
                (
                    "images",
                    ("product.jpg", content, "image/jpeg"),
                )
            ],
        )
        assert response.status_code == 201
        assert service.create_calls == index + 1

    limited = client.post(
        "/api/v1/chat/image-bundles",
        data={"session_id": "rate-owner-limited"},
        files=[
            (
                "images",
                ("product.jpg", content, "image/jpeg"),
            )
        ],
    )

    assert limited.status_code == 429
    assert limited.json() == PUBLIC_RATE_ERROR
    assert service.create_calls == 12


def test_upload_rate_limit_is_shared_by_two_real_worker_processes(
    tmp_path: Path,
) -> None:
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    queue = context.Queue()
    rate_state_path = str(
        tmp_path / "rate-state" / "image_upload_rate.sqlite3"
    )
    lock_dir = str(tmp_path / "upload-locks")
    processes = [
        context.Process(
            target=_multiprocess_rate_uploads,
            args=(rate_state_path, lock_dir, 12, start, queue),
        )
        for _ in range(2)
    ]

    try:
        for process in processes:
            process.start()
        start.set()
        worker_results = [queue.get(timeout=20) for _ in processes]
        for process in processes:
            process.join(timeout=20)
    finally:
        start.set()
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        queue.close()
        queue.join_thread()

    assert [process.exitcode for process in processes] == [0, 0]
    results = [
        result
        for worker_result, _ in worker_results
        for result in worker_result
    ]
    assert sum(status_code == 201 for status_code, _ in results) == 12
    assert sum(
        status_code == 429
        and code == "image_upload_rate_limited"
        for status_code, code in results
    ) == 12
    assert sum(create_calls for _, create_calls in worker_results) == 12


def test_upload_rate_limit_survives_real_worker_restarts(
    tmp_path: Path,
) -> None:
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    start.set()
    queue = context.Queue()
    rate_state_path = str(
        tmp_path / "restart-rate-state" / "image_upload_rate.sqlite3"
    )
    lock_dir = str(tmp_path / "restart-upload-locks")
    results = []
    exitcodes = []

    try:
        for request_count in (6, 6, 1):
            process = context.Process(
                target=_multiprocess_rate_uploads,
                args=(
                    rate_state_path,
                    lock_dir,
                    request_count,
                    start,
                    queue,
                    1_000_000_000_000.0,
                ),
            )
            process.start()
            worker_results, _ = queue.get(timeout=20)
            process.join(timeout=20)
            results.extend(worker_results)
            exitcodes.append(process.exitcode)
    finally:
        queue.close()
        queue.join_thread()

    assert exitcodes == [0, 0, 0]
    assert [status_code for status_code, _ in results[:12]] == [201] * 12
    assert results[12] == (429, "image_upload_rate_limited")


@pytest.mark.parametrize(
    "configured_path",
    [
        "relative-rate-state.sqlite3",
        "",
    ],
)
def test_invalid_rate_state_configuration_returns_controlled_503(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    configured_path: str,
) -> None:
    monkeypatch.setenv(
        request_limits.IMAGE_UPLOAD_RATE_STATE_PATH_ENV,
        configured_path,
    )
    monkeypatch.setenv(
        request_limits.IMAGE_UPLOAD_LOCK_DIR_ENV,
        str(tmp_path / "upload-locks"),
    )
    service = CountingBundleService()

    response = TestClient(
        create_app(
            image_bundle_service=service,
        ),
        raise_server_exceptions=False,
    ).post(
        "/api/v1/chat/image-bundles",
        data={"session_id": "invalid-rate-state"},
        files=[
            (
                "images",
                ("product.jpg", _jpeg(), "image/jpeg"),
            )
        ],
    )

    assert response.status_code == 503
    assert response.json() == PUBLIC_UNAVAILABLE_ERROR
    assert service.create_calls == 0


def test_corrupt_rate_state_database_returns_controlled_503(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_directory = tmp_path / "corrupt-rate-state"
    state_directory.mkdir(mode=0o700)
    database_path = state_directory / "image_upload_rate.sqlite3"
    database_path.write_text("not a sqlite database", encoding="utf-8")
    database_path.chmod(0o600)
    monkeypatch.setenv(
        request_limits.IMAGE_UPLOAD_RATE_STATE_PATH_ENV,
        str(database_path),
    )
    monkeypatch.setenv(
        request_limits.IMAGE_UPLOAD_LOCK_DIR_ENV,
        str(tmp_path / "upload-locks"),
    )
    service = CountingBundleService()

    response = TestClient(
        create_app(
            image_bundle_service=service,
        ),
        raise_server_exceptions=False,
    ).post(
        "/api/v1/chat/image-bundles",
        data={"session_id": "corrupt-rate-state"},
        files=[
            (
                "images",
                ("product.jpg", _jpeg(), "image/jpeg"),
            )
        ],
    )

    assert response.status_code == 503
    assert response.json() == PUBLIC_UNAVAILABLE_ERROR
    assert "not a sqlite database" not in response.text
    assert service.create_calls == 0


def test_default_upload_lock_directory_canonicalizes_temp_root_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        request_limits.IMAGE_UPLOAD_LOCK_DIR_ENV,
        raising=False,
    )
    real_temp_root = tmp_path / "real-temp"
    real_temp_root.mkdir(mode=0o700)
    temp_root_alias = tmp_path / "temp-alias"
    temp_root_alias.symlink_to(real_temp_root, target_is_directory=True)
    monkeypatch.setattr(
        request_limits.tempfile,
        "gettempdir",
        lambda: str(temp_root_alias),
    )

    response = TestClient(
        create_app(
            image_bundle_service=CountingBundleService(),
        )
    ).post(
        "/api/v1/chat/image-bundles",
        data={"session_id": "default-lock-root-alias"},
        files=[
            (
                "images",
                ("product.jpg", _jpeg(), "image/jpeg"),
            )
        ],
    )

    assert response.status_code == 201
    assert (
        real_temp_root / f"xiaoro-image-upload-{os.getuid()}"
    ).is_dir()


@pytest.mark.skipif(
    sys.platform != "darwin",
    reason="macOS exposes /tmp as a trusted /private/tmp alias",
)
def test_macos_tmp_upload_lock_directory_is_canonicalized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured_lock_dir = (
        Path("/tmp")
        / f"xiaoro-upload-test-{os.getpid()}-{time.time_ns()}"
    )
    canonical_lock_dir = configured_lock_dir.resolve(strict=False)
    monkeypatch.setenv(
        request_limits.IMAGE_UPLOAD_LOCK_DIR_ENV,
        str(configured_lock_dir),
    )

    try:
        response = TestClient(
            create_app(
                image_bundle_service=CountingBundleService(),
            )
        ).post(
            "/api/v1/chat/image-bundles",
            data={"session_id": "macos-tmp-lock-alias"},
            files=[
                (
                    "images",
                    ("product.jpg", _jpeg(), "image/jpeg"),
                )
            ],
        )
    finally:
        shutil.rmtree(canonical_lock_dir, ignore_errors=True)

    assert response.status_code == 201


def test_unsafe_configured_upload_lock_directory_returns_controlled_503(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unsafe_lock_dir = tmp_path / "unsafe-upload-lock"
    unsafe_lock_dir.mkdir(mode=0o700)
    unsafe_lock_dir.chmod(0o755)
    monkeypatch.setenv(
        request_limits.IMAGE_UPLOAD_LOCK_DIR_ENV,
        str(unsafe_lock_dir),
    )
    service = CountingBundleService()

    response = TestClient(
        create_app(
            image_bundle_service=service,
        ),
        raise_server_exceptions=False,
    ).post(
        "/api/v1/chat/image-bundles",
        data={"session_id": "unsafe-lock-owner"},
        files=[
            (
                "images",
                ("product.jpg", _jpeg(), "image/jpeg"),
            )
        ],
    )

    assert response.status_code == 503
    assert response.json() == PUBLIC_UNAVAILABLE_ERROR
    assert service.create_calls == 0


def test_unresolvable_upload_lock_directory_returns_controlled_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        request_limits.IMAGE_UPLOAD_LOCK_DIR_ENV,
        "~xiaoro-user-that-must-not-exist/upload-locks",
    )
    service = CountingBundleService()

    response = TestClient(
        create_app(
            image_bundle_service=service,
        ),
        raise_server_exceptions=False,
    ).post(
        "/api/v1/chat/image-bundles",
        data={"session_id": "unresolvable-lock-owner"},
        files=[
            (
                "images",
                ("product.jpg", _jpeg(), "image/jpeg"),
            )
        ],
    )

    assert response.status_code == 503
    assert response.json() == PUBLIC_UNAVAILABLE_ERROR
    assert service.create_calls == 0


def test_unavailable_default_temp_directory_returns_controlled_503(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.guide_runtime.composition import (
        build_consultation_vertical_runtime,
    )

    monkeypatch.delenv(
        request_limits.IMAGE_UPLOAD_LOCK_DIR_ENV,
        raising=False,
    )

    def unavailable_temp_directory() -> str:
        raise FileNotFoundError("private temp directory detail")

    monkeypatch.setattr(
        request_limits.tempfile,
        "gettempdir",
        unavailable_temp_directory,
    )
    service = CountingBundleService()
    consultation_runtime = build_consultation_vertical_runtime(
        state_dir=tmp_path / "conversation-state",
        image_bundle_service=service,
    )

    response = TestClient(
        create_app(
            consultation_runtime=consultation_runtime,
            image_bundle_service=service,
        ),
        raise_server_exceptions=False,
    ).post(
        "/api/v1/chat/image-bundles",
        data={"session_id": "missing-default-temp-owner"},
        files=[
            (
                "images",
                ("product.jpg", _jpeg(), "image/jpeg"),
            )
        ],
    )

    assert response.status_code == 503
    assert response.json() == PUBLIC_UNAVAILABLE_ERROR
    assert "private temp directory detail" not in response.text
    assert service.create_calls == 0


def test_upload_admission_is_independent_from_saturated_inference_domain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inference_lock_dir = tmp_path / "inference-slots"
    monkeypatch.setenv(
        request_limits.IMAGE_UPLOAD_LOCK_DIR_ENV,
        str(tmp_path / "upload-slots"),
    )
    service = CountingBundleService()
    client = TestClient(
        create_app(
            image_bundle_service=service,
        )
    )

    with image_inference_slot(lock_dir=inference_lock_dir):
        with image_inference_slot(lock_dir=inference_lock_dir):
            response = client.post(
                "/api/v1/chat/image-bundles",
                data={"session_id": "independent-upload-domain"},
                files=[
                    (
                        "images",
                        ("product.jpg", _jpeg(), "image/jpeg"),
                    )
                ],
            )

    assert response.status_code == 201
    assert service.create_calls == 1


def test_upload_concurrency_is_host_wide_and_rejects_before_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "XIAORO_IMAGE_UPLOAD_LOCK_DIR",
        str(tmp_path / "upload-slots"),
    )
    service = BlockingBundleService()
    app = create_app(
        image_bundle_service=service,
    )
    content = _jpeg()

    def upload(index: int):
        return TestClient(app).post(
            "/api/v1/chat/image-bundles",
            data={"session_id": f"concurrent-owner-{index}"},
            files=[
                (
                    "images",
                    (f"product-{index}.jpg", content, "image/jpeg"),
                )
            ],
        )

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(upload, index) for index in range(3)]
        deadline = time.monotonic() + 2
        while service.active < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        deadline = time.monotonic() + 2
        while (
            not any(future.done() for future in futures)
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        service.release.set()
        responses = [future.result(timeout=3) for future in futures]

    statuses = sorted(response.status_code for response in responses)
    assert statuses == [201, 201, 429]
    rejected = next(
        response
        for response in responses
        if response.status_code == 429
    )
    assert rejected.json() == PUBLIC_BUSY_ERROR
    assert service.maximum_active == 2
    assert service.create_calls == 2
