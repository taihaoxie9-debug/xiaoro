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
import secrets
import stat
import sys
from typing import Any

from tools.guide_gates.attempt_ledger import (
    read_attempt_context,
    read_ledger,
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
BOUND_PROVIDER_TIMEOUT_SECONDS = 30
BOUND_TURN_MEANING_MAX_TOKENS = 1024
BOUND_COPYWRITER_MAX_TOKENS = 1536
BOUND_DAILY_BUDGET_CNY = "3.00"
BOUND_FORMAT_REPAIR_ATTEMPTS = 0
BOUND_STARTUP_TIMEOUT_SECONDS = 30
RUNTIME_IDENTITY_FILENAME = "runtime-identity.json"

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
    if (
        manifest.get("schema_version")
        != "guide-task11-candidate-manifest-v1"
        or manifest.get("plan_revision")
        != readiness.get("plan_revision")
        or manifest.get("candidate_head")
        != readiness.get("candidate_head")
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
    phase = next(reversed(phase_attempt_ids))
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
    if (
        ledger.get("circuit_state") != "closed"
        or len(attempts) != 1
        or len(authorizations) != 1
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


def _validated_environment(
    source: Mapping[str, str],
    *,
    key_path: str | Path,
) -> dict[str, str]:
    if any(name in source for name in _FORBIDDEN_RUNTIME_ENVIRONMENT):
        raise BoundRuntimeError(
            "forbidden runtime configuration is present"
        )
    for name, expected in _FIXED_PROVIDER_ENVIRONMENT.items():
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
        **_FIXED_PROVIDER_ENVIRONMENT,
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
) -> dict[str, Any]:
    files = readiness["evidence_files"]
    hashes = readiness["evidence_sha256"]
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
        "code_revision": manifest["candidate_head"],
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
        "process_identity": {
            "pid": os.getpid(),
            "parent_pid": os.getppid(),
        },
        "host": host,
        "port": port,
        "state_dir": str(state_dir),
        "runtime_nonce": secrets.token_hex(32),
        "provider": {
            "base_url": BOUND_BASE_URL,
            "model": BOUND_MODEL,
        },
        "provider_limits": {
            "copywriter": {
                "daily_budget_cny": BOUND_DAILY_BUDGET_CNY,
                "daily_call_cap": BOUND_TURN_COUNT,
                "max_tokens": BOUND_COPYWRITER_MAX_TOKENS,
                "timeout_seconds": BOUND_PROVIDER_TIMEOUT_SECONDS,
            },
            "turn_meaning": {
                "daily_budget_cny": BOUND_DAILY_BUDGET_CNY,
                "daily_call_cap": BOUND_TURN_COUNT,
                "format_repair_attempts": (
                    BOUND_FORMAT_REPAIR_ATTEMPTS
                ),
                "max_tokens": BOUND_TURN_MEANING_MAX_TOKENS,
                "timeout_seconds": BOUND_PROVIDER_TIMEOUT_SECONDS,
            },
        },
    }


def _write_identity(path: Path, payload: Mapping[str, Any]) -> None:
    descriptor = open_private_path(path)
    try:
        write_json_fd(descriptor, payload)
        os.fsync(descriptor)
        verify_path_binding(path, descriptor)
    finally:
        os.close(descriptor)


async def _serve_until_stopped(
    server: object,
    *,
    identity_path: Path,
    identity: Mapping[str, Any],
) -> None:
    serve = getattr(server, "serve", None)
    if not callable(serve):
        raise BoundRuntimeError("runtime server is invalid")
    task = asyncio.create_task(serve())
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
    )
    resolved_state_dir = _prepare_state_directory(Path(state_dir))
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
    )
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
        server = server_factory(application, host, port)
        asyncio.run(
            _serve_until_stopped(
                server,
                identity_path=identity_path,
                identity=identity,
            )
        )
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
]
