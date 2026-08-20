"""Supervise the Guide runtime and its existing browser probes."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

if __package__:
    from tools.guide_gates.private_output_io import (
        OutputBindingError,
        PrivateRunDirectory,
        open_private_at,
        verify_output_binding,
        write_json_fd,
    )
    from tools.guide_gates.run_bounded_command import run_bounded
else:
    from private_output_io import (
        OutputBindingError,
        PrivateRunDirectory,
        open_private_at,
        verify_output_binding,
        write_json_fd,
    )
    from run_bounded_command import run_bounded


SERVER_COMMAND = (
    sys.executable,
    "-m",
    "uvicorn",
    "app.guide_runtime.app:app",
    "--host",
    "127.0.0.1",
    "--port",
    "8765",
)
BROWSER_COMMANDS = (
    (
        sys.executable,
        "tools/guide_gates/runtime_browser_smoke.py",
        "--url",
        "http://127.0.0.1:8765/chat",
    ),
    (
        sys.executable,
        "tools/guide_gates/runtime_browser_adversarial.py",
        "--url",
        "http://127.0.0.1:8765/chat",
    ),
)
READY_URL = "http://127.0.0.1:8765/health"
SUMMARY_FILENAME = "runtime_browser_matrix_summary.json"
BROWSER_ENVIRONMENT_FAILURE_RETURN_CODE = 2
BROWSER_ENVIRONMENT_PREFLIGHT_TIMEOUT_SECONDS = 60
BROWSER_ENVIRONMENT_PREFLIGHT_MARKER = (
    "XIAORO_BROWSER_ENVIRONMENT_PREFLIGHT="
)
REQUIRED_BROWSER_MODULES = (
    "numpy",
    "torch",
    "open_clip",
    "rapidocr_onnxruntime",
    "playwright",
)
BROWSER_ENVIRONMENT_COMPONENTS = frozenset(
    (*REQUIRED_BROWSER_MODULES, "browser_runtime", "preflight")
)
BROWSER_ENVIRONMENT_PREFLIGHT_PROGRAM = r"""
import importlib
import json
import os
from pathlib import Path
import sys

required_modules = json.loads(sys.argv[1])
checks = []
playwright_available = True
for module_name in required_modules:
    try:
        importlib.import_module(module_name)
    except BaseException:
        checks.append(
            {"component": module_name, "code": "unavailable"}
        )
        if module_name == "playwright":
            playwright_available = False

if playwright_available:
    try:
        configured_path = os.environ.get(
            "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"
        )
        if configured_path:
            browser_path = Path(configured_path)
        else:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser_path = Path(
                    playwright.chromium.executable_path
                )
        if not browser_path.is_file() or not os.access(
            browser_path,
            os.X_OK,
        ):
            raise RuntimeError("browser runtime unavailable")
    except BaseException:
        checks.append(
            {"component": "browser_runtime", "code": "unavailable"}
        )

payload = {
    "checks": checks,
    "status": "failed" if checks else "passed",
}
print(
    "XIAORO_BROWSER_ENVIRONMENT_PREFLIGHT="
    + json.dumps(payload, sort_keys=True)
)
raise SystemExit(3 if checks else 0)
""".strip()


@dataclass(frozen=True, slots=True)
class BrowserEnvironmentCheck:
    component: str
    code: str


@dataclass(frozen=True, slots=True)
class BrowserEnvironmentFailure:
    code: str
    checks: tuple[BrowserEnvironmentCheck, ...]


@dataclass(frozen=True, slots=True)
class BrowserProbeResult:
    name: str
    returncode: int
    timed_out: bool
    term_sent: bool
    kill_sent: bool
    elapsed_seconds: float
    output_lines: int


@dataclass(frozen=True, slots=True)
class BrowserMatrixResult:
    returncode: int
    server_pid: int | None
    server_ready: bool
    server_term_sent: bool
    server_kill_sent: bool
    probes: tuple[BrowserProbeResult, ...]
    environment_failure: BrowserEnvironmentFailure | None


def run_browser_matrix(
    *,
    server_command: Sequence[str] = SERVER_COMMAND,
    browser_commands: Sequence[Sequence[str]] = BROWSER_COMMANDS,
    ready_url: str = READY_URL,
    timeout_seconds: float = 600,
    heartbeat_seconds: float = 30,
    ready_timeout_seconds: float = 30,
    termination_grace_seconds: float = 5,
    output_dir: str | Path,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
) -> BrowserMatrixResult:
    """Run browser probes in order against one supervised Guide server."""
    normalized_server = _normalized_command(server_command)
    normalized_probes = tuple(
        _normalized_command(command) for command in browser_commands
    )
    requires_environment_preflight = (
        normalized_server == SERVER_COMMAND
        and normalized_probes == BROWSER_COMMANDS
    )
    _require_positive("timeout_seconds", timeout_seconds)
    _require_positive("heartbeat_seconds", heartbeat_seconds)
    _require_positive("ready_timeout_seconds", ready_timeout_seconds)
    _require_positive(
        "termination_grace_seconds",
        termination_grace_seconds,
    )
    if not isinstance(ready_url, str) or not ready_url:
        raise ValueError("ready_url must be a non-empty string")

    destination = Path(output_dir)
    run_directory = PrivateRunDirectory.create(destination)
    directory_fd = run_directory.directory_descriptor
    output_fds: dict[str, int] = {}
    output_names = (
        "server.log",
        *(f"{_probe_name(index)}.log" for index in range(len(normalized_probes))),
        SUMMARY_FILENAME,
    )
    try:
        for filename in output_names:
            output_fds[filename] = open_private_at(
                directory_fd,
                filename,
            )
        server_log_descriptor = os.dup(output_fds["server.log"])
        try:
            server_log = os.fdopen(
                server_log_descriptor,
                "w",
                encoding="utf-8",
                closefd=True,
            )
        except BaseException:
            os.close(server_log_descriptor)
            raise
    except BaseException as exc:
        setup_failure = exc
        try:
            run_directory.verify_binding()
        except OutputBindingError as binding_failure:
            setup_failure = binding_failure
        for descriptor in output_fds.values():
            os.close(descriptor)
        run_directory.close()
        raise setup_failure

    server: subprocess.Popen[str] | None = None
    server_ready = False
    server_term_sent = False
    server_kill_sent = False
    probes: list[BrowserProbeResult] = []
    returncode = 1
    failure: BaseException | None = None
    environment_failure: BrowserEnvironmentFailure | None = None

    try:
        if requires_environment_preflight:
            environment_failure = _preflight_browser_environment(
                cwd=cwd,
                env=env,
            )
            if environment_failure is not None:
                returncode = BROWSER_ENVIRONMENT_FAILURE_RETURN_CODE

        if environment_failure is None:
            server = subprocess.Popen(
                normalized_server,
                cwd=cwd,
                stdout=server_log,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
                env=env,
            )
            server_ready = _wait_until_ready(
                server,
                ready_url,
                timeout_seconds=ready_timeout_seconds,
                heartbeat_seconds=heartbeat_seconds,
            )
            if server_ready:
                returncode = 0
                for index, command in enumerate(normalized_probes):
                    name = _probe_name(index)
                    probe_log_name = f"{name}.log"
                    verify_output_binding(
                        directory_fd,
                        probe_log_name,
                        output_fds[probe_log_name],
                    )
                    bounded = run_bounded(
                        command,
                        timeout_seconds=timeout_seconds,
                        heartbeat_seconds=heartbeat_seconds,
                        output_fd=output_fds[probe_log_name],
                        cwd=cwd,
                        env=env,
                        termination_grace_seconds=(
                            termination_grace_seconds
                        ),
                    )
                    verify_output_binding(
                        directory_fd,
                        probe_log_name,
                        output_fds[probe_log_name],
                    )
                    probe_returncode = (
                        124 if bounded.timed_out else bounded.returncode
                    )
                    probes.append(
                        BrowserProbeResult(
                            name=name,
                            returncode=probe_returncode,
                            timed_out=bounded.timed_out,
                            term_sent=bounded.term_sent,
                            kill_sent=bounded.kill_sent,
                            elapsed_seconds=bounded.elapsed_seconds,
                            output_lines=bounded.output_lines,
                        )
                    )
                    if probe_returncode != 0:
                        returncode = probe_returncode
                        break
            else:
                server_returncode = server.poll()
                returncode = (
                    server_returncode
                    if server_returncode not in (None, 0)
                    else 1
                )
    except BaseException as exc:
        failure = exc
    finally:
        try:
            if server is not None:
                server_term_sent, server_kill_sent = _stop_process_group(
                    server,
                    termination_grace_seconds,
                )
        except BaseException as exc:
            if failure is None:
                failure = exc
        try:
            server_log.close()
        except BaseException as exc:
            if failure is None:
                failure = exc

        for filename, descriptor in output_fds.items():
            try:
                verify_output_binding(
                    directory_fd,
                    filename,
                    descriptor,
                )
            except BaseException as exc:
                if failure is None:
                    failure = exc
        try:
            run_directory.verify_binding()
        except OutputBindingError as exc:
            failure = exc

        payload = {
            "schema_version": 1,
            "status": (
                "passed"
                if failure is None and returncode == 0
                else "failed"
            ),
            "returncode": returncode,
            "server": {
                "pid": server.pid if server is not None else None,
                "ready": server_ready,
                "term_sent": server_term_sent,
                "kill_sent": server_kill_sent,
            },
            "probes": [asdict(probe) for probe in probes],
        }
        if failure is not None:
            payload["failure_type"] = type(failure).__name__
        if environment_failure is not None:
            payload["environment_failure"] = asdict(
                environment_failure
            )
        try:
            write_json_fd(output_fds[SUMMARY_FILENAME], payload)
        except BaseException as exc:
            if failure is None:
                failure = exc

        try:
            verify_output_binding(
                directory_fd,
                SUMMARY_FILENAME,
                output_fds[SUMMARY_FILENAME],
            )
        except BaseException as exc:
            if failure is None:
                failure = exc
        try:
            run_directory.verify_binding()
        except OutputBindingError as exc:
            failure = exc

        for descriptor in output_fds.values():
            try:
                os.close(descriptor)
            except BaseException as exc:
                if failure is None:
                    failure = exc
        try:
            run_directory.close()
        except BaseException as exc:
            if failure is None:
                failure = exc

    if failure is not None:
        raise failure

    if server is None and environment_failure is None:
        raise RuntimeError("browser matrix completed without a server")
    return BrowserMatrixResult(
        returncode=returncode,
        server_pid=server.pid if server is not None else None,
        server_ready=server_ready,
        server_term_sent=server_term_sent,
        server_kill_sent=server_kill_sent,
        probes=tuple(probes),
        environment_failure=environment_failure,
    )


def _preflight_browser_environment(
    *,
    cwd: str | Path | None,
    env: Mapping[str, str] | None,
) -> BrowserEnvironmentFailure | None:
    try:
        completed = subprocess.run(
            (
                sys.executable,
                "-c",
                BROWSER_ENVIRONMENT_PREFLIGHT_PROGRAM,
                json.dumps(REQUIRED_BROWSER_MODULES),
            ),
            cwd=cwd,
            env=dict(env) if env is not None else None,
            check=False,
            capture_output=True,
            text=True,
            timeout=BROWSER_ENVIRONMENT_PREFLIGHT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return _browser_environment_failure("preflight")

    encoded_payload = next(
        (
            line.removeprefix(BROWSER_ENVIRONMENT_PREFLIGHT_MARKER)
            for line in reversed(completed.stdout.splitlines())
            if line.startswith(BROWSER_ENVIRONMENT_PREFLIGHT_MARKER)
        ),
        None,
    )
    if encoded_payload is None:
        return _browser_environment_failure("preflight")
    try:
        payload = json.loads(encoded_payload)
    except (TypeError, ValueError):
        return _browser_environment_failure("preflight")
    if not isinstance(payload, dict):
        return _browser_environment_failure("preflight")

    checks: list[BrowserEnvironmentCheck] = []
    seen: set[str] = set()
    raw_checks = payload.get("checks")
    if isinstance(raw_checks, list):
        for raw_check in raw_checks:
            if not isinstance(raw_check, dict):
                continue
            component = raw_check.get("component")
            if (
                component not in BROWSER_ENVIRONMENT_COMPONENTS
                or component in seen
            ):
                continue
            seen.add(component)
            checks.append(
                BrowserEnvironmentCheck(
                    component=component,
                    code="unavailable",
                )
            )
    if (
        completed.returncode == 0
        and payload.get("status") == "passed"
        and not checks
    ):
        return None
    if not checks:
        return _browser_environment_failure("preflight")
    return BrowserEnvironmentFailure(
        code="browser_environment_unavailable",
        checks=tuple(checks),
    )


def _browser_environment_failure(
    component: str,
) -> BrowserEnvironmentFailure:
    return BrowserEnvironmentFailure(
        code="browser_environment_unavailable",
        checks=(
            BrowserEnvironmentCheck(
                component=component,
                code="unavailable",
            ),
        ),
    )


def _normalized_command(command: Sequence[str]) -> tuple[str, ...]:
    if isinstance(command, (str, bytes)):
        raise TypeError("command must be a sequence of arguments")
    normalized = tuple(command)
    if not normalized or any(
        not isinstance(argument, str) for argument in normalized
    ):
        raise ValueError("command must contain string arguments")
    return normalized


def _require_positive(name: str, value: float) -> None:
    if not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{name} must be positive")


def _probe_name(index: int) -> str:
    if index == 0:
        return "normal"
    if index == 1:
        return "adversarial"
    return f"probe_{index + 1}"


def _wait_until_ready(
    server: subprocess.Popen[str],
    ready_url: str,
    *,
    timeout_seconds: float,
    heartbeat_seconds: float,
) -> bool:
    started_at = time.monotonic()
    deadline = started_at + timeout_seconds
    next_heartbeat = started_at + heartbeat_seconds
    attempts = 0
    while time.monotonic() < deadline:
        if server.poll() is not None:
            return False
        attempts += 1
        remaining = deadline - time.monotonic()
        try:
            with urlopen(
                ready_url,
                timeout=max(0.01, min(1.0, remaining)),
            ) as response:
                if 200 <= response.status < 300:
                    return True
        except (HTTPError, URLError, TimeoutError, OSError):
            pass

        now = time.monotonic()
        if now >= next_heartbeat:
            print(
                "heartbeat "
                "phase=server_ready "
                f"elapsed={now - started_at:.1f} "
                f"attempts={attempts}",
                file=sys.stderr,
                flush=True,
            )
            next_heartbeat = now + heartbeat_seconds
        time.sleep(min(0.05, max(0.001, deadline - now)))
    return False


def _stop_process_group(
    process: subprocess.Popen[str],
    grace_seconds: float,
) -> tuple[bool, bool]:
    process_group_id = process.pid
    if not _process_group_exists(process_group_id):
        process.poll()
        return False, False
    term_sent = _signal_group(process_group_id, signal.SIGTERM)
    if _wait_for_group_exit(process, grace_seconds):
        return term_sent, False
    kill_sent = _signal_group(process_group_id, signal.SIGKILL)
    process.wait()
    return term_sent, kill_sent


def _signal_group(
    process_group_id: int,
    requested: signal.Signals,
) -> bool:
    try:
        os.killpg(process_group_id, requested)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_for_group_exit(
    process: subprocess.Popen[str],
    timeout_seconds: float,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        process.poll()
        if not _process_group_exists(process.pid):
            return True
        time.sleep(0.01)
    process.poll()
    return not _process_group_exists(process.pid)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the supervised Guide runtime browser matrix."
    )
    parser.add_argument("--timeout-seconds", type=float, default=600)
    parser.add_argument("--heartbeat-seconds", type=float, default=30)
    parser.add_argument("--ready-timeout-seconds", type=float, default=30)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
    )
    return parser


def _default_output_directory() -> Path:
    return Path(tempfile.gettempdir()) / (
        "xiaoro-browser-matrix-"
        f"{os.getpid()}-{secrets.token_hex(8)}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    output_dir = (
        arguments.output_dir
        if arguments.output_dir is not None
        else _default_output_directory()
    )
    try:
        result = run_browser_matrix(
            timeout_seconds=arguments.timeout_seconds,
            heartbeat_seconds=arguments.heartbeat_seconds,
            ready_timeout_seconds=arguments.ready_timeout_seconds,
            output_dir=output_dir,
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        print("browser matrix failed", file=sys.stderr)
        return 1
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
