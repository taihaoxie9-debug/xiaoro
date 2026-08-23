from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable
from contextlib import contextmanager
from hashlib import sha256
import hmac
import ipaddress
import json
import multiprocessing.process
import os
from pathlib import Path
import re
import secrets
import subprocess
from threading import Lock
from typing import Any, Iterator, Sequence

from tools.guide_gates.build_task11_readiness import (
    Task11ReadinessError,
    _validated_manifest,
)
from tools.guide_gates.zero_api_network_guard import (
    ZeroApiNetworkGuard,
    ZeroApiNetworkViolation,
)


_IDENTITY_SCHEMA = "guide-zero-api-runtime-identity-v1"
_REPORT_SCHEMA = "guide-zero-api-runtime-network-report-v1"
_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_NONCE_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_PROVIDER_KEY_ENVIRONMENTS = (
    "GUIDE_LLM_API_KEY",
    "GUIDE_COPY_LLM_API_KEY",
    "OPENAI_API_KEY",
)
_STATE_DIRECTORY_ENVIRONMENT = "XIAORO_GUIDE_STATE_DIR"


class ZeroApiRuntimeError(RuntimeError):
    pass


class ZeroApiRuntimeViolation(RuntimeError):
    pass


class _RuntimeLifecycle:
    def __init__(self) -> None:
        self.runtime_started = False
        self.ready_identity_written = False
        self.shutdown_finalized = False
        self.runtime_succeeded = False
        self.candidate_manifest_sha256: str | None = None
        self.runtime_identity_sha256: str | None = None


class _ProcessCreationGuard:
    _OS_PROCESS_FUNCTIONS = (
        "execl",
        "execle",
        "execlp",
        "execlpe",
        "execv",
        "execve",
        "execvp",
        "execvpe",
        "fork",
        "forkpty",
        "posix_spawn",
        "posix_spawnp",
        "spawnl",
        "spawnle",
        "spawnlp",
        "spawnlpe",
        "spawnv",
        "spawnve",
        "spawnvp",
        "spawnvpe",
        "system",
    )

    def __init__(self) -> None:
        self._lock = Lock()
        self._installed = False
        self._attempts: list[dict[str, str]] = []
        self._popen_init: Callable[..., None] | None = None
        self._multiprocessing_start: Callable[..., None] | None = None
        self._os_functions: dict[str, Callable[..., Any]] = {}

    @property
    def attempt_count(self) -> int:
        with self._lock:
            return len(self._attempts)

    @property
    def attempts(self) -> list[dict[str, str]]:
        with self._lock:
            return [dict(item) for item in self._attempts]

    def install(self) -> None:
        if self._installed:
            raise RuntimeError(
                "zero API process guard is already installed"
            )
        guard = self
        self._popen_init = subprocess.Popen.__init__
        self._multiprocessing_start = (
            multiprocessing.process.BaseProcess.start
        )

        def guarded_popen_init(
            process: subprocess.Popen[Any],
            *args: object,
            **kwargs: object,
        ) -> None:
            del process
            target = args[0] if args else kwargs.get("args")
            guard._block("subprocess.Popen", target)

        def guarded_process_start(
            process: multiprocessing.process.BaseProcess,
            *args: object,
            **kwargs: object,
        ) -> None:
            del args, kwargs
            guard._block(
                "multiprocessing.Process.start",
                getattr(process, "name", type(process).__name__),
            )

        subprocess.Popen.__init__ = guarded_popen_init
        multiprocessing.process.BaseProcess.start = guarded_process_start
        for name in self._OS_PROCESS_FUNCTIONS:
            original = getattr(os, name, None)
            if not callable(original):
                continue
            self._os_functions[name] = original

            def blocked_os_call(
                *args: object,
                _name: str = name,
                **kwargs: object,
            ) -> None:
                target = args[0] if args else kwargs
                guard._block(f"os.{_name}", target)

            setattr(os, name, blocked_os_call)
        self._installed = True

    def uninstall(self) -> None:
        if not self._installed:
            return
        if self._popen_init is not None:
            subprocess.Popen.__init__ = self._popen_init
        if self._multiprocessing_start is not None:
            multiprocessing.process.BaseProcess.start = (
                self._multiprocessing_start
            )
        for name, original in self._os_functions.items():
            setattr(os, name, original)
        self._installed = False

    def _block(self, kind: str, target: object) -> None:
        rendered_target = repr(target)
        if len(rendered_target) > 500:
            rendered_target = f"{rendered_target[:497]}..."
        with self._lock:
            self._attempts.append(
                {"kind": kind, "target": rendered_target}
            )
        raise ZeroApiRuntimeViolation(
            f"process creation is forbidden: {kind}"
        )


class _RuntimeNetworkGuard(ZeroApiNetworkGuard):
    def __init__(
        self,
        *,
        lifecycle: _RuntimeLifecycle,
        process_guard: _ProcessCreationGuard,
    ) -> None:
        super().__init__()
        self._lifecycle = lifecycle
        self._process_guard = process_guard

    def report(self) -> dict[str, object]:
        measured = super().report()
        outbound_attempts = measured[
            "outbound_network_attempt_count"
        ]
        process_attempts = self._process_guard.attempt_count
        passed = (
            measured["passed"] is True
            and process_attempts == 0
            and self._lifecycle.runtime_started
            and self._lifecycle.ready_identity_written
            and self._lifecycle.shutdown_finalized
            and self._lifecycle.runtime_succeeded
        )
        return {
            **measured,
            "schema_version": _REPORT_SCHEMA,
            "passed": passed,
            "runtime_started": self._lifecycle.runtime_started,
            "ready_identity_written": (
                self._lifecycle.ready_identity_written
            ),
            "shutdown_finalized": (
                self._lifecycle.shutdown_finalized
            ),
            "process_creation_attempt_count": process_attempts,
            "process_creation_attempts": (
                self._process_guard.attempts
            ),
            "runtime_process_tree_non_loopback_attempt_count": (
                outbound_attempts
            ),
            "candidate_manifest_sha256": (
                self._lifecycle.candidate_manifest_sha256
            ),
            "runtime_identity_sha256": (
                self._lifecycle.runtime_identity_sha256
            ),
        }


def _canonical_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _write_json_atomically(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"output already exists: {path}")
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(_canonical_bytes(payload))
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _is_loopback_host(host: object) -> bool:
    if not isinstance(host, str):
        return False
    normalized = host.strip().rstrip(".").casefold()
    if normalized == "localhost" or normalized.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(
            normalized.split("%", 1)[0]
        ).is_loopback
    except ValueError:
        return False


def _require_runtime_arguments(
    *,
    host: str,
    port: int,
    ready_file: Path,
    network_report: Path,
) -> None:
    if not _is_loopback_host(host):
        raise ZeroApiRuntimeError(
            "zero API runtime requires a loopback host"
        )
    if isinstance(port, bool) or not isinstance(port, int):
        raise ZeroApiRuntimeError("runtime port is invalid")
    if not 1 <= port <= 65535:
        raise ZeroApiRuntimeError("runtime port is invalid")
    if ready_file.resolve() == network_report.resolve():
        raise ZeroApiRuntimeError(
            "ready identity and network report must differ"
        )
    for label, path in (
        ("ready identity", ready_file),
        ("network report", network_report),
    ):
        if path.exists() or path.is_symlink():
            raise ZeroApiRuntimeError(f"{label} already exists")


def _git_directory(root: Path) -> Path:
    marker = root / ".git"
    if marker.is_dir():
        return marker
    try:
        text = marker.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ZeroApiRuntimeError(
            "candidate repository HEAD is unavailable"
        ) from exc
    prefix = "gitdir:"
    if not text.casefold().startswith(prefix):
        raise ZeroApiRuntimeError(
            "candidate repository HEAD is unavailable"
        )
    git_directory = Path(text[len(prefix):].strip())
    if not git_directory.is_absolute():
        git_directory = marker.parent / git_directory
    return git_directory.resolve()


def _repository_head(root: Path) -> str:
    git_directory = _git_directory(root)
    try:
        head = (git_directory / "HEAD").read_text(
            encoding="ascii"
        ).strip()
    except OSError as exc:
        raise ZeroApiRuntimeError(
            "candidate repository HEAD is unavailable"
        ) from exc
    if _REVISION_PATTERN.fullmatch(head):
        return head
    prefix = "ref:"
    if not head.startswith(prefix):
        raise ZeroApiRuntimeError(
            "candidate repository HEAD is invalid"
        )
    reference = head[len(prefix):].strip()
    reference_path = git_directory / reference
    try:
        revision = reference_path.read_text(
            encoding="ascii"
        ).strip()
    except OSError:
        revision = ""
    if not revision:
        try:
            packed_refs = (git_directory / "packed-refs").read_text(
                encoding="ascii"
            ).splitlines()
        except OSError as exc:
            raise ZeroApiRuntimeError(
                "candidate repository HEAD is unavailable"
            ) from exc
        for row in packed_refs:
            if row.startswith(("#", "^")):
                continue
            fields = row.split(" ", 1)
            if len(fields) == 2 and fields[1] == reference:
                revision = fields[0]
                break
    if not _REVISION_PATTERN.fullmatch(revision):
        raise ZeroApiRuntimeError(
            "candidate repository HEAD is invalid"
        )
    return revision


def _load_candidate_manifest(
    manifest_path: Path,
) -> tuple[dict[str, Any], Path, str]:
    try:
        manifest, root = _validated_manifest(manifest_path)
    except Task11ReadinessError as exc:
        raise ZeroApiRuntimeError(
            "candidate manifest is invalid"
        ) from exc
    candidate_head = manifest.get("candidate_head")
    if (
        not isinstance(candidate_head, str)
        or not _REVISION_PATTERN.fullmatch(candidate_head)
        or candidate_head != _repository_head(root)
    ):
        raise ZeroApiRuntimeError(
            "candidate_head does not match repository HEAD"
        )
    plan_revision = manifest.get("plan_revision")
    protected_payload = manifest.get("protected_payload_sha256")
    if (
        not isinstance(plan_revision, str)
        or not plan_revision
        or not isinstance(protected_payload, str)
        or not re.fullmatch(r"[0-9a-f]{64}", protected_payload)
    ):
        raise ZeroApiRuntimeError(
            "candidate manifest identity is invalid"
        )
    return manifest, root, candidate_head


def _identity_digest(payload: dict[str, object]) -> str:
    unsigned = dict(payload)
    unsigned.pop("identity_sha256", None)
    return sha256(_canonical_bytes(unsigned)).hexdigest()


def _build_runtime_identity(
    *,
    manifest_path: Path,
    manifest: dict[str, Any],
    code_revision: str,
    host: str,
    port: int,
    state_dir: Path,
) -> dict[str, object]:
    identity: dict[str, object] = {
        "schema_version": _IDENTITY_SCHEMA,
        "candidate_manifest_sha256": sha256(
            manifest_path.read_bytes()
        ).hexdigest(),
        "plan_revision": manifest["plan_revision"],
        "code_revision": code_revision,
        "protected_payload_sha256": (
            manifest["protected_payload_sha256"]
        ),
        "process_identity": {"pid": os.getpid()},
        "host": host,
        "port": port,
        "state_dir": str(state_dir),
        "runtime_nonce": secrets.token_hex(32),
    }
    identity["identity_sha256"] = _identity_digest(identity)
    return identity


def verify_runtime_identity(
    *,
    identity_path: str | Path,
    manifest_path: str | Path,
    expected_host: str,
    expected_port: int,
    expected_pid: int,
) -> dict[str, object]:
    try:
        identity_file = Path(identity_path)
        manifest_file = Path(manifest_path)
        identity = json.loads(identity_file.read_text(encoding="utf-8"))
        if not isinstance(identity, dict):
            raise ValueError("identity is not an object")
        manifest, _, code_revision = _load_candidate_manifest(
            manifest_file
        )
        process_identity = identity.get("process_identity")
        runtime_nonce = identity.get("runtime_nonce")
        identity_sha256 = identity.get("identity_sha256")
        valid = (
            identity.get("schema_version") == _IDENTITY_SCHEMA
            and identity.get("candidate_manifest_sha256")
            == sha256(manifest_file.read_bytes()).hexdigest()
            and identity.get("plan_revision")
            == manifest["plan_revision"]
            and identity.get("code_revision") == code_revision
            and identity.get("protected_payload_sha256")
            == manifest["protected_payload_sha256"]
            and identity.get("host") == expected_host
            and identity.get("port") == expected_port
            and isinstance(process_identity, dict)
            and process_identity.get("pid") == expected_pid
            and isinstance(runtime_nonce, str)
            and _NONCE_PATTERN.fullmatch(runtime_nonce) is not None
            and runtime_nonce != "0" * 64
            and isinstance(identity_sha256, str)
            and hmac.compare_digest(
                identity_sha256,
                _identity_digest(identity),
            )
        )
    except (
        OSError,
        json.JSONDecodeError,
        Task11ReadinessError,
        ValueError,
        ZeroApiRuntimeError,
    ) as exc:
        raise ZeroApiRuntimeError(
            "runtime identity is invalid"
        ) from exc
    if not valid:
        raise ZeroApiRuntimeError("runtime identity is invalid")
    return identity


@contextmanager
def _runtime_environment(state_dir: Path) -> Iterator[None]:
    names = (
        *_PROVIDER_KEY_ENVIRONMENTS,
        _STATE_DIRECTORY_ENVIRONMENT,
    )
    previous = {
        name: os.environ[name]
        for name in names
        if name in os.environ
    }
    try:
        for name in _PROVIDER_KEY_ENVIRONMENTS:
            os.environ.pop(name, None)
        os.environ[_STATE_DIRECTORY_ENVIRONMENT] = str(state_dir)
        yield
    finally:
        for name in names:
            if name in previous:
                os.environ[name] = previous[name]
            else:
                os.environ.pop(name, None)


def _default_application_loader() -> object:
    from app.guide_runtime.app import app

    return app


def _default_server_factory(
    application: object,
    host: str,
    port: int,
) -> object:
    import uvicorn

    configuration = uvicorn.Config(
        application,
        host=host,
        port=port,
        log_level="info",
    )
    return uvicorn.Server(configuration)


async def _serve_until_shutdown(
    *,
    server: object,
    on_started: Callable[[], None],
    lifecycle: _RuntimeLifecycle,
) -> None:
    serve = getattr(server, "serve", None)
    if not callable(serve):
        raise ZeroApiRuntimeError("runtime server is invalid")
    task = asyncio.create_task(serve())
    try:
        while not bool(getattr(server, "started", False)):
            if task.done():
                await task
                raise ZeroApiRuntimeError(
                    "runtime server exited before startup"
                )
            await asyncio.sleep(0.01)
        lifecycle.runtime_started = True
        if task.done():
            await task
        on_started()
        if not task.done():
            await task
    except BaseException:
        if not task.done():
            if hasattr(server, "should_exit"):
                setattr(server, "should_exit", True)
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        raise


def run_zero_api_runtime(
    *,
    manifest_path: str | Path,
    host: str,
    port: int,
    state_dir: str | Path,
    ready_file: str | Path,
    network_report: str | Path,
    application_loader: Callable[[], object] = (
        _default_application_loader
    ),
    server_factory: Callable[[object, str, int], object] = (
        _default_server_factory
    ),
) -> dict[str, object]:
    manifest_file = Path(manifest_path).resolve()
    ready_path = Path(ready_file).resolve()
    report_path = Path(network_report).resolve()
    resolved_state_dir = Path(state_dir).resolve()
    _require_runtime_arguments(
        host=host,
        port=port,
        ready_file=ready_path,
        network_report=report_path,
    )

    lifecycle = _RuntimeLifecycle()
    process_guard = _ProcessCreationGuard()
    network_guard = _RuntimeNetworkGuard(
        lifecycle=lifecycle,
        process_guard=process_guard,
    )
    identity: dict[str, object] | None = None
    failure: BaseException | None = None
    guard_installed = False
    process_guard_installed = False

    try:
        network_guard.install()
        guard_installed = True
        process_guard.install()
        process_guard_installed = True
        with _runtime_environment(resolved_state_dir):
            resolved_state_dir.mkdir(parents=True, exist_ok=True)
            manifest, _, code_revision = _load_candidate_manifest(
                manifest_file
            )
            lifecycle.candidate_manifest_sha256 = sha256(
                manifest_file.read_bytes()
            ).hexdigest()
            identity = _build_runtime_identity(
                manifest_path=manifest_file,
                manifest=manifest,
                code_revision=code_revision,
                host=host,
                port=port,
                state_dir=resolved_state_dir,
            )

            def write_ready_identity() -> None:
                assert identity is not None
                _write_json_atomically(ready_path, identity)
                lifecycle.ready_identity_written = True
                lifecycle.runtime_identity_sha256 = sha256(
                    ready_path.read_bytes()
                ).hexdigest()

            application = application_loader()
            server = server_factory(application, host, port)
            asyncio.run(
                _serve_until_shutdown(
                    server=server,
                    on_started=write_ready_identity,
                    lifecycle=lifecycle,
                )
            )
            if (
                network_guard.provider_call_count != 0
                or network_guard.outbound_network_attempt_count != 0
                or process_guard.attempt_count != 0
            ):
                raise ZeroApiRuntimeError(
                    "zero API runtime network policy failed"
                )
            lifecycle.runtime_succeeded = True
    except BaseException as exc:
        failure = exc
    finally:
        if process_guard_installed:
            process_guard.uninstall()
        if guard_installed:
            network_guard.uninstall()
        lifecycle.shutdown_finalized = True
        if failure is not None:
            try:
                ready_path.unlink(missing_ok=True)
            except OSError:
                pass
            lifecycle.ready_identity_written = False
            lifecycle.runtime_identity_sha256 = None
        try:
            network_guard.write_report(report_path)
        except BaseException as exc:
            try:
                ready_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise ZeroApiRuntimeError(
                "zero API runtime shutdown finalization failed"
            ) from exc

    if failure is not None:
        if isinstance(
            failure,
            (ZeroApiNetworkViolation, ZeroApiRuntimeViolation),
        ):
            raise ZeroApiRuntimeError(
                "zero API runtime network policy failed"
            ) from failure
        raise failure
    if identity is None:
        raise ZeroApiRuntimeError("runtime identity was not created")
    return identity


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Task 11 loopback-only zero-API runtime.",
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--ready-file", type=Path, required=True)
    parser.add_argument("--network-report", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    identity = run_zero_api_runtime(
        manifest_path=args.manifest,
        host=args.host,
        port=args.port,
        state_dir=args.state_dir,
        ready_file=args.ready_file,
        network_report=args.network_report,
    )
    print(json.dumps(identity, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ZeroApiRuntimeError",
    "ZeroApiRuntimeViolation",
    "run_zero_api_runtime",
    "verify_runtime_identity",
]
