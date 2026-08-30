"""Start the real Guide runtime only from a verified attempt context."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from hashlib import sha256
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import stat
import sys
from threading import Lock
from typing import Any

from tools.guide_gates.runtime_auth import (
    PROOF_REQUEST_SCHEMA,
    RuntimeProofError,
    generate_runtime_keypair,
    sign_runtime_proof,
    validate_runtime_public_key,
)
from tools.guide_gates.attempt_ledger import (
    AttemptLedgerError,
    abort_runtime_bound_registration,
    attempt_context_phase,
    read_attempt_context,
    read_ledger,
    register_runtime_bound_attempt,
    runtime_request_lifecycle_lease,
    validate_runtime_request_authority,
)
from tools.guide_gates.build_task11_readiness import (
    verify_task11_readiness,
)
from tools.guide_gates.private_api_key import (
    DEFAULT_KEY_PATH,
    KeyPrecheckError,
    read_private_api_key,
)
from tools.guide_gates.private_output_io import (
    open_private_path,
    verify_path_binding,
    write_json_fd,
)
BOUND_BASE_URL = "https://api.deepseek.com"
BOUND_MODEL = "deepseek-v4-pro"
BOUND_TURN_COUNT = 9
RELEASE_BROWSER_TURN_COUNT = 14
BOUND_PROVIDER_TIMEOUT_SECONDS = 30
BOUND_TURN_MEANING_MAX_TOKENS = 1024
BOUND_COPYWRITER_MAX_TOKENS = 1536
BOUND_DAILY_BUDGET_CNY = "3.00"
BOUND_FORMAT_REPAIR_ATTEMPTS = 0
BOUND_STARTUP_TIMEOUT_SECONDS = 30
RUNTIME_IDENTITY_FILENAME = "runtime-identity.json"
_RUNTIME_CONTROL_PATHS = frozenset({
    "/__task11_runtime__/proof",
    "/__task11_runtime__/shutdown",
})
_RUNTIME_PROOF_HEADER = b"x-task11-runtime-proof"

_FIXED_PROVIDER_ENVIRONMENT = {
    "GUIDE_LLM_BASE_URL": BOUND_BASE_URL,
    "GUIDE_LLM_MODEL": BOUND_MODEL,
    "GUIDE_LLM_TIMEOUT_SECONDS": str(
        BOUND_PROVIDER_TIMEOUT_SECONDS
    ),
    "GUIDE_LLM_MAX_TOKENS": str(
        BOUND_TURN_MEANING_MAX_TOKENS
    ),
    "GUIDE_LLM_DAILY_BUDGET_CNY": BOUND_DAILY_BUDGET_CNY,
    "GUIDE_LLM_DAILY_CALL_CAP": str(BOUND_TURN_COUNT),
    "GUIDE_LLM_FORMAT_REPAIR_ATTEMPTS": str(
        BOUND_FORMAT_REPAIR_ATTEMPTS
    ),
    "GUIDE_COPY_LLM_BASE_URL": BOUND_BASE_URL,
    "GUIDE_COPY_LLM_MODEL": BOUND_MODEL,
    "GUIDE_COPY_LLM_TIMEOUT_SECONDS": str(
        BOUND_PROVIDER_TIMEOUT_SECONDS
    ),
    "GUIDE_COPY_LLM_MAX_TOKENS": str(
        BOUND_COPYWRITER_MAX_TOKENS
    ),
    "GUIDE_COPY_LLM_TEMPERATURE": "0.3",
    "GUIDE_COPY_LLM_DAILY_BUDGET_CNY": BOUND_DAILY_BUDGET_CNY,
    "GUIDE_COPY_LLM_DAILY_CALL_CAP": str(BOUND_TURN_COUNT),
}
BOUND_PROVIDER_ENVIRONMENT = (
    "GUIDE_LLM_API_KEY",
    "GUIDE_LLM_BASE_URL",
    "GUIDE_LLM_MODEL",
    "GUIDE_LLM_TIMEOUT_SECONDS",
    "GUIDE_LLM_MAX_TOKENS",
    "GUIDE_LLM_DAILY_BUDGET_CNY",
    "GUIDE_LLM_DAILY_CALL_CAP",
    "GUIDE_LLM_FORMAT_REPAIR_ATTEMPTS",
    "GUIDE_COPY_LLM_API_KEY",
    "GUIDE_COPY_LLM_BASE_URL",
    "GUIDE_COPY_LLM_MODEL",
    "GUIDE_COPY_LLM_TIMEOUT_SECONDS",
    "GUIDE_COPY_LLM_MAX_TOKENS",
    "GUIDE_COPY_LLM_TEMPERATURE",
    "GUIDE_COPY_LLM_DAILY_BUDGET_CNY",
    "GUIDE_COPY_LLM_DAILY_CALL_CAP",
)
_FORBIDDEN_RUNTIME_ENVIRONMENT = (
    "GUIDE_DEMO_RELAX_COPYWRITER_VALIDATION",
)


class BoundRuntimeError(RuntimeError):
    """Raised before serving when bounded authority is incomplete."""


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _read_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BoundRuntimeError(f"{label} is invalid") from exc
    if not isinstance(payload, dict):
        raise BoundRuntimeError(f"{label} is invalid")
    return payload


def _file_sha256(path: Path) -> str:
    try:
        return sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise BoundRuntimeError("bound evidence is unavailable") from exc


def _validate_loopback(host: str, port: int) -> None:
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise BoundRuntimeError(
            "bound runtime host must be a loopback address"
        ) from exc
    if not address.is_loopback:
        raise BoundRuntimeError(
            "bound runtime host must be a loopback address"
        )
    if (
        not isinstance(port, int)
        or isinstance(port, bool)
        or not 1 <= port <= 65535
    ):
        raise BoundRuntimeError("bound runtime port is invalid")


@contextmanager
def _bound_listener(host: str, port: int):
    address = ipaddress.ip_address(host)
    family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
    listener = socket.socket(family, socket.SOCK_STREAM)
    try:
        listener.set_inheritable(False)
        listener.bind((address.compressed, port))
        listener.listen(socket.SOMAXCONN)
        listener.setblocking(False)
    except OSError as exc:
        listener.close()
        raise BoundRuntimeError(
            "bound runtime listen socket is unavailable"
        ) from exc
    try:
        yield listener
    finally:
        listener.close()


def _bound_evidence(
    *,
    context_path: Path,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    str,
    str,
]:
    raw_context = _read_object(context_path, label="attempt context")
    ledger_path = Path(str(raw_context.get("ledger_path")))
    readiness_path = Path(str(raw_context.get("readiness_path")))
    context = read_attempt_context(
        context_path,
        ledger_path=ledger_path,
        readiness_path=readiness_path,
    )
    readiness = verify_task11_readiness(
        readiness_path=readiness_path,
        ledger_path=ledger_path,
        expected_manifest_sha256=str(
            context.get("expected_manifest_sha256")
        ),
    )
    if (
        context.get("readiness_sha256")
        != _file_sha256(readiness_path)
    ):
        raise BoundRuntimeError("attempt readiness binding is invalid")

    files = readiness.get("evidence_files")
    hashes = readiness.get("evidence_sha256")
    if not isinstance(files, dict) or not isinstance(hashes, dict):
        raise BoundRuntimeError("readiness evidence binding is invalid")
    manifest_path = Path(str(files.get("candidate_manifest")))
    audit_path = Path(str(files.get("independent_audit")))
    if (
        hashes.get("candidate_manifest")
        != _file_sha256(manifest_path)
    ):
        raise BoundRuntimeError("candidate manifest binding is invalid")
    if (
        hashes.get("independent_audit")
        != _file_sha256(audit_path)
    ):
        raise BoundRuntimeError("independent audit binding is invalid")

    manifest = _read_object(
        manifest_path,
        label="candidate manifest",
    )
    audit = _read_object(audit_path, label="independent audit")
    expected_manifest_head = (
        readiness.get("candidate_base_head")
        if readiness.get("schema_version")
        == "guide-task11-release-readiness-v1"
        else readiness.get("candidate_head")
    )
    if (
        manifest.get("schema_version")
        != "guide-task11-candidate-manifest-v1"
        or manifest.get("plan_revision")
        != readiness.get("plan_revision")
        or manifest.get("candidate_head")
        != expected_manifest_head
        or manifest.get("protected_payload_sha256")
        != readiness.get("protected_payload_sha256")
    ):
        raise BoundRuntimeError("candidate manifest is invalid")
    if (
        audit.get("schema_version")
        != "guide-task11-independent-audit-v1"
        or audit.get("passed") is not True
        or audit.get("plan_revision")
        != readiness.get("plan_revision")
        or audit.get("protected_payload_sha256")
        != readiness.get("protected_payload_sha256")
    ):
        raise BoundRuntimeError("independent audit is invalid")

    phase_attempt_ids = context.get("phase_attempt_ids")
    phase_authorization_ids = context.get(
        "phase_authorization_ids"
    )
    if (
        not isinstance(phase_attempt_ids, dict)
        or not phase_attempt_ids
        or not isinstance(phase_authorization_ids, dict)
    ):
        raise BoundRuntimeError("attempt context phase is invalid")
    phase = attempt_context_phase(context)
    if phase not in {"bounded", "browser"}:
        raise BoundRuntimeError(
            "attempt context cannot start a bound runtime"
        )
    attempt_id = phase_attempt_ids.get(phase)
    authorization_id = phase_authorization_ids.get(phase)
    if (
        not isinstance(attempt_id, str)
        or not attempt_id
        or not isinstance(authorization_id, str)
        or not authorization_id
    ):
        raise BoundRuntimeError("attempt context phase is invalid")

    ledger = read_ledger(ledger_path)
    attempts = [
        item
        for item in ledger.get("attempts", ())
        if isinstance(item, dict)
        and item.get("attempt_id") == attempt_id
    ]
    authorizations = [
        item
        for item in ledger.get("authorizations", ())
        if isinstance(item, dict)
        and item.get("authorization_id") == authorization_id
    ]
    plan_revision = readiness.get("plan_revision")
    if (
        _plan_circuit_state(
            ledger,
            plan_revision=plan_revision,
        )
        != "closed"
        or len(attempts) != 1
        or len(authorizations) != 1
        or attempts[0].get("plan_revision") != plan_revision
        or authorizations[0].get("plan_revision") != plan_revision
        or attempts[0].get("trajectory_set") != phase
        or attempts[0].get("result") != "allocated"
        or attempts[0].get("retry_authorization_id")
        != authorization_id
        or authorizations[0].get("phase") != phase
        or authorizations[0].get("state") != "allocated"
        or authorizations[0].get("attempt_id") != attempt_id
    ):
        raise BoundRuntimeError(
            "bound runtime requires a fresh allocated attempt"
        )
    return context, readiness, manifest, audit, phase, attempt_id


def _plan_circuit_state(
    ledger: Mapping[str, object],
    *,
    plan_revision: object,
) -> str:
    failure_counts: dict[str, int] = {}
    attempts = ledger.get("attempts")
    if not isinstance(plan_revision, str) or not isinstance(attempts, list):
        return "open"
    for attempt in attempts:
        if (
            not isinstance(attempt, dict)
            or attempt.get("plan_revision") != plan_revision
        ):
            continue
        if attempt.get("result") == "unverifiable_history":
            return "open"
        if attempt.get("result") != "failed":
            continue
        owner = attempt.get("first_failure_owner")
        if not isinstance(owner, str) or not owner:
            return "open"
        failure_counts[owner] = failure_counts.get(owner, 0) + 1
    return (
        "open"
        if any(count >= 2 for count in failure_counts.values())
        else "closed"
    )


def _validated_environment(
    source: Mapping[str, str],
    *,
    key_path: str | Path,
    phase: str = "bounded",
) -> dict[str, str]:
    if any(name in source for name in _FORBIDDEN_RUNTIME_ENVIRONMENT):
        raise BoundRuntimeError(
            "forbidden runtime configuration is present"
        )
    fixed_environment = dict(_FIXED_PROVIDER_ENVIRONMENT)
    if phase == "browser":
        fixed_environment["GUIDE_LLM_DAILY_CALL_CAP"] = str(
            RELEASE_BROWSER_TURN_COUNT
        )
        fixed_environment["GUIDE_COPY_LLM_DAILY_CALL_CAP"] = str(
            RELEASE_BROWSER_TURN_COUNT
        )
    for name, expected in fixed_environment.items():
        value = source.get(name)
        if value is not None and value != expected:
            raise BoundRuntimeError(
                f"fixed provider setting cannot be overridden: {name}"
            )

    turn_key = source.get("GUIDE_LLM_API_KEY")
    copy_key = source.get("GUIDE_COPY_LLM_API_KEY")
    if (turn_key is None) != (copy_key is None):
        raise BoundRuntimeError(
            "both provider credentials must be configured together"
        )
    if turn_key is None:
        key = read_private_api_key(key_path)
    else:
        if turn_key != copy_key:
            raise BoundRuntimeError(
                "provider credentials must use one private key"
            )
        key = turn_key
        if (
            not key
            or key != key.strip()
            or len(key.encode("utf-8")) > 1024
            or any(
                ord(character) < 32 or ord(character) == 127
                for character in key
            )
        ):
            raise BoundRuntimeError("provider credential is invalid")

    return {
        **fixed_environment,
        "GUIDE_LLM_API_KEY": key,
        "GUIDE_COPY_LLM_API_KEY": key,
    }


def _prepare_state_directory(path: Path) -> Path:
    if not path.is_absolute():
        raise BoundRuntimeError("state directory must be absolute")
    if path.is_symlink():
        raise BoundRuntimeError("state directory must not be a symlink")
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise BoundRuntimeError(
            "state directory already exists"
        ) from exc
    os.chmod(path, 0o700)
    if not stat.S_ISDIR(path.stat(follow_symlinks=False).st_mode):
        raise BoundRuntimeError("state directory is invalid")
    return path


@contextmanager
def _runtime_environment(
    values: Mapping[str, str],
    *,
    state_dir: Path,
):
    managed = {
        *BOUND_PROVIDER_ENVIRONMENT,
        *_FORBIDDEN_RUNTIME_ENVIRONMENT,
        "XIAORO_GUIDE_STATE_DIR",
    }
    previous = {
        name: os.environ.get(name)
        for name in managed
    }
    try:
        for name in _FORBIDDEN_RUNTIME_ENVIRONMENT:
            os.environ.pop(name, None)
        for name, value in values.items():
            os.environ[name] = value
        os.environ["XIAORO_GUIDE_STATE_DIR"] = str(state_dir)
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _default_application_loader() -> object:
    from app.guide_runtime.app import app

    return app


def _default_server_factory(
    application: object,
    host: str,
    port: int,
) -> object:
    import uvicorn

    return uvicorn.Server(
        uvicorn.Config(
            application,
            host=host,
            port=port,
            access_log=False,
            log_level="info",
        )
    )


class _BoundRuntimeProofApplication:
    def __init__(
        self,
        application: object,
        *,
        private_key: object,
        registration: Mapping[str, object],
    ) -> None:
        self._application = application
        self._private_key = private_key
        self._registration = dict(registration)
        self._lock = Lock()
        self._proof_issued = False
        self._business_capability: str | None = None

    @property
    def proof_issued(self) -> bool:
        with self._lock:
            return self._proof_issued

    def accepts_business_capability(self, value: object) -> bool:
        if not isinstance(value, str):
            return False
        with self._lock:
            return (
                self._business_capability is not None
                and secrets.compare_digest(
                    value,
                    self._business_capability,
                )
            )

    def bind_shutdown(self, callback: Callable[[], None]) -> None:
        del callback

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Any],
        send: Callable[[dict[str, Any]], Any],
    ) -> None:
        path = scope.get("path")
        if (
            scope.get("type") != "http"
            or path not in _RUNTIME_CONTROL_PATHS
        ):
            await self._application(scope, receive, send)  # type: ignore[misc]
            return
        client = scope.get("client")
        try:
            client_address = ipaddress.ip_address(
                str(client[0])
                if isinstance(client, (tuple, list)) and client
                else ""
            )
        except ValueError:
            client_address = None
        if client_address is None or not client_address.is_loopback:
            await self._send_json(
                send,
                403,
                {"error": "loopback_required"},
            )
            return
        if (
            path != "/__task11_runtime__/proof"
            or scope.get("method") != "POST"
        ):
            await self._send_json(
                send,
                409,
                {"error": "runtime_control_disabled"},
            )
            return
        body = bytearray()
        more_body = True
        while more_body:
            message = await receive()
            if message.get("type") != "http.request":
                continue
            body.extend(message.get("body", b""))
            if len(body) > 8192:
                await self._send_json(
                    send,
                    413,
                    {"error": "runtime_proof_request_too_large"},
                )
                return
            more_body = bool(message.get("more_body", False))
        try:
            request = json.loads(bytes(body))
            if not isinstance(request, dict):
                raise RuntimeProofError(
                    "runtime proof request is invalid"
                )
            expected = {
                "schema_version": PROOF_REQUEST_SCHEMA,
                **{
                    key: self._registration.get(key)
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
                "verifier_nonce": request.get("verifier_nonce"),
            }
            if request != expected:
                raise RuntimeProofError(
                    "runtime proof request binding is invalid"
                )
            nonce = request.get("verifier_nonce")
            if not isinstance(nonce, str):
                raise RuntimeProofError(
                    "runtime verifier nonce is invalid"
                )
            with self._lock:
                if self._proof_issued:
                    raise RuntimeProofError(
                        "runtime proof was already issued"
                    )
                proof = sign_runtime_proof(
                    private_key=self._private_key,  # type: ignore[arg-type]
                    public_key=str(
                        self._registration.get("runtime_public_key")
                    ),
                    request=request,
                )
                self._business_capability = sha256(
                    _canonical_bytes(proof)
                ).hexdigest()
                self._proof_issued = True
        except (
            AttributeError,
            json.JSONDecodeError,
            RuntimeProofError,
        ) as exc:
            await self._send_json(send, 409, {"error": str(exc)})
            return
        await self._send_json(send, 200, proof)

    @staticmethod
    async def _send_json(
        send: Callable[[dict[str, Any]], Any],
        status: int,
        payload: Mapping[str, object],
    ) -> None:
        await _ProofGatedApplication._send_json(
            send,
            status,
            payload,
        )


class _ProofGatedApplication:
    def __init__(
        self,
        application: object,
        *,
        registration_is_current: Callable[[], bool] = lambda: True,
        attempt_authority_check: Callable[[], None] | None = None,
        request_lifecycle_lease: Callable[[], object] | None = None,
    ) -> None:
        self._application = application
        self._registration_is_current = registration_is_current
        self._attempt_authority_check = attempt_authority_check
        self._request_lifecycle_lease = request_lifecycle_lease

    def bind_shutdown(self, callback: Callable[[], None]) -> None:
        bind = getattr(self._application, "bind_shutdown", None)
        if callable(bind):
            bind(callback)

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Any],
        send: Callable[[dict[str, Any]], Any],
    ) -> None:
        if (
            scope.get("type") == "http"
            and not self._registration_is_current()
        ):
            await self._send_json(
                send,
                503,
                {"error": "runtime_registration_required"},
            )
            return
        if (
            scope.get("type") == "http"
            and scope.get("path") not in _RUNTIME_CONTROL_PATHS
        ):
            if not bool(
                getattr(self._application, "proof_issued", False)
            ):
                await self._send_json(
                    send,
                    409,
                    {"error": "runtime_proof_required"},
                )
                return
            capability = self._business_capability(scope)
            accepts_capability = getattr(
                self._application,
                "accepts_business_capability",
                None,
            )
            if (
                capability is None
                or not callable(accepts_capability)
                or not accepts_capability(capability)
            ):
                await self._send_json(
                    send,
                    403,
                    {"error": "runtime_proof_capability_required"},
                )
                return
            path = scope.get("path")
            requires_authority_lease = (
                isinstance(path, str)
                and (path == "/api" or path.startswith("/api/"))
            )
            if requires_authority_lease:
                if (
                    self._attempt_authority_check is None
                    or self._request_lifecycle_lease is None
                ):
                    await self._send_json(
                        send,
                        409,
                        {"error": "runtime_attempt_consumption_required"},
                    )
                    return
                lease = self._request_lifecycle_lease()
                entered = False
                try:
                    lease.__enter__()  # type: ignore[attr-defined]
                    entered = True
                    self._attempt_authority_check()
                except (AttemptLedgerError, OSError, ValueError):
                    if entered:
                        lease.__exit__(*sys.exc_info())  # type: ignore[attr-defined]
                    await self._send_json(
                        send,
                        409,
                        {"error": "runtime_attempt_consumption_required"},
                    )
                    return
                except BaseException:
                    if entered:
                        lease.__exit__(*sys.exc_info())  # type: ignore[attr-defined]
                    raise
                try:
                    await self._application(scope, receive, send)  # type: ignore[misc]
                except BaseException:
                    lease.__exit__(*sys.exc_info())  # type: ignore[attr-defined]
                    raise
                else:
                    lease.__exit__(None, None, None)  # type: ignore[attr-defined]
                return
        await self._application(scope, receive, send)

    @staticmethod
    def _business_capability(scope: Mapping[str, object]) -> str | None:
        headers = scope.get("headers")
        if not isinstance(headers, (list, tuple)):
            return None
        values = [
            value
            for name, value in headers
            if (
                isinstance(name, bytes)
                and isinstance(value, bytes)
                and name.lower() == _RUNTIME_PROOF_HEADER
            )
        ]
        if len(values) != 1:
            return None
        try:
            capability = values[0].decode("ascii")
        except UnicodeDecodeError:
            return None
        if re.fullmatch(r"[0-9a-f]{64}", capability) is None:
            return None
        return capability

    @staticmethod
    async def _send_json(
        send: Callable[[dict[str, Any]], Any],
        status: int,
        payload: Mapping[str, object],
    ) -> None:
        content = json.dumps(
            dict(payload),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(content)).encode("ascii")),
                (b"cache-control", b"no-store"),
            ],
        })
        await send({"type": "http.response.body", "body": content})


def _readiness_code_revision(
    readiness: Mapping[str, Any],
) -> str:
    revision = (
        readiness.get("task11_commit")
        if readiness.get("schema_version")
        == "guide-task11-release-readiness-v1"
        else readiness.get("candidate_head")
    )
    if (
        not isinstance(revision, str)
        or re.fullmatch(r"[0-9a-f]{40}", revision) is None
    ):
        raise BoundRuntimeError(
            "readiness code revision is invalid"
        )
    return revision


def _runtime_registration_is_current(
    *,
    context_path: Path,
    context: Mapping[str, Any],
    phase: str,
    attempt_id: str,
    registration_id: str,
    runtime_identity_sha256: str,
    runtime_public_key: str,
    host: str,
    port: int,
) -> bool:
    ledger_path = Path(str(context.get("ledger_path")))
    readiness_path = Path(str(context.get("readiness_path")))
    try:
        readiness = verify_task11_readiness(
            readiness_path=readiness_path,
            ledger_path=ledger_path,
            expected_manifest_sha256=str(
                context.get("expected_manifest_sha256")
            ),
        )
        if (
            context.get("readiness_sha256")
            != _file_sha256(readiness_path)
            or context.get("attempt_context_sha256")
            not in {None, _file_sha256(context_path)}
        ):
            return False
        ledger = read_ledger(ledger_path)
        attempts = [
            item
            for item in ledger.get("attempts", ())
            if (
                isinstance(item, dict)
                and item.get("attempt_id") == attempt_id
            )
        ]
        if len(attempts) != 1:
            return False
        attempt = attempts[0]
        registrations = attempt.get("runtime_registrations")
        matches = (
            [
                item
                for item in registrations
                if (
                    isinstance(item, dict)
                    and item.get("registration_id") == registration_id
                )
            ]
            if isinstance(registrations, list)
            else []
        )
        if len(matches) != 1:
            return False
        registration = matches[0]
        return (
            attempt.get("trajectory_set") == phase
            and attempt.get("plan_revision")
            == readiness.get("plan_revision")
            and registration.get("state")
            in {"registered", "consumed", "terminated"}
            and registration.get("phase") == phase
            and registration.get("attempt_id") == attempt_id
            and registration.get("attempt_context_sha256")
            == _file_sha256(context_path)
            and registration.get("readiness_sha256")
            == context.get("readiness_sha256")
            and registration.get("allocated_ledger_revision")
            == context.get("allocated_ledger_revision")
            and registration.get("allocated_ledger_hash")
            == context.get("allocated_ledger_hash")
            and registration.get("runtime_identity_sha256")
            == runtime_identity_sha256
            and registration.get("runtime_public_key")
            == runtime_public_key
            and registration.get("host") == host
            and registration.get("port") == port
        )
    except (AttemptLedgerError, OSError, ValueError):
        return False


def _runtime_registration_state(
    *,
    ledger_path: str | Path,
    attempt_id: str,
    registration_id: str,
) -> str | None:
    ledger = read_ledger(ledger_path)
    matches = [
        registration
        for attempt in ledger.get("attempts", ())
        if (
            isinstance(attempt, dict)
            and attempt.get("attempt_id") == attempt_id
            and isinstance(attempt.get("runtime_registrations"), list)
        )
        for registration in attempt["runtime_registrations"]
        if (
            isinstance(registration, dict)
            and registration.get("registration_id") == registration_id
        )
    ]
    if len(matches) != 1:
        return None
    state = matches[0].get("state")
    return str(state) if isinstance(state, str) else None


def _runtime_identity(
    *,
    context_path: Path,
    context: Mapping[str, Any],
    readiness: Mapping[str, Any],
    manifest: Mapping[str, Any],
    audit: Mapping[str, Any],
    phase: str,
    attempt_id: str,
    host: str,
    port: int,
    state_dir: Path,
    registration_id: str,
    runtime_public_key: str,
) -> dict[str, Any]:
    files = readiness["evidence_files"]
    hashes = readiness["evidence_sha256"]
    turn_count = (
        RELEASE_BROWSER_TURN_COUNT
        if phase == "browser"
        else BOUND_TURN_COUNT
    )
    return {
        "schema_version": "guide-bound-runtime-identity-v1",
        "phase": phase,
        "attempt_id": attempt_id,
        "attempt_context_path": str(context_path.resolve()),
        "attempt_context_sha256": _file_sha256(context_path),
        "readiness_path": str(
            Path(str(context["readiness_path"])).resolve()
        ),
        "readiness_sha256": context["readiness_sha256"],
        "candidate_manifest_path": str(
            Path(str(files["candidate_manifest"])).resolve()
        ),
        "candidate_manifest_sha256": hashes["candidate_manifest"],
        "independent_audit_path": str(
            Path(str(files["independent_audit"])).resolve()
        ),
        "independent_audit_sha256": hashes["independent_audit"],
        "plan_revision": readiness["plan_revision"],
        "code_revision": _readiness_code_revision(readiness),
        "protected_payload_sha256": (
            manifest["protected_payload_sha256"]
        ),
        "independent_audit_passed": audit["passed"],
        "ledger_path": str(
            Path(str(context["ledger_path"])).resolve()
        ),
        "allocated_ledger_revision": context[
            "allocated_ledger_revision"
        ],
        "allocated_ledger_hash": context["allocated_ledger_hash"],
        "runtime_registration_id": registration_id,
        "runtime_public_key": runtime_public_key,
        "process_identity": {
            "pid": os.getpid(),
            "parent_pid": os.getppid(),
        },
        "host": host,
        "port": port,
        "state_dir": str(state_dir),
        "provider": {
            "base_url": BOUND_BASE_URL,
            "model": BOUND_MODEL,
        },
        "provider_limits": {
            "copywriter": {
                "daily_budget_cny": BOUND_DAILY_BUDGET_CNY,
                "daily_call_cap": turn_count,
                "max_tokens": BOUND_COPYWRITER_MAX_TOKENS,
                "timeout_seconds": BOUND_PROVIDER_TIMEOUT_SECONDS,
            },
            "turn_meaning": {
                "daily_budget_cny": BOUND_DAILY_BUDGET_CNY,
                "daily_call_cap": turn_count,
                "format_repair_attempts": (
                    BOUND_FORMAT_REPAIR_ATTEMPTS
                ),
                "max_tokens": BOUND_TURN_MEANING_MAX_TOKENS,
                "timeout_seconds": BOUND_PROVIDER_TIMEOUT_SECONDS,
            },
        },
    }


def verify_bound_runtime_identity(
    *,
    identity_path: str | Path,
    attempt_context: str | Path,
    expected_host: str,
    expected_port: int,
) -> dict[str, Any]:
    context_path = Path(attempt_context).resolve()
    identity_file = Path(identity_path).resolve()
    (
        context,
        readiness,
        manifest,
        audit,
        phase,
        attempt_id,
    ) = _bound_evidence(context_path=context_path)
    identity = _read_object(
        identity_file,
        label="bound runtime identity",
    )
    process_identity = identity.get("process_identity")
    runtime_registration_id = identity.get(
        "runtime_registration_id"
    )
    runtime_public_key = identity.get("runtime_public_key")
    files = readiness["evidence_files"]
    hashes = readiness["evidence_sha256"]
    turn_count = (
        RELEASE_BROWSER_TURN_COUNT
        if phase == "browser"
        else BOUND_TURN_COUNT
    )
    expected_provider_limits = {
        "copywriter": {
            "daily_budget_cny": BOUND_DAILY_BUDGET_CNY,
            "daily_call_cap": turn_count,
            "max_tokens": BOUND_COPYWRITER_MAX_TOKENS,
            "timeout_seconds": BOUND_PROVIDER_TIMEOUT_SECONDS,
        },
        "turn_meaning": {
            "daily_budget_cny": BOUND_DAILY_BUDGET_CNY,
            "daily_call_cap": turn_count,
            "format_repair_attempts": BOUND_FORMAT_REPAIR_ATTEMPTS,
            "max_tokens": BOUND_TURN_MEANING_MAX_TOKENS,
            "timeout_seconds": BOUND_PROVIDER_TIMEOUT_SECONDS,
        },
    }
    valid = (
        identity_file.read_bytes() == _canonical_bytes(identity)
        and identity.get("schema_version")
        == "guide-bound-runtime-identity-v1"
        and identity.get("phase") == phase
        and identity.get("attempt_id") == attempt_id
        and identity.get("attempt_context_path") == str(context_path)
        and identity.get("attempt_context_sha256")
        == _file_sha256(context_path)
        and identity.get("readiness_path")
        == str(Path(str(context["readiness_path"])).resolve())
        and identity.get("readiness_sha256")
        == context["readiness_sha256"]
        and identity.get("candidate_manifest_path")
        == str(Path(str(files["candidate_manifest"])).resolve())
        and identity.get("candidate_manifest_sha256")
        == hashes["candidate_manifest"]
        and identity.get("independent_audit_path")
        == str(Path(str(files["independent_audit"])).resolve())
        and identity.get("independent_audit_sha256")
        == hashes["independent_audit"]
        and identity.get("plan_revision") == readiness["plan_revision"]
        and identity.get("code_revision")
        == _readiness_code_revision(readiness)
        and identity.get("protected_payload_sha256")
        == manifest["protected_payload_sha256"]
        and identity.get("independent_audit_passed") is True
        and audit.get("passed") is True
        and identity.get("ledger_path")
        == str(Path(str(context["ledger_path"])).resolve())
        and identity.get("allocated_ledger_revision")
        == context["allocated_ledger_revision"]
        and identity.get("allocated_ledger_hash")
        == context["allocated_ledger_hash"]
        and isinstance(runtime_registration_id, str)
        and re.fullmatch(
            r"runtime_[0-9a-f]{16,64}",
            runtime_registration_id,
        )
        is not None
        and validate_runtime_public_key(runtime_public_key)
        == runtime_public_key
        and identity.get("host") == expected_host
        and identity.get("port") == expected_port
        and isinstance(process_identity, dict)
        and type(process_identity.get("pid")) is int
        and process_identity["pid"] > 0
        and type(process_identity.get("parent_pid")) is int
        and process_identity["parent_pid"] > 0
        and identity.get("provider") == {
            "base_url": BOUND_BASE_URL,
            "model": BOUND_MODEL,
        }
        and identity.get("provider_limits") == expected_provider_limits
    )
    if not valid:
        raise BoundRuntimeError("bound runtime identity is invalid")
    if not _runtime_registration_is_current(
        context_path=context_path,
        context=context,
        phase=phase,
        attempt_id=attempt_id,
        registration_id=runtime_registration_id,
        runtime_identity_sha256=sha256(
            identity_file.read_bytes()
        ).hexdigest(),
        runtime_public_key=str(runtime_public_key),
        host=expected_host,
        port=expected_port,
    ):
        raise BoundRuntimeError(
            "bound runtime registration is invalid"
        )
    try:
        os.kill(int(process_identity["pid"]), 0)
    except OSError as exc:
        raise BoundRuntimeError(
            "bound runtime process is unavailable"
        ) from exc
    return identity


def _write_identity(path: Path, payload: Mapping[str, Any]) -> None:
    descriptor = open_private_path(path)
    try:
        write_json_fd(descriptor, payload)
        os.fsync(descriptor)
        verify_path_binding(path, descriptor)
    finally:
        os.close(descriptor)


def _remove_identity_if_matches(
    path: Path,
    *,
    expected_sha256: str,
) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if (
        path.is_symlink()
        or not path.is_file()
        or _file_sha256(path) != expected_sha256
    ):
        raise BoundRuntimeError(
            "runtime identity cleanup binding is invalid"
        )
    path.unlink()


async def _serve_until_stopped(
    server: object,
    *,
    listener: socket.socket,
    identity_path: Path,
    identity: Mapping[str, Any],
) -> None:
    serve = getattr(server, "serve", None)
    if not callable(serve):
        raise BoundRuntimeError("runtime server is invalid")
    task = asyncio.create_task(serve(sockets=[listener]))
    loop = asyncio.get_running_loop()
    deadline = loop.time() + BOUND_STARTUP_TIMEOUT_SECONDS
    while getattr(server, "started", False) is not True:
        if task.done():
            await task
            raise BoundRuntimeError(
                "runtime server stopped before startup"
            )
        if loop.time() >= deadline:
            if hasattr(server, "should_exit"):
                setattr(server, "should_exit", True)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            raise BoundRuntimeError("runtime server startup timed out")
        await asyncio.sleep(0.01)
    _write_identity(identity_path, identity)
    await task


def run_bound_runtime(
    *,
    attempt_context: str | Path,
    host: str,
    port: int,
    state_dir: str | Path,
    key_path: str | Path = DEFAULT_KEY_PATH,
    environ: Mapping[str, str] | None = None,
    application_loader: Callable[[], object] = (
        _default_application_loader
    ),
    server_factory: Callable[[object, str, int], object] = (
        _default_server_factory
    ),
) -> dict[str, Any]:
    """Verify the complete authority chain, then serve one bound runtime."""
    _validate_loopback(host, port)
    context_path = Path(attempt_context)
    (
        context,
        readiness,
        manifest,
        audit,
        phase,
        attempt_id,
    ) = _bound_evidence(context_path=context_path)
    output_directory = Path(str(context.get("output_directory")))
    if (
        not output_directory.is_dir()
        or output_directory.is_symlink()
    ):
        raise BoundRuntimeError(
            "attempt output directory is invalid"
        )
    identity_path = output_directory / RUNTIME_IDENTITY_FILENAME
    if identity_path.exists() or identity_path.is_symlink():
        raise BoundRuntimeError("runtime identity already exists")

    source_environment = (
        dict(os.environ)
        if environ is None
        else dict(environ)
    )
    provider_environment = _validated_environment(
        source_environment,
        key_path=key_path,
        phase=phase,
    )
    resolved_state_dir = _prepare_state_directory(Path(state_dir))
    private_key, runtime_public_key = generate_runtime_keypair()
    registration_id = f"runtime_{secrets.token_hex(16)}"
    with _bound_listener(host, port) as listener:
        identity = _runtime_identity(
            context_path=context_path,
            context=context,
            readiness=readiness,
            manifest=manifest,
            audit=audit,
            phase=phase,
            attempt_id=attempt_id,
            host=host,
            port=port,
            state_dir=resolved_state_dir,
            registration_id=registration_id,
            runtime_public_key=runtime_public_key,
        )
        runtime_identity_sha256 = sha256(
            _canonical_bytes(identity)
        ).hexdigest()
        register_runtime_bound_attempt(
            context_path,
            phase=phase,  # type: ignore[arg-type]
            ledger_path=context["ledger_path"],
            readiness_path=context["readiness_path"],
            registration_id=registration_id,
            runtime_identity_sha256=runtime_identity_sha256,
            runtime_public_key=runtime_public_key,
            host=host,
            port=port,
        )
        try:
            with _runtime_environment(
                provider_environment,
                state_dir=resolved_state_dir,
            ):
                application = application_loader()
                application_state = getattr(application, "state", None)
                if application_state is not None:
                    setattr(
                        application_state,
                        "bound_runtime_identity",
                        identity,
                    )
                proof_application = _BoundRuntimeProofApplication(
                    application,
                    private_key=private_key,
                    registration={
                        "registration_id": registration_id,
                        "phase": phase,
                        "attempt_id": attempt_id,
                        "attempt_context_sha256": identity[
                            "attempt_context_sha256"
                        ],
                        "readiness_sha256": identity[
                            "readiness_sha256"
                        ],
                        "allocated_ledger_revision": identity[
                            "allocated_ledger_revision"
                        ],
                        "allocated_ledger_hash": identity[
                            "allocated_ledger_hash"
                        ],
                        "runtime_identity_sha256": (
                            runtime_identity_sha256
                        ),
                        "runtime_public_key": runtime_public_key,
                    },
                )
                application = _ProofGatedApplication(
                    proof_application,
                    registration_is_current=lambda: True,
                    attempt_authority_check=lambda: (
                        validate_runtime_request_authority(
                            context_path=context_path.resolve(),
                            phase=phase,
                            attempt_id=attempt_id,
                        )
                    ),
                    request_lifecycle_lease=lambda: (
                        runtime_request_lifecycle_lease(
                            context_path.resolve()
                        )
                    ),
                )
                server = server_factory(application, host, port)
                asyncio.run(
                    _serve_until_stopped(
                        server,
                        listener=listener,
                        identity_path=identity_path,
                        identity=identity,
                    )
                )
            registration_state = _runtime_registration_state(
                ledger_path=context["ledger_path"],
                attempt_id=attempt_id,
                registration_id=registration_id,
            )
            if registration_state == "registered":
                abort_runtime_bound_registration(
                    context_path,
                    phase=phase,  # type: ignore[arg-type]
                    ledger_path=context["ledger_path"],
                    registration_id=registration_id,
                )
                _remove_identity_if_matches(
                    identity_path,
                    expected_sha256=runtime_identity_sha256,
                )
                raise BoundRuntimeError(
                    "runtime stopped before attempt consumption"
                )
            if registration_state != "terminated":
                raise BoundRuntimeError(
                    "runtime stopped before attempt completion"
                )
        except BaseException:
            if _runtime_registration_state(
                ledger_path=context["ledger_path"],
                attempt_id=attempt_id,
                registration_id=registration_id,
            ) == "registered":
                abort_runtime_bound_registration(
                    context_path,
                    phase=phase,  # type: ignore[arg-type]
                    ledger_path=context["ledger_path"],
                    registration_id=registration_id,
                )
                _remove_identity_if_matches(
                    identity_path,
                    expected_sha256=runtime_identity_sha256,
                )
            raise
    return identity


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Start an attempt-bound Guide runtime.",
    )
    parser.add_argument(
        "--attempt-context",
        type=Path,
        required=True,
    )
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument(
        "--key-path",
        type=Path,
        default=Path(DEFAULT_KEY_PATH),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        identity = run_bound_runtime(
            attempt_context=args.attempt_context,
            host=args.host,
            port=args.port,
            state_dir=args.state_dir,
            key_path=args.key_path,
        )
    except KeyPrecheckError as exc:
        print(
            json.dumps(
                {
                    "status": "key_precheck_failed",
                    "code": exc.code.value,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 5
    except (BoundRuntimeError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "runtime_preflight_failed",
                    "error_type": type(exc).__name__,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 3
    print(json.dumps(identity, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BOUND_BASE_URL",
    "BOUND_DAILY_BUDGET_CNY",
    "BOUND_FORMAT_REPAIR_ATTEMPTS",
    "BOUND_MODEL",
    "BOUND_PROVIDER_ENVIRONMENT",
    "BOUND_PROVIDER_TIMEOUT_SECONDS",
    "BOUND_TURN_COUNT",
    "BoundRuntimeError",
    "RUNTIME_IDENTITY_FILENAME",
    "main",
    "run_bound_runtime",
    "verify_bound_runtime_identity",
]
