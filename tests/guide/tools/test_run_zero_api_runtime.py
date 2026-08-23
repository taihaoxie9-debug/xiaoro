from __future__ import annotations

import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from typing import Callable

import pytest

import tools.guide_gates.run_zero_api_runtime as zero_runtime
from tools.guide_gates.zero_api_network_guard import (
    ZeroApiNetworkViolation,
)


_HEAD = "a" * 40


def _payload_sha256(root: Path, paths: list[str]) -> str:
    digest = sha256()
    for relative in sorted(paths):
        content = (root / relative).read_bytes()
        encoded_path = relative.encode("utf-8")
        digest.update(str(len(encoded_path)).encode("ascii"))
        digest.update(b":")
        digest.update(encoded_path)
        digest.update(str(len(content)).encode("ascii"))
        digest.update(b":")
        digest.update(content)
    return digest.hexdigest()


def _candidate_manifest(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    protected = "app/protected.txt"
    (root / protected).parent.mkdir(parents=True)
    (root / protected).write_text("candidate\n", encoding="utf-8")
    git_dir = root / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text(f"{_HEAD}\n", encoding="ascii")
    payload_sha256 = _payload_sha256(root, [protected])
    manifest = root / "evidence" / "manifest.json"
    manifest.parent.mkdir()
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "guide-task11-candidate-manifest-v1",
                "plan_revision": "2026-08-23-task11-r5",
                "candidate_head": _HEAD,
                "source_paths": [protected],
                "test_paths": [],
                "tool_paths": [],
                "plan_paths": [],
                "fixture_paths": [],
                "deleted_paths": [],
                "excluded_paths": [],
                "protected_paths": [protected],
                "candidate_payload_sha256": payload_sha256,
                "protected_payload_sha256": payload_sha256,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return manifest


class _Server:
    def __init__(
        self,
        *,
        application: object,
        host: str,
        port: int,
        action: Callable[[], None] | None = None,
    ) -> None:
        self.application = application
        self.host = host
        self.port = port
        self.started = False
        self._action = action

    async def serve(self) -> None:
        self.started = True
        if self._action is not None:
            self._action()
        await asyncio.sleep(0)


def _run(
    tmp_path: Path,
    *,
    manifest: Path | None = None,
    host: str = "127.0.0.1",
    application_loader: Callable[[], object] = object,
    action: Callable[[], None] | None = None,
) -> tuple[dict[str, object], Path, Path]:
    candidate = manifest or _candidate_manifest(tmp_path)
    ready_file = tmp_path / "runtime-ready.json"
    network_report = tmp_path / "runtime-network.json"

    identity = zero_runtime.run_zero_api_runtime(
        manifest_path=candidate,
        host=host,
        port=8820,
        state_dir=tmp_path / "state",
        ready_file=ready_file,
        network_report=network_report,
        application_loader=application_loader,
        server_factory=lambda application, runtime_host, runtime_port: (
            _Server(
                application=application,
                host=runtime_host,
                port=runtime_port,
                action=action,
            )
        ),
    )
    return identity, ready_file, network_report


def test_runtime_installs_guard_before_loading_application_and_writes_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original_getaddrinfo = socket.getaddrinfo
    observed: dict[str, object] = {}
    monkeypatch.setenv("GUIDE_LLM_API_KEY", "must-not-reach-app")
    monkeypatch.setenv("GUIDE_COPY_LLM_API_KEY", "must-not-reach-app")

    def load_application() -> object:
        observed["guard_installed"] = (
            socket.getaddrinfo is not original_getaddrinfo
        )
        observed["provider_keys"] = (
            os.environ.get("GUIDE_LLM_API_KEY"),
            os.environ.get("GUIDE_COPY_LLM_API_KEY"),
        )
        observed["state_dir"] = os.environ.get(
            "XIAORO_GUIDE_STATE_DIR"
        )
        return object()

    manifest = _candidate_manifest(tmp_path)
    identity, ready_file, network_report = _run(
        tmp_path,
        manifest=manifest,
        application_loader=load_application,
    )

    assert observed == {
        "guard_installed": True,
        "provider_keys": (None, None),
        "state_dir": str((tmp_path / "state").resolve()),
    }
    assert os.environ["GUIDE_LLM_API_KEY"] == "must-not-reach-app"
    assert os.environ["GUIDE_COPY_LLM_API_KEY"] == "must-not-reach-app"
    assert identity == json.loads(ready_file.read_text(encoding="utf-8"))
    assert identity["schema_version"] == (
        "guide-zero-api-runtime-identity-v1"
    )
    assert identity["candidate_manifest_sha256"] == sha256(
        manifest.read_bytes()
    ).hexdigest()
    assert identity["plan_revision"] == "2026-08-23-task11-r5"
    assert identity["code_revision"] == _HEAD
    assert identity["protected_payload_sha256"] == (
        json.loads(manifest.read_text(encoding="utf-8"))[
            "protected_payload_sha256"
        ]
    )
    assert identity["process_identity"]["pid"] == os.getpid()
    assert identity["host"] == "127.0.0.1"
    assert identity["port"] == 8820
    assert len(identity["runtime_nonce"]) == 64
    assert zero_runtime.verify_runtime_identity(
        identity_path=ready_file,
        manifest_path=manifest,
        expected_host="127.0.0.1",
        expected_port=8820,
        expected_pid=os.getpid(),
    ) == identity

    report = json.loads(network_report.read_text(encoding="utf-8"))
    assert report["guard_active"] is True
    assert report["shutdown_finalized"] is True
    assert report["provider_call_count"] == 0
    assert report["outbound_network_attempt_count"] == 0
    assert report["process_creation_attempt_count"] == 0
    assert report["runtime_process_tree_non_loopback_attempt_count"] == 0
    assert report["passed"] is True
    assert not tuple(tmp_path.glob(".*.tmp"))


def test_runtime_rejects_non_loopback_bind_before_application_import(
    tmp_path: Path,
) -> None:
    loaded = False

    def load_application() -> object:
        nonlocal loaded
        loaded = True
        return object()

    with pytest.raises(
        zero_runtime.ZeroApiRuntimeError,
        match="loopback",
    ):
        _run(
            tmp_path,
            host="0.0.0.0",
            application_loader=load_application,
        )

    assert loaded is False
    assert not (tmp_path / "runtime-ready.json").exists()
    assert not (tmp_path / "runtime-network.json").exists()


def test_runtime_rejects_manifest_whose_code_revision_is_not_head(
    tmp_path: Path,
) -> None:
    manifest = _candidate_manifest(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["candidate_head"] = "b" * 40
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        zero_runtime.ZeroApiRuntimeError,
        match="candidate_head",
    ):
        _run(tmp_path, manifest=manifest)

    report = json.loads(
        (tmp_path / "runtime-network.json").read_text(encoding="utf-8")
    )
    assert report["passed"] is False
    assert report["runtime_started"] is False
    assert not (tmp_path / "runtime-ready.json").exists()


def test_runtime_identity_verifier_rejects_tampered_ready_file(
    tmp_path: Path,
) -> None:
    manifest = _candidate_manifest(tmp_path)
    _, ready_file, _ = _run(tmp_path, manifest=manifest)
    payload = json.loads(ready_file.read_text(encoding="utf-8"))
    payload["runtime_nonce"] = "0" * 64
    ready_file.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        zero_runtime.ZeroApiRuntimeError,
        match="runtime identity",
    ):
        zero_runtime.verify_runtime_identity(
            identity_path=ready_file,
            manifest_path=manifest,
            expected_host="127.0.0.1",
            expected_port=8820,
            expected_pid=os.getpid(),
        )


def test_runtime_measures_and_fails_on_non_loopback_attempt(
    tmp_path: Path,
) -> None:
    def attempt_outbound() -> None:
        with pytest.raises(ZeroApiNetworkViolation):
            socket.create_connection(("203.0.113.10", 443))

    with pytest.raises(
        zero_runtime.ZeroApiRuntimeError,
        match="network policy",
    ):
        _run(tmp_path, action=attempt_outbound)

    report = json.loads(
        (tmp_path / "runtime-network.json").read_text(encoding="utf-8")
    )
    assert report["passed"] is False
    assert report["outbound_network_attempt_count"] == 1
    assert report["runtime_process_tree_non_loopback_attempt_count"] == 1
    assert report["attempts"] == [
        {"kind": "socket.create_connection", "target": "203.0.113.10"}
    ]


def test_runtime_rejects_child_process_escape_and_reports_attempt(
    tmp_path: Path,
) -> None:
    def attempt_child() -> None:
        with pytest.raises(zero_runtime.ZeroApiRuntimeViolation):
            subprocess.run(
                [sys.executable, "-c", "pass"],
                check=True,
            )

    with pytest.raises(
        zero_runtime.ZeroApiRuntimeError,
        match="network policy",
    ):
        _run(tmp_path, action=attempt_child)

    report = json.loads(
        (tmp_path / "runtime-network.json").read_text(encoding="utf-8")
    )
    assert report["passed"] is False
    assert report["process_creation_attempt_count"] == 1
    assert report["process_creation_attempts"][0]["kind"] == (
        "subprocess.Popen"
    )
    subprocess.run(
        [sys.executable, "-c", "pass"],
        check=True,
    )


def test_runtime_finalizes_failed_startup_report_without_ready_identity(
    tmp_path: Path,
) -> None:
    def fail_to_load() -> object:
        raise RuntimeError("application failed")

    with pytest.raises(RuntimeError, match="application failed"):
        _run(tmp_path, application_loader=fail_to_load)

    assert not (tmp_path / "runtime-ready.json").exists()
    report = json.loads(
        (tmp_path / "runtime-network.json").read_text(encoding="utf-8")
    )
    assert report["guard_active"] is True
    assert report["runtime_started"] is False
    assert report["ready_identity_written"] is False
    assert report["shutdown_finalized"] is True
    assert report["passed"] is False
