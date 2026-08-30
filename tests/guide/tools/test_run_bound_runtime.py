from __future__ import annotations

import asyncio
from contextlib import contextmanager
from hashlib import sha256
import http.client
import importlib
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
from threading import Thread
import time
from typing import Callable

import pytest

from tools.guide_gates import attempt_ledger


_HEAD = "a" * 40
_PAYLOAD_SHA256 = "b" * 64
_PLAN_REVISION = "2026-08-23-task11-r5"
_SECRET = "offline-private-key"


def _runner():
    return importlib.import_module(
        "tools.guide_gates.run_bound_runtime"
    )


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_key(path: Path) -> Path:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
        0o600,
    )
    try:
        os.write(descriptor, _SECRET.encode("utf-8"))
    finally:
        os.close(descriptor)
    return path


def _verified_inputs(
    tmp_path: Path,
) -> tuple[Path, Path, dict[str, object], dict[str, object]]:
    output = tmp_path / "bounded-smoke-attempt-07"
    output.mkdir(parents=True)
    manifest = _write_json(
        tmp_path / "task11-candidate-manifest.json",
        {
            "schema_version": "guide-task11-candidate-manifest-v1",
            "plan_revision": _PLAN_REVISION,
            "candidate_head": _HEAD,
            "protected_payload_sha256": _PAYLOAD_SHA256,
        },
    )
    audit = _write_json(
        tmp_path / "task11-independent-audit.json",
        {
            "schema_version": "guide-task11-independent-audit-v1",
            "passed": True,
            "plan_revision": _PLAN_REVISION,
            "protected_payload_sha256": _PAYLOAD_SHA256,
        },
    )
    readiness = _write_json(
        tmp_path / "task11-candidate-readiness.json",
        {
            "schema_version": "guide-task11-readiness-v1",
            "plan_revision": _PLAN_REVISION,
            "reviewed_candidate_manifest_sha256": sha256(
                manifest.read_bytes()
            ).hexdigest(),
            "candidate_head": _HEAD,
            "protected_payload_sha256": _PAYLOAD_SHA256,
            "circuit_state": "closed",
            "evidence_files": {
                "candidate_manifest": str(manifest.resolve()),
                "independent_audit": str(audit.resolve()),
            },
            "evidence_sha256": {
                "candidate_manifest": sha256(
                    manifest.read_bytes()
                ).hexdigest(),
                "independent_audit": sha256(
                    audit.read_bytes()
                ).hexdigest(),
            },
        },
    )
    ledger = _write_json(
        tmp_path / "smoke-attempt-ledger.json",
        {
            "schema_version": "guide-smoke-attempt-ledger-v1",
            "revision": 4,
            "circuit_state": "closed",
            "attempts": [
                {
                    "attempt_id": "bounded-smoke-attempt-07",
                    "plan_revision": _PLAN_REVISION,
                    "trajectory_set": "bounded",
                    "result": "allocated",
                    "retry_authorization_id": "auth-07",
                }
            ],
            "authorizations": [
                {
                    "authorization_id": "auth-07",
                    "phase": "bounded",
                    "plan_revision": _PLAN_REVISION,
                    "state": "allocated",
                    "attempt_id": "bounded-smoke-attempt-07",
                }
            ],
        },
    )
    context_payload: dict[str, object] = {
        "schema_version": "guide-smoke-attempt-context-v1",
        "expected_manifest_sha256": sha256(
            manifest.read_bytes()
        ).hexdigest(),
        "current_phase": "bounded",
        "phase_attempt_ids": {
            "bounded": "bounded-smoke-attempt-07",
        },
        "phase_authorization_ids": {"bounded": "auth-07"},
        "output_directory": str(output.resolve()),
        "readiness_path": str(readiness.resolve()),
        "readiness_sha256": sha256(readiness.read_bytes()).hexdigest(),
        "ledger_path": str(ledger.resolve()),
        "allocated_ledger_revision": 4,
        "allocated_ledger_hash": "e" * 64,
    }
    context = _write_json(
        output / "attempt-context.json",
        context_payload,
    )
    readiness_payload = json.loads(
        readiness.read_text(encoding="utf-8")
    )
    return context, ledger, context_payload, readiness_payload


def _allocated_runtime_inputs(
    tmp_path: Path,
) -> tuple[
    Path,
    Path,
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    ledger = tmp_path / "smoke-attempt-ledger.json"
    attempt_ledger.initialize_ledger(ledger)
    manifest_payload = {
        "schema_version": "guide-task11-candidate-manifest-v1",
        "plan_revision": _PLAN_REVISION,
        "candidate_head": _HEAD,
        "protected_payload_sha256": _PAYLOAD_SHA256,
        "protected_paths": [],
        "deleted_paths": [],
    }
    manifest = _write_json(
        tmp_path / "task11-candidate-manifest.json",
        manifest_payload,
    )
    audit_payload = {
        "schema_version": "guide-task11-independent-audit-v1",
        "passed": True,
        "plan_revision": _PLAN_REVISION,
        "first_failure_owner": "planned_gate",
        "repair_epoch": 0,
        "protected_payload_sha256": _PAYLOAD_SHA256,
        "local_reproduction": None,
        "focused_test": None,
        "shared_owner_repair": None,
    }
    audit = _write_json(
        tmp_path / "task11-independent-audit.json",
        audit_payload,
    )
    anchor = attempt_ledger.ledger_anchor(
        attempt_ledger.read_ledger(ledger)
    )
    readiness_payload = {
        "schema_version": "guide-task11-readiness-v1",
        "plan_revision": _PLAN_REVISION,
        "reviewed_candidate_manifest_sha256": sha256(
            manifest.read_bytes()
        ).hexdigest(),
        "candidate_head": _HEAD,
        "candidate_payload_sha256": "c" * 64,
        "protected_payload_sha256": _PAYLOAD_SHA256,
        "step_0_passed": True,
        "step_0_5_passed": True,
        "step_4_5_passed": True,
        "affected_zero_api_passed": True,
        "desktop_fixture_passed": True,
        "mobile_fixture_passed": True,
        "invalid_clarification_count": 0,
        "ledger_path": str(ledger.resolve()),
        "ledger_anchor_revision": anchor["revision"],
        "ledger_anchor_hash": anchor["revision_hash"],
        "circuit_state": "closed",
        "evidence_files": {
            "candidate_manifest": str(manifest.resolve()),
            "independent_audit": str(audit.resolve()),
        },
        "evidence_sha256": {
            "candidate_manifest": sha256(
                manifest.read_bytes()
            ).hexdigest(),
            "independent_audit": sha256(
                audit.read_bytes()
            ).hexdigest(),
        },
    }
    readiness = _write_json(
        tmp_path / "task11-candidate-readiness.json",
        readiness_payload,
    )
    authorization_id = attempt_ledger.authorize_attempt(
        phase="bounded",
        expected_manifest_sha256=sha256(
            manifest.read_bytes()
        ).hexdigest(),
        readiness_path=readiness,
        ledger_path=ledger,
        independent_audit_path=audit,
        readiness_verifier=lambda **_: readiness_payload,
    )
    context_path = attempt_ledger.allocate_attempt(
        phase="bounded",
        authorization_id=authorization_id,
        ledger_path=ledger,
        readiness_path=readiness,
        output_root=tmp_path / "attempts",
    )
    context_payload = json.loads(
        context_path.read_text(encoding="utf-8")
    )
    return (
        context_path,
        ledger,
        context_payload,
        readiness_payload,
        manifest_payload,
        audit_payload,
    )


def _install_verified_apis(
    monkeypatch: pytest.MonkeyPatch,
    runner,
    *,
    context: dict[str, object],
    readiness: dict[str, object],
    ledger_path: Path,
) -> list[str]:
    calls: list[str] = []

    def read_context(
        path: str | Path,
        *,
        ledger_path: str | Path,
        readiness_path: str | Path,
    ) -> dict[str, object]:
        del path, ledger_path, readiness_path
        calls.append("context")
        return context

    def verify_readiness(
        *,
        readiness_path: str | Path,
        ledger_path: str | Path,
        expected_manifest_sha256: str,
    ) -> dict[str, object]:
        del readiness_path, ledger_path
        assert expected_manifest_sha256 == (
            context["expected_manifest_sha256"]
        )
        calls.append("readiness")
        return readiness

    monkeypatch.setattr(runner, "read_attempt_context", read_context)
    monkeypatch.setattr(
        runner,
        "verify_task11_readiness",
        verify_readiness,
    )
    monkeypatch.setattr(
        runner,
        "read_ledger",
        lambda path: (
            calls.append("ledger")
            or json.loads(Path(path).read_text(encoding="utf-8"))
        ),
    )
    def register_runtime(*args, **kwargs):
        del args
        calls.append("registration")
        return {
            "registration_id": kwargs["registration_id"],
            "state": "registered",
        }

    monkeypatch.setattr(
        runner,
        "register_runtime_bound_attempt",
        register_runtime,
    )
    monkeypatch.setattr(
        runner,
        "abort_runtime_bound_registration",
        lambda *args, **kwargs: {
            "registration_id": kwargs["registration_id"],
            "state": "aborted",
        },
    )
    monkeypatch.setattr(
        runner,
        "_runtime_registration_is_current",
        lambda **_: True,
    )
    monkeypatch.setattr(
        runner,
        "_runtime_registration_state",
        lambda **_: "terminated",
    )
    assert Path(str(context["ledger_path"])) == ledger_path.resolve()
    return calls


class _Server:
    def __init__(
        self,
        *,
        assertion: Callable[[], None] | None = None,
        fail: bool = False,
    ) -> None:
        self.started = False
        self.assertion = assertion
        self.fail = fail

    async def serve(self, *, sockets: object = None) -> None:
        assert sockets
        if self.fail:
            raise RuntimeError("offline startup failure")
        if self.assertion is not None:
            self.assertion()
        self.started = True


async def _asgi_request(
    application: object,
    *,
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, object]]:
    body = (
        json.dumps(payload).encode("utf-8")
        if payload is not None
        else b""
    )
    request_sent = False
    messages: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        nonlocal request_sent
        if request_sent:
            return {"type": "http.disconnect"}
        request_sent = True
        return {
            "type": "http.request",
            "body": body,
            "more_body": False,
        }

    async def send(message: dict[str, object]) -> None:
        messages.append(message)

    await application(  # type: ignore[operator]
        {
            "type": "http",
            "method": method,
            "path": path,
            "client": ("127.0.0.1", 45123),
            "headers": [
                (
                    name.lower().encode("ascii"),
                    value.encode("ascii"),
                )
                for name, value in (headers or {}).items()
            ],
        },
        receive,
        send,
    )
    status = next(
        int(message["status"])
        for message in messages
        if message.get("type") == "http.response.start"
    )
    response_body = b"".join(
        message.get("body", b"")
        for message in messages
        if message.get("type") == "http.response.body"
    )
    return status, (
        json.loads(response_body)
        if response_body
        else {}
    )


class _ProofProbeServer:
    def __init__(self, application: object) -> None:
        self.application = application
        self.started = False
        self.business_calls: list[str] = []

    async def serve(self, *, sockets: object = None) -> None:
        assert sockets
        self.started = True
        before_status, before = await _asgi_request(
            self.application,
            method="POST",
            path="/api/v1/chat/stream",
            payload={"message": "must stay blocked"},
        )
        registration = self.application._application._registration
        request = {
            "schema_version": (
                "guide-bound-runtime-proof-request-v1"
            ),
            **{
                key: registration[key]
                for key in (
                    "registration_id",
                    "phase",
                    "attempt_id",
                    "attempt_context_sha256",
                    "readiness_sha256",
                    "allocated_ledger_revision",
                    "allocated_ledger_hash",
                    "runtime_identity_sha256",
                )
            },
            "verifier_nonce": "f" * 64,
        }
        proof_status, proof = await _asgi_request(
            self.application,
            method="POST",
            path="/__task11_runtime__/proof",
            payload=request,
        )
        after_status, _ = await _asgi_request(
            self.application,
            method="POST",
            path="/api/v1/chat/stream",
            payload={"message": "must remain blocked"},
        )

        assert before_status == 409
        assert before == {"error": "runtime_proof_required"}
        assert proof_status == 200
        assert proof["registration_id"] == registration["registration_id"]
        assert after_status == 403


def test_import_does_not_load_application_or_start_runtime() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys;"
                "import tools.guide_gates.run_bound_runtime;"
                "assert 'app.guide_runtime.app' not in sys.modules"
            ),
        ],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_bound_runtime_declares_and_uses_asymmetric_runtime_proofs() -> None:
    root = Path(__file__).resolve().parents[3]
    requirements = (
        root / "requirements-guide-runtime.txt"
    ).read_text(encoding="utf-8").splitlines()
    ledger_source = (
        root / "tools/guide_gates/attempt_ledger.py"
    ).read_text(encoding="utf-8")
    runtime_source = (
        root / "tools/guide_gates/run_bound_runtime.py"
    ).read_text(encoding="utf-8")
    assert "cryptography==49.0.0" in requirements
    assert (
        root / "tools/guide_gates/runtime_auth.py"
    ).is_file()
    assert "consumed_health_challenge_sha256" not in ledger_source
    assert "/__task11_runtime__/challenge" not in runtime_source
    assert "_ChallengeGatedApplication" not in runtime_source
    assert "runtime_health_challenge_required" not in runtime_source

    runtime_auth = importlib.import_module(
        "tools.guide_gates.runtime_auth"
    )
    private_key, public_key = runtime_auth.generate_runtime_keypair()
    request = {
        "schema_version": "guide-bound-runtime-proof-request-v1",
        "registration_id": "runtime_0123456789abcdef",
        "phase": "bounded",
        "attempt_id": "bounded-smoke-attempt-07",
        "attempt_context_sha256": "a" * 64,
        "readiness_sha256": "b" * 64,
        "allocated_ledger_revision": 4,
        "allocated_ledger_hash": "c" * 64,
        "runtime_identity_sha256": "d" * 64,
        "verifier_nonce": "e" * 64,
    }
    proof = runtime_auth.sign_runtime_proof(
        private_key=private_key,
        public_key=public_key,
        request=request,
    )

    assert runtime_auth.verify_runtime_proof(
        proof=proof,
        expected_request=request,
        expected_public_key=public_key,
    ) == proof
    forged = dict(proof)
    forged["signature"] = proof["signature"][::-1]
    with pytest.raises(
        runtime_auth.RuntimeProofError,
        match="signature",
    ):
        runtime_auth.verify_runtime_proof(
            proof=forged,
            expected_request=request,
            expected_public_key=public_key,
        )


def test_runtime_verifies_all_authority_before_loading_application(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _runner()
    context_path, ledger_path, context, readiness = _verified_inputs(
        tmp_path
    )
    calls = _install_verified_apis(
        monkeypatch,
        runner,
        context=context,
        readiness=readiness,
        ledger_path=ledger_path,
    )
    key_path = _write_key(tmp_path / "api-key")
    state_dir = tmp_path / "state"
    observed_environment: dict[str, str | None] = {}

    def load_application() -> object:
        calls.append("application")
        for name in runner.BOUND_PROVIDER_ENVIRONMENT:
            observed_environment[name] = os.environ.get(name)
        return object()

    identity = runner.run_bound_runtime(
        attempt_context=context_path,
        host="127.0.0.1",
        port=8821,
        state_dir=state_dir,
        key_path=key_path,
        application_loader=load_application,
        server_factory=lambda application, host, port: _Server(
            assertion=lambda: calls.append("server")
        ),
    )

    assert calls == [
        "context",
        "readiness",
        "ledger",
        "registration",
        "application",
        "server",
    ]
    assert observed_environment == {
        "GUIDE_LLM_API_KEY": _SECRET,
        "GUIDE_LLM_BASE_URL": "https://api.deepseek.com",
        "GUIDE_LLM_MODEL": "deepseek-v4-pro",
        "GUIDE_LLM_TIMEOUT_SECONDS": "30",
        "GUIDE_LLM_MAX_TOKENS": "1024",
        "GUIDE_LLM_DAILY_BUDGET_CNY": "3.00",
        "GUIDE_LLM_DAILY_CALL_CAP": "9",
        "GUIDE_LLM_FORMAT_REPAIR_ATTEMPTS": "0",
        "GUIDE_COPY_LLM_API_KEY": _SECRET,
        "GUIDE_COPY_LLM_BASE_URL": "https://api.deepseek.com",
        "GUIDE_COPY_LLM_MODEL": "deepseek-v4-pro",
        "GUIDE_COPY_LLM_TIMEOUT_SECONDS": "30",
        "GUIDE_COPY_LLM_MAX_TOKENS": "1536",
        "GUIDE_COPY_LLM_TEMPERATURE": "0.3",
        "GUIDE_COPY_LLM_DAILY_BUDGET_CNY": "3.00",
        "GUIDE_COPY_LLM_DAILY_CALL_CAP": "9",
    }
    assert identity["schema_version"] == (
        "guide-bound-runtime-identity-v1"
    )
    assert identity["phase"] == "bounded"
    assert identity["attempt_id"] == "bounded-smoke-attempt-07"
    assert identity["readiness_sha256"] == sha256(
        Path(str(context["readiness_path"])).read_bytes()
    ).hexdigest()
    assert identity["candidate_manifest_sha256"] == (
        readiness["evidence_sha256"]["candidate_manifest"]
    )
    assert identity["independent_audit_sha256"] == (
        readiness["evidence_sha256"]["independent_audit"]
    )
    assert identity["provider_limits"] == {
        "copywriter": {
            "daily_budget_cny": "3.00",
            "daily_call_cap": 9,
            "max_tokens": 1536,
            "timeout_seconds": 30,
        },
        "turn_meaning": {
            "daily_budget_cny": "3.00",
            "daily_call_cap": 9,
            "format_repair_attempts": 0,
            "max_tokens": 1024,
            "timeout_seconds": 30,
        },
    }
    identity_path = Path(str(context["output_directory"])) / (
        "runtime-identity.json"
    )
    assert json.loads(identity_path.read_text(encoding="utf-8")) == identity
    assert runner.verify_bound_runtime_identity(
        identity_path=identity_path,
        attempt_context=context_path,
        expected_host="127.0.0.1",
        expected_port=8821,
    ) == identity
    assert stat.S_IMODE(identity_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(state_dir.stat().st_mode) == 0o700
    assert _SECRET not in identity_path.read_text(encoding="utf-8")


def test_runtime_blocks_business_without_proof_capability(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _runner()
    context_path, ledger_path, context, readiness = _verified_inputs(
        tmp_path
    )
    _install_verified_apis(
        monkeypatch,
        runner,
        context=context,
        readiness=readiness,
        ledger_path=ledger_path,
    )
    business_calls: list[str] = []

    async def application(scope, receive, send) -> None:
        del receive
        business_calls.append(str(scope["path"]))
        await send({
            "type": "http.response.start",
            "status": 204,
            "headers": [],
        })
        await send({"type": "http.response.body", "body": b""})

    runner.run_bound_runtime(
        attempt_context=context_path,
        host="127.0.0.1",
        port=8821,
        state_dir=tmp_path / "state",
        key_path=_write_key(tmp_path / "api-key"),
        application_loader=lambda: application,
        server_factory=lambda application, host, port: (
            _ProofProbeServer(application)
        ),
    )

    assert business_calls == []


def test_runtime_requires_proof_capability_and_consumed_ledger() -> None:
    runner = _runner()
    consumed = False
    business_calls: list[str] = []
    capability = "a" * 64

    async def application(scope, receive, send) -> None:
        del receive
        business_calls.append(str(scope["path"]))
        await send({
            "type": "http.response.start",
            "status": 204,
            "headers": [],
        })
        await send({"type": "http.response.body", "body": b""})

    class SignedProofState:
        proof_issued = True

        @staticmethod
        def accepts_business_capability(value: str) -> bool:
            return value == capability

        async def __call__(self, scope, receive, send) -> None:
            await application(scope, receive, send)

    @contextmanager
    def request_lifecycle():
        yield

    def check_authority() -> None:
        if not consumed:
            raise attempt_ledger.AttemptLedgerError(
                "attempt is not consumed"
            )

    guarded = runner._ProofGatedApplication(
        SignedProofState(),
        attempt_authority_check=check_authority,
        request_lifecycle_lease=request_lifecycle,
    )

    async def exercise() -> tuple[int, int, int, int]:
        nonlocal consumed
        blocked_status, _ = await _asgi_request(
            guarded,
            method="POST",
            path="/api/v1/chat/stream",
            headers={"X-Task11-Runtime-Proof": capability},
        )
        consumed = True
        missing_status, _ = await _asgi_request(
            guarded,
            method="POST",
            path="/api/v1/chat/stream",
        )
        forged_status, _ = await _asgi_request(
            guarded,
            method="POST",
            path="/api/v1/chat/stream",
            headers={"X-Task11-Runtime-Proof": "b" * 64},
        )
        allowed_status, _ = await _asgi_request(
            guarded,
            method="POST",
            path="/api/v1/chat/stream",
            headers={"X-Task11-Runtime-Proof": capability},
        )
        return (
            blocked_status,
            missing_status,
            forged_status,
            allowed_status,
        )

    assert asyncio.run(exercise()) == (409, 403, 403, 204)
    assert business_calls == ["/api/v1/chat/stream"]


def test_runtime_shell_assets_do_not_take_business_authority_lease() -> None:
    runner = _runner()
    application_calls: list[str] = []
    lease_events: list[str] = []
    capability = "a" * 64

    async def application(scope, receive, send) -> None:
        del receive
        application_calls.append(str(scope["path"]))
        await send({
            "type": "http.response.start",
            "status": 204,
            "headers": [],
        })
        await send({"type": "http.response.body", "body": b""})

    class SignedProofState:
        proof_issued = True

        @staticmethod
        def accepts_business_capability(value: str) -> bool:
            return value == capability

        async def __call__(self, scope, receive, send) -> None:
            await application(scope, receive, send)

    class Lease:
        def __enter__(self) -> None:
            lease_events.append("enter")

        def __exit__(self, *_: object) -> None:
            lease_events.append("exit")

    guarded = runner._ProofGatedApplication(
        SignedProofState(),
        attempt_authority_check=lambda: None,
        request_lifecycle_lease=Lease,
    )

    async def exercise() -> tuple[int, int, int]:
        headers = {"X-Task11-Runtime-Proof": capability}
        chat_status, _ = await _asgi_request(
            guarded,
            method="GET",
            path="/chat",
            headers=headers,
        )
        static_status, _ = await _asgi_request(
            guarded,
            method="GET",
            path="/static/guide-presentation.js",
            headers=headers,
        )
        api_status, _ = await _asgi_request(
            guarded,
            method="POST",
            path="/api/v1/chat/stream",
            headers=headers,
        )
        return chat_status, static_status, api_status

    assert asyncio.run(exercise()) == (204, 204, 204)
    assert application_calls == [
        "/chat",
        "/static/guide-presentation.js",
        "/api/v1/chat/stream",
    ]
    assert lease_events == ["enter", "exit"]


def test_runtime_releases_ledger_lock_before_entering_application() -> None:
    runner = _runner()
    events: list[str] = []
    capability = "a" * 64

    async def application(scope, receive, send) -> None:
        del scope, receive
        events.append("application")
        assert events == [
            "lifecycle_enter",
            "authority_enter",
            "authority_exit",
            "application",
        ]
        await send({
            "type": "http.response.start",
            "status": 204,
            "headers": [],
        })
        await send({"type": "http.response.body", "body": b""})

    class SignedProofState:
        proof_issued = True

        @staticmethod
        def accepts_business_capability(value: str) -> bool:
            return value == capability

        async def __call__(self, scope, receive, send) -> None:
            await application(scope, receive, send)

    @contextmanager
    def request_lifecycle():
        events.append("lifecycle_enter")
        try:
            yield
        finally:
            events.append("lifecycle_exit")

    def check_authority() -> None:
        events.append("authority_enter")
        events.append("authority_exit")

    guarded = runner._ProofGatedApplication(
        SignedProofState(),
        attempt_authority_check=check_authority,
        request_lifecycle_lease=request_lifecycle,
    )

    status, _ = asyncio.run(
        _asgi_request(
            guarded,
            method="POST",
            path="/api/v1/chat/stream",
            headers={"X-Task11-Runtime-Proof": capability},
        )
    )

    assert status == 204
    assert events == [
        "lifecycle_enter",
        "authority_enter",
        "authority_exit",
        "application",
        "lifecycle_exit",
    ]


def test_runtime_version_check_uses_lightweight_authority_check() -> None:
    runner = _runner()
    authority_calls: list[str] = []
    capability = "a" * 64

    async def application(scope, receive, send) -> None:
        del receive
        assert authority_calls == ["checked"]
        assert scope["path"] == (
            "/api/v1/chat/sessions/session-01/version"
        )
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [],
        })
        await send({
            "type": "http.response.body",
            "body": b'{"conversation_version":0}',
        })

    class SignedProofState:
        proof_issued = True

        @staticmethod
        def accepts_business_capability(value: str) -> bool:
            return value == capability

        async def __call__(self, scope, receive, send) -> None:
            await application(scope, receive, send)

    @contextmanager
    def request_lifecycle():
        yield

    guarded = runner._ProofGatedApplication(
        SignedProofState(),
        attempt_authority_check=lambda: authority_calls.append("checked"),
        request_lifecycle_lease=request_lifecycle,
    )

    status, body = asyncio.run(
        _asgi_request(
            guarded,
            method="GET",
            path="/api/v1/chat/sessions/session-01/version",
            headers={"X-Task11-Runtime-Proof": capability},
        )
    )

    assert status == 200
    assert body == {"conversation_version": 0}
    assert authority_calls == ["checked"]


def test_unregistered_runtime_rejects_control_and_business_requests() -> None:
    runner = _runner()
    business_calls: list[str] = []

    async def application(scope, receive, send) -> None:
        del receive
        business_calls.append(str(scope["path"]))
        await send({
            "type": "http.response.start",
            "status": 204,
            "headers": [],
        })
        await send({"type": "http.response.body", "body": b""})

    guarded = runner._ProofGatedApplication(
        application,
        registration_is_current=lambda: False,
    )

    async def exercise() -> tuple[int, int]:
        challenge_status, _ = await _asgi_request(
            guarded,
            method="POST",
            path="/__task11_runtime__/proof",
            payload={},
        )
        business_status, _ = await _asgi_request(
            guarded,
            method="POST",
            path="/api/v1/chat/stream",
        )
        return challenge_status, business_status

    assert asyncio.run(exercise()) == (503, 503)
    assert business_calls == []


def test_bound_runtime_proof_is_signed_by_registered_private_key() -> None:
    runner = _runner()
    runtime_auth = importlib.import_module(
        "tools.guide_gates.runtime_auth"
    )
    private_key, public_key = runtime_auth.generate_runtime_keypair()
    registration = {
        "registration_id": "runtime_0123456789abcdef",
        "phase": "bounded",
        "attempt_id": "bounded-smoke-attempt-07",
        "attempt_context_sha256": "a" * 64,
        "readiness_sha256": "b" * 64,
        "allocated_ledger_revision": 4,
        "allocated_ledger_hash": "c" * 64,
        "runtime_identity_sha256": "d" * 64,
        "runtime_public_key": public_key,
    }
    application = runner._BoundRuntimeProofApplication(
        object(),
        private_key=private_key,
        registration=registration,
    )
    request = {
        "schema_version": runtime_auth.PROOF_REQUEST_SCHEMA,
        **{
            key: registration[key]
            for key in (
                "registration_id",
                "phase",
                "attempt_id",
                "attempt_context_sha256",
                "readiness_sha256",
                "allocated_ledger_revision",
                "allocated_ledger_hash",
                "runtime_identity_sha256",
            )
        },
        "verifier_nonce": "e" * 64,
    }

    status, proof = asyncio.run(
        _asgi_request(
            application,
            method="POST",
            path="/__task11_runtime__/proof",
            payload=request,
        )
    )

    assert status == 200
    assert runtime_auth.verify_runtime_proof(
        proof=proof,
        expected_request=request,
        expected_public_key=public_key,
    ) == proof
    proof_sha256 = sha256(
        runner._canonical_bytes(proof)
    ).hexdigest()
    assert application.accepts_business_capability(proof_sha256)
    assert not application.accepts_business_capability("f" * 64)
    second_request = {
        **request,
        "verifier_nonce": "f" * 64,
    }
    second_status, second_payload = asyncio.run(
        _asgi_request(
            application,
            method="POST",
            path="/__task11_runtime__/proof",
            payload=second_request,
        )
    )
    assert second_status == 409
    assert second_payload == {
        "error": "runtime proof was already issued"
    }


def test_bound_runtime_proof_round_trips_over_real_loopback_socket() -> None:
    import uvicorn

    runner = _runner()
    runtime_auth = importlib.import_module(
        "tools.guide_gates.runtime_auth"
    )
    private_key, public_key = runtime_auth.generate_runtime_keypair()
    registration = {
        "registration_id": "runtime_0123456789abcdef",
        "phase": "bounded",
        "attempt_id": "bounded-smoke-attempt-07",
        "attempt_context_sha256": "a" * 64,
        "readiness_sha256": "b" * 64,
        "allocated_ledger_revision": 4,
        "allocated_ledger_hash": "c" * 64,
        "runtime_identity_sha256": "d" * 64,
        "runtime_public_key": public_key,
    }
    application = runner._BoundRuntimeProofApplication(
        object(),
        private_key=private_key,
        registration=registration,
    )
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(socket.SOMAXCONN)
    listener.setblocking(False)
    port = int(listener.getsockname()[1])
    server = uvicorn.Server(
        uvicorn.Config(
            application,
            log_level="error",
            lifespan="off",
        )
    )
    thread = Thread(
        target=lambda: asyncio.run(server.serve(sockets=[listener])),
        daemon=True,
    )
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started
    request = {
        "schema_version": runtime_auth.PROOF_REQUEST_SCHEMA,
        **{
            key: registration[key]
            for key in (
                "registration_id",
                "phase",
                "attempt_id",
                "attempt_context_sha256",
                "readiness_sha256",
                "allocated_ledger_revision",
                "allocated_ledger_hash",
                "runtime_identity_sha256",
            )
        },
        "verifier_nonce": "e" * 64,
    }
    try:
        proof = attempt_ledger._request_live_runtime_proof(
            host="127.0.0.1",
            port=port,
            request=request,
        )
        assert runtime_auth.verify_runtime_proof(
            proof=proof,
            expected_request=request,
            expected_public_key=public_key,
        ) == proof
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
    assert not thread.is_alive()


def test_bound_runtime_registers_and_consumes_real_http_proof(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import uvicorn

    runner = _runner()
    (
        context_path,
        ledger_path,
        context,
        readiness,
        manifest,
        audit,
    ) = _allocated_runtime_inputs(tmp_path)
    attempt_id = str(context["phase_attempt_ids"]["bounded"])
    monkeypatch.setattr(
        attempt_ledger,
        "_verify_current_readiness",
        lambda **_: None,
    )
    monkeypatch.setattr(
        attempt_ledger,
        "_capture_readiness_binding",
        lambda path: (sha256(Path(path).read_bytes()).hexdigest(), ()),
    )
    monkeypatch.setattr(
        runner,
        "verify_task11_readiness",
        lambda **_: readiness,
    )
    monkeypatch.setattr(
        runner,
        "_bound_evidence",
        lambda **_: (
            context,
            readiness,
            manifest,
            audit,
            "bounded",
            attempt_id,
        ),
    )

    async def application(scope, receive, send) -> None:
        del scope, receive
        await send({
            "type": "http.response.start",
            "status": 204,
            "headers": [],
        })
        await send({"type": "http.response.body", "body": b""})

    servers: list[object] = []

    def server_factory(application, host: str, port: int):
        server = uvicorn.Server(
            uvicorn.Config(
                application,
                host=host,
                port=port,
                log_level="error",
                lifespan="off",
            )
        )
        servers.append(server)
        return server

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = int(probe.getsockname()[1])
    probe.close()
    errors: list[BaseException] = []

    def serve() -> None:
        try:
            runner.run_bound_runtime(
                attempt_context=context_path,
                host="127.0.0.1",
                port=port,
                state_dir=tmp_path / "state",
                key_path=_write_key(tmp_path / "api-key"),
                application_loader=lambda: application,
                server_factory=server_factory,
            )
        except BaseException as error:
            errors.append(error)

    thread = Thread(target=serve, daemon=True)
    thread.start()
    identity_path = context_path.parent / "runtime-identity.json"
    deadline = (
        time.monotonic()
        + runner.BOUND_STARTUP_TIMEOUT_SECONDS
        + 15
    )
    while (
        (not identity_path.is_file() or not servers)
        and not errors
        and time.monotonic() < deadline
    ):
        time.sleep(0.01)
    assert identity_path.is_file(), errors
    assert servers

    runtime_proof = attempt_ledger.consume_runtime_bound_attempt(
        context_path,
        phase="bounded",
        ledger_path=ledger_path,
        readiness_path=Path(str(context["readiness_path"])),
        base_url=f"http://127.0.0.1:{port}",
    )
    connection = http.client.HTTPConnection(
        "127.0.0.1",
        port,
        timeout=5,
    )
    try:
        connection.request(
            "POST",
            "/api/v1/chat/stream",
            body=b"{}",
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        response.read()
        assert response.status == 403
        connection.request(
            "POST",
            "/api/v1/chat/stream",
            body=b"{}",
            headers={
                "Content-Type": "application/json",
                "X-Task11-Runtime-Proof": runtime_proof[
                    "runtime_proof_sha256"
                ],
            },
        )
        response = connection.getresponse()
        response.read()
        assert response.status == 204
    finally:
        connection.close()
        servers[0].should_exit = True
        thread.join(timeout=10)

    stored = attempt_ledger.read_ledger(ledger_path)
    attempt = stored["attempts"][-1]
    assert runtime_proof["runtime_proof_sha256"] == (
        attempt["runtime_proof_sha256"]
    )
    assert attempt["result"] == "consumed"
    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], runner.BoundRuntimeError)
    assert "before attempt completion" in str(errors[0])
    _, replacement_public_key = (
        importlib.import_module(
            "tools.guide_gates.runtime_auth"
        ).generate_runtime_keypair()
    )
    with pytest.raises(
        attempt_ledger.AttemptLedgerError,
        match="active runtime registration",
    ):
        attempt_ledger.register_runtime_bound_attempt(
            context_path,
            phase="bounded",
            ledger_path=ledger_path,
            readiness_path=Path(str(context["readiness_path"])),
            registration_id="runtime_abcdef0123456789",
            runtime_identity_sha256="9" * 64,
            runtime_public_key=replacement_public_key,
            host="127.0.0.1",
            port=port,
        )


def test_bound_runtime_has_no_parallel_consumed_check() -> None:
    runner = _runner()
    assert not hasattr(runner, "_bound_attempt_is_consumed")


def test_plan_environment_is_accepted_but_limits_are_not_overridable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _runner()
    context_path, ledger_path, context, readiness = _verified_inputs(
        tmp_path
    )
    _install_verified_apis(
        monkeypatch,
        runner,
        context=context,
        readiness=readiness,
        ledger_path=ledger_path,
    )
    environment = {
        "GUIDE_LLM_API_KEY": _SECRET,
        "GUIDE_COPY_LLM_API_KEY": _SECRET,
        "GUIDE_LLM_BASE_URL": "https://api.deepseek.com",
        "GUIDE_LLM_MODEL": "deepseek-v4-pro",
        "GUIDE_LLM_FORMAT_REPAIR_ATTEMPTS": "0",
        "GUIDE_COPY_LLM_BASE_URL": "https://api.deepseek.com",
        "GUIDE_COPY_LLM_MODEL": "deepseek-v4-pro",
    }

    runner.run_bound_runtime(
        attempt_context=context_path,
        host="127.0.0.1",
        port=8821,
        state_dir=tmp_path / "state",
        environ=environment,
        application_loader=object,
        server_factory=lambda application, host, port: _Server(),
    )

    context_path, ledger_path, context, readiness = _verified_inputs(
        tmp_path / "second"
    )
    _install_verified_apis(
        monkeypatch,
        runner,
        context=context,
        readiness=readiness,
        ledger_path=ledger_path,
    )
    environment["GUIDE_LLM_DAILY_CALL_CAP"] = "10"
    with pytest.raises(
        runner.BoundRuntimeError,
        match="fixed provider setting",
    ):
        runner.run_bound_runtime(
            attempt_context=context_path,
            host="127.0.0.1",
            port=8821,
            state_dir=tmp_path / "second-state",
            environ=environment,
            application_loader=lambda: pytest.fail(
                "application must not load"
            ),
            server_factory=lambda application, host, port: pytest.fail(
                "server must not start"
            ),
        )


def test_invalid_readiness_fails_before_key_or_application(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _runner()
    context_path, ledger_path, context, readiness = _verified_inputs(
        tmp_path
    )
    calls = _install_verified_apis(
        monkeypatch,
        runner,
        context=context,
        readiness=readiness,
        ledger_path=ledger_path,
    )

    def reject_readiness(**kwargs):
        del kwargs
        calls.append("readiness-rejected")
        raise ValueError("readiness rejected")

    monkeypatch.setattr(
        runner,
        "verify_task11_readiness",
        reject_readiness,
    )
    monkeypatch.setattr(
        runner,
        "read_private_api_key",
        lambda path: pytest.fail("key must not be read"),
    )

    with pytest.raises(ValueError, match="readiness rejected"):
        runner.run_bound_runtime(
            attempt_context=context_path,
            host="127.0.0.1",
            port=8821,
            state_dir=tmp_path / "state",
            key_path=tmp_path / "missing-key",
            application_loader=lambda: pytest.fail(
                "application must not load"
            ),
            server_factory=lambda application, host, port: pytest.fail(
                "server must not start"
            ),
        )

    assert calls == ["context", "readiness-rejected"]
    assert not (tmp_path / "state").exists()


def test_independent_audit_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _runner()
    context_path, ledger_path, context, readiness = _verified_inputs(
        tmp_path
    )
    _install_verified_apis(
        monkeypatch,
        runner,
        context=context,
        readiness=readiness,
        ledger_path=ledger_path,
    )
    audit = Path(
        str(readiness["evidence_files"]["independent_audit"])
    )
    audit.write_text("{}\n", encoding="utf-8")

    with pytest.raises(
        runner.BoundRuntimeError,
        match="independent audit",
    ):
        runner.run_bound_runtime(
            attempt_context=context_path,
            host="127.0.0.1",
            port=8821,
            state_dir=tmp_path / "state",
            key_path=tmp_path / "missing-key",
            application_loader=lambda: pytest.fail(
                "application must not load"
            ),
            server_factory=lambda application, host, port: pytest.fail(
                "server must not start"
            ),
        )


@pytest.mark.parametrize(
    ("attempt_result", "authorization_state"),
    [("consumed", "allocated"), ("allocated", "consumed")],
)
def test_runtime_rejects_nonfresh_attempt_without_consuming_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    attempt_result: str,
    authorization_state: str,
) -> None:
    runner = _runner()
    context_path, ledger_path, context, readiness = _verified_inputs(
        tmp_path
    )
    _install_verified_apis(
        monkeypatch,
        runner,
        context=context,
        readiness=readiness,
        ledger_path=ledger_path,
    )
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["attempts"][0]["result"] = attempt_result
    ledger["authorizations"][0]["state"] = authorization_state
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    before = ledger_path.read_bytes()

    with pytest.raises(
        runner.BoundRuntimeError,
        match="fresh allocated attempt",
    ):
        runner.run_bound_runtime(
            attempt_context=context_path,
            host="127.0.0.1",
            port=8821,
            state_dir=tmp_path / "state",
            key_path=tmp_path / "missing-key",
            application_loader=lambda: pytest.fail(
                "application must not load"
            ),
            server_factory=lambda application, host, port: pytest.fail(
                "server must not start"
            ),
        )
    assert ledger_path.read_bytes() == before


def test_runtime_uses_current_plan_circuit_not_global_history(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _runner()
    context_path, ledger_path, context, readiness = _verified_inputs(
        tmp_path
    )
    calls = _install_verified_apis(
        monkeypatch,
        runner,
        context=context,
        readiness=readiness,
        ledger_path=ledger_path,
    )
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["circuit_state"] = "open"
    ledger["attempts"][0]["plan_revision"] = _PLAN_REVISION
    ledger["authorizations"][0]["plan_revision"] = _PLAN_REVISION
    ledger["attempts"][:0] = [
        {
            "attempt_id": "bounded-smoke-attempt-01",
            "plan_revision": "2026-08-22-task11-r1",
            "trajectory_set": "bounded",
            "result": "failed",
            "first_failure_owner": "planning_state",
        },
        {
            "attempt_id": "bounded-smoke-attempt-02",
            "plan_revision": "2026-08-22-task11-r1",
            "trajectory_set": "bounded",
            "result": "failed",
            "first_failure_owner": "planning_state",
        },
    ]
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    runner.run_bound_runtime(
        attempt_context=context_path,
        host="127.0.0.1",
        port=8821,
        state_dir=tmp_path / "state",
        key_path=_write_key(tmp_path / "api-key"),
        application_loader=lambda: calls.append("application") or object(),
        server_factory=lambda application, host, port: _Server(),
    )

    assert calls[-1] == "application"


def test_browser_runtime_accepts_release_readiness_candidate_base(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _runner()
    context_path, ledger_path, context, readiness = _verified_inputs(
        tmp_path
    )
    release_head = "c" * 40
    readiness.update({
        "schema_version": "guide-task11-release-readiness-v1",
        "candidate_head": release_head,
        "task11_commit": release_head,
        "candidate_base_head": _HEAD,
    })
    Path(str(context["readiness_path"])).write_text(
        json.dumps(readiness, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    context["readiness_sha256"] = sha256(
        Path(str(context["readiness_path"])).read_bytes()
    ).hexdigest()
    context_path.write_text(
        json.dumps(context, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["attempts"][0].update({
        "plan_revision": _PLAN_REVISION,
        "trajectory_set": "browser",
    })
    ledger["authorizations"][0].update({
        "plan_revision": _PLAN_REVISION,
        "phase": "browser",
    })
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    context["phase_attempt_ids"] = {
        "translation": "translation-attempt-01",
        "browser": "bounded-smoke-attempt-07",
    }
    context["current_phase"] = "browser"
    context["phase_authorization_ids"] = {
        "translation": "auth-translation",
        "browser": "auth-07",
    }
    context_path.write_text(
        json.dumps(context, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    calls = _install_verified_apis(
        monkeypatch,
        runner,
        context=context,
        readiness=readiness,
        ledger_path=ledger_path,
    )
    observed_limits: dict[str, str | None] = {}

    def load_application() -> object:
        calls.append("application")
        observed_limits["turn"] = os.environ.get(
            "GUIDE_LLM_DAILY_CALL_CAP"
        )
        observed_limits["copy"] = os.environ.get(
            "GUIDE_COPY_LLM_DAILY_CALL_CAP"
        )
        return object()

    identity = runner.run_bound_runtime(
        attempt_context=context_path,
        host="127.0.0.1",
        port=8821,
        state_dir=tmp_path / "state",
        key_path=_write_key(tmp_path / "api-key"),
        application_loader=load_application,
        server_factory=lambda application, host, port: _Server(),
    )

    assert calls[-1] == "application"
    assert observed_limits == {"turn": "14", "copy": "14"}
    assert identity["code_revision"] == release_head
    assert runner.verify_bound_runtime_identity(
        identity_path=(
            Path(str(context["output_directory"]))
            / "runtime-identity.json"
        ),
        attempt_context=context_path,
        expected_host="127.0.0.1",
        expected_port=8821,
    ) == identity


def test_runtime_rejects_non_loopback_before_authority_checks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _runner()
    monkeypatch.setattr(
        runner,
        "read_attempt_context",
        lambda *args, **kwargs: pytest.fail(
            "authority must not be read for unsafe bind"
        ),
    )

    with pytest.raises(runner.BoundRuntimeError, match="loopback"):
        runner.run_bound_runtime(
            attempt_context=tmp_path / "missing-context",
            host="0.0.0.0",
            port=8821,
            state_dir=tmp_path / "state",
        )


def test_server_startup_failure_writes_no_runtime_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _runner()
    context_path, ledger_path, context, readiness = _verified_inputs(
        tmp_path
    )
    _install_verified_apis(
        monkeypatch,
        runner,
        context=context,
        readiness=readiness,
        ledger_path=ledger_path,
    )
    monkeypatch.setattr(
        runner,
        "_runtime_registration_state",
        lambda **_: "registered",
    )
    key_path = _write_key(tmp_path / "api-key")

    with pytest.raises(RuntimeError, match="offline startup failure"):
        runner.run_bound_runtime(
            attempt_context=context_path,
            host="127.0.0.1",
            port=8821,
            state_dir=tmp_path / "state",
            key_path=key_path,
            application_loader=object,
            server_factory=lambda application, host, port: _Server(
                fail=True
            ),
        )

    assert not (
        Path(str(context["output_directory"]))
        / "runtime-identity.json"
    ).exists()


def test_server_startup_abort_failure_is_not_swallowed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _runner()
    context_path, ledger_path, context, readiness = _verified_inputs(
        tmp_path
    )
    _install_verified_apis(
        monkeypatch,
        runner,
        context=context,
        readiness=readiness,
        ledger_path=ledger_path,
    )
    monkeypatch.setattr(
        runner,
        "_runtime_registration_state",
        lambda **_: "registered",
    )

    def reject_abort(*args, **kwargs):
        del args, kwargs
        raise runner.BoundRuntimeError("runtime registration abort failed")

    monkeypatch.setattr(
        runner,
        "abort_runtime_bound_registration",
        reject_abort,
    )

    with pytest.raises(
        runner.BoundRuntimeError,
        match="runtime registration abort failed",
    ):
        runner.run_bound_runtime(
            attempt_context=context_path,
            host="127.0.0.1",
            port=8821,
            state_dir=tmp_path / "state",
            key_path=_write_key(tmp_path / "api-key"),
            application_loader=object,
            server_factory=lambda application, host, port: _Server(
                fail=True
            ),
        )


def test_occupied_port_fails_before_runtime_registration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _runner()
    context_path, ledger_path, context, readiness = _verified_inputs(
        tmp_path
    )
    _install_verified_apis(
        monkeypatch,
        runner,
        context=context,
        readiness=readiness,
        ledger_path=ledger_path,
    )
    registrations: list[str] = []
    monkeypatch.setattr(
        runner,
        "register_runtime_bound_attempt",
        lambda *args, **kwargs: registrations.append("registered"),
        raising=False,
    )
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = int(listener.getsockname()[1])
    try:
        with pytest.raises(
            runner.BoundRuntimeError,
            match="listen socket",
        ):
            runner.run_bound_runtime(
                attempt_context=context_path,
                host="127.0.0.1",
                port=port,
                state_dir=tmp_path / "state",
                key_path=_write_key(tmp_path / "api-key"),
                application_loader=lambda: pytest.fail(
                    "application must not load"
                ),
                server_factory=lambda application, host, port: pytest.fail(
                    "server must not start"
                ),
            )
    finally:
        listener.close()

    assert registrations == []


def test_cli_surface_matches_the_task11_plan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _runner()
    observed: dict[str, object] = {}

    def fake_run(**kwargs):
        observed.update(kwargs)
        return {"passed": True}

    monkeypatch.setattr(runner, "run_bound_runtime", fake_run)

    assert runner.main(
        [
            "--attempt-context",
            str(tmp_path / "attempt-context.json"),
            "--host",
            "127.0.0.1",
            "--port",
            "8821",
            "--state-dir",
            str(tmp_path / "state"),
        ]
    ) == 0
    assert observed["attempt_context"] == (
        tmp_path / "attempt-context.json"
    )
    assert observed["host"] == "127.0.0.1"
    assert observed["port"] == 8821
    assert observed["state_dir"] == tmp_path / "state"
