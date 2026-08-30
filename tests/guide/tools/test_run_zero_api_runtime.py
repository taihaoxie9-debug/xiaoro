from __future__ import annotations

import asyncio
import base64
from hashlib import sha256
import inspect
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
from typing import Callable

import pytest

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

import tools.guide_gates.run_zero_api_runtime as zero_runtime
from tools.guide_gates import attempt_ledger
from tools.guide_gates.runtime_auth import encode_runtime_private_key
from tools.guide_gates.zero_api_network_guard import (
    ZeroApiNetworkViolation,
)


_HEAD = "a" * 40
_TEST_RUNTIME_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(
    bytes(range(32))
)
_TEST_RUNTIME_PUBLIC_KEY = (
    base64.urlsafe_b64encode(
        _TEST_RUNTIME_PRIVATE_KEY.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )
    .decode("ascii")
    .rstrip("=")
)
_RETRY_RUNTIME_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(
    bytes(range(32, 64))
)
_RETRY_RUNTIME_PUBLIC_KEY = (
    base64.urlsafe_b64encode(
        _RETRY_RUNTIME_PRIVATE_KEY.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )
    .decode("ascii")
    .rstrip("=")
)


def _sign_test_payload(domain: bytes, payload: dict[str, object]) -> str:
    return (
        base64.urlsafe_b64encode(
            _TEST_RUNTIME_PRIVATE_KEY.sign(
                domain + zero_runtime._canonical_bytes(payload)
            )
        )
        .decode("ascii")
        .rstrip("=")
    )


def _seatbelt_event(
    *,
    message: str,
    process_path: str,
    sender_path: str = "",
) -> bytes:
    return (
        json.dumps(
            {
                "eventType": "logEvent",
                "processImagePath": process_path,
                "senderImagePath": sender_path,
                "eventMessage": message,
            },
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _runtime_seatbelt_raw(
    nonce: str,
    *,
    extra_events: tuple[bytes, ...] = (),
    post_end_events: tuple[bytes, ...] = (),
) -> bytes:
    kernel = "/System/Library/Extensions/Sandbox.kext/Contents/MacOS/Sandbox"
    return b"".join(
        (
            _seatbelt_event(
                message=f"XIAORO_RUNTIME_SEATBELT_READY:{nonce}",
                process_path="/usr/bin/logger",
            ),
            _seatbelt_event(
                message=f"XIAORO_RUNTIME_SEATBELT_CANARY_BEGIN:{nonce}:4000",
                process_path="/usr/bin/logger",
            ),
            _seatbelt_event(
                message=(
                    "Sandbox: nc(4001) deny(1) "
                    f"network-outbound remote:*:9\n{nonce}"
                ),
                process_path="/kernel",
                sender_path=kernel,
            ),
            _seatbelt_event(
                message=(
                    "Sandbox: nc(4002) deny(1) "
                    f"network-outbound remote:*:443\n{nonce}"
                ),
                process_path="/kernel",
                sender_path=kernel,
            ),
            _seatbelt_event(
                message=(
                    f"XIAORO_RUNTIME_SEATBELT_CANARY:{nonce}:"
                    "root_child:4001:9"
                ),
                process_path="/usr/bin/logger",
            ),
            _seatbelt_event(
                message=(
                    f"XIAORO_RUNTIME_SEATBELT_CANARY:{nonce}:"
                    "descendant:4002:443"
                ),
                process_path="/usr/bin/logger",
            ),
            *extra_events,
            _seatbelt_event(
                message=f"XIAORO_RUNTIME_SEATBELT_CANARY_END:{nonce}:4000",
                process_path="/usr/bin/logger",
            ),
            _seatbelt_event(
                message=f"XIAORO_RUNTIME_SEATBELT_BEGIN:{nonce}:4100",
                process_path="/usr/bin/logger",
            ),
            _seatbelt_event(
                message=f"XIAORO_RUNTIME_SEATBELT_END:{nonce}:4100",
                process_path="/usr/bin/logger",
            ),
            *post_end_events,
            _seatbelt_event(
                message=(
                    f"XIAORO_RUNTIME_SEATBELT_CANARY:{nonce}:"
                    "drain:4200:53"
                ),
                process_path="/usr/bin/logger",
            ),
            _seatbelt_event(
                message=(
                    "Sandbox: nc(4200) deny(1) "
                    f"network-outbound remote:*:53\n{nonce}"
                ),
                process_path="/kernel",
                sender_path=kernel,
            ),
            _seatbelt_event(
                message=f"XIAORO_RUNTIME_SEATBELT_DRAIN:{nonce}",
                process_path="/usr/bin/logger",
            ),
        )
    )


def _passing_child_report() -> dict[str, object]:
    report: dict[str, object] = {
        "schema_version": (
            "guide-zero-api-runtime-child-network-report-v1"
        ),
        "measurement": "python-runtime-guard",
        "fixture_runtime_public_key": _TEST_RUNTIME_PUBLIC_KEY,
        "guard_active": True,
        "passed": True,
        "provider_call_count": 0,
        "outbound_network_attempt_count": 0,
        "attempts": [],
        "runtime_started": True,
        "ready_identity_written": True,
        "challenge_consumed": True,
        "shutdown_consumed": True,
        "shutdown_finalized": True,
        "runtime_succeeded": True,
        "process_creation_attempt_count": 0,
        "process_creation_attempts": [],
        "candidate_manifest_sha256": "1" * 64,
        "runtime_identity_sha256": "2" * 64,
        "consumed_health_challenge_sha256s": ["3" * 64],
    }
    report["runtime_report_signature"] = _sign_test_payload(
        zero_runtime._CHILD_REPORT_SIGNATURE_DOMAIN,
        report,
    )
    return report


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
    plan = "docs/superpowers/plans/task11.md"
    (root / protected).parent.mkdir(parents=True)
    (root / protected).write_text("candidate\n", encoding="utf-8")
    (root / plan).parent.mkdir(parents=True)
    (root / plan).write_text(
        "Task 11 evidence epoch: repair-epoch-1\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "tests@example.com"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Tests"],
        cwd=root,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "candidate"],
        cwd=root,
        check=True,
    )
    candidate_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    ledger = (
        root
        / "docs/audits/final-release/mainline-contract-closure"
        / "smoke-attempt-ledger.json"
    )
    attempt_ledger.initialize_ledger(ledger)
    ledger_bytes = ledger.read_bytes()
    ledger_payload = attempt_ledger.read_ledger(ledger)
    ledger_anchor = attempt_ledger.ledger_anchor(ledger_payload)
    payload_sha256 = _payload_sha256(root, [protected, plan])
    manifest = (
        root
        / "docs/audits/final-release/mainline-contract-closure"
        / "repair-epoch-1"
        / "task11-candidate-manifest.json"
    )
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "guide-task11-candidate-manifest-v1",
                "repository_root": str(root.resolve()),
                "plan_revision": "2026-08-23-task11-r5",
                "repair_epoch": 1,
                "candidate_head": candidate_head,
                "source_paths": [protected],
                "test_paths": [],
                "tool_paths": [],
                "plan_paths": [plan],
                "fixture_paths": [],
                "deleted_paths": [],
                "deleted_base_blob_sha256_by_path": {},
                "mutable_evidence_paths": [
                    "docs/audits/final-release/"
                    "mainline-contract-closure/"
                    "smoke-attempt-ledger.json"
                ],
                "excluded_paths": [],
                "protected_paths": [protected, plan],
                "change_paths": [protected],
                "candidate_payload_sha256": payload_sha256,
                "protected_payload_sha256": payload_sha256,
                "fixture_runtime_public_keys": [
                    _TEST_RUNTIME_PUBLIC_KEY,
                    _RETRY_RUNTIME_PUBLIC_KEY,
                ],
                "fixture_runtime_private_key_paths": [
                    str(
                        (
                            tmp_path
                            / "fixture-runtime-private-key.json"
                        ).resolve()
                    ),
                    str(
                        (
                            tmp_path
                            / "fixture-runtime-private-key.retry-2.json"
                        ).resolve()
                    ),
                ],
                "pre_checkpoint_ledger": {
                    "path": str(ledger.resolve()),
                    "sha256": sha256(ledger_bytes).hexdigest(),
                    "revision": ledger_anchor["revision"],
                    "revision_hash": ledger_anchor["revision_hash"],
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return manifest


def _runtime_private_key_file(
    tmp_path: Path,
    manifest: Path,
    *,
    private_key: Ed25519PrivateKey = _TEST_RUNTIME_PRIVATE_KEY,
    public_key: str = _TEST_RUNTIME_PUBLIC_KEY,
    runtime_key_slot: int = 1,
) -> Path:
    path = tmp_path / (
        "fixture-runtime-private-key.json"
        if runtime_key_slot == 1
        else f"fixture-runtime-private-key.retry-{runtime_key_slot}.json"
    )
    path.write_bytes(
        zero_runtime._canonical_bytes({
            "schema_version": (
                "guide-task11-fixture-runtime-private-key-v1"
            ),
            "candidate_manifest_sha256": sha256(
                manifest.read_bytes()
            ).hexdigest(),
            "runtime_key_slot": runtime_key_slot,
            "fixture_runtime_public_key": public_key,
            "fixture_runtime_private_key": encode_runtime_private_key(
                private_key
            ),
        })
    )
    path.chmod(0o600)
    return path


class _Server:
    def __init__(
        self,
        *,
        application: object,
        host: str,
        port: int,
        ready_file: Path,
        consume_challenge: bool,
        consume_shutdown: bool,
        action: Callable[[], None] | None = None,
    ) -> None:
        self.application = application
        self.host = host
        self.port = port
        self.ready_file = ready_file
        self.consume_challenge = consume_challenge
        self.consume_shutdown = consume_shutdown
        self.started = False
        self.should_exit = False
        self._action = action

    async def _request(
        self,
        *,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        body = (
            b""
            if payload is None
            else json.dumps(payload, sort_keys=True).encode("utf-8")
        )
        request_pending = True
        messages: list[dict[str, object]] = []

        async def receive() -> dict[str, object]:
            nonlocal request_pending
            if request_pending:
                request_pending = False
                return {
                    "type": "http.request",
                    "body": body,
                    "more_body": False,
                }
            return {"type": "http.disconnect"}

        async def send(message: dict[str, object]) -> None:
            messages.append(message)

        await self.application(  # type: ignore[operator]
            {
                "type": "http",
                "method": method,
                "path": path,
                "client": ("127.0.0.1", 32000),
            },
            receive,
            send,
        )
        status = next(
            message["status"]
            for message in messages
            if message.get("type") == "http.response.start"
        )
        assert status == 200
        response_body = b"".join(
            message.get("body", b"")  # type: ignore[arg-type]
            for message in messages
            if message.get("type") == "http.response.body"
        )
        decoded = json.loads(response_body)
        assert isinstance(decoded, dict)
        return decoded

    async def serve(self) -> None:
        self.started = True
        if self._action is not None:
            self._action()
        issued: dict[str, object] | None = None
        if self.consume_challenge:
            issued = await self._request(
                method="GET",
                path="/__task11_runtime__/challenge",
            )
            await self._request(
                method="POST",
                path="/__task11_runtime__/challenge",
                payload={"challenge": issued["challenge"]},
            )
        if self.consume_shutdown:
            for _ in range(100):
                if self.ready_file.is_file():
                    break
                await asyncio.sleep(0.01)
            identity = json.loads(
                self.ready_file.read_text(encoding="utf-8")
            )
            await self._request(
                method="POST",
                path="/__task11_runtime__/shutdown",
                payload={"runtime_nonce": identity["runtime_nonce"]},
            )
        await asyncio.sleep(0)


def _run(
    tmp_path: Path,
    *,
    manifest: Path | None = None,
    host: str = "127.0.0.1",
    application_loader: Callable[[], object] = object,
    action: Callable[[], None] | None = None,
    consume_challenge: bool = True,
    consume_shutdown: bool = True,
) -> tuple[dict[str, object], Path, Path]:
    candidate = manifest or _candidate_manifest(tmp_path)
    private_key = _runtime_private_key_file(tmp_path, candidate)
    ready_file = tmp_path / "runtime-ready.json"
    network_report = tmp_path / "runtime-network.json"

    identity = zero_runtime.run_zero_api_runtime(
        manifest_path=candidate,
        expected_manifest_sha256=sha256(
            candidate.read_bytes()
        ).hexdigest(),
        runtime_signing_private_key=private_key,
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
                ready_file=ready_file,
                consume_challenge=consume_challenge,
                consume_shutdown=consume_shutdown,
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
    original_popen_init = subprocess.Popen.__init__
    original_manifest_loader = zero_runtime._load_candidate_manifest
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

    def load_manifest(
        path: Path,
        *,
        expected_manifest_sha256: str,
    ):
        observed["manifest_loaded_before_process_guard"] = (
            subprocess.Popen.__init__ is original_popen_init
        )
        return original_manifest_loader(
            path,
            expected_manifest_sha256=expected_manifest_sha256,
        )

    monkeypatch.setattr(
        zero_runtime,
        "_load_candidate_manifest",
        load_manifest,
    )
    manifest = _candidate_manifest(tmp_path)
    identity, ready_file, network_report = _run(
        tmp_path,
        manifest=manifest,
        application_loader=load_application,
    )

    assert not (tmp_path / "fixture-runtime-private-key.json").exists()
    assert observed == {
        "guard_installed": True,
        "manifest_loaded_before_process_guard": True,
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
    assert identity["code_revision"] == json.loads(
        manifest.read_text(encoding="utf-8")
    )["candidate_head"]
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
        expected_manifest_sha256=sha256(
            manifest.read_bytes()
        ).hexdigest(),
        expected_host="127.0.0.1",
        expected_port=8820,
        expected_pid=os.getpid(),
    ) == identity

    report = json.loads(network_report.read_text(encoding="utf-8"))
    assert report["guard_active"] is True
    assert report["challenge_consumed"] is True
    consumed_challenge_digests = report[
        "consumed_health_challenge_sha256s"
    ]
    assert isinstance(consumed_challenge_digests, list)
    assert len(consumed_challenge_digests) == 1
    assert len(consumed_challenge_digests[0]) == 64
    assert report["shutdown_consumed"] is True
    assert report["shutdown_finalized"] is True
    assert report["runtime_succeeded"] is True
    assert report["measurement"] == "python-runtime-guard"
    assert report["provider_call_count"] == 0
    assert report["outbound_network_attempt_count"] == 0
    assert report["process_creation_attempt_count"] == 0
    assert "runtime_process_tree_non_loopback_attempt_count" not in report
    assert report["passed"] is True
    assert not tuple(tmp_path.glob(".*.tmp"))


def test_runtime_accepts_second_precommitted_private_key(
    tmp_path: Path,
) -> None:
    manifest = _candidate_manifest(tmp_path)
    retry_private_key = _runtime_private_key_file(
        tmp_path,
        manifest,
        private_key=_RETRY_RUNTIME_PRIVATE_KEY,
        public_key=_RETRY_RUNTIME_PUBLIC_KEY,
        runtime_key_slot=2,
    )
    ready_file = tmp_path / "runtime-ready.json"
    network_report = tmp_path / "runtime-network.json"

    identity = zero_runtime.run_zero_api_runtime(
        manifest_path=manifest,
        expected_manifest_sha256=sha256(
            manifest.read_bytes()
        ).hexdigest(),
        runtime_signing_private_key=retry_private_key,
        host="127.0.0.1",
        port=8820,
        state_dir=tmp_path / "state",
        ready_file=ready_file,
        network_report=network_report,
        application_loader=object,
        server_factory=lambda application, runtime_host, runtime_port: (
            _Server(
                application=application,
                host=runtime_host,
                port=runtime_port,
                ready_file=ready_file,
                consume_challenge=True,
                consume_shutdown=True,
            )
        ),
    )

    assert identity["runtime_public_key"] == _RETRY_RUNTIME_PUBLIC_KEY
    assert not retry_private_key.exists()
    report = json.loads(network_report.read_text(encoding="utf-8"))
    assert report["fixture_runtime_public_key"] == (
        _RETRY_RUNTIME_PUBLIC_KEY
    )
    assert report["passed"] is True


def test_runtime_private_key_consumption_does_not_unlink_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _candidate_manifest(tmp_path)
    private_key_path = _runtime_private_key_file(tmp_path, manifest)
    escaped_key_path = tmp_path / "escaped-private-key.json"
    original_unlink = os.unlink
    swapped = False

    def swap_before_unlink(
        path: str | bytes,
        *args: object,
        dir_fd: int | None = None,
        **kwargs: object,
    ) -> None:
        nonlocal swapped
        if path == private_key_path.name and not swapped:
            swapped = True
            assert dir_fd is not None
            os.rename(
                path,
                escaped_key_path.name,
                src_dir_fd=dir_fd,
                dst_dir_fd=dir_fd,
            )
            replacement = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=dir_fd,
            )
            try:
                os.write(replacement, b"{}\n")
            finally:
                os.close(replacement)
        original_unlink(
            path,
            *args,
            dir_fd=dir_fd,
            **kwargs,
        )

    monkeypatch.setattr(os, "unlink", swap_before_unlink)

    with pytest.raises(
        zero_runtime.ZeroApiRuntimeError,
        match="private key inode changed",
    ):
        zero_runtime._consume_runtime_private_key_file(
            path=private_key_path,
            manifest=json.loads(manifest.read_text(encoding="utf-8")),
            expected_manifest_sha256=sha256(
                manifest.read_bytes()
            ).hexdigest(),
        )

    assert escaped_key_path.exists()
    assert escaped_key_path.read_bytes()


def test_runtime_private_key_unlink_interruption_preserves_retryable_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _candidate_manifest(tmp_path)
    private_key_path = _runtime_private_key_file(tmp_path, manifest)
    original_bytes = private_key_path.read_bytes()
    original_unlink = os.unlink

    def interrupt_unlink(
        path: str | bytes,
        *args: object,
        dir_fd: int | None = None,
        **kwargs: object,
    ) -> None:
        if path == private_key_path.name:
            raise OSError("simulated unlink interruption")
        original_unlink(
            path,
            *args,
            dir_fd=dir_fd,
            **kwargs,
        )

    monkeypatch.setattr(os, "unlink", interrupt_unlink)
    with pytest.raises(
        zero_runtime.ZeroApiRuntimeError,
        match="private key was not consumed",
    ):
        zero_runtime._consume_runtime_private_key_file(
            path=private_key_path,
            manifest=json.loads(manifest.read_text(encoding="utf-8")),
            expected_manifest_sha256=sha256(
                manifest.read_bytes()
            ).hexdigest(),
        )
    assert private_key_path.read_bytes() == original_bytes

    monkeypatch.setattr(os, "unlink", original_unlink)
    private_key = zero_runtime._consume_runtime_private_key_file(
        path=private_key_path,
        manifest=json.loads(manifest.read_text(encoding="utf-8")),
        expected_manifest_sha256=sha256(
            manifest.read_bytes()
        ).hexdigest(),
    )

    assert private_key.public_key() == _TEST_RUNTIME_PRIVATE_KEY.public_key()
    assert not private_key_path.exists()


def test_runtime_private_key_consumption_rejects_parent_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _candidate_manifest(tmp_path)
    key_parent = tmp_path / "runtime-keys"
    key_parent.mkdir()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["fixture_runtime_private_key_paths"] = [
        str((key_parent / "fixture-runtime-private-key.json").resolve()),
        str(
            (
                key_parent
                / "fixture-runtime-private-key.retry-2.json"
            ).resolve()
        ),
    ]
    manifest.write_text(
        json.dumps(payload, sort_keys=True),
        encoding="utf-8",
    )
    private_key_path = _runtime_private_key_file(key_parent, manifest)
    escaped_parent = tmp_path / "escaped-runtime-keys"
    original_unlink = os.unlink
    swapped = False

    def swap_parent_before_unlink(
        path: str | bytes,
        *args: object,
        dir_fd: int | None = None,
        **kwargs: object,
    ) -> None:
        nonlocal swapped
        if path == private_key_path.name and not swapped:
            swapped = True
            key_parent.rename(escaped_parent)
            key_parent.mkdir()
            replacement = key_parent / private_key_path.name
            replacement.write_bytes(
                (escaped_parent / private_key_path.name).read_bytes()
            )
            replacement.chmod(0o600)
        original_unlink(
            path,
            *args,
            dir_fd=dir_fd,
            **kwargs,
        )

    monkeypatch.setattr(os, "unlink", swap_parent_before_unlink)

    with pytest.raises(
        zero_runtime.ZeroApiRuntimeError,
        match="private key parent changed",
    ):
        zero_runtime._consume_runtime_private_key_file(
            path=private_key_path,
            manifest=payload,
            expected_manifest_sha256=sha256(
                manifest.read_bytes()
            ).hexdigest(),
        )

    assert private_key_path.exists()
    assert private_key_path.read_bytes()


def test_runtime_rejects_private_key_outside_precommitted_pair(
    tmp_path: Path,
) -> None:
    manifest = _candidate_manifest(tmp_path)
    uncommitted_private_key = Ed25519PrivateKey.generate()
    uncommitted_public_key = (
        base64.urlsafe_b64encode(
            uncommitted_private_key.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        )
        .decode("ascii")
        .rstrip("=")
    )
    private_key_path = _runtime_private_key_file(
        tmp_path,
        manifest,
        private_key=uncommitted_private_key,
        public_key=uncommitted_public_key,
        runtime_key_slot=2,
    )

    with pytest.raises(
        zero_runtime.ZeroApiRuntimeError,
        match="private key is invalid",
    ):
        zero_runtime.run_zero_api_runtime(
            manifest_path=manifest,
            expected_manifest_sha256=sha256(
                manifest.read_bytes()
            ).hexdigest(),
            runtime_signing_private_key=private_key_path,
            host="127.0.0.1",
            port=8820,
            state_dir=tmp_path / "state",
            ready_file=tmp_path / "runtime-ready.json",
            network_report=tmp_path / "runtime-network.json",
        )

    assert private_key_path.is_file()


def test_runtime_sandbox_report_is_derived_from_kernel_events() -> None:
    nonce = "9" * 64
    profile = zero_runtime._runtime_sandbox_profile(nonce)
    raw = _runtime_seatbelt_raw(nonce)

    report = zero_runtime._build_runtime_sandbox_report(
        child_report=_passing_child_report(),
        fixture_runtime_public_key=_TEST_RUNTIME_PUBLIC_KEY,
        sandbox_profile=profile,
        runtime_sandbox_profile=(
            zero_runtime._runtime_execution_sandbox_profile(nonce)
        ),
        measurement_nonce=nonce,
        seatbelt_raw=raw,
        logger_stderr=b"",
        logger_returncode=0,
        canary_root_pid=4000,
        runtime_root_pid=4100,
        runtime_process_group_id=4100,
        drain_canary_pid=4200,
        canary_process_groups_quiescent=True,
        process_group_quiescent=True,
    )

    assert report["schema_version"] == (
        "guide-zero-api-runtime-network-report-v2"
    )
    assert report["measurement"] == (
        "macos-unified-log-seatbelt-kernel"
    )
    assert report["seatbelt_raw_ndjson_sha256"] == sha256(raw).hexdigest()
    assert report["seatbelt_canary_denial_count"] == 3
    assert report["logger_drain_marker_count"] == 1
    assert report["runtime_root_pid"] == 4100
    assert report["runtime_process_group_id"] == 4100
    assert report["canary_process_groups_quiescent"] is True
    assert report["process_group_quiescent"] is True
    assert report["runtime_process_tree_non_loopback_attempt_count"] == 0
    assert report["process_tree_attempts"] == []
    assert report["passed"] is True


def test_runtime_sandbox_report_accepts_duplicate_known_canary_denial() -> None:
    nonce = "0" * 64
    duplicate = _seatbelt_event(
        message=(
            "1 duplicate report for Sandbox: nc(4002) deny(1) "
            f"network-outbound remote:*:443\n{nonce}"
        ),
        process_path="/kernel",
        sender_path=(
            "/System/Library/Extensions/Sandbox.kext/"
            "Contents/MacOS/Sandbox"
        ),
    )

    report = zero_runtime._build_runtime_sandbox_report(
        child_report=_passing_child_report(),
        fixture_runtime_public_key=_TEST_RUNTIME_PUBLIC_KEY,
        sandbox_profile=zero_runtime._runtime_sandbox_profile(nonce),
        runtime_sandbox_profile=(
            zero_runtime._runtime_execution_sandbox_profile(nonce)
        ),
        measurement_nonce=nonce,
        seatbelt_raw=_runtime_seatbelt_raw(
            nonce,
            extra_events=(duplicate,),
        ),
        logger_stderr=b"",
        logger_returncode=0,
        canary_root_pid=4000,
        runtime_root_pid=4100,
        runtime_process_group_id=4100,
        drain_canary_pid=4200,
        canary_process_groups_quiescent=True,
        process_group_quiescent=True,
    )

    assert report["passed"] is True
    assert report["process_tree_attempts"] == []
    assert report["duplicate_canary_denial_count"] == 1


def test_runtime_sandbox_report_rejects_unexpected_kernel_egress() -> None:
    nonce = "8" * 64
    unexpected = _seatbelt_event(
        message=(
            "Sandbox: Python(4100) deny(1) "
            f"network-outbound remote:*:8443\n{nonce}"
        ),
        process_path="/kernel",
        sender_path=(
            "/System/Library/Extensions/Sandbox.kext/"
            "Contents/MacOS/Sandbox"
        ),
    )

    with pytest.raises(
        zero_runtime.ZeroApiRuntimeError,
        match="non-loopback",
    ):
        zero_runtime._build_runtime_sandbox_report(
            child_report=_passing_child_report(),
            fixture_runtime_public_key=_TEST_RUNTIME_PUBLIC_KEY,
            sandbox_profile=zero_runtime._runtime_sandbox_profile(nonce),
            runtime_sandbox_profile=(
                zero_runtime._runtime_execution_sandbox_profile(nonce)
            ),
            measurement_nonce=nonce,
            seatbelt_raw=_runtime_seatbelt_raw(
                nonce,
                extra_events=(unexpected,),
            ),
            logger_stderr=b"",
            logger_returncode=0,
            canary_root_pid=4000,
            runtime_root_pid=4100,
            runtime_process_group_id=4100,
            drain_canary_pid=4200,
            canary_process_groups_quiescent=True,
            process_group_quiescent=True,
        )


def test_runtime_sandbox_report_requires_post_exit_drain_marker() -> None:
    nonce = "6" * 64
    raw = _runtime_seatbelt_raw(nonce)
    drain = _seatbelt_event(
        message=f"XIAORO_RUNTIME_SEATBELT_DRAIN:{nonce}",
        process_path="/usr/bin/logger",
    )

    with pytest.raises(
        zero_runtime.ZeroApiRuntimeError,
        match="drain",
    ):
        zero_runtime._build_runtime_sandbox_report(
            child_report=_passing_child_report(),
            fixture_runtime_public_key=_TEST_RUNTIME_PUBLIC_KEY,
            sandbox_profile=zero_runtime._runtime_sandbox_profile(nonce),
            runtime_sandbox_profile=(
                zero_runtime._runtime_execution_sandbox_profile(nonce)
            ),
            measurement_nonce=nonce,
            seatbelt_raw=raw.removesuffix(drain),
            logger_stderr=b"",
            logger_returncode=0,
            canary_root_pid=4000,
            runtime_root_pid=4100,
            runtime_process_group_id=4100,
            drain_canary_pid=4200,
            canary_process_groups_quiescent=True,
            process_group_quiescent=True,
        )


def test_runtime_sandbox_report_rejects_egress_after_end_before_drain() -> None:
    nonce = "5" * 64
    delayed = _seatbelt_event(
        message=(
            "Sandbox: Python(4100) deny(1) "
            f"network-outbound remote:*:8443\n{nonce}"
        ),
        process_path="/kernel",
        sender_path=(
            "/System/Library/Extensions/Sandbox.kext/"
            "Contents/MacOS/Sandbox"
        ),
    )

    with pytest.raises(
        zero_runtime.ZeroApiRuntimeError,
        match="non-loopback",
    ):
        zero_runtime._build_runtime_sandbox_report(
            child_report=_passing_child_report(),
            fixture_runtime_public_key=_TEST_RUNTIME_PUBLIC_KEY,
            sandbox_profile=zero_runtime._runtime_sandbox_profile(nonce),
            runtime_sandbox_profile=(
                zero_runtime._runtime_execution_sandbox_profile(nonce)
            ),
            measurement_nonce=nonce,
            seatbelt_raw=_runtime_seatbelt_raw(
                nonce,
                post_end_events=(delayed,),
            ),
            logger_stderr=b"",
            logger_returncode=0,
            canary_root_pid=4000,
            runtime_root_pid=4100,
            runtime_process_group_id=4100,
            drain_canary_pid=4200,
            canary_process_groups_quiescent=True,
            process_group_quiescent=True,
        )


def test_runtime_sandbox_report_requires_kernel_drain_before_marker() -> None:
    nonce = "2" * 64
    events = _runtime_seatbelt_raw(nonce).splitlines(keepends=True)
    drain_denial = next(
        line
        for line in events
        if b"network-outbound remote:*:53" in line
    )
    events.remove(drain_denial)
    events.append(drain_denial)

    with pytest.raises(
        zero_runtime.ZeroApiRuntimeError,
        match="canary delivery order",
    ):
        zero_runtime._build_runtime_sandbox_report(
            child_report=_passing_child_report(),
            fixture_runtime_public_key=_TEST_RUNTIME_PUBLIC_KEY,
            sandbox_profile=zero_runtime._runtime_sandbox_profile(nonce),
            runtime_sandbox_profile=(
                zero_runtime._runtime_execution_sandbox_profile(nonce)
            ),
            measurement_nonce=nonce,
            seatbelt_raw=b"".join(events),
            logger_stderr=b"",
            logger_returncode=0,
            canary_root_pid=4000,
            runtime_root_pid=4100,
            runtime_process_group_id=4100,
            drain_canary_pid=4200,
            canary_process_groups_quiescent=True,
            process_group_quiescent=True,
        )


def test_runtime_capture_requires_isolated_quiescent_process_group() -> None:
    source = inspect.getsource(
        zero_runtime._execute_runtime_sandbox_process
    )

    assert "start_new_session=True" in source
    assert "_require_process_group_quiescent" in source
    assert "_runtime_execution_sandbox_profile" in source
    assert "_run_post_exit_drain_canary" in source
    assert "_RUNTIME_SEATBELT_DRAIN_PREFIX" in source
    assert "timeout=runtime_timeout_seconds" in source


def test_runtime_drain_canary_kills_nonquiescent_descendants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminated: list[int] = []

    class _FakeStdin:
        def write(self, value: bytes) -> int:
            return len(value)

        def close(self) -> None:
            return None

    class _FakeProcess:
        pid = 4200
        returncode: int | None = None
        stdin: _FakeStdin | None = _FakeStdin()

        def communicate(
            self,
            *,
            timeout: float,
        ) -> tuple[bytes, bytes]:
            self.returncode = 1
            return b"", b""

        def poll(self) -> int | None:
            return self.returncode

    monkeypatch.setattr(
        zero_runtime.subprocess,
        "Popen",
        lambda *args, **kwargs: _FakeProcess(),
    )
    monkeypatch.setattr(
        zero_runtime.os,
        "getpgid",
        lambda pid: pid,
    )
    monkeypatch.setattr(
        zero_runtime,
        "_require_process_group_quiescent",
        lambda process_group_id: (_ for _ in ()).throw(
            zero_runtime.ZeroApiRuntimeError(
                "runtime sandbox process group did not become quiescent"
            )
        ),
    )
    monkeypatch.setattr(
        zero_runtime,
        "_terminate_process_group",
        lambda process: terminated.append(process.pid),
    )

    with pytest.raises(
        zero_runtime.ZeroApiRuntimeError,
        match="did not become quiescent",
    ):
        zero_runtime._run_post_exit_drain_canary(
            sandbox_profile="profile",
            measurement_nonce="a" * 64,
            environment={},
            on_started=lambda process_id: None,
        )

    assert terminated == [4200]


def test_runtime_capture_waits_for_every_required_marker_family() -> None:
    marker_events = {
        name: zero_runtime.threading.Event()
        for name in (
            "canary_begin",
            "root_child",
            "descendant",
            "canary_end",
        )
    }
    marker_events["canary_begin"].set()
    marker_events["root_child"].set()
    marker_events["canary_end"].set()

    def deliver_last_marker() -> None:
        marker_events["descendant"].set()

    delivery = zero_runtime.threading.Timer(
        0.05,
        deliver_last_marker,
    )
    delivery.start()
    try:
        zero_runtime._wait_for_runtime_marker_delivery(
            marker_events=marker_events,
            required_markers=tuple(marker_events),
            timeout_seconds=1.0,
        )
    finally:
        delivery.join(timeout=1)

    source = inspect.getsource(
        zero_runtime._execute_runtime_sandbox_process
    )
    assert source.count(
        "_wait_for_runtime_marker_delivery("
    ) >= 4
    for marker_name in (
        "canary_begin",
        "root_child",
        "descendant",
        "canary_end",
        "runtime_begin",
        "runtime_end",
        "drain_canary",
        "drain",
    ):
        assert f'"{marker_name}"' in source


def test_short_lived_runtime_canaries_do_not_emit_logger_markers() -> None:
    child_source = inspect.getsource(
        zero_runtime._run_runtime_seatbelt_canary_child
    )
    harness_source = inspect.getsource(
        zero_runtime._run_runtime_seatbelt_canaries
    )
    capture_source = inspect.getsource(
        zero_runtime._execute_runtime_sandbox_process
    )

    assert "_emit_runtime_seatbelt_marker" not in child_source
    assert "_emit_runtime_seatbelt_marker" not in harness_source
    assert "stdin=subprocess.PIPE" in capture_source
    assert "canary.stdin.write" in capture_source
    assert capture_source.count(
        "_emit_runtime_seatbelt_marker("
    ) >= 7


def test_runtime_execution_sandbox_denies_process_fork() -> None:
    nonce = "4" * 64

    profile = zero_runtime._runtime_execution_sandbox_profile(nonce)

    assert profile.startswith(zero_runtime._runtime_sandbox_profile(nonce))
    assert "(deny process-fork" in profile
    assert nonce in profile


def test_runtime_uses_distinct_child_and_parent_report_signature_domains(
) -> None:
    assert (
        zero_runtime._CHILD_REPORT_SIGNATURE_DOMAIN
        != zero_runtime._PARENT_REPORT_SIGNATURE_DOMAIN
    )


def test_runtime_cli_requires_reviewed_manifest_sha256() -> None:
    parser = zero_runtime._parser()
    arguments = [
        "--manifest",
        "manifest.json",
        "--runtime-signing-private-key",
        "/tmp/runtime-key.json",
        "--host",
        "127.0.0.1",
        "--port",
        "8820",
        "--state-dir",
        "/tmp/state",
        "--ready-file",
        "/tmp/ready.json",
        "--network-report",
        "runtime-network.json",
    ]

    with pytest.raises(SystemExit):
        parser.parse_args(arguments)

    parsed = parser.parse_args([
        *arguments,
        "--expected-manifest-sha256",
        "a" * 64,
    ])

    assert parsed.expected_manifest_sha256 == "a" * 64


def test_runtime_report_binds_observed_runtime_pid_and_pgid() -> None:
    nonce = "3" * 64

    with pytest.raises(
        zero_runtime.ZeroApiRuntimeError,
        match="runtime process identity",
    ):
        zero_runtime._build_runtime_sandbox_report(
            child_report=_passing_child_report(),
            fixture_runtime_public_key=_TEST_RUNTIME_PUBLIC_KEY,
            sandbox_profile=zero_runtime._runtime_sandbox_profile(nonce),
            runtime_sandbox_profile=(
                zero_runtime._runtime_execution_sandbox_profile(nonce)
            ),
            measurement_nonce=nonce,
            seatbelt_raw=_runtime_seatbelt_raw(nonce),
            logger_stderr=b"",
            logger_returncode=0,
            canary_root_pid=4000,
            runtime_root_pid=9999,
            runtime_process_group_id=9999,
            drain_canary_pid=4200,
            canary_process_groups_quiescent=True,
            process_group_quiescent=True,
        )


def test_runtime_process_group_probe_rejects_live_members() -> None:
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True,
    )
    try:
        with pytest.raises(
            zero_runtime.ZeroApiRuntimeError,
            match="did not become quiescent",
        ):
            zero_runtime._require_process_group_quiescent(
                child.pid,
                timeout_seconds=0.1,
            )
    finally:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait(timeout=5)

    zero_runtime._require_process_group_quiescent(
        child.pid,
        timeout_seconds=0.1,
    )


def test_runtime_parent_collects_and_publishes_kernel_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    nonce = "7" * 64
    manifest = _candidate_manifest(tmp_path)
    private_key = _runtime_private_key_file(tmp_path, manifest)
    report_path = tmp_path / "runtime-network.json"
    captured: dict[str, object] = {}

    def execute(
        *,
        argv: tuple[str, ...],
        sandbox_profile: str,
        measurement_nonce: str,
        environment: dict[str, str],
        runtime_timeout_seconds: float,
    ) -> dict[str, object]:
        captured.update(
            argv=argv,
            sandbox_profile=sandbox_profile,
            measurement_nonce=measurement_nonce,
            environment=environment,
            runtime_timeout_seconds=runtime_timeout_seconds,
        )
        child_report = Path(
            environment[zero_runtime._RUNTIME_CHILD_REPORT_ENV]
        )
        child_report.parent.mkdir(parents=True, exist_ok=True)
        child_report.write_text(
            json.dumps(
                _passing_child_report(),
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return {
            "child_returncode": 0,
            "child_stdout": b'{"identity_sha256":"2"}\n',
            "child_stderr": b"",
            "seatbelt_raw": _runtime_seatbelt_raw(nonce),
            "logger_stderr": b"",
            "logger_returncode": 0,
            "canary_root_pid": 4000,
            "runtime_root_pid": 4100,
            "runtime_process_group_id": 4100,
            "drain_canary_pid": 4200,
            "canary_process_groups_quiescent": True,
            "process_group_quiescent": True,
        }

    monkeypatch.setattr(zero_runtime.secrets, "token_hex", lambda size: nonce)
    monkeypatch.setattr(
        zero_runtime,
        "_execute_runtime_sandbox_process",
        execute,
    )

    returncode = zero_runtime._run_runtime_in_macos_sandbox(
        (
            "--manifest",
            str(manifest),
            "--runtime-signing-private-key",
            str(private_key),
            "--host",
            "127.0.0.1",
            "--port",
            "8820",
            "--state-dir",
            str(tmp_path / "state"),
            "--ready-file",
            str(tmp_path / "ready.json"),
            "--network-report",
            str(report_path),
        ),
        manifest_path=manifest,
        expected_manifest_sha256=sha256(
            manifest.read_bytes()
        ).hexdigest(),
        runtime_signing_private_key_path=private_key,
        network_report=report_path,
    )

    assert returncode == 0
    assert captured["measurement_nonce"] == nonce
    environment = captured["environment"]
    assert isinstance(environment, dict)
    assert environment[zero_runtime._RUNTIME_SANDBOX_NONCE_ENV] == nonce
    assert json.loads(report_path.read_text(encoding="utf-8"))[
        "measurement"
    ] == "macos-unified-log-seatbelt-kernel"
    assert not tuple(tmp_path.glob(".*.child.json"))


def test_default_runtime_server_emits_no_unattested_stderr() -> None:
    server = zero_runtime._default_server_factory(
        object(),
        "127.0.0.1",
        8820,
    )

    assert server.config.log_level == "critical"
    assert server.config.access_log is False


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


def test_repository_head_supports_a_linked_worktree(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    linked = tmp_path / "linked"
    repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(
        ["git", "config", "user.email", "tests@example.com"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Tests"],
        cwd=repository,
        check=True,
    )
    (repository / "tracked.txt").write_text(
        "tracked\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "base"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "worktree",
            "add",
            "-b",
            "linked-worktree-test",
            str(linked),
            "HEAD",
        ],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    git_file = (linked / ".git").read_text(encoding="utf-8").strip()
    linked_git_dir = Path(git_file.removeprefix("gitdir:").strip())
    assert (linked_git_dir / "HEAD").read_text(
        encoding="ascii"
    ).startswith("ref:")

    assert zero_runtime._repository_head(linked) == subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=linked,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_fixture_runtime_rotates_single_use_browser_challenge() -> None:
    authority = zero_runtime.RuntimeChallengeAuthority(
        runtime_identity_sha256="1" * 64,
        runtime_private_key=_TEST_RUNTIME_PRIVATE_KEY,
        runtime_public_key=_TEST_RUNTIME_PUBLIC_KEY,
    )

    first = authority.issue()
    second = authority.issue()

    assert first["challenge"] != second["challenge"]
    assert first["challenge_sha256"] != second["challenge_sha256"]
    assert authority.consume(first["challenge"]) == first
    with pytest.raises(
        zero_runtime.ZeroApiRuntimeError,
        match="already consumed",
    ):
        authority.consume(first["challenge"])
    assert authority.consume(second["challenge"]) == second


def test_runtime_challenge_application_exposes_read_only_consumption_state() -> None:
    application = zero_runtime.RuntimeChallengeApplication(
        object(),
        runtime_identity_sha256="1" * 64,
        runtime_private_key=_TEST_RUNTIME_PRIVATE_KEY,
        runtime_public_key=_TEST_RUNTIME_PUBLIC_KEY,
        shutdown_token="2" * 64,
    )

    assert application.challenge_consumed is False
    assert application.shutdown_consumed is False
    with pytest.raises(AttributeError):
        application.challenge_consumed = True
    with pytest.raises(AttributeError):
        application.shutdown_consumed = True


def test_runtime_shutdown_requires_single_use_runtime_nonce() -> None:
    calls: list[str] = []
    authority = zero_runtime.RuntimeChallengeAuthority(
        runtime_identity_sha256="1" * 64,
        runtime_private_key=_TEST_RUNTIME_PRIVATE_KEY,
        runtime_public_key=_TEST_RUNTIME_PUBLIC_KEY,
        shutdown_token="2" * 64,
        shutdown_callback=lambda: calls.append("shutdown"),
    )

    with pytest.raises(
        zero_runtime.ZeroApiRuntimeError,
        match="shutdown token",
    ):
        authority.shutdown("3" * 64)
    authority.shutdown("2" * 64)
    with pytest.raises(
        zero_runtime.ZeroApiRuntimeError,
        match="already consumed",
    ):
        authority.shutdown("2" * 64)

    assert calls == ["shutdown"]


@pytest.mark.parametrize(
    ("consume_challenge", "consume_shutdown"),
    (
        (False, False),
        (True, False),
        (False, True),
    ),
)
def test_runtime_rejects_server_exit_without_consumed_authorization(
    tmp_path: Path,
    consume_challenge: bool,
    consume_shutdown: bool,
) -> None:
    with pytest.raises(
        zero_runtime.ZeroApiRuntimeError,
        match="runtime (challenge|shutdown) was not consumed",
    ):
        _run(
            tmp_path,
            consume_challenge=consume_challenge,
            consume_shutdown=consume_shutdown,
        )

    report = json.loads(
        (tmp_path / "runtime-network.json").read_text(encoding="utf-8")
    )
    assert report["passed"] is False
    assert report["challenge_consumed"] is consume_challenge
    assert report["shutdown_consumed"] is consume_shutdown
    assert report["shutdown_finalized"] is consume_shutdown
    assert report["runtime_succeeded"] is False
    assert not (tmp_path / "runtime-ready.json").exists()


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

    assert not (tmp_path / "runtime-network.json").exists()
    assert not (tmp_path / "runtime-ready.json").exists()


def test_runtime_requires_reviewed_manifest_sha256(
    tmp_path: Path,
) -> None:
    manifest = _candidate_manifest(tmp_path)
    private_key = _runtime_private_key_file(tmp_path, manifest)

    with pytest.raises(
        zero_runtime.ZeroApiRuntimeError,
        match="reviewed SHA-256",
    ):
        zero_runtime.run_zero_api_runtime(
            manifest_path=manifest,
            expected_manifest_sha256="0" * 64,
            runtime_signing_private_key=private_key,
            host="127.0.0.1",
            port=8820,
            state_dir=tmp_path / "state",
            ready_file=tmp_path / "runtime-ready.json",
            network_report=tmp_path / "runtime-network.json",
        )

    assert private_key.is_file()
    assert not (tmp_path / "runtime-network.json").exists()
    assert not (tmp_path / "runtime-ready.json").exists()


def test_parent_attested_runtime_rejects_symlinked_epoch_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest = _candidate_manifest(tmp_path)
    manifest_sha256 = sha256(manifest.read_bytes()).hexdigest()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    monkeypatch.setenv(
        zero_runtime._RUNTIME_MANIFEST_SHA256_ENV,
        manifest_sha256,
    )
    monkeypatch.setenv(
        zero_runtime._RUNTIME_CANDIDATE_HEAD_ENV,
        str(payload["candidate_head"]),
    )
    monkeypatch.setenv(
        zero_runtime._RUNTIME_PROTECTED_PAYLOAD_ENV,
        str(payload["protected_payload_sha256"]),
    )
    epoch_directory = manifest.parent
    moved_epoch = tmp_path / "moved-epoch"
    epoch_directory.rename(moved_epoch)
    epoch_directory.symlink_to(moved_epoch, target_is_directory=True)

    with pytest.raises(
        zero_runtime.ZeroApiRuntimeError,
        match="symlink",
    ):
        zero_runtime._load_parent_attested_candidate_manifest(
            manifest,
            expected_manifest_sha256=manifest_sha256,
        )


def test_parent_attested_runtime_accepts_revision_qualified_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest = _candidate_manifest(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["plan_revision"] = "2026-08-29-task11-r46"
    versioned_manifest = manifest.with_name(
        "task11-candidate-manifest-r46.json"
    )
    versioned_manifest.write_text(
        json.dumps(payload, sort_keys=True),
        encoding="utf-8",
    )
    manifest.unlink()
    manifest_sha256 = sha256(versioned_manifest.read_bytes()).hexdigest()
    monkeypatch.setenv(
        zero_runtime._RUNTIME_MANIFEST_SHA256_ENV,
        manifest_sha256,
    )
    monkeypatch.setenv(
        zero_runtime._RUNTIME_CANDIDATE_HEAD_ENV,
        str(payload["candidate_head"]),
    )
    monkeypatch.setenv(
        zero_runtime._RUNTIME_PROTECTED_PAYLOAD_ENV,
        str(payload["protected_payload_sha256"]),
    )

    loaded, root, head = (
        zero_runtime._load_parent_attested_candidate_manifest(
            versioned_manifest,
            expected_manifest_sha256=manifest_sha256,
        )
    )

    assert loaded["plan_revision"] == "2026-08-29-task11-r46"
    assert root == versioned_manifest.parents[5]
    assert head == payload["candidate_head"]


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
            expected_manifest_sha256=sha256(
                manifest.read_bytes()
            ).hexdigest(),
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
    assert "runtime_process_tree_non_loopback_attempt_count" not in report
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
    assert report["challenge_consumed"] is False
    assert report["shutdown_consumed"] is False
    assert report["shutdown_finalized"] is False
    assert report["runtime_succeeded"] is False
    assert report["passed"] is False
